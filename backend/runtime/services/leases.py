from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from runtime.exceptions import (
    RuntimeAuthorizationError,
    RuntimeConflictError,
    RuntimeFencedError,
    RuntimeIdempotencyConflictError,
    RuntimeLeaseConflictError,
    RuntimeValidationError,
)
from runtime.models import (
    Attempt,
    AttemptStatus,
    ExecutionStatus,
    Lease,
    LeaseState,
    RuntimeProfile,
    Workspace,
)
from runtime.services.claims import LeaseReceipt

from .profiles import profile_allows_runtime_write, profile_allows_stop
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
_CLAIMABLE_ATTEMPT_STATUSES = frozenset({AttemptStatus.LEASED, AttemptStatus.RUNNING})


__all__ = [
    "FenceReceipt",
    "StopReceipt",
    "acknowledge_stopped",
    "authorize_attempt_mutation",
    "confirm_machine_stopped_and_fence",
    "create_lease",
    "create_lease_from_digest",
    "digest_lease_token",
    "renew_lease",
]


@dataclass(frozen=True, slots=True)
class StopReceipt:
    attempt_id: UUID
    state: str
    requeued: bool


@dataclass(frozen=True, slots=True)
class FenceReceipt:
    workspace_id: UUID
    source_generation: int
    target_generation: int
    fenced_count: int
    requeued_count: int


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
    if not profile_allows_runtime_write(profile):
        raise RuntimeAuthorizationError("profile lifecycle is not active")
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
        raise RuntimeConflictError("claimed_at requires a leased or running attempt")


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
    if not profile_allows_runtime_write(profile):
        raise RuntimeAuthorizationError("profile lifecycle is not active")
    if lease.expires_at <= timezone.now():
        raise RuntimeAuthorizationError("lease has expired")
    return _AttemptAuthorization(
        attempt_id=attempt.id,
        status=attempt.status,
        claimed_at=attempt.claimed_at,
        machine_generation=attempt.machine_generation,
    )


def renew_lease(context, attempt_id: UUID, lease_token: str) -> LeaseReceipt:
    """Extend one current-generation ACTIVE lease for another 60 seconds."""

    from runtime.services.claims import LEASE_SECONDS
    from runtime.services.runtime_auth import RuntimeContext

    if not isinstance(context, RuntimeContext):
        raise RuntimeValidationError("runtime context is required")
    try:
        attempt_uuid = UUID(str(attempt_id))
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError("attempt_id must be a UUID") from exc
    token_digest = digest_lease_token(lease_token)

    @transaction.atomic
    def renew_once() -> LeaseReceipt:
        workspace = Workspace.objects.select_for_update().get(pk=context.workspace_id)
        _check_runtime_workspace(workspace, context)
        attempt = (
            Attempt.objects.select_for_update()
            .select_related("execution")
            .filter(pk=attempt_uuid, execution__workspace_id=workspace.id)
            .first()
        )
        if attempt is None:
            raise RuntimeLeaseConflictError("attempt is not in this workspace")
        profile = RuntimeProfile.objects.select_for_update().get(
            pk=attempt.execution.profile_id
        )
        if not profile_allows_runtime_write(profile):
            raise RuntimeLeaseConflictError("profile lifecycle is not active")
        lease = Lease.objects.select_for_update().filter(attempt=attempt).first()
        if lease is None or lease.token_digest != token_digest:
            raise RuntimeLeaseConflictError("lease token does not authorize attempt")
        now = timezone.now()
        if lease.machine_generation != workspace.machine_generation:
            raise RuntimeFencedError("lease belongs to a retired generation")
        if lease.state != LeaseState.ACTIVE:
            raise RuntimeLeaseConflictError("lease is no longer active")
        if lease.expires_at <= now:
            raise RuntimeLeaseConflictError("lease has expired")
        lease.expires_at = now + timedelta(seconds=LEASE_SECONDS)
        lease.save(update_fields=["expires_at", "updated_at"])
        return LeaseReceipt(lease.id, lease.expires_at)

    return run_with_sqlite_lock_retry(renew_once)


