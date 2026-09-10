from __future__ import annotations

import hashlib
import hmac
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
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
    IN_FLIGHT_PROVISIONING_PHASES,
    Attempt,
    AttemptStatus,
    Execution,
    ExecutionEvent,
    ExecutionStatus,
    Lease,
    LeaseState,
    RoutineApprovalAction,
    RoutineApprovalStatus,
    RoutineExecution,
    RoutineLeaseAcquisition,
    RoutineRunStatus,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
)

from .profiles import profile_is_claim_ready
from .retry import run_with_sqlite_lock_retry
from .routines import _require_routine_admission, routine_scope_key
from .runtime_auth import RuntimeContext
from .runtime_readiness import require_current_runtime_ready_locked

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
    routine_id: UUID | None = None
    reasoning_effort: str | None = None
    command_id: UUID | None = None


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
        workspace.provisioning_phase in IN_FLIGHT_PROVISIONING_PHASES
        or workspace.machine_generation <= 0
        or not workspace.fly_app_ref
        or not workspace.volume_ref
        or not workspace.machine_ref
    ):
        raise RuntimeNotReadyError("workspace is not ready for claims")
    require_current_runtime_ready_locked(workspace, context)

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
        if replay.execution.source_kind == "routine_dispatch":
            _require_routine_admission(workspace)
        # Once the original lease has expired, returning its deterministic
        # token only hands the worker a claim that every mutation will reject.
        # Let the caller drop the ambiguous reservation and request a fresh
        # claim instead; the expired lease remains fenced by normal reclaim.
        if lease.expires_at <= timezone.now():
            return None
        return _claim_from_records(replay, lease)

    routine_replay = (
        RoutineLeaseAcquisition.objects.select_for_update()
        .select_related("lease__attempt__execution__profile", "lease__attempt__execution__workspace")
        .filter(claim_id=claim_id)
        .first()
    )
    if routine_replay is not None:
        replay_attempt = routine_replay.lease.attempt
        if replay_attempt.execution.workspace_id != workspace.id:
            raise RuntimeIdempotencyConflictError(
                "claim_id already belongs to another workspace"
            )
        lease = routine_replay.lease
        if (
            replay_attempt.machine_generation != workspace.machine_generation
            or lease.machine_generation != workspace.machine_generation
            or not routine_replay.current
        ):
            raise RuntimeIdempotencyConflictError(
                "claim_id belongs to a retired machine generation"
            )
        _require_routine_admission(workspace)
        if lease.expires_at <= timezone.now():
            return None
        return _claim_from_records(
            replay_attempt,
            lease,
            acquisition=routine_replay,
        )

    # Candidate IDs are read without locks.  Once a candidate is selected, all
    # writes acquire the fixed Workspace -> Profile -> Execution -> Attempt ->
    # Lease order.
    candidate_ids = list(
        Execution.objects.filter(
            workspace_id=workspace.id,
        )
        .filter(
            Q(status=ExecutionStatus.QUEUED)
            | Q(status=ExecutionStatus.RUNNING, source_kind="routine_dispatch")
        )
        .order_by("created_at", "id")
        .values_list("id", flat=True)
    )
    saw_unready_profile = False
    saw_routine_not_ready = False
    saw_routine_fenced = False
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
        if execution is None:
            continue
        routine = (
            RoutineExecution.objects.select_for_update()
            .filter(execution_id=execution.id)
            .first()
        )
        if routine is None and execution.status != ExecutionStatus.QUEUED:
            continue
        if routine is not None and routine.status == RoutineRunStatus.QUEUED:
            if execution.status != ExecutionStatus.QUEUED:
                continue
        elif routine is not None and routine.status == RoutineRunStatus.WORKING:
            if (
                execution.status != ExecutionStatus.RUNNING
                or not RoutineApprovalAction.objects.filter(
                    routine_execution_id=routine.id,
                    status=RoutineApprovalStatus.AUTHORIZING,
                ).exists()
            ):
                continue
        elif routine is not None:
            continue
        if not profile_is_claim_ready(profile, workspace.machine_generation):
            saw_unready_profile = True
            continue
        if routine is not None:
            try:
                _require_routine_admission(workspace)
            except RuntimeNotReadyError:
                saw_routine_not_ready = True
                continue
            except RuntimeFencedError:
                saw_routine_fenced = True
                continue
        scope_key = routine_scope_key(routine.routine_id) if routine is not None else "main"
        if Lease.objects.select_for_update().filter(
            profile_id=profile.id,
            scope_key=scope_key,
            state__in=(LeaseState.ACTIVE, LeaseState.STOPPING),
        ).exists():
            continue
        now = timezone.now()
        if routine is not None and routine.current_attempt_id is not None:
            attempt = Attempt.objects.select_for_update().get(pk=routine.current_attempt_id)
            if attempt.status != AttemptStatus.QUEUED:
                continue
            attempt.status = AttemptStatus.RUNNING
            attempt.machine_generation = workspace.machine_generation
            attempt.claimed_at = now
            attempt.save(update_fields=["status", "machine_generation", "claimed_at", "updated_at"])
        else:
            number = (
                Attempt.objects.select_for_update()
                .filter(execution_id=execution.id)
                .order_by("-number")
                .values_list("number", flat=True)
                .first()
                or 0
            ) + 1
            try:
                attempt = Attempt.objects.create(
                    execution=execution,
                    number=number,
                    status=AttemptStatus.RUNNING,
                    machine_generation=workspace.machine_generation,
                    claim_id=None if routine is not None else claim_id,
                    claimed_at=now,
                )
            except IntegrityError as exc:
                raise RuntimeIdempotencyConflictError("claim_id already exists") from exc
            if routine is not None:
                routine.current_attempt = attempt
        execution.status = ExecutionStatus.RUNNING
        execution.save(update_fields=["status", "updated_at"])
        if routine is not None:
            routine.status = RoutineRunStatus.WORKING
            routine.generation = workspace.machine_generation
            routine.save(update_fields=["status", "generation", "current_attempt", "updated_at"])
        raw_token = _claim_token(claim_id, attempt.id, workspace.machine_generation)
        lease = (
            Lease.objects.select_for_update()
            .filter(attempt_id=attempt.id)
            .first()
        )
        if lease is None:
            lease = Lease.objects.create(
                attempt=attempt,
                profile=profile,
                token_digest=_digest(raw_token),
                claim_id=claim_id,
                expires_at=now + timedelta(seconds=LEASE_SECONDS),
                machine_generation=workspace.machine_generation,
                state=LeaseState.ACTIVE,
                scope_key=scope_key,
            )
        else:
            if lease.state not in {LeaseState.RELEASED, LeaseState.FENCED}:
                continue
            current = RoutineLeaseAcquisition.objects.select_for_update().filter(
                lease_id=lease.id, current=True
            ).first()
            if current is not None:
                current.current = False
                current.retired_at = now
                current.save(update_fields=["current", "retired_at"])
            lease.claim_id = claim_id
            lease.token_digest = _digest(raw_token)
            lease.expires_at = now + timedelta(seconds=LEASE_SECONDS)
            lease.machine_generation = workspace.machine_generation
            lease.state = LeaseState.ACTIVE
            lease.current_acquisition = None
            lease.save(
                update_fields=[
                    "claim_id",
                    "token_digest",
                    "expires_at",
                    "machine_generation",
                    "state",
                    "current_acquisition",
                    "updated_at",
                ]
            )
        if routine is not None:
            acquisition = RoutineLeaseAcquisition.objects.create(
                lease=lease,
                ordinal=(
                    RoutineLeaseAcquisition.objects.filter(lease_id=lease.id).count()
                    + 1
                ),
                claim_id=claim_id,
                token_digest=_digest(raw_token),
                machine_generation=workspace.machine_generation,
                current=True,
                claim_receipt={"claim_id": str(claim_id)},
            )
            lease.current_acquisition = acquisition
            lease.save(update_fields=["current_acquisition", "updated_at"])
        return _claim_from_records(
            attempt,
            lease,
            raw_token=raw_token,
            acquisition=acquisition if routine is not None else None,
        )
    if saw_unready_profile:
        raise RuntimeNotReadyError("profile is not ready for runtime claims")
    if saw_routine_fenced:
        raise RuntimeFencedError("routine admission release is stale")
    if saw_routine_not_ready:
        raise RuntimeNotReadyError("routine admission is not ready")
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
        routine = (
            RoutineExecution.objects.select_for_update()
            .filter(workspace_id=workspace.id, current_attempt_id=attempt_id)
            .first()
        )
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
        _reconcile_expired_lease(
            workspace,
            profile,
            attempt,
            lease,
            routine=routine,
        )


