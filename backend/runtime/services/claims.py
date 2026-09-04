from __future__ import annotations

import hashlib
import hmac
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeFencedError,
    RuntimeIdempotencyConflictError,
    RuntimeLeaseConflictError,
    RuntimeNotReadyError,
    RuntimeValidationError,
)
from runtime.models import (
    Attempt,
    AttemptStatus,
    Execution,
    ExecutionEvent,
    ExecutionStatus,
    Lease,
    LeaseState,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
    WorkspaceProvisioningPhase,
)

from .profiles import profile_is_claim_ready
from .retry import run_with_sqlite_lock_retry
from .runtime_auth import RuntimeContext

LEASE_SECONDS = 60
MAX_AVAILABLE_SLOTS = 8


@dataclass(frozen=True, slots=True)
class Claim:
    attempt_id: UUID
    execution_id: UUID
    profile_id: UUID
    hermes_profile_key: str
    model: str
    conversation_id: str | None
    session_id: str | None
    stream_id: str
    lease_id: UUID
    lease_token: str
    expires_at: datetime
    payload: dict
    claim_id: UUID


@dataclass(frozen=True, slots=True)
class LeaseReceipt:
    lease_id: UUID
    expires_at: datetime


def claim_next_execution(
    context: RuntimeContext,
    claim_id: UUID,
    available_slots: int,
) -> Claim | None:
    if not isinstance(claim_id, UUID):
        try:
            claim_id = UUID(str(claim_id))
        except (TypeError, ValueError) as exc:
            raise RuntimeValidationError("claim_id must be a UUID") from exc
    if (
        isinstance(available_slots, bool)
        or not isinstance(available_slots, int)
        or not 1 <= available_slots <= MAX_AVAILABLE_SLOTS
    ):
        raise RuntimeValidationError("available_slots must be an integer from 1 to 8")
    return run_with_sqlite_lock_retry(
        lambda: _claim_next_execution_once(context, claim_id, available_slots)
    )


