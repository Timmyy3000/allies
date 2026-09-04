from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import transaction
from django.test import override_settings
from django.utils import timezone

from runtime.exceptions import RuntimeFencedError, RuntimeNotReadyError
from runtime.models import (
    Execution,
    ExecutionStatus,
    RuntimeIntentOutcome,
    RuntimeOperationState,
    RuntimeOperationTrigger,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.providers import (
    MachineRecord,
    MachineState,
    OwnershipMetadata,
    ProviderCapacityError,
    ProviderOwnershipError,
    ProviderTimeoutError,
)
from runtime.services import runtime_power
from runtime.services.claims import claim_next_execution
from runtime.services.executions import create_execution
from runtime.services.runtime_auth import (
    authenticate_runtime_token,
    issue_runtime_credential,
)
from runtime.services.runtime_intents import (
    request_execution_wake_locked,
    request_runtime_intent,
)
from runtime.services.runtime_power import (
    _requested_workspace_ids,
    process_runtime_wakes,
    stop_idle_workspaces,
)
from runtime.services.runtime_provider import runtime_power_provider
from runtime.services.runtime_readiness import accept_runtime_readiness


class FakePowerProvider:
    def __init__(
        self, workspace: Workspace, *, state: MachineState = MachineState.STOPPED
    ):
        self.workspace = workspace
        self.machine = MachineRecord(
            id=workspace.machine_ref or "machine-1",
            name="machine-1",
            app_name=workspace.fly_app_ref or "app",
            region="ams",
            state=state,
            volume_id=workspace.volume_ref,
            ownership=OwnershipMetadata(
                workspace.id,
                workspace.provisioning_id or uuid4(),
                workspace.machine_generation,
            ),
        )
        self.inspect_calls = 0
        self.start_calls = 0
        self.stop_calls = 0
        self.timeout_after_start = False
        self.start_error = None

    def inspect_machine_by_id(self, app_name: str, machine_id: str):
        self.inspect_calls += 1
        if app_name != self.machine.app_name or machine_id != self.machine.id:
            return None
        return self.machine

    def start_machine(self, app_name: str, machine_id: str):
        self.start_calls += 1
        if self.start_error is not None:
            raise self.start_error
        self.machine = MachineRecord(
            id=self.machine.id,
            name=self.machine.name,
            app_name=self.machine.app_name,
            region=self.machine.region,
            state=MachineState.STARTED,
            volume_id=self.machine.volume_id,
            ownership=self.machine.ownership,
        )
        if self.timeout_after_start:
            raise ProviderTimeoutError("start response was lost")
        return self.machine

    def stop_machine(self, app_name: str, machine_id: str):
        self.stop_calls += 1
        self.machine = MachineRecord(
            id=self.machine.id,
            name=self.machine.name,
            app_name=self.machine.app_name,
            region=self.machine.region,
            state=MachineState.STOPPED,
            volume_id=self.machine.volume_id,
            ownership=self.machine.ownership,
        )
        return self.machine


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(
        tenant_ref=f"fnd009-{uuid4()}",
        fly_app_ref="app",
        volume_ref="volume",
        machine_ref="machine-1",
        machine_generation=1,
        provisioning_id=uuid4(),
        provisioning_phase=WorkspaceProvisioningPhase.IDLE,
    )


def test_intent_is_durable_and_wakes_only_the_recorded_machine(workspace):
    now = timezone.now()
    provider = FakePowerProvider(workspace)
    receipt = request_runtime_intent(
        workspace.id,
        "composing_started",
        uuid4(),
        now,
        now=now,
    )

    assert receipt.status == RuntimeIntentOutcome.WAKING
    assert provider.start_calls == 0
    report = process_runtime_wakes(provider=provider, now=now)

    assert report.started == 1
    assert report.awaiting_readiness == 1
    assert provider.start_calls == 1
    workspace.refresh_from_db()
    assert workspace.runtime_operation_state == RuntimeOperationState.AWAITING_READINESS
    assert workspace.runtime_start_epoch == 1


def test_workspace_limit_applies_while_intents_coalesce(workspace):
    now = timezone.now()

    receipts = [
        request_runtime_intent(
            workspace.id,
            "composing_started",
            uuid4(),
            now,
            now=now,
        )
        for _ in range(31)
    ]

    assert all(receipt.status == RuntimeIntentOutcome.WAKING for receipt in receipts[:30])
    assert receipts[30].status == RuntimeIntentOutcome.RATE_LIMITED
    assert len({receipt.operation_id for receipt in receipts[:30]}) == 1


@override_settings(
    ALLIES_RUNTIME_INTENT_TTL_SECONDS=120,
    ALLIES_RUNTIME_INTENT_RETENTION_SECONDS=600,
)
def test_future_intent_fails_without_extending_quota_or_retention(workspace):
    now = timezone.now()
    receipt = request_runtime_intent(
        workspace.id,
        "composing_started",
        uuid4(),
        now + timedelta(minutes=10),
        now=now,
    )

    intent = workspace.runtime_intents.get()
    assert receipt.status == RuntimeIntentOutcome.FAILED
    assert intent.received_at == now
    assert intent.expires_at == now + timedelta(seconds=120)
    assert intent.delete_after == now + timedelta(seconds=600)


@override_settings(ALLIES_RUNTIME_KEEP_WARM_SECONDS=600)
def test_ready_intent_persists_keep_warm_extension(workspace):
    now = timezone.now()
    workspace.ready_generation = workspace.machine_generation
    workspace.ready_start_epoch = workspace.runtime_start_epoch
    workspace.ready_boot_id = uuid4()
    workspace.ready_at = now
    workspace.runtime_last_seen_at = now
    workspace.speculative_keep_warm_until = now - timedelta(seconds=1)
    workspace.save(
        update_fields=[
            "ready_generation",
            "ready_start_epoch",
            "ready_boot_id",
            "ready_at",
            "runtime_last_seen_at",
            "speculative_keep_warm_until",
            "updated_at",
        ]
    )

    receipt = request_runtime_intent(
        workspace.id, "composing_started", uuid4(), now, now=now
    )

    workspace.refresh_from_db()
    assert receipt.status == RuntimeIntentOutcome.ALREADY_READY
    assert workspace.speculative_keep_warm_until == now + timedelta(minutes=10)


@override_settings(ALLIES_RUNTIME_KEEP_WARM_SECONDS=600)
def test_coalesced_waking_intent_persists_keep_warm_extension(workspace):
    now = timezone.now()
    operation_id = uuid4()
    workspace.runtime_operation_id = operation_id
    workspace.runtime_operation_state = RuntimeOperationState.REQUESTED
    workspace.runtime_operation_trigger = RuntimeOperationTrigger.SPECULATIVE
    workspace.runtime_operation_requested_at = now
    workspace.speculative_keep_warm_until = now - timedelta(seconds=1)
    workspace.save(
        update_fields=[
            "runtime_operation_id",
            "runtime_operation_state",
            "runtime_operation_trigger",
            "runtime_operation_requested_at",
            "speculative_keep_warm_until",
            "updated_at",
        ]
    )

    receipt = request_runtime_intent(
        workspace.id, "composing_started", uuid4(), now, now=now
    )

    workspace.refresh_from_db()
    assert receipt.status == RuntimeIntentOutcome.WAKING
    assert receipt.operation_id == operation_id
    assert workspace.speculative_keep_warm_until == now + timedelta(minutes=10)


def test_failed_provisioning_without_binding_requires_first_provision(db):
    now = timezone.now()
    workspace = Workspace.objects.create(
        tenant_ref=f"fnd009-failed-{uuid4()}",
        provisioning_phase=WorkspaceProvisioningPhase.FAILED,
    )

    receipt = request_runtime_intent(
        workspace.id,
        "composing_started",
        uuid4(),
        now,
        now=now,
    )

    assert receipt.status == RuntimeIntentOutcome.FIRST_PROVISION_REQUIRED
    workspace.refresh_from_db()
    assert workspace.runtime_operation_state == RuntimeOperationState.IDLE
    assert workspace.runtime_operation_id is None


def test_failed_provisioning_with_retained_binding_can_wake(workspace):
    now = timezone.now()
    workspace.provisioning_phase = WorkspaceProvisioningPhase.FAILED
    workspace.save(update_fields=["provisioning_phase", "updated_at"])
    provider = FakePowerProvider(workspace)

    receipt = request_runtime_intent(
        workspace.id,
        "composing_started",
        uuid4(),
        now,
        now=now,
    )
    report = process_runtime_wakes(provider=provider, now=now)

    assert receipt.status == RuntimeIntentOutcome.WAKING
    assert report.started == 1
    assert provider.start_calls == 1


def test_failed_provisioning_with_retained_binding_can_claim_after_wake(workspace):
    issued = issue_runtime_credential(workspace.id, "runtime-secret")
    workspace.provisioning_phase = WorkspaceProvisioningPhase.FAILED
    workspace.save(update_fields=["provisioning_phase", "updated_at"])
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="retained-ally",
        hermes_profile_key="retained-ally",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=workspace.machine_generation,
    )
    execution = create_execution(
        workspace.id,
        profile.id,
        "retained-turn",
        {"message": "hello", "cloud_conversation_ref": "retained-cloud"},
    )
    now = timezone.now()
    provider = FakePowerProvider(workspace)

    wake = process_runtime_wakes(provider=provider, now=now)
    context = authenticate_runtime_token(issued.raw_token)
    workspace.refresh_from_db()
    accept_runtime_readiness(
        context,
        uuid4(),
        workspace.machine_generation,
        workspace.runtime_start_epoch,
        now=now,
    )
    claim = claim_next_execution(context, uuid4(), 1)

    assert wake.started == 1
    assert claim is not None
    assert claim.execution_id == execution.id


