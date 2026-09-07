from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from uuid import uuid4

import pytest
from django.utils import timezone

from runtime.models import (
    ReadyWorkspaceBundle,
    ReadyWorkspaceBundleState,
    RuntimeCredential,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.providers import (
    AppRecord,
    ContainerState,
    MachineHealth,
    MachineRecord,
    MachineState,
    OwnershipMetadata,
    ProviderOwnershipError,
    VolumeRecord,
    deterministic_resource_names,
)
from runtime.providers.fly_pool import FlyPoolAdapter


class FakeProvider:
    def __init__(self, workspace: Workspace, *, owned: bool = True) -> None:
        names = deterministic_resource_names(workspace.id)
        ownership = OwnershipMetadata(
            workspace.id if owned else uuid4(),
            workspace.provisioning_id or uuid4(),
            workspace.machine_generation,
        )
        self.app = AppRecord("app-id", workspace.fly_app_ref, "org")
        self.volume = VolumeRecord(
            workspace.volume_ref,
            names.volume,
            workspace.fly_app_ref,
            "ams",
            1,
            attached_machine_id=workspace.machine_ref,
        )
        self.machine = MachineRecord(
            workspace.machine_ref,
            names.machine(workspace.machine_generation),
            workspace.fly_app_ref,
            "ams",
            MachineState.STARTED,
            volume_id=workspace.volume_ref,
            ownership=ownership,
            health=MachineHealth(
                MachineState.STARTED,
                {
                    "hermes": ContainerState.STARTED,
                    "allies-runtime": ContainerState.STARTED,
                },
            ),
            images={
                "hermes": "registry.example/hermes@sha256:" + "a" * 64,
                "allies-runtime": "registry.example/runtime@sha256:" + "b" * 64,
            },
        )
        self.calls: list[str] = []

    def inspect_app(self, _app_ref):
        self.calls.append("inspect_app")
        return self.app

    def list_volumes(self, _app_ref):
        self.calls.append("list_volumes")
        return (self.volume,) if self.volume is not None else ()

    def inspect_machine_by_id(self, _app_ref, _machine_ref):
        self.calls.append("inspect_machine")
        return self.machine

    def stop_machine(self, _app_ref, _machine_ref):
        self.calls.append("stop_machine")
        self.machine = replace(self.machine, state=MachineState.STOPPED)
        return self.machine

    def destroy_machine(self, _app_ref, _machine_ref):
        self.calls.append("destroy_machine")
        self.machine = None
        self.volume = replace(self.volume, attached_machine_id=None)

    def delete_volume(self, _app_ref, _volume_ref):
        self.calls.append("delete_volume")
        self.volume = None

    def delete_app(self, _app_ref):
        self.calls.append("delete_app")
        self.app = None


def make_workspace():
    operation_id = uuid4()
    workspace = Workspace.objects.create(
        tenant_ref=f"pool:{uuid4()}",
    )
    names = deterministic_resource_names(workspace.id)
    workspace.fly_app_ref = names.app
    workspace.volume_ref = f"vol-{uuid4().hex}"
    workspace.machine_ref = f"mach-{uuid4().hex}"
    workspace.machine_generation = 1
    workspace.provisioning_id = operation_id
    workspace.provisioning_phase = WorkspaceProvisioningPhase.IDLE
    workspace.save()
    ReadyWorkspaceBundle.objects.create(
        workspace=workspace,
        state=ReadyWorkspaceBundleState.PREPARING,
        region="ams",
        release_fingerprint="release",
        config_version=1,
        next_attempt_at=timezone.now(),
    )
    return workspace


@pytest.mark.django_db(transaction=True)
def test_inspect_translates_exact_provider_evidence():
    workspace = make_workspace()
    provider = FakeProvider(workspace)
    adapter = FlyPoolAdapter(
        provider,
        lambda _workspace_id: None,
        organization="org",
        blank_probe=lambda _workspace: True,
    )

    snapshot = adapter.inspect(workspace)

    assert snapshot.app_ref == workspace.fly_app_ref
    assert snapshot.volume_ref == workspace.volume_ref
    assert snapshot.machine_ref == workspace.machine_ref
    assert snapshot.region == "ams"
    assert set(snapshot.health_containers) == {"hermes", "allies-runtime"}
    assert snapshot.ownership_workspace_id == workspace.id
    assert snapshot.ownership_operation_id == workspace.provisioning_id
    assert snapshot.blank


@pytest.mark.django_db(transaction=True)
def test_inspect_without_blank_proof_fails_closed():
    workspace = make_workspace()
    provider = FakeProvider(workspace)
    adapter = FlyPoolAdapter(provider, lambda _workspace_id: None, organization="org")

    snapshot = adapter.inspect(workspace)

    assert snapshot.blank is False


@pytest.mark.django_db(transaction=True)
def test_inspect_uses_durable_blank_volume_proof_after_adapter_recreation():
    workspace = make_workspace()
    ReadyWorkspaceBundle.objects.filter(workspace_id=workspace.id).update(
        blank_volume_ref=workspace.volume_ref
    )
    provider = FakeProvider(workspace)
    adapter = FlyPoolAdapter(provider, lambda _workspace_id: None, organization="org")

    snapshot = adapter.inspect(workspace)

    assert snapshot.blank is True


@pytest.mark.django_db(transaction=True)
def test_record_fresh_volume_proves_exact_new_volume_for_resume():
    workspace = make_workspace()
    provider = FakeProvider(workspace)
    adapter = FlyPoolAdapter(provider, lambda _workspace_id: None, organization="org")
    adapter._fresh_volume_workspaces.add(workspace.id)

    assert adapter.record_fresh_volume(workspace) == workspace.volume_ref
    assert workspace.id not in adapter._fresh_volume_workspaces
    assert provider.calls == ["inspect_app", "list_volumes"]


@pytest.mark.django_db(transaction=True)
def test_inspect_rejects_wrong_provider_ownership():
    workspace = make_workspace()
    provider = FakeProvider(workspace, owned=False)
    adapter = FlyPoolAdapter(provider, lambda _workspace_id: None, organization="org")

    with pytest.raises(ProviderOwnershipError):
        adapter.inspect(workspace)

    assert provider.calls == ["inspect_app", "list_volumes", "inspect_machine"]


@pytest.mark.django_db(transaction=True)
def test_cleanup_revokes_credentials_and_deletes_exact_resources_and_app_secrets():
    workspace = make_workspace()
    credential = RuntimeCredential.objects.create(
        workspace=workspace,
        token_digest=sha256(b"pool-token").hexdigest(),
        machine_generation=1,
    )
    provider = FakeProvider(workspace)
    adapter = FlyPoolAdapter(
        provider,
        lambda _workspace_id: None,
        organization="org",
    )

    # Deleting the independently verified App removes its scoped Fly secrets;
    # individual unsets would restart the live runtime and use a guessed name.
    assert adapter.cleanup(workspace)

    credential.refresh_from_db()
    assert credential.revoked_at is not None
    assert provider.calls == [
        "inspect_app",
        "inspect_machine",
        "inspect_machine",
        "stop_machine",
        "inspect_machine",
        "destroy_machine",
        "inspect_machine",
        "list_volumes",
        "delete_volume",
        "delete_app",
    ]


@pytest.mark.django_db(transaction=True)
def test_cleanup_fails_closed_before_destroying_mismatched_machine():
    workspace = make_workspace()
    provider = FakeProvider(workspace, owned=False)
    adapter = FlyPoolAdapter(provider, lambda _workspace_id: None, organization="org")

    with pytest.raises(ProviderOwnershipError):
        adapter.cleanup(workspace)

    assert provider.calls == ["inspect_app", "inspect_machine"]


@pytest.mark.django_db(transaction=True)
def test_cleanup_rejects_foreign_app_reference_before_provider_io():
    workspace = make_workspace()
    Workspace.objects.filter(pk=workspace.pk).update(fly_app_ref="foreign-app")
    workspace.refresh_from_db()
    provider = FakeProvider(workspace)
    adapter = FlyPoolAdapter(provider, lambda _workspace_id: None, organization="org")

    with pytest.raises(ProviderOwnershipError):
        adapter.cleanup(workspace)

    assert provider.calls == []
