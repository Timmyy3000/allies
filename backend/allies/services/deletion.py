"""Confirmed Ally deletion, admission fencing, and bounded Cloud purge."""

from __future__ import annotations

import hmac
import re
import uuid
from datetime import timedelta
from uuid import UUID

from django.db import connection, transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from allies.exceptions import (
    DeletionConflict,
    DeletionInvalid,
    DeletionUnavailable,
    FoundryGatewayConflict,
    FoundryGatewayInvalid,
    FoundryGatewayRejected,
    FoundryGatewayRetryable,
    FoundryGatewayUnknownOutcome,
)
from allies.gateways.foundry import (
    ProfileDeletionReceipt,
    ProfileDeletionRequest,
    request_profile_deletion,
    resume_profile_deletion,
)
from allies.models import (
    Ally,
    AllyBinding,
    AllyDeletionMarker,
    AllyDeletionState,
    DeletionOperation,
    DeletionOperationState,
    DeletionStage,
)
from auths.models import User
from common.uuids import canonical_uuid
from files.models import (
    FileAllyTombstone,
    FileIOOutcome,
    FileStagingObject,
    FileState,
    FileStorageAccount,
    FileVersion,
)
from files.services.cleanup import (
    _tombstone_ally_files_locked,
    cleanup_files,
    record_foundry_cleanup_receipt,
)
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability

DELETION_LEASE_SECONDS = 60
DELETION_BATCH_SIZE = 100
DELETION_MAX_BACKOFF_SECONDS = 300
DELETION_OPERATION_TTL = timedelta(hours=24)
_SAFE_CODE = re.compile(r"^(?:[a-z][a-z0-9_]*)?$")


class DeletionResult:
    """Small response-compatible object for an operation or terminal marker."""

    def __init__(
        self,
        *,
        ally_id: UUID,
        state: str,
        operation_id: UUID | None = None,
        retryable: bool = True,
        safe_error_code: str = "",
    ):
        self.ally_id = ally_id
        self.state = state
        self.operation_id = operation_id
        self.retryable = retryable
        self.safe_error_code = safe_error_code


def _terminal_result(*, ally_id: UUID) -> DeletionResult:
    return DeletionResult(
        ally_id=ally_id,
        state=DeletionOperationState.COMPLETE,
        retryable=False,
    )


def deletion_response(value: DeletionOperation | DeletionResult) -> dict[str, object]:
    """Return the public, content-free operation shape."""

    state = str(value.state)
    operation_id = getattr(value, "operation_id", None)
    if operation_id is None and isinstance(value, DeletionOperation):
        operation_id = value.pk
    payload: dict[str, object] = {
        "ally_id": str(value.ally_id),
        "state": state,
        "retryable": state != DeletionOperationState.COMPLETE,
        "safe_error_code": (
            value.safe_error_code if state != DeletionOperationState.COMPLETE else ""
        ),
    }
    if state != DeletionOperationState.COMPLETE and operation_id is not None:
        payload["operation_id"] = str(operation_id)
    return payload


def _parse_ally_id(value: UUID | str) -> UUID:
    try:
        return canonical_uuid(value)
    except (TypeError, ValueError) as exc:
        raise DeletionUnavailable("ally unavailable") from exc


def _owner_context(*, user: User, workspace_id, capability: Capability):
    context = require_workspace_capability(
        user=user, workspace_id=workspace_id, capability=capability
    )
    if context.workspace.owner_id != user.id:
        raise DeletionUnavailable("ally unavailable")
    return context