@pytest.mark.parametrize("state", [MachineState.CREATED, MachineState.UNKNOWN])
def test_execution_wake_retries_transitional_machine_state(workspace, state):
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref=f"transitional-{state}",
        hermes_profile_key=f"transitional-{state}",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=workspace.machine_generation,
    )
    create_execution(
        workspace.id,
        profile.id,
        f"transitional-{state}",
        {"message": "hello", "cloud_conversation_ref": f"state-{state}"},
    )
    provider = FakePowerProvider(workspace, state=state)
    now = timezone.now()

    report = process_runtime_wakes(provider=provider, now=now)

    workspace.refresh_from_db()
    assert report.failed == 1
    assert workspace.runtime_operation_state == RuntimeOperationState.REQUESTED
    assert workspace.runtime_operation_retry_count == 1
    assert workspace.runtime_operation_requested_at == now + timedelta(seconds=5)


@pytest.mark.parametrize("state", [MachineState.CREATED, MachineState.UNKNOWN])
def test_expired_execution_wake_retries_transitional_machine_state(
    workspace, state
):
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref=f"recovered-{state}",
        hermes_profile_key=f"recovered-{state}",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=workspace.machine_generation,
    )
    create_execution(
        workspace.id,
        profile.id,
        f"recovered-{state}",
        {"message": "hello", "cloud_conversation_ref": f"recovered-{state}"},
    )
    now = timezone.now()
    workspace.refresh_from_db()
    workspace.runtime_operation_state = RuntimeOperationState.STARTING
    workspace.activation_claim_token = "expired-claim"
    workspace.activation_claim_expires_at = now
    workspace.save(
        update_fields=[
            "runtime_operation_state",
            "activation_claim_token",
            "activation_claim_expires_at",
            "updated_at",
        ]
    )

    report = process_runtime_wakes(
        provider=FakePowerProvider(workspace, state=state),
        now=now,
    )

    workspace.refresh_from_db()
    assert report.failed == 1
    assert workspace.runtime_operation_state == RuntimeOperationState.REQUESTED
    assert workspace.runtime_operation_retry_count == 1
    assert workspace.runtime_operation_requested_at == now + timedelta(seconds=5)


