from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import Case, Exists, IntegerField, OuterRef, Value, When
from django.utils import timezone

from observability.events import build_event, emit_event
from runtime.exceptions import RuntimeConflictError
from runtime.models import (
    IN_FLIGHT_PROVISIONING_PHASES,
    Attempt,
    AttemptStatus,
    Execution,
    ExecutionStatus,
    Lease,
    LeaseState,
    RuntimeIntent,
    RuntimeIntentOutcome,
    RuntimeOperationState,
    RuntimeOperationTrigger,
    Workspace,
)
from runtime.providers import (
    MachineRecord,
    MachineState,
    ProviderError,
    ProviderNotFoundError,
    ProviderOwnershipError,
    provider_workspace_context,
)

from .runtime_provider import runtime_power_provider
from .runtime_readiness import advance_runtime_start_epoch_locked

OPERATION_CLAIM_SECONDS = 60
EXECUTION_WAKE_RETRY_SECONDS = 5
EXECUTION_WAKE_MAX_RETRIES = 4
MAX_POWER_BATCH = 20
ACTIVE_EXECUTION_STATES = (ExecutionStatus.QUEUED, ExecutionStatus.RUNNING)
ACTIVE_ATTEMPT_STATES = (
    AttemptStatus.QUEUED,
    AttemptStatus.LEASED,
    AttemptStatus.RUNNING,
)
ACTIVE_LEASE_STATES = (LeaseState.ACTIVE, LeaseState.STOPPING)


@dataclass(frozen=True, slots=True)
class RuntimePowerReport:
    examined: int = 0
    started: int = 0
    awaiting_readiness: int = 0
    stopped: int = 0
    failed: int = 0
    skipped: int = 0
    unavailable: int = 0


@dataclass(frozen=True, slots=True)
class RuntimeMaintenanceReport:
    wakes: RuntimePowerReport
    expired_intents: int
    idle_stops: RuntimePowerReport


@dataclass(frozen=True, slots=True)
class _OperationClaim:
    workspace_id: UUID
    operation_id: UUID
    token: str
    trigger: str


def process_runtime_wakes(
    *,
    provider: Any | None = None,
    now: datetime | None = None,
    limit: int = MAX_POWER_BATCH,
) -> RuntimePowerReport:
    _validate_limit(limit)
    observed_at = now or timezone.now()
    provider = provider or _safe_provider()
    if provider is None:
        return RuntimePowerReport(unavailable=1)
    report = RuntimePowerReport()
    for workspace_id in _requested_workspace_ids(
        observed_at,
        limit,
        trigger=RuntimeOperationTrigger.EXECUTION,
    ):
        claim = _claim_requested_operation(workspace_id, observed_at)
        if claim is None:
            continue
        report = _increment(report, examined=1)
        report = _merge(report, _process_wake_claim(claim, provider, observed_at))
    remaining = max(0, limit - report.examined)
    if remaining == 0:
        return report
    report = _merge(
        report,
        _recover_expired_operations(provider, observed_at, remaining),
    )
    remaining = max(0, limit - report.examined)
    if remaining == 0:
        return report
    expired_readiness = _expire_unacknowledged_readiness(observed_at, remaining)
    report = _merge(report, expired_readiness)
    remaining = max(0, limit - report.examined)
    if remaining == 0:
        return report
    for workspace_id in _requested_workspace_ids(observed_at, remaining):
        claim = _claim_requested_operation(workspace_id, observed_at)
        if claim is None:
            continue
        report = _increment(report, examined=1)
        result = _process_wake_claim(claim, provider, observed_at)
        report = _merge(report, result)
    return report