def acknowledge_stopped(
    context,
    attempt_id: UUID,
    lease_token: str,
    reason: str,
    request_digest: str | None = None,
) -> StopReceipt:
    """Release ACTIVE/STOPPING work and requeue the execution exactly once."""

    from runtime.services.runtime_auth import RuntimeContext

    from .validation import digest_payload, validate_nonempty

    if not isinstance(context, RuntimeContext):
        raise RuntimeValidationError("runtime context is required")
    validate_nonempty(reason, "reason", max_length=255)
    try:
        attempt_uuid = UUID(str(attempt_id))
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError("attempt_id must be a UUID") from exc
    token_digest = digest_lease_token(lease_token)
    canonical_digest = request_digest or digest_payload({"reason": reason})

    @transaction.atomic
    def stop_once() -> StopReceipt:
        workspace = Workspace.objects.select_for_update().get(pk=context.workspace_id)
        _check_runtime_workspace(workspace, context)
        attempt = (
            Attempt.objects.select_for_update()
            .select_related("execution")
            .filter(pk=attempt_uuid, execution__workspace_id=workspace.id)
            .first()
        )
        if attempt is None:
            raise RuntimeLeaseConflictError("attempt is not in this workspace")
        profile = RuntimeProfile.objects.select_for_update().get(
            pk=attempt.execution.profile_id
        )
        lease = Lease.objects.select_for_update().filter(attempt=attempt).first()
        if attempt.stopped_request_digest is not None:
            if (
                attempt.stopped_request_digest != canonical_digest
                or attempt.stopped_lease_digest != token_digest
            ):
                raise RuntimeIdempotencyConflictError(
                    "stopped request conflicts with its stored receipt"
                )
            return StopReceipt(
                attempt.id,
                (attempt.stopped_receipt or {}).get("state", LeaseState.RELEASED),
                bool((attempt.stopped_receipt or {}).get("requeued", False)),
            )
        if not profile_allows_stop(profile):
            raise RuntimeLeaseConflictError("profile lifecycle does not accept stop")
        if lease is None or lease.token_digest != token_digest:
            raise RuntimeLeaseConflictError("lease token does not authorize attempt")
        if lease.machine_generation != workspace.machine_generation:
            raise RuntimeFencedError("lease belongs to a retired generation")
        if lease.state not in (LeaseState.ACTIVE, LeaseState.STOPPING):
            raise RuntimeLeaseConflictError("lease is already released")
        cleanup_pending = profile.lifecycle_state == "cleanup_pending"
        # ACTIVE is deliberately moved through STOPPING in the same transaction
        # so a concurrent stop/reclaim sees one serialized transition.
        if lease.state == LeaseState.ACTIVE:
            lease.state = LeaseState.STOPPING
            lease.save(update_fields=["state", "updated_at"])
        attempt.status = AttemptStatus.UNKNOWN
        attempt.stopped_request_digest = canonical_digest
        attempt.stopped_lease_digest = token_digest
        receipt = {
            "state": LeaseState.RELEASED,
            "requeued": not cleanup_pending,
            "reason": "profile_deprovisioned" if cleanup_pending else reason,
        }
        attempt.stopped_receipt = receipt
        attempt.save(
            update_fields=[
                "status",
                "stopped_request_digest",
                "stopped_lease_digest",
                "stopped_receipt",
                "updated_at",
            ]
        )
        execution = attempt.execution
        execution.status = (
            ExecutionStatus.FAILED if cleanup_pending else ExecutionStatus.QUEUED
        )
        execution.save(update_fields=["status", "updated_at"])
        lease.state = LeaseState.RELEASED
        lease.save(update_fields=["state", "updated_at"])
        return StopReceipt(attempt.id, LeaseState.RELEASED, not cleanup_pending)

    return run_with_sqlite_lock_retry(stop_once)


def confirm_machine_stopped_and_fence(
    workspace_id: UUID,
    source_generation: int,
    target_generation: int,
    machine_ref: str | None = None,
) -> FenceReceipt:
    """Retire old-generation leases after provider-confirmed stop/404."""

    if source_generation < 0 or target_generation <= source_generation:
        raise RuntimeValidationError("source/target generations are invalid")

    @transaction.atomic
    def fence_once() -> FenceReceipt:
        workspace = Workspace.objects.select_for_update().get(pk=workspace_id)
        if workspace.machine_generation < target_generation:
            raise RuntimeConflictError(
                "workspace has not advanced to target generation"
            )
        # A callback replay after a later replacement is not safe to apply.
        if workspace.machine_generation > target_generation:
            raise RuntimeConflictError("fence generation is stale")
        if source_generation != target_generation - 1:
            raise RuntimeConflictError("fence generations are not adjacent")
        if workspace.provisioning_kind != "replace":
            raise RuntimeConflictError("workspace is not in replacement fencing")
        if (
            workspace.provisioning_source_generation != source_generation
            or workspace.provisioning_target_generation != target_generation
        ):
            raise RuntimeConflictError("fence does not match replacement generations")
        if workspace.provisioning_phase not in {
            "old_machine_stopped",
            "old_machine_destroyed",
        }:
            raise RuntimeConflictError("workspace is not at the stopped fence phase")
        if workspace.provisioning_previous_machine_ref != machine_ref:
            raise RuntimeConflictError("fence Machine does not match replacement state")
        profile_ids = list(
            RuntimeProfile.objects.filter(workspace_id=workspace.id).values_list(
                "id", flat=True
            )
        )
        fenced = 0
        requeued = 0
        for profile_id in profile_ids:
            RuntimeProfile.objects.select_for_update().get(pk=profile_id)
            lease_ids = list(
                Lease.objects.filter(
                    profile_id=profile_id,
                    machine_generation=source_generation,
                    state__in=(LeaseState.ACTIVE, LeaseState.STOPPING),
                ).values_list("id", flat=True)
            )
            for lease_id in lease_ids:
                lease = (
                    Lease.objects.select_for_update()
                    .select_related("attempt__execution")
                    .get(pk=lease_id)
                )
                if lease.state in (LeaseState.RELEASED, LeaseState.FENCED):
                    continue
                attempt = lease.attempt
                execution = attempt.execution
                lease.state = LeaseState.FENCED
                lease.save(update_fields=["state", "updated_at"])
                fenced += 1
                if attempt.status in (
                    AttemptStatus.QUEUED,
                    AttemptStatus.LEASED,
                    AttemptStatus.RUNNING,
                ):
                    attempt.status = AttemptStatus.UNKNOWN
                    attempt.save(update_fields=["status", "updated_at"])
                    if execution.status == ExecutionStatus.RUNNING:
                        execution.status = ExecutionStatus.QUEUED
                        execution.save(update_fields=["status", "updated_at"])
                        requeued += 1
        return FenceReceipt(
            workspace_id,
            source_generation,
            target_generation,
            fenced,
            requeued,
        )

    return run_with_sqlite_lock_retry(fence_once)


def _check_runtime_workspace(workspace: Workspace, context) -> None:
    if workspace.machine_generation != context.machine_generation:
        raise RuntimeFencedError("runtime generation is stale")