def test_execution_wake_parks_destroyed_machine(workspace):
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="destroyed-ally",
        hermes_profile_key="destroyed-ally",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=workspace.machine_generation,
    )
    create_execution(
        workspace.id,
        profile.id,
        "destroyed-turn",
        {"message": "hello", "cloud_conversation_ref": "destroyed"},
    )
    provider = FakePowerProvider(workspace, state=MachineState.DESTROYED)

    report = process_runtime_wakes(provider=provider, now=timezone.now())

    workspace.refresh_from_db()
    assert report.failed == 1
    assert workspace.runtime_operation_state == RuntimeOperationState.IDLE


def test_uncertain_start_inspects_before_retry(workspace):
    now = timezone.now()
    provider = FakePowerProvider(workspace)
    provider.timeout_after_start = True
    request_runtime_intent(workspace.id, "composing_started", uuid4(), now, now=now)

    report = process_runtime_wakes(provider=provider, now=now)

    assert report.started == 1
    assert report.failed == 0
    assert provider.start_calls == 1
    assert provider.inspect_calls == 2


def test_expired_speculative_operation_does_not_start_machine(workspace):
    now = timezone.now()
    provider = FakePowerProvider(workspace)
    receipt = request_runtime_intent(
        workspace.id, "composing_started", uuid4(), now, now=now
    )

    process_runtime_wakes(provider=provider, now=now + timedelta(seconds=121))

    assert provider.start_calls == 0
    workspace.refresh_from_db()
    assert workspace.runtime_operation_state == RuntimeOperationState.IDLE
    assert workspace.runtime_intents.get(
        coalesced_operation_id=receipt.operation_id
    ).outcome == RuntimeIntentOutcome.FAILED