def _expire_unacknowledged_readiness(
    now: datetime,
    limit: int,
) -> RuntimePowerReport:
    timeout = getattr(settings, "ALLIES_RUNTIME_READINESS_TIMEOUT_SECONDS", None)
    if timeout is None:
        timeout = getattr(settings, "ALLIES_RUNTIME_INTENT_TTL_SECONDS", 120)
    cutoff = now - timedelta(seconds=timeout)
    report = RuntimePowerReport()
    ids = list(
        Workspace.objects.filter(
            runtime_operation_state=RuntimeOperationState.AWAITING_READINESS,
            runtime_operation_requested_at__isnull=False,
            runtime_operation_requested_at__lte=cutoff,
        )
        .order_by("runtime_operation_requested_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    for workspace_id in ids:
        if _expire_unacknowledged_readiness_one(workspace_id, cutoff, now):
            report = _increment(report, examined=1, failed=1)
    return report


@transaction.atomic
def _expire_unacknowledged_readiness_one(
    workspace_id: UUID,
    cutoff: datetime,
    now: datetime,
) -> bool:
    workspace = (
        Workspace.objects.select_for_update()
        .filter(
            pk=workspace_id,
            runtime_operation_state=RuntimeOperationState.AWAITING_READINESS,
            runtime_operation_requested_at__isnull=False,
            runtime_operation_requested_at__lte=cutoff,
        )
        .first()
    )
    if workspace is None:
        return False
    _mark_operation_failed_locked(workspace, now=now, retry_execution=True)
    return True


def _recover_expired_operations(
    provider: Any,
    now: datetime,
    limit: int,
) -> RuntimePowerReport:
    """Reconcile claims abandoned by a crashed publisher before retrying."""

    report = RuntimePowerReport()
    for workspace_id in _expired_operation_ids(now, limit):
        workspace = Workspace.objects.filter(pk=workspace_id).first()
        if workspace is None:
            continue
        if (
            workspace.runtime_operation_id is None
            or workspace.activation_claim_token is None
        ):
            _clear_expired_operation(workspace_id, now)
            report = _increment(report, examined=1, failed=1)
            continue
        claim = _OperationClaim(
            workspace.id,
            workspace.runtime_operation_id,
            workspace.activation_claim_token,
            workspace.runtime_operation_trigger or "idle_stop",
        )
        try:
            machine = _inspect_machine(provider, workspace)
            _verify_machine_binding(workspace, machine)
            if workspace.runtime_operation_state == RuntimeOperationState.STARTING:
                if machine.state is MachineState.STARTED:
                    if _recover_start_as_awaiting(claim):
                        report = _increment(report, examined=1, awaiting_readiness=1)
                    continue
                if machine.state is MachineState.STOPPED:
                    if _recover_start_as_requested(claim):
                        report = _increment(report, examined=1)
                    continue
            elif workspace.runtime_operation_state == RuntimeOperationState.STOPPING:
                if machine.state is MachineState.STOPPED:
                    if _recover_stop_as_finished(claim):
                        report = _increment(report, examined=1, stopped=1)
                    continue
                if machine.state is MachineState.STARTED:
                    retry_claim = _recover_stop_as_claimed(claim, now)
                    if retry_claim is not None:
                        result = _process_stop_claim(retry_claim, provider, now)
                        report = _increment(report, examined=1)
                        report = _merge(report, result)
                    continue
            retry_execution = (
                workspace.runtime_operation_state == RuntimeOperationState.STARTING
                and machine.state in {MachineState.CREATED, MachineState.UNKNOWN}
            )
            _mark_operation_failed(
                claim,
                now=now,
                retry_execution=retry_execution,
            )
            report = _increment(report, examined=1, failed=1)
        except ProviderError as exc:
            _mark_operation_failed(
                claim,
                now=now,
                retry_execution=exc.retryable or exc.uncertain,
            )
            report = _increment(report, examined=1, failed=1)
        except RuntimeConflictError:
            _mark_operation_failed(claim, now=now)
            report = _increment(report, examined=1, failed=1)
        except Exception:  # noqa: BLE001 - one stale claim must not halt wakes
            _mark_operation_failed(claim, now=now)
            report = _increment(report, examined=1, failed=1)
    return report


def stop_idle_workspaces(
    *,
    provider: Any | None = None,
    now: datetime | None = None,
    limit: int = MAX_POWER_BATCH,
) -> RuntimePowerReport:
    _validate_limit(limit)
    if not getattr(settings, "ALLIES_RUNTIME_IDLE_STOP_ENABLED", False):
        return RuntimePowerReport()
    observed_at = now or timezone.now()
    provider = provider or _safe_provider()
    if provider is None:
        return RuntimePowerReport(unavailable=1)
    report = RuntimePowerReport()
    for workspace_id in _idle_workspace_ids(observed_at, limit):
        claim = _claim_idle_operation(workspace_id, observed_at)
        if claim is None:
            continue
        report = _increment(report, examined=1)
        result = _process_stop_claim(claim, provider, observed_at)
        report = _merge(report, result)
    return report


def run_runtime_maintenance(
    *,
    provider: Any | None = None,
    now: datetime | None = None,
    limit: int = MAX_POWER_BATCH,
) -> RuntimeMaintenanceReport:
    observed_at = now or timezone.now()
    wakes = process_runtime_wakes(provider=provider, now=observed_at, limit=limit)
    from .runtime_intents import cleanup_runtime_intents

    expired = cleanup_runtime_intents(now=observed_at)
    idle = stop_idle_workspaces(provider=provider, now=observed_at, limit=limit)
    return RuntimeMaintenanceReport(wakes, expired, idle)


def _process_wake_claim(
    claim: _OperationClaim,
    provider: Any,
    now: datetime,
) -> RuntimePowerReport:
    workspace: Workspace | None = None
    try:
        workspace = Workspace.objects.get(pk=claim.workspace_id)
        machine = _inspect_machine(provider, workspace)
        _verify_machine_binding(workspace, machine)
        _prepare_start(claim, now)
        if machine.state is MachineState.STARTED:
            _mark_awaiting_readiness(claim)
            return RuntimePowerReport(awaiting_readiness=1)
        if machine.state is not MachineState.STOPPED:
            _mark_operation_failed(
                claim,
                now=now,
                retry_execution=machine.state
                in {MachineState.CREATED, MachineState.UNKNOWN},
            )
            return RuntimePowerReport(failed=1)
        try:
            with provider_workspace_context(workspace.id):
                provider.start_machine(workspace.fly_app_ref, workspace.machine_ref)
        except ProviderError as exc:
            if not exc.uncertain:
                _mark_operation_failed(
                    claim,
                    now=now,
                    retry_execution=exc.retryable or exc.uncertain,
                )
                return RuntimePowerReport(failed=1)
            inspected = _inspect_machine(provider, workspace)
            if inspected is None or inspected.state is not MachineState.STARTED:
                _mark_operation_failed(claim, now=now, retry_execution=True)
                return RuntimePowerReport(failed=1)
        _mark_awaiting_readiness(claim)
        _emit_power_event(
            "runtime.operation.succeeded", workspace, "awaiting_readiness"
        )
        return RuntimePowerReport(started=1, awaiting_readiness=1)
    except ProviderError as exc:
        _mark_operation_failed(
            claim,
            now=now,
            retry_execution=exc.retryable or exc.uncertain,
        )
        return RuntimePowerReport(failed=1)
    except (RuntimeConflictError, Workspace.DoesNotExist):
        _mark_operation_failed(claim, now=now)
        return RuntimePowerReport(failed=1)
    except Exception as exc:  # noqa: BLE001 - maintenance must keep iterating
        _mark_operation_failed(claim, now=now)
        if workspace is not None:
            _emit_power_event(
                "runtime.operation.failed",
                workspace,
                "error",
                error_type=type(exc).__name__,
            )
        return RuntimePowerReport(failed=1)


def _process_stop_claim(
    claim: _OperationClaim,
    provider: Any,
    now: datetime,
) -> RuntimePowerReport:
    workspace: Workspace | None = None
    try:
        workspace = Workspace.objects.get(pk=claim.workspace_id)
        machine = _inspect_machine(provider, workspace)
        _verify_machine_binding(workspace, machine)
        if machine.state is MachineState.STOPPED:
            _prepare_stop(claim, now)
            _finalize_stop(claim)
            return RuntimePowerReport(stopped=1)
        if machine.state is not MachineState.STARTED:
            _mark_operation_failed(claim, now=now, clear_keep_warm=True)
            return RuntimePowerReport(failed=1)
        _prepare_stop(claim, now)
        try:
            with provider_workspace_context(workspace.id):
                provider.stop_machine(workspace.fly_app_ref, workspace.machine_ref)
        except ProviderError as exc:
            if not exc.uncertain:
                _mark_operation_failed(claim, now=now, clear_keep_warm=True)
                return RuntimePowerReport(failed=1)
            inspected = _inspect_machine(provider, workspace)
            if inspected is None or inspected.state is not MachineState.STOPPED:
                _mark_operation_failed(claim, now=now, clear_keep_warm=True)
                return RuntimePowerReport(failed=1)
        _finalize_stop(claim)
        _emit_power_event("runtime.operation.succeeded", workspace, "stopped")
        return RuntimePowerReport(stopped=1)
    except RuntimeConflictError:
        _mark_operation_failed(claim, now=now)
        return RuntimePowerReport(failed=1)
    except (ProviderError, Workspace.DoesNotExist):
        _mark_operation_failed(claim, now=now, clear_keep_warm=True)
        return RuntimePowerReport(failed=1)
    except Exception as exc:  # noqa: BLE001 - maintenance must keep iterating
        _mark_operation_failed(claim, now=now, clear_keep_warm=True)
        if workspace is not None:
            _emit_power_event(
                "runtime.operation.failed",
                workspace,
                "error",
                error_type=type(exc).__name__,
            )
        return RuntimePowerReport(failed=1)


@transaction.atomic
def _claim_requested_operation(
    workspace_id: UUID,
    now: datetime,
) -> _OperationClaim | None:
    workspace = Workspace.objects.select_for_update().filter(pk=workspace_id).first()
    if (
        workspace is None
        or workspace.runtime_operation_state != RuntimeOperationState.REQUESTED
    ):
        return None
    if (
        workspace.runtime_operation_id is None
        or workspace.runtime_operation_trigger is None
    ):
        return None
    if workspace.provisioning_phase in IN_FLIGHT_PROVISIONING_PHASES:
        return None
    if (
        workspace.runtime_operation_trigger == RuntimeOperationTrigger.SPECULATIVE
        and not RuntimeIntent.objects.filter(
            workspace_id=workspace.id,
            coalesced_operation_id=workspace.runtime_operation_id,
            outcome=RuntimeIntentOutcome.WAKING,
            expires_at__gte=now,
        ).exists()
    ):
        _mark_operation_failed_locked(workspace, now=now)
        return None
    token = secrets.token_urlsafe(24)
    workspace.runtime_operation_state = RuntimeOperationState.STARTING
    workspace.activation_claim_token = token
    workspace.activation_claim_expires_at = now + timedelta(
        seconds=OPERATION_CLAIM_SECONDS
    )
    workspace.save(
        update_fields=[
            "runtime_operation_state",
            "activation_claim_token",
            "activation_claim_expires_at",
            "updated_at",
        ]
    )
    return _OperationClaim(
        workspace.id,
        workspace.runtime_operation_id,
        token,
        workspace.runtime_operation_trigger,
    )


def _expired_operation_ids(now: datetime, limit: int) -> list[UUID]:
    return list(
        Workspace.objects.filter(
            runtime_operation_state__in=(
                RuntimeOperationState.STARTING,
                RuntimeOperationState.STOPPING,
            ),
            activation_claim_expires_at__isnull=False,
            activation_claim_expires_at__lte=now,
        )
        .order_by("activation_claim_expires_at", "id")
        .values_list("id", flat=True)[:limit]
    )


@transaction.atomic
def _recover_start_as_awaiting(claim: _OperationClaim) -> bool:
    workspace = (
        Workspace.objects.select_for_update().filter(pk=claim.workspace_id).first()
    )
    if not _same_expired_claim(workspace, claim, RuntimeOperationState.STARTING):
        return False
    workspace.runtime_operation_state = RuntimeOperationState.AWAITING_READINESS
    workspace.activation_claim_token = None
    workspace.activation_claim_expires_at = None
    workspace.save(
        update_fields=[
            "runtime_operation_state",
            "activation_claim_token",
            "activation_claim_expires_at",
            "updated_at",
        ]
    )
    return True


@transaction.atomic
def _recover_start_as_requested(claim: _OperationClaim) -> bool:
    workspace = (
        Workspace.objects.select_for_update().filter(pk=claim.workspace_id).first()
    )
    if not _same_expired_claim(workspace, claim, RuntimeOperationState.STARTING):
        return False
    workspace.runtime_operation_state = RuntimeOperationState.REQUESTED
    workspace.activation_claim_token = None
    workspace.activation_claim_expires_at = None
    workspace.save(
        update_fields=[
            "runtime_operation_state",
            "activation_claim_token",
            "activation_claim_expires_at",
            "updated_at",
        ]
    )
    return True


@transaction.atomic
def _recover_stop_as_finished(claim: _OperationClaim) -> bool:
    workspace = (
        Workspace.objects.select_for_update().filter(pk=claim.workspace_id).first()
    )
    if not _same_expired_claim(workspace, claim, RuntimeOperationState.STOPPING):
        return False
    # Even when the provider reports an already-stopped Machine, advancing the
    # epoch fences any receipt from the runtime that was running before it.
    advance_runtime_start_epoch_locked(workspace)
    workspace.runtime_operation_id = None
    workspace.runtime_operation_state = RuntimeOperationState.IDLE
    workspace.runtime_operation_trigger = None
    workspace.runtime_operation_requested_at = None
    workspace.speculative_keep_warm_until = None
    workspace.activation_claim_token = None
    workspace.activation_claim_expires_at = None
    workspace.save(
        update_fields=[
            "runtime_start_epoch",
            "ready_generation",
            "ready_start_epoch",
            "ready_boot_id",
            "ready_at",
            "runtime_last_seen_at",
            "runtime_operation_id",
            "runtime_operation_state",
            "runtime_operation_trigger",
            "runtime_operation_requested_at",
            "speculative_keep_warm_until",
            "activation_claim_token",
            "activation_claim_expires_at",
            "updated_at",
        ]
    )
    return True


@transaction.atomic
def _recover_stop_as_claimed(
    claim: _OperationClaim,
    now: datetime,
) -> _OperationClaim | None:
    workspace = (
        Workspace.objects.select_for_update().filter(pk=claim.workspace_id).first()
    )
    if not _same_expired_claim(workspace, claim, RuntimeOperationState.STOPPING):
        return None
    operation_id = uuid4()
    token = secrets.token_urlsafe(24)
    workspace.runtime_operation_id = operation_id
    workspace.runtime_operation_state = RuntimeOperationState.STOPPING
    workspace.runtime_operation_requested_at = now
    workspace.activation_claim_token = token
    workspace.activation_claim_expires_at = now + timedelta(
        seconds=OPERATION_CLAIM_SECONDS
    )
    workspace.save(
        update_fields=[
            "runtime_operation_id",
            "runtime_operation_state",
            "runtime_operation_requested_at",
            "activation_claim_token",
            "activation_claim_expires_at",
            "updated_at",
        ]
    )
    return _OperationClaim(workspace.id, operation_id, token, "idle_stop")


@transaction.atomic
def _clear_expired_operation(workspace_id: UUID, now: datetime) -> None:
    workspace = Workspace.objects.select_for_update().filter(pk=workspace_id).first()
    if workspace is None or workspace.runtime_operation_id is None:
        return
    if workspace.runtime_operation_state not in {
        RuntimeOperationState.STARTING,
        RuntimeOperationState.STOPPING,
    }:
        return
    _mark_operation_failed_locked(workspace, now=now)


def _same_expired_claim(
    workspace: Workspace | None,
    claim: _OperationClaim,
    state: str,
) -> bool:
    return bool(
        workspace is not None
        and workspace.runtime_operation_id == claim.operation_id
        and workspace.runtime_operation_state == state
        and workspace.activation_claim_token == claim.token
    )


@transaction.atomic
def _prepare_start(claim: _OperationClaim, now: datetime) -> None:
    workspace = _owned_operation(claim, RuntimeOperationState.STARTING)
    advance_runtime_start_epoch_locked(workspace)
    if claim.trigger == RuntimeOperationTrigger.SPECULATIVE:
        workspace.last_speculative_start_at = now
    workspace.save(
        update_fields=[
            "runtime_start_epoch",
            "ready_generation",
            "ready_start_epoch",
            "ready_boot_id",
            "ready_at",
            "runtime_last_seen_at",
            "last_speculative_start_at",
            "updated_at",
        ]
    )


@transaction.atomic
def _prepare_stop(claim: _OperationClaim, now: datetime) -> None:
    workspace = _owned_operation(claim, RuntimeOperationState.STOPPING)
    if not _idle_candidate_locked(workspace, now, allow_stopping=True):
        # A prompt, execution, lease, or other activity won the race after
        # the candidate query.  Leave the newer state untouched and make the
        # old stop claim fail its compare-and-set boundary.
        raise RuntimeConflictError("workspace is no longer idle")
    advance_runtime_start_epoch_locked(workspace)
    workspace.save(
        update_fields=[
            "runtime_start_epoch",
            "ready_generation",
            "ready_start_epoch",
            "ready_boot_id",
            "ready_at",
            "runtime_last_seen_at",
            "updated_at",
        ]
    )


@transaction.atomic
def _mark_awaiting_readiness(claim: _OperationClaim) -> None:
    workspace = _owned_operation(claim, RuntimeOperationState.STARTING)
    workspace.runtime_operation_state = RuntimeOperationState.AWAITING_READINESS
    workspace.activation_claim_token = None
    workspace.activation_claim_expires_at = None
    workspace.save(
        update_fields=[
            "runtime_operation_state",
            "activation_claim_token",
            "activation_claim_expires_at",
            "updated_at",
        ]
    )


@transaction.atomic
def _finalize_stop(claim: _OperationClaim) -> None:
    workspace = _owned_operation(claim, RuntimeOperationState.STOPPING)
    workspace.runtime_operation_id = None
    workspace.runtime_operation_state = RuntimeOperationState.IDLE
    workspace.runtime_operation_trigger = None
    workspace.runtime_operation_requested_at = None
    workspace.speculative_keep_warm_until = None
    workspace.activation_claim_token = None
    workspace.activation_claim_expires_at = None
    workspace.save(
        update_fields=[
            "runtime_operation_id",
            "runtime_operation_state",
            "runtime_operation_trigger",
            "runtime_operation_requested_at",
            "speculative_keep_warm_until",
            "activation_claim_token",
            "activation_claim_expires_at",
            "updated_at",
        ]
    )


@transaction.atomic
def _mark_operation_failed(
    claim: _OperationClaim,
    *,
    now: datetime | None = None,
    retry_execution: bool = False,
    clear_keep_warm: bool = False,
) -> None:
    workspace = (
        Workspace.objects.select_for_update().filter(pk=claim.workspace_id).first()
    )
    if workspace is None:
        return
    if (
        workspace.runtime_operation_id != claim.operation_id
        or workspace.activation_claim_token != claim.token
    ):
        return
    _mark_operation_failed_locked(
        workspace,
        now=now,
        retry_execution=retry_execution,
        clear_keep_warm=clear_keep_warm,
    )


def _mark_operation_failed_locked(
    workspace: Workspace,
    *,
    now: datetime | None = None,
    retry_execution: bool = False,
    clear_keep_warm: bool = False,
) -> None:
    operation_id = workspace.runtime_operation_id
    observed_at = now or timezone.now()
    retry_execution = (
        retry_execution
        and workspace.runtime_operation_trigger == RuntimeOperationTrigger.EXECUTION
        and Execution.objects.filter(
            workspace_id=workspace.id,
            status=ExecutionStatus.QUEUED,
        ).exists()
        and workspace.runtime_operation_retry_count < EXECUTION_WAKE_MAX_RETRIES
    )
    if operation_id is not None:
        RuntimeIntent.objects.filter(
            workspace_id=workspace.id,
            coalesced_operation_id=operation_id,
            outcome=RuntimeIntentOutcome.WAKING,
        ).update(
            outcome=RuntimeIntentOutcome.FAILED,
            updated_at=observed_at,
        )
    if retry_execution:
        retry_count = workspace.runtime_operation_retry_count + 1
        workspace.runtime_operation_id = uuid4()
        workspace.runtime_operation_state = RuntimeOperationState.REQUESTED
        workspace.runtime_operation_requested_at = observed_at + timedelta(
            seconds=EXECUTION_WAKE_RETRY_SECONDS * 2 ** (retry_count - 1)
        )
        workspace.runtime_operation_retry_count = retry_count
        workspace.activation_claim_token = None
        workspace.activation_claim_expires_at = None
        workspace.save(
            update_fields=[
                "runtime_operation_id",
                "runtime_operation_state",
                "runtime_operation_requested_at",
                "runtime_operation_retry_count",
                "activation_claim_token",
                "activation_claim_expires_at",
                "updated_at",
            ]
        )
        return
    if clear_keep_warm:
        workspace.speculative_keep_warm_until = None
    workspace.runtime_operation_id = None
    workspace.runtime_operation_state = RuntimeOperationState.IDLE
    workspace.runtime_operation_trigger = None
    workspace.runtime_operation_requested_at = None
    workspace.runtime_operation_retry_count = 0
    workspace.activation_claim_token = None
    workspace.activation_claim_expires_at = None
    workspace.save(
        update_fields=[
            "runtime_operation_id",
            "runtime_operation_state",
            "runtime_operation_trigger",
            "runtime_operation_requested_at",
            "runtime_operation_retry_count",
            "speculative_keep_warm_until",
            "activation_claim_token",
            "activation_claim_expires_at",
            "updated_at",
        ]
    )


@transaction.atomic
def _claim_idle_operation(workspace_id: UUID, now: datetime) -> _OperationClaim | None:
    workspace = Workspace.objects.select_for_update().filter(pk=workspace_id).first()
    if workspace is None or not _idle_candidate_locked(workspace, now):
        return None
    operation_id = uuid4()
    token = secrets.token_urlsafe(24)
    workspace.runtime_operation_id = operation_id
    workspace.runtime_operation_state = RuntimeOperationState.STOPPING
    workspace.runtime_operation_trigger = None
    workspace.runtime_operation_requested_at = now
    workspace.activation_claim_token = token
    workspace.activation_claim_expires_at = now + timedelta(
        seconds=OPERATION_CLAIM_SECONDS
    )
    workspace.save(
        update_fields=[
            "runtime_operation_id",
            "runtime_operation_state",
            "runtime_operation_trigger",
            "runtime_operation_requested_at",
            "activation_claim_token",
            "activation_claim_expires_at",
            "updated_at",
        ]
    )
    return _OperationClaim(workspace.id, operation_id, token, "idle_stop")


def _owned_operation(claim: _OperationClaim, state: str) -> Workspace:
    workspace = (
        Workspace.objects.select_for_update().filter(pk=claim.workspace_id).first()
    )
    if (
        workspace is None
        or workspace.runtime_operation_id != claim.operation_id
        or workspace.runtime_operation_state != state
        or workspace.activation_claim_token != claim.token
    ):
        raise RuntimeConflictError("runtime operation claim is stale")
    return workspace


def _requested_workspace_ids(
    now: datetime,
    limit: int,
    *,
    trigger: str | None = None,
) -> list[UUID]:
    query = Workspace.objects.filter(
        runtime_operation_state=RuntimeOperationState.REQUESTED,
        runtime_operation_requested_at__lte=now,
    )
    if trigger is not None:
        query = query.filter(runtime_operation_trigger=trigger)
    return list(
        query
        .annotate(
            trigger_priority=Case(
                When(
                    runtime_operation_trigger=RuntimeOperationTrigger.EXECUTION,
                    then=Value(0),
                ),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("trigger_priority", "runtime_operation_requested_at", "id")
        .values_list("id", flat=True)[:limit]
    )


def _idle_workspace_ids(now: datetime, limit: int) -> list[UUID]:
    active_execution = Execution.objects.filter(
        workspace_id=OuterRef("pk"), status__in=ACTIVE_EXECUTION_STATES
    )
    active_attempt = Attempt.objects.filter(
        execution__workspace_id=OuterRef("pk"), status__in=ACTIVE_ATTEMPT_STATES
    )
    active_lease = Lease.objects.filter(
        profile__workspace_id=OuterRef("pk"), state__in=ACTIVE_LEASE_STATES
    )
    return list(
        Workspace.objects.filter(
            runtime_operation_state=RuntimeOperationState.IDLE,
            speculative_keep_warm_until__isnull=False,
            speculative_keep_warm_until__lte=now,
            machine_generation__gt=0,
            fly_app_ref__isnull=False,
            volume_ref__isnull=False,
            machine_ref__isnull=False,
        )
        .exclude(provisioning_phase__in=IN_FLIGHT_PROVISIONING_PHASES)
        .annotate(
            has_active_execution=Exists(active_execution),
            has_active_attempt=Exists(active_attempt),
            has_active_lease=Exists(active_lease),
        )
        .filter(
            has_active_execution=False,
            has_active_attempt=False,
            has_active_lease=False,
        )
        .order_by("speculative_keep_warm_until", "id")
        .values_list("id", flat=True)[:limit]
    )


def _idle_candidate_locked(
    workspace: Workspace,
    now: datetime,
    *,
    allow_stopping: bool = False,
) -> bool:
    if not getattr(settings, "ALLIES_RUNTIME_IDLE_STOP_ENABLED", False):
        return False
    if (
        workspace.runtime_operation_state
        != (
            RuntimeOperationState.STOPPING
            if allow_stopping
            else RuntimeOperationState.IDLE
        )
        or workspace.provisioning_phase in IN_FLIGHT_PROVISIONING_PHASES
        or workspace.speculative_keep_warm_until is None
        or workspace.speculative_keep_warm_until > now
        or workspace.machine_generation <= 0
        or not workspace.fly_app_ref
        or not workspace.volume_ref
        or not workspace.machine_ref
    ):
        return False
    if Execution.objects.filter(
        workspace_id=workspace.id, status__in=ACTIVE_EXECUTION_STATES
    ).exists():
        return False
    if Attempt.objects.filter(
        execution__workspace_id=workspace.id, status__in=ACTIVE_ATTEMPT_STATES
    ).exists():
        return False
    return not Lease.objects.filter(
        profile__workspace_id=workspace.id, state__in=ACTIVE_LEASE_STATES
    ).exists()


def _inspect_machine(provider: Any, workspace: Workspace) -> MachineRecord | None:
    if not workspace.fly_app_ref or not workspace.machine_ref:
        return None
    inspect = getattr(provider, "inspect_machine_by_id", None)
    try:
        with provider_workspace_context(workspace.id):
            if callable(inspect):
                return inspect(workspace.fly_app_ref, workspace.machine_ref)
            return provider.inspect_machine(
                workspace.fly_app_ref, workspace.machine_ref
            )
    except ProviderNotFoundError:
        return None


def _verify_machine_binding(
    workspace: Workspace, machine: MachineRecord | None
) -> None:
    if machine is None or machine.id != workspace.machine_ref:
        raise ProviderNotFoundError("recorded workspace Machine is unavailable")
    if machine.app_name != workspace.fly_app_ref:
        raise ProviderOwnershipError("recorded Machine belongs to another App")
    if machine.volume_id != workspace.volume_ref:
        raise ProviderOwnershipError("recorded Machine is mounted to another Volume")
    ownership = machine.ownership
    if ownership is None or (
        str(ownership.workspace_id) != str(workspace.id)
        or workspace.provisioning_id is None
        or str(ownership.operation_id) != str(workspace.provisioning_id)
        or ownership.generation != workspace.machine_generation
    ):
        raise ProviderOwnershipError("recorded Machine ownership does not match")


def _safe_provider() -> Any | None:
    try:
        return runtime_power_provider()
    except ProviderError:
        return None


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not 1 <= limit <= MAX_POWER_BATCH:
        raise ValueError("power batch limit must be between 1 and 20")


def _increment(report: RuntimePowerReport, **changes: int) -> RuntimePowerReport:
    values = {
        "examined": report.examined,
        "started": report.started,
        "awaiting_readiness": report.awaiting_readiness,
        "stopped": report.stopped,
        "failed": report.failed,
        "skipped": report.skipped,
        "unavailable": report.unavailable,
    }
    values.update({key: values[key] + value for key, value in changes.items()})
    return RuntimePowerReport(**values)


def _merge(left: RuntimePowerReport, right: RuntimePowerReport) -> RuntimePowerReport:
    return _increment(
        left,
        examined=right.examined,
        started=right.started,
        awaiting_readiness=right.awaiting_readiness,
        stopped=right.stopped,
        failed=right.failed,
        skipped=right.skipped,
        unavailable=right.unavailable,
    )


def _emit_power_event(
    event_name: str, workspace: Workspace, outcome: str, **fields: Any
):
    try:
        emit_event(
            build_event(
                event_name,
                operation="runtime_power",
                workspace_id=str(workspace.id),
                outcome=outcome,
                **fields,
            )
        )
    except Exception:  # noqa: BLE001 - observability cannot block maintenance
        return


__all__ = [
    "MAX_POWER_BATCH",
    "RuntimeMaintenanceReport",
    "RuntimePowerReport",
    "process_runtime_wakes",
    "run_runtime_maintenance",
    "stop_idle_workspaces",
]
