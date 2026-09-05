from __future__ import annotations

import json
import random
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from runtime.contracts import (
    EventDeliveryReceipt,
    FoundryEventEnvelope,
    build_event_envelope,
    event_envelope_bytes,
    validate_event,
)
from runtime.exceptions import RuntimeConflictError, RuntimeValidationError
from runtime.models import (
    EventDeliveryState,
    ExecutionEvent,
    ExecutionEventDelivery,
)

DELIVERY_LEASE_SECONDS = 60
MAX_DELIVERY_ATTEMPTS = 8
MAX_DELIVERY_BATCH = 20
MAX_DELIVERY_BACKOFF_SECONDS = 300
MAX_RESPONSE_BYTES = 8 * 1024
REPAIR_DELAY_SECONDS = 300
MAX_AUTOMATIC_REPAIR_CYCLES = 3


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True, slots=True)
class EventDeliveryClaim:
    delivery_id: UUID
    envelope_bytes: bytes
    attempt: int
    repair_cycle: int = 0


@dataclass(frozen=True, slots=True)
class DeliveryReport:
    claimed: int = 0
    delivered: int = 0
    deferred: int = 0
    exhausted: int = 0
    repair_pending: int = 0
    recovered: int = 0


@dataclass(frozen=True, slots=True)
class RedriveReport:
    requested: int = 0
    validated: int = 0
    redriven: int = 0
    skipped: int = 0


def enqueue_event_delivery(event: ExecutionEvent) -> ExecutionEventDelivery | None:
    """Create one wire outbox row for a contract-visible FND-007 event."""

    execution = event.attempt.execution
    envelope = build_event_envelope(execution, event.attempt, event)
    if envelope is None:
        return None
    encoded = event_envelope_bytes(envelope)
    existing = ExecutionEventDelivery.objects.filter(event_id=event.id).first()
    if existing is not None:
        if existing.fingerprint != envelope.fingerprint:
            raise RuntimeConflictError(
                "event delivery identity conflicts with stored state"
            )
        return existing
    return ExecutionEventDelivery.objects.create(
        event=event,
        envelope_bytes=encoded,
        byte_length=len(encoded),
        fingerprint=envelope.fingerprint,
        state=EventDeliveryState.PENDING,
        delivery_attempts=0,
        next_attempt_at=event.created_at or timezone.now(),
    )


def claim_event_deliveries(
    limit: int = MAX_DELIVERY_BATCH,
    *,
    now: datetime | None = None,
) -> tuple[EventDeliveryClaim, ...]:
    if isinstance(limit, bool) or not 1 <= limit <= MAX_DELIVERY_BATCH:
        raise RuntimeValidationError("delivery limit must be between 1 and 20")
    observed_at = now or timezone.now()

    with transaction.atomic():
        # An expired eighth claim has no attempt left in this repair cycle.
        # Rebuild its immutable wire envelope from the retained event before
        # moving it back to PENDING for a later repair cycle.
        expired_final_rows = list(
            ExecutionEventDelivery.objects.select_for_update()
            .filter(
                state=EventDeliveryState.DELIVERING,
                delivery_attempts=MAX_DELIVERY_ATTEMPTS,
                lease_expires_at__lte=observed_at,
            )
            .order_by("next_attempt_at", "created_at", "id")[:limit]
        )
        for row in expired_final_rows:
            _transition_to_repair(
                row,
                observed_at=observed_at,
                safe_error_code="delivery_lease_expired",
            )
        rows = list(
            ExecutionEventDelivery.objects.select_for_update()
            .filter(
                state__in=(EventDeliveryState.PENDING, EventDeliveryState.DELIVERING),
                next_attempt_at__lte=observed_at,
                delivery_attempts__lt=MAX_DELIVERY_ATTEMPTS,
            )
            .filter(
                Q(state=EventDeliveryState.PENDING)
                | Q(
                    state=EventDeliveryState.DELIVERING,
                    lease_expires_at__lte=observed_at,
                )
            )
            .order_by("next_attempt_at", "created_at", "id")[:limit]
        )
        claims: list[EventDeliveryClaim] = []
        for row in rows:
            row.state = EventDeliveryState.DELIVERING
            row.delivery_attempts += 1
            row.lease_expires_at = observed_at + timedelta(
                seconds=DELIVERY_LEASE_SECONDS
            )
            row.save(
                update_fields=[
                    "state",
                    "delivery_attempts",
                    "lease_expires_at",
                    "updated_at",
                ]
            )
            claims.append(
                EventDeliveryClaim(
                    row.id,
                    bytes(row.envelope_bytes),
                    row.delivery_attempts,
                    row.repair_cycle,
                )
            )
    return tuple(claims)