@pytest.mark.parametrize("missing", ["volume", "ownership"])
def test_wake_requires_complete_provider_binding_evidence(workspace, missing):
    now = timezone.now()
    provider = FakePowerProvider(workspace)
    provider.machine = MachineRecord(
        id=provider.machine.id,
        name=provider.machine.name,
        app_name=provider.machine.app_name,
        region=provider.machine.region,
        state=provider.machine.state,
        volume_id=None if missing == "volume" else provider.machine.volume_id,
        ownership=None if missing == "ownership" else provider.machine.ownership,
    )
    request_runtime_intent(workspace.id, "composing_started", uuid4(), now, now=now)

    report = process_runtime_wakes(provider=provider, now=now)

    assert report.failed == 1
    assert provider.start_calls == 0


def test_wake_rejects_machine_from_another_provisioning_operation(workspace):
    now = timezone.now()
    provider = FakePowerProvider(workspace)
    provider.machine = MachineRecord(
        id=provider.machine.id,
        name=provider.machine.name,
        app_name=provider.machine.app_name,
        region=provider.machine.region,
        state=provider.machine.state,
        volume_id=provider.machine.volume_id,
        ownership=OwnershipMetadata(
            workspace.id,
            uuid4(),
            workspace.machine_generation,
        ),
    )
    request_runtime_intent(workspace.id, "composing_started", uuid4(), now, now=now)

    report = process_runtime_wakes(provider=provider, now=now)

    assert report.failed == 1
    assert provider.start_calls == 0


def test_retryable_execution_wake_uses_durable_backoff(workspace):
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="retry-ally",
        hermes_profile_key="retry-ally",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=workspace.machine_generation,
    )
    create_execution(
        workspace.id,
        profile.id,
        "retry-turn",
        {"message": "hello", "cloud_conversation_ref": "retry-cloud"},
    )
    provider = FakePowerProvider(workspace)
    provider.start_error = ProviderCapacityError("temporary provider capacity")
    now = timezone.now()

    first = process_runtime_wakes(provider=provider, now=now)
    workspace.refresh_from_db()
    assert first.failed == 1
    assert workspace.runtime_operation_state == RuntimeOperationState.REQUESTED
    assert workspace.runtime_operation_trigger == RuntimeOperationTrigger.EXECUTION

    provider.start_error = None
    assert process_runtime_wakes(
        provider=provider,
        now=now + timedelta(seconds=4),
    ).examined == 0
    second = process_runtime_wakes(
        provider=provider,
        now=now + timedelta(seconds=5),
    )
    assert second.started == 1


def test_terminal_execution_wake_failure_is_parked(workspace):
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="terminal-ally",
        hermes_profile_key="terminal-ally",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=workspace.machine_generation,
    )
    execution = create_execution(
        workspace.id,
        profile.id,
        "terminal-turn",
        {"message": "hello", "cloud_conversation_ref": "terminal-cloud"},
    )
    provider = FakePowerProvider(workspace)
    provider.start_error = ProviderOwnershipError("binding ownership mismatch")
    now = timezone.now()

    report = process_runtime_wakes(provider=provider, now=now)

    workspace.refresh_from_db()
    execution.refresh_from_db()
    assert report.failed == 1
    assert workspace.runtime_operation_state == RuntimeOperationState.IDLE
    assert workspace.runtime_operation_id is None
    assert execution.status == ExecutionStatus.QUEUED
    assert process_runtime_wakes(
        provider=provider,
        now=now + timedelta(minutes=1),
    ).examined == 0


