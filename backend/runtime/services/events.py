from __future__ import annotations

from uuid import UUID

from django.db import IntegrityError, transaction

from runtime.exceptions import RuntimeConflictError, RuntimeValidationError
from runtime.models import AttemptStatus, ExecutionEvent

from .leases import _authorize_attempt_mutation
from .retry import run_with_sqlite_lock_retry
from .validation import (
    MAX_EVENT_PAYLOAD_BYTES,
    digest_payload,
    validate_nonempty,
    validate_object_payload,
)

_EVENT_WRITABLE_ATTEMPT_STATUSES = frozenset(
    {AttemptStatus.QUEUED, AttemptStatus.LEASED, AttemptStatus.RUNNING}
)


def append_event(
    attempt_id: UUID,
    lease_id: UUID,
    event_id: UUID,
    sequence: int,
    event_type: str,
    payload: dict,
    token_digest: str | None = None,
    machine_generation: int | None = None,
) -> ExecutionEvent:
    return run_with_sqlite_lock_retry(
        lambda: _append_event_once(
            attempt_id,
            lease_id,
            event_id,
            sequence,
            event_type,
            payload,
            token_digest=token_digest,
            machine_generation=machine_generation,
        )
    )


@transaction.atomic
def _append_event_once(
    attempt_id: UUID,
    lease_id: UUID,
    event_id: UUID,
    sequence: int,
    event_type: str,
    payload: dict,
    token_digest: str | None = None,
    machine_generation: int | None = None,
) -> ExecutionEvent:
    """Append an ordered event after lease/generation authorization.

    ``token_digest`` and ``machine_generation`` are explicit authorization
    inputs so the service cannot infer identity from an attempt identifier.
    """

    if token_digest is None or machine_generation is None:
        raise RuntimeValidationError(
            "token_digest and machine_generation are required"
        )
    try:
        event_uuid = UUID(str(event_id))
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError("event_id must be a UUID") from exc
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
        raise RuntimeValidationError("sequence must be a positive integer")
    validate_nonempty(event_type, "event_type", max_length=128)
    event_payload = validate_object_payload(
        payload,
        max_bytes=MAX_EVENT_PAYLOAD_BYTES,
    )
    payload_digest = digest_payload(event_payload)
    authorization = _authorize_attempt_mutation(
        attempt_id,
        lease_id,
        token_digest,
        machine_generation,
    )

    existing = (
        ExecutionEvent.objects.select_for_update()
        .filter(attempt_id=authorization.attempt_id, event_id=event_uuid)
        .first()
    )
    if existing is not None:
        _ensure_exact_replay(existing, sequence, event_type, payload_digest)
        return existing
    if authorization.status not in _EVENT_WRITABLE_ATTEMPT_STATUSES:
        raise RuntimeConflictError("terminal attempt cannot append events")

    latest = (
        ExecutionEvent.objects.select_for_update()
        .filter(attempt_id=authorization.attempt_id)
        .order_by("-sequence")
        .first()
    )
    if latest is not None and sequence <= latest.sequence:
        raise RuntimeConflictError("event sequence is not monotonic")
    if ExecutionEvent.objects.filter(
        attempt_id=authorization.attempt_id,
        sequence=sequence,
    ).exists():
        raise RuntimeConflictError("event sequence already belongs to another event")

    try:
        with transaction.atomic():
            return ExecutionEvent.objects.create(
                attempt_id=authorization.attempt_id,
                event_id=event_uuid,
                sequence=sequence,
                event_type=event_type,
                payload=event_payload,
                payload_digest=payload_digest,
            )
    except IntegrityError:
        existing = (
            ExecutionEvent.objects.select_for_update()
            .filter(attempt_id=authorization.attempt_id, event_id=event_uuid)
            .first()
        )
        if existing is not None:
            _ensure_exact_replay(existing, sequence, event_type, payload_digest)
            return existing
        raise RuntimeConflictError("event append conflicts with existing state")


def _ensure_exact_replay(
    existing: ExecutionEvent,
    sequence: int,
    event_type: str,
    payload_digest: str,
) -> None:
    if (
        existing.sequence != sequence
        or existing.event_type != event_type
        or _stored_payload_digest(existing) != payload_digest
    ):
        raise RuntimeConflictError("event identifier already has different content")


def _stored_payload_digest(existing: ExecutionEvent) -> str:
    if existing.payload_digest:
        return existing.payload_digest
    digest = digest_payload(existing.payload)
    existing.payload_digest = digest
    existing.save(update_fields=["payload_digest"])
    return digest
