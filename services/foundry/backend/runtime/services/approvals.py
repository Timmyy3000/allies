from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from runtime.contracts import (
    APPROVAL_ACTION_KINDS,
    MAX_APPROVAL_LIFETIME_SECONDS,
    ApprovalDecisionCommand,
    ApprovalDecisionReceipt,
    validate_approval_decision,
)
from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeFencedError,
    RuntimeLeaseConflictError,
    RuntimeNotFoundError,
    RuntimeValidationError,
)
from runtime.models import (
    ApprovalRequest,
    ApprovalRequestStatus,
    Attempt,
    AttemptStatus,
    Lease,
    LeaseState,
    Workspace,
)

from .retry import run_with_sqlite_lock_retry
from .runtime_auth import RuntimeContext
from .validation import digest_lease_token

APPROVAL_OUTCOMES = frozenset({"approved", "rejected", "expired", "cancelled"})
_LIVE_ATTEMPT_STATUSES = frozenset(
    {AttemptStatus.QUEUED, AttemptStatus.LEASED, AttemptStatus.RUNNING}
)
_TERMINAL_ATTEMPT_STATUSES = frozenset(
    {
        AttemptStatus.SUCCEEDED,
        AttemptStatus.FAILED,
        AttemptStatus.CANCELLED,
        AttemptStatus.UNKNOWN,
    }
)


@dataclass(frozen=True, slots=True)
class RuntimeApprovalStatus:
    approval_request_id: UUID
    status: str
    decision: str | None
    decided_at: datetime | None
    acknowledgement_deadline_at: datetime | None
    expires_at: datetime