def test_retryable_execution_wake_stops_after_bounded_backoff(workspace):
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="bounded-ally",
        hermes_profile_key="bounded-ally",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=workspace.machine_generation,
    )
    create_execution(
        workspace.id,
        profile.id,
        "bounded-turn",
        {"message": "hello", "cloud_conversation_ref": "bounded-cloud"},
    )
    provider = FakePowerProvider(workspace)
    provider.start_error = ProviderCapacityError("capacity unavailable")
    now = timezone.now()

    expected_delays = (5, 10, 20, 40)
    observed_at = now
    for retry_count, delay in enumerate(expected_delays, start=1):
        report = process_runtime_wakes(provider=provider, now=observed_at)
        workspace.refresh_from_db()
        assert report.failed == 1
        assert workspace.runtime_operation_retry_count == retry_count
        assert workspace.runtime_operation_requested_at == observed_at + timedelta(
            seconds=delay
        )
        observed_at = workspace.runtime_operation_requested_at

    final = process_runtime_wakes(provider=provider, now=observed_at)
    workspace.refresh_from_db()
    assert final.failed == 1
    assert workspace.runtime_operation_state == RuntimeOperationState.IDLE
    assert workspace.runtime_operation_retry_count == 0


@override_settings(ALLIES_RUNTIME_READINESS_TIMEOUT_SECONDS=10)
def test_execution_readiness_timeout_remains_durably_retryable(workspace):
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="timeout-ally",
        hermes_profile_key="timeout-ally",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=workspace.machine_generation,
    )
    now = timezone.now()
    create_execution(
        workspace.id,
        profile.id,
        "timeout-turn",
        {"message": "hello", "cloud_conversation_ref": "timeout-cloud"},
    )
    workspace.refresh_from_db()
    workspace.runtime_operation_state = RuntimeOperationState.AWAITING_READINESS
    workspace.runtime_operation_requested_at = now - timedelta(seconds=10)
    workspace.save(
        update_fields=[
            "runtime_operation_state",
            "runtime_operation_requested_at",
            "updated_at",
        ]
    )

    timed_out = process_runtime_wakes(
        provider=FakePowerProvider(workspace),
        now=now,
    )

    workspace.refresh_from_db()
    assert timed_out.failed == 1
    assert workspace.runtime_operation_state == RuntimeOperationState.REQUESTED
    assert workspace.runtime_operation_requested_at == now + timedelta(seconds=5)


def test_prompt_upgrades_speculative_wake_and_refreshes_deadline(workspace):
    now = timezone.now()
    request_runtime_intent(
        workspace.id,
        "composing_started",
        uuid4(),
        now,
        now=now,
    )

    upgraded_at = now + timedelta(seconds=119)
    with transaction.atomic():
        locked = Workspace.objects.select_for_update().get(pk=workspace.id)
        request_execution_wake_locked(locked, now=upgraded_at)

    workspace.refresh_from_db()
    assert workspace.runtime_operation_trigger == RuntimeOperationTrigger.EXECUTION
    assert workspace.runtime_operation_requested_at == upgraded_at


def test_execution_wake_is_selected_before_older_speculative_work(workspace):
    now = timezone.now()
    workspace.runtime_operation_id = uuid4()
    workspace.runtime_operation_state = RuntimeOperationState.REQUESTED
    workspace.runtime_operation_trigger = RuntimeOperationTrigger.SPECULATIVE
    workspace.runtime_operation_requested_at = now - timedelta(seconds=30)
    workspace.save(
        update_fields=[
            "runtime_operation_id",
            "runtime_operation_state",
            "runtime_operation_trigger",
            "runtime_operation_requested_at",
            "updated_at",
        ]
    )
    execution_workspace = Workspace.objects.create(
        tenant_ref=f"fnd009-execution-priority-{uuid4()}",
        runtime_operation_id=uuid4(),
        runtime_operation_state=RuntimeOperationState.REQUESTED,
        runtime_operation_trigger=RuntimeOperationTrigger.EXECUTION,
        runtime_operation_requested_at=now,
    )

    assert _requested_workspace_ids(now, 1) == [execution_workspace.id]


