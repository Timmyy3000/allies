from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from django.db import IntegrityError, transaction
from django.utils import timezone

from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeFencedError,
    RuntimeIdempotencyConflictError,
    RuntimeLeaseConflictError,
    RuntimeNotFoundError,
    RuntimeNotReadyError,
    RuntimeValidationError,
)
from runtime.models import (
    Attempt,
    AttemptStatus,
    ConversationBinding,
    Execution,
    ExecutionEvent,
    ExecutionStatus,
    Lease,
    LeaseState,
    RoutineActionState,
    RoutineApprovalAction,
    RoutineApprovalStatus,
    RoutineCommandReceipt,
    RoutineExecution,
    RoutineLeaseAcquisition,
    RoutineRunStatus,
    RuntimeProfile,
    Workspace,
)
from runtime.routine_contracts import (
    MAX_ROUTINE_SEQUENCE,
    MAX_ROUTINE_TERMINAL_SEQUENCE,
    RoutineApprovalDecision,
    RoutineApprovalReceipt,
    RoutineCancelWait,
    RoutineDispatch,
    RoutineDispatchReceipt,
    RoutineResult,
    routine_fingerprint,
)

from .event_delivery import enqueue_event_delivery
from .retry import run_with_sqlite_lock_retry
from .runtime_intents import request_execution_wake_locked
from .runtime_readiness import is_runtime_ready
from .runtime_releases import (
    current_runtime_release_digest,
    desired_images,
    runtime_release_digest,
)
from .validation import digest_lease_token, digest_payload, validate_object_payload

PROFILE_ID_NAMESPACE = uuid5(NAMESPACE_URL, "allies-foundry-profile-v1")
ROUTINE_LEASE_PREFIX = "routine:"
APPROVAL_WAIT_SECONDS = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class RoutineCancelReceipt:
    code: str
    routine_execution_id: UUID
    fence: int
    status: str
    replayed: bool = False


def routine_scope_key(routine_id: UUID | str) -> str:
    try:
        value = UUID(str(routine_id))
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError("routine_id must be a UUID") from exc
    return f"{ROUTINE_LEASE_PREFIX}{value}"


def enable_routine_admission(
    workspace_id: UUID | str,
    *,
    release_digest: str,
    machine_generation: int,
    runtime_start_epoch: int,
) -> Workspace:
    """Clear an explicit pause after checking the current deployed release."""

    if not isinstance(release_digest, str) or not release_digest.strip():
        raise RuntimeValidationError("release_digest is required")
    release_digest = release_digest.strip()
    if machine_generation <= 0 or runtime_start_epoch < 0:
        raise RuntimeValidationError("runtime release generation is invalid")

    @transaction.atomic
    def enable_once() -> Workspace:
        workspace = Workspace.objects.select_for_update().filter(pk=workspace_id).first()
        if workspace is None:
            raise RuntimeNotFoundError("workspace is unavailable")
        if workspace.machine_generation != machine_generation:
            raise RuntimeFencedError("runtime release generation is stale")
        if workspace.runtime_start_epoch != runtime_start_epoch:
            raise RuntimeFencedError("runtime release epoch is stale")
        approved_digest = _desired_routine_release_digest()
        if not approved_digest or release_digest != approved_digest:
            raise RuntimeNotReadyError("runtime release is not approved for routines")
        if not is_runtime_ready(workspace):
            raise RuntimeNotReadyError("runtime readiness receipt is missing or stale")
        if current_runtime_release_digest(workspace) != release_digest:
            raise RuntimeFencedError("runtime image release is not the approved release")
        target = dict(workspace.release_target or {})
        target["routine_admission"] = {
            "enabled": True,
            "release_digest": release_digest,
            "machine_generation": machine_generation,
            "runtime_start_epoch": runtime_start_epoch,
        }
        workspace.release_target = target
        workspace.save(update_fields=["release_target", "updated_at"])
        return workspace

    return run_with_sqlite_lock_retry(enable_once)


def disable_routine_admission(workspace_id: UUID | str) -> None:
    @transaction.atomic
    def disable_once() -> None:
        workspace = Workspace.objects.select_for_update().filter(pk=workspace_id).first()
        if workspace is None:
            raise RuntimeNotFoundError("workspace is unavailable")
        target = dict(workspace.release_target or {})
        gate = dict(target.get("routine_admission") or {})
        gate["enabled"] = False
        target["routine_admission"] = gate
        workspace.release_target = target
        workspace.save(update_fields=["release_target", "updated_at"])

    run_with_sqlite_lock_retry(disable_once)


def accept_routine_dispatch(
    command: RoutineDispatch | dict[str, Any],
    *,
    now: datetime | None = None,
) -> RoutineDispatchReceipt:
    command = _coerce(command, RoutineDispatch)
    observed_at = _aware(now or timezone.now())
    return run_with_sqlite_lock_retry(
        lambda: _accept_routine_dispatch_once(command, observed_at)
    )


