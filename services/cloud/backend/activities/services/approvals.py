"""Cloud approval truth, membership-scoped reads, and bounded delivery."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from django.db import connection, transaction
from django.db.models import F, Q
from django.utils import timezone

from allies.exceptions import (
    FoundryGatewayConflict,
    FoundryGatewayInvalid,
    FoundryGatewayNotFound,
    FoundryGatewayRejected,
    FoundryGatewayRetryable,
    FoundryGatewayUnknownOutcome,
)
from allies.gateways.contracts import (
    ApprovalDecisionCommand,
    ApprovalDecisionReceipt,
    canonical_fingerprint,
    canonical_json_bytes,
)
from allies.gateways.foundry import submit_approval_decision
from allies.models import Ally, AllyBinding, AllyDeletionState, BindingStatus
from auths.config import digest_key
from chat.models import Conversation
from common.uuids import canonical_uuid
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability

from ..exceptions import ApprovalConflict, ApprovalInvalid, ApprovalNotFound
from ..models import (
    Approval,
    ApprovalDeliveryState,
    ApprovalStatus,
)

APPROVAL_MAX_LIST = 50
APPROVAL_DELIVERY_LEASE_SECONDS = 60
APPROVAL_DELIVERY_MAX_ATTEMPTS = 5
APPROVAL_DELIVERY_MAX_BACKOFF_SECONDS = 300
APPROVAL_ACKNOWLEDGEMENT_SECONDS = 30
_TERMINAL_STATUSES = (
    ApprovalStatus.APPROVED,
    ApprovalStatus.REJECTED,
    ApprovalStatus.EXPIRED,
    ApprovalStatus.CANCELLED,
    ApprovalStatus.OUTCOME_UNKNOWN,
)


@dataclass(frozen=True, slots=True)
class ApprovalDecisionResult:
    approval: Approval
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ApprovalDeliveryReport:
    claimed: int = 0
    delivered: int = 0
    deferred: int = 0
    unknown: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "claimed": self.claimed,
            "delivered": self.delivered,
            "deferred": self.deferred,
            "unknown": self.unknown,
        }


def _conversation_for_user(*, user, workspace_id, conversation_id, capability):
    context = require_workspace_capability(
        user=user, workspace_id=workspace_id, capability=capability
    )
    try:
        parsed_conversation_id = canonical_uuid(conversation_id)
    except (TypeError, ValueError) as exc:
        raise ApprovalNotFound("approval unavailable") from exc
    conversation = (
        Conversation.objects.select_related("ally", "ally__workspace")
        .filter(
            pk=parsed_conversation_id,
            ally__workspace=context.workspace,
            ally__deletion_state=AllyDeletionState.ACTIVE,
        )
        .first()
    )
    if conversation is None:
        raise ApprovalNotFound("approval unavailable")
    return context, conversation


def _approval_queryset(*, context, conversation):
    return Approval.objects.select_related(
        "workspace", "ally", "conversation", "message", "deciding_user"
    ).filter(
        workspace=context.workspace,
        ally_id=conversation.ally_id,
        ally__deletion_state=AllyDeletionState.ACTIVE,
        conversation=conversation,
        message__conversation=conversation,
    )


def _approval_for_user(
    *, user, workspace_id, conversation_id, approval_id, capability, lock=False
):
    context, conversation = _conversation_for_user(
        user=user,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        capability=capability,
    )
    try:
        parsed_approval_id = canonical_uuid(approval_id)
    except (TypeError, ValueError) as exc:
        raise ApprovalNotFound("approval unavailable") from exc
    queryset = _approval_queryset(context=context, conversation=conversation).filter(
        pk=parsed_approval_id
    )
    if lock:
        # Keep the nullable deciding-user relation out of PostgreSQL's lock set.
        queryset = queryset.select_for_update(of=("self",))
    approval = queryset.first()
    if approval is None:
        raise ApprovalNotFound("approval unavailable")
    return context, conversation, approval


def _save_reconciliation(approval: Approval, *, now: datetime) -> bool:
    """Apply timestamp-based status transitions while the row is locked."""

    if approval.status == ApprovalStatus.PENDING and now >= approval.expires_at:
        approval.status = ApprovalStatus.EXPIRED
        approval.delivery_state = ApprovalDeliveryState.CANCELLED
        approval.delivery_next_attempt_at = None
        approval.delivery_lease_expires_at = None
        approval.delivery_safe_error_code = "approval_expired"
    elif (
        approval.status == ApprovalStatus.DECISION_RECORDED
        and approval.acknowledgement_deadline_at is not None
        and now >= approval.acknowledgement_deadline_at
    ):
        approval.status = ApprovalStatus.OUTCOME_UNKNOWN
        approval.delivery_state = ApprovalDeliveryState.CANCELLED
        approval.delivery_next_attempt_at = None
        approval.delivery_lease_expires_at = None
        approval.delivery_safe_error_code = "acknowledgement_timeout"
    else:
        return False
    approval.save(
        update_fields=(
            "status",
            "delivery_state",
            "delivery_next_attempt_at",
            "delivery_lease_expires_at",
            "delivery_safe_error_code",
            "updated_at",
        )
    )
    return True


def _approval_binding_is_current(approval: Approval) -> bool:
    return AllyBinding.objects.filter(
        pk=approval.cloud_binding_id,
        ally_id=approval.ally_id,
        status=BindingStatus.BOUND,
    ).exists()


def reconcile_approval(approval: Approval, *, now: datetime | None = None) -> Approval:
    """Reconcile one approval in a short transaction for read callers."""

    with transaction.atomic():
        locked = Approval.objects.select_for_update(of=("self",)).get(pk=approval.pk)
        if (
            Ally.objects.values_list("deletion_state", flat=True).get(pk=locked.ally_id)
            != AllyDeletionState.ACTIVE
        ):
            return locked
        _save_reconciliation(locked, now=now or timezone.now())
        return locked


def reconcile_conversation_approvals(
    conversation_id: UUID, *, now: datetime | None = None
) -> None:
    """Apply lazy expiry/acknowledgement deadlines for one conversation."""

    current = now or timezone.now()
    with transaction.atomic():
        pending_ids = list(
            Approval.objects.filter(
                conversation_id=conversation_id,
                ally__deletion_state=AllyDeletionState.ACTIVE,
                status=ApprovalStatus.PENDING,
                expires_at__lte=current,
            )
            .order_by("requested_at", "id")
            .values_list("pk", flat=True)[:APPROVAL_MAX_LIST]
        )
        if pending_ids:
            Approval.objects.filter(
                pk__in=pending_ids,
                status=ApprovalStatus.PENDING,
            ).update(
                status=ApprovalStatus.EXPIRED,
                delivery_state=ApprovalDeliveryState.CANCELLED,
                delivery_next_attempt_at=None,
                delivery_lease_expires_at=None,
                delivery_safe_error_code="approval_expired",
                updated_at=current,
            )
        decision_ids = list(
            Approval.objects.filter(
                conversation_id=conversation_id,
                ally__deletion_state=AllyDeletionState.ACTIVE,
                status=ApprovalStatus.DECISION_RECORDED,
                acknowledgement_deadline_at__lte=current,
            )
            .order_by("decided_at", "id")
            .values_list("pk", flat=True)[:APPROVAL_MAX_LIST]
        )
        if decision_ids:
            Approval.objects.filter(
                pk__in=decision_ids,
                status=ApprovalStatus.DECISION_RECORDED,
            ).update(
                status=ApprovalStatus.OUTCOME_UNKNOWN,
                delivery_state=ApprovalDeliveryState.CANCELLED,
                delivery_next_attempt_at=None,
                delivery_lease_expires_at=None,
                delivery_safe_error_code="acknowledgement_timeout",
                updated_at=current,
            )


def list_approvals(
    *, user, workspace_id, conversation_id, limit: int = APPROVAL_MAX_LIST
) -> list[Approval]:
    if not 1 <= limit <= APPROVAL_MAX_LIST:
        raise ApprovalInvalid("approval limit is invalid")
    with transaction.atomic():
        context, conversation = _conversation_for_user(
            user=user,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            capability=Capability.PROFILE_READ,
        )
        current = timezone.now()
        reconcile_conversation_approvals(conversation.id, now=current)
        queryset = _approval_queryset(context=context, conversation=conversation)
        live_active = Q(status=ApprovalStatus.PENDING, expires_at__gt=current) | (
            Q(status=ApprovalStatus.DECISION_RECORDED)
            & (
                Q(acknowledgement_deadline_at__isnull=True)
                | Q(acknowledgement_deadline_at__gt=current)
            )
        )
        active = list(
            queryset.filter(live_active)
            .select_for_update(of=("self",))
            .order_by("requested_at", "id")[:limit]
        )
        for approval in active:
            _save_reconciliation(approval, now=current)
        remaining = limit - len(active)
        if remaining <= 0:
            return active
        terminal = list(
            queryset.filter(status__in=_TERMINAL_STATUSES)
            .exclude(pk__in=[approval.pk for approval in active])
            .order_by(
                F("decided_at").desc(nulls_last=True),
                F("updated_at").desc(nulls_last=True),
                "id",
            )[:remaining]
        )
        return active + terminal


def get_approval_detail(
    *, user, workspace_id, conversation_id, approval_id
) -> Approval:
    with transaction.atomic():
        _context, _conversation, approval = _approval_for_user(
            user=user,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            approval_id=approval_id,
            capability=Capability.PROFILE_READ,
            lock=True,
        )
        _save_reconciliation(approval, now=timezone.now())
        return approval


def _key_digest(key: UUID) -> str:
    return hmac.new(digest_key(), str(key).encode(), hashlib.sha256).hexdigest()


def _decision_fingerprint(approval: Approval, key: UUID, decision: str) -> str:
    return canonical_fingerprint(
        {
            "approval_id": str(approval.id),
            "approval_request_id": str(approval.approval_request_id),
            "decision": decision,
            "idempotency_key": str(key),
        }
    )


def _schedule_approval_delivery() -> None:
    try:
        from ..tasks import dispatch_pending_approvals_task

        dispatch_pending_approvals_task.delay()
    except Exception:  # noqa: BLE001 - the row remains the recovery path
        return


def record_approval_decision(
    *, user, workspace_id, conversation_id, approval_id, decision: str, idempotency_key
) -> ApprovalDecisionResult:
    if decision not in {"approve", "reject"}:
        raise ApprovalInvalid("approval decision is invalid")
    try:
        parsed_key = canonical_uuid(idempotency_key)
    except (TypeError, ValueError) as exc:
        raise ApprovalInvalid("idempotency key is invalid") from exc
    key_digest = _key_digest(parsed_key)
    with transaction.atomic():
        _context, _conversation, approval = _approval_for_user(
            user=user,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            approval_id=approval_id,
            capability=Capability.PROFILE_WRITE,
            lock=True,
        )
        now = timezone.now()
        _save_reconciliation(approval, now=now)
        if not _approval_binding_is_current(approval):
            raise ApprovalConflict("approval binding is no longer current")
        fingerprint = _decision_fingerprint(approval, parsed_key, decision)
        if approval.decision_idempotency_key_digest:
            if (
                approval.decision_idempotency_key_digest == key_digest
                and approval.decision == decision
                and approval.decision_fingerprint == fingerprint
            ):
                if approval.status == ApprovalStatus.DECISION_RECORDED:
                    transaction.on_commit(_schedule_approval_delivery)
                return ApprovalDecisionResult(approval=approval, replayed=True)
            raise ApprovalConflict("approval decision conflicts with existing choice")
        if approval.status != ApprovalStatus.PENDING:
            raise ApprovalConflict("approval is no longer pending")
        approval.decision_idempotency_key = parsed_key
        approval.decision_idempotency_key_digest = key_digest
        approval.decision_fingerprint = fingerprint
        approval.decision = decision
        approval.decided_at = now
        approval.acknowledgement_deadline_at = now + timedelta(
            seconds=APPROVAL_ACKNOWLEDGEMENT_SECONDS
        )
        approval.status = ApprovalStatus.DECISION_RECORDED
        approval.delivery_state = ApprovalDeliveryState.PENDING
        approval.delivery_attempt_count = 0
        approval.delivery_next_attempt_at = now
        approval.delivery_lease_expires_at = None
        approval.delivery_last_attempt_at = None
        approval.delivery_completed_at = None
        approval.delivery_safe_error_code = ""
        approval.delivery_receipt_digest = ""
        approval.deciding_user = user
        approval.save(
            update_fields=(
                "decision_idempotency_key",
                "decision_idempotency_key_digest",
                "decision_fingerprint",
                "decision",
                "decided_at",
                "acknowledgement_deadline_at",
                "status",
                "delivery_state",
                "delivery_attempt_count",
                "delivery_next_attempt_at",
                "delivery_lease_expires_at",
                "delivery_last_attempt_at",
                "delivery_completed_at",
                "delivery_safe_error_code",
                "delivery_receipt_digest",
                "deciding_user",
                "updated_at",
            )
        )
        transaction.on_commit(_schedule_approval_delivery)
        return ApprovalDecisionResult(approval=approval, replayed=False)


def approval_decision_command(
    approval: Approval,
) -> tuple[ApprovalDecisionCommand, bytes]:
    if (
        approval.status != ApprovalStatus.DECISION_RECORDED
        or approval.decision_idempotency_key is None
        or approval.decided_at is None
        or approval.acknowledgement_deadline_at is None
    ):
        raise ApprovalInvalid("approval is not deliverable")
    issued_at = approval.decided_at
    deadline_at = min(approval.expires_at, approval.acknowledgement_deadline_at)

    def wire_timestamp(value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    values = {
        "schema_version": "v1",
        "kind": "approval.decision",
        "producer": "cloud",
        "service_identity": "cloud-service",
        "command_id": str(approval.id),
        "idempotency_key": str(approval.decision_idempotency_key),
        "scope": {
            "kind": "workspace",
            "cloud_workspace_id": str(approval.workspace_id),
        },
        "cloud": {
            "ally_id": str(approval.ally_id),
            "conversation_id": str(approval.conversation_id),
            "message_id": str(approval.message_id),
            "cloud_binding_id": str(approval.cloud_binding_id),
        },
        "foundry": {
            "execution_id": str(approval.execution_id),
            "attempt_id": str(approval.attempt_id),
            "generation": approval.generation,
        },
        "approval_request_id": str(approval.approval_request_id),
        "decision": approval.decision,
        "decided_at": wire_timestamp(approval.decided_at),
        "acknowledgement_deadline_at": wire_timestamp(
            approval.acknowledgement_deadline_at
        ),
        "issued_at": wire_timestamp(issued_at),
        "deadline_at": wire_timestamp(deadline_at),
    }
    values["fingerprint"] = canonical_fingerprint(values)
    command = ApprovalDecisionCommand.model_validate(values)
    body = canonical_json_bytes(command.model_dump(mode="json"))
    return command, body


def _backoff_seconds(attempt: int) -> int:
    return min(APPROVAL_DELIVERY_MAX_BACKOFF_SECONDS, 2 ** max(0, attempt - 1))


def _receipt_digest(receipt: ApprovalDecisionReceipt) -> str:
    return hashlib.sha256(
        canonical_json_bytes(receipt.model_dump(mode="json"))
    ).hexdigest()


def _mark_unknown(*, pk: UUID, fence: int, code: str, now: datetime) -> bool:
    return bool(
        Approval.objects.filter(
            pk=pk,
            ally__deletion_state=AllyDeletionState.ACTIVE,
            status=ApprovalStatus.DECISION_RECORDED,
            delivery_state=ApprovalDeliveryState.IN_PROGRESS,
            delivery_attempt_count=fence,
        ).update(
            status=ApprovalStatus.OUTCOME_UNKNOWN,
            delivery_state=ApprovalDeliveryState.CANCELLED,
            delivery_safe_error_code=code,
            delivery_next_attempt_at=None,
            delivery_lease_expires_at=None,
            updated_at=now,
        )
    )


def _mark_deferred(*, pk: UUID, fence: int, code: str, now: datetime) -> bool:
    return bool(
        Approval.objects.filter(
            pk=pk,
            ally__deletion_state=AllyDeletionState.ACTIVE,
            status=ApprovalStatus.DECISION_RECORDED,
            delivery_state=ApprovalDeliveryState.IN_PROGRESS,
            delivery_attempt_count=fence,
        ).update(
            delivery_state=ApprovalDeliveryState.FAILED,
            delivery_safe_error_code=code,
            delivery_next_attempt_at=now + timedelta(seconds=_backoff_seconds(fence)),
            delivery_lease_expires_at=None,
            updated_at=now,
        )
    )


def _mark_consent_expired(*, pk: UUID, fence: int, now: datetime) -> bool:
    return bool(
        Approval.objects.filter(
            pk=pk,
            ally__deletion_state=AllyDeletionState.ACTIVE,
            status=ApprovalStatus.DECISION_RECORDED,
            delivery_state=ApprovalDeliveryState.IN_PROGRESS,
            delivery_attempt_count=fence,
        ).update(
            delivery_state=ApprovalDeliveryState.CANCELLED,
            delivery_safe_error_code="consent_expired",
            delivery_next_attempt_at=None,
            delivery_lease_expires_at=None,
            updated_at=now,
        )
    )


def _mark_delivered(
    *, pk: UUID, fence: int, receipt: ApprovalDecisionReceipt, now: datetime
) -> bool:
    return bool(
        Approval.objects.filter(
            pk=pk,
            ally__deletion_state=AllyDeletionState.ACTIVE,
            status=ApprovalStatus.DECISION_RECORDED,
            delivery_state=ApprovalDeliveryState.IN_PROGRESS,
            delivery_attempt_count=fence,
        ).update(
            delivery_state=ApprovalDeliveryState.DELIVERED,
            delivery_safe_error_code="",
            delivery_next_attempt_at=None,
            delivery_lease_expires_at=None,
            delivery_completed_at=now,
            delivery_receipt_digest=_receipt_digest(receipt),
            updated_at=now,
        )
    )


def _enforce_delivery_deadline(
    *, approval: Approval, pk: UUID, fence: int, now: datetime
) -> str | None:
    if now >= approval.expires_at:
        _mark_consent_expired(pk=pk, fence=fence, now=now)
        return "skipped"
    if (
        approval.acknowledgement_deadline_at
        and now >= approval.acknowledgement_deadline_at
    ):
        _mark_unknown(pk=pk, fence=fence, code="acknowledgement_timeout", now=now)
        return "unknown"
    return None


def _claim_due(*, now: datetime, limit: int) -> list[tuple[UUID, int]]:
    due = Q(
        delivery_state__in=(
            ApprovalDeliveryState.PENDING,
            ApprovalDeliveryState.FAILED,
        ),
        delivery_next_attempt_at__lte=now,
    ) | Q(
        delivery_state=ApprovalDeliveryState.IN_PROGRESS,
        delivery_lease_expires_at__lte=now,
    )
    bound = max(1, min(limit, 100))
    candidate_ids = list(
        Approval.objects.filter(
            ally__deletion_state=AllyDeletionState.ACTIVE,
            status=ApprovalStatus.DECISION_RECORDED,
        )
        .filter(due)
        .order_by("delivery_next_attempt_at", "decided_at", "id")
        .values_list("pk", flat=True)[:bound]
    )
    lease_until = now + timedelta(seconds=APPROVAL_DELIVERY_LEASE_SECONDS)
    with transaction.atomic():
        claimed: list[tuple[UUID, int]] = []
        for pk in candidate_ids:
            try:
                approval = Approval.objects.select_for_update(
                    skip_locked=connection.features.has_select_for_update_skip_locked
                ).get(pk=pk)
            except Approval.DoesNotExist:
                continue
            if approval.ally.deletion_state != AllyDeletionState.ACTIVE:
                continue
            _save_reconciliation(approval, now=now)
            if approval.status != ApprovalStatus.DECISION_RECORDED:
                continue
            if now >= approval.expires_at:
                approval.delivery_state = ApprovalDeliveryState.CANCELLED
                approval.delivery_next_attempt_at = None
                approval.delivery_lease_expires_at = None
                approval.delivery_safe_error_code = "consent_expired"
                approval.save(
                    update_fields=(
                        "delivery_state",
                        "delivery_next_attempt_at",
                        "delivery_lease_expires_at",
                        "delivery_safe_error_code",
                        "updated_at",
                    )
                )
                continue
            if not _approval_binding_is_current(approval):
                approval.status = ApprovalStatus.OUTCOME_UNKNOWN
                approval.delivery_state = ApprovalDeliveryState.CANCELLED
                approval.delivery_next_attempt_at = None
                approval.delivery_lease_expires_at = None
                approval.delivery_safe_error_code = "binding_unavailable"
                approval.save(
                    update_fields=(
                        "status",
                        "delivery_state",
                        "delivery_next_attempt_at",
                        "delivery_lease_expires_at",
                        "delivery_safe_error_code",
                        "updated_at",
                    )
                )
                continue
            if approval.delivery_state in {
                ApprovalDeliveryState.PENDING,
                ApprovalDeliveryState.FAILED,
            }:
                if (
                    approval.delivery_next_attempt_at is None
                    or approval.delivery_next_attempt_at > now
                ):
                    continue
            elif approval.delivery_state == ApprovalDeliveryState.IN_PROGRESS:
                if (
                    approval.delivery_lease_expires_at is None
                    or approval.delivery_lease_expires_at > now
                ):
                    continue
            else:
                continue
            if approval.delivery_attempt_count >= APPROVAL_DELIVERY_MAX_ATTEMPTS:
                approval.status = ApprovalStatus.OUTCOME_UNKNOWN
                approval.delivery_state = ApprovalDeliveryState.CANCELLED
                approval.delivery_safe_error_code = "delivery_attempts_exhausted"
                approval.delivery_next_attempt_at = None
                approval.delivery_lease_expires_at = None
                approval.save(
                    update_fields=(
                        "status",
                        "delivery_state",
                        "delivery_safe_error_code",
                        "delivery_next_attempt_at",
                        "delivery_lease_expires_at",
                        "updated_at",
                    )
                )
                continue
            approval.delivery_attempt_count += 1
            approval.delivery_state = ApprovalDeliveryState.IN_PROGRESS
            approval.delivery_last_attempt_at = now
            approval.delivery_lease_expires_at = lease_until
            approval.save(
                update_fields=(
                    "delivery_attempt_count",
                    "delivery_state",
                    "delivery_last_attempt_at",
                    "delivery_lease_expires_at",
                    "updated_at",
                )
            )
            claimed.append((approval.pk, approval.delivery_attempt_count))
        return claimed


def _deliver_one(*, pk: UUID, fence: int, now: datetime | None = None) -> str:
    current = now or timezone.now()
    approval = Approval.objects.select_related(
        "workspace", "ally", "conversation__ally__binding", "message"
    ).get(pk=pk)
    if (
        approval.status != ApprovalStatus.DECISION_RECORDED
        or approval.ally.deletion_state != AllyDeletionState.ACTIVE
    ):
        return "skipped"
    deadline_result = _enforce_delivery_deadline(
        approval=approval, pk=pk, fence=fence, now=current
    )
    if deadline_result is not None:
        return deadline_result
    if not _approval_binding_is_current(approval):
        _mark_unknown(pk=pk, fence=fence, code="binding_unavailable", now=current)
        return "unknown"
    submission_now = current
    try:
        command, body = approval_decision_command(approval)
        # A batch claim may wait behind earlier network calls. Recheck the
        # original consent window immediately before each outbound request.
        submission_now = now or timezone.now()
        deadline_result = _enforce_delivery_deadline(
            approval=approval, pk=pk, fence=fence, now=submission_now
        )
        if deadline_result is not None:
            return deadline_result
        if not _approval_binding_is_current(approval):
            _mark_unknown(
                pk=pk, fence=fence, code="binding_unavailable", now=submission_now
            )
            return "unknown"
        receipt = submit_approval_decision(command, raw_body=body)
    except FoundryGatewayUnknownOutcome:
        failure_now = now or timezone.now()
        deadline_result = _enforce_delivery_deadline(
            approval=approval, pk=pk, fence=fence, now=failure_now
        )
        if deadline_result is not None:
            return deadline_result
        _mark_deferred(
            pk=pk, fence=fence, code="foundry_outcome_unknown", now=failure_now
        )
        return "deferred"
    except FoundryGatewayRetryable:
        failure_now = now or timezone.now()
        deadline_result = _enforce_delivery_deadline(
            approval=approval, pk=pk, fence=fence, now=failure_now
        )
        if deadline_result is not None:
            return deadline_result
        _mark_deferred(pk=pk, fence=fence, code="foundry_unavailable", now=failure_now)
        return "deferred"
    except (
        FoundryGatewayConflict,
        FoundryGatewayInvalid,
        FoundryGatewayNotFound,
        FoundryGatewayRejected,
        ApprovalInvalid,
        ValueError,
    ):
        failure_now = now or timezone.now()
        deadline_result = _enforce_delivery_deadline(
            approval=approval, pk=pk, fence=fence, now=failure_now
        )
        if deadline_result is not None:
            return deadline_result
        _mark_unknown(pk=pk, fence=fence, code="foundry_rejected", now=failure_now)
        return "unknown"
    completion_now = now or timezone.now()
    deadline_result = _enforce_delivery_deadline(
        approval=approval, pk=pk, fence=fence, now=completion_now
    )
    if deadline_result is not None:
        return deadline_result
    if (
        receipt.command_id != command.command_id
        or receipt.idempotency_key != command.idempotency_key
        or receipt.approval_request_id != command.approval_request_id
        or receipt.fingerprint != command.fingerprint
    ):
        _mark_unknown(
            pk=pk,
            fence=fence,
            code="receipt_identity_mismatch",
            now=completion_now,
        )
        return "unknown"
    return (
        "delivered"
        if _mark_delivered(pk=pk, fence=fence, receipt=receipt, now=completion_now)
        else "deferred"
    )


def dispatch_pending_approvals(*, now: datetime | None = None, limit: int = 20):
    current = now or timezone.now()
    claims = _claim_due(now=current, limit=limit)
    outcomes = [_deliver_one(pk=pk, fence=fence, now=now) for pk, fence in claims]
    return ApprovalDeliveryReport(
        claimed=len(claims),
        delivered=outcomes.count("delivered"),
        deferred=outcomes.count("deferred"),
        unknown=outcomes.count("unknown"),
    )


__all__ = [
    "APPROVAL_MAX_LIST",
    "ApprovalDecisionResult",
    "ApprovalDeliveryReport",
    "approval_decision_command",
    "dispatch_pending_approvals",
    "get_approval_detail",
    "list_approvals",
    "reconcile_approval",
    "reconcile_conversation_approvals",
    "record_approval_decision",
]
