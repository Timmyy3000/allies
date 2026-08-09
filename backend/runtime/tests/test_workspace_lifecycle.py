from __future__ import annotations

from uuid import UUID

import pytest

from runtime.models import Workspace
from runtime.providers import (
    AppRecord,
    ContainerState,
    MachineHealth,
    MachineRecord,
    MachineState,
    OwnershipMetadata,
    ProviderNotFoundError,
    ProviderOwnershipError,
    VolumeRecord,
    deterministic_resource_names,
)
from runtime.services.workspaces import (
    WorkspaceLifecycle,
    WorkspaceReplacementRequiredError,
    WorkspaceSpec,
)

WORKSPACE_ID = UUID("01234567-89ab-cdef-0123-456789abcdef")


class FakeProvider:
    def __init__(self):
        self.app = None
        self.volume = None
        self.machines = {}
        self.calls = []
        self.force_unhealthy = False
        self.stop_ack_only = False
        self.stop_inspections = 0
        self.reject_destroy_while_running = False
        self.stop_404_after_inspect = False
        self.destroy_404_after_inspect = False

    def ensure_app(self, spec):
        self.calls.append("ensure_app")
        self.app = self.app or AppRecord("app-id", spec.name, spec.organization)
        return self.app

    def list_volumes(self, app_name):
        self.calls.append("list_volumes")
        return [self.volume] if self.volume else []

    def ensure_volume(self, spec):
        self.calls.append("ensure_volume")
        self.volume = self.volume or VolumeRecord(
            "volume-id", spec.name, spec.app_name, spec.region, spec.size_gb
        )
        return self.volume

    def inspect_machine(self, app_name, name):
        return next((m for m in self.machines.values() if m.name == name), None)

    def inspect_machine_by_id(self, app_name, machine_id):
        machine = self.machines.get(machine_id)
        if self.stop_ack_only and machine_id in self.machines:
            self.stop_inspections += 1
            if self.stop_inspections >= 2:
                machine = self._set_machine(machine_id, MachineState.STOPPED)
        if machine is None or not self.force_unhealthy:
            return machine
        return MachineRecord(
            machine.id,
            machine.name,
            machine.app_name,
            machine.region,
            machine.state,
            machine.volume_id,
            machine.ownership,
            MachineHealth(machine.state, {}),
        )

    def ensure_machine(self, spec):
        self.calls.append("ensure_machine")
        existing = self.inspect_machine(spec.app_name, spec.name)
        if existing:
            return existing
        machine = MachineRecord(
            f"machine-{spec.ownership.generation}",
            spec.name,
            spec.app_name,
            spec.region,
            MachineState.CREATED,
            spec.mount.volume_id,
            spec.ownership,
            MachineHealth(MachineState.CREATED, {}),
        )
        self.machines[machine.id] = machine
        self.volume = VolumeRecord(
            self.volume.id,
            self.volume.name,
            self.volume.app_name,
            self.volume.region,
            self.volume.size_gb,
            machine.id,
            self.volume.ownership,
        )
        return machine

    def start_machine(self, app_name, machine_id):
        self.calls.append("start_machine")
        return self._set_machine(machine_id, MachineState.STARTED)

    def stop_machine(self, app_name, machine_id):
        self.calls.append("stop_machine")
        if self.stop_404_after_inspect:
            self._remove_machine(machine_id)
            raise ProviderNotFoundError("Machine already stopped")
        if self.stop_ack_only:
            return self.machines[machine_id]
        return self._set_machine(machine_id, MachineState.STOPPED)

    def destroy_machine(self, app_name, machine_id):
        self.calls.append("destroy_machine")
        if self.reject_destroy_while_running and self.machines[
            machine_id
        ].state not in (
            MachineState.STOPPED,
            MachineState.DESTROYED,
        ):
            raise AssertionError("destroyed a Machine before it stopped")
        if self.destroy_404_after_inspect:
            self._remove_machine(machine_id)
            raise ProviderNotFoundError("Machine already destroyed")
        self._remove_machine(machine_id)

    def wait_machine(self, app_name, machine_id, *, timeout_seconds):
        self.calls.append("wait_machine")
        if self.force_unhealthy:
            machine = self.machines[machine_id]
            return MachineRecord(
                machine.id,
                machine.name,
                machine.app_name,
                machine.region,
                MachineState.STARTED,
                machine.volume_id,
                machine.ownership,
                MachineHealth(MachineState.STARTED, {}),
            )
        return self.machines[machine_id]

    def _set_machine(self, machine_id, state):
        old = self.machines[machine_id]
        machine = MachineRecord(
            old.id,
            old.name,
            old.app_name,
            old.region,
            state,
            old.volume_id,
            old.ownership,
            MachineHealth(
                state,
                {
                    "hermes": ContainerState.STARTED,
                    "allies-runtime": ContainerState.STARTED,
                }
                if state is MachineState.STARTED
                else {},
            ),
        )
        self.machines[machine_id] = machine
        return machine

    def _remove_machine(self, machine_id):
        self.machines.pop(machine_id, None)
        self.volume = VolumeRecord(
            self.volume.id,
            self.volume.name,
            self.volume.app_name,
            self.volume.region,
            self.volume.size_gb,
            None,
            self.volume.ownership,
        )


