"""Durable lifecycle orchestration for a tenant Fly workspace.

The service deliberately keeps the database transaction at the phase claim and
result boundaries.  A provider request never runs while a Workspace row is
locked; the row's provisioning fields are the durable hand-off between two
Foundry processes.
"""

from __future__ import annotations

import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from observability.events import build_event, emit_event
from runtime.exceptions import RuntimeConflictError, RuntimeValidationError
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
    WorkspaceProvisioningKind,
    WorkspaceProvisioningPhase,
)
from runtime.providers import (
    AppRecord,
    AppSpec,
    ContainerSpec,
    ContainerState,
    MachineHealth,
    MachineRecord,
    MachineSpec,
    MachineState,
    OpaqueReference,
    OwnershipMetadata,
    ProviderAttachmentConflictError,
    ProviderError,
    ProviderInvalidConfigurationError,
    ProviderNotFoundError,
    ProviderOwnershipError,
    ProviderRetryableError,
    ProviderTerminalError,
    ProviderTimeoutError,
    VolumeMount,
    VolumeRecord,
    VolumeSpec,
    deterministic_resource_names,
)
from runtime.providers.protocol import WorkspaceProvider, provider_workspace_context

from .retry import run_with_sqlite_lock_retry

# A Machine reconciliation can make four sequential ten-second provider
# requests (inspect, volume check, create, and timeout reconciliation). Keep
# the claim longer than that bounded sequence so a live side effect cannot be
# taken over by another Foundry process.
CLAIM_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 10
PHASE_DEADLINE_SECONDS = 120
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = (0.5, 1.0, 2.0, 4.0)
STOP_POLL_SECONDS = 0.05
HEALTH_POLL_SECONDS = 1.0
REQUIRED_CONTAINERS = frozenset(("hermes", "allies-runtime"))


class WorkspaceReplacementRequiredError(RuntimeConflictError):
    """The durable binding exists but its recorded Machine is gone."""

    code = "replacement_required"


class WorkspaceStaleOperationError(RuntimeConflictError):
    code = "stale_operation"


@dataclass(frozen=True, slots=True)
class WorkspaceSpec:
    """Deployment input for one tenant Machine.

    Images and the opaque credential reference are inputs, never values read
    from a Workspace row.  ``containers`` is accepted for tests and for later
    image-shape evolution; when omitted the two image fields build the
    required two-container topology.
    """

    organization: str = "allies"
    region: str = "ams"
    hermes_image: str | None = None
    runtime_image: str | None = None
    runtime_credential_ref: OpaqueReference | str | None = None
    foundry_origin: str | None = None
    foundry_runtime_credential_ref: OpaqueReference | str | None = None
    foundry_runtime_credential_secret_name: str | None = None
    volume_size_gb: int = 1
    filesystem: str = "ext4"
    containers: tuple[ContainerSpec, ...] | None = None

    def __post_init__(self) -> None:
        if not self.organization or not self.region:
            raise ValueError("organization and region are required")
        if type(self.volume_size_gb) is not int or self.volume_size_gb <= 0:
            raise ValueError("volume_size_gb must be positive")
        if self.containers is not None and not isinstance(self.containers, tuple):
            object.__setattr__(self, "containers", tuple(self.containers))

    def app_spec(self, workspace_id: UUID | str) -> AppSpec:
        names = deterministic_resource_names(workspace_id)
        return AppSpec(names.app, self.organization, self.region)

    def volume_spec(self, workspace_id: UUID | str) -> VolumeSpec:
        names = deterministic_resource_names(workspace_id)
        return VolumeSpec(
            names.app,
            names.volume,
            self.region,
            self.volume_size_gb,
            self.filesystem,
        )

    def machine_spec(
        self,
        workspace_id: UUID | str,
        volume_id: str,
        generation: int,
        operation_id: UUID,
    ) -> MachineSpec:
        names = deterministic_resource_names(workspace_id)
        containers = self.containers
        if containers is None:
            if not self.hermes_image or not self.runtime_image:
                raise ValueError(
                    "hermes_image and runtime_image are required when containers are omitted"
                )
            containers = (
                ContainerSpec(
                    "hermes",
                    self.hermes_image,
                    healthchecks=(_default_process_healthcheck("hermes"),),
                ),
                ContainerSpec(
                    "allies-runtime",
                    self.runtime_image,
                    healthchecks=(_default_process_healthcheck("allies-runtime"),),
                ),
            )
        return MachineSpec(
            app_name=names.app,
            name=names.machine(generation),
            region=self.region,
            containers=containers,
            mount=VolumeMount(volume_id),
            ownership=OwnershipMetadata(workspace_id, operation_id, generation),
            runtime_credential_ref=self.runtime_credential_ref,
            foundry_origin=self.foundry_origin,
            foundry_runtime_credential_ref=self.foundry_runtime_credential_ref,
            foundry_runtime_credential_secret_name=(
                self.foundry_runtime_credential_secret_name
            ),
        )


