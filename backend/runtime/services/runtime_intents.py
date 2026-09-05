from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeIdempotencyConflictError,
    RuntimeNotFoundError,
    RuntimeValidationError,
)
from runtime.models import (
    IN_FLIGHT_PROVISIONING_PHASES,
    RuntimeIntent,
    RuntimeIntentOutcome,
    RuntimeIntentType,
    RuntimeOperationState,
    RuntimeOperationTrigger,
    Workspace,
    WorkspaceProvisioningPhase,
)

from .retry import run_with_sqlite_lock_retry
from .runtime_readiness import is_runtime_ready

WORKSPACE_INTENT_LIMIT = 30
WORKSPACE_INTENT_PERIOD_SECONDS = 60
MAX_RECEIVED_AT_FUTURE_SKEW_SECONDS = 5


@dataclass(frozen=True, slots=True)
class RuntimeIntentReceipt:
    status: str
    operation_id: UUID | None = None
    replayed: bool = False


def request_runtime_intent(
    workspace_id: UUID | str,
    intent: str,
    idempotency_key: UUID | str,
    received_at: datetime,
    *,
    now: datetime | None = None,
) -> RuntimeIntentReceipt:
    workspace_uuid = _uuid(workspace_id, "workspace_id")
    key = _uuid(idempotency_key, "idempotency_key")
    if intent != RuntimeIntentType.COMPOSING_STARTED:
        raise RuntimeValidationError("intent is not supported")
    if not isinstance(received_at, datetime) or timezone.is_naive(received_at):
        raise RuntimeValidationError("received_at must include a timezone")
    observed_at = now or timezone.now()
    if timezone.is_naive(observed_at):
        raise RuntimeValidationError("now must include a timezone")
    return run_with_sqlite_lock_retry(
        lambda: _request_runtime_intent_once(
            workspace_uuid, key, received_at, observed_at
        )
    )