def spec():
    return WorkspaceSpec(
        organization="allies",
        region="ams",
        hermes_image="hermes@sha256:test",
        runtime_image="runtime@sha256:test",
        runtime_credential_ref="vault://runtime/test",
    )


@pytest.mark.django_db(transaction=True)
def test_ensure_is_idempotent_and_binds_one_machine():
    provider = FakeProvider()
    lifecycle = WorkspaceLifecycle(provider, sleep=lambda _: None, jitter=False)
    workspace = Workspace.objects.create(id=WORKSPACE_ID, tenant_ref="tenant-lifecycle")

    first = lifecycle.ensure_workspace(workspace.id, spec())
    second = lifecycle.ensure_workspace(workspace.id, spec())

    assert first == second
    assert first.machine_generation == 1
    assert len(provider.machines) == 1
    assert provider.calls.count("ensure_app") == 1
    assert provider.calls.count("ensure_volume") == 1


@pytest.mark.django_db(transaction=True)
def test_missing_bound_machine_requires_explicit_replacement():
    names = deterministic_resource_names(WORKSPACE_ID)
    Workspace.objects.create(
        id=WORKSPACE_ID,
        tenant_ref="tenant-missing",
        fly_app_ref="app-id",
        volume_ref="volume-id",
        machine_ref="missing-machine",
        machine_generation=1,
    )
    provider = FakeProvider()
    provider.app = AppRecord("app-id", names.app, "allies")
    provider.volume = VolumeRecord("volume-id", names.volume, names.app, "ams", 1)

    with pytest.raises(WorkspaceReplacementRequiredError):
        WorkspaceLifecycle(provider, sleep=lambda _: None).ensure_workspace(
            WORKSPACE_ID, spec()
        )


@pytest.mark.django_db(transaction=True)
def test_replace_fences_generation_preserves_volume_and_replays_same_source():
    provider = FakeProvider()
    lifecycle = WorkspaceLifecycle(provider, sleep=lambda _: None, jitter=False)
    initial = Workspace.objects.create(id=WORKSPACE_ID, tenant_ref="tenant-replace")
    binding = lifecycle.ensure_workspace(initial.id, spec())
    old_machine = binding.machine_ref
    volume_id = binding.volume_ref

    replaced = lifecycle.replace_machine(initial.id, spec(), 1)
    replay = lifecycle.replace_machine(initial.id, spec(), 1)

    assert replaced.machine_generation == 2
    assert replaced.volume_ref == volume_id
    assert replaced.machine_ref != old_machine
    assert replay == replaced
    assert old_machine not in provider.machines
    assert provider.calls.index("stop_machine") < provider.calls.index(
        "destroy_machine"
    )


@pytest.mark.django_db(transaction=True)
def test_replace_waits_for_authoritative_stop_before_destroying_machine():
    provider = FakeProvider()
    provider.stop_ack_only = True
    provider.reject_destroy_while_running = True
    lifecycle = WorkspaceLifecycle(provider, sleep=lambda _: None, jitter=False)
    initial = Workspace.objects.create(id=WORKSPACE_ID, tenant_ref="tenant-stop-wait")

    lifecycle.ensure_workspace(initial.id, spec())
    replaced = lifecycle.replace_machine(initial.id, spec(), 1)

    assert replaced.machine_generation == 2
    assert provider.stop_inspections >= 2


