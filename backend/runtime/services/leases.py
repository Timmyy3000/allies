from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from runtime.exceptions import (
    RuntimeAuthorizationError,
    RuntimeConflictError,
    RuntimeValidationError,
)
from runtime.models import Attempt, AttemptStatus, Lease, LeaseState

from .retry import run_with_sqlite_lock_retry
from .validation import digest_lease_token, validate_token_digest

_UNSET = object()


@dataclass(frozen=True, slots=True)
class _AttemptAuthorization:
    attempt_id: UUID
    status: str
    claimed_at: datetime | None
    machine_generation: int


_TERMINAL_ATTEMPT_STATUSES = frozenset(
    {
        AttemptStatus.SUCCEEDED,
        AttemptStatus.FAILED,
        AttemptStatus.CANCELLED,
        AttemptStatus.UNKNOWN,
    }
)
_ATTEMPT_STATUS_TRANSITIONS = {
    AttemptStatus.QUEUED: frozenset(
        {
            AttemptStatus.QUEUED,
            AttemptStatus.LEASED,
            AttemptStatus.RUNNING,
        }
    ),
    AttemptStatus.LEASED: frozenset(
        {
            AttemptStatus.LEASED,
            AttemptStatus.RUNNING,
        }
    ),
    AttemptStatus.RUNNING: frozenset(
        {AttemptStatus.RUNNING, *_TERMINAL_ATTEMPT_STATUSES}
    ),
}
_ATTEMPT_STATUS_TRANSITIONS.update(
    {status: frozenset({status}) for status in _TERMINAL_ATTEMPT_STATUSES}
)
_CLAIMABLE_ATTEMPT_STATUSES = frozenset(
    {AttemptStatus.LEASED, AttemptStatus.RUNNING}
)


__all__ = [
    "authorize_attempt_mutation",
    "create_lease",
    "create_lease_from_digest",
    "digest_lease_token",
]


def create_lease(
    attempt_id: UUID,
    raw_token: str,
    expires_at: datetime,
    machine_generation: int,
    *,
    profile_id: UUID | None = None,
    state: str = LeaseState.ACTIVE,
) -> Lease:
    """Create a generation-scoped lease from an opaque raw token.

    Runtime claim selection belongs to a later ticket. This helper keeps the
    durable relationship and its invariants in one transaction for that caller.
    The raw token is hashed before any persistence boundary.
    """

    return create_lease_from_digest(
        attempt_id,
        digest_lease_token(raw_token),
        expires_at,
        machine_generation,
        profile_id=profile_id,
        state=state,
    )


def create_lease_from_digest(
    attempt_id: UUID,
    token_digest: str,
    expires_at: datetime,
    machine_generation: int,
    *,
    profile_id: UUID | None = None,
    state: str = LeaseState.ACTIVE,
) -> Lease:
    return run_with_sqlite_lock_retry(
        lambda: _create_lease_from_digest(
            attempt_id,
            token_digest,
            expires_at,
            machine_generation,
            profile_id=profile_id,
            state=state,
        )
    )


@transaction.atomic
def _create_lease_from_digest(
    attempt_id: UUID,
    token_digest: str,
    expires_at: datetime,
    machine_generation: int,
    *,
    profile_id: UUID | None = None,
    state: str = LeaseState.ACTIVE,
) -> Lease:
    """Create a lease from a precomputed, validated SHA-256 digest."""

    validate_token_digest(token_digest)
    if state not in LeaseState.values:
        raise RuntimeValidationError("invalid lease state")
    if machine_generation < 0:
        raise RuntimeValidationError("machine_generation cannot be negative")
    try:
        attempt = (
            Attempt.objects.select_for_update()
            .select_related("execution__workspace", "execution__profile")
            .get(pk=attempt_id)
        )
    except Attempt.DoesNotExist as exc:
        raise RuntimeValidationError("attempt does not exist") from exc
    execution = attempt.execution
    profile = execution.profile
    if profile_id is not None and profile.id != profile_id:
        raise RuntimeValidationError("profile does not own the attempt")
    if (
        attempt.machine_generation != machine_generation
        or execution.workspace.machine_generation != machine_generation
    ):
        raise RuntimeAuthorizationError("lease generation is stale")
    try:
        with transaction.atomic():
            return Lease.objects.create(
                attempt=attempt,
                profile=profile,
                token_digest=token_digest,
                expires_at=expires_at,
                machine_generation=machine_generation,
                state=state,
            )
    except IntegrityError as exc:
        raise RuntimeConflictError(
            "lease creation conflicts with an existing lease"
        ) from exc