def _valid_confirmation(value: object, *, name: str) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise DeletionInvalid("confirmation is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise DeletionInvalid("confirmation is invalid")
    expected = f"{name} - deletes me"
    return hmac.compare_digest(value.encode("utf-8"), expected.encode("utf-8"))


def _account_locked(workspace_id) -> FileStorageAccount:
    FileStorageAccount.objects.get_or_create(workspace_id=workspace_id)
    return FileStorageAccount.objects.select_for_update().get(workspace_id=workspace_id)


def _enqueue_reconciliation(operation_id: UUID) -> None:
    try:
        from allies.tasks import reconcile_ally_deletion_task

        reconcile_ally_deletion_task.delay(str(operation_id))
    except Exception:  # noqa: BLE001 - the due scan is the durable fallback.
        return


def _operation_for_scope(*, workspace_id, ally_id, lock: bool = False):
    query = DeletionOperation.objects
    if lock:
        query = query.select_for_update()
    return query.filter(workspace_id=workspace_id, ally_id=ally_id).first()


def request_ally_deletion(
    *,
    user: User,
    workspace_id: UUID | str,
    ally_id: UUID | str,
    confirmation: str,
) -> DeletionOperation | DeletionResult:
    """Fence one Ally and enqueue its deletion after exact confirmation."""

    context = _owner_context(
        user=user, workspace_id=workspace_id, capability=Capability.PROFILE_WRITE
    )
    parsed_ally_id = _parse_ally_id(ally_id)
    marker = AllyDeletionMarker.objects.filter(
        workspace=context.workspace, ally_id=parsed_ally_id
    ).first()
    if marker is not None:
        return _terminal_result(ally_id=parsed_ally_id)

    with transaction.atomic():
        # Keep the established storage-account -> Ally -> conversation order.
        account = _account_locked(context.workspace.id)
        if AllyDeletionMarker.objects.filter(
            workspace=context.workspace, ally_id=parsed_ally_id
        ).exists():
            return _terminal_result(ally_id=parsed_ally_id)
        ally = (
            Ally.objects.select_for_update()
            .filter(pk=parsed_ally_id, workspace=context.workspace)
            .first()
        )
        if ally is None:
            raise DeletionUnavailable("ally unavailable")
        if not _valid_confirmation(confirmation, name=ally.name):
            raise DeletionConflict("confirmation does not match current Ally name")
        existing = _operation_for_scope(
            workspace_id=context.workspace.id, ally_id=ally.id, lock=True
        )
        if existing is not None:
            return existing
        try:
            binding = AllyBinding.objects.only("id").get(ally=ally)
        except AllyBinding.DoesNotExist as exc:
            raise DeletionUnavailable("ally binding unavailable") from exc
        _tombstone_ally_files_locked(ally=ally, account=account, now=timezone.now())
        ally.deletion_state = AllyDeletionState.PENDING
        ally.label_generation_state = "unavailable"
        ally.save(
            update_fields=(
                "deletion_state",
                "label_generation_state",
                "updated_at",
            )
        )
        operation = DeletionOperation.objects.create(
            workspace=context.workspace,
            ally_id=ally.id,
            binding_id=binding.id,
            state=DeletionOperationState.PENDING,
            stage=DeletionStage.FOUNDRY,
            next_attempt_at=timezone.now(),
            expires_at=timezone.now() + DELETION_OPERATION_TTL,
        )
        transaction.on_commit(lambda: _enqueue_reconciliation(operation.id))
        return operation


def get_ally_deletion(
    *, user: User, workspace_id: UUID | str, ally_id: UUID | str
) -> DeletionOperation | DeletionResult:
    """Read current deletion progress or the scoped terminal marker."""

    context = _owner_context(
        user=user, workspace_id=workspace_id, capability=Capability.PROFILE_READ
    )
    parsed_ally_id = _parse_ally_id(ally_id)
    marker = AllyDeletionMarker.objects.filter(
        workspace=context.workspace, ally_id=parsed_ally_id
    ).first()
    if marker is not None:
        return _terminal_result(ally_id=parsed_ally_id)
    operation = _operation_for_scope(
        workspace_id=context.workspace.id, ally_id=parsed_ally_id
    )
    if operation is not None:
        return operation
    raise DeletionUnavailable("deletion unavailable")


def _claim_due(*, now, limit: int) -> list[tuple[UUID, int]]:
    limit = max(1, min(int(limit), DELETION_BATCH_SIZE))
    expired_ids = tuple(
        DeletionOperation.objects.filter(
            state=DeletionOperationState.PENDING, expires_at__lte=now
        )
        .order_by("expires_at", "id")
        .values_list("pk", flat=True)[:limit]
    )
    for operation_id in expired_ids:
        with transaction.atomic():
            identity = (
                DeletionOperation.objects.filter(pk=operation_id)
                .values("workspace_id", "ally_id")
                .first()
            )
            if identity is None:
                continue
            _account_locked(identity["workspace_id"])
            ally = (
                Ally.objects.select_for_update()
                .filter(pk=identity["ally_id"], workspace_id=identity["workspace_id"])
                .first()
            )
            operation = (
                DeletionOperation.objects.select_for_update()
                .filter(
                    pk=operation_id,
                    state=DeletionOperationState.PENDING,
                    expires_at__lte=now,
                )
                .first()
            )
            if operation is None:
                continue
            operation.state = DeletionOperationState.REPAIR_REQUIRED
            operation.safe_error_code = "retry_expired"
            operation.lease_expires_at = None
            operation.updated_at = now
            operation.save(
                update_fields=(
                    "state",
                    "safe_error_code",
                    "lease_expires_at",
                    "updated_at",
                )
            )
            if ally is not None and ally.deletion_state == AllyDeletionState.PENDING:
                ally.deletion_state = AllyDeletionState.REPAIR_REQUIRED
                ally.updated_at = now
                ally.save(update_fields=("deletion_state", "updated_at"))
    due = DeletionOperation.objects.filter(
        state=DeletionOperationState.PENDING,
        next_attempt_at__lte=now,
        expires_at__gt=now,
    ).filter(Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now))
    with transaction.atomic():
        due = due.select_for_update(
            skip_locked=connection.features.has_select_for_update_skip_locked
        )
        claimed: list[tuple[UUID, int]] = []
        lease_until = now + timedelta(seconds=DELETION_LEASE_SECONDS)
        for operation in due.order_by("next_attempt_at", "id")[:limit]:
            operation.attempt_count += 1
            operation.last_attempt_at = now
            operation.lease_expires_at = lease_until
            operation.save(
                update_fields=(
                    "attempt_count",
                    "last_attempt_at",
                    "lease_expires_at",
                    "updated_at",
                )
            )
            claimed.append((operation.pk, operation.attempt_count))
        return claimed


