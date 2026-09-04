from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeFencedError,
    RuntimeNotReadyError,
    RuntimeValidationError,
)
from runtime.models import (
    IN_FLIGHT_PROVISIONING_PHASES,
    RuntimeIntent,
    RuntimeIntentOutcome,
    RuntimeOperationState,
    Workspace,
)

from .retry import run_with_sqlite_lock_retry
from .runtime_auth import RuntimeContext


@dataclass(frozen=True, slots=True)
class RuntimeReadinessReceipt:
    status: str
    generation: int
    runtime_start_epoch: int
    accepted_at: datetime


def accept_runtime_readiness(
    context: RuntimeContext,
    boot_id: UUID | str,
    reconciled_generation: int,
    runtime_start_epoch: int,
    *,
    now: datetime | None = None,
) -> RuntimeReadinessReceipt:
    boot = _uuid(boot_id, "boot_id")
    if (
        isinstance(reconciled_generation, bool)
        or not isinstance(reconciled_generation, int)
        or reconciled_generation <= 0
    ):
        raise RuntimeValidationError("reconciled_generation must be positive")
    if (
        isinstance(runtime_start_epoch, bool)
        or not isinstance(runtime_start_epoch, int)
        or runtime_start_epoch < 0
    ):
        raise RuntimeValidationError("runtime_start_epoch must be nonnegative")
    observed_at = _aware(now or timezone.now())

    return run_with_sqlite_lock_retry(
        lambda: _accept_runtime_readiness_once(
            context,
            boot,
            reconciled_generation,
            runtime_start_epoch,
            observed_at,
        )
    )


@transaction.atomic
def _accept_runtime_readiness_once(
    context: RuntimeContext,
    boot_id: UUID,
    reconciled_generation: int,
    runtime_start_epoch: int,
    observed_at: datetime,
) -> RuntimeReadinessReceipt:
    workspace = (
        Workspace.objects.select_for_update().filter(pk=context.workspace_id).first()
    )
    if workspace is None:
        raise RuntimeNotReadyError("runtime workspace does not exist")
    if workspace.machine_generation != context.machine_generation:
        raise RuntimeFencedError("runtime credential belongs to a retired generation")
    if reconciled_generation != workspace.machine_generation:
        raise RuntimeFencedError("readiness belongs to a different machine generation")
    if runtime_start_epoch != workspace.runtime_start_epoch:
        raise RuntimeFencedError("readiness belongs to a retired runtime start")
    if (
        workspace.provisioning_phase in IN_FLIGHT_PROVISIONING_PHASES
        or workspace.machine_generation <= 0
        or not workspace.fly_app_ref
        or not workspace.volume_ref
        or not workspace.machine_ref
    ):
        raise RuntimeNotReadyError("workspace has no current Machine binding")

    accepting_start = (
        workspace.runtime_operation_state == RuntimeOperationState.AWAITING_READINESS
    )
    accepting_idle = workspace.runtime_operation_state == RuntimeOperationState.IDLE
    if not accepting_start and not accepting_idle:
        raise RuntimeNotReadyError("runtime start has no provider evidence")
    boot_replaced = (
        workspace.ready_boot_id is not None and workspace.ready_boot_id != boot_id
    )
    if accepting_start and boot_replaced:
        raise RuntimeConflictError("runtime boot was replaced")

    workspace.ready_generation = reconciled_generation
    workspace.ready_start_epoch = runtime_start_epoch
    workspace.ready_boot_id = boot_id
    if workspace.ready_at is None or accepting_start or boot_replaced:
        workspace.ready_at = observed_at
    workspace.runtime_last_seen_at = observed_at
    if accepting_start:
        operation_id = workspace.runtime_operation_id
        RuntimeIntent.objects.filter(
            workspace_id=workspace.id,
            coalesced_operation_id=operation_id,
            outcome=RuntimeIntentOutcome.WAKING,
        ).update(
            outcome=RuntimeIntentOutcome.READY,
            updated_at=observed_at,
        )
        workspace.runtime_operation_id = None
        workspace.runtime_operation_state = RuntimeOperationState.IDLE
        workspace.runtime_operation_trigger = None
        workspace.runtime_operation_requested_at = None
        workspace.runtime_operation_retry_count = 0
    workspace.save(
        update_fields=[
            "ready_generation",
            "ready_start_epoch",
            "ready_boot_id",
            "ready_at",
            "runtime_last_seen_at",
            "runtime_operation_id",
            "runtime_operation_state",
            "runtime_operation_trigger",
            "runtime_operation_requested_at",
            "runtime_operation_retry_count",
            "updated_at",
        ]
    )
    return RuntimeReadinessReceipt(
        status="ready",
        generation=reconciled_generation,
        runtime_start_epoch=runtime_start_epoch,
        accepted_at=observed_at,
    )


def require_current_runtime_ready_locked(
    workspace: Workspace,
    context: RuntimeContext,
    *,
    now: datetime | None = None,
) -> None:
    """Enforce durable readiness while the caller owns the Workspace lock."""

    if workspace.id != context.workspace_id:
        raise RuntimeFencedError("runtime credential does not match workspace")
    if workspace.machine_generation != context.machine_generation:
        raise RuntimeFencedError("runtime credential belongs to a retired generation")
    observed_at = _aware(now or timezone.now())
    freshness = getattr(settings, "ALLIES_RUNTIME_READINESS_FRESHNESS_SECONDS", 60)
    if not is_runtime_ready(workspace, now=observed_at, freshness_seconds=freshness):
        raise RuntimeNotReadyError("workspace readiness receipt is missing or stale")


def is_runtime_ready(
    workspace: Workspace,
    *,
    now: datetime | None = None,
    freshness_seconds: float | None = None,
) -> bool:
    observed_at = _aware(now or timezone.now())
    freshness = (
        freshness_seconds
        if freshness_seconds is not None
        else getattr(settings, "ALLIES_RUNTIME_READINESS_FRESHNESS_SECONDS", 60)
    )
    return bool(
        workspace.provisioning_phase not in IN_FLIGHT_PROVISIONING_PHASES
        and workspace.machine_generation > 0
        and workspace.fly_app_ref
        and workspace.volume_ref
        and workspace.machine_ref
        and workspace.ready_generation == workspace.machine_generation
        and workspace.ready_start_epoch == workspace.runtime_start_epoch
        and workspace.ready_boot_id is not None
        and workspace.runtime_last_seen_at is not None
        and workspace.runtime_last_seen_at >= observed_at - timedelta(seconds=freshness)
    )


def advance_runtime_start_epoch_locked(workspace: Workspace) -> int:
    """Fence old runtime receipts before any provider start or stop."""

    if workspace.runtime_start_epoch >= 2**63 - 1:
        raise RuntimeConflictError("runtime start epoch is exhausted")
    workspace.runtime_start_epoch += 1
    workspace.ready_generation = None
    workspace.ready_start_epoch = None
    workspace.ready_boot_id = None
    workspace.ready_at = None
    workspace.runtime_last_seen_at = None
    return workspace.runtime_start_epoch


def _uuid(value: UUID | str, name: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError(f"{name} must be a UUID") from exc


def _aware(value: datetime) -> datetime:
    if timezone.is_naive(value):
        raise RuntimeValidationError("timestamps must include a timezone")
    return value


__all__ = [
    "RuntimeReadinessReceipt",
    "accept_runtime_readiness",
    "advance_runtime_start_epoch_locked",
    "is_runtime_ready",
    "require_current_runtime_ready_locked",
]
