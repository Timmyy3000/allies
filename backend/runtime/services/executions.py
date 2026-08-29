from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import IntegrityError, transaction

from runtime.contracts import (
    ExecutionCommand,
    ExecutionReceipt,
    ReconciliationReceipt,
    validate_command,
    validate_fingerprint,
)
from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeNotFoundError,
    RuntimeValidationError,
)
from runtime.models import ConversationBinding, Execution, RuntimeProfile, Workspace

from .retry import run_with_sqlite_lock_retry
from .validation import (
    MAX_EXECUTION_PAYLOAD_BYTES,
    digest_payload,
    validate_nonempty,
    validate_object_payload,
)

_PROFILE_ID_NAMESPACE = uuid5(NAMESPACE_URL, "allies-foundry-profile-v1")


def create_execution(
    workspace_id: UUID,
    profile_id: UUID,
    idempotency_key: str,
    input_payload: dict,
) -> Execution:
    """Create one workspace-scoped execution, safely replaying exact retries."""

    validate_nonempty(idempotency_key, "idempotency_key", max_length=255)
    payload = validate_object_payload(
        input_payload,
        max_bytes=MAX_EXECUTION_PAYLOAD_BYTES,
    )
    payload_digest = digest_payload(payload)
    try:
        profile = RuntimeProfile.objects.select_related("workspace").get(pk=profile_id)
    except RuntimeProfile.DoesNotExist as exc:
        raise RuntimeValidationError("profile does not exist") from exc
    if profile.workspace_id != workspace_id:
        raise RuntimeValidationError("profile does not belong to workspace")
    return run_with_sqlite_lock_retry(
        lambda: _create_execution_once(
            workspace_id,
            profile_id,
            idempotency_key,
            payload,
            payload_digest,
        )
    )


def create_execution_intent(command: ExecutionCommand) -> ExecutionReceipt:
    """Accept one Cloud command and return a privacy-safe durable receipt."""

    command = _coerce_command(command)
    validate_command(command)
    workspace, profile = _resolve_command_binding(command)
    execution, created = run_with_sqlite_lock_retry(
        lambda: _create_contract_execution_once(command, workspace.id, profile.id)
    )
    return ExecutionReceipt(
        schema_version="v1",
        kind="execution.receipt",
        status="accepted" if created is True else "duplicate",
        command_id=execution.command_id or command.command_id,
        idempotency_key=command.idempotency_key,
        fingerprint=execution.command_fingerprint or command.fingerprint,
    )


def reconcile_execution_intent(
    idempotency_key: UUID | str,
    fingerprint: str,
) -> ReconciliationReceipt:
    """Look up a command without creating work or exposing runtime IDs."""

    try:
        key = UUID(str(idempotency_key))
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError("idempotency_key must be a UUID") from exc
    validate_fingerprint(fingerprint)
    executions = list(
        Execution.objects.filter(idempotency_key=str(key)).order_by("created_at", "id")
    )
    status = "not_found"
    command_id = None
    if len(executions) != 0:
        status = "conflict"
    if len(executions) == 1 and executions[0].command_fingerprint == fingerprint:
        status = "accepted"
        command_id = executions[0].command_id
    return ReconciliationReceipt(
        schema_version="v1",
        kind="execution.reconciliation",
        status=status,
        idempotency_key=key,
        fingerprint=fingerprint,
        command_id=command_id,
    )


def _coerce_command(command: ExecutionCommand) -> ExecutionCommand:
    if isinstance(command, ExecutionCommand):
        return command
    try:
        return ExecutionCommand.model_validate(command)
    except ValueError as exc:
        raise RuntimeValidationError("command is invalid") from exc


def _resolve_command_binding(
    command: ExecutionCommand,
) -> tuple[Workspace, RuntimeProfile]:
    workspace = Workspace.objects.filter(
        tenant_ref=str(command.scope.cloud_workspace_id),
    ).first()
    if workspace is None:
        raise RuntimeNotFoundError("execution binding is unavailable")
    profile_id = uuid5(_PROFILE_ID_NAMESPACE, str(command.cloud.cloud_binding_id))
    profile = RuntimeProfile.objects.filter(
        pk=profile_id,
        workspace_id=workspace.id,
        ally_ref=str(command.cloud.ally_id),
    ).first()
    if profile is None:
        raise RuntimeNotFoundError("execution binding is unavailable")
    binding = ConversationBinding.objects.filter(profile_id=profile.id).first()
    if binding is not None and binding.cloud_conversation_ref != str(
        command.cloud.conversation_id
    ):
        raise RuntimeNotFoundError("execution binding is unavailable")
    return workspace, profile