@dataclass(frozen=True, slots=True)
class ReplacementProofPrecondition:
    """Read-only proof state that must exist before generation fencing."""

    active_attempt_ids: tuple[UUID, UUID]
    queued_execution_id: UUID

    def __post_init__(self) -> None:
        if (
            not isinstance(self.active_attempt_ids, tuple)
            or len(self.active_attempt_ids) != 2
            or len(set(self.active_attempt_ids)) != 2
            or not all(isinstance(item, UUID) for item in self.active_attempt_ids)
        ):
            raise RuntimeValidationError("exactly two active attempt IDs are required")
        if not isinstance(self.queued_execution_id, UUID):
            raise RuntimeValidationError("queued_execution_id must be a UUID")

    def assert_satisfied(self, workspace: Workspace) -> None:
        attempts = list(
            Attempt.objects.select_related("execution__profile")
            .filter(
                pk__in=self.active_attempt_ids,
                execution__workspace_id=workspace.id,
                execution__status=ExecutionStatus.RUNNING,
                status=AttemptStatus.RUNNING,
                machine_generation=workspace.machine_generation,
            )
            .order_by("id")
        )
        if (
            len(attempts) != 2
            or len({item.execution.profile_id for item in attempts}) != 2
        ):
            raise RuntimeConflictError(
                "replacement proof requires two active profile-scoped attempts"
            )
        attempt_ids = {item.id for item in attempts}
        active_leases = set(
            Lease.objects.filter(
                attempt_id__in=attempt_ids,
                state=LeaseState.ACTIVE,
                machine_generation=workspace.machine_generation,
                expires_at__gt=timezone.now(),
            ).values_list("attempt_id", flat=True)
        )
        if active_leases != attempt_ids:
            raise RuntimeConflictError(
                "replacement proof attempts must have active generation leases"
            )
        dispatched = set(
            ExecutionEvent.objects.filter(
                attempt_id__in=attempt_ids,
                event_type="execution.dispatched",
            ).values_list("attempt_id", flat=True)
        )
        safe_progress = set(
            ExecutionEvent.objects.filter(attempt_id__in=attempt_ids)
            .exclude(event_type="execution.dispatched")
            .values_list("attempt_id", flat=True)
        )
        if dispatched != attempt_ids or safe_progress != attempt_ids:
            raise RuntimeConflictError(
                "replacement proof attempts must have durable dispatch and progress"
            )
        queued = (
            Execution.objects.filter(
                pk=self.queued_execution_id,
                workspace_id=workspace.id,
                status=ExecutionStatus.QUEUED,
            )
            .only("profile_id")
            .first()
        )
        if queued is None or queued.profile_id not in {
            item.execution.profile_id for item in attempts
        }:
            raise RuntimeConflictError(
                "replacement proof requires a same-profile queued execution"
            )


@dataclass(frozen=True, slots=True)
class WorkspaceBinding:
    workspace_id: UUID
    app_ref: str
    volume_ref: str
    machine_ref: str
    machine_generation: int
    provisioning_id: UUID | None = None

    @classmethod
    def from_workspace(cls, workspace: Workspace) -> WorkspaceBinding:
        if not (
            workspace.fly_app_ref
            and workspace.volume_ref
            and workspace.machine_ref
            and workspace.machine_generation > 0
        ):
            raise RuntimeConflictError("workspace has no complete provider binding")
        return cls(
            workspace.id,
            workspace.fly_app_ref,
            workspace.volume_ref,
            workspace.machine_ref,
            workspace.machine_generation,
            workspace.provisioning_id,
        )


@dataclass(frozen=True, slots=True)
class _Claim:
    operation_id: UUID
    token: str
    phase: str
    target_generation: int
    previous_machine_ref: str | None


