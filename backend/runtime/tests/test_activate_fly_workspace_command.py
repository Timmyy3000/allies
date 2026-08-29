from __future__ import annotations

from typing import ClassVar
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from runtime.models import RuntimeCredential, Workspace, WorkspaceProvisioningPhase
from runtime.providers import (
    AppRecord,
    ContainerState,
    MachineHealth,
    MachineRecord,
    MachineState,
    ProviderRetryableError,
    ProviderTerminalError,
    VolumeRecord,
    deterministic_resource_names,
)
from runtime.services.continuity_proof import (
    ProofCredentialHandle,
    ProofDependencyCredentialHandle,
)
from runtime.tests.test_workspace_lifecycle import FakeProvider


class CommandProvider(FakeProvider):
    def assert_proof_capabilities(self):
        return None

    def set_release_metadata(self, *_metadata):
        return None


def configure_activation(monkeypatch):
    settings = {
        "FLY_API_TOKEN": "fly-token",
        "FLY_ORG": "allies",
        "FLY_REGION": "ams",
        "FOUNDRY_ORIGIN": "https://foundry.example.com",
        "RUNTIME_IMAGE": "runtime@sha256:test",
        "HERMES_IMAGE": "hermes@sha256:test",
        "PROFILE_PROVISIONING_API_KEY": "provider-key",
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)


def machine_for(workspace_id, machine_id="machine-owned"):
    names = deterministic_resource_names(workspace_id)
    return MachineRecord(
        machine_id,
        names.machine(1),
        names.app,
        "ams",
        MachineState.STARTED,
        "volume-id",
        health=MachineHealth(
            MachineState.STARTED,
            {
                "hermes": ContainerState.STARTED,
                "allies-runtime": ContainerState.STARTED,
            },
        ),
    )


class FakeSecretStore:
    def bootstrap_release(self, *_args):
        return "rel_test", "1"


class FakeCredentialBootstrap:
    instances: ClassVar[list] = []

    def __init__(self, _secret_store):
        self.cleanup_calls = []
        self.__class__.instances.append(self)

    def prepare(self, workspace_id, app_ref, *, generation, operation_id):
        return ProofCredentialHandle(
            workspace_id=workspace_id,
            app_ref=app_ref,
            generation=generation,
            operation_id=operation_id,
            credential_id=uuid4(),
            secret_name=f"ALLIES_FND008_G{generation}_TEST",
            credential_ref="file:///run/secrets/foundry-runtime-token",
            raw_token="token",
        )

    def cleanup(self, handle):
        self.cleanup_calls.append(handle)


class FakeDependencyBootstrap:
    instances: ClassVar[list] = []

    def __init__(self, _secret_store, *, provider_api_key):
        assert provider_api_key == "provider-key"
        self.cleanup_calls = []
        self.__class__.instances.append(self)

    def prepare(self, app_ref):
        return ProofDependencyCredentialHandle(
            app_ref=app_ref,
            hermes_key_secret_name="ALLIES_FND008_HERMES_KEY",
            provider_key_secret_name="ALLIES_FND008_OPENAI_KEY",
        )

    def cleanup(self, handle):
        self.cleanup_calls.append(handle)


def patch_command_dependencies(monkeypatch, provider, lifecycle):
    import runtime.management.commands.activate_fly_workspace as activation

    monkeypatch.setattr(activation, "FlyProvider", lambda **_kwargs: provider)
    monkeypatch.setattr(activation, "FlyCliSecretStore", FakeSecretStore)
    monkeypatch.setattr(activation, "ProofCredentialBootstrap", FakeCredentialBootstrap)
    monkeypatch.setattr(
        activation,
        "ProofDependencyCredentialBootstrap",
        FakeDependencyBootstrap,
    )
    monkeypatch.setattr(activation, "WorkspaceLifecycle", lambda *_a, **_k: lifecycle)


class FailingLifecycle:
    def __init__(self, provider, workspace_id, *, create_machine):
        self.provider = provider
        self.workspace_id = workspace_id
        self.create_machine = create_machine

    def ensure_workspace(self, *_args, **_kwargs):
        if self.create_machine:
            machine = machine_for(self.workspace_id)
            self.provider.machines[machine.id] = machine
        raise ProviderRetryableError("tunnel is unavailable", operation="ensure")


class TerminalLifecycle:
    def ensure_workspace(self, *_args, **_kwargs):
        raise ProviderTerminalError("invalid image", operation="ensure")


@pytest.fixture(autouse=True)
def reset_fake_bootstraps():
    FakeCredentialBootstrap.instances.clear()
    FakeDependencyBootstrap.instances.clear()