@transaction.atomic
def _accept_routine_dispatch_once(
    command: RoutineDispatch,
    observed_at: datetime,
) -> RoutineDispatchReceipt:
    workspace, profile = _resolve_scope(command.scope.workspace_id, command.scope.ally_id, command.scope.cloud_binding_id)
    _require_routine_admission(workspace, require_readiness=False)
    binding = _ensure_main_binding(profile, command.main_conversation_id)
    if binding.cloud_conversation_ref != str(command.main_conversation_id):
        raise RuntimeConflictError("routine main conversation is not the profile binding")
    if command.run_conversation_id == command.main_conversation_id:
        raise RuntimeValidationError("routine run conversation must be fresh")

    stored = (
        RoutineCommandReceipt.objects.select_for_update()
        .filter(workspace_id=workspace.id, idempotency_key=command.idempotency_key)
        .first()
    )
    if stored is not None:
        _ensure_command_replay(stored, command)
        return RoutineDispatchReceipt.model_validate(stored.response)
    if RoutineCommandReceipt.objects.filter(command_id=command.command_id).exists():
        raise RuntimeIdempotencyConflictError("command identity already exists")
    existing = (
        RoutineExecution.objects.select_for_update()
        .filter(workspace_id=workspace.id, occurrence_id=command.occurrence_id)
        .first()
    )
    if existing is not None:
        if existing.execution.input_payload.get("routine_dispatch_fingerprint") != command.fingerprint:
            raise RuntimeIdempotencyConflictError("occurrence identity conflicts")
        response = RoutineDispatchReceipt.model_validate(existing.dispatch_receipt)
        _store_command_receipt(workspace, command, response.model_dump(mode="json"))
        return response

    payload = {
        "kind": "routine",
        "message": command.execution_prompt,
        "execution_prompt": command.execution_prompt,
        "cloud_conversation_ref": str(command.main_conversation_id),
        "main_conversation_id": str(command.main_conversation_id),
        "run_conversation_id": str(command.run_conversation_id),
        "schedule": deepcopy(command.schedule),
        "routine_id": str(command.routine_id),
        "routine_revision": command.routine_revision,
        "occurrence_id": str(command.occurrence_id),
        "run_id": str(command.run_id),
        "title_snapshot": command.title_snapshot,
        "delayed": command.delayed,
        "occurrence_disposition": command.occurrence_disposition,
        "routine_dispatch_fingerprint": command.fingerprint,
    }
    payload_digest = digest_payload(payload)
    try:
        execution = Execution.objects.create(
            workspace=workspace,
            profile=profile,
            idempotency_key=str(command.idempotency_key),
            input_payload=payload,
            payload_digest=payload_digest,
            source_kind="routine_dispatch",
            status=ExecutionStatus.QUEUED,
        )
        attempt = Attempt.objects.create(
            execution=execution,
            number=1,
            status=AttemptStatus.QUEUED,
            machine_generation=workspace.machine_generation,
        )
        routine = RoutineExecution.objects.create(
            execution=execution,
            workspace=workspace,
            profile=profile,
            routine_id=command.routine_id,
            routine_revision=command.routine_revision,
            schedule_generation=command.schedule_generation,
            occurrence_id=command.occurrence_id,
            run_id=command.run_id,
            scheduled_at=command.scheduled_at,
            delayed=command.delayed,
            occurrence_disposition=command.occurrence_disposition,
            main_conversation_id=command.main_conversation_id,
            run_conversation_id=command.run_conversation_id,
            cloud_binding_id=command.cloud_binding_id,
            owner_user_id=command.scope.owner_user_id,
            ally_id=command.scope.ally_id,
            title_snapshot=command.title_snapshot,
            execution_prompt=command.execution_prompt,
            generation=workspace.machine_generation,
            fence=0,
            status=RoutineRunStatus.QUEUED,
            current_attempt=attempt,
        )
    except IntegrityError as exc:
        raise RuntimeIdempotencyConflictError("routine dispatch identity conflicts") from exc

    response = _dispatch_receipt(command, workspace, execution, attempt, observed_at)
    routine.dispatch_receipt = response.model_dump(mode="json")
    routine.save(update_fields=["dispatch_receipt", "updated_at"])
    _store_command_receipt(workspace, command, response.model_dump(mode="json"))
    request_execution_wake_locked(workspace, now=observed_at)
    return response


def decide_routine_approval(
    command: RoutineApprovalDecision | dict[str, Any],
    *,
    now: datetime | None = None,
) -> RoutineApprovalReceipt:
    command = _coerce(command, RoutineApprovalDecision)
    observed_at = _aware(now or timezone.now())
    return run_with_sqlite_lock_retry(
        lambda: _decide_routine_approval_once(command, observed_at)
    )


