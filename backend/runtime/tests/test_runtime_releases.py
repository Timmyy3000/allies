from dataclasses import replace
from datetime import timedelta
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from runtime.exceptions import RuntimeFencedError
from runtime.models import (
    Attempt,
    Execution,
    Lease,
    RuntimeCredential,
    RuntimeOperationState,
    RuntimeProfile,
    Workspace,
)
from runtime.providers import ProviderRetryableError
from runtime.services.runtime_auth import RuntimeContext
from runtime.services.runtime_intents import request_execution_wake_locked
from runtime.services.runtime_power import process_runtime_wakes
from runtime.services.runtime_readiness import (
    accept_runtime_readiness,
    is_runtime_ready,
)
from runtime.services.runtime_releases import reconcile_workspace_release
from runtime.services.workspaces import WorkspaceLifecycle, WorkspaceSpec
from runtime.tests.test_workspace_lifecycle import FakeProvider

OLD = {
    "hermes": "hermes@sha256:" + "a" * 64,
    "allies-runtime": "runtime@sha256:" + "b" * 64,
}
NEW = {
    "hermes": "hermes@sha256:" + "c" * 64,
    "allies-runtime": "runtime@sha256:" + "d" * 64,
}


class ImageProvider(FakeProvider):
    fail_create = False
    wrong_image = False

    def ensure_machine(self, spec):
        if self.fail_create and spec.ownership.generation > 1:
            raise ProviderRetryableError("image pull unavailable")
        machine = super().ensure_machine(spec)
        images = {c.name: c.image for c in spec.containers}
        if self.wrong_image:
            images = OLD
        machine = replace(machine, images=images)
        self.machines[machine.id] = machine
        return machine

    def _set_machine(self, machine_id, state):
        images = self.machines[machine_id].images
        machine = replace(super()._set_machine(machine_id, state), images=images)
        self.machines[machine_id] = machine
        return machine


class SecretStore:
    def __init__(self):
        self.staged = []

    def stage(self, app, name, value):
        self.staged.append((app, name))

    def remove(self, *_args):
        pass


@pytest.fixture
def release_setup(db, monkeypatch):
    from runtime.services import runtime_releases

    monkeypatch.setenv("HERMES_IMAGE", NEW["hermes"])
    monkeypatch.setenv("RUNTIME_IMAGE", NEW["allies-runtime"])
    monkeypatch.setenv("FOUNDRY_ORIGIN", "https://foundry.example.com")
    monkeypatch.setenv("ALLIES_RUNTIME_IMAGE_UPDATES_ENABLED", "true")
    store = SecretStore()
    monkeypatch.setattr(runtime_releases, "FlyCliSecretStore", lambda: store)
    provider = ImageProvider()
    workspace = Workspace.objects.create(tenant_ref=str(uuid4()))
    spec = WorkspaceSpec(
        hermes_image=OLD["hermes"], runtime_image=OLD["allies-runtime"]
    )
    WorkspaceLifecycle(provider, sleep=lambda _: None, jitter=False).ensure_workspace(
        workspace.id, spec
    )
    workspace.refresh_from_db()
    workspace.runtime_operation_state = RuntimeOperationState.IDLE
    workspace.runtime_operation_id = None
    workspace.speculative_keep_warm_until = timezone.now() - timedelta(minutes=1)
    workspace.save()
    provider.stop_machine(workspace.fly_app_ref, workspace.machine_ref)
    provider.calls.clear()
    return workspace, provider, store


def ready(workspace):
    workspace.refresh_from_db()
    return accept_runtime_readiness(
        RuntimeContext(workspace.id, workspace.machine_generation, uuid4()),
        uuid4(),
        workspace.machine_generation,
        workspace.runtime_start_epoch,
    )


def wake(workspace, provider):
    request_execution_wake_locked(workspace)
    return process_runtime_wakes(provider=provider)


def test_wake_replaces_both_images_preserves_volume_and_gates_readiness(release_setup):
    workspace, provider, store = release_setup
    volume, old_machine = workspace.volume_ref, workspace.machine_ref
    report = wake(workspace, provider)
    workspace.refresh_from_db()
    assert report.awaiting_readiness == 1 and report.failed == 0
    assert workspace.machine_generation == 2
    assert workspace.volume_ref == volume
    assert old_machine not in provider.machines
    assert len(provider.machines) == 1
    assert workspace.applied_images == NEW and workspace.release_target == {}
    assert not is_runtime_ready(workspace)
    assert len(store.staged) == 1
    with pytest.raises(RuntimeFencedError):
        accept_runtime_readiness(
            RuntimeContext(workspace.id, 1, uuid4()), uuid4(), 1, 1
        )
    ready(workspace)
    workspace.refresh_from_db()
    assert is_runtime_ready(workspace)