@pytest.mark.django_db
def test_command_rejects_an_unregistered_workspace():
    with pytest.raises(CommandError, match="not registered"):
        call_command("activate_fly_workspace", str(uuid4()))


@pytest.mark.django_db
def test_command_rejects_missing_activation_settings():
    tenant_ref = uuid4()
    Workspace.objects.create(tenant_ref=str(tenant_ref))

    with pytest.raises(CommandError, match="Missing required settings"):
        call_command("activate_fly_workspace", str(tenant_ref))


@pytest.mark.django_db
def test_active_generation_must_have_a_ready_recorded_machine(monkeypatch):
    configure_activation(monkeypatch)
    tenant_ref = uuid4()
    workspace = Workspace.objects.create(
        tenant_ref=str(tenant_ref),
        fly_app_ref=deterministic_resource_names(tenant_ref).app,
        volume_ref="volume-id",
        machine_ref="machine-owned",
        machine_generation=1,
        provisioning_phase=WorkspaceProvisioningPhase.IDLE,
    )
    provider = CommandProvider()
    provider.app = AppRecord("app-id", workspace.fly_app_ref, "allies")
    provider.volume = VolumeRecord(
        "volume-id",
        deterministic_resource_names(tenant_ref).volume,
        workspace.fly_app_ref,
        "ams",
        1,
    )
    provider.machines["machine-owned"] = machine_for(workspace.id)
    provider.force_unhealthy = True

    import runtime.management.commands.activate_fly_workspace as activation

    monkeypatch.setattr(activation, "FlyProvider", lambda **_kwargs: provider)
    with pytest.raises(CommandError, match="activation failed"):
        call_command("activate_fly_workspace", str(tenant_ref))


@pytest.mark.django_db
def test_resumable_failure_retains_credentials_when_machine_appears(monkeypatch):
    configure_activation(monkeypatch)
    tenant_ref = uuid4()
    workspace = Workspace.objects.create(tenant_ref=str(tenant_ref))
    provider = CommandProvider()
    lifecycle = FailingLifecycle(provider, workspace.id, create_machine=True)
    patch_command_dependencies(monkeypatch, provider, lifecycle)

    with pytest.raises(CommandError, match="activation failed"):
        call_command("activate_fly_workspace", str(tenant_ref))

    assert FakeCredentialBootstrap.instances[0].cleanup_calls == []
    assert FakeDependencyBootstrap.instances[0].cleanup_calls == []


@pytest.mark.django_db
def test_terminal_failure_does_not_revoke_existing_active_credential(monkeypatch):
    configure_activation(monkeypatch)
    tenant_ref = uuid4()
    workspace = Workspace.objects.create(tenant_ref=str(tenant_ref))
    credential = RuntimeCredential.objects.create(
        workspace=workspace,
        token_digest="a" * 64,
        machine_generation=1,
    )
    provider = CommandProvider()
    patch_command_dependencies(monkeypatch, provider, TerminalLifecycle())

    with pytest.raises(CommandError, match="activation failed"):
        call_command("activate_fly_workspace", str(tenant_ref))

    credential.refresh_from_db()
    assert credential.revoked_at is None
    assert FakeCredentialBootstrap.instances[0].cleanup_calls == []
    assert len(FakeDependencyBootstrap.instances[0].cleanup_calls) == 1


@pytest.mark.django_db
def test_cleanup_failure_does_not_replace_original_activation_error(monkeypatch):
    configure_activation(monkeypatch)
    tenant_ref = uuid4()
    Workspace.objects.create(tenant_ref=str(tenant_ref))
    provider = CommandProvider()

    class CleanupFailsCredential(FakeCredentialBootstrap):
        def cleanup(self, _handle):
            raise RuntimeError("credential cleanup failed")

    class CleanupFailsDependency(FakeDependencyBootstrap):
        def cleanup(self, _handle):
            raise RuntimeError("dependency cleanup failed")

    import runtime.management.commands.activate_fly_workspace as activation

    monkeypatch.setattr(activation, "FlyProvider", lambda **_kwargs: provider)
    monkeypatch.setattr(activation, "FlyCliSecretStore", FakeSecretStore)
    monkeypatch.setattr(activation, "ProofCredentialBootstrap", CleanupFailsCredential)
    monkeypatch.setattr(
        activation, "ProofDependencyCredentialBootstrap", CleanupFailsDependency
    )
    monkeypatch.setattr(
        activation, "WorkspaceLifecycle", lambda *_a, **_k: TerminalLifecycle()
    )

    with pytest.raises(CommandError) as error:
        call_command("activate_fly_workspace", str(tenant_ref))

    assert isinstance(error.value.__cause__, ProviderTerminalError)