def mark_event_delivery(
    delivery_id: UUID,
    *,
    attempt: int,
    success: bool,
    safe_error_code: str = "",
    terminal: bool = False,
    repair_cycle: int,
    now: datetime | None = None,
) -> ExecutionEventDelivery | None:
    observed_at = now or timezone.now()
    if (
        isinstance(repair_cycle, bool)
        or not isinstance(repair_cycle, int)
        or repair_cycle < 0
    ):
        raise RuntimeValidationError("delivery repair cycle is invalid")

    with transaction.atomic():
        row = ExecutionEventDelivery.objects.select_for_update().get(pk=delivery_id)
        if (
            row.state != EventDeliveryState.DELIVERING
            or row.delivery_attempts != attempt
            or row.repair_cycle != repair_cycle
        ):
            return None
        if success:
            row.state = EventDeliveryState.DELIVERED
            row.delivered_at = observed_at
            row.lease_expires_at = None
            row.safe_error_code = ""
        else:
            if safe_error_code and not _safe_error_code(safe_error_code):
                raise RuntimeValidationError("delivery error code is invalid")
            row.safe_error_code = safe_error_code or "delivery_failed"
            row.lease_expires_at = None
            if terminal:
                row.state = EventDeliveryState.EXHAUSTED
            elif row.delivery_attempts >= MAX_DELIVERY_ATTEMPTS:
                _transition_to_repair(
                    row,
                    observed_at=observed_at,
                    safe_error_code=row.safe_error_code,
                )
                return row
            else:
                row.state = EventDeliveryState.PENDING
                row.next_attempt_at = observed_at + timedelta(
                    seconds=_backoff_seconds(row.delivery_attempts)
                )
        if row.state in {EventDeliveryState.DELIVERED, EventDeliveryState.EXHAUSTED}:
            row.envelope_bytes = b""
            row.byte_length = 0
        row.save(
            update_fields=[
                "envelope_bytes",
                "byte_length",
                "state",
                "repair_cycle",
                "delivered_at",
                "lease_expires_at",
                "safe_error_code",
                "next_attempt_at",
                "updated_at",
            ]
        )
    return row


def publish_pending_event_deliveries(limit: int = MAX_DELIVERY_BATCH) -> DeliveryReport:
    """Deliver a bounded batch; the outbox remains the retry authority."""

    if not getattr(settings, "ALLIES_CLOUD_EVENT_DELIVERY_ENABLED", False):
        return DeliveryReport()
    claims = claim_event_deliveries(limit)
    delivered = deferred = exhausted = repair_pending = recovered = 0
    for claim in claims:
        status, code = _post_to_cloud(claim.envelope_bytes)
        if status == 202:
            marked = mark_event_delivery(
                claim.delivery_id,
                attempt=claim.attempt,
                success=True,
                repair_cycle=claim.repair_cycle,
            )
            if marked is not None:
                delivered += 1
                recovered += int(claim.repair_cycle > 0)
            else:
                deferred += 1
        elif status in (401, 403, 404, 422) or (status == 409 and code == "conflict"):
            marked = mark_event_delivery(
                claim.delivery_id,
                attempt=claim.attempt,
                success=False,
                safe_error_code=code or "delivery_rejected",
                terminal=True,
                repair_cycle=claim.repair_cycle,
            )
            if marked is None:
                deferred += 1
            else:
                exhausted += int(marked.state == EventDeliveryState.EXHAUSTED)
                deferred += int(marked.state == EventDeliveryState.PENDING)
                repair_pending += int(
                    marked.state == EventDeliveryState.PENDING
                    and marked.repair_cycle > 0
                )
        else:
            marked = mark_event_delivery(
                claim.delivery_id,
                attempt=claim.attempt,
                success=False,
                safe_error_code=code or "delivery_unavailable",
                repair_cycle=claim.repair_cycle,
            )
            if marked is None:
                deferred += 1
            else:
                exhausted += int(marked.state == EventDeliveryState.EXHAUSTED)
                deferred += int(marked.state == EventDeliveryState.PENDING)
                repair_pending += int(
                    marked.state == EventDeliveryState.PENDING
                    and marked.repair_cycle > 0
                )
    return DeliveryReport(
        len(claims), delivered, deferred, exhausted, repair_pending, recovered
    )