def test_execution_wake_consumes_bounded_slot_before_recovery(monkeypatch):
    now = timezone.now()
    workspace_id = uuid4()
    claim = object()
    calls = []
    monkeypatch.setattr(
        runtime_power,
        "_requested_workspace_ids",
        lambda _now, _limit, *, trigger=None: [workspace_id]
        if trigger == RuntimeOperationTrigger.EXECUTION
        else [],
    )
    monkeypatch.setattr(
        runtime_power,
        "_claim_requested_operation",
        lambda candidate, _now: claim if candidate == workspace_id else None,
    )
    monkeypatch.setattr(
        runtime_power,
        "_process_wake_claim",
        lambda selected, _provider, _now: calls.append(selected)
        or runtime_power.RuntimePowerReport(started=1),
    )
    monkeypatch.setattr(
        runtime_power,
        "_recover_expired_operations",
        lambda *_args: pytest.fail("recovery ran before bounded execution wake"),
    )

    report = process_runtime_wakes(provider=object(), now=now, limit=1)

    assert calls == [claim]
    assert report.started == 1


def test_readiness_receipt_fences_claim_until_current_boot(workspace):
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="ally",
        hermes_profile_key="ally",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=workspace.machine_generation,
    )
    execution = create_execution(
        workspace.id,
        profile.id,
        "turn-1",
        {"message": "hello", "cloud_conversation_ref": "cloud-1"},
    )
    issued = issue_runtime_credential(workspace.id, "runtime-secret")
    context = authenticate_runtime_token(issued.raw_token)
    with pytest.raises(RuntimeNotReadyError):
        claim_next_execution(context, uuid4(), 1)
    assert not execution.attempts.exists()

    now = timezone.now()
    workspace.runtime_operation_id = uuid4()
    workspace.runtime_operation_state = RuntimeOperationState.AWAITING_READINESS
    workspace.runtime_operation_requested_at = now
    workspace.save(
        update_fields=[
            "runtime_operation_id",
            "runtime_operation_state",
            "runtime_operation_requested_at",
            "updated_at",
        ]
    )
    boot_id = uuid4()
    receipt = accept_runtime_readiness(
        context,
        boot_id,
        workspace.machine_generation,
        workspace.runtime_start_epoch,
        now=now,
    )
    assert receipt.status == "ready"
    assert claim_next_execution(context, uuid4(), 1) is not None
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.RUNNING


def test_stale_boot_and_epoch_are_rejected(workspace):
    issued = issue_runtime_credential(workspace.id, "runtime-secret")
    context = authenticate_runtime_token(issued.raw_token)
    now = timezone.now()
    workspace.runtime_operation_id = uuid4()
    workspace.runtime_operation_state = RuntimeOperationState.AWAITING_READINESS
    workspace.runtime_operation_requested_at = now
    workspace.save(
        update_fields=[
            "runtime_operation_id",
            "runtime_operation_state",
            "runtime_operation_requested_at",
            "updated_at",
        ]
    )
    boot_id = uuid4()
    accept_runtime_readiness(
        context, boot_id, 1, workspace.runtime_start_epoch, now=now
    )
    workspace.runtime_start_epoch += 1
    workspace.ready_generation = None
    workspace.ready_start_epoch = None
    workspace.ready_boot_id = None
    workspace.ready_at = None
    workspace.runtime_last_seen_at = None
    workspace.runtime_operation_id = uuid4()
    workspace.runtime_operation_state = RuntimeOperationState.AWAITING_READINESS
    workspace.runtime_operation_requested_at = now
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
            "runtime_operation_requested_at",
            "updated_at",
        ]
    )
    with pytest.raises(RuntimeFencedError):
        accept_runtime_readiness(context, boot_id, 1, 0, now=now)


