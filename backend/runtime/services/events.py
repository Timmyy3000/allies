from __future__ import annotations

from uuid import UUID

from django.db import IntegrityError, transaction

from runtime.exceptions import (
    RuntimeAuthorizationError,
    RuntimeConflictError,
    RuntimeValidationError,
)
from runtime.models import Attempt, AttemptStatus, ExecutionEvent

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


def append_runtime_event(
    context,
    attempt_id: UUID,
    lease_token: str,
    event_id: UUID,
    stream_id: str,
    sequence: int,
    event_type: str,
    payload: dict,
) -> ExecutionEvent:
    """Runtime-authenticated event append with Workspace-first locking."""

    from runtime.exceptions import RuntimeFencedError, RuntimeLeaseConflictError
    from runtime.models import Lease, RuntimeProfile, Workspace

    from .runtime_auth import RuntimeContext
    from .validation import digest_lease_token

    if not isinstance(context, RuntimeContext):
        raise RuntimeValidationError("runtime context is required")
    token_digest = digest_lease_token(lease_token)

    @transaction.atomic
    def append_once() -> ExecutionEvent:
        workspace = Workspace.objects.select_for_update().get(pk=context.workspace_id)
        if workspace.machine_generation != context.machine_generation:
            raise RuntimeFencedError("runtime generation is stale")
        attempt = (
            Attempt.objects.select_for_update()
            .select_related("execution")
            .filter(pk=attempt_id, execution__workspace_id=workspace.id)
            .first()
        )
        if attempt is None:
            raise RuntimeLeaseConflictError("attempt is not in this workspace")
        RuntimeProfile.objects.select_for_update().get(pk=attempt.execution.profile_id)
        lease = Lease.objects.select_for_update().filter(attempt=attempt).first()
        if lease is None or lease.token_digest != token_digest:
            raise RuntimeLeaseConflictError("lease token does not authorize attempt")
        return _append_event_once(
            attempt_id,
            lease.id,
            event_id,
            sequence,
            event_type,
            payload,
            token_digest=token_digest,
            machine_generation=context.machine_generation,
            stream_id=stream_id,
        )

    return run_with_sqlite_lock_retry(append_once)


def append_event(
    attempt_id: UUID,
    lease_id: UUID,
    event_id: UUID,
    sequence: int,
    event_type: str,
    payload: dict,
    token_digest: str | None = None,
    machine_generation: int | None = None,
    stream_id: str = "",
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
            stream_id=stream_id,
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
    stream_id: str = "",
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
    if (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence <= 0
        or sequence > 100000
    ):
        raise RuntimeValidationError("sequence must be an integer from 1 to 100000")
    validate_nonempty(event_type, "event_type", max_length=64)
    if stream_id:
        validate_nonempty(stream_id, "stream_id", max_length=255)
    event_payload = validate_object_payload(
        payload,
        max_bytes=MAX_EVENT_PAYLOAD_BYTES,
    )
    payload_digest = digest_payload(event_payload)
    existing = (
        ExecutionEvent.objects.select_for_update()
        .filter(attempt_id=attempt_id, event_id=event_uuid)
        .first()
    )
    if existing is not None:
        try:
            authorization = _authorize_attempt_mutation(
                attempt_id,
                lease_id,
                token_digest,
                machine_generation,
            )
        except RuntimeAuthorizationError:
            _authorize_released_event_replay(
                attempt_id, lease_id, token_digest, machine_generation
            )
        _ensure_exact_replay(existing, sequence, event_type, payload_digest, stream_id)
        return existing
    authorization = _authorize_attempt_mutation(
        attempt_id,
        lease_id,
        token_digest,
        machine_generation,
    )
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
                stream_id=stream_id,
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
            _ensure_exact_replay(
                existing, sequence, event_type, payload_digest, stream_id
            )
            return existing
        raise RuntimeConflictError("event append conflicts with existing state")


def _ensure_exact_replay(
    existing: ExecutionEvent,
    sequence: int,
    event_type: str,
    payload_digest: str,
    stream_id: str = "",
) -> None:
    if (
        existing.sequence != sequence
        or existing.event_type != event_type
        or existing.stream_id != stream_id
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


def _authorize_released_event_replay(
    attempt_id: UUID,
    lease_id: UUID,
    token_digest: str,
    machine_generation: int,
) -> None:
    """Permit an exact event replay after terminal lease release only."""

    from runtime.models import Attempt, Lease, LeaseState

    attempt = Attempt.objects.select_related("execution").filter(pk=attempt_id).first()
    lease = Lease.objects.filter(pk=lease_id, attempt_id=attempt_id).first()
    if (
        attempt is None
        or lease is None
        or lease.token_digest != token_digest
        or lease.state != LeaseState.RELEASED
        or lease.machine_generation != machine_generation
        or attempt.execution.workspace.machine_generation != machine_generation
    ):
        raise RuntimeAuthorizationError("lease no longer authorizes this event")