def _backoff(attempt: int) -> int:
    return min(DELETION_MAX_BACKOFF_SECONDS, 5 * 2 ** min(max(attempt - 1, 0), 6))


def _mark_pending(*, operation_id: UUID, attempt: int, code: str, now) -> bool:
    if not _SAFE_CODE.fullmatch(code):
        code = "deletion_unavailable"
    return bool(
        DeletionOperation.objects.filter(
            pk=operation_id,
            state=DeletionOperationState.PENDING,
            attempt_count=attempt,
        ).update(
            next_attempt_at=now + timedelta(seconds=_backoff(attempt)),
            lease_expires_at=None,
            safe_error_code=code,
            updated_at=now,
        )
    )


def _mark_repair(*, operation_id: UUID, attempt: int, code: str, now) -> bool:
    if not _SAFE_CODE.fullmatch(code):
        code = "deletion_repair_required"
    identity = (
        DeletionOperation.objects.filter(pk=operation_id)
        .values("workspace_id", "ally_id")
        .first()
    )
    if identity is None:
        return False
    with transaction.atomic():
        _account_locked(identity["workspace_id"])
        ally = (
            Ally.objects.select_for_update()
            .filter(pk=identity["ally_id"], workspace_id=identity["workspace_id"])
            .first()
        )
        operation = (
            DeletionOperation.objects.select_for_update()
            .filter(
                pk=operation_id,
                state=DeletionOperationState.PENDING,
                attempt_count=attempt,
            )
            .first()
        )
        if operation is None:
            return False
        operation.state = DeletionOperationState.REPAIR_REQUIRED
        operation.lease_expires_at = None
        operation.safe_error_code = code
        operation.updated_at = now
        operation.save(
            update_fields=(
                "state",
                "lease_expires_at",
                "safe_error_code",
                "updated_at",
            )
        )
        if ally is not None and ally.deletion_state == AllyDeletionState.PENDING:
            ally.deletion_state = AllyDeletionState.REPAIR_REQUIRED
            ally.updated_at = now
            ally.save(update_fields=("deletion_state", "updated_at"))
        return True