def redrive_event_deliveries(
    *,
    delivery_ids: Iterable[UUID | str] = (),
    event_ids: Iterable[UUID | str] = (),
    confirm: bool = False,
    now: datetime | None = None,
) -> RedriveReport:
    """Validate selected retained events and optionally redrive exhausted rows.

    The default is a read-only dry run.  Confirmation only changes existing
    delivery rows; it never creates an execution or an ``ExecutionEvent``.
    """

    delivery_values = _identifier_values(delivery_ids)
    event_values = _identifier_values(event_ids)
    if not delivery_values and not event_values:
        raise RuntimeValidationError("at least one delivery_id or event_id is required")
    try:
        delivery_uuids = tuple(UUID(value) for value in delivery_values)
        event_uuids = tuple(UUID(value) for value in event_values)
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError(
            "delivery and event identifiers must be UUIDs"
        ) from exc

    observed_at = now or timezone.now()
    with transaction.atomic():
        rows_by_id = {
            row.id: row
            for row in ExecutionEventDelivery.objects.select_for_update().filter(
                id__in=delivery_uuids
            )
        }
        rows_by_event = {
            row.event.event_id: row
            for row in ExecutionEventDelivery.objects.select_for_update()
            .select_related("event")
            .filter(event__event_id__in=event_uuids)
        }
        rows: list[ExecutionEventDelivery] = []
        seen: set[UUID] = set()
        for identifier in (*delivery_uuids, *event_uuids):
            row = rows_by_id.get(identifier) or rows_by_event.get(identifier)
            if row is None:
                raise RuntimeValidationError("selected delivery was not found")
            if row.id not in seen:
                seen.add(row.id)
                rows.append(row)

        rebuilt = {row.id: _rebuild_delivery_envelope(row) for row in rows}

        redriven = 0
        skipped = 0
        if confirm:
            for row in rows:
                if row.state != EventDeliveryState.EXHAUSTED:
                    skipped += 1
                    continue
                encoded = rebuilt[row.id]
                row.repair_cycle += 1
                row.delivery_attempts = 0
                row.state = EventDeliveryState.PENDING
                row.envelope_bytes = encoded
                row.byte_length = len(encoded)
                row.lease_expires_at = None
                row.next_attempt_at = observed_at
                row.delivered_at = None
                row.safe_error_code = "manual_redrive"
                row.save(
                    update_fields=[
                        "repair_cycle",
                        "delivery_attempts",
                        "state",
                        "envelope_bytes",
                        "byte_length",
                        "lease_expires_at",
                        "next_attempt_at",
                        "delivered_at",
                        "safe_error_code",
                        "updated_at",
                    ]
                )
                redriven += 1
        return RedriveReport(
            requested=len(rows),
            validated=len(rows),
            redriven=redriven,
            skipped=skipped,
        )


def _transition_to_repair(
    row: ExecutionEventDelivery,
    *,
    observed_at: datetime,
    safe_error_code: str,
) -> bool:
    """Advance a final retryable delivery to a fenced, delayed repair cycle."""

    if not safe_error_code or not _safe_error_code(safe_error_code):
        safe_error_code = "delivery_failed"
    try:
        encoded = _rebuild_delivery_envelope(row)
    except (RuntimeConflictError, RuntimeValidationError):
        _park_exhausted(row, "delivery_source_invalid")
        return False
    if row.repair_cycle >= MAX_AUTOMATIC_REPAIR_CYCLES:
        _park_exhausted(row, "delivery_repair_exhausted")
        return False
    row.repair_cycle += 1
    row.delivery_attempts = 0
    row.state = EventDeliveryState.PENDING
    row.envelope_bytes = encoded
    row.byte_length = len(encoded)
    row.lease_expires_at = None
    row.next_attempt_at = observed_at + timedelta(seconds=REPAIR_DELAY_SECONDS)
    row.safe_error_code = safe_error_code
    row.delivered_at = None
    row.save(
        update_fields=[
            "repair_cycle",
            "delivery_attempts",
            "state",
            "envelope_bytes",
            "byte_length",
            "lease_expires_at",
            "next_attempt_at",
            "safe_error_code",
            "delivered_at",
            "updated_at",
        ]
    )
    return True


def _park_exhausted(row: ExecutionEventDelivery, safe_error_code: str) -> None:
    row.state = EventDeliveryState.EXHAUSTED
    row.lease_expires_at = None
    row.safe_error_code = safe_error_code
    row.envelope_bytes = b""
    row.byte_length = 0
    row.save(
        update_fields=[
            "state",
            "lease_expires_at",
            "safe_error_code",
            "envelope_bytes",
            "byte_length",
            "updated_at",
        ]
    )


