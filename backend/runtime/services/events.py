from __future__ import annotations

import re
from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import IntegrityError, transaction
from django.utils import timezone

from runtime.exceptions import (
    RuntimeAuthorizationError,
    RuntimeConflictError,
    RuntimeValidationError,
)
from runtime.models import Attempt, AttemptStatus, ExecutionEvent, Lease, LeaseState

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
_SERVER_EVENT_NAMESPACE = uuid5(NAMESPACE_URL, "allies-foundry:server-owned-events:v1")
_LEASE_EXPIRY_FAILURE_CODE = "lease_expired"


def _append_lease_expired_failure(attempt: Attempt, lease: Lease) -> ExecutionEvent:
    """Append the fixed server-owned failure for one locked stale lease."""

    if transaction.get_autocommit():
        raise RuntimeValidationError(
            "lease expiry event append requires an atomic transaction"
        )
    if lease.attempt_id != attempt.id or lease.state not in {
        LeaseState.ACTIVE,
        LeaseState.STOPPING,
    }:
        raise RuntimeValidationError("lease expiry event target is invalid")
    if lease.expires_at > timezone.now():
        raise RuntimeValidationError("lease expiry event target is not expired")

    event_id = uuid5(
        _SERVER_EVENT_NAMESPACE,
        f"{attempt.id}:{_LEASE_EXPIRY_FAILURE_CODE}",
    )
    stream_id = f"stream-{attempt.id.hex}"
    from .attempts import _failure_event_payload

    payload = _failure_event_payload(
        {
            "code": _LEASE_EXPIRY_FAILURE_CODE,
            "retryable": False,
        }
    )
    existing = (
        ExecutionEvent.objects.select_for_update()
        .filter(attempt_id=attempt.id, event_id=event_id)
        .first()
    )
    if existing is not None:
        _ensure_exact_replay(
            existing,
            existing.sequence,
            "execution.failed",
            digest_payload(payload),
            stream_id,
        )
        _enqueue_event_delivery(existing)
        return existing

    latest = (
        ExecutionEvent.objects.select_for_update()
        .filter(attempt_id=attempt.id)
        .order_by("-sequence")
        .first()
    )
    sequence = (latest.sequence if latest is not None else 0) + 1
    payload_digest = digest_payload(payload)
    event = ExecutionEvent.objects.create(
        attempt_id=attempt.id,
        event_id=event_id,
        stream_id=stream_id,
        sequence=sequence,
        event_type="execution.failed",
        payload=payload,
        payload_digest=payload_digest,
    )
    _enqueue_event_delivery(event)
    return event


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
    payload = _runtime_event_payload(event_type, payload)
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


def _runtime_event_payload(event_type: str, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise RuntimeValidationError("event payload must be an object")
    if event_type == "execution.dispatched":
        if payload != {"status": "dispatched"}:
            raise RuntimeValidationError("dispatch event payload is invalid")
        return dict(payload)
    if event_type == "execution.awaiting_action":
        action_kind = payload.get("action_kind")
        if (
            set(payload) != {"action_kind"}
            or not isinstance(action_kind, str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", action_kind)
        ):
            raise RuntimeValidationError("awaiting-action payload is invalid")
        return {"action_kind": action_kind}
    if event_type == "execution.stopped":
        reason = payload.get("reason")
        if (
            set(payload) != {"reason"}
            or not isinstance(reason, str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", reason)
        ):
            raise RuntimeValidationError("stopped event payload is invalid")
        return {"reason": reason}
    if event_type == "message.delta":
        text = payload.get("text")
        if set(payload) != {"text"} or not isinstance(text, str) or not text:
            raise RuntimeValidationError("message event payload is invalid")
        if len(text.encode("utf-8")) > 16 * 1024:
            raise RuntimeValidationError("message event payload is too large")
        return {"text": text}
    if event_type == "activity.started":
        activity_id = payload.get("activity_id")
        if (
            set(payload) != {"activity_id", "kind"}
            or not isinstance(activity_id, str)
            or not activity_id
            or len(activity_id) > 128
            or payload.get("kind") != "tool"
        ):
            raise RuntimeValidationError("activity start payload is invalid")
        return {"activity_id": activity_id, "kind": "tool"}
    if event_type == "activity.completed":
        activity_id = payload.get("activity_id")
        if (
            set(payload) != {"activity_id", "status"}
            or not isinstance(activity_id, str)
            or not activity_id
            or len(activity_id) > 128
            or payload.get("status") != "completed"
        ):
            raise RuntimeValidationError("activity completion payload is invalid")
        return {"activity_id": activity_id, "status": "completed"}
    raise RuntimeValidationError("event type is not allowed for append")


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
        raise RuntimeValidationError("token_digest and machine_generation are required")
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
        _enqueue_event_delivery(existing)
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
            event = ExecutionEvent.objects.create(
                attempt_id=authorization.attempt_id,
                event_id=event_uuid,
                stream_id=stream_id,
                sequence=sequence,
                event_type=event_type,
                payload=event_payload,
                payload_digest=payload_digest,
            )
            _enqueue_event_delivery(event)
            return event
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
            _enqueue_event_delivery(existing)
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


def _enqueue_event_delivery(event: ExecutionEvent) -> None:
    from .event_delivery import enqueue_event_delivery

    enqueue_event_delivery(event)


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