def test_runtime_restart_replaces_idle_boot_and_claims_queued_work(workspace):
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="restart-ally",
        hermes_profile_key="restart-ally",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=workspace.machine_generation,
    )
    issued = issue_runtime_credential(workspace.id, "runtime-secret")
    context = authenticate_runtime_token(issued.raw_token)
    now = timezone.now()
    workspace.runtime_operation_id = uuid4()
    workspace.runtime_operation_state = RuntimeOperationState.AWAITING_READINESS
    workspace.runtime_operation_requested_at = now
    workspace.save(
        update_fields=[
            "runtime_operation_id",
            "runtime_operation_state",
            "runtime_operation_requested_at",
            "updated_at",
        ]
    )
    accept_runtime_readiness(
        context,
        uuid4(),
        workspace.machine_generation,
        workspace.runtime_start_epoch,
        now=now,
    )
    execution = create_execution(
        workspace.id,
        profile.id,
        "restart-turn",
        {"message": "hello", "cloud_conversation_ref": "restart-cloud"},
    )

    replacement_boot = uuid4()
    receipt = accept_runtime_readiness(
        context,
        replacement_boot,
        workspace.machine_generation,
        workspace.runtime_start_epoch,
        now=now + timedelta(seconds=1),
    )

    workspace.refresh_from_db()
    assert receipt.status == "ready"
    assert workspace.ready_boot_id == replacement_boot
    claim = claim_next_execution(context, uuid4(), 1)
    assert claim is not None
    assert claim.execution_id == execution.id


@override_settings(ALLIES_RUNTIME_READINESS_TIMEOUT_SECONDS=10)
def test_late_initial_readiness_receipt_recovers_after_timeout(workspace):
    issued = issue_runtime_credential(workspace.id, "runtime-secret")
    context = authenticate_runtime_token(issued.raw_token)
    now = timezone.now()
    workspace.runtime_operation_id = uuid4()
    workspace.runtime_operation_state = RuntimeOperationState.AWAITING_READINESS
    workspace.runtime_operation_trigger = None
    workspace.runtime_operation_requested_at = now - timedelta(seconds=10)
    workspace.save(
        update_fields=[
            "runtime_operation_id",
            "runtime_operation_state",
            "runtime_operation_trigger",
            "runtime_operation_requested_at",
            "updated_at",
        ]
    )

    report = process_runtime_wakes(
        provider=FakePowerProvider(workspace, state=MachineState.STARTED),
        now=now,
    )
    workspace.refresh_from_db()
    assert report.failed == 1
    assert workspace.runtime_operation_state == RuntimeOperationState.IDLE

    boot_id = uuid4()
    receipt = accept_runtime_readiness(
        context,
        boot_id,
        workspace.machine_generation,
        workspace.runtime_start_epoch,
        now=now + timedelta(seconds=1),
    )

    workspace.refresh_from_db()
    assert receipt.status == "ready"
    assert workspace.ready_boot_id == boot_id


def test_readiness_rejects_starting_before_provider_start_is_confirmed(workspace):
    issued = issue_runtime_credential(workspace.id, "runtime-secret")
    context = authenticate_runtime_token(issued.raw_token)
    now = timezone.now()
    workspace.runtime_operation_id = uuid4()
    workspace.runtime_operation_state = RuntimeOperationState.STARTING
    workspace.runtime_operation_requested_at = now
    workspace.save(
        update_fields=[
            "runtime_operation_id",
            "runtime_operation_state",
            "runtime_operation_requested_at",
            "updated_at",
        ]
    )

    with pytest.raises(RuntimeNotReadyError, match="provider evidence"):
        accept_runtime_readiness(
            context,
            uuid4(),
            workspace.machine_generation,
            workspace.runtime_start_epoch,
            now=now,
        )


def test_prompt_during_idle_stop_invalidates_stop_claim(workspace):
    now = timezone.now()
    workspace.runtime_operation_id = uuid4()
    workspace.runtime_operation_state = RuntimeOperationState.STOPPING
    workspace.runtime_operation_requested_at = now
    workspace.activation_claim_token = "old-stop-token"
    workspace.activation_claim_expires_at = now + timedelta(seconds=30)
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
    with transaction.atomic():
        locked = Workspace.objects.select_for_update().get(pk=workspace.id)
        request_execution_wake_locked(locked, now=now)
    workspace.refresh_from_db()
    assert workspace.runtime_operation_state == RuntimeOperationState.REQUESTED
    assert workspace.runtime_operation_trigger == RuntimeOperationTrigger.EXECUTION
    assert workspace.activation_claim_token is None