@transaction.atomic
def _create_contract_execution_once(
    command: ExecutionCommand,
    workspace_id: UUID,
    profile_id: UUID,
) -> tuple[Execution, bool]:
    workspace = Workspace.objects.select_for_update().get(pk=workspace_id)
    profile = RuntimeProfile.objects.select_for_update().get(
        pk=profile_id, workspace_id=workspace.id
    )
    if profile.ally_ref != str(command.cloud.ally_id):
        raise RuntimeNotFoundError("execution binding is unavailable")
    _ensure_conversation_binding(
        profile,
        str(command.cloud.conversation_id),
        mismatch_error=RuntimeNotFoundError,
    )
    existing = (
        Execution.objects.select_for_update()
        .filter(workspace_id=workspace.id, idempotency_key=str(command.idempotency_key))
        .first()
    )
    if existing is not None:
        _ensure_contract_replay(existing, command, profile_id)
        return existing, False
    existing_command = Execution.objects.filter(command_id=command.command_id).first()
    if existing_command is not None:
        raise RuntimeConflictError(
            "command identity already identifies another execution"
        )
    payload = {
        "message": command.payload.text,
        "cloud_conversation_ref": str(command.cloud.conversation_id),
    }
    try:
        execution = Execution.objects.create(
            workspace=workspace,
            profile=profile,
            idempotency_key=str(command.idempotency_key),
            input_payload=payload,
            payload_digest=digest_payload(payload),
            command_id=command.command_id,
            command_fingerprint=command.fingerprint,
            cloud_workspace_id=command.scope.cloud_workspace_id,
            cloud_ally_id=command.cloud.ally_id,
            cloud_conversation_id=command.cloud.conversation_id,
            cloud_message_id=command.cloud.message_id,
            cloud_binding_id=command.cloud.cloud_binding_id,
            conversation_turn_ordinal=command.conversation_turn_ordinal,
            source_kind=command.source_kind,
        )
    except IntegrityError as exc:
        raise RuntimeConflictError(
            "execution identity conflicts with existing state"
        ) from exc
    return execution, True


def _ensure_contract_replay(
    existing: Execution,
    command: ExecutionCommand,
    profile_id: UUID,
) -> None:
    if (
        existing.profile_id != profile_id
        or existing.command_id != command.command_id
        or existing.command_fingerprint != command.fingerprint
        or existing.cloud_workspace_id != command.scope.cloud_workspace_id
        or existing.cloud_ally_id != command.cloud.ally_id
        or existing.cloud_conversation_id != command.cloud.conversation_id
        or existing.cloud_message_id != command.cloud.message_id
        or existing.cloud_binding_id != command.cloud.cloud_binding_id
        or existing.conversation_turn_ordinal != command.conversation_turn_ordinal
    ):
        raise RuntimeConflictError(
            "idempotency key already identifies a different execution"
        )


@transaction.atomic
def _create_execution_once(
    workspace_id: UUID,
    profile_id: UUID,
    idempotency_key: str,
    payload: dict,
    payload_digest: str,
) -> Execution:
    workspace = Workspace.objects.select_for_update().get(pk=workspace_id)
    profile = RuntimeProfile.objects.select_for_update().get(
        pk=profile_id, workspace_id=workspace.id
    )
    conversation_ref = payload.get("cloud_conversation_ref")
    if conversation_ref is not None:
        validate_nonempty(
            conversation_ref,
            "cloud_conversation_ref",
            max_length=255,
        )
        _ensure_conversation_binding(profile, conversation_ref)
    try:
        with transaction.atomic():
            return Execution.objects.create(
                workspace_id=workspace_id,
                profile_id=profile_id,
                idempotency_key=idempotency_key,
                input_payload=payload,
                payload_digest=payload_digest,
            )
    except IntegrityError:
        # Another transaction won the unique workspace/key race. Re-read it
        # under the outer transaction and apply the same exact-retry rule.
        existing = (
            Execution.objects.select_for_update()
            .filter(workspace_id=workspace_id, idempotency_key=idempotency_key)
            .first()
        )
        if existing is None:
            raise
        _ensure_exact_retry(existing, profile_id, payload_digest)
        return existing


def _ensure_conversation_binding(
    profile: RuntimeProfile,
    cloud_conversation_ref: str,
    *,
    mismatch_error: type[RuntimeConflictError] = RuntimeConflictError,
) -> ConversationBinding:
    """Reserve one profile conversation while its row is already locked."""

    validate_nonempty(
        cloud_conversation_ref,
        "cloud_conversation_ref",
        max_length=255,
    )
    binding = (
        ConversationBinding.objects.select_for_update()
        .filter(profile_id=profile.id)
        .first()
    )
    if binding is not None:
        if binding.cloud_conversation_ref != cloud_conversation_ref:
            raise mismatch_error("execution binding is unavailable")
        return binding
    try:
        with transaction.atomic():
            return ConversationBinding.objects.create(
                profile=profile,
                cloud_conversation_ref=cloud_conversation_ref,
                hermes_session_id=None,
            )
    except IntegrityError as exc:
        # On PostgreSQL the profile lock serializes this path.  SQLite's
        # select_for_update is a no-op, so two first executions can race on
        # the OneToOne insert.  Re-read after the savepoint before deciding
        # whether the winner reserved the same conversation or a conflict.
        binding = (
            ConversationBinding.objects.select_for_update()
            .filter(profile_id=profile.id)
            .first()
        )
        if (
            binding is not None
            and binding.cloud_conversation_ref == cloud_conversation_ref
        ):
            return binding
        raise mismatch_error(
            "conversation binding conflicts with existing state"
        ) from exc


def _ensure_exact_retry(
    existing: Execution,
    profile_id: UUID,
    payload_digest: str,
) -> None:
    if (
        existing.profile_id != profile_id
        or _stored_payload_digest(existing) != payload_digest
    ):
        raise RuntimeConflictError(
            "idempotency key already identifies a different execution"
        )


def _stored_payload_digest(existing: Execution) -> str:
    if existing.payload_digest:
        return existing.payload_digest
    digest = digest_payload(existing.input_payload)
    existing.payload_digest = digest
    existing.save(update_fields=["payload_digest"])
    return digest