def _store_foundry_receipt(
    *, operation_id: UUID, attempt: int, receipt: ProfileDeletionReceipt, now
) -> bool:
    if (
        receipt.version != 1
        or receipt.binding_id
        != str(
            DeletionOperation.objects.filter(pk=operation_id)
            .values_list("binding_id", flat=True)
            .first()
        )
        or receipt.operation_id != str(operation_id)
    ):
        _mark_repair(
            operation_id=operation_id,
            attempt=attempt,
            code="foundry_receipt_identity_mismatch",
            now=now,
        )
        return False
    values = {
        "foundry_state": receipt.state,
        "foundry_attempt_id": receipt.attempt_id,
        "foundry_receipt_id": receipt.receipt_id or "",
        "safe_error_code": receipt.safe_error_code or "",
        "updated_at": now,
    }
    return bool(
        DeletionOperation.objects.filter(
            pk=operation_id,
            state=DeletionOperationState.PENDING,
            attempt_count=attempt,
        ).update(**values)
    )


def _file_cleanup_ready(*, ally_id: UUID) -> tuple[bool, str, bool]:
    active_candidates = FileStagingObject.objects.filter(
        file__ally_id=ally_id, deleted_at__isnull=True
    )
    if active_candidates.exists():
        if active_candidates.filter(
            io_outcome__in=(FileIOOutcome.IN_FLIGHT, FileIOOutcome.AMBIGUOUS)
        ).exists():
            return False, "storage_io_ambiguous", True
        if active_candidates.filter(cleanup_attempts__gte=5).exists():
            return False, "storage_retry_exhausted", True
        return False, "storage_cleanup_pending", False
    files = FileVersion.objects.filter(ally_id=ally_id)
    if files.exclude(state=FileState.DELETED, object_key="").exists():
        return False, "storage_cleanup_pending", False
    if files.filter(Q(reserved_accounted=True) | Q(retained_accounted=True)).exists():
        return False, "storage_accounting_pending", False
    return True, "", False