@transaction.atomic
def _decide_routine_approval_once(
    command: RoutineApprovalDecision,
    observed_at: datetime,
) -> RoutineApprovalReceipt:
    workspace, _ = _resolve_scope(
        command.scope.workspace_id, command.scope.ally_id, command.scope.cloud_binding_id
    )
    stored = (
        RoutineCommandReceipt.objects.select_for_update()
        .filter(workspace_id=workspace.id, idempotency_key=command.idempotency_key)
        .first()
    )
    if stored is not None:
        _ensure_command_replay(stored, command)
        return RoutineApprovalReceipt.model_validate(stored.response)
    if RoutineCommandReceipt.objects.filter(command_id=command.command_id).exists():
        raise RuntimeIdempotencyConflictError("command identity already exists")
    routine = (
        RoutineExecution.objects.select_for_update()
        .select_related("execution", "workspace", "profile")
        .filter(
            workspace_id=workspace.id,
            run_id=command.run_id,
            current_attempt_id=command.attempt_id,
        )
        .first()
    )
    if routine is None:
        raise RuntimeNotFoundError("routine run is unavailable")
    if routine.current_attempt_id is None:
        raise RuntimeConflictError("routine has no current attempt")
    attempt = Attempt.objects.select_for_update().get(pk=routine.current_attempt_id)
    _validate_routine_identity(routine, command)
    action = (
        RoutineApprovalAction.objects.select_for_update()
        .filter(
            routine_execution_id=routine.id,
            approval_request_id=command.approval_request_id,
            action_attempt_id=command.action_attempt_id,
        )
        .first()
    )
    if action is None:
        raise RuntimeNotFoundError("approval request is unavailable")
    if action.generation != command.generation:
        raise RuntimeFencedError("approval generation is stale")
    if action.status != RoutineApprovalStatus.PENDING:
        raise RuntimeConflictError("approval request is no longer pending")
    if observed_at >= action.expires_at:
        response = _expire_action_locked(routine, action, attempt, observed_at, command)
        _store_command_receipt(workspace, command, response.model_dump(mode="json"))
        return response

    if command.decision == "reject":
        action.status = RoutineApprovalStatus.REJECTED
        action.permission_consumed = True
        action.decision = command.decision
        action.decision_digest = command.fingerprint.split(":")[-1]
        action.save(
            update_fields=[
                "status",
                "permission_consumed",
                "decision",
                "decision_digest",
                "updated_at",
            ]
        )
        result_event = _record_terminal_failure_result(
            routine,
            text="Routine approval was rejected before execution.",
            observed_at=observed_at,
        )
        routine.fence += 1
        routine.status = RoutineRunStatus.CANCELLED
        routine.terminal_receipt = {
            "code": "APPROVAL_REJECTED",
            "fence": routine.fence,
            "result_event_id": str(result_event.event_id),
        }
        routine.save(update_fields=["fence", "status", "terminal_receipt", "updated_at"])
        routine.execution.status = ExecutionStatus.CANCELLED
        routine.execution.save(update_fields=["status", "updated_at"])
        attempt.status = AttemptStatus.CANCELLED
        attempt.save(update_fields=["status", "updated_at"])
        response = _approval_receipt(
            command,
            "APPROVAL_REJECTED",
            action,
            run_status=RoutineRunStatus.CANCELLED,
            permission_consumed=True,
            observed_at=observed_at,
        )
        _store_command_receipt(workspace, command, response.model_dump(mode="json"))
        return response

    action.status = RoutineApprovalStatus.AUTHORIZING
    action.permission_consumed = True
    action.decision = command.decision
    action.decision_digest = command.fingerprint.split(":")[-1]
    action.action_state = RoutineActionState.PRE_DISPATCH
    action.save(
        update_fields=[
            "status",
            "permission_consumed",
            "decision",
            "decision_digest",
            "action_state",
            "updated_at",
        ]
    )
    routine.status = RoutineRunStatus.WORKING
    routine.save(update_fields=["status", "updated_at"])
    routine.execution.status = ExecutionStatus.RUNNING
    routine.execution.save(update_fields=["status", "updated_at"])
    attempt.status = AttemptStatus.QUEUED
    attempt.save(update_fields=["status", "updated_at"])
    request_execution_wake_locked(workspace, now=observed_at)
    response = _approval_receipt(
        command,
        "APPROVAL_AUTHORIZED",
        action,
        run_status=RoutineRunStatus.WORKING,
        permission_consumed=True,
        observed_at=observed_at,
    )
    _store_command_receipt(workspace, command, response.model_dump(mode="json"))
    return response