class WorkspaceLifecycle:
    """Run one Workspace operation against an injected provider."""

    def __init__(
        self,
        provider: WorkspaceProvider,
        *,
        clock=timezone.now,
        sleep=time.sleep,
        jitter: bool = True,
        phase_deadline_seconds: float = PHASE_DEADLINE_SECONDS,
        fence_callback: Callable[[UUID, int, int, str | None], Any] | None = None,
    ) -> None:
        self.provider = provider
        self.clock = clock
        self.sleep = sleep
        self.jitter = jitter
        self.phase_deadline_seconds = phase_deadline_seconds
        self.fence_callback = fence_callback
        self._phase_attempts: dict[str, int] = {}
        self._retry_reasons: dict[str, tuple[UUID, str | None]] = {}

    def ensure_workspace(
        self,
        workspace_id: UUID | str,
        spec: WorkspaceSpec,
        *,
        before_bind: Callable[[UUID, WorkspaceSpec, _Claim, float], None] | None = None,
    ) -> WorkspaceBinding:
        """Ensure a workspace and retain the existing lifecycle semantics."""

        started_at = time.monotonic()
        safe_workspace_id = str(workspace_id)
        emit_event(
            build_event(
                "runtime.operation.started",
                operation="workspace_ensure",
                workspace_id=safe_workspace_id,
                outcome="started",
            ),
        )
        try:
            result = self._ensure_workspace(workspace_id, spec, before_bind=before_bind)
        except BaseException as error:
            emit_event(
                build_event(
                    "runtime.operation.failed",
                    operation="workspace_ensure",
                    workspace_id=safe_workspace_id,
                    duration_ms=(time.monotonic() - started_at) * 1000,
                    outcome="error",
                    error_type=type(error).__name__,
                )
            )
            raise
        emit_event(
            build_event(
                "runtime.operation.succeeded",
                operation="workspace_ensure",
                workspace_id=safe_workspace_id,
                duration_ms=(time.monotonic() - started_at) * 1000,
                outcome="success",
            )
        )
        return result

    def _ensure_workspace(
        self,
        workspace_id: UUID | str,
        spec: WorkspaceSpec,
        *,
        before_bind: Callable[[UUID, WorkspaceSpec, _Claim, float], None] | None = None,
    ) -> WorkspaceBinding:
        workspace_id = _uuid(workspace_id)
        deadline = self._deadline()
        while True:
            operation = self._claim_or_wait(
                workspace_id,
                WorkspaceProvisioningKind.ENSURE,
                expected_source_generation=None,
            )
            if isinstance(operation, WorkspaceBinding):
                self._verify_existing_machine(operation, workspace_id)
                return operation
            if operation is None:
                self._wait_for_other_operation(deadline)
                continue
            self._emit_retry_if_pending(
                workspace_id, operation, operation_name="workspace_ensure"
            )
            self._begin_attempt(operation.phase)
            try:
                with provider_workspace_context(workspace_id):
                    result = self._run_ensure_phase(
                        workspace_id, spec, operation, deadline, before_bind
                    )
                if result is not None:
                    return result
                self._phase_attempts.pop(operation.phase, None)
            except (ProviderError, ValueError) as error:
                if isinstance(error, ValueError) and not isinstance(
                    error, ProviderError
                ):
                    error = ProviderInvalidConfigurationError(
                        str(error), operation="workspace_spec"
                    )
                self._handle_failure(workspace_id, operation, error)
                if not error.retryable:
                    raise
                if self._phase_attempts.get(operation.phase, 0) >= MAX_ATTEMPTS:
                    raise
            self._backoff(operation.phase)

    def replace_machine(
        self,
        workspace_id: UUID | str,
        spec: WorkspaceSpec,
        expected_source_generation: int,
        proof_precondition: ReplacementProofPrecondition | None = None,
    ) -> WorkspaceBinding:
        """Replace a workspace Machine with lifecycle evidence."""

        started_at = time.monotonic()
        safe_workspace_id = str(workspace_id)
        emit_event(
            build_event(
                "runtime.operation.started",
                operation="workspace_replace",
                workspace_id=safe_workspace_id,
                outcome="started",
            )
        )
        try:
            result = self._replace_machine(
                workspace_id,
                spec,
                expected_source_generation,
                proof_precondition,
            )
        except BaseException as error:
            emit_event(
                build_event(
                    "runtime.operation.failed",
                    operation="workspace_replace",
                    workspace_id=safe_workspace_id,
                    duration_ms=(time.monotonic() - started_at) * 1000,
                    outcome="error",
                    error_type=type(error).__name__,
                )
            )
            raise
        emit_event(
            build_event(
                "runtime.operation.succeeded",
                operation="workspace_replace",
                workspace_id=safe_workspace_id,
                duration_ms=(time.monotonic() - started_at) * 1000,
                outcome="success",
            )
        )
        return result

    def _replace_machine(
        self,
        workspace_id: UUID | str,
        spec: WorkspaceSpec,
        expected_source_generation: int,
        proof_precondition: ReplacementProofPrecondition | None = None,
    ) -> WorkspaceBinding:
        workspace_id = _uuid(workspace_id)
        if (
            type(expected_source_generation) is not int
            or expected_source_generation <= 0
        ):
            raise RuntimeValidationError("expected_source_generation must be positive")
        deadline = self._deadline()
        while True:
            operation = self._claim_or_wait(
                workspace_id,
                WorkspaceProvisioningKind.REPLACE,
                expected_source_generation=expected_source_generation,
                proof_precondition=proof_precondition,
            )
            if isinstance(operation, WorkspaceBinding):
                return operation
            if operation is None:
                self._wait_for_other_operation(deadline)
                continue
            self._emit_retry_if_pending(
                workspace_id, operation, operation_name="workspace_replace"
            )
            self._begin_attempt(operation.phase)
            try:
                with provider_workspace_context(workspace_id):
                    result = self._run_replace_phase(
                        workspace_id, spec, operation, deadline
                    )
                if result is not None:
                    return result
                self._phase_attempts.pop(operation.phase, None)
            except (ProviderError, ValueError) as error:
                if isinstance(error, ValueError) and not isinstance(
                    error, ProviderError
                ):
                    error = ProviderInvalidConfigurationError(
                        str(error), operation="workspace_spec"
                    )
                self._handle_failure(workspace_id, operation, error)
                if not error.retryable:
                    raise
                if self._phase_attempts.get(operation.phase, 0) >= MAX_ATTEMPTS:
                    raise
            self._backoff(operation.phase)

    def _claim_or_wait(
        self,
        workspace_id: UUID,
        kind: str,
        *,
        expected_source_generation: int | None,
        proof_precondition: ReplacementProofPrecondition | None = None,
    ) -> _Claim | WorkspaceBinding | None:
        now = self.clock()

        @transaction.atomic
        def transaction_once():
            workspace = (
                Workspace.objects.select_for_update().filter(pk=workspace_id).first()
            )
            if workspace is None:
                raise RuntimeValidationError("workspace does not exist")

            phase = workspace.provisioning_phase
            if phase == WorkspaceProvisioningPhase.FAILED:
                raise ProviderTerminalError(
                    "workspace provisioning is terminally failed",
                    operation="workspace_lifecycle",
                )
            if phase == WorkspaceProvisioningPhase.IDLE:
                if kind == WorkspaceProvisioningKind.ENSURE:
                    if workspace.machine_generation > 0:
                        return WorkspaceBinding.from_workspace(workspace)
                    operation_id = uuid.uuid4()
                    target = 1
                    previous = None
                    machine_name = None
                    next_phase = WorkspaceProvisioningPhase.APP_READY
                    workspace.machine_generation = target
                else:
                    source = workspace.machine_generation
                    if source != expected_source_generation:
                        if source > expected_source_generation and (
                            workspace.provisioning_kind
                            == WorkspaceProvisioningKind.REPLACE
                            and workspace.provisioning_source_generation
                            == expected_source_generation
                        ):
                            return WorkspaceBinding.from_workspace(workspace)
                        raise WorkspaceStaleOperationError(
                            "replacement source generation is stale"
                        )
                    if proof_precondition is not None:
                        proof_precondition.assert_satisfied(workspace)
                    operation_id = uuid.uuid4()
                    target = source + 1
                    previous = workspace.machine_ref
                    machine_name = deterministic_resource_names(workspace_id).machine(
                        target
                    )
                    next_phase = WorkspaceProvisioningPhase.OLD_MACHINE_STOPPED
                    # Fence before any provider call.  This is intentionally
                    # part of the claim transaction.
                    workspace.machine_generation = target
                    workspace.machine_ref = None

                workspace.provisioning_id = operation_id
                workspace.provisioning_kind = kind
                workspace.provisioning_phase = next_phase
                workspace.provisioning_source_generation = (
                    expected_source_generation
                    if kind == WorkspaceProvisioningKind.REPLACE
                    else None
                )
                workspace.provisioning_target_generation = target
                workspace.provisioning_previous_machine_ref = previous
                workspace.provisioning_machine_name = machine_name
                workspace.provisioning_claim_token = None
                workspace.provisioning_claim_expires_at = None
                # A new Machine generation must reconcile every active profile
                # before claims resume.  Clear only generation-scoped receipt
                # state; identity, seed, and cleanup tombstones remain durable.
                RuntimeProfile.objects.filter(
                    workspace_id=workspace.id,
                    lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
                ).update(
                    materialized_generation=0,
                    materialization_operation_id=None,
                    materialization_request_digest="",
                    materialization_receipt_id=None,
                    materialization_result_code="",
                    updated_at=now,
                )
                workspace.save(
                    update_fields=[
                        "machine_generation",
                        "machine_ref",
                        "provisioning_id",
                        "provisioning_kind",
                        "provisioning_phase",
                        "provisioning_source_generation",
                        "provisioning_target_generation",
                        "provisioning_previous_machine_ref",
                        "provisioning_machine_name",
                        "provisioning_claim_token",
                        "provisioning_claim_expires_at",
                        "updated_at",
                    ]
                )
                phase = next_phase

            if workspace.provisioning_kind != kind:
                return None
            if (
                kind == WorkspaceProvisioningKind.REPLACE
                and workspace.provisioning_source_generation
                != expected_source_generation
            ):
                raise WorkspaceStaleOperationError(
                    "replacement source generation is stale"
                )

            if (
                workspace.provisioning_claim_token
                and workspace.provisioning_claim_expires_at
                and workspace.provisioning_claim_expires_at > now
            ):
                return None

            token = uuid.uuid4().hex
            workspace.provisioning_claim_token = token
            workspace.provisioning_claim_expires_at = now + timedelta(
                seconds=CLAIM_SECONDS
            )
            workspace.save(
                update_fields=[
                    "provisioning_claim_token",
                    "provisioning_claim_expires_at",
                    "updated_at",
                ]
            )
            return _Claim(
                workspace.provisioning_id,
                token,
                workspace.provisioning_phase,
                workspace.provisioning_target_generation
                or workspace.machine_generation,
                workspace.provisioning_previous_machine_ref,
            )

        return run_with_sqlite_lock_retry(transaction_once)

    def _run_ensure_phase(
        self,
        workspace_id: UUID,
        spec: WorkspaceSpec,
        claim: _Claim,
        deadline: float,
        before_bind: Callable[[UUID, WorkspaceSpec, _Claim, float], None] | None = None,
    ) -> WorkspaceBinding | None:
        workspace = Workspace.objects.get(pk=workspace_id)
        app_spec = spec.app_spec(workspace_id)
        if claim.phase == WorkspaceProvisioningPhase.APP_READY:
            app = self._ensure_app(app_spec)
            self._cas_phase(
                workspace_id,
                claim,
                phase=WorkspaceProvisioningPhase.VOLUME_READY,
                updates={"fly_app_ref": app.id},
            )
            return None
        if claim.phase == WorkspaceProvisioningPhase.VOLUME_READY:
            volume = self._ensure_volume(spec.volume_spec(workspace_id))
            self._cas_phase(
                workspace_id,
                claim,
                phase=WorkspaceProvisioningPhase.MACHINE_CREATED,
                updates={"fly_app_ref": app_spec.name, "volume_ref": volume.id},
            )
            return None
        if claim.phase == WorkspaceProvisioningPhase.MACHINE_CREATED:
            volume_id = workspace.volume_ref
            if not volume_id:
                raise ProviderTerminalError("workspace Volume is missing")
            machine_spec = spec.machine_spec(
                workspace_id, volume_id, claim.target_generation, claim.operation_id
            )
            machine = self._ensure_machine(workspace_id, machine_spec, volume_id)
            self._cas_phase(
                workspace_id,
                claim,
                phase=WorkspaceProvisioningPhase.MACHINE_STARTED,
                updates={"machine_ref": machine.id},
            )
            return None
        if claim.phase == WorkspaceProvisioningPhase.MACHINE_STARTED:
            if not workspace.machine_ref:
                raise ProviderTerminalError("workspace Machine binding is incomplete")
            self._start_machine_if_needed(
                app_spec.name, workspace.machine_ref, deadline
            )
            self._cas_phase(
                workspace_id,
                claim,
                phase=WorkspaceProvisioningPhase.HEALTHY,
                updates={},
            )
            return None
        if claim.phase == WorkspaceProvisioningPhase.HEALTHY:
            if not workspace.machine_ref or not workspace.volume_ref:
                raise ProviderTerminalError("workspace binding is incomplete")
            self._wait_healthy(app_spec.name, workspace.machine_ref, spec, deadline)
            if before_bind is not None:
                # The callback is the final activation gate. It runs after
                # provider liveness but before the durable idle binding, so a
                # failed authenticated bootstrap cannot leave a usable-looking
                # Workspace row behind.
                before_bind(workspace_id, spec, claim, deadline)
            return self._bind_idle(workspace_id, claim, workspace.machine_ref)
        raise ProviderTerminalError(f"unsupported ensure phase: {claim.phase}")

    def _run_replace_phase(
        self,
        workspace_id: UUID,
        spec: WorkspaceSpec,
        claim: _Claim,
        deadline: float,
    ) -> WorkspaceBinding | None:
        workspace = Workspace.objects.get(pk=workspace_id)
        if not workspace.volume_ref:
            raise ProviderTerminalError("workspace provider binding is incomplete")
        app_name = deterministic_resource_names(workspace_id).app
        volume_id = workspace.volume_ref
        previous = claim.previous_machine_ref

        if claim.phase == WorkspaceProvisioningPhase.OLD_MACHINE_STOPPED:
            if previous:
                existing = self._inspect_machine_by_id(app_name, previous)
                if existing is not None:
                    self._verify_previous_machine(
                        existing,
                        workspace_id,
                        volume_id,
                        claim,
                    )
                if existing is not None and existing.state not in (
                    MachineState.STOPPED,
                    MachineState.DESTROYED,
                ):
                    try:
                        self.provider.stop_machine(app_name, previous)
                    except ProviderNotFoundError:
                        # A stop can succeed before its response is lost.  A
                        # 404 for the recorded Machine is therefore an
                        # idempotent success, not a terminal replacement
                        # failure.
                        existing = None
                    self._wait_machine_stopped(
                        app_name,
                        previous,
                        workspace_id,
                        volume_id,
                        claim,
                        deadline,
                    )
            # The provider has now authoritatively reported STOPPED or 404.
            # Retire old-generation leases before destroying/replacing the
            # Machine; this callback is intentionally after the wait and also
            # runs for an already-absent recorded Machine.
            if claim.target_generation > 1:
                callback = self.fence_callback
                if callback is None:
                    from .leases import confirm_machine_stopped_and_fence

                    callback = confirm_machine_stopped_and_fence
                callback(
                    workspace_id,
                    claim.target_generation - 1,
                    claim.target_generation,
                    previous,
                )
            self._cas_phase(
                workspace_id,
                claim,
                phase=WorkspaceProvisioningPhase.OLD_MACHINE_DESTROYED,
                updates={},
            )
            return None
        if claim.phase == WorkspaceProvisioningPhase.OLD_MACHINE_DESTROYED:
            if previous:
                existing = self._inspect_machine_by_id(app_name, previous)
                if existing is not None:
                    self._verify_previous_machine(
                        existing,
                        workspace_id,
                        volume_id,
                        claim,
                    )
                    try:
                        self.provider.destroy_machine(app_name, previous)
                    except ProviderNotFoundError:
                        # The recorded Machine is already gone; continue to
                        # the authoritative Volume-detachment reconciliation.
                        pass
            volume = self._volume_by_id(app_name, volume_id, spec)
            if volume.attached_machine_id:
                if volume.attached_machine_id != previous:
                    raise ProviderAttachmentConflictError(
                        volume_id=volume.id,
                        attached_machine_id=volume.attached_machine_id,
                    )
                raise ProviderRetryableError(
                    "workspace Volume is still attached to the previous Machine",
                    operation="wait_volume_detach",
                )
            self._cas_phase(
                workspace_id,
                claim,
                phase=WorkspaceProvisioningPhase.MACHINE_CREATED,
                updates={},
            )
            return None
        if claim.phase == WorkspaceProvisioningPhase.MACHINE_CREATED:
            machine_spec = spec.machine_spec(
                workspace_id, volume_id, claim.target_generation, claim.operation_id
            )
            machine = self._ensure_machine(workspace_id, machine_spec, volume_id)
            self._cas_phase(
                workspace_id,
                claim,
                phase=WorkspaceProvisioningPhase.MACHINE_STARTED,
                updates={"machine_ref": machine.id},
            )
            return None
        if claim.phase == WorkspaceProvisioningPhase.MACHINE_STARTED:
            if not workspace.machine_ref:
                raise ProviderTerminalError("replacement Machine is missing")
            self._start_machine_if_needed(app_name, workspace.machine_ref, deadline)
            self._cas_phase(
                workspace_id,
                claim,
                phase=WorkspaceProvisioningPhase.HEALTHY,
                updates={},
            )
            return None
        if claim.phase == WorkspaceProvisioningPhase.HEALTHY:
            if not workspace.machine_ref:
                raise ProviderTerminalError("replacement Machine is missing")
            self._wait_healthy(app_name, workspace.machine_ref, spec, deadline)
            return self._bind_idle(workspace_id, claim, workspace.machine_ref)
        raise ProviderTerminalError(f"unsupported replace phase: {claim.phase}")

    def _ensure_app(self, spec: AppSpec) -> AppRecord:
        ensure = getattr(self.provider, "ensure_app", None)
        if ensure:
            return ensure(spec)
        existing = self.provider.inspect_app(spec.name)
        return existing or self.provider.create_app(spec)

    def _ensure_volume(self, spec: VolumeSpec) -> VolumeRecord:
        ensure = getattr(self.provider, "ensure_volume", None)
        if ensure:
            return ensure(spec)
        volumes = tuple(self.provider.list_volumes(spec.app_name))
        if len(volumes) > 1:
            raise ProviderTerminalError("multiple workspace Volumes found")
        return volumes[0] if volumes else self.provider.create_volume(spec)

    def _ensure_machine(
        self, workspace_id: UUID, spec: MachineSpec, volume_id: str
    ) -> MachineRecord:
        volume = self._volume_by_id(spec.app_name, volume_id, None)
        if volume.attached_machine_id and volume.attached_machine_id != spec.name:
            # The provider reports IDs here, while ``spec.name`` is the
            # deterministic identity.  An existing owned Machine is allowed.
            existing = self._inspect_machine_by_id(
                spec.app_name, volume.attached_machine_id
            )
            if existing is None or existing.name != spec.name:
                raise ProviderAttachmentConflictError(
                    volume_id=volume.id,
                    attached_machine_id=volume.attached_machine_id,
                )
        ensure = getattr(self.provider, "ensure_machine", None)
        if ensure:
            return ensure(spec)
        existing = self.provider.inspect_machine(spec.app_name, spec.name)
        return existing or self.provider.create_machine(spec)

    def _volume_by_id(
        self, app_name: str, volume_id: str, spec: WorkspaceSpec | None
    ) -> VolumeRecord:
        volumes = tuple(self.provider.list_volumes(app_name))
        matches = [volume for volume in volumes if volume.id == volume_id]
        if len(matches) != 1:
            if not matches:
                raise ProviderNotFoundError("workspace Volume was not found")
            raise ProviderTerminalError("workspace Volume identity is ambiguous")
        return matches[0]

    def _inspect_machine_by_id(
        self, app_name: str, machine_id: str
    ) -> MachineRecord | None:
        inspect = getattr(self.provider, "inspect_machine_by_id", None)
        try:
            if inspect:
                return inspect(app_name, machine_id)
            # Protocol implementations may only support deterministic-name
            # lookup; use the recorded ID as a safe best-effort fallback.
            return self.provider.inspect_machine(app_name, machine_id)
        except ProviderNotFoundError:
            # A provider 404 is the authoritative absence signal for a
            # recorded Machine and is safe to reconcile as already gone.
            return None

    def _start_machine_if_needed(
        self, app_name: str, machine_id: str, deadline: float
    ) -> None:
        machine = self._inspect_machine_by_id(app_name, machine_id)
        if machine is None:
            raise ProviderNotFoundError("workspace Machine was not found")
        if machine.state is MachineState.STARTED:
            return
        if machine.state is MachineState.DESTROYED:
            raise ProviderNotFoundError("workspace Machine was destroyed")
        if machine.state not in (MachineState.CREATED, MachineState.STOPPED):
            machine = self._wait_machine_ready_to_start(app_name, machine_id, deadline)
            if machine.state is MachineState.STARTED:
                return
        while True:
            try:
                self.provider.start_machine(app_name, machine_id)
                break
            except ProviderRetryableError:
                if time.monotonic() >= deadline:
                    raise
                self.sleep(STOP_POLL_SECONDS)
        self._wait_machine_started(app_name, machine_id, deadline)

    def _wait_machine_ready_to_start(
        self, app_name: str, machine_id: str, deadline: float
    ) -> MachineRecord:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                machine = self.provider.wait_machine(
                    app_name,
                    machine_id,
                    timeout_seconds=min(REQUEST_TIMEOUT_SECONDS, remaining),
                    state="stopped",
                )
            except ProviderTimeoutError:
                continue
            if machine.state in (MachineState.STOPPED, MachineState.STARTED):
                return machine
            if machine.state is MachineState.DESTROYED:
                raise ProviderNotFoundError("workspace Machine was destroyed")
        raise ProviderRetryableError(
            "workspace Machine was not ready to start before deadline",
            operation="wait_machine_stopped",
        )

    def _wait_machine_started(
        self, app_name: str, machine_id: str, deadline: float
    ) -> None:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                machine = self.provider.wait_machine(
                    app_name,
                    machine_id,
                    timeout_seconds=min(REQUEST_TIMEOUT_SECONDS, remaining),
                )
            except ProviderTimeoutError:
                continue
            if machine.state is MachineState.STARTED:
                return
            self.sleep(
                min(HEALTH_POLL_SECONDS, max(0.0, deadline - time.monotonic()))
            )
        raise ProviderRetryableError(
            "workspace Machine did not start before deadline",
            operation="wait_machine_start",
        )

    def _wait_healthy(
        self,
        app_name: str,
        machine_id: str,
        spec: WorkspaceSpec,
        deadline: float,
    ) -> MachineRecord:
        while time.monotonic() < deadline:
            try:
                machine = self.provider.wait_machine(
                    app_name,
                    machine_id,
                    timeout_seconds=min(
                        REQUEST_TIMEOUT_SECONDS, max(1, deadline - time.monotonic())
                    ),
                )
            except ProviderTimeoutError:
                self.sleep(
                    min(
                        HEALTH_POLL_SECONDS,
                        max(0.0, deadline - time.monotonic()),
                    )
                )
                continue
            if machine.state is MachineState.STARTED:
                health = machine.health
                if health is None or not _healthy_containers(health, spec):
                    inspect = getattr(self.provider, "inspect_machine_by_id", None)
                    if inspect:
                        inspected = inspect(app_name, machine_id)
                        health = inspected.health if inspected else None
                if health is not None and _healthy_containers(health, spec):
                    return machine
            self.sleep(
                min(HEALTH_POLL_SECONDS, max(0.0, deadline - time.monotonic()))
            )
        raise ProviderRetryableError(
            "workspace Machine did not become healthy before deadline",
            operation="wait_machine",
        )

    def _wait_machine_stopped(
        self,
        app_name: str,
        machine_id: str,
        workspace_id: UUID,
        volume_id: str,
        claim: _Claim,
        deadline: float,
    ) -> None:
        """Wait for the provider's authoritative stopped state after an ack."""

        while time.monotonic() < deadline:
            machine = self._inspect_machine_by_id(app_name, machine_id)
            if machine is None or machine.state in (
                MachineState.STOPPED,
                MachineState.DESTROYED,
            ):
                return
            self._verify_previous_machine(machine, workspace_id, volume_id, claim)
            self.sleep(min(STOP_POLL_SECONDS, max(0.0, deadline - time.monotonic())))
        raise ProviderRetryableError(
            "previous workspace Machine did not stop before deadline",
            operation="wait_machine_stop",
        )

    def _verify_existing_machine(
        self, binding: WorkspaceBinding, workspace_id: UUID
    ) -> None:
        app_name = deterministic_resource_names(workspace_id).app
        machine = self._inspect_machine_by_id(app_name, binding.machine_ref)
        if machine is None or machine.state is MachineState.DESTROYED:
            raise WorkspaceReplacementRequiredError(
                "workspace binding points to a missing Machine"
            )

    def _verify_previous_machine(
        self,
        machine: MachineRecord,
        workspace_id: UUID,
        volume_id: str,
        claim: _Claim,
    ) -> None:
        expected_name = deterministic_resource_names(workspace_id).machine(
            claim.target_generation - 1
        )
        ownership = machine.ownership
        if (
            machine.name != expected_name
            or machine.volume_id != volume_id
            or ownership is None
            or str(ownership.workspace_id) != str(workspace_id)
            or ownership.generation != claim.target_generation - 1
        ):
            raise ProviderOwnershipError(
                "recorded previous Machine is not an owned workspace resource",
                operation="replace_machine",
                details={"resource_type": "machine", "resource_id": machine.id},
            )

    def _cas_phase(
        self,
        workspace_id: UUID,
        claim: _Claim,
        *,
        phase: str,
        updates: dict[str, Any],
    ) -> None:
        @transaction.atomic
        def transaction_once():
            workspace = Workspace.objects.select_for_update().get(pk=workspace_id)
            if (
                workspace.provisioning_id != claim.operation_id
                or workspace.provisioning_claim_token != claim.token
            ):
                raise RuntimeConflictError("workspace provisioning claim is stale")
            for key, value in updates.items():
                setattr(workspace, key, value)
            workspace.provisioning_phase = phase
            workspace.provisioning_claim_token = None
            workspace.provisioning_claim_expires_at = None
            workspace.save(
                update_fields=[
                    *updates.keys(),
                    "provisioning_phase",
                    "provisioning_claim_token",
                    "provisioning_claim_expires_at",
                    "updated_at",
                ]
            )

        run_with_sqlite_lock_retry(transaction_once)

    def _bind_idle(
        self, workspace_id: UUID, claim: _Claim, machine_ref: str
    ) -> WorkspaceBinding:
        @transaction.atomic
        def transaction_once():
            workspace = Workspace.objects.select_for_update().get(pk=workspace_id)
            if (
                workspace.provisioning_id != claim.operation_id
                or workspace.provisioning_claim_token != claim.token
            ):
                raise RuntimeConflictError("workspace provisioning claim is stale")
            workspace.machine_ref = machine_ref
            workspace.provisioning_phase = WorkspaceProvisioningPhase.IDLE
            workspace.provisioning_claim_token = None
            workspace.provisioning_claim_expires_at = None
            # Keep the operation ID and source/target generation for exact
            # replacement replay; claim ownership is no longer active.
            workspace.save(
                update_fields=[
                    "machine_ref",
                    "provisioning_phase",
                    "provisioning_claim_token",
                    "provisioning_claim_expires_at",
                    "updated_at",
                ]
            )
            return WorkspaceBinding.from_workspace(workspace)

        return run_with_sqlite_lock_retry(transaction_once)

    def _handle_failure(
        self, workspace_id: UUID, claim: _Claim, error: ProviderError
    ) -> None:
        will_retry = (
            error.retryable
            and self._phase_attempts.get(claim.phase, 0) < MAX_ATTEMPTS
        )
        if error.retryable:
            if will_retry:
                self._retry_reasons[claim.phase] = (
                    claim.operation_id,
                    getattr(error, "code", None),
                )
            self._clear_claim(workspace_id, claim)
            return

        @transaction.atomic
        def transaction_once():
            workspace = Workspace.objects.select_for_update().get(pk=workspace_id)
            if (
                workspace.provisioning_id == claim.operation_id
                and workspace.provisioning_claim_token == claim.token
            ):
                workspace.provisioning_phase = WorkspaceProvisioningPhase.FAILED
                workspace.provisioning_claim_token = None
                workspace.provisioning_claim_expires_at = None
                workspace.save(
                    update_fields=[
                        "provisioning_phase",
                        "provisioning_claim_token",
                        "provisioning_claim_expires_at",
                        "updated_at",
                    ]
                )

        run_with_sqlite_lock_retry(transaction_once)

    def _emit_retry_if_pending(
        self, workspace_id: UUID, claim: _Claim, *, operation_name: str
    ) -> None:
        """Record a retry only after a new claim has actually been acquired."""

        pending = self._retry_reasons.pop(claim.phase, None)
        if pending is None or pending[0] != claim.operation_id:
            return
        _, reason_code = pending
        emit_event(
            build_event(
                "runtime.operation.retried",
                operation=operation_name,
                workspace_id=str(workspace_id),
                reason_code=reason_code,
                outcome="retry",
            )
        )

    def _clear_claim(self, workspace_id: UUID, claim: _Claim) -> None:
        @transaction.atomic
        def transaction_once():
            workspace = Workspace.objects.select_for_update().get(pk=workspace_id)
            if (
                workspace.provisioning_id == claim.operation_id
                and workspace.provisioning_claim_token == claim.token
            ):
                workspace.provisioning_claim_token = None
                workspace.provisioning_claim_expires_at = None
                workspace.save(
                    update_fields=[
                        "provisioning_claim_token",
                        "provisioning_claim_expires_at",
                        "updated_at",
                    ]
                )

        run_with_sqlite_lock_retry(transaction_once)

    def _wait_for_other_operation(self, deadline: float) -> None:
        if time.monotonic() >= deadline:
            raise ProviderRetryableError(
                "workspace operation did not finish before deadline"
            )
        self.sleep(0.01)

    def _deadline(self) -> float:
        return time.monotonic() + self.phase_deadline_seconds

    def _backoff(self, phase: str) -> None:
        index = min(MAX_ATTEMPTS - 1, self._phase_attempts.get(phase, 1) - 1)
        delay = BACKOFF_SECONDS[min(index, len(BACKOFF_SECONDS) - 1)]
        if self.jitter:
            delay += random.random() * delay * 0.25
        self.sleep(delay)

    def _begin_attempt(self, phase: str) -> None:
        self._phase_attempts[phase] = self._phase_attempts.get(phase, 0) + 1