def authorize_attempt_mutation(
    attempt_id: UUID,
    lease_id: UUID,
    token_digest: str,
    machine_generation: int,
    *,
    status: str | None = None,
    claimed_at: datetime | None | object = _UNSET,
) -> None:
    """Authorize and apply bounded attempt fields in one transaction."""

    updates = _validate_attempt_mutation(status, claimed_at)
    run_with_sqlite_lock_retry(
        lambda: _authorize_and_mutate(
            attempt_id,
            lease_id,
            token_digest,
            machine_generation,
            updates,
        )
    )


@transaction.atomic
def _authorize_and_mutate(
    attempt_id: UUID,
    lease_id: UUID,
    token_digest: str,
    machine_generation: int,
    updates: dict[str, object],
) -> None:
    authorization = _authorize_attempt_mutation(
        attempt_id,
        lease_id,
        token_digest,
        machine_generation,
    )
    _validate_authorized_attempt_mutation(authorization, updates)
    effective_updates = {
        field: value
        for field, value in updates.items()
        if value != getattr(authorization, field)
    }
    if not effective_updates:
        return
    updated = Attempt.objects.filter(pk=authorization.attempt_id).update(
        **effective_updates,
        updated_at=timezone.now(),
    )
    if updated != 1:
        raise RuntimeAuthorizationError("attempt mutation target is unavailable")


def _validate_attempt_mutation(
    status: str | None,
    claimed_at: datetime | None | object,
) -> dict[str, object]:
    updates: dict[str, object] = {}
    if status is not None:
        if status not in AttemptStatus.values:
            raise RuntimeValidationError("invalid attempt status")
        updates["status"] = status
    if claimed_at is not _UNSET:
        if claimed_at is not None and not isinstance(claimed_at, datetime):
            raise RuntimeValidationError("claimed_at must be a datetime or null")
        updates["claimed_at"] = claimed_at
    if not updates:
        raise RuntimeValidationError("attempt mutation requires a field")
    return updates


def _validate_authorized_attempt_mutation(
    authorization: _AttemptAuthorization,
    updates: dict[str, object],
) -> None:
    current_status = authorization.status
    next_status = updates.get("status", current_status)
    if next_status not in _ATTEMPT_STATUS_TRANSITIONS.get(current_status, ()):
        raise RuntimeConflictError("attempt status transition is invalid")

    if "claimed_at" not in updates:
        return
    current_claimed_at = authorization.claimed_at
    next_claimed_at = updates["claimed_at"]
    if current_claimed_at is not None:
        if next_claimed_at != current_claimed_at:
            raise RuntimeConflictError("attempt claimed_at is immutable")
        return
    if next_claimed_at is None:
        return
    if next_status not in _CLAIMABLE_ATTEMPT_STATUSES:
        raise RuntimeConflictError(
            "claimed_at requires a leased or running attempt"
        )


def _authorize_attempt_mutation(
    attempt_id: UUID,
    lease_id: UUID,
    token_digest: str,
    machine_generation: int,
) -> _AttemptAuthorization:
    """Lock and validate an attempt for a caller-owned atomic transaction."""

    if transaction.get_autocommit():
        raise RuntimeValidationError(
            "attempt authorization requires an atomic transaction"
        )
    validate_token_digest(token_digest)
    try:
        attempt = (
            Attempt.objects.select_for_update()
            .select_related("execution__workspace", "execution__profile")
            .get(pk=attempt_id)
        )
    except Attempt.DoesNotExist as exc:
        raise RuntimeAuthorizationError("attempt is not authorized") from exc

    lease = (
        Lease.objects.select_for_update()
        .filter(pk=lease_id, attempt_id=attempt.id)
        .first()
    )
    if lease is None:
        raise RuntimeAuthorizationError("lease is not authorized for attempt")

    workspace = attempt.execution.workspace
    profile = attempt.execution.profile
    if (
        lease.profile_id != profile.id
        or profile.workspace_id != workspace.id
        or lease.token_digest != token_digest
        or lease.machine_generation != machine_generation
        or attempt.machine_generation != machine_generation
        or workspace.machine_generation != machine_generation
        or lease.state != LeaseState.ACTIVE
    ):
        raise RuntimeAuthorizationError("lease or machine generation is stale")
    if lease.expires_at <= timezone.now():
        raise RuntimeAuthorizationError("lease has expired")
    return _AttemptAuthorization(
        attempt_id=attempt.id,
        status=attempt.status,
        claimed_at=attempt.claimed_at,
        machine_generation=attempt.machine_generation,
    )