def _purge_cloud_graph(*, operation_id: UUID, now) -> DeletionOperation:
    from activities.models import (
        Activity,
        Approval,
        FoundryEventReceipt,
        RoutineResultContext,
        RoutineResultProjection,
        RoutineResultReceipt,
    )
    from chat.models import (
        AssistantReply,
        Conversation,
        DispatchOutbox,
        Message,
    )
    from files.models import (
        FileDraftFile,
        FileDraftRecovery,
        FilePublication,
        MessageFile,
    )
    from routines.models import (
        Routine,
        RoutineApprovalCommand,
        RoutineApprovalProjection,
        RoutineDeletionConfirmation,
        RoutineDispatchOutbox,
        RoutineManagementReceipt,
        RoutineOccurrence,
        RoutineRunSnapshot,
        RoutineToolCall,
    )

    identity = (
        DeletionOperation.objects.filter(pk=operation_id)
        .values("workspace_id", "ally_id")
        .first()
    )
    if identity is None:
        raise DeletionUnavailable("deletion unavailable")
    with transaction.atomic():
        # Match acceptance's account -> Ally -> operation lock order.
        _account_locked(identity["workspace_id"])
        ally = Ally.objects.select_for_update().get(
            pk=identity["ally_id"], workspace_id=identity["workspace_id"]
        )
        operation = DeletionOperation.objects.select_for_update().get(
            pk=operation_id,
            workspace_id=identity["workspace_id"],
            ally_id=identity["ally_id"],
        )
        if operation.state != DeletionOperationState.PENDING:
            return operation
        if ally.deletion_state == AllyDeletionState.ACTIVE:
            raise DeletionConflict("ally deletion fence is missing")
        list(
            Conversation.objects.select_for_update()
            .filter(ally_id=ally.id)
            .order_by("id")
        )
        tombstone = FileAllyTombstone.objects.select_for_update().get(ally=ally)
        if not tombstone.foundry_cleanup_receipt:
            raise DeletionConflict("foundry cleanup receipt is missing")

        RoutineApprovalCommand.objects.filter(approval__ally_id=ally.id).delete()
        RoutineApprovalProjection.objects.filter(ally_id=ally.id).delete()
        RoutineResultReceipt.objects.filter(result__ally_id=ally.id).delete()
        RoutineResultContext.objects.filter(result__ally_id=ally.id).delete()
        RoutineResultProjection.objects.filter(ally_id=ally.id).delete()
        RoutineDispatchOutbox.objects.filter(routine__ally_id=ally.id).delete()
        RoutineManagementReceipt.objects.filter(ally_id=ally.id).delete()
        RoutineDeletionConfirmation.objects.filter(ally_id=ally.id).delete()
        RoutineRunSnapshot.objects.filter(ally_id=ally.id).delete()
        RoutineOccurrence.objects.filter(ally_id=ally.id).delete()
        Routine.objects.filter(ally_id=ally.id).delete()

        FileDraftFile.objects.filter(draft__ally_id=ally.id).delete()
        MessageFile.objects.filter(file__ally_id=ally.id).delete()
        FileDraftRecovery.objects.filter(ally_id=ally.id).delete()
        publications = FilePublication.objects.filter(
            Q(binding__ally_id=ally.id)
            | Q(source_message__conversation__ally_id=ally.id)
        )
        if (
            FileVersion.objects.filter(publication__in=publications)
            .exclude(ally_id=ally.id)
            .exists()
        ):
            raise DeletionConflict("publication graph crosses Ally scope")
        FileVersion.objects.filter(publication__in=publications).update(
            publication=None
        )
        publications.delete()
        FileVersion.objects.filter(ally_id=ally.id).delete()

        RoutineToolCall.objects.filter(message__conversation__ally_id=ally.id).delete()
        AssistantReply.objects.filter(message__conversation__ally_id=ally.id).delete()
        DispatchOutbox.objects.filter(message__conversation__ally_id=ally.id).delete()
        Activity.objects.filter(conversation__ally_id=ally.id).delete()
        FoundryEventReceipt.objects.filter(conversation__ally_id=ally.id).delete()
        Approval.objects.filter(ally_id=ally.id).delete()
        Message.objects.filter(conversation__ally_id=ally.id).delete()
        Conversation.objects.filter(ally_id=ally.id).delete()

        FileAllyTombstone.objects.filter(ally_id=ally.id).delete()
        from allies.models import OnboardingAttempt, ProvisioningOperation

        ProvisioningOperation.objects.filter(binding_id=operation.binding_id).delete()
        OnboardingAttempt.objects.filter(ally_id=ally.id).delete()
        AllyBinding.objects.filter(pk=operation.binding_id, ally_id=ally.id).delete()
        AllyDeletionMarker.objects.get_or_create(
            workspace_id=operation.workspace_id,
            ally_id=operation.ally_id,
        )
        ally.delete()
        operation.state = DeletionOperationState.COMPLETE
        operation.completed_at = now
        operation.lease_expires_at = None
        operation.safe_error_code = ""
        operation.save(
            update_fields=(
                "state",
                "completed_at",
                "lease_expires_at",
                "safe_error_code",
            )
        )
        result = DeletionOperation(
            id=operation.id,
            workspace_id=operation.workspace_id,
            ally_id=operation.ally_id,
            binding_id=operation.binding_id,
            state=DeletionOperationState.COMPLETE,
            stage=DeletionStage.PURGE,
            completed_at=now,
        )
        operation.delete()
        return result