_configured_provider: WorkspaceProvider | None = None


def configure_workspace_provider(provider: WorkspaceProvider) -> None:
    """Install the process-local provider used by the small module API."""

    global _configured_provider
    _configured_provider = provider


def _service() -> WorkspaceLifecycle:
    if _configured_provider is None:
        from runtime.providers import FlyProvider

        return WorkspaceLifecycle(FlyProvider())
    return WorkspaceLifecycle(_configured_provider)


def ensure_workspace(workspace_id: UUID | str, spec: WorkspaceSpec) -> WorkspaceBinding:
    return _service().ensure_workspace(workspace_id, spec)


def replace_machine(
    workspace_id: UUID | str,
    spec: WorkspaceSpec,
    expected_source_generation: int,
    proof_precondition: ReplacementProofPrecondition | None = None,
) -> WorkspaceBinding:
    return _service().replace_machine(
        workspace_id,
        spec,
        expected_source_generation,
        proof_precondition,
    )


def _uuid(value: UUID | str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError("workspace_id must be a UUID") from exc


def _healthy_containers(health: MachineHealth, spec: WorkspaceSpec) -> bool:
    required = (
        {container.name for container in spec.containers}
        if spec.containers
        else REQUIRED_CONTAINERS
    )
    return (
        health.state is MachineState.STARTED
        and required.issubset(health.containers)
        and all(health.containers[name] is ContainerState.STARTED for name in required)
    )


def _default_process_healthcheck(name: str) -> dict[str, object]:
    """Provide a minimal liveness gate until FND-004 supplies service checks."""

    return {
        "name": name,
        "exec": {"command": ["/bin/sh", "-c", "test -r /proc/1/stat"]},
        "interval": 5,
        "timeout": 2,
        "grace_period": 5,
    }


__all__ = [
    "WorkspaceBinding",
    "WorkspaceLifecycle",
    "WorkspaceReplacementRequiredError",
    "WorkspaceSpec",
    "WorkspaceStaleOperationError",
    "configure_workspace_provider",
    "ensure_workspace",
    "replace_machine",
]
