from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from threading import Event, Thread
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection
from django.test import override_settings
from django.utils import timezone

from runtime.exceptions import RuntimeValidationError
from runtime.models import (
    ReadyWorkspaceBundle,
    ReadyWorkspaceBundleState,
    RuntimeCredential,
    RuntimeOperationState,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.providers import ProviderRetryableError
from runtime.services import ready_pool_maintenance
from runtime.services.ready_pool_maintenance import (
    PoolProviderSnapshot,
    PoolReadinessPending,
    _Claim,
    _pool_config,
    _record_fresh_blank_volume,
    _run_cleanup,
    _run_park,
    maintain_ready_pool_once,
    pool_config_fingerprint,
)

POOL_IMAGES = {
    "hermes": "registry.example/hermes@sha256:" + "a" * 64,
    "allies-runtime": "registry.example/runtime@sha256:" + "b" * 64,
}
POOL_SETTINGS = {
    "READY_WORKSPACE_POOL_TARGET": 1,
    "READY_WORKSPACE_POOL_REGION": "ams",
    "READY_WORKSPACE_POOL_RELEASE_FINGERPRINT": pool_config_fingerprint(
        region="ams",
        images=POOL_IMAGES,
        containers=tuple(POOL_IMAGES),
    ),
    "READY_WORKSPACE_POOL_CONFIG_VERSION": 1,
    "READY_WORKSPACE_POOL_MAX_PREPARING": 1,
    "READY_WORKSPACE_POOL_MAX_ATTEMPTS": 5,
    "READY_WORKSPACE_POOL_READY_TTL_SECONDS": 900,
    "READY_WORKSPACE_POOL_HEALTH_FRESHNESS_SECONDS": 60,
    "READY_WORKSPACE_POOL_PHASE_CLAIM_SECONDS": 60,
}


class FakePoolAdapter:
    def __init__(self, *, behavior: str = "ready") -> None:
        self.behavior = behavior
        self.activations: list[str] = []
        self.inspections = 0
        self.cleanups: list[str] = []
        self.parks: list[str] = []
        self.machine_state = "started"

    def activate(self, workspace_id):
        self.activations.append(str(workspace_id))
        if self.behavior == "pending":
            raise PoolReadinessPending()
        if self.behavior == "retry":
            raise ProviderRetryableError("provider is busy")
        workspace = Workspace.objects.get(pk=workspace_id)
        operation_id = uuid4()
        observed_at = timezone.now()
        Workspace.objects.filter(pk=workspace_id).update(
            fly_app_ref=f"app-{workspace.id.hex}",
            volume_ref=f"volume-{workspace.id.hex}",
            machine_ref=f"machine-{workspace.id.hex}",
            machine_generation=1,
            runtime_start_epoch=1,
            ready_generation=1,
            ready_start_epoch=1,
            ready_boot_id=uuid4(),
            ready_at=observed_at,
            runtime_last_seen_at=observed_at,
            provisioning_id=operation_id,
            provisioning_phase=WorkspaceProvisioningPhase.IDLE,
            applied_images=POOL_IMAGES,
        )
        RuntimeCredential.objects.create(
            workspace_id=workspace_id,
            token_digest=sha256(str(workspace_id).encode()).hexdigest(),
            machine_generation=1,
        )

    def inspect(self, workspace):
        self.inspections += 1
        bundle = ReadyWorkspaceBundle.objects.get(workspace_id=workspace.id)
        return PoolProviderSnapshot(
            app_ref=workspace.fly_app_ref,
            volume_ref=workspace.volume_ref,
            machine_ref=workspace.machine_ref,
            region=bundle.region,
            machine_state=self.machine_state,
            health_containers={"hermes": "started", "allies-runtime": "started"},
            ownership_workspace_id=workspace.id,
            ownership_operation_id=workspace.provisioning_id,
            ownership_generation=workspace.machine_generation,
            volume_attached_machine_ref=workspace.machine_ref,
            images=POOL_IMAGES,
            config_fingerprint=pool_config_fingerprint(
                region=bundle.region,
                images=POOL_IMAGES,
                containers=tuple(POOL_IMAGES),
            ),
            cpu_kind="shared",
            cpus=2,
            memory_mb=2048,
            volume_size_gb=10,
            blank=True,
        )

    def cleanup(self, workspace):
        self.cleanups.append(str(workspace.id))
        RuntimeCredential.objects.filter(workspace_id=workspace.id).update(
            revoked_at=timezone.now()
        )
        return True

    def park(self, workspace):
        self.parks.append(str(workspace.id))
        self.machine_state = "stopped"
        return True


class FakeClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


class SlowPoolAdapter(FakePoolAdapter):
    def __init__(self, clock):
        super().__init__()
        self.clock = clock

    def activate(self, workspace_id):
        self.clock.advance(901)
        super().activate(workspace_id)
        Workspace.objects.filter(pk=workspace_id).update(
            ready_at=self.clock(),
            runtime_last_seen_at=self.clock(),
        )


class PendingFreshVolumeAdapter(FakePoolAdapter):
    def activate(self, workspace_id):
        self.activations.append(str(workspace_id))
        workspace = Workspace.objects.get(pk=workspace_id)
        operation_id = uuid4()
        Workspace.objects.filter(pk=workspace_id).update(
            fly_app_ref=f"app-{workspace.id.hex}",
            volume_ref=f"volume-{workspace.id.hex}",
            machine_ref=f"machine-{workspace.id.hex}",
            machine_generation=1,
            provisioning_id=operation_id,
            provisioning_phase=WorkspaceProvisioningPhase.IDLE,
            runtime_operation_state=RuntimeOperationState.AWAITING_READINESS,
            applied_images=POOL_IMAGES,
        )
        RuntimeCredential.objects.create(
            workspace_id=workspace_id,
            token_digest=sha256(str(workspace_id).encode()).hexdigest(),
            machine_generation=1,
        )
        raise PoolReadinessPending()

    def record_fresh_volume(self, workspace):
        return workspace.volume_ref


@pytest.mark.django_db(transaction=True)
@override_settings(**{**POOL_SETTINGS, "READY_WORKSPACE_POOL_TARGET": 0})
def test_target_zero_is_a_creation_gate():
    adapter = FakePoolAdapter()

    result = maintain_ready_pool_once(adapter=adapter)

    assert result.disabled
    assert adapter.activations == []
    assert not ReadyWorkspaceBundle.objects.exists()


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_target_zero_drain_evicts_a_fresh_ready_bundle():
    now = timezone.now()
    adapter = FakePoolAdapter()
    maintain_ready_pool_once(adapter=adapter, now=now)

    with override_settings(READY_WORKSPACE_POOL_TARGET=0):
        result = maintain_ready_pool_once(
            adapter=adapter,
            now=now + timedelta(seconds=1),
            drain=True,
        )

    bundle = ReadyWorkspaceBundle.objects.get()
    assert result.evicted == 1
    assert bundle.state == ReadyWorkspaceBundleState.EVICTED
    assert adapter.cleanups == [str(bundle.workspace_id)]


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_first_pass_prepares_and_promotes_one_complete_bundle():
    now = timezone.now()
    adapter = FakePoolAdapter()

    result = maintain_ready_pool_once(adapter=adapter, now=now)

    bundle = ReadyWorkspaceBundle.objects.get()
    assert result.created == 1
    assert result.ready == 1
    assert bundle.state == ReadyWorkspaceBundleState.READY
    assert bundle.blank_volume_ref == bundle.workspace.volume_ref
    assert bundle.phase_claim_owner is None
    assert adapter.activations == [str(bundle.workspace_id)]


@pytest.mark.django_db(transaction=True)
@override_settings(**{**POOL_SETTINGS, "READY_WORKSPACE_POOL_SLEEP_ENABLED": True})
def test_sleeping_pool_parks_once_and_refreshes_without_activation_churn():
    now = timezone.now()
    adapter = FakePoolAdapter()

    first = maintain_ready_pool_once(adapter=adapter, now=now)
    second = maintain_ready_pool_once(adapter=adapter, now=now + timedelta(seconds=1))
    bundle = ReadyWorkspaceBundle.objects.get()

    assert first.ready == 1
    assert second.refreshed == 1
    assert bundle.state == ReadyWorkspaceBundleState.SLEEPING
    assert len(adapter.activations) == 1
    assert adapter.parks == [str(bundle.workspace_id)]
    Workspace.objects.filter(pk=bundle.workspace_id).update(
        ready_generation=None,
        ready_start_epoch=None,
        ready_boot_id=None,
        ready_at=None,
        runtime_last_seen_at=None,
    )

    third = maintain_ready_pool_once(
        adapter=adapter,
        now=now + timedelta(minutes=35),
    )

    bundle.refresh_from_db()
    assert third.refreshed == 1
    assert bundle.state == ReadyWorkspaceBundleState.SLEEPING
    assert len(adapter.activations) == 1
    assert len(adapter.parks) == 1

    fourth = maintain_ready_pool_once(
        adapter=adapter,
        now=now + timedelta(minutes=36),
    )

    bundle.refresh_from_db()
    assert fourth.refreshed == 1
    assert bundle.state == ReadyWorkspaceBundleState.SLEEPING
    assert len(adapter.activations) == 1
    assert len(adapter.parks) == 1


@pytest.mark.django_db(transaction=True)
@override_settings(**{**POOL_SETTINGS, "READY_WORKSPACE_POOL_SLEEP_ENABLED": True})
def test_sleeping_inspection_of_running_machine_parks_without_reactivation():
    now = timezone.now()
    adapter = FakePoolAdapter()
    maintain_ready_pool_once(adapter=adapter, now=now)
    maintain_ready_pool_once(adapter=adapter, now=now + timedelta(seconds=1))
    adapter.machine_state = "started"

    result = maintain_ready_pool_once(
        adapter=adapter,
        now=now + timedelta(seconds=61),
    )

    bundle = ReadyWorkspaceBundle.objects.get()
    assert result.refreshed == 1
    assert bundle.state == ReadyWorkspaceBundleState.SLEEPING
    assert len(adapter.activations) == 1
    assert len(adapter.parks) == 2


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_pending_fresh_volume_proof_survives_adapter_recreation():
    now = timezone.now()
    first_adapter = PendingFreshVolumeAdapter()

    first = maintain_ready_pool_once(adapter=first_adapter, now=now)

    bundle = ReadyWorkspaceBundle.objects.get()
    workspace = Workspace.objects.get(pk=bundle.workspace_id)
    assert first.skipped == 1
    assert bundle.state == ReadyWorkspaceBundleState.PREPARING
    assert bundle.blank_volume_ref == workspace.volume_ref

    resumed_at = now + timedelta(seconds=2)
    Workspace.objects.filter(pk=workspace.pk).update(
        ready_generation=1,
        ready_start_epoch=1,
        ready_boot_id=uuid4(),
        ready_at=resumed_at,
        runtime_last_seen_at=resumed_at,
        runtime_start_epoch=1,
        runtime_operation_id=None,
        runtime_operation_state=RuntimeOperationState.IDLE,
    )

    class ResumeAdapter(FakePoolAdapter):
        def activate(self, workspace_id):
            self.activations.append(str(workspace_id))

    second_adapter = ResumeAdapter()
    second = maintain_ready_pool_once(adapter=second_adapter, now=resumed_at)

    bundle.refresh_from_db()
    assert second.ready == 1
    assert bundle.state == ReadyWorkspaceBundleState.READY
    assert bundle.blank_volume_ref == workspace.volume_ref
    assert second_adapter.activations == [str(workspace.id)]


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_expired_phase_claim_cannot_record_fresh_volume_proof():
    now = timezone.now()
    adapter = PendingFreshVolumeAdapter()
    maintain_ready_pool_once(adapter=adapter, now=now)
    bundle = ReadyWorkspaceBundle.objects.get()
    workspace = Workspace.objects.get(pk=bundle.workspace_id)
    ReadyWorkspaceBundle.objects.filter(pk=bundle.pk).update(
        blank_volume_ref=None,
        phase_claim_owner="expired-worker",
        phase_claim_until=now - timedelta(seconds=1),
    )

    claim = _Claim(
        bundle.id,
        workspace.id,
        "expired-worker",
        "prepare",
    )
    assert not _record_fresh_blank_volume(
        claim, workspace.id, workspace.volume_ref, now
    )
    bundle.refresh_from_db()
    assert bundle.blank_volume_ref is None


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_slow_activation_uses_completion_time_for_ready_expiry():
    started_at = timezone.now()
    clock = FakeClock(started_at)
    adapter = SlowPoolAdapter(clock)

    result = maintain_ready_pool_once(adapter=adapter, clock=clock)

    bundle = ReadyWorkspaceBundle.objects.get()
    assert result.ready == 1
    assert bundle.ready_at == clock()
    assert bundle.expires_at == clock() + timedelta(seconds=900)
    assert bundle.expires_at > started_at + timedelta(seconds=900)


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_healthy_bundle_is_not_rechecked_before_due_time():
    now = timezone.now()
    adapter = FakePoolAdapter()
    maintain_ready_pool_once(adapter=adapter, now=now)

    result = maintain_ready_pool_once(adapter=adapter, now=now + timedelta(seconds=2))

    assert result.created == 0
    assert result.refreshed == 0
    assert adapter.inspections == 1


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_stale_health_timestamp_is_revalidated_before_eviction():
    now = timezone.now()
    adapter = FakePoolAdapter()
    maintain_ready_pool_once(adapter=adapter, now=now)
    Workspace.objects.filter(pk=ReadyWorkspaceBundle.objects.get().workspace_id).update(
        runtime_last_seen_at=now + timedelta(seconds=61)
    )

    result = maintain_ready_pool_once(adapter=adapter, now=now + timedelta(seconds=61))

    bundle = ReadyWorkspaceBundle.objects.get()
    assert result.refreshed == 1
    assert bundle.state == ReadyWorkspaceBundleState.READY
    assert adapter.inspections == 2


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_expired_ready_health_claim_is_reclaimed():
    now = timezone.now()
    adapter = FakePoolAdapter()
    maintain_ready_pool_once(adapter=adapter, now=now)
    bundle = ReadyWorkspaceBundle.objects.get()
    ReadyWorkspaceBundle.objects.filter(pk=bundle.pk).update(
        phase_claim_owner="expired-worker",
        phase_claim_until=now - timedelta(seconds=1),
        next_attempt_at=now,
    )

    result = maintain_ready_pool_once(adapter=adapter, now=now)

    bundle.refresh_from_db()
    assert result.refreshed == 1
    assert bundle.state == ReadyWorkspaceBundleState.READY
    assert bundle.phase_claim_owner is None
    assert adapter.inspections == 2


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_readiness_pending_resumes_without_consuming_attempt_budget():
    now = timezone.now()
    adapter = FakePoolAdapter(behavior="pending")

    maintain_ready_pool_once(adapter=adapter, now=now)
    bundle = ReadyWorkspaceBundle.objects.get()
    bundle.refresh_from_db()

    assert bundle.state == ReadyWorkspaceBundleState.PREPARING
    assert bundle.attempt_count == 0
    assert bundle.safe_error_code == "readiness_pending"


@pytest.mark.django_db(transaction=True)
@override_settings(**{**POOL_SETTINGS, "READY_WORKSPACE_POOL_MAX_ATTEMPTS": 2})
def test_exhausted_resource_free_failure_does_not_block_next_capacity():
    now = timezone.now()
    adapter = FakePoolAdapter(behavior="retry")

    maintain_ready_pool_once(adapter=adapter, now=now)
    maintain_ready_pool_once(adapter=adapter, now=now + timedelta(seconds=2))
    failed = ReadyWorkspaceBundle.objects.get()
    assert failed.state == ReadyWorkspaceBundleState.FAILED
    assert failed.attempt_count == 2

    replacement = FakePoolAdapter()
    maintain_ready_pool_once(adapter=replacement, now=now + timedelta(seconds=4))

    assert (
        ReadyWorkspaceBundle.objects.filter(
            state=ReadyWorkspaceBundleState.READY
        ).count()
        == 1
    )
    assert len(replacement.activations) == 1


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_expired_bundle_is_cleaned_and_becomes_evicted():
    now = timezone.now()
    adapter = FakePoolAdapter()
    maintain_ready_pool_once(adapter=adapter, now=now)
    bundle = ReadyWorkspaceBundle.objects.get()
    ReadyWorkspaceBundle.objects.filter(pk=bundle.pk).update(
        expires_at=now - timedelta(seconds=1),
        next_attempt_at=now,
    )

    result = maintain_ready_pool_once(adapter=adapter, now=now)

    bundle.refresh_from_db()
    assert result.evicted == 1
    assert bundle.state == ReadyWorkspaceBundleState.EVICTED
    assert adapter.cleanups == [str(bundle.workspace_id)]


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_nonreserved_cleanup_row_stays_visible_without_provider_io():
    workspace = Workspace.objects.create(tenant_ref=str(uuid4()))
    bundle = ReadyWorkspaceBundle.objects.create(
        workspace=workspace,
        state=ReadyWorkspaceBundleState.EVICTING,
        region="ams",
        release_fingerprint=POOL_SETTINGS["READY_WORKSPACE_POOL_RELEASE_FINGERPRINT"],
        config_version=1,
        next_attempt_at=timezone.now(),
    )
    adapter = FakePoolAdapter()

    maintain_ready_pool_once(adapter=adapter)

    bundle.refresh_from_db()
    assert bundle.state == ReadyWorkspaceBundleState.EVICTING
    assert adapter.cleanups == []

    maintain_ready_pool_once(adapter=adapter)

    bundle.refresh_from_db()
    assert bundle.state == ReadyWorkspaceBundleState.EVICTING
    assert adapter.cleanups == []


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_late_completion_cannot_promote_a_fenced_claim():
    class FencedAdapter(FakePoolAdapter):
        def inspect(self, workspace):
            snapshot = super().inspect(workspace)
            bundle = ReadyWorkspaceBundle.objects.get(workspace_id=workspace.id)
            ReadyWorkspaceBundle.objects.filter(pk=bundle.pk).update(
                phase_claim_owner="other-owner",
                phase_claim_until=timezone.now() + timedelta(minutes=20),
            )
            return snapshot

    adapter = FencedAdapter()

    maintain_ready_pool_once(adapter=adapter)

    assert (
        ReadyWorkspaceBundle.objects.get().state == ReadyWorkspaceBundleState.PREPARING
    )


@pytest.mark.django_db(transaction=True)
@override_settings(**{**POOL_SETTINGS, "READY_WORKSPACE_POOL_SLEEP_ENABLED": True})
def test_expired_parking_claim_cannot_stop_a_reassigned_row():
    now = timezone.now()
    adapter = FakePoolAdapter()
    maintain_ready_pool_once(adapter=adapter, now=now)
    bundle = ReadyWorkspaceBundle.objects.get()
    workspace = Workspace.objects.get(pk=bundle.workspace_id)
    ReadyWorkspaceBundle.objects.filter(pk=bundle.pk).update(
        state=ReadyWorkspaceBundleState.PARKING,
        phase_claim_owner="expired-worker",
        phase_claim_until=now - timedelta(seconds=1),
    )

    claim = _Claim(bundle.id, workspace.id, "expired-worker", "park")
    assert _run_park(claim, workspace, adapter, _pool_config(), lambda: now) == (
        "skipped"
    )
    assert adapter.parks == []


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_expired_cleanup_claim_cannot_delete_after_reassignment(monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row-lock semantics")
    now = timezone.now()
    workspace = Workspace.objects.create(tenant_ref=f"pool:{uuid4()}")
    bundle = ReadyWorkspaceBundle.objects.create(
        workspace=workspace,
        state=ReadyWorkspaceBundleState.EVICTING,
        region="ams",
        release_fingerprint=POOL_SETTINGS["READY_WORKSPACE_POOL_RELEASE_FINGERPRINT"],
        config_version=1,
        next_attempt_at=now,
        phase_claim_owner="old-worker",
        phase_claim_until=now + timedelta(minutes=5),
    )
    claim = _Claim(bundle.id, workspace.id, "old-worker", "cleanup")
    adapter = FakePoolAdapter()
    paused = Event()
    resume = Event()
    original = ready_pool_maintenance._cleanup_side_effect_allowed

    def pause_before_cleanup_side_effect(claim, observed_at):
        paused.set()
        assert resume.wait(timeout=5)
        return original(claim, observed_at)

    monkeypatch.setattr(
        ready_pool_maintenance,
        "_cleanup_side_effect_allowed",
        pause_before_cleanup_side_effect,
    )
    result_holder = []
    error_holder = []

    def run_cleanup():
        close_old_connections()
        try:
            result_holder.append(
                _run_cleanup(
                    claim,
                    workspace,
                    adapter,
                    _pool_config(),
                    now,
                    lambda: now,
                )
            )
        except Exception as exc:  # noqa: BLE001 - report worker failures below
            error_holder.append(exc)
        finally:
            connection.close()

    worker = Thread(target=run_cleanup)
    worker.start()
    assert paused.wait(timeout=5)
    ReadyWorkspaceBundle.objects.filter(pk=bundle.pk).update(
        phase_claim_owner="new-worker",
        phase_claim_until=now + timedelta(minutes=5),
    )
    resume.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert error_holder == []
    assert result_holder == ["skipped"]
    assert adapter.cleanups == []
    bundle.refresh_from_db()
    assert bundle.phase_claim_owner == "new-worker"


def test_pool_fingerprint_changes_with_region_images_and_topology():
    baseline = pool_config_fingerprint(
        region="ams", images=POOL_IMAGES, containers=tuple(POOL_IMAGES)
    )
    assert baseline != pool_config_fingerprint(
        region="fra", images=POOL_IMAGES, containers=tuple(POOL_IMAGES)
    )
    assert baseline != pool_config_fingerprint(
        region="ams",
        images={**POOL_IMAGES, "extra": POOL_IMAGES["hermes"]},
        containers=tuple(POOL_IMAGES) + ("extra",),
    )


def test_maintenance_limit_is_bounded():
    with pytest.raises(RuntimeValidationError):
        maintain_ready_pool_once(limit=0)