@transaction.atomic
def _request_runtime_intent_once(
    workspace_id: UUID,
    idempotency_key: UUID,
    received_at: datetime,
    now: datetime,
) -> RuntimeIntentReceipt:
    workspace = Workspace.objects.select_for_update().filter(pk=workspace_id).first()
    if workspace is None:
        raise RuntimeNotFoundError("workspace is unavailable")

    existing = (
        RuntimeIntent.objects.select_for_update()
        .filter(workspace_id=workspace.id, idempotency_key=idempotency_key)
        .first()
    )
    if existing is not None:
        if existing.intent_type != RuntimeIntentType.COMPOSING_STARTED:
            raise RuntimeIdempotencyConflictError(
                "idempotency key already identifies a different intent"
            )
        return RuntimeIntentReceipt(
            status=existing.outcome,
            operation_id=existing.coalesced_operation_id,
            replayed=True,
        )

    ttl_seconds = getattr(settings, "ALLIES_RUNTIME_INTENT_TTL_SECONDS", 120)
    retention_seconds = getattr(
        settings, "ALLIES_RUNTIME_INTENT_RETENTION_SECONDS", 600
    )
    future_skewed = received_at > now + timedelta(
        seconds=MAX_RECEIVED_AT_FUTURE_SKEW_SECONDS
    )
    if future_skewed:
        received_at = now
    expires_at = received_at + timedelta(seconds=ttl_seconds)
    delete_after = received_at + timedelta(seconds=retention_seconds)

    if future_skewed or now > expires_at:
        return _create_intent(
            workspace,
            idempotency_key,
            received_at,
            expires_at,
            delete_after,
            RuntimeIntentOutcome.FAILED,
            None,
        )

    window_start = now - timedelta(seconds=WORKSPACE_INTENT_PERIOD_SECONDS)
    if (
        RuntimeIntent.objects.filter(
            workspace_id=workspace.id,
            received_at__gte=window_start,
        ).count()
        >= WORKSPACE_INTENT_LIMIT
    ):
        return _create_intent(
            workspace,
            idempotency_key,
            received_at,
            expires_at,
            delete_after,
            RuntimeIntentOutcome.RATE_LIMITED,
            None,
        )

    if is_runtime_ready(workspace, now=now):
        _extend_keep_warm(workspace, now)
        workspace.save(update_fields=["speculative_keep_warm_until", "updated_at"])
        return _create_intent(
            workspace,
            idempotency_key,
            received_at,
            expires_at,
            delete_after,
            RuntimeIntentOutcome.ALREADY_READY,
            None,
        )

    if workspace.provisioning_phase in IN_FLIGHT_PROVISIONING_PHASES:
        return _create_intent(
            workspace,
            idempotency_key,
            received_at,
            expires_at,
            delete_after,
            RuntimeIntentOutcome.FAILED,
            None,
        )

    if not _has_existing_binding(workspace):
        return _create_intent(
            workspace,
            idempotency_key,
            received_at,
            expires_at,
            delete_after,
            RuntimeIntentOutcome.FIRST_PROVISION_REQUIRED,
            None,
        )

    if workspace.runtime_operation_state != RuntimeOperationState.IDLE:
        if workspace.runtime_operation_state == RuntimeOperationState.STOPPING:
            workspace.runtime_operation_id = uuid4()
            workspace.runtime_operation_state = RuntimeOperationState.REQUESTED
            workspace.runtime_operation_trigger = RuntimeOperationTrigger.SPECULATIVE
            workspace.runtime_operation_requested_at = now
            workspace.runtime_operation_retry_count = 0
            workspace.activation_claim_token = None
            workspace.activation_claim_expires_at = None
        operation_id = workspace.runtime_operation_id
        if operation_id is None:
            raise RuntimeConflictError("runtime operation state has no identity")
        _extend_keep_warm(workspace, now)
        workspace.save(
            update_fields=[
                "runtime_operation_id",
                "runtime_operation_state",
                "runtime_operation_trigger",
                "runtime_operation_requested_at",
                "runtime_operation_retry_count",
                "activation_claim_token",
                "activation_claim_expires_at",
                "speculative_keep_warm_until",
                "updated_at",
            ]
        )
        return _create_intent(
            workspace,
            idempotency_key,
            received_at,
            expires_at,
            delete_after,
            RuntimeIntentOutcome.WAKING,
            operation_id,
        )

    cooldown_seconds = getattr(
        settings, "ALLIES_RUNTIME_SPECULATIVE_START_COOLDOWN_SECONDS", 300
    )
    if workspace.last_speculative_start_at is not None and (
        workspace.last_speculative_start_at >= now - timedelta(seconds=cooldown_seconds)
    ):
        return _create_intent(
            workspace,
            idempotency_key,
            received_at,
            expires_at,
            delete_after,
            RuntimeIntentOutcome.RATE_LIMITED,
            None,
        )

    operation_id = uuid4()
    workspace.runtime_operation_id = operation_id
    workspace.runtime_operation_state = RuntimeOperationState.REQUESTED
    workspace.runtime_operation_trigger = RuntimeOperationTrigger.SPECULATIVE
    workspace.runtime_operation_requested_at = now
    workspace.runtime_operation_retry_count = 0
    _extend_keep_warm(workspace, now)
    workspace.save(
        update_fields=[
            "runtime_operation_id",
            "runtime_operation_state",
            "runtime_operation_trigger",
            "runtime_operation_requested_at",
            "runtime_operation_retry_count",
            "speculative_keep_warm_until",
            "updated_at",
        ]
    )
    return _create_intent(
        workspace,
        idempotency_key,
        received_at,
        expires_at,
        delete_after,
        RuntimeIntentOutcome.WAKING,
        operation_id,
    )