def _reconcile_expired_lease(
    workspace: Workspace,
    profile: RuntimeProfile,
    attempt: Attempt,
    lease: Lease,
    *,
    routine: RoutineExecution | None,
) -> None:
    now = timezone.now()
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
    if replayable and routine is not None:
        try:
            _require_routine_admission(workspace)
        except RuntimeNotReadyError:
            # Disabled admission leaves the attempt queued for a later
            # explicitly enabled release.
            pass
        except RuntimeFencedError:
            # A stale release must not be replayed by an old authority.
            replayable = False
            retired = True
    if replayable:
        attempt.status = (
            AttemptStatus.QUEUED if routine is not None else AttemptStatus.UNKNOWN
        )
        attempt.save(update_fields=["status", "updated_at"])
        execution = attempt.execution
        execution.status = ExecutionStatus.QUEUED
        execution.save(update_fields=["status", "updated_at"])
        if routine is not None:
            routine.status = RoutineRunStatus.QUEUED
            routine.save(update_fields=["status", "updated_at"])
            current = RoutineLeaseAcquisition.objects.select_for_update().filter(
                lease_id=lease.id, current=True
            ).first()
            if current is not None:
                current.current = False
                current.retired_at = timezone.now()
                current.save(update_fields=["current", "retired_at"])
        lease.current_acquisition = None
        from .approvals import cancel_live_approval_requests

        cancel_live_approval_requests(attempt, now=now)
        lease.state = LeaseState.RELEASED
        lease.save(update_fields=["current_acquisition", "state", "updated_at"])
        return

    if unresolved:
        routine_was_terminal = routine is not None and routine.status in {
            RoutineRunStatus.SUCCEEDED,
            RoutineRunStatus.FAILED,
            RoutineRunStatus.CANCELLED,
            RoutineRunStatus.EXPIRED,
        }
        if not cleanup_pending:
            from .events import _append_lease_expired_failure

            _append_lease_expired_failure(attempt, lease)
        routine_result_event = None
        if routine is not None and not routine_was_terminal:
            from .routines import _record_terminal_failure_result

            routine_result_event = _record_terminal_failure_result(
                routine,
                text="Routine lease expired before completion.",
                observed_at=now,
            )
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
        if routine is not None and not routine_was_terminal:
            routine.status = RoutineRunStatus.FAILED
            routine.terminal_receipt = {
                **(routine.terminal_receipt or {}),
                "code": "LEASE_EXPIRED",
                **(
                    {"result_event_id": str(routine_result_event.event_id)}
                    if routine_result_event is not None
                    else {}
                ),
            }
            routine.save(update_fields=["status", "terminal_receipt", "updated_at"])

    from .approvals import cancel_live_approval_requests

    cancel_live_approval_requests(attempt, now=now)

    if cleanup_pending or retired:
        lease.state = LeaseState.FENCED
    else:
        lease.state = LeaseState.RELEASED
    if routine is not None:
        current = RoutineLeaseAcquisition.objects.select_for_update().filter(
            lease_id=lease.id, current=True
        ).first()
        if current is not None:
            current.current = False
            current.retired_at = timezone.now()
            current.save(update_fields=["current", "retired_at"])
    lease.current_acquisition = None
    lease.save(update_fields=["current_acquisition", "state", "updated_at"])