@pytest.mark.parametrize("container", ["hermes", "allies-runtime"])
def test_either_changed_image_triggers_replacement(
    release_setup, monkeypatch, container
):
    workspace, provider, _ = release_setup
    other = "hermes" if container == "allies-runtime" else "allies-runtime"
    monkeypatch.setenv(
        "HERMES_IMAGE" if other == "hermes" else "RUNTIME_IMAGE", OLD[other]
    )
    assert wake(workspace, provider).awaiting_readiness == 1
    workspace.refresh_from_db()
    assert workspace.machine_generation == 2
    assert workspace.applied_images[container] == NEW[container]
    assert workspace.applied_images[other] == OLD[other]


def test_current_machine_only_starts_and_backfills_legacy_images(
    release_setup, monkeypatch
):
    workspace, provider, store = release_setup
    monkeypatch.setenv("HERMES_IMAGE", OLD["hermes"])
    monkeypatch.setenv("RUNTIME_IMAGE", OLD["allies-runtime"])
    workspace.applied_images = {}
    workspace.save()
    assert wake(workspace, provider).started == 1
    workspace.refresh_from_db()
    assert workspace.machine_generation == 1 and not store.staged
    assert "destroy_machine" not in provider.calls
    assert workspace.applied_images == OLD


def test_active_workspace_is_not_replaced_until_keep_warm_expires(release_setup):
    workspace, provider, store = release_setup
    provider.start_machine(workspace.fly_app_ref, workspace.machine_ref)
    workspace.speculative_keep_warm_until = timezone.now() + timedelta(minutes=10)
    workspace.save()
    assert reconcile_workspace_release(workspace.id, provider=provider) == "busy"
    assert not store.staged
    workspace.speculative_keep_warm_until = timezone.now() - timedelta(seconds=1)
    workspace.save()
    assert (
        reconcile_workspace_release(workspace.id, provider=provider)
        == "awaiting_readiness"
    )


def test_release_retries_same_generation_credentials_and_pinned_images(
    release_setup, monkeypatch
):
    workspace, provider, store = release_setup
    provider.fail_create = True
    # No wall-clock sleeps in the real lifecycle's retry test.
    monkeypatch.setattr("runtime.services.workspaces.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "runtime.services.runtime_releases.WorkspaceLifecycle",
        lambda p, **kw: WorkspaceLifecycle(p, sleep=lambda _: None, **kw),
    )
    with pytest.raises(ProviderRetryableError):
        reconcile_workspace_release(workspace.id, provider=provider)
    workspace.refresh_from_db()
    assert workspace.machine_generation == 2 and workspace.release_target
    assert workspace.volume_ref == "volume-id" and not provider.machines
    assert not is_runtime_ready(workspace)
    monkeypatch.setenv("RUNTIME_IMAGE", "runtime@sha256:" + "e" * 64)
    provider.fail_create = False
    report = process_runtime_wakes(provider=provider)
    workspace.refresh_from_db()
    assert report.awaiting_readiness == 1
    assert workspace.machine_generation == 2 and workspace.applied_images == NEW
    assert len(store.staged) == 1 and RuntimeCredential.objects.count() == 1


def test_duplicate_release_cannot_steal_live_claim(release_setup):
    workspace, provider, _ = release_setup
    workspace.activation_claim_token = "another-worker"
    workspace.activation_claim_expires_at = timezone.now() + timedelta(minutes=1)
    workspace.save()
    assert reconcile_workspace_release(workspace.id, provider=provider) == "busy"
    assert "destroy_machine" not in provider.calls


def test_invalid_digest_never_destroys_machine(release_setup, monkeypatch):
    workspace, provider, _ = release_setup
    monkeypatch.setenv("HERMES_IMAGE", "hermes:latest")
    with pytest.raises(ValueError, match="immutable"):
        reconcile_workspace_release(workspace.id, provider=provider)
    assert "destroy_machine" not in provider.calls


def test_resume_failure_is_attributable_without_secrets_and_continues(
    release_setup, monkeypatch, caplog
):
    from runtime.services import runtime_releases

    workspace, provider, _ = release_setup
    workspace.release_target = {"attempts": 4}
    workspace.save()
    other = Workspace.objects.create(
        tenant_ref="other-workspace", release_target={"attempts": 1}
    )
    calls = []

    def reconcile(workspace_id, **kwargs):
        calls.append(workspace_id)
        if workspace_id == workspace.id:
            raise RuntimeError("secret-credential-must-not-be-logged")
        return "awaiting_readiness"

    monkeypatch.setattr(runtime_releases, "reconcile_workspace_release", reconcile)
    report = runtime_releases.resume_runtime_releases(provider, limit=2)

    assert calls == [workspace.id, other.id]
    assert report.failed == 1
    assert report.awaiting_readiness == 1
    assert str(workspace.id) in caplog.text
    assert "RuntimeError" in caplog.text
    assert "secret-credential-must-not-be-logged" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_wrong_provider_image_remains_unavailable(release_setup):
    workspace, provider, _ = release_setup
    provider.wrong_image = True
    assert wake(workspace, provider).failed == 1
    workspace.refresh_from_db()
    assert workspace.release_target and workspace.provisioning_phase == "failed"
    assert not is_runtime_ready(workspace)