def _rebuild_delivery_envelope(
    row: ExecutionEventDelivery,
) -> bytes:
    """Rebuild and verify a row's canonical payload from its retained event."""

    event = (
        ExecutionEvent.objects.select_related("attempt__execution")
        .filter(pk=row.event_id)
        .first()
    )
    if event is None:
        raise RuntimeConflictError("event delivery source event is unavailable")
    envelope = build_event_envelope(event.attempt.execution, event.attempt, event)
    if envelope is None:
        raise RuntimeConflictError("event delivery source event is not publishable")
    encoded = event_envelope_bytes(envelope)
    if envelope.fingerprint != row.fingerprint:
        raise RuntimeConflictError(
            "event delivery fingerprint does not match retained event"
        )
    if not row.byte_length and row.state not in {
        EventDeliveryState.EXHAUSTED,
        EventDeliveryState.DELIVERED,
    }:
        raise RuntimeConflictError("event delivery envelope is missing")
    if row.byte_length and bytes(row.envelope_bytes) != encoded:
        raise RuntimeConflictError(
            "event delivery envelope differs from retained event"
        )
    return encoded


def _identifier_values(
    values: Iterable[UUID | str] | UUID | str | None,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (UUID, str)):
        values = (values,)
    return tuple(str(value) for value in values)


def _post_to_cloud(envelope_bytes: bytes) -> tuple[int, str]:
    if not getattr(settings, "ALLIES_CLOUD_EVENT_DELIVERY_ENABLED", False):
        return 503, "delivery_disabled"
    try:
        event = FoundryEventEnvelope.model_validate_json(envelope_bytes)
        validate_event(event)
    except (TypeError, ValueError):
        return 503, "delivery_envelope_invalid"
    base_url = _validated_cloud_url(getattr(settings, "ALLIES_CLOUD_URL", None))
    token = getattr(settings, "ALLIES_CLOUD_EVENT_SERVICE_TOKEN", None)
    if not base_url or not token:
        return 503, "delivery_not_configured"
    request = Request(
        f"{base_url.rstrip('/')}/api/v1/internal/foundry/events",
        data=envelope_bytes,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with build_opener(_NoRedirect).open(request, timeout=5) as response:
            status = int(response.status)
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                return 503, "delivery_response_too_large"
            if status == 202:
                try:
                    receipt = EventDeliveryReceipt.model_validate_json(body)
                except (TypeError, ValueError):
                    return 503, "delivery_receipt_invalid"
                if receipt.event_id != event.event_id:
                    return 503, "delivery_receipt_mismatch"
                return status, ""
            return status, _safe_response_code(body)
    except HTTPError as exc:
        try:
            body = exc.read(MAX_RESPONSE_BYTES + 1)
        finally:
            exc.close()
        if len(body) > MAX_RESPONSE_BYTES:
            return int(exc.code), "delivery_response_too_large"
        return int(exc.code), _safe_response_code(body)
    except (TimeoutError, URLError, OSError):
        return 503, "delivery_unavailable"


def _validated_cloud_url(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if any(character in value for character in "\x00\r\n"):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    local_proof_cloud = bool(
        getattr(settings, "DEBUG", False)
        and getattr(settings, "ALLIES_RUNTIME_POWER_PROOF_ENABLED", False)
        and parsed.scheme.lower() == "http"
        and parsed.hostname
        and parsed.hostname.lower() == "host.docker.internal"
    )
    if (
        parsed.scheme.lower() != "https"
        and not local_proof_cloud
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        and not 0 <= port <= 65535
        or parsed.query
        or parsed.fragment
    ):
        return None
    return value.rstrip("/")


def _safe_response_code(body: bytes) -> str:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, TypeError, ValueError):
        return ""
    code = None
    if isinstance(value, dict):
        code = value.get("code") or value.get("status")
    return code if isinstance(code, str) and _safe_error_code(code) else ""


def _safe_error_code(value: str) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 64
        and value[0].islower()
        and all(character.isalnum() or character in "_-" for character in value)
    )


def _backoff_seconds(attempt: int) -> float:
    base = min(MAX_DELIVERY_BACKOFF_SECONDS, 2 ** max(attempt - 1, 0))
    return base * (1 + random.random() * 0.25)


__all__ = [
    "DELIVERY_LEASE_SECONDS",
    "MAX_AUTOMATIC_REPAIR_CYCLES",
    "MAX_DELIVERY_ATTEMPTS",
    "REPAIR_DELAY_SECONDS",
    "DeliveryReport",
    "EventDeliveryClaim",
    "RedriveReport",
    "claim_event_deliveries",
    "enqueue_event_delivery",
    "mark_event_delivery",
    "publish_pending_event_deliveries",
    "redrive_event_deliveries",
]