def _reconcile_claimed(
    operation_id: UUID, attempt: int
) -> DeletionOperation | DeletionResult:
    now = timezone.now()
    operation = DeletionOperation.objects.select_related("workspace").get(
        pk=operation_id
    )
    if operation.state == DeletionOperationState.REPAIR_REQUIRED:
        return operation
    if operation.expires_at <= now:
        _mark_repair(
            operation_id=operation_id, attempt=attempt, code="retry_expired", now=now
        )
        operation.state = DeletionOperationState.REPAIR_REQUIRED
        operation.safe_error_code = "retry_expired"
        return operation

    if operation.stage == DeletionStage.FOUNDRY:
        payload = ProfileDeletionRequest(
            workspace_id=str(operation.workspace_id),
            ally_id=str(operation.ally_id),
            binding_id=str(operation.binding_id),
            operation_id=str(operation.id),
        )
        try:
            if operation.foundry_resume_attempt_id is not None:
                receipt = resume_profile_deletion(
                    payload=payload,
                    expected_attempt_id=operation.foundry_resume_attempt_id,
                )
            else:
                receipt = request_profile_deletion(payload)
        except FoundryGatewayUnknownOutcome:
            _mark_pending(
                operation_id=operation_id,
                attempt=attempt,
                code="foundry_outcome_unknown",
                now=timezone.now(),
            )
            return operation
        except FoundryGatewayRetryable:
            _mark_pending(
                operation_id=operation_id,
                attempt=attempt,
                code="foundry_unavailable",
                now=timezone.now(),
            )
            return operation
        except (FoundryGatewayConflict, FoundryGatewayInvalid, FoundryGatewayRejected):
            _mark_repair(
                operation_id=operation_id,
                attempt=attempt,
                code="foundry_rejected",
                now=timezone.now(),
            )
            return operation
        now = timezone.now()
        if now >= operation.expires_at:
            _mark_repair(
                operation_id=operation_id,
                attempt=attempt,
                code="retry_expired",
                now=now,
            )
            return operation
        if not _store_foundry_receipt(
            operation_id=operation_id, attempt=attempt, receipt=receipt, now=now
        ):
            return operation
        if receipt.state == "pending":
            if operation.foundry_resume_attempt_id is not None:
                DeletionOperation.objects.filter(
                    pk=operation_id,
                    state=DeletionOperationState.PENDING,
                    attempt_count=attempt,
                ).update(
                    foundry_resume_attempt_id=receipt.attempt_id
                    or operation.foundry_resume_attempt_id,
                    updated_at=now,
                )
            _mark_pending(
                operation_id=operation_id,
                attempt=attempt,
                code=receipt.safe_error_code or "foundry_pending",
                now=now,
            )
            return operation
        if receipt.state == "repair_required":
            _mark_repair(
                operation_id=operation_id,
                attempt=attempt,
                code=receipt.safe_error_code or "foundry_repair_required",
                now=now,
            )
            return operation
        if not receipt.receipt_id:
            _mark_repair(
                operation_id=operation_id,
                attempt=attempt,
                code="foundry_receipt_missing",
                now=now,
            )
            return operation
        DeletionOperation.objects.filter(
            pk=operation_id,
            state=DeletionOperationState.PENDING,
            attempt_count=attempt,
        ).update(foundry_resume_attempt_id=None, updated_at=now)
        try:
            tombstone = record_foundry_cleanup_receipt(
                ally_id=operation.ally_id, receipt=receipt.receipt_id
            )
        except (FileAllyTombstone.DoesNotExist, ValueError):
            _mark_repair(
                operation_id=operation_id,
                attempt=attempt,
                code="file_tombstone_missing",
                now=now,
            )
            return operation
        if tombstone.foundry_cleanup_receipt != receipt.receipt_id:
            _mark_repair(
                operation_id=operation_id,
                attempt=attempt,
                code="foundry_receipt_conflict",
                now=now,
            )
            return operation
        updated = DeletionOperation.objects.filter(
            pk=operation_id,
            state=DeletionOperationState.PENDING,
            attempt_count=attempt,
        ).update(
            stage=DeletionStage.FILES,
            next_attempt_at=now,
            lease_expires_at=None,
            safe_error_code="",
            updated_at=now,
        )
        if not updated:
            return operation
        operation.stage = DeletionStage.FILES

    if operation.stage == DeletionStage.FILES:
        try:
            cleanup_files(
                ally_id=operation.ally_id,
                limit=DELETION_BATCH_SIZE,
                duration_seconds=60.0,
            )
        except Exception:  # noqa: BLE001 - storage uncertainty is not success.
            _mark_pending(
                operation_id=operation_id,
                attempt=attempt,
                code="storage_unavailable",
                now=timezone.now(),
            )
            return operation
        ready, code, exhausted = _file_cleanup_ready(ally_id=operation.ally_id)
        if not ready:
            if exhausted:
                _mark_repair(
                    operation_id=operation_id,
                    attempt=attempt,
                    code=code,
                    now=timezone.now(),
                )
            else:
                _mark_pending(
                    operation_id=operation_id,
                    attempt=attempt,
                    code=code,
                    now=timezone.now(),
                )
            return operation
        updated = DeletionOperation.objects.filter(
            pk=operation_id,
            state=DeletionOperationState.PENDING,
            attempt_count=attempt,
        ).update(stage=DeletionStage.PURGE, updated_at=timezone.now())
        if not updated:
            return operation
        operation.stage = DeletionStage.PURGE

    try:
        return _purge_cloud_graph(operation_id=operation_id, now=timezone.now())
    except (Ally.DoesNotExist, FileAllyTombstone.DoesNotExist):
        _mark_repair(
            operation_id=operation_id,
            attempt=attempt,
            code="purge_scope_missing",
            now=timezone.now(),
        )
    except (ProtectedError, DeletionConflict):
        _mark_repair(
            operation_id=operation_id,
            attempt=attempt,
            code="protected_relation",
            now=timezone.now(),
        )
    return operation