def test_canary_command_stops_at_readiness(release_setup, monkeypatch):
    workspace, provider, _ = release_setup
    monkeypatch.setattr(
        "runtime.management.commands.reconcile_runtime_images.runtime_power_provider",
        lambda: provider,
    )
    output = StringIO()
    call_command(
        "reconcile_runtime_images", workspace=workspace.tenant_ref, stdout=output
    )
    assert "awaiting_readiness" in output.getvalue()
    assert "readiness gate" in output.getvalue()

    output = StringIO()
    call_command(
        "reconcile_runtime_images", workspace=workspace.tenant_ref, stdout=output
    )
    assert "current" in output.getvalue()
    assert "readiness gate" in output.getvalue()


def test_batch_continues_past_current_sleeping_workspace(release_setup, monkeypatch):
    from runtime.management.commands import reconcile_runtime_images as command

    workspace, provider, _ = release_setup
    monkeypatch.setenv("HERMES_IMAGE", OLD["hermes"])
    monkeypatch.setenv("RUNTIME_IMAGE", OLD["allies-runtime"])
    monkeypatch.setattr(command, "runtime_power_provider", lambda: provider)
    other = Workspace.objects.create(
        tenant_ref="next-workspace",
        machine_generation=1,
        provisioning_phase="machine_created",
    )
    calls = []

    def reconcile(workspace_id, **kwargs):
        calls.append(workspace_id)
        if workspace_id == other.id:
            return "busy"
        return reconcile_workspace_release(workspace_id, **kwargs)

    monkeypatch.setattr(command, "reconcile_workspace_release", reconcile)
    output = StringIO()
    call_command("reconcile_runtime_images", batch=True, limit=2, stdout=output)
    assert set(calls) == {workspace.id, other.id}
    assert "current" in output.getvalue()
    assert "Next batch cursor:" in output.getvalue()
    assert "readiness gate" not in output.getvalue()


def queued_turn(workspace):
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="ally",
        hermes_profile_key="ally",
        lifecycle_state="active",
        materialized_generation=1,
    )
    return Execution.objects.create(
        workspace=workspace,
        profile=profile,
        idempotency_key="first-turn",
        input_payload={"message": "hello", "bootstrap": "greeting"},
        status="queued",
    )


def test_queued_message_and_profile_survive_upgrade(release_setup):
    workspace, provider, _ = release_setup
    execution = queued_turn(workspace)
    assert wake(workspace, provider).awaiting_readiness == 1
    execution.refresh_from_db()
    execution.profile.refresh_from_db()
    assert execution.status == "queued"
    assert execution.input_payload == {"message": "hello", "bootstrap": "greeting"}
    assert execution.profile.materialized_generation == 0
    assert execution.profile.hermes_profile_key == "ally"
    assert execution.attempts.count() == 0


@pytest.mark.parametrize("blocker", ["queued", "running", "lease"])
def test_active_workspace_work_blocks_operator_upgrade(release_setup, blocker):
    workspace, provider, store = release_setup
    provider.start_machine(workspace.fly_app_ref, workspace.machine_ref)
    execution = queued_turn(workspace)
    if blocker == "running":
        execution.status = "running"
        execution.save()
    if blocker == "lease":
        execution.status = "succeeded"
        execution.save()
        attempt = Attempt.objects.create(
            execution=execution, number=1, status="succeeded", machine_generation=1
        )
        Lease.objects.create(
            profile=execution.profile,
            attempt=attempt,
            machine_generation=1,
            token_digest="a" * 64,
            expires_at=timezone.now() - timedelta(seconds=1),
            state="stopping",
        )
    assert reconcile_workspace_release(workspace.id, provider=provider) == "busy"
    assert not store.staged and "destroy_machine" not in provider.calls


def test_fly_maps_image_pair_without_changing_machine_name():
    from runtime.providers.fly import _machine_record

    machine = _machine_record(
        {
            "id": "one",
            "name": "workspace-machine",
            "region": "ams",
            "state": "stopped",
            "config": {"containers": [{"name": n, "image": i} for n, i in NEW.items()]},
        },
        app_name="app",
    )
    assert machine.name == "workspace-machine"
    assert dict(machine.images) == NEW