@transaction.atomic
def _claim_next_execution_once(
    context: RuntimeContext,
    claim_id: UUID,
    available_slots: int,
) -> Claim | None:
    workspace = (
        Workspace.objects.select_for_update().filter(pk=context.workspace_id).first()
    )
    if workspace is None:
        raise RuntimeLeaseConflictError("runtime workspace does not exist")
    _check_context_generation(workspace, context)
    if (
        workspace.provisioning_phase != WorkspaceProvisioningPhase.IDLE
        or workspace.machine_generation <= 0
        or not workspace.fly_app_ref
        or not workspace.volume_ref
        or not workspace.machine_ref
    ):
        raise RuntimeNotReadyError("workspace is not ready for claims")

    _reconcile_expired_leases(workspace)

    replay = (
        Attempt.objects.select_for_update()
        .select_related("execution__profile", "execution__workspace")
        .filter(claim_id=claim_id)
        .first()
    )
    if replay is not None:
        if replay.execution.workspace_id != workspace.id:
            raise RuntimeIdempotencyConflictError(
                "claim_id already belongs to another workspace"
            )
        lease = Lease.objects.select_for_update().filter(attempt=replay).first()
        if lease is None:
            raise RuntimeConflictError("claim has no durable lease")
        if (
            replay.machine_generation != workspace.machine_generation
            or lease.machine_generation != workspace.machine_generation
        ):
            raise RuntimeIdempotencyConflictError(
                "claim_id belongs to a retired machine generation"
            )
        if not profile_is_claim_ready(
            replay.execution.profile, workspace.machine_generation
        ):
            raise RuntimeFencedError("profile lifecycle has fenced this claim")
        # Once the original lease has expired, returning its deterministic
        # token only hands the worker a claim that every mutation will reject.
        # Let the caller drop the ambiguous reservation and request a fresh
        # claim instead; the expired lease remains fenced by normal reclaim.
        if lease.expires_at <= timezone.now():
            return None
        return _claim_from_records(replay, lease)

    # Candidate IDs are read without locks.  Once a candidate is selected, all
    # writes acquire the fixed Workspace -> Profile -> Execution -> Attempt ->
    # Lease order.
    candidate_ids = list(
        Execution.objects.filter(
            workspace_id=workspace.id,
            status=ExecutionStatus.QUEUED,
        )
        .order_by("created_at", "id")
        .values_list("id", flat=True)
    )
    saw_unready_profile = False
    for execution_id in candidate_ids:
        execution_hint = (
            Execution.objects.filter(pk=execution_id)
            .values_list("profile_id", flat=True)
            .first()
        )
        if execution_hint is None:
            continue
        profile = (
            RuntimeProfile.objects.select_for_update()
            .filter(pk=execution_hint, workspace_id=workspace.id)
            .first()
        )
        if profile is None:
            continue
        execution = (
            Execution.objects.select_for_update()
            .select_related("workspace", "profile")
            .filter(pk=execution_id, workspace_id=workspace.id)
            .first()
        )
        if execution is None or execution.status != ExecutionStatus.QUEUED:
            continue
        if not profile_is_claim_ready(profile, workspace.machine_generation):
            saw_unready_profile = True
            continue
        if (
            Lease.objects.select_for_update()
            .filter(
                profile_id=profile.id,
                state__in=(LeaseState.ACTIVE, LeaseState.STOPPING),
            )
            .exists()
        ):
            continue
        number = (
            Attempt.objects.select_for_update()
            .filter(execution_id=execution.id)
            .order_by("-number")
            .values_list("number", flat=True)
            .first()
            or 0
        ) + 1
        now = timezone.now()
        try:
            attempt = Attempt.objects.create(
                execution=execution,
                number=number,
                status=AttemptStatus.RUNNING,
                machine_generation=workspace.machine_generation,
                claim_id=claim_id,
                claimed_at=now,
            )
        except IntegrityError as exc:
            raise RuntimeIdempotencyConflictError("claim_id already exists") from exc
        execution.status = ExecutionStatus.RUNNING
        execution.save(update_fields=["status", "updated_at"])
        raw_token = _claim_token(claim_id, attempt.id, workspace.machine_generation)
        lease = Lease.objects.create(
            attempt=attempt,
            profile=profile,
            token_digest=_digest(raw_token),
            claim_id=claim_id,
            expires_at=now + timedelta(seconds=LEASE_SECONDS),
            machine_generation=workspace.machine_generation,
            state=LeaseState.ACTIVE,
        )
        return _claim_from_records(attempt, lease, raw_token=raw_token)
    if saw_unready_profile:
        raise RuntimeNotReadyError("profile is not ready for runtime claims")
    return None


def _reconcile_expired_leases(workspace: Workspace) -> None:
    now = timezone.now()
    stale_leases = list(
        Lease.objects.filter(
            profile__workspace_id=workspace.id,
            state__in=(LeaseState.ACTIVE, LeaseState.STOPPING),
            expires_at__lte=now,
        )
        .order_by("expires_at", "id")
        .values_list("id", "attempt_id")[:MAX_AVAILABLE_SLOTS]
    )
    for lease_id, attempt_id in stale_leases:
        attempt = (
            Attempt.objects.select_for_update()
            .select_related("execution")
            .filter(pk=attempt_id, execution__workspace_id=workspace.id)
            .first()
        )
        if attempt is None:
            continue
        profile = (
            RuntimeProfile.objects.select_for_update()
            .filter(pk=attempt.execution.profile_id, workspace_id=workspace.id)
            .first()
        )
        if profile is None:
            continue
        lease = (
            Lease.objects.select_for_update()
            .filter(pk=lease_id, attempt_id=attempt.id)
            .first()
        )
        if (
            lease is None
            or lease.state not in (LeaseState.ACTIVE, LeaseState.STOPPING)
            or lease.expires_at > now
        ):
            continue
        _reconcile_expired_lease(workspace, profile, attempt, lease)