def test_composing_during_idle_stop_invalidates_stop_claim(workspace):
    now = timezone.now()
    old_operation_id = uuid4()
    workspace.runtime_operation_id = old_operation_id
    workspace.runtime_operation_state = RuntimeOperationState.STOPPING
    workspace.runtime_operation_requested_at = now
    workspace.activation_claim_token = "old-stop-token"
    workspace.activation_claim_expires_at = now + timedelta(seconds=30)
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

    receipt = request_runtime_intent(
        workspace.id, "composing_started", uuid4(), now, now=now
    )

    workspace.refresh_from_db()
    assert receipt.status == RuntimeIntentOutcome.WAKING
    assert receipt.operation_id != old_operation_id
    assert workspace.runtime_operation_state == RuntimeOperationState.REQUESTED
    assert workspace.runtime_operation_trigger == RuntimeOperationTrigger.SPECULATIVE
    assert workspace.activation_claim_token is None


@override_settings(ALLIES_RUNTIME_IDLE_STOP_ENABLED=True)
def test_idle_stop_is_gated_and_clears_deadline(workspace):
    now = timezone.now()
    workspace.speculative_keep_warm_until = now - timedelta(seconds=1)
    workspace.save(update_fields=["speculative_keep_warm_until", "updated_at"])
    provider = FakePowerProvider(workspace, state=MachineState.STARTED)

    report = stop_idle_workspaces(provider=provider, now=now)

    assert report.stopped == 1
    assert provider.stop_calls == 1
    workspace.refresh_from_db()
    assert workspace.speculative_keep_warm_until is None
    assert workspace.runtime_operation_state == RuntimeOperationState.IDLE


@override_settings(ALLIES_RUNTIME_IDLE_STOP_ENABLED=True)
def test_failed_idle_stop_parks_expired_deadline(workspace):
    now = timezone.now()
    workspace.speculative_keep_warm_until = now - timedelta(seconds=1)
    workspace.save(update_fields=["speculative_keep_warm_until", "updated_at"])
    provider = FakePowerProvider(workspace, state=MachineState.DESTROYED)

    first = stop_idle_workspaces(provider=provider, now=now)
    workspace.refresh_from_db()
    second = stop_idle_workspaces(provider=provider, now=now + timedelta(seconds=1))

    assert first.failed == 1
    assert workspace.speculative_keep_warm_until is None
    assert second.examined == 0
    assert provider.inspect_calls == 1


@override_settings(ALLIES_RUNTIME_IDLE_STOP_ENABLED=True)
def test_failed_provisioning_with_retained_binding_can_idle_stop(workspace):
    now = timezone.now()
    workspace.provisioning_phase = WorkspaceProvisioningPhase.FAILED
    workspace.speculative_keep_warm_until = now - timedelta(seconds=1)
    workspace.save(
        update_fields=[
            "provisioning_phase",
            "speculative_keep_warm_until",
            "updated_at",
        ]
    )
    provider = FakePowerProvider(workspace, state=MachineState.STARTED)

    report = stop_idle_workspaces(provider=provider, now=now)

    assert report.stopped == 1
    assert provider.stop_calls == 1


@override_settings(ALLIES_RUNTIME_IDLE_STOP_ENABLED=True)
def test_idle_stop_does_not_touch_workspace_with_queued_execution(workspace):
    now = timezone.now()
    workspace.speculative_keep_warm_until = now - timedelta(seconds=1)
    workspace.save(update_fields=["speculative_keep_warm_until", "updated_at"])
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="ally",
        hermes_profile_key="ally",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=workspace.machine_generation,
    )
    Execution.objects.create(
        workspace=workspace,
        profile=profile,
        idempotency_key="queued-turn",
        input_payload={"message": "hello"},
        status=ExecutionStatus.QUEUED,
    )
    provider = FakePowerProvider(workspace, state=MachineState.STARTED)

    report = stop_idle_workspaces(provider=provider, now=now)

    assert report.stopped == 0
    assert provider.stop_calls == 0


@override_settings(ALLIES_FLY_API_BASE_URL="http://fly-simulator:8765")
def test_power_provider_adds_fly_api_version_to_proof_origin(monkeypatch):
    monkeypatch.setenv("FLY_API_TOKEN", "proof-token")

    provider = runtime_power_provider()

    assert provider.http.base_url == "http://fly-simulator:8765/v1"