def record_approval_request_from_event(
    attempt: Attempt,
    payload: dict,
) -> ApprovalRequest:
    """Persist the rich awaiting event in the same transaction as its event."""

    if not isinstance(payload, dict):
        raise RuntimeValidationError("approval request payload is invalid")
    try:
        request_id = UUID(str(payload["approval_request_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeValidationError("approval request identity is invalid") from exc
    if str(request_id) != payload.get("approval_request_id"):
        raise RuntimeValidationError("approval request identity is invalid")
    required = {
        "approval_request_id",
        "action_kind",
        "action_label",
        "action_preview",
        "expires_at",
    }
    if set(payload) != required:
        raise RuntimeValidationError("rich awaiting-action payload is invalid")
    action_kind = payload.get("action_kind")
    label = payload.get("action_label")
    preview = payload.get("action_preview")
    if action_kind not in APPROVAL_ACTION_KINDS:
        raise RuntimeValidationError("approval action kind is invalid")
    if not isinstance(label, str) or not 1 <= len(label) <= 120 or "\x00" in label:
        raise RuntimeValidationError("approval action label is invalid")
    if (
        not isinstance(preview, str)
        or not preview
        or "\x00" in preview
        or len(preview.encode("utf-8")) > 16 * 1024
    ):
        raise RuntimeValidationError("approval action preview is invalid")
    expires_at = _parse_timestamp(payload.get("expires_at"), "approval expiry")
    now = timezone.now()
    if expires_at <= now or expires_at > now + timedelta(
        seconds=MAX_APPROVAL_LIFETIME_SECONDS
    ):
        raise RuntimeValidationError("approval expiry is outside the bounded window")

    if attempt.execution.workspace_id != attempt.execution.profile.workspace_id:
        raise RuntimeValidationError("approval execution binding is invalid")
    if attempt.machine_generation != attempt.execution.workspace.machine_generation:
        raise RuntimeFencedError("approval generation is stale")
    try:
        existing = ApprovalRequest.objects.select_for_update().get(pk=request_id)
    except ApprovalRequest.DoesNotExist:
        existing = None
    if existing is not None:
        _ensure_request_binding(
            existing, attempt, action_kind, label, preview, expires_at
        )
        return existing
    try:
        # Keep the integrity-error rollback inside a savepoint. The enclosing
        # event transaction must remain usable when an exact append races.
        with transaction.atomic():
            return ApprovalRequest.objects.create(
                id=request_id,
                workspace_id=attempt.execution.workspace_id,
                profile_id=attempt.execution.profile_id,
                execution_id=attempt.execution_id,
                attempt_id=attempt.id,
                generation=attempt.machine_generation,
                hermes_run_id="",
                hermes_approval_id=str(request_id),
                action_kind=action_kind,
                action_label=label,
                action_preview=preview,
                expires_at=expires_at,
            )
    except IntegrityError:
        existing = (
            ApprovalRequest.objects.select_for_update().filter(pk=request_id).first()
        )
        if existing is None:
            raise RuntimeConflictError(
                "approval request identity conflicts with existing state"
            )
        _ensure_request_binding(
            existing, attempt, action_kind, label, preview, expires_at
        )
        return existing


def record_approval_decision(
    command: ApprovalDecisionCommand,
) -> ApprovalDecisionReceipt:
    command = validate_approval_decision(command)

    @transaction.atomic
    def record_once() -> ApprovalDecisionReceipt:
        workspace = (
            Workspace.objects.select_for_update()
            .filter(tenant_ref=str(command.scope.cloud_workspace_id))
            .first()
        )
        if workspace is None:
            raise RuntimeNotFoundError("approval workspace is unavailable")
        attempt = (
            Attempt.objects.select_for_update()
            .select_related("execution", "execution__profile")
            .filter(
                pk=command.foundry.attempt_id,
                execution__workspace_id=workspace.id,
            )
            .first()
        )
        if attempt is None:
            raise RuntimeNotFoundError("approval attempt is unavailable")
        lease = Lease.objects.select_for_update().filter(attempt_id=attempt.id).first()
        approval = (
            ApprovalRequest.objects.select_for_update()
            .select_related("execution", "workspace")
            .filter(pk=command.approval_request_id, attempt_id=attempt.id)
            .first()
        )
        if approval is None:
            raise RuntimeNotFoundError("approval request is unavailable")
        _ensure_command_binding(approval, command)
        now = timezone.now()
        _reconcile_locked(approval, now)
        if approval.status != ApprovalRequestStatus.PENDING:
            if _same_recorded_decision(approval, command):
                return _decision_receipt(command, "duplicate")
            raise RuntimeConflictError("approval request has already been resolved")
        _ensure_decision_window(approval, command, now)
        if (
            lease is None
            or lease.state != LeaseState.ACTIVE
            or lease.expires_at <= now
            or lease.machine_generation != workspace.machine_generation
            or lease.machine_generation != attempt.machine_generation
        ):
            raise RuntimeLeaseConflictError("approval lease is unavailable")
        if (
            workspace.machine_generation != command.foundry.generation
            or attempt.machine_generation != command.foundry.generation
        ):
            raise RuntimeFencedError("approval generation is stale")
        if approval.attempt.status not in _LIVE_ATTEMPT_STATUSES:
            raise RuntimeConflictError("approval attempt cannot be resumed")
        if approval.expires_at <= now:
            raise RuntimeConflictError("approval request has expired")
        approval.decision = command.decision
        approval.decision_command_id = command.command_id
        approval.decision_idempotency_key = command.idempotency_key
        approval.decision_fingerprint = command.fingerprint
        approval.decided_at = command.decided_at
        approval.acknowledgement_deadline_at = command.acknowledgement_deadline_at
        approval.status = ApprovalRequestStatus.DECISION_RECORDED
        approval.save(
            update_fields=[
                "decision",
                "decision_command_id",
                "decision_idempotency_key",
                "decision_fingerprint",
                "decided_at",
                "acknowledgement_deadline_at",
                "status",
                "updated_at",
            ]
        )
        return _decision_receipt(command, "accepted")

    return run_with_sqlite_lock_retry(record_once)


def read_runtime_approval(
    context: RuntimeContext,
    attempt_id: UUID | str,
    lease_token: str,
    approval_request_id: UUID | str,
) -> RuntimeApprovalStatus:
    if not isinstance(context, RuntimeContext):
        raise RuntimeValidationError("runtime context is required")
    try:
        attempt_uuid = UUID(str(attempt_id))
        request_uuid = UUID(str(approval_request_id))
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError("approval identity is invalid") from exc
    token_digest = digest_lease_token(lease_token)

    @transaction.atomic
    def read_once() -> RuntimeApprovalStatus:
        workspace = Workspace.objects.select_for_update().get(pk=context.workspace_id)
        if workspace.machine_generation != context.machine_generation:
            raise RuntimeFencedError("runtime generation is stale")
        attempt = (
            Attempt.objects.select_for_update()
            .select_related("execution", "execution__profile")
            .filter(pk=attempt_uuid, execution__workspace_id=workspace.id)
            .first()
        )
        if attempt is None:
            raise RuntimeLeaseConflictError("attempt is not in this workspace")
        lease = Lease.objects.select_for_update().filter(attempt_id=attempt.id).first()
        if (
            lease is None
            or lease.token_digest != token_digest
            or lease.machine_generation != context.machine_generation
            or lease.profile_id != attempt.execution.profile_id
            or lease.state != LeaseState.ACTIVE
            or lease.expires_at <= timezone.now()
        ):
            raise RuntimeLeaseConflictError("lease does not authorize approval read")
        approval = (
            ApprovalRequest.objects.select_for_update()
            .filter(pk=request_uuid, attempt_id=attempt.id, workspace_id=workspace.id)
            .first()
        )
        if approval is None:
            raise RuntimeNotFoundError("approval request is unavailable")
        _reconcile_locked(approval, timezone.now())
        return _status(approval)

    return run_with_sqlite_lock_retry(read_once)


def apply_approval_resolution(
    attempt_id: UUID,
    approval_request_id: UUID | str,
    outcome: str,
) -> ApprovalRequest:
    if outcome not in APPROVAL_OUTCOMES:
        raise RuntimeValidationError("approval outcome is invalid")
    try:
        request_uuid = UUID(str(approval_request_id))
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError("approval request identity is invalid") from exc
    approval = (
        ApprovalRequest.objects.select_for_update()
        .select_related("attempt")
        .filter(pk=request_uuid, attempt_id=attempt_id)
        .first()
    )
    if approval is None:
        raise RuntimeConflictError("approval request does not belong to attempt")
    _reconcile_locked(approval, timezone.now())
    if approval.status == ApprovalRequestStatus.OUTCOME_UNKNOWN:
        if outcome in {"approved", "rejected"}:
            expected = "approved" if approval.decision == "approve" else "rejected"
            if outcome != expected:
                raise RuntimeConflictError("approval outcome conflicts with decision")
        return approval
    if approval.outcome == outcome and approval.status in {
        ApprovalRequestStatus.APPLIED,
        ApprovalRequestStatus.EXPIRED,
        ApprovalRequestStatus.CANCELLED,
    }:
        return approval
    if outcome in {"approved", "rejected"}:
        expected = "approve" if outcome == "approved" else "reject"
        if approval.status != ApprovalRequestStatus.DECISION_RECORDED:
            raise RuntimeConflictError(
                "approval decision is not awaiting runtime acknowledgement"
            )
        if approval.decision != expected:
            raise RuntimeConflictError("approval outcome conflicts with decision")
        approval.status = ApprovalRequestStatus.APPLIED
    elif outcome == "expired":
        if approval.status not in {
            ApprovalRequestStatus.PENDING,
            ApprovalRequestStatus.DECISION_RECORDED,
            ApprovalRequestStatus.EXPIRED,
        }:
            raise RuntimeConflictError("approval cannot be expired after decision")
        approval.status = ApprovalRequestStatus.EXPIRED
    else:
        if approval.status not in {
            ApprovalRequestStatus.PENDING,
            ApprovalRequestStatus.DECISION_RECORDED,
            ApprovalRequestStatus.CANCELLED,
        }:
            raise RuntimeConflictError("approval cannot be cancelled")
        approval.status = ApprovalRequestStatus.CANCELLED
    approval.outcome = outcome
    approval.resolved_at = timezone.now()
    approval.save(update_fields=["status", "outcome", "resolved_at", "updated_at"])
    return approval


def cancel_live_approval_requests(
    attempt: Attempt,
    *,
    now: datetime | None = None,
) -> int:
    """Close approvals that cannot resume after an attempt leaves the lease.

    Callers hold the attempt's lifecycle locks inside their enclosing atomic
    transition.  Expired pending consent is reconciled first. A recorded
    decision becomes outcome-unknown until Hermes acknowledges it; only a
    pending request is cancelled.
    """

    effective_now = now or timezone.now()
    if timezone.is_naive(effective_now):
        raise RuntimeValidationError(
            "approval cancellation time must be timezone-aware"
        )
    transitioned = 0
    approvals = (
        ApprovalRequest.objects.select_for_update()
        .filter(
            attempt_id=attempt.id,
            status__in=(
                ApprovalRequestStatus.PENDING,
                ApprovalRequestStatus.DECISION_RECORDED,
            ),
        )
        .order_by("id")
    )
    for approval in approvals:
        _reconcile_locked(approval, effective_now)
        if approval.status == ApprovalRequestStatus.PENDING:
            approval.status = ApprovalRequestStatus.CANCELLED
            approval.outcome = "cancelled"
            approval.resolved_at = effective_now
            approval.save(
                update_fields=["status", "outcome", "resolved_at", "updated_at"]
            )
            transitioned += 1
        elif approval.status == ApprovalRequestStatus.DECISION_RECORDED:
            approval.status = ApprovalRequestStatus.OUTCOME_UNKNOWN
            approval.resolved_at = effective_now
            approval.save(update_fields=["status", "resolved_at", "updated_at"])
            transitioned += 1
    return transitioned


def _ensure_request_binding(
    existing: ApprovalRequest,
    attempt: Attempt,
    action_kind: str,
    label: str,
    preview: str,
    expires_at: datetime,
) -> None:
    if (
        existing.attempt_id != attempt.id
        or existing.execution_id != attempt.execution_id
        or existing.workspace_id != attempt.execution.workspace_id
        or existing.profile_id != attempt.execution.profile_id
        or existing.generation != attempt.machine_generation
        or existing.action_kind != action_kind
        or existing.action_label != label
        or existing.action_preview != preview
        or existing.expires_at != expires_at
    ):
        raise RuntimeConflictError("approval request identity conflicts with content")


def _ensure_command_binding(
    approval: ApprovalRequest,
    command: ApprovalDecisionCommand,
) -> None:
    if (
        approval.execution_id != command.foundry.execution_id
        or approval.attempt_id != command.foundry.attempt_id
        or approval.generation != command.foundry.generation
        or approval.execution.cloud_workspace_id != command.scope.cloud_workspace_id
        or approval.execution.cloud_ally_id != command.cloud.ally_id
        or approval.execution.cloud_conversation_id != command.cloud.conversation_id
        or approval.execution.cloud_message_id != command.cloud.message_id
        or approval.execution.cloud_binding_id != command.cloud.cloud_binding_id
    ):
        raise RuntimeConflictError("approval command scope does not match request")


def _ensure_decision_window(
    approval: ApprovalRequest,
    command: ApprovalDecisionCommand,
    now: datetime,
) -> None:
    if command.issued_at > command.decided_at:
        raise RuntimeValidationError("approval command timestamps are out of order")
    if command.deadline_at > command.acknowledgement_deadline_at:
        raise RuntimeValidationError(
            "approval command deadline is beyond acknowledgement"
        )
    if command.deadline_at > approval.expires_at:
        raise RuntimeConflictError("approval command deadline exceeds consent expiry")
    if command.decided_at > now:
        raise RuntimeConflictError("approval decision is dated in the future")
    if now >= min(
        command.deadline_at,
        command.acknowledgement_deadline_at,
        approval.expires_at,
    ):
        raise RuntimeConflictError("approval decision window has expired")


def _same_recorded_decision(
    approval: ApprovalRequest,
    command: ApprovalDecisionCommand,
) -> bool:
    return (
        approval.decision_command_id == command.command_id
        and approval.decision_idempotency_key == command.idempotency_key
        and approval.decision_fingerprint == command.fingerprint
        and approval.decision == command.decision
    )


def _decision_receipt(
    command: ApprovalDecisionCommand,
    status: str,
) -> ApprovalDecisionReceipt:
    return ApprovalDecisionReceipt(
        schema_version="v1",
        kind="approval.receipt",
        status=status,
        command_id=command.command_id,
        idempotency_key=command.idempotency_key,
        approval_request_id=command.approval_request_id,
        fingerprint=command.fingerprint,
    )


def _status(approval: ApprovalRequest) -> RuntimeApprovalStatus:
    return RuntimeApprovalStatus(
        approval_request_id=approval.id,
        status=approval.status,
        decision=approval.decision,
        decided_at=approval.decided_at,
        acknowledgement_deadline_at=approval.acknowledgement_deadline_at,
        expires_at=approval.expires_at,
    )


def _reconcile_locked(approval: ApprovalRequest, now: datetime) -> None:
    if approval.status == ApprovalRequestStatus.PENDING and now >= approval.expires_at:
        approval.status = ApprovalRequestStatus.EXPIRED
        approval.outcome = "expired"
        approval.resolved_at = now
        approval.save(update_fields=["status", "outcome", "resolved_at", "updated_at"])
        return
    if (
        approval.status == ApprovalRequestStatus.DECISION_RECORDED
        and approval.acknowledgement_deadline_at is not None
        and now >= approval.acknowledgement_deadline_at
    ):
        approval.status = ApprovalRequestStatus.OUTCOME_UNKNOWN
        approval.resolved_at = now
        approval.save(update_fields=["status", "resolved_at", "updated_at"])


def _parse_timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise RuntimeValidationError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeValidationError(f"{name} is invalid") from exc
    if parsed.tzinfo is None:
        raise RuntimeValidationError(f"{name} must include a timezone")
    return parsed


__all__ = [
    "APPROVAL_OUTCOMES",
    "RuntimeApprovalStatus",
    "apply_approval_resolution",
    "cancel_live_approval_requests",
    "read_runtime_approval",
    "record_approval_decision",
    "record_approval_request_from_event",
]