@pytest.mark.django_db(transaction=True)
def test_stop_404_after_inspection_is_reconciled_as_already_gone():
    provider = FakeProvider()
    provider.stop_404_after_inspect = True
    lifecycle = WorkspaceLifecycle(provider, sleep=lambda _: None, jitter=False)
    initial = Workspace.objects.create(id=WORKSPACE_ID, tenant_ref="tenant-stop-404")

    lifecycle.ensure_workspace(initial.id, spec())
    replaced = lifecycle.replace_machine(initial.id, spec(), 1)

    assert replaced.machine_generation == 2
    assert "destroy_machine" not in provider.calls


@pytest.mark.django_db(transaction=True)
def test_destroy_404_after_inspection_is_reconciled_as_already_gone():
    provider = FakeProvider()
    provider.destroy_404_after_inspect = True
    lifecycle = WorkspaceLifecycle(provider, sleep=lambda _: None, jitter=False)
    initial = Workspace.objects.create(id=WORKSPACE_ID, tenant_ref="tenant-destroy-404")

    lifecycle.ensure_workspace(initial.id, spec())
    replaced = lifecycle.replace_machine(initial.id, spec(), 1)

    assert replaced.machine_generation == 2
    assert provider.calls.count("destroy_machine") == 1


@pytest.mark.django_db(transaction=True)
def test_replace_never_destroys_a_machine_with_mismatched_ownership():
    provider = FakeProvider()
    app_name = deterministic_resource_names(WORKSPACE_ID).app
    volume_name = deterministic_resource_names(WORKSPACE_ID).volume
    workspace = Workspace.objects.create(
        id=WORKSPACE_ID,
        tenant_ref="tenant-ownership",
        fly_app_ref=app_name,
        volume_ref="volume-id",
        machine_ref="machine-legacy",
        machine_generation=1,
    )
    provider.volume = VolumeRecord(
        "volume-id",
        volume_name,
        app_name,
        "ams",
        1,
        "machine-legacy",
    )
    provider.machines["machine-legacy"] = MachineRecord(
        "machine-legacy",
        "unknown-machine-name",
        app_name,
        "ams",
        MachineState.STARTED,
        "volume-id",
        OwnershipMetadata(UUID(int=2), UUID(int=3), 1),
    )

    with pytest.raises(ProviderOwnershipError):
        WorkspaceLifecycle(
            provider, sleep=lambda _: None, jitter=False
        ).replace_machine(workspace.id, spec(), 1)

    assert "stop_machine" not in provider.calls
    assert "destroy_machine" not in provider.calls


@pytest.mark.django_db(transaction=True)
def test_attachment_conflict_does_not_create_a_machine():
    provider = FakeProvider()
    lifecycle = WorkspaceLifecycle(provider, sleep=lambda _: None, jitter=False)
    workspace = Workspace.objects.create(id=WORKSPACE_ID, tenant_ref="tenant-attach")
    provider.volume = VolumeRecord(
        "volume-id",
        "volume",
        deterministic_resource_names(WORKSPACE_ID).app,
        "ams",
        1,
        "unknown",
    )

    from runtime.providers import ProviderAttachmentConflictError

    with pytest.raises(ProviderAttachmentConflictError):
        lifecycle.ensure_workspace(workspace.id, spec())
    assert not provider.machines


@pytest.mark.django_db(transaction=True)
def test_health_timeout_keeps_operation_resumable():
    provider = FakeProvider()
    provider.force_unhealthy = True
    lifecycle = WorkspaceLifecycle(
        provider, sleep=lambda _: None, jitter=False, phase_deadline_seconds=0.01
    )
    workspace = Workspace.objects.create(id=WORKSPACE_ID, tenant_ref="tenant-health")

    from runtime.providers import ProviderRetryableError

    with pytest.raises(ProviderRetryableError):
        lifecycle.ensure_workspace(workspace.id, spec())
    workspace.refresh_from_db()
    assert workspace.provisioning_phase == "healthy"
    assert workspace.provisioning_claim_token is None