def reconcile_ally_deletion(
    *, operation_id: UUID | str
) -> DeletionOperation | DeletionResult | None:
    """Claim and advance one deletion operation through all Cloud stages."""

    try:
        parsed_operation_id = canonical_uuid(operation_id)
    except (TypeError, ValueError) as exc:
        raise DeletionUnavailable("deletion unavailable") from exc
    now = timezone.now()
    claims = _claim_due(now=now, limit=DELETION_BATCH_SIZE)
    attempt = next((fence for pk, fence in claims if pk == parsed_operation_id), None)
    if attempt is None:
        operation = DeletionOperation.objects.filter(pk=parsed_operation_id).first()
        if operation is None:
            # The operation row is intentionally purged with the Ally. A late
            # broker delivery therefore has no identity left to look up and is
            # already complete.
            return None
        return operation
    return _reconcile_claimed(parsed_operation_id, attempt)


def reconcile_due_ally_deletions(
    *, now=None, limit: int = DELETION_BATCH_SIZE
) -> dict[str, int]:
    now = now or timezone.now()
    claims = _claim_due(now=now, limit=limit)
    completed = pending = repair_required = 0
    for operation_id, attempt in claims:
        result = _reconcile_claimed(operation_id, attempt)
        state = str(getattr(result, "state", ""))
        completed += state == DeletionOperationState.COMPLETE
        repair_required += state == DeletionOperationState.REPAIR_REQUIRED
        pending += state == DeletionOperationState.PENDING
    return {
        "claimed": len(claims),
        "completed": completed,
        "pending": pending,
        "repair_required": repair_required,
    }