def request_execution_wake_locked(
    workspace: Workspace,
    *,
    now: datetime | None = None,
) -> None:
    """Mark an accepted prompt as the authoritative wake trigger.

    The caller already owns the Workspace lock. This function performs no
    provider I/O and intentionally bypasses speculative cooldowns.
    """

    observed_at = now or timezone.now()
    if timezone.is_naive(observed_at):
        raise RuntimeValidationError("now must include a timezone")
    _extend_keep_warm(workspace, observed_at)
    # A queued prompt on an already-ready runtime must not manufacture a
    # power operation.  The execution can claim against the existing receipt
    # and the keep-warm extension is the only durable side effect needed.
    if is_runtime_ready(workspace, now=observed_at):
        workspace.save(update_fields=["speculative_keep_warm_until", "updated_at"])
        return
    state = workspace.runtime_operation_state
    if state == RuntimeOperationState.IDLE:
        # First provisioning remains owned by the normal workspace lifecycle;
        # a prompt cannot create a Machine or a speculative power operation.
        if not _has_existing_binding(workspace):
            workspace.save(update_fields=["speculative_keep_warm_until", "updated_at"])
            return
        workspace.runtime_operation_id = uuid4()
        workspace.runtime_operation_state = RuntimeOperationState.REQUESTED
        workspace.runtime_operation_trigger = RuntimeOperationTrigger.EXECUTION
        workspace.runtime_operation_requested_at = observed_at
        workspace.runtime_operation_retry_count = 0
    elif state == RuntimeOperationState.STOPPING:
        # The stop claim may already have committed before this prompt.  A
        # fresh operation identity invalidates that claim's finalization and
        # lets the next wake-first pass reconcile the recorded Machine.
        workspace.runtime_operation_id = uuid4()
        workspace.runtime_operation_state = RuntimeOperationState.REQUESTED
        workspace.runtime_operation_trigger = RuntimeOperationTrigger.EXECUTION
        workspace.runtime_operation_requested_at = observed_at
        workspace.runtime_operation_retry_count = 0
        workspace.activation_claim_token = None
        workspace.activation_claim_expires_at = None
    elif workspace.runtime_operation_id is None:
        raise RuntimeConflictError("runtime operation state has no identity")
    elif workspace.runtime_operation_trigger != RuntimeOperationTrigger.EXECUTION:
        workspace.runtime_operation_trigger = RuntimeOperationTrigger.EXECUTION
        workspace.runtime_operation_requested_at = observed_at
        workspace.runtime_operation_retry_count = 0
    workspace.save(
        update_fields=[
            "runtime_operation_id",
            "runtime_operation_state",
            "runtime_operation_trigger",
            "runtime_operation_requested_at",
            "runtime_operation_retry_count",
            "activation_claim_token",
            "activation_claim_expires_at",
            "speculative_keep_warm_until",
            "updated_at",
        ]
    )


def request_activation_recovery_wake(
    workspace_id: UUID | str,
    activation_claim_token: str,
    *,
    observed_app_ref: str,
    observed_machine_ref: str,
    observed_volume_ref: str | None,
    observed_owner_workspace_id: UUID | str | None,
    observed_owner_operation_id: UUID | str | None,
    observed_owner_generation: int | None,
    observed_generation: int,
    now: datetime | None = None,
) -> UUID | None:
    """Queue a wake after an activation provider observation.

    Provider inspection happens before this transaction.  Re-read every
    durable identity here so a replacement or another activation cannot turn
    that observation into a start for a different Machine.
    """

    workspace_uuid = _uuid(workspace_id, "workspace_id")
    if not isinstance(activation_claim_token, str) or not activation_claim_token:
        raise RuntimeValidationError("activation_claim_token is required")
    if any(
        not isinstance(value, str) or not value
        for value in (observed_app_ref, observed_machine_ref)
    ):
        raise RuntimeValidationError("observed provider references are required")
    if (
        observed_volume_ref is not None
        and (not isinstance(observed_volume_ref, str) or not observed_volume_ref)
    ):
        raise RuntimeValidationError("observed_volume_ref must be non-empty")
    if (
        isinstance(observed_generation, bool)
        or not isinstance(observed_generation, int)
        or observed_generation <= 0
        or isinstance(observed_owner_generation, bool)
        or (
            observed_owner_generation is not None
            and (
                not isinstance(observed_owner_generation, int)
                or observed_owner_generation <= 0
            )
        )
    ):
        raise RuntimeValidationError("observed generation must be positive")
    if now is not None and timezone.is_naive(now):
        raise RuntimeValidationError("now must include a timezone")
    return run_with_sqlite_lock_retry(
        lambda: _request_activation_recovery_wake_once(
            workspace_uuid,
            activation_claim_token,
            observed_app_ref=observed_app_ref,
            observed_machine_ref=observed_machine_ref,
            observed_volume_ref=observed_volume_ref,
            observed_owner_workspace_id=observed_owner_workspace_id,
            observed_owner_operation_id=observed_owner_operation_id,
            observed_owner_generation=observed_owner_generation,
            observed_generation=observed_generation,
            observed_at=now,
        )
    )


