"""Bounded lease helpers for authenticated revision-9 routine dispatch."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator

from allies.exceptions import (
    FoundryGatewayConflict,
    FoundryGatewayInvalid,
    FoundryGatewayNotFound,
    FoundryGatewayRejected,
    FoundryGatewayRetryable,
    FoundryGatewayUnknownOutcome,
)
from allies.gateways.contracts import (
    MAX_COMMAND_TEXT_BYTES,
    RoutineDispatchReceipt,
    RoutineEnvelope,
    canonical_json_bytes,
)
from allies.gateways.foundry import accept_routine_dispatch

from ..models import RoutineDispatchOutbox, RoutineDispatchState

ROUTINE_DISPATCH_LEASE_SECONDS = 60
ROUTINE_DISPATCH_MAX_ATTEMPTS = 5


class RoutineDispatchReconciliationUnavailable(ValueError):
    """A late dispatch receipt has no matching Cloud command."""


class RoutineDispatchReconciliationConflict(ValueError):
    """A late dispatch receipt conflicts with the immutable Cloud command."""


@dataclass(frozen=True, slots=True)
class RoutineDispatchLease:
    outbox_id: UUID
    command_id: UUID
    attempt_count: int
    lease_expires_at: datetime
    command_bytes: bytes
    idempotency_key: UUID | None = None


@dataclass(frozen=True, slots=True)
class RoutineDispatchReport:
    claimed: int = 0
    deferred: int = 0
    accepted: int = 0
    reconciliation: int = 0
    disabled: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "claimed": self.claimed,
            "deferred": self.deferred,
            "accepted": self.accepted,
            "reconciliation": self.reconciliation,
            "disabled": self.disabled,
        }


def _utc(value: datetime | None) -> datetime:
    current = value or timezone.now()
    if current.tzinfo is None:
        raise ValueError("routine dispatch timestamps must be timezone-aware")
    return current.astimezone(UTC).replace(microsecond=0)


def _enabled() -> bool:
    return bool(getattr(settings, "ALLIES_ROUTINE_DISPATCH_ENABLED", False))


def claim_pending_routine_dispatches(
    *, now: datetime | None = None, limit: int = 20
) -> tuple[RoutineDispatchLease, ...]:
    """Claim durable outboxes with a lease fence, without performing network I/O."""

    boundary = _utc(now)
    bound = max(1, min(int(limit), 100))
    due = (
        Q(
            status__in=(
                RoutineDispatchState.PENDING,
                RoutineDispatchState.RECONCILIATION_NEEDED,
            ),
            next_attempt_at__lte=boundary,
        )
        & (Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=boundary))
    ) | Q(status=RoutineDispatchState.IN_PROGRESS, lease_expires_at__lte=boundary)
    ids = list(
        RoutineDispatchOutbox.objects.filter(due)
        .order_by("next_attempt_at", "id")
        .values_list("id", flat=True)[:bound]
    )
    lease_until = boundary + timedelta(seconds=ROUTINE_DISPATCH_LEASE_SECONDS)
    claimed: list[RoutineDispatchLease] = []
    with transaction.atomic():
        for outbox_id in ids:
            try:
                row = RoutineDispatchOutbox.objects.select_for_update(
                    skip_locked=connection.features.has_select_for_update_skip_locked
                ).get(pk=outbox_id)
            except RoutineDispatchOutbox.DoesNotExist:
                continue
            if row.status in {
                RoutineDispatchState.PENDING,
                RoutineDispatchState.RECONCILIATION_NEEDED,
            }:
                if row.next_attempt_at is not None and row.next_attempt_at > boundary:
                    continue
                if row.lease_expires_at is not None and row.lease_expires_at > boundary:
                    continue
            elif row.status == RoutineDispatchState.IN_PROGRESS:
                if row.lease_expires_at is None or row.lease_expires_at > boundary:
                    continue
            else:
                continue
            if row.attempt_count >= ROUTINE_DISPATCH_MAX_ATTEMPTS:
                row.status = RoutineDispatchState.RECONCILIATION_NEEDED
                row.safe_error_code = "dispatch_attempts_exhausted"
                row.next_attempt_at = None
                row.lease_expires_at = None
                row.save(
                    update_fields=(
                        "status",
                        "safe_error_code",
                        "next_attempt_at",
                        "lease_expires_at",
                        "updated_at",
                    )
                )
                continue
            row.attempt_count += 1
            row.status = RoutineDispatchState.IN_PROGRESS
            row.last_attempt_at = boundary
            row.lease_expires_at = lease_until
            row.save(
                update_fields=(
                    "attempt_count",
                    "status",
                    "last_attempt_at",
                    "lease_expires_at",
                    "updated_at",
                )
            )
            claimed.append(
                RoutineDispatchLease(
                    outbox_id=row.id,
                    command_id=row.command_id,
                    idempotency_key=row.idempotency_key,
                    attempt_count=row.attempt_count,
                    lease_expires_at=lease_until,
                    command_bytes=bytes(row.command_bytes),
                )
            )
    return tuple(claimed)


class RoutineDispatchCommand(RoutineEnvelope):
    """Strict Cloud-side parser for the persisted implementation-facing command."""

    kind: Literal["routine.dispatch"]
    producer: Literal["cloud"]
    service_identity: Literal["cloud-service"]
    command_id: UUID
    idempotency_key: UUID
    routine_id: UUID
    routine_revision: StrictInt = Field(ge=1)
    schedule_generation: StrictInt = Field(ge=1)
    occurrence_id: UUID
    run_id: UUID
    schedule: dict[str, Any]
    scheduled_at: datetime
    delayed: StrictBool
    occurrence_disposition: Literal[
        "admitted",
        "replay",
        "skipped_active",
        "delayed",
        "recovered",
        "cancelled",
    ]
    main_conversation_id: UUID
    run_conversation_id: UUID
    cloud_binding_id: UUID
    execution_prompt: StrictStr = Field(min_length=1, max_length=MAX_COMMAND_TEXT_BYTES)
    title_snapshot: StrictStr = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_dispatch(self) -> RoutineDispatchCommand:
        if self.cloud_binding_id != self.scope.cloud_binding_id:
            raise ValueError("routine dispatch binding conflicts with scope")
        if self.main_conversation_id == self.run_conversation_id:
            raise ValueError("routine dispatch conversations must be distinct")
        if len(self.execution_prompt.encode("utf-8")) > MAX_COMMAND_TEXT_BYTES:
            raise ValueError("routine dispatch prompt is too large")
        if self.scheduled_at.tzinfo is None:
            raise ValueError("routine dispatch scheduled_at must be timezone-aware")
        if not self.schedule.get("kind") or not self.schedule.get("timezone"):
            raise ValueError("routine dispatch schedule snapshot is incomplete")
        return self


def _parse_dispatch_command(lease: RoutineDispatchLease) -> RoutineDispatchCommand:
    try:
        parsed = json.loads(lease.command_bytes)
        if not isinstance(parsed, dict):
            raise TypeError("routine dispatch must be an object")
        if canonical_json_bytes(parsed) != lease.command_bytes:
            raise ValueError("routine dispatch bytes are not canonical")
        command = RoutineDispatchCommand.model_validate(parsed)
    except (TypeError, UnicodeDecodeError, ValueError) as exc:
        raise FoundryGatewayInvalid("routine dispatch command is invalid") from exc
    if command.command_id != lease.command_id or (
        lease.idempotency_key is not None
        and command.idempotency_key != lease.idempotency_key
    ):
        raise FoundryGatewayInvalid("routine dispatch identity conflicts")
    return command


def _receipt_digest(receipt) -> str:
    return hashlib.sha256(
        canonical_json_bytes(receipt.model_dump(mode="json"))
    ).hexdigest()


def _validate_dispatch_receipt(command: RoutineDispatchCommand, receipt) -> None:
    if (
        receipt.command_id != command.command_id
        or receipt.idempotency_key != command.idempotency_key
        or receipt.occurrence_id != command.occurrence_id
        or receipt.run_id != command.run_id
        or receipt.scope != command.scope
        or receipt.outcome not in {"accepted", "duplicate"}
        or receipt.acceptance_is_completion is not False
    ):
        raise FoundryGatewayInvalid("routine dispatch receipt identity conflicts")


def _settle_transport_failure(
    lease: RoutineDispatchLease,
    exc: Exception,
    *,
    now: datetime | None,
) -> str:
    if isinstance(
        exc,
        (
            FoundryGatewayUnknownOutcome,
            FoundryGatewayConflict,
            FoundryGatewayNotFound,
            FoundryGatewayRetryable,
        ),
    ):
        status = RoutineDispatchState.RECONCILIATION_NEEDED
    else:
        status = RoutineDispatchState.FAILED
    settle_routine_dispatch(
        lease,
        status=status,
        safe_error_code=getattr(exc, "code", "routine_dispatch_failed"),
        now=now,
    )
    return status


@transaction.atomic
def settle_routine_dispatch(
    lease: RoutineDispatchLease,
    *,
    status: RoutineDispatchState,
    receipt_digest: str = "",
    safe_error_code: str = "",
    execution_id: UUID | str | None = None,
    attempt_id: UUID | str | None = None,
    generation: int | None = None,
    now: datetime | None = None,
) -> bool:
    """Settle only the currently held lease; stale workers cannot overwrite it."""

    boundary = _utc(now)
    row = (
        RoutineDispatchOutbox.objects.select_for_update()
        .filter(
            pk=lease.outbox_id,
            command_id=lease.command_id,
            status=RoutineDispatchState.IN_PROGRESS,
            lease_expires_at=lease.lease_expires_at,
        )
        .first()
    )
    if row is None:
        return False
    if status not in {
        RoutineDispatchState.ACCEPTED,
        RoutineDispatchState.RECONCILIATION_NEEDED,
        RoutineDispatchState.FAILED,
    }:
        raise ValueError("routine dispatch settlement status is invalid")
    if status == RoutineDispatchState.ACCEPTED:
        if execution_id is None or attempt_id is None or generation is None:
            raise ValueError("accepted routine dispatch requires Foundry identity")
        execution_id = UUID(str(execution_id))
        attempt_id = UUID(str(attempt_id))
        if generation < 0:
            raise ValueError("routine dispatch generation is invalid")
    elif any(value is not None for value in (execution_id, attempt_id, generation)):
        raise ValueError("Foundry identity is only valid for accepted dispatches")
    row.status = status
    row.execution_id = execution_id
    row.attempt_id = attempt_id
    row.generation = generation
    row.receipt_digest = receipt_digest
    row.safe_error_code = safe_error_code
    row.lease_expires_at = None
    row.completed_at = (
        boundary
        if status
        in {
            RoutineDispatchState.ACCEPTED,
            RoutineDispatchState.FAILED,
        }
        else None
    )
    row.next_attempt_at = (
        None if status != RoutineDispatchState.RECONCILIATION_NEEDED else boundary
    )
    row.save(
        update_fields=(
            "status",
            "execution_id",
            "attempt_id",
            "generation",
            "receipt_digest",
            "safe_error_code",
            "lease_expires_at",
            "completed_at",
            "next_attempt_at",
            "updated_at",
        )
    )
    return True


@transaction.atomic
def reconcile_late_routine_dispatch_receipt(
    receipt: RoutineDispatchReceipt,
    *,
    now: datetime | None = None,
) -> str:
    """Apply one authenticated Foundry receipt after bounded delivery exhaustion."""

    outbox = (
        RoutineDispatchOutbox.objects.select_for_update()
        .filter(
            command_id=receipt.command_id,
            idempotency_key=receipt.idempotency_key,
        )
        .first()
    )
    if outbox is None:
        raise RoutineDispatchReconciliationUnavailable(
            "routine dispatch receipt has no Cloud command"
        )
    try:
        raw_command = bytes(outbox.command_bytes)
        if canonical_json_bytes(json.loads(raw_command)) != raw_command:
            raise ValueError("routine dispatch command is not canonical")
        command = RoutineDispatchCommand.model_validate_json(raw_command)
        if outbox.command_fingerprint != command.fingerprint:
            raise ValueError("routine dispatch fingerprint is not preserved")
        _validate_dispatch_receipt(command, receipt)
    except (FoundryGatewayInvalid, TypeError, ValueError) as exc:
        raise RoutineDispatchReconciliationConflict(
            "routine dispatch receipt conflicts with Cloud command"
        ) from exc
    if outbox.status == RoutineDispatchState.ACCEPTED:
        if (
            outbox.execution_id == receipt.execution_id
            and outbox.attempt_id == receipt.attempt_id
            and outbox.generation == receipt.generation
            and outbox.receipt_digest == _receipt_digest(receipt)
        ):
            return "duplicate"
        raise RoutineDispatchReconciliationConflict(
            "routine dispatch receipt conflicts with accepted identity"
        )
    if (
        outbox.status != RoutineDispatchState.RECONCILIATION_NEEDED
        or outbox.safe_error_code != "dispatch_attempts_exhausted"
        or outbox.execution_id is not None
        or outbox.attempt_id is not None
        or outbox.generation is not None
    ):
        raise RoutineDispatchReconciliationConflict(
            "routine dispatch is not eligible for late reconciliation"
        )
    boundary = _utc(now)
    outbox.status = RoutineDispatchState.ACCEPTED
    outbox.execution_id = receipt.execution_id
    outbox.attempt_id = receipt.attempt_id
    outbox.generation = receipt.generation
    outbox.receipt_digest = _receipt_digest(receipt)
    outbox.safe_error_code = "late_acceptance_reconciled"
    outbox.lease_expires_at = None
    outbox.next_attempt_at = None
    outbox.completed_at = boundary
    outbox.save(
        update_fields=(
            "status",
            "execution_id",
            "attempt_id",
            "generation",
            "receipt_digest",
            "safe_error_code",
            "lease_expires_at",
            "next_attempt_at",
            "completed_at",
            "updated_at",
        )
    )
    return "applied"


def dispatch_pending_routine_outboxes(
    *, now: datetime | None = None, limit: int = 20
) -> RoutineDispatchReport:
    """Run the transport seam without claiming work when the adapter is disabled."""

    if not _enabled():
        return RoutineDispatchReport(disabled=1)
    leases = claim_pending_routine_dispatches(now=now, limit=limit)
    if not leases:
        return RoutineDispatchReport()
    accepted = 0
    deferred = 0
    reconciliation = 0
    for lease in leases:
        try:
            command = _parse_dispatch_command(lease)
            receipt = accept_routine_dispatch(raw_body=lease.command_bytes)
            _validate_dispatch_receipt(command, receipt)
        except (FoundryGatewayRetryable, FoundryGatewayUnknownOutcome) as exc:
            _settle_transport_failure(lease, exc, now=now)
            deferred += 1
            reconciliation += 1
        except (
            FoundryGatewayConflict,
            FoundryGatewayNotFound,
            FoundryGatewayInvalid,
            FoundryGatewayRejected,
        ) as exc:
            status = _settle_transport_failure(lease, exc, now=now)
            if status == RoutineDispatchState.RECONCILIATION_NEEDED:
                deferred += 1
                reconciliation += 1
        else:
            settled = settle_routine_dispatch(
                lease,
                status=RoutineDispatchState.ACCEPTED,
                receipt_digest=_receipt_digest(receipt),
                execution_id=receipt.execution_id,
                attempt_id=receipt.attempt_id,
                generation=receipt.generation,
                now=now,
            )
            if settled:
                accepted += 1
    return RoutineDispatchReport(
        claimed=len(leases),
        deferred=deferred,
        accepted=accepted,
        reconciliation=reconciliation,
    )


__all__ = [
    "RoutineDispatchCommand",
    "RoutineDispatchLease",
    "RoutineDispatchReconciliationConflict",
    "RoutineDispatchReconciliationUnavailable",
    "RoutineDispatchReport",
    "claim_pending_routine_dispatches",
    "dispatch_pending_routine_outboxes",
    "reconcile_late_routine_dispatch_receipt",
    "settle_routine_dispatch",
]