def resume_ally_deletion(
    *, operation_id: UUID | str, expected_attempt_id: UUID | str
) -> DeletionOperation:
    """Create one fresh epoch only for the matching repair attempt."""

    try:
        operation_key = canonical_uuid(operation_id)
        expected = canonical_uuid(expected_attempt_id)
    except (TypeError, ValueError) as exc:
        raise DeletionInvalid("deletion resume is invalid") from exc
    now = timezone.now()
    with transaction.atomic():
        identity = (
            DeletionOperation.objects.filter(pk=operation_key)
            .values("workspace_id", "ally_id")
            .first()
        )
        if identity is None:
            raise DeletionUnavailable("deletion unavailable")
        _account_locked(identity["workspace_id"])
        ally = (
            Ally.objects.select_for_update()
            .filter(pk=identity["ally_id"], workspace_id=identity["workspace_id"])
            .first()
        )
        operation = DeletionOperation.objects.select_for_update().get(
            pk=operation_key,
            workspace_id=identity["workspace_id"],
            ally_id=identity["ally_id"],
        )
        if operation.state == DeletionOperationState.PENDING:
            if expected in {
                operation.supersedes_attempt_id,
                operation.foundry_resume_attempt_id,
            }:
                return operation
            raise DeletionConflict("deletion is already active")
        if operation.state == DeletionOperationState.COMPLETE:
            return operation
        if expected in {operation.attempt_id, operation.foundry_attempt_id}:
            if (
                ally is not None
                and ally.deletion_state == AllyDeletionState.REPAIR_REQUIRED
            ):
                ally.deletion_state = AllyDeletionState.PENDING
                ally.updated_at = now
                ally.save(update_fields=("deletion_state", "updated_at"))
            FileStagingObject.objects.filter(
                file__workspace_id=operation.workspace_id,
                file__ally_id=operation.ally_id,
                deleted_at__isnull=True,
                cleanup_attempts__gte=5,
            ).update(
                cleanup_attempts=0,
                cleanup_lease_until=None,
                cleanup_last_error="",
                cleanup_after=now,
            )
            operation.supersedes_attempt_id = expected
            operation.foundry_resume_attempt_id = operation.foundry_attempt_id
            operation.attempt_id = uuid.uuid4()
            operation.lifecycle_epoch += 1
            operation.attempt_count = 0
            operation.state = DeletionOperationState.PENDING
            operation.stage = DeletionStage.FOUNDRY
            operation.next_attempt_at = now
            operation.lease_expires_at = None
            operation.expires_at = now + DELETION_OPERATION_TTL
            operation.safe_error_code = ""
            operation.foundry_state = ""
            operation.foundry_receipt_id = ""
            operation.save(
                update_fields=(
                    "supersedes_attempt_id",
                    "attempt_id",
                    "lifecycle_epoch",
                    "attempt_count",
                    "state",
                    "stage",
                    "next_attempt_at",
                    "lease_expires_at",
                    "expires_at",
                    "safe_error_code",
                    "foundry_state",
                    "foundry_attempt_id",
                    "foundry_resume_attempt_id",
                    "foundry_receipt_id",
                    "updated_at",
                )
            )
            return operation
        if operation.supersedes_attempt_id == expected:
            return operation
        raise DeletionConflict("deletion attempt is stale")


__all__ = [
    "DELETION_BATCH_SIZE",
    "DeletionResult",
    "deletion_response",
    "get_ally_deletion",
    "reconcile_ally_deletion",
    "reconcile_due_ally_deletions",
    "request_ally_deletion",
    "resume_ally_deletion",
]