def _has_replay_checkpoint(attempt: Attempt) -> bool:
    attempt_checkpoint = (
        attempt.session_request_digest is not None
        or attempt.session_receipt is not None
        or ExecutionEvent.objects.filter(
            attempt_id=attempt.id,
            event_type="execution.dispatched",
        ).exists()
    )
    if attempt_checkpoint or attempt.execution.source_kind != "routine_dispatch":
        return attempt_checkpoint
    return RoutineLeaseAcquisition.objects.filter(
        lease__attempt_id=attempt.id,
    ).filter(
        Q(session_request_digest__isnull=False)
        | Q(session_receipt__isnull=False)
        | Q(stop_request_digest__isnull=False)
        | Q(stop_receipt__isnull=False)
        | Q(terminal_request_digest__isnull=False)
        | Q(terminal_receipt__isnull=False)
    ).exists()


def _claim_from_records(
    attempt: Attempt,
    lease: Lease,
    *,
    raw_token: str | None = None,
    acquisition: RoutineLeaseAcquisition | None = None,
) -> Claim:
    profile = attempt.execution.profile
    routine = (
        RoutineExecution.objects.filter(execution_id=attempt.execution_id).first()
        if attempt.execution.source_kind == "routine_dispatch"
        else None
    )
    binding = getattr(profile, "conversation_binding", None)
    token = raw_token or _claim_token(
        (acquisition.claim_id if acquisition is not None else None)
        or attempt.claim_id
        or lease.claim_id
        or attempt.id,
        attempt.id,
        lease.machine_generation,
    )
    conversation_id = (
        str(routine.run_conversation_id)
        if routine is not None
        else binding.cloud_conversation_ref if binding else None
    )
    # A conversation can be reserved before its first Hermes session exists.
    session_id = (
        routine.hermes_session_id
        if routine is not None
        else (binding.hermes_session_id or None) if binding else None
    )
    payload = deepcopy(attempt.execution.input_payload)
    if routine is not None:
        authorization = (
            RoutineApprovalAction.objects.filter(
                routine_execution_id=routine.id,
                status=RoutineApprovalStatus.AUTHORIZING,
            )
            .order_by("-updated_at", "-id")
            .first()
        )
        if authorization is not None:
            payload["routine_approval"] = {
                "action_attempt_id": str(authorization.action_attempt_id),
                "provider_idempotency_key": authorization.provider_idempotency_key,
                "continuation": deepcopy(authorization.continuation),
            }
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
        payload=payload,
        claim_id=(acquisition.claim_id if acquisition is not None else None)
        or attempt.claim_id
        or lease.claim_id
        or attempt.id,
        routine_id=routine.routine_id if routine is not None else None,
        reasoning_effort=settings.ALLIES_RUNTIME_REASONING_EFFORT,
        command_id=attempt.execution.command_id,
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