@transaction.atomic
def _request_activation_recovery_wake_once(
    workspace_id: UUID,
    activation_claim_token: str,
    *,
    observed_app_ref: str,
    observed_machine_ref: str,
    observed_volume_ref: str | None,
    observed_owner_workspace_id: UUID | str | None,
    observed_owner_operation_id: UUID | str | None,
    observed_owner_generation: int | None,
    observed_generation: int,
    observed_at: datetime | None,
) -> UUID | None:
    workspace = Workspace.objects.select_for_update().filter(pk=workspace_id).first()
    if workspace is None:
        raise RuntimeNotFoundError("workspace is unavailable")
    observed_at = observed_at or timezone.now()
    if (
        workspace.activation_claim_token != activation_claim_token
        or workspace.activation_claim_expires_at is None
        or workspace.activation_claim_expires_at <= observed_at
    ):
        raise RuntimeConflictError("workspace activation claim is stale")
    if workspace.provisioning_phase != WorkspaceProvisioningPhase.IDLE:
        raise RuntimeConflictError("workspace provisioning state changed")
    if workspace.runtime_operation_state in {
        RuntimeOperationState.STARTING,
        RuntimeOperationState.AWAITING_READINESS,
    }:
        raise RuntimeConflictError("runtime wake is already in progress")
    if (
        workspace.machine_generation != observed_generation
        or workspace.fly_app_ref != observed_app_ref
        or workspace.machine_ref != observed_machine_ref
        or workspace.volume_ref != observed_volume_ref
        or workspace.provisioning_id is None
        or observed_volume_ref is None
        or observed_owner_workspace_id is None
        or str(observed_owner_workspace_id) != str(workspace.id)
        or observed_owner_operation_id is None
        or str(observed_owner_operation_id) != str(workspace.provisioning_id)
        or observed_owner_generation != workspace.machine_generation
        or observed_owner_generation != observed_generation
    ):
        raise RuntimeConflictError("workspace provider binding changed")

    workspace.ready_generation = None
    workspace.ready_start_epoch = None
    workspace.ready_boot_id = None
    workspace.ready_at = None
    workspace.runtime_last_seen_at = None
    request_execution_wake_locked(workspace, now=observed_at)
    workspace.save(
        update_fields=[
            "ready_generation",
            "ready_start_epoch",
            "ready_boot_id",
            "ready_at",
            "runtime_last_seen_at",
            "updated_at",
        ]
    )
    return workspace.runtime_operation_id


def cleanup_runtime_intents(*, now: datetime | None = None, limit: int = 500) -> int:
    observed_at = now or timezone.now()
    ids = list(
        RuntimeIntent.objects.filter(delete_after__lte=observed_at)
        .order_by("delete_after", "id")
        .values_list("id", flat=True)[:limit]
    )
    if not ids:
        return 0
    return RuntimeIntent.objects.filter(id__in=ids).delete()[0]


def _create_intent(
    workspace: Workspace,
    idempotency_key: UUID,
    received_at: datetime,
    expires_at: datetime,
    delete_after: datetime,
    outcome: str,
    operation_id: UUID | None,
) -> RuntimeIntentReceipt:
    try:
        RuntimeIntent.objects.create(
            workspace=workspace,
            idempotency_key=idempotency_key,
            intent_type=RuntimeIntentType.COMPOSING_STARTED,
            received_at=received_at,
            expires_at=expires_at,
            delete_after=delete_after,
            outcome=outcome,
            coalesced_operation_id=operation_id,
        )
    except IntegrityError as exc:
        raise RuntimeConflictError("runtime intent identity conflicts") from exc
    return RuntimeIntentReceipt(status=outcome, operation_id=operation_id)


def _has_existing_binding(workspace: Workspace) -> bool:
    return bool(
        workspace.machine_generation > 0
        and workspace.fly_app_ref
        and workspace.volume_ref
        and workspace.machine_ref
    )


def _extend_keep_warm(workspace: Workspace, now: datetime) -> None:
    seconds = getattr(settings, "ALLIES_RUNTIME_KEEP_WARM_SECONDS", 600)
    deadline = now + timedelta(seconds=seconds)
    if workspace.speculative_keep_warm_until is None or (
        workspace.speculative_keep_warm_until < deadline
    ):
        workspace.speculative_keep_warm_until = deadline


def _uuid(value: UUID | str, name: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError(f"{name} must be a UUID") from exc


__all__ = [
    "RuntimeIntentReceipt",
    "cleanup_runtime_intents",
    "request_activation_recovery_wake",
    "request_execution_wake_locked",
    "request_runtime_intent",
]