def request_routine_approval(
    routine_execution_id: UUID,
    *,
    action_attempt_id: UUID | str,
    action_digest: str,
    provider_idempotency_key: str,
    continuation: dict[str, Any] | None = None,
    approval_request_id: UUID | str | None = None,
    event_id: UUID | str | None = None,
    event_sequence: int | None = None,
    expires_at: datetime | None = None,
    now: datetime | None = None,
) -> ExecutionEvent:
    """Persist one approval checkpoint and publish its durable request event."""

    routine_id = _uuid(routine_execution_id, "routine_execution_id")
    action_attempt_uuid = _uuid(action_attempt_id, "action_attempt_id")
    approval_request_uuid = _uuid(
        approval_request_id or uuid4(), "approval_request_id"
    )
    request_event_id = _uuid(event_id or uuid4(), "event_id")
    observed_at = _aware(now or timezone.now())
    expiry = _aware(
        expires_at or observed_at + timedelta(seconds=APPROVAL_WAIT_SECONDS)
    )
    if expiry <= observed_at:
        raise RuntimeValidationError("approval expiry must be after creation")
    if (
        not isinstance(action_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", action_digest)
    ):
        raise RuntimeValidationError("action_digest must be a lowercase SHA-256 digest")
    if (
        not isinstance(provider_idempotency_key, str)
        or not provider_idempotency_key
        or len(provider_idempotency_key) > 255
    ):
        raise RuntimeValidationError("provider_idempotency_key is invalid")
    continuation_value = validate_object_payload(
        continuation or {},
        max_bytes=8 * 1024,
    )
    if event_sequence is not None and (
        isinstance(event_sequence, bool)
        or not isinstance(event_sequence, int)
        or not 1 <= event_sequence <= MAX_ROUTINE_SEQUENCE
    ):
        raise RuntimeValidationError("approval event sequence is invalid")
    return run_with_sqlite_lock_retry(
        lambda: _request_routine_approval_once(
            routine_id,
            action_attempt_id=action_attempt_uuid,
            approval_request_id=approval_request_uuid,
            action_digest=action_digest,
            provider_idempotency_key=provider_idempotency_key,
            continuation=continuation_value,
            event_id=request_event_id,
            event_sequence=event_sequence,
            created_at=observed_at,
            expires_at=expiry,
        )
    )


@transaction.atomic
def _request_routine_approval_once(
    routine_execution_id: UUID,
    *,
    action_attempt_id: UUID,
    approval_request_id: UUID,
    action_digest: str,
    provider_idempotency_key: str,
    continuation: dict[str, Any],
    event_id: UUID,
    event_sequence: int | None,
    created_at: datetime,
    expires_at: datetime,
) -> ExecutionEvent:
    routine = (
        RoutineExecution.objects.select_for_update()
        .select_related("execution", "workspace", "profile")
        .get(pk=routine_execution_id)
    )
    if routine.current_attempt_id is None:
        raise RuntimeConflictError("routine has no current attempt")
    attempt = Attempt.objects.select_for_update().get(pk=routine.current_attempt_id)
    existing = (
        RoutineApprovalAction.objects.select_for_update()
        .filter(action_attempt_id=action_attempt_id)
        .first()
    )
    if existing is None:
        existing = (
            RoutineApprovalAction.objects.select_for_update()
            .filter(approval_request_id=approval_request_id)
            .first()
        )
    if existing is not None:
        if (
            existing.routine_execution_id != routine.id
            or existing.attempt_id != attempt.id
            or existing.approval_request_id != approval_request_id
            or existing.action_attempt_id != action_attempt_id
            or existing.action_digest != action_digest
            or existing.provider_idempotency_key != provider_idempotency_key
            or existing.continuation != continuation
        ):
            raise RuntimeIdempotencyConflictError("approval request identity conflicts")
        if existing.created_event_id is None:
            raise RuntimeConflictError("approval request event is unavailable")
        return ExecutionEvent.objects.get(
            attempt_id=attempt.id,
            event_id=existing.created_event_id,
        )
    if routine.status != RoutineRunStatus.WORKING or attempt.status not in {
        AttemptStatus.LEASED,
        AttemptStatus.RUNNING,
    }:
        raise RuntimeConflictError("routine is not eligible for approval")
    lease = Lease.objects.select_for_update().filter(attempt_id=attempt.id).first()
    if lease is None or lease.state not in {LeaseState.ACTIVE, LeaseState.STOPPING}:
        raise RuntimeLeaseConflictError("routine lease is unavailable")
    if lease.scope_key != routine_scope_key(routine.routine_id):
        raise RuntimeLeaseConflictError("routine lease scope is stale")
    current = (
        RoutineLeaseAcquisition.objects.select_for_update()
        .filter(lease_id=lease.id, current=True)
        .first()
    )
    action = RoutineApprovalAction.objects.create(
        routine_execution=routine,
        attempt=attempt,
        approval_request_id=approval_request_id,
        action_attempt_id=action_attempt_id,
        generation=routine.generation,
        status=RoutineApprovalStatus.PENDING,
        permission_consumed=False,
        action_digest=action_digest,
        provider_idempotency_key=provider_idempotency_key,
        created_at=created_at,
        expires_at=expires_at,
        action_state=RoutineActionState.PRE_DISPATCH,
        continuation=continuation,
    )
    if current is not None:
        current.current = False
        current.retired_at = created_at
        current.save(update_fields=["current", "retired_at"])
    lease.current_acquisition = None
    lease.state = LeaseState.RELEASED
    lease.save(update_fields=["current_acquisition", "state", "updated_at"])
    routine.status = RoutineRunStatus.APPROVAL_WAITING
    routine.save(update_fields=["status", "updated_at"])
    attempt.status = AttemptStatus.APPROVAL_WAITING
    attempt.save(update_fields=["status", "updated_at"])
    sequence = (
        event_sequence if event_sequence is not None else _next_event_sequence(attempt.id)
    )
    if not 1 <= sequence <= MAX_ROUTINE_SEQUENCE:
        raise RuntimeConflictError("approval event sequence budget is exhausted")
    latest = (
        ExecutionEvent.objects.select_for_update()
        .filter(attempt_id=attempt.id)
        .order_by("-sequence")
        .first()
    )
    if latest is not None and sequence <= latest.sequence:
        raise RuntimeConflictError("approval event sequence is not monotonic")
    payload = {
        "approval_request_id": str(approval_request_id),
        "action_attempt_id": str(action_attempt_id),
        "run_id": str(routine.run_id),
        "execution_id": str(routine.execution_id),
        "attempt_id": str(attempt.id),
        "generation": routine.generation,
        "status": "pending",
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "action_digest": action_digest,
        "provider_idempotency_key": provider_idempotency_key,
    }
    try:
        event = ExecutionEvent.objects.create(
            attempt=attempt,
            event_id=event_id,
            stream_id=f"routine-{routine.run_id}",
            sequence=sequence,
            event_type="routine.approval_requested",
            payload=payload,
            payload_digest=digest_payload(payload),
        )
    except IntegrityError as exc:
        raise RuntimeConflictError("approval event identity conflicts") from exc
    action.created_event_id = event.event_id
    action.created_event_sequence = event.sequence
    action.save(update_fields=["created_event_id", "created_event_sequence", "updated_at"])
    enqueue_event_delivery(event)
    return event


def cancel_routine_wait(
    command: RoutineCancelWait | dict[str, Any],
    *,
    now: datetime | None = None,
) -> RoutineCancelReceipt:
    command = _coerce(command, RoutineCancelWait)
    observed_at = _aware(now or timezone.now())
    return run_with_sqlite_lock_retry(
        lambda: _cancel_routine_wait_once(command, observed_at)
    )


@transaction.atomic
def _cancel_routine_wait_once(
    command: RoutineCancelWait,
    observed_at: datetime,
) -> RoutineCancelReceipt:
    workspace, _ = _resolve_scope(
        command.scope.workspace_id, command.scope.ally_id, command.scope.cloud_binding_id
    )
    stored = (
        RoutineCommandReceipt.objects.select_for_update()
        .filter(workspace_id=workspace.id, idempotency_key=command.idempotency_key)
        .first()
    )
    if stored is not None:
        _ensure_command_replay(stored, command)
        return _cancel_receipt_from_json(stored.response)
    if RoutineCommandReceipt.objects.filter(command_id=command.command_id).exists():
        raise RuntimeIdempotencyConflictError("command identity already exists")
    routine = (
        RoutineExecution.objects.select_for_update()
        .filter(workspace_id=workspace.id, run_id=command.run_id, current_attempt_id=command.attempt_id)
        .first()
    )
    if routine is None:
        raise RuntimeNotFoundError("routine run is unavailable")
    attempt = None
    if routine.current_attempt_id is not None:
        attempt = Attempt.objects.select_for_update().get(pk=routine.current_attempt_id)
    _validate_routine_identity(routine, command)
    action = (
        RoutineApprovalAction.objects.select_for_update()
        .filter(routine_execution_id=routine.id, approval_request_id=command.approval_request_id)
        .first()
    )
    if action is None:
        raise RuntimeNotFoundError("approval request is unavailable")
    if action.status == RoutineApprovalStatus.AUTHORIZING:
        response = RoutineCancelReceipt(
            "APPROVAL_ALREADY_AUTHORIZING", routine.id, routine.fence, action.status
        )
        _store_command_receipt(workspace, command, _cancel_receipt_json(response))
        return response
    if action.status != RoutineApprovalStatus.PENDING:
        response = RoutineCancelReceipt(
            "APPROVAL_ALREADY_TERMINAL", routine.id, routine.fence, action.status
        )
        _store_command_receipt(workspace, command, _cancel_receipt_json(response))
        return response
    action.status = RoutineApprovalStatus.CANCELLED
    action.permission_consumed = True
    action.decision = "cancel"
    action.save(update_fields=["status", "permission_consumed", "decision", "updated_at"])
    result_event = _record_terminal_failure_result(
        routine,
        text="Routine wait was cancelled before execution.",
        observed_at=observed_at,
    )
    routine.fence += 1
    routine.status = RoutineRunStatus.CANCELLED
    routine.terminal_receipt = {
        "code": "WAIT_CANCELLED",
        "fence": routine.fence,
        "replacing_occurrence_id": str(command.replacing_occurrence_id),
        "result_event_id": str(result_event.event_id),
    }
    routine.save(update_fields=["fence", "status", "terminal_receipt", "updated_at"])
    routine.execution.status = ExecutionStatus.CANCELLED
    routine.execution.save(update_fields=["status", "updated_at"])
    if attempt is not None:
        attempt.status = AttemptStatus.CANCELLED
        attempt.save(update_fields=["status", "updated_at"])
        Lease.objects.filter(
            attempt_id=attempt.id,
            state__in=(LeaseState.ACTIVE, LeaseState.STOPPING),
        ).update(state=LeaseState.FENCED, updated_at=observed_at)
    response = RoutineCancelReceipt("WAIT_CANCELLED", routine.id, routine.fence, action.status)
    _store_command_receipt(workspace, command, _cancel_receipt_json(response))
    return response


def expire_routine_approvals(
    *,
    limit: int = 20,
    now: datetime | None = None,
) -> int:
    if isinstance(limit, bool) or not 1 <= limit <= 100:
        raise RuntimeValidationError("limit must be between 1 and 100")
    observed_at = _aware(now or timezone.now())
    ids = list(
        RoutineApprovalAction.objects.filter(
            status=RoutineApprovalStatus.PENDING,
            expires_at__lte=observed_at,
        )
        .order_by("expires_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    expired = 0
    for action_id in ids:
        action_ref = (
            RoutineApprovalAction.objects.filter(pk=action_id)
            .values("routine_execution_id")
            .first()
        )
        if action_ref is None:
            continue
        with transaction.atomic():
            routine = (
                RoutineExecution.objects.select_for_update()
                .filter(pk=action_ref["routine_execution_id"])
                .first()
            )
            if routine is None:
                continue
            attempt = None
            if routine.current_attempt_id is not None:
                attempt = Attempt.objects.select_for_update().get(pk=routine.current_attempt_id)
            action = RoutineApprovalAction.objects.select_for_update().filter(pk=action_id).first()
            if (
                action is None
                or action.routine_execution_id != routine.id
                or action.status != RoutineApprovalStatus.PENDING
                or action.expires_at > observed_at
            ):
                continue
            _expire_action_locked(routine, action, attempt, observed_at, None)
            expired += 1
    return expired


def record_routine_result(
    routine_execution_id: UUID,
    *,
    outcome: str,
    text: str,
    references: list[dict[str, str]] | None = None,
    delayed: bool | None = None,
    event_id: UUID | str | None = None,
    event_sequence: int | None = None,
    now: datetime | None = None,
) -> ExecutionEvent:
    observed_at = _aware(now or timezone.now())
    return run_with_sqlite_lock_retry(
        lambda: _record_routine_result_once(
            routine_execution_id,
            outcome=outcome,
            text=text,
            references=references or [],
            delayed=delayed,
            event_id=event_id,
            event_sequence=event_sequence,
            observed_at=observed_at,
        )
    )


def append_runtime_routine_result(
    context,
    attempt_id: UUID,
    lease_token: str,
    *,
    event_id: UUID | str,
    sequence: int,
    outcome: str,
    text: str,
    references: list[dict[str, str]],
    delayed: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    from .runtime_auth import RuntimeContext

    if not isinstance(context, RuntimeContext):
        raise RuntimeValidationError("runtime context is required")
    token_digest = digest_lease_token(lease_token)
    observed_at = _aware(now or timezone.now())

    @transaction.atomic
    def append_once() -> dict[str, Any]:
        workspace = Workspace.objects.select_for_update().get(pk=context.workspace_id)
        if workspace.machine_generation != context.machine_generation:
            raise RuntimeFencedError("runtime generation is stale")
        routine = RoutineExecution.objects.select_for_update().filter(
            workspace_id=workspace.id,
            current_attempt_id=attempt_id,
        ).first()
        if routine is None:
            raise RuntimeLeaseConflictError("routine lease scope is stale")
        attempt = (
            Attempt.objects.select_for_update()
            .select_related("execution")
            .filter(
                pk=attempt_id,
                execution__workspace_id=workspace.id,
                execution__source_kind="routine_dispatch",
            )
            .first()
        )
        if attempt is None:
            raise RuntimeLeaseConflictError("routine attempt is unavailable")
        lease = Lease.objects.select_for_update().filter(attempt_id=attempt.id).first()
        if lease is None or lease.token_digest != token_digest:
            raise RuntimeLeaseConflictError("routine lease is stale")
        if lease.scope_key != routine_scope_key(routine.routine_id):
            raise RuntimeLeaseConflictError("routine lease scope is stale")
        request_event_id = _uuid(event_id, "event_id")
        request_digest = digest_payload(
            {
                "event_id": str(request_event_id),
                "sequence": sequence,
                "outcome": outcome,
                "text": text,
                "references": references,
                "delayed": delayed,
            }
        )
        acquisition = (
            RoutineLeaseAcquisition.objects.select_for_update()
            .filter(lease_id=lease.id, token_digest=token_digest)
            .first()
        )
        if acquisition is None:
            raise RuntimeLeaseConflictError("routine lease authority is unavailable")
        replay_after_release = (
            lease.state == LeaseState.RELEASED
            and ExecutionEvent.objects.filter(
                attempt_id=attempt.id,
                event_id=request_event_id,
            ).exists()
        )
        if (
            not replay_after_release
            and (lease.state != LeaseState.ACTIVE or lease.expires_at <= observed_at)
        ):
            raise RuntimeLeaseConflictError("routine lease is stale")
        if replay_after_release and acquisition.terminal_receipt is not None:
            if acquisition.terminal_request_digest != request_digest:
                raise RuntimeConflictError("routine result replay conflicts")
            return deepcopy(acquisition.terminal_receipt)
        event = _record_routine_result_once(
            routine.id,
            outcome=outcome,
            text=text,
            references=references,
            delayed=delayed,
            event_id=request_event_id,
            event_sequence=sequence,
            observed_at=observed_at,
        )
        response = {
            "attempt_id": str(attempt.id),
            "status": "succeeded" if outcome in {"changed", "unchanged"} else "failed",
            "receipt_id": str(uuid4()),
            "requeued": False,
            "receipt": {"outcome": outcome, "event_id": str(event.event_id)},
        }
        acquisition.terminal_request_digest = request_digest
        acquisition.terminal_receipt = response
        acquisition.save(
            update_fields=["terminal_request_digest", "terminal_receipt"]
        )
        return response

    return run_with_sqlite_lock_retry(append_once)


@transaction.atomic
def _record_routine_result_once(
    routine_execution_id: UUID,
    *,
    outcome: str,
    text: str,
    references: list[dict[str, str]],
    delayed: bool | None,
    event_id: UUID | str | None,
    event_sequence: int | None,
    observed_at: datetime,
) -> ExecutionEvent:
    routine = (
        RoutineExecution.objects.select_for_update()
        .select_related("execution", "workspace", "profile")
        .get(pk=routine_execution_id)
    )
    if routine.current_attempt_id is None:
        raise RuntimeConflictError("routine has no current attempt")
    attempt = (
        Attempt.objects.select_for_update()
        .select_related("execution")
        .get(pk=routine.current_attempt_id)
    )
    event_id = _uuid(event_id or uuid4(), "event_id")
    sequence = (
        event_sequence if event_sequence is not None else _next_event_sequence(attempt.id)
    )
    if (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or not 1 <= sequence <= MAX_ROUTINE_TERMINAL_SEQUENCE
    ):
        raise RuntimeValidationError("routine result event sequence is invalid")
    payload = _result_payload(
        routine,
        attempt,
        outcome,
        text,
        references,
        delayed,
        event_id=event_id,
        event_sequence=sequence,
        issued_at=observed_at,
    )
    existing = ExecutionEvent.objects.select_for_update().filter(
        attempt_id=attempt.id, event_id=event_id
    ).first()
    if existing is not None:
        if existing.sequence != sequence or existing.payload != payload:
            raise RuntimeConflictError("routine result replay conflicts")
        return existing
    if routine.status in {
        RoutineRunStatus.SUCCEEDED,
        RoutineRunStatus.FAILED,
        RoutineRunStatus.CANCELLED,
        RoutineRunStatus.EXPIRED,
    }:
        raise RuntimeConflictError("routine run is terminal")
    event = ExecutionEvent.objects.create(
        attempt=attempt,
        event_id=event_id,
        stream_id=f"routine-{routine.run_id}",
        sequence=sequence,
        event_type="routine.result",
        payload=payload,
        payload_digest=digest_payload(payload),
    )
    enqueue_event_delivery(event)
    routine.status = (
        RoutineRunStatus.SUCCEEDED if outcome in {"changed", "unchanged"} else RoutineRunStatus.FAILED
    )
    routine.terminal_receipt = {"outcome": outcome, "event_id": str(event_id)}
    routine.save(update_fields=["status", "terminal_receipt", "updated_at"])
    attempt.status = (
        AttemptStatus.SUCCEEDED if outcome in {"changed", "unchanged"} else AttemptStatus.FAILED
    )
    attempt.save(update_fields=["status", "updated_at"])
    routine.execution.status = (
        ExecutionStatus.SUCCEEDED if outcome in {"changed", "unchanged"} else ExecutionStatus.FAILED
    )
    routine.execution.save(update_fields=["status", "updated_at"])
    if outcome == "failed":
        RoutineApprovalAction.objects.filter(
            routine_execution_id=routine.id,
            status=RoutineApprovalStatus.AUTHORIZING,
        ).update(
            status=RoutineApprovalStatus.CANCELLED,
            permission_consumed=True,
            decision="system_failure",
            action_state=RoutineActionState.MANUAL_RECONCILIATION,
            updated_at=observed_at,
        )
    lease = (
        Lease.objects.select_for_update()
        .filter(
            attempt_id=attempt.id,
            state__in=(LeaseState.ACTIVE, LeaseState.STOPPING),
        )
        .first()
    )
    if lease is not None:
        acquisition = (
            RoutineLeaseAcquisition.objects.select_for_update()
            .filter(lease_id=lease.id, current=True)
            .first()
        )
        if acquisition is not None:
            acquisition.current = False
            acquisition.retired_at = observed_at
            acquisition.save(update_fields=["current", "retired_at"])
        lease.current_acquisition = None
        lease.state = LeaseState.RELEASED
        lease.save(update_fields=["current_acquisition", "state", "updated_at"])
    return event


def _record_terminal_failure_result(
    routine: RoutineExecution,
    *,
    text: str,
    observed_at: datetime,
) -> ExecutionEvent:
    """Emit a failure before a caller applies a specific terminal state."""

    return _record_routine_result_once(
        routine.id,
        outcome="failed",
        text=text,
        references=[],
        delayed=None,
        event_id=uuid4(),
        event_sequence=None,
        observed_at=observed_at,
    )


def _expire_action_locked(
    routine: RoutineExecution,
    action: RoutineApprovalAction,
    attempt: Attempt | None,
    observed_at: datetime,
    command: RoutineApprovalDecision | None,
) -> RoutineApprovalReceipt | None:
    action.status = RoutineApprovalStatus.EXPIRED
    action.permission_consumed = False
    action.action_state = RoutineActionState.PRE_DISPATCH
    action.save(update_fields=["status", "permission_consumed", "action_state", "updated_at"])
    result_event = (
        _record_terminal_failure_result(
            routine,
            text="Routine approval expired before execution.",
            observed_at=observed_at,
        )
        if attempt is not None
        else None
    )
    routine.fence += 1
    routine.status = RoutineRunStatus.EXPIRED
    routine.terminal_receipt = {
        "code": "APPROVAL_EXPIRED",
        "fence": routine.fence,
        **(
            {"result_event_id": str(result_event.event_id)}
            if result_event is not None
            else {}
        ),
    }
    routine.save(update_fields=["fence", "status", "terminal_receipt", "updated_at"])
    routine.execution.status = ExecutionStatus.FAILED
    routine.execution.save(update_fields=["status", "updated_at"])
    if attempt is not None:
        attempt.status = AttemptStatus.FAILED
        attempt.save(update_fields=["status", "updated_at"])
        Lease.objects.filter(
            attempt_id=attempt.id,
            state__in=(LeaseState.ACTIVE, LeaseState.STOPPING),
        ).update(state=LeaseState.FENCED, updated_at=observed_at)
    if command is None:
        return None
    return _approval_receipt(
        command,
        "APPROVAL_EXPIRED",
        action,
        run_status=RoutineRunStatus.EXPIRED,
        permission_consumed=False,
        observed_at=observed_at,
    )


def _dispatch_receipt(
    command: RoutineDispatch,
    workspace: Workspace,
    execution: Execution,
    attempt: Attempt,
    observed_at: datetime,
) -> RoutineDispatchReceipt:
    value = {
        "schema_version": "v1",
        "kind": "routine.dispatch_receipt",
        "producer": "foundry",
        "service_identity": "foundry-service",
        "command_id": str(command.command_id),
        "idempotency_key": str(command.idempotency_key),
        "outcome": "accepted",
        "occurrence_id": str(command.occurrence_id),
        "run_id": str(command.run_id),
        "execution_id": str(execution.id),
        "attempt_id": str(attempt.id),
        "generation": workspace.machine_generation,
        "acceptance_is_completion": False,
        "scope": command.scope.model_dump(mode="json"),
        "issued_at": observed_at.isoformat(),
        "deadline_at": (observed_at + timedelta(seconds=60)).isoformat(),
        "fingerprint": "",
    }
    value["fingerprint"] = routine_fingerprint(value)
    return RoutineDispatchReceipt.model_validate(value)


def _approval_receipt(
    command: RoutineApprovalDecision,
    result_code: str,
    action: RoutineApprovalAction,
    *,
    run_status: str,
    permission_consumed: bool,
    observed_at: datetime,
) -> RoutineApprovalReceipt:
    value = {
        "schema_version": "v1",
        "kind": "routine.approval_receipt",
        "producer": "foundry",
        "service_identity": "foundry-service",
        "command_id": str(command.command_id),
        "idempotency_key": str(command.idempotency_key),
        "result_code": result_code,
        "request_status": action.status,
        "run_status": run_status,
        "permission_consumed": permission_consumed,
        "action_attempt_state": action.action_state or RoutineActionState.PRE_DISPATCH,
        "scope": command.scope.model_dump(mode="json"),
        "issued_at": observed_at.isoformat(),
        "deadline_at": (observed_at + timedelta(seconds=60)).isoformat(),
        "fingerprint": "",
    }
    value["fingerprint"] = routine_fingerprint(value)
    return RoutineApprovalReceipt.model_validate(value)


def _result_payload(
    routine: RoutineExecution,
    attempt: Attempt,
    outcome: str,
    text: str,
    references: list[dict[str, str]],
    delayed: bool | None,
    *,
    event_id: UUID,
    event_sequence: int,
    issued_at: datetime,
) -> dict[str, Any]:
    value = {
        "schema_version": "v1",
        "kind": "routine.result",
        "producer": "foundry",
        "service_identity": "foundry-service",
        "event_id": str(event_id),
        "event_sequence": event_sequence,
        "routine_id": str(routine.routine_id),
        "occurrence_id": str(routine.occurrence_id),
        "run_id": str(routine.run_id),
        "routine_revision": routine.routine_revision,
        "title_snapshot": routine.title_snapshot,
        "execution_id": str(routine.execution_id),
        "attempt_id": str(attempt.id),
        "generation": routine.generation,
        "main_conversation_id": str(routine.main_conversation_id),
        "run_conversation_id": str(routine.run_conversation_id),
        "outcome": outcome,
        "text": text,
        "references": references,
        "delayed": routine.delayed if delayed is None else delayed,
        "scope": _routine_scope(routine),
        "issued_at": issued_at.isoformat(),
        "deadline_at": (issued_at + timedelta(seconds=60)).isoformat(),
        "fingerprint": "",
    }
    value["fingerprint"] = routine_fingerprint(value)
    try:
        model = RoutineResult.model_validate(value)
    except ValueError as exc:
        raise RuntimeValidationError("routine result is invalid") from exc
    output = model.model_dump(mode="json")
    return {
        key: output[key]
        for key in (
            "routine_id",
            "occurrence_id",
            "run_id",
            "routine_revision",
            "title_snapshot",
            "execution_id",
            "attempt_id",
            "generation",
            "main_conversation_id",
            "run_conversation_id",
            "outcome",
            "text",
            "references",
            "delayed",
        )
    }


def _resolve_scope(
    workspace_id: UUID,
    ally_id: UUID,
    cloud_binding_id: UUID,
) -> tuple[Workspace, RuntimeProfile]:
    workspace = Workspace.objects.select_for_update().filter(pk=workspace_id).first()
    if workspace is None:
        workspace = Workspace.objects.select_for_update().filter(tenant_ref=str(workspace_id)).first()
    if workspace is None:
        raise RuntimeNotFoundError("routine workspace is unavailable")
    profile_id = uuid5(PROFILE_ID_NAMESPACE, str(cloud_binding_id))
    profile = (
        RuntimeProfile.objects.select_for_update()
        .filter(pk=profile_id, workspace_id=workspace.id, ally_ref=str(ally_id))
        .first()
    )
    if profile is None:
        raise RuntimeNotFoundError("routine binding is unavailable")
    return workspace, profile


def _ensure_main_binding(profile: RuntimeProfile, main_conversation_id: UUID) -> ConversationBinding:
    binding = (
        ConversationBinding.objects.select_for_update()
        .filter(profile_id=profile.id)
        .first()
    )
    if binding is None:
        try:
            return ConversationBinding.objects.create(
                profile=profile,
                cloud_conversation_ref=str(main_conversation_id),
                hermes_session_id=None,
            )
        except IntegrityError as exc:
            raise RuntimeConflictError("main conversation binding conflicts") from exc
    if binding.cloud_conversation_ref != str(main_conversation_id):
        raise RuntimeConflictError("main conversation binding is different")
    return binding


def _require_routine_admission(
    workspace: Workspace, *, require_readiness: bool = True
) -> None:
    gate = (workspace.release_target or {}).get("routine_admission")
    if gate is not None and (
        not isinstance(gate, dict) or gate.get("enabled") is not True
    ):
        raise RuntimeNotReadyError("routine admission is disabled")
    release_digest = _desired_routine_release_digest()
    if require_readiness and not is_runtime_ready(workspace):
        raise RuntimeNotReadyError("runtime readiness receipt is missing or stale")
    if current_runtime_release_digest(workspace) != release_digest:
        raise RuntimeFencedError("runtime image release is stale")


def _desired_routine_release_digest() -> str:
    try:
        digest = runtime_release_digest(desired_images())
    except ValueError as exc:
        raise RuntimeNotReadyError("runtime image release is invalid") from exc
    if digest is None:
        raise RuntimeNotReadyError("runtime image release is not configured")
    return digest


def _ensure_command_replay(stored: RoutineCommandReceipt, command: Any) -> None:
    if stored.kind != command.kind or stored.fingerprint != command.fingerprint:
        raise RuntimeIdempotencyConflictError("routine command replay conflicts")


def _cancel_receipt_json(receipt: RoutineCancelReceipt) -> dict[str, Any]:
    return {
        "code": receipt.code,
        "routine_execution_id": str(receipt.routine_execution_id),
        "fence": receipt.fence,
        "status": receipt.status,
        "replayed": receipt.replayed,
    }


def _cancel_receipt_from_json(value: dict[str, Any]) -> RoutineCancelReceipt:
    try:
        return RoutineCancelReceipt(
            code=value["code"],
            routine_execution_id=UUID(value["routine_execution_id"]),
            fence=value["fence"],
            status=value["status"],
            replayed=value["replayed"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeConflictError("stored routine cancellation receipt is invalid") from exc


def _store_command_receipt(
    workspace: Workspace,
    command: Any,
    response: dict[str, Any],
) -> RoutineCommandReceipt:
    return RoutineCommandReceipt.objects.create(
        workspace=workspace,
        command_id=command.command_id,
        idempotency_key=command.idempotency_key,
        kind=command.kind,
        fingerprint=command.fingerprint,
        response=response,
    )


def _validate_routine_identity(routine: RoutineExecution, command: Any) -> None:
    scope = command.scope
    if (
        routine.routine_id != getattr(command, "routine_id", routine.routine_id)
        or routine.run_id != command.run_id
        or routine.current_attempt_id != command.attempt_id
        or routine.generation != command.generation
        or routine.cloud_binding_id != scope.cloud_binding_id
    ):
        raise RuntimeFencedError("routine identity or generation is stale")


def _coerce(value: Any, model: type) -> Any:
    if isinstance(value, model):
        return value
    try:
        return model.model_validate(value)
    except ValueError as exc:
        raise RuntimeValidationError("routine command is invalid") from exc


def _next_event_sequence(attempt_id: UUID) -> int:
    latest = (
        ExecutionEvent.objects.filter(attempt_id=attempt_id)
        .order_by("-sequence")
        .values_list("sequence", flat=True)
        .first()
    )
    return (latest or 0) + 1


def _routine_scope(routine: RoutineExecution) -> dict[str, str]:
    return {
        "kind": "workspace",
        "workspace_id": str(routine.workspace_id),
        "owner_user_id": str(routine.owner_user_id),
        "ally_id": str(routine.ally_id),
        "cloud_binding_id": str(routine.cloud_binding_id),
    }


def _uuid(value: UUID | str, name: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError(f"{name} must be a UUID") from exc


def _aware(value: datetime) -> datetime:
    if timezone.is_naive(value):
        raise RuntimeValidationError("timestamp must include a timezone")
    return value


__all__ = [
    "RoutineCancelReceipt",
    "accept_routine_dispatch",
    "append_runtime_routine_result",
    "cancel_routine_wait",
    "decide_routine_approval",
    "disable_routine_admission",
    "enable_routine_admission",
    "expire_routine_approvals",
    "record_routine_result",
    "request_routine_approval",
    "routine_scope_key",
]
