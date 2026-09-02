"""Message-linked Foundry dispatch and bounded retry state."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from allies.exceptions import (
    FoundryGatewayConflict,
    FoundryGatewayInvalid,
    FoundryGatewayNotFound,
    FoundryGatewayRejected,
    FoundryGatewayRetryable,
    FoundryGatewayUnknownOutcome,
)
from allies.gateways.contracts import (
    ExecutionCommand,
    ExecutionReceipt,
    ReconciliationReceipt,
    canonical_fingerprint,
    canonical_json_bytes,
)
from allies.gateways.foundry import create_execution_intent, reconcile_execution_intent
from allies.models import AllyBinding, BindingStatus
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from chat.exceptions import (
    DispatchConflict,
    DispatchUnavailable,
    OnboardingHandoffRepairRequired,
    OnboardingHandoffUnavailable,
)
from chat.models import (
    DispatchOutbox,
    DispatchState,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessageSender,
)

DISPATCH_LEASE_SECONDS = 60
DISPATCH_MAX_ATTEMPTS = 5
DISPATCH_MAX_BACKOFF_SECONDS = 300


@dataclass(frozen=True, slots=True)
class DispatchReceipt:
    message_id: UUID
    status: str
    attempt_count: int
    command_fingerprint: str


@dataclass(frozen=True, slots=True)
class DispatchReport:
    claimed: int = 0
    accepted: int = 0
    deferred: int = 0
    exhausted: int = 0
    reconciled: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "claimed": self.claimed,
            "accepted": self.accepted,
            "deferred": self.deferred,
            "exhausted": self.exhausted,
            "reconciled": self.reconciled,
        }


def _enabled() -> bool:
    return bool(getattr(settings, "ALLIES_FOUNDRY_EXECUTION_ENABLED", False))


def _command_for_message(message: Message) -> tuple[ExecutionCommand, bytes, str]:
    if (
        message.sender != MessageSender.USER
        or message.origin != MessageOrigin.SEND
        or message.status not in {MessageLifecycle.QUEUED, MessageLifecycle.IN_PROGRESS}
    ):
        raise DispatchConflict("message is not dispatchable")
    try:
        binding_id = message.conversation.ally.binding.id
    except AllyBinding.DoesNotExist:
        raise DispatchUnavailable("ally binding unavailable") from None
    issued_at = timezone.now()
    deadline_at = issued_at + timedelta(seconds=5)
    values = {
        "schema_version": "v1",
        "kind": "execution.command",
        "producer": "cloud",
        "service_identity": "cloud-service",
        "command_id": str(message.id),
        "idempotency_key": str(message.id),
        "scope": {
            "kind": "workspace",
            "cloud_workspace_id": str(message.conversation.ally.workspace_id),
        },
        "conversation_turn_ordinal": message.sequence,
        "cloud": {
            "ally_id": str(message.conversation.ally_id),
            "conversation_id": str(message.conversation_id),
            "message_id": str(message.id),
            "cloud_binding_id": str(binding_id),
        },
        "source_kind": "conversation_message",
        "payload": {"kind": "execution_input", "text": message.content},
        "issued_at": issued_at.isoformat(),
        "deadline_at": deadline_at.isoformat(),
    }
    values["fingerprint"] = canonical_fingerprint(values)
    command = ExecutionCommand.model_validate({**values})
    body = canonical_json_bytes(command.model_dump(mode="json"))
    return command, body, hashlib.sha256(body).hexdigest()


def dispatch_accepted_message(message: Message) -> DispatchReceipt:
    """Persist exactly one command for an accepted message."""

    with transaction.atomic():
        locked = (
            Message.objects.select_for_update()
            .select_related("conversation__ally__workspace")
            .get(pk=message.pk)
        )
        existing = (
            DispatchOutbox.objects.select_for_update().filter(message=locked).first()
        )
        if existing is not None:
            return DispatchReceipt(
                message_id=locked.id,
                status=existing.status,
                attempt_count=existing.attempt_count,
                command_fingerprint=existing.command_fingerprint,
            )
        command, body, body_digest = _command_for_message(locked)
        outbox = DispatchOutbox.objects.create(
            message=locked,
            command_bytes=body,
            command_byte_length=len(body),
            command_sha256=body_digest,
            command_fingerprint=command.fingerprint,
        )
        return DispatchReceipt(
            message_id=locked.id,
            status=outbox.status,
            attempt_count=outbox.attempt_count,
            command_fingerprint=outbox.command_fingerprint,
        )


def _schedule_dispatch() -> None:
    try:
        from chat.tasks import dispatch_pending_messages_task

        dispatch_pending_messages_task.delay()
    except Exception:  # noqa: BLE001 - the durable outbox is the recovery path
        return


def ensure_dispatch_after_accept(message: Message) -> None:
    try:
        dispatch_accepted_message(message)
    except DispatchUnavailable:
        return
    except (DispatchConflict, ValueError):
        DispatchOutbox.objects.get_or_create(
            message=message,
            defaults={
                "status": DispatchState.FAILED,
                "safe_error_code": "command_invalid",
                "next_attempt_at": None,
                "completed_at": timezone.now(),
            },
        )
        return
    if _enabled():
        transaction.on_commit(_schedule_dispatch)


def _claim_due(*, now, limit: int) -> list[tuple[UUID, int, bool]]:
    lease_until = now + timedelta(seconds=DISPATCH_LEASE_SECONDS)
    lease_available = Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now)
    due = (
        Q(
            status__in=[DispatchState.PENDING, DispatchState.RECONCILIATION_NEEDED],
            next_attempt_at__lte=now,
        )
        & lease_available
    ) | Q(status=DispatchState.IN_PROGRESS, lease_expires_at__lte=now)
    with transaction.atomic():
        query = DispatchOutbox.objects.filter(due).order_by(
            "message__conversation_id", "message__sequence", "next_attempt_at", "id"
        )
        query = query.select_for_update(
            skip_locked=connection.features.has_select_for_update_skip_locked
        )
        claimed: list[tuple[UUID, int, bool]] = []
        for row in query[: max(1, min(limit, 100))]:
            reconcile_first = row.status in {
                DispatchState.RECONCILIATION_NEEDED,
                DispatchState.IN_PROGRESS,
            }
            if row.attempt_count >= DISPATCH_MAX_ATTEMPTS and row.status in {
                DispatchState.PENDING,
                DispatchState.RECONCILIATION_NEEDED,
            }:
                row.status = DispatchState.RECONCILIATION_NEEDED
                row.safe_error_code = "dispatch_attempts_exhausted"
                reconcile_first = True
            if row.attempt_count < DISPATCH_MAX_ATTEMPTS:
                row.attempt_count += 1
            row.status = DispatchState.IN_PROGRESS
            row.last_attempt_at = now
            row.lease_expires_at = lease_until
            row.save(
                update_fields=(
                    "attempt_count",
                    "status",
                    "safe_error_code",
                    "last_attempt_at",
                    "lease_expires_at",
                    "updated_at",
                )
            )
            claimed.append((row.pk, row.attempt_count, reconcile_first))
        return claimed


def _backoff_seconds(attempt: int) -> float:
    base = min(DISPATCH_MAX_BACKOFF_SECONDS, 2 ** max(0, attempt - 1))
    return base * (1 + random.random() * 0.25)


def _receipt_digest(receipt: ExecutionReceipt | ReconciliationReceipt) -> str:
    return hashlib.sha256(
        canonical_json_bytes(receipt.model_dump(mode="json"))
    ).hexdigest()


def _mark_deferred(
    pk: UUID, fence: int, code: str, *, now, reconciliation: bool = False
) -> bool:
    status = (
        DispatchState.RECONCILIATION_NEEDED if reconciliation else DispatchState.PENDING
    )
    delay = _backoff_seconds(fence)
    return bool(
        DispatchOutbox.objects.filter(
            pk=pk, attempt_count=fence, status=DispatchState.IN_PROGRESS
        ).update(
            status=status,
            safe_error_code=code,
            next_attempt_at=now + timedelta(seconds=delay),
            lease_expires_at=None,
        )
    )


def _mark_binding_pending(pk: UUID, fence: int, *, now) -> bool:
    return bool(
        DispatchOutbox.objects.filter(
            pk=pk, attempt_count=fence, status=DispatchState.IN_PROGRESS
        ).update(
            status=DispatchState.PENDING,
            attempt_count=max(0, fence - 1),
            safe_error_code="binding_pending",
            next_attempt_at=now + timedelta(seconds=_backoff_seconds(fence)),
            lease_expires_at=None,
        )
    )


def _mark_prior_turn_pending(pk: UUID, fence: int, *, now) -> bool:
    return bool(
        DispatchOutbox.objects.filter(
            pk=pk, attempt_count=fence, status=DispatchState.IN_PROGRESS
        ).update(
            status=DispatchState.PENDING,
            attempt_count=max(0, fence - 1),
            safe_error_code="prior_turn_pending",
            next_attempt_at=now + timedelta(seconds=_backoff_seconds(fence)),
            lease_expires_at=None,
        )
    )


def _prior_turn_ready(message: Message) -> bool:
    prior = (
        Message.objects.filter(
            conversation_id=message.conversation_id,
            sender=MessageSender.USER,
            sequence__lt=message.sequence,
        )
        .order_by("-sequence", "-id")
        .first()
    )
    if prior is None:
        return True
    if prior.origin == MessageOrigin.ONBOARDING:
        return False
    if prior.origin != MessageOrigin.SEND:
        return False
    prior_outbox = (
        DispatchOutbox.objects.filter(message_id=prior.id)
        .only("status", "next_attempt_at")
        .first()
    )
    if prior_outbox is None:
        try:
            dispatch_accepted_message(prior)
        except DispatchUnavailable:
            DispatchOutbox.objects.get_or_create(
                message=prior,
                defaults={
                    "status": DispatchState.FAILED,
                    "safe_error_code": "binding_unavailable",
                    "next_attempt_at": None,
                    "completed_at": timezone.now(),
                },
            )
        except (DispatchConflict, ValueError):
            DispatchOutbox.objects.get_or_create(
                message=prior,
                defaults={
                    "status": DispatchState.FAILED,
                    "safe_error_code": "command_invalid",
                    "next_attempt_at": None,
                    "completed_at": timezone.now(),
                },
            )
        prior_outbox = (
            DispatchOutbox.objects.filter(message_id=prior.id)
            .only("status", "next_attempt_at")
            .first()
        )
    if prior_outbox is None:
        return False
    if (
        prior_outbox.status == DispatchState.RECONCILIATION_NEEDED
        and prior_outbox.next_attempt_at is None
    ):
        return True
    return prior_outbox.status in {
        DispatchState.ACCEPTED,
        DispatchState.FAILED,
    }


def _reconcile_onboarding_before_dispatch(message: Message) -> None:
    from .conversations import reconcile_onboarding_reply

    reconcile_onboarding_reply(ally=message.conversation.ally)
    if (
        message.conversation.is_default
        and message.sequence > 2
        and not Message.objects.filter(
            conversation_id=message.conversation_id,
            sequence=2,
            sender=MessageSender.USER,
        ).exists()
    ):
        raise OnboardingHandoffUnavailable("onboarding handoff unavailable")


def _mark_terminal(
    pk: UUID, fence: int, status: str, code: str, *, now, receipt_digest: str = ""
) -> bool:
    values = {
        "status": status,
        "safe_error_code": code,
        "receipt_digest": receipt_digest,
        "lease_expires_at": None,
        "next_attempt_at": None,
        "completed_at": now
        if status in {DispatchState.ACCEPTED, DispatchState.FAILED}
        else None,
    }
    if status in {DispatchState.ACCEPTED, DispatchState.FAILED}:
        values["command_bytes"] = b""
        values["command_byte_length"] = 0
    return bool(
        DispatchOutbox.objects.filter(
            pk=pk, attempt_count=fence, status=DispatchState.IN_PROGRESS
        ).update(**values)
    )


def _mark_reconciliation_exhausted(pk: UUID, fence: int, *, now) -> bool:
    return bool(
        DispatchOutbox.objects.filter(
            pk=pk, attempt_count=fence, status=DispatchState.IN_PROGRESS
        ).update(
            status=DispatchState.RECONCILIATION_NEEDED,
            safe_error_code="dispatch_attempts_exhausted",
            command_bytes=b"",
            command_byte_length=0,
            next_attempt_at=None,
            lease_expires_at=None,
            completed_at=now,
        )
    )


def _reconcile_one(
    pk: UUID,
    fence: int,
    outbox: DispatchOutbox,
    *,
    now,
    permit_post: bool,
) -> str | None:
    try:
        reconciliation = reconcile_execution_intent(
            outbox.message_id, outbox.command_fingerprint
        )
    except FoundryGatewayUnknownOutcome:
        _mark_deferred(
            pk, fence, "reconciliation_unavailable", now=now, reconciliation=True
        )
        return "deferred"
    except (
        FoundryGatewayConflict,
        FoundryGatewayInvalid,
        FoundryGatewayRejected,
        FoundryGatewayNotFound,
    ):
        _mark_terminal(
            pk, fence, DispatchState.FAILED, "reconciliation_conflict", now=now
        )
        return "failed"
    if reconciliation.status == "accepted":
        if (
            (
                reconciliation.command_id is not None
                and reconciliation.command_id != outbox.message_id
            )
            or reconciliation.idempotency_key != outbox.message_id
            or reconciliation.fingerprint != outbox.command_fingerprint
        ):
            _mark_terminal(
                pk,
                fence,
                DispatchState.FAILED,
                "receipt_identity_mismatch",
                now=now,
            )
            return "failed"
        updated = _mark_terminal(
            pk,
            fence,
            DispatchState.ACCEPTED,
            "",
            now=now,
            receipt_digest=_receipt_digest(reconciliation),
        )
        return "reconciled" if updated else "deferred"
    if reconciliation.status == "not_found":
        if permit_post and fence < DISPATCH_MAX_ATTEMPTS and outbox.command_bytes:
            return None
        if fence >= DISPATCH_MAX_ATTEMPTS:
            _mark_reconciliation_exhausted(pk, fence, now=now)
            return "exhausted"
        _mark_deferred(pk, fence, "not_found", now=now, reconciliation=True)
        return "deferred"
    _mark_terminal(pk, fence, DispatchState.FAILED, "reconciliation_conflict", now=now)
    return "failed"


def _dispatch_one(pk: UUID, fence: int, reconcile_first: bool, *, now) -> str:
    outbox = DispatchOutbox.objects.select_related(
        "message__conversation__ally__binding"
    ).get(pk=pk)
    try:
        binding_status = outbox.message.conversation.ally.binding.status
    except AllyBinding.DoesNotExist:
        _mark_terminal(pk, fence, DispatchState.FAILED, "binding_unavailable", now=now)
        return "failed"
    if binding_status == BindingStatus.INCOMPATIBLE:
        _mark_terminal(pk, fence, DispatchState.FAILED, "binding_incompatible", now=now)
        return "failed"
    if binding_status != BindingStatus.BOUND:
        _mark_binding_pending(pk, fence, now=now)
        return "deferred"
    try:
        _reconcile_onboarding_before_dispatch(outbox.message)
    except (OnboardingHandoffUnavailable, OnboardingHandoffRepairRequired) as exc:
        _mark_terminal(pk, fence, DispatchState.FAILED, exc.code, now=now)
        return "failed"
    if not _prior_turn_ready(outbox.message):
        _mark_prior_turn_pending(pk, fence, now=now)
        return "deferred"
    if reconcile_first:
        reconciled = _reconcile_one(pk, fence, outbox, now=now, permit_post=True)
        if reconciled is not None:
            return reconciled
    if not outbox.command_bytes:
        _mark_deferred(pk, fence, "command_unavailable", now=now, reconciliation=True)
        return "deferred"
    try:
        command = ExecutionCommand.model_validate_json(bytes(outbox.command_bytes))
        receipt = create_execution_intent(command, raw_body=bytes(outbox.command_bytes))
    except FoundryGatewayUnknownOutcome:
        return (
            _reconcile_one(pk, fence, outbox, now=now, permit_post=False) or "deferred"
        )
    except FoundryGatewayRetryable:
        if fence >= DISPATCH_MAX_ATTEMPTS:
            _mark_reconciliation_exhausted(pk, fence, now=now)
            return "exhausted"
        _mark_deferred(pk, fence, "foundry_unavailable", now=now)
        return "deferred"
    except FoundryGatewayConflict:
        _mark_terminal(pk, fence, DispatchState.FAILED, "fingerprint_conflict", now=now)
        return "failed"
    except FoundryGatewayNotFound:
        _mark_terminal(pk, fence, DispatchState.FAILED, "binding_unavailable", now=now)
        return "failed"
    except (FoundryGatewayInvalid, FoundryGatewayRejected, ValueError):
        _mark_terminal(pk, fence, DispatchState.FAILED, "foundry_rejected", now=now)
        return "failed"
    if (
        receipt.command_id != command.command_id
        or receipt.idempotency_key != command.idempotency_key
        or receipt.fingerprint != outbox.command_fingerprint
    ):
        _mark_terminal(
            pk, fence, DispatchState.FAILED, "receipt_identity_mismatch", now=now
        )
        return "failed"
    digest = _receipt_digest(receipt)
    updated = _mark_terminal(
        pk,
        fence,
        DispatchState.ACCEPTED,
        "",
        now=now,
        receipt_digest=digest,
    )
    return "accepted" if updated else "deferred"


def dispatch_pending_messages(*, now=None, limit: int = 20) -> DispatchReport:
    if not _enabled():
        return DispatchReport()
    now = now or timezone.now()
    claims = _claim_due(now=now, limit=limit)
    outcomes = [
        _dispatch_one(pk, fence, reconcile_first, now=now)
        for pk, fence, reconcile_first in claims
    ]
    return DispatchReport(
        claimed=len(claims),
        accepted=outcomes.count("accepted"),
        deferred=outcomes.count("deferred"),
        exhausted=outcomes.count("exhausted"),
        reconciled=outcomes.count("reconciled"),
    )


__all__ = [
    "DispatchReceipt",
    "DispatchReport",
    "dispatch_accepted_message",
    "dispatch_pending_messages",
    "ensure_dispatch_after_accept",
]