def _reconcile_expired_lease(
    workspace: Workspace,
    profile: RuntimeProfile,
    attempt: Attempt,
    lease: Lease,
) -> None:
    unresolved = attempt.status in {
        AttemptStatus.QUEUED,
        AttemptStatus.LEASED,
        AttemptStatus.RUNNING,
    }
    retired = (
        lease.machine_generation != workspace.machine_generation
        or attempt.machine_generation != workspace.machine_generation
        or lease.profile_id != profile.id
    )
    cleanup_pending = (
        profile.lifecycle_state == RuntimeProfileLifecycleState.CLEANUP_PENDING
    )
    replayable = (
        unresolved
        and attempt.execution.status
        in (ExecutionStatus.QUEUED, ExecutionStatus.RUNNING)
        and not retired
        and not cleanup_pending
        and profile_is_claim_ready(profile, workspace.machine_generation)
        and not _has_replay_checkpoint(attempt)
    )
    if replayable:
        attempt.status = AttemptStatus.UNKNOWN
        attempt.save(update_fields=["status", "updated_at"])
        execution = attempt.execution
        execution.status = ExecutionStatus.QUEUED
        execution.save(update_fields=["status", "updated_at"])
        lease.state = LeaseState.RELEASED
        lease.save(update_fields=["state", "updated_at"])
        return

    if unresolved:
        if not cleanup_pending:
            from .events import _append_lease_expired_failure

            _append_lease_expired_failure(attempt, lease)
        attempt.status = AttemptStatus.UNKNOWN
        attempt.save(update_fields=["status", "updated_at"])
        execution = attempt.execution
        if execution.status not in {
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        }:
            execution.status = ExecutionStatus.FAILED
            execution.save(update_fields=["status", "updated_at"])

    if cleanup_pending or retired:
        lease.state = LeaseState.FENCED
    else:
        lease.state = LeaseState.RELEASED
    lease.save(update_fields=["state", "updated_at"])


def _has_replay_checkpoint(attempt: Attempt) -> bool:
    return (
        attempt.session_request_digest is not None
        or attempt.session_receipt is not None
        or ExecutionEvent.objects.filter(
            attempt_id=attempt.id,
            event_type="execution.dispatched",
        ).exists()
    )


def _claim_from_records(
    attempt: Attempt,
    lease: Lease,
    *,
    raw_token: str | None = None,
) -> Claim:
    profile = attempt.execution.profile
    binding = getattr(profile, "conversation_binding", None)
    token = raw_token or _claim_token(
        attempt.claim_id or lease.claim_id or attempt.id,
        attempt.id,
        lease.machine_generation,
    )
    conversation_id = binding.cloud_conversation_ref if binding else None
    # A conversation can be reserved before its first Hermes session exists.
    session_id = (binding.hermes_session_id or None) if binding else None
    return Claim(
        attempt_id=attempt.id,
        execution_id=attempt.execution_id,
        profile_id=profile.id,
        hermes_profile_key=profile.hermes_profile_key,
        model=str(profile.seed_payload.get("model") or ""),
        conversation_id=conversation_id,
        session_id=session_id,
        stream_id=f"stream-{attempt.id.hex}",
        lease_id=lease.id,
        lease_token=token,
        expires_at=lease.expires_at,
        payload=deepcopy(attempt.execution.input_payload),
        claim_id=attempt.claim_id or lease.claim_id or attempt.id,
    )


def _check_context_generation(workspace: Workspace, context: RuntimeContext) -> None:
    if workspace.machine_generation != context.machine_generation:
        raise RuntimeFencedError("runtime credential belongs to a retired generation")


def _claim_token(claim_id: UUID, attempt_id: UUID, generation: int) -> str:
    # Deterministic replay is backed by the server-only Django secret, so
    # public claim/attempt IDs cannot derive a valid lease capability.
    message = f"{claim_id.hex}:{attempt_id.hex}:{generation}".encode("ascii")
    secret = str(settings.SECRET_KEY).encode("utf-8")
    return f"lease-{hmac.new(secret, message, hashlib.sha256).hexdigest()}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = ["Claim", "LeaseReceipt", "claim_next_execution"]
