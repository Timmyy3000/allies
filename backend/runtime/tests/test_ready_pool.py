from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import override_settings
from django.utils import timezone

import runtime.services.ready_pool as ready_pool_service
from runtime.exceptions import RuntimeConflictError
from runtime.models import (
    ReadyWorkspaceBundle,
    ReadyWorkspaceBundleState,
    RuntimeCredential,
    RuntimeProfile,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.services.ready_pool import assign_ready_workspace
from runtime.services.workspaces import register_workspace

POOL_SETTINGS = {
    "READY_WORKSPACE_POOL_TARGET": 2,
    "READY_WORKSPACE_POOL_REGION": "ams",
    "READY_WORKSPACE_POOL_RELEASE_FINGERPRINT": "release-v1",
    "READY_WORKSPACE_POOL_CONFIG_VERSION": 1,
    "READY_WORKSPACE_POOL_MAX_PREPARING": 1,
    "READY_WORKSPACE_POOL_MAX_ATTEMPTS": 5,
    "READY_WORKSPACE_POOL_READY_TTL_SECONDS": 900,
    "READY_WORKSPACE_POOL_HEALTH_FRESHNESS_SECONDS": 60,
}


def create_ready_bundle(*, suffix: str = "1", now=None):
    now = now or timezone.now()
    workspace = Workspace.objects.create(
        tenant_ref=f"pool:{uuid4()}",
        fly_app_ref=f"app-{suffix}",
        volume_ref=f"volume-{suffix}",
        machine_ref=f"machine-{suffix}",
        machine_generation=1,
        runtime_start_epoch=1,
        ready_generation=1,
        ready_start_epoch=1,
        ready_boot_id=uuid4(),
        ready_at=now,
        runtime_last_seen_at=now,
        provisioning_phase=WorkspaceProvisioningPhase.IDLE,
    )
    RuntimeCredential.objects.create(
        workspace=workspace,
        token_digest=sha256(f"credential-{suffix}".encode()).hexdigest(),
        machine_generation=1,
    )
    bundle = ReadyWorkspaceBundle.objects.create(
        workspace=workspace,
        state=ReadyWorkspaceBundleState.READY,
        region="ams",
        release_fingerprint="release-v1",
        blank_volume_ref=workspace.volume_ref,
        config_version=1,
        next_attempt_at=now,
        ready_at=now,
        expires_at=now + timedelta(minutes=15),
        last_health_at=now,
    )
    return workspace, bundle


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_assignment_is_permanent_and_preserves_workspace_identity():
    workspace, bundle = create_ready_bundle()
    tenant_ref = str(uuid4())

    assigned = register_workspace(tenant_ref)

    assert assigned.id == workspace.id
    assert assigned.tenant_ref == tenant_ref
    assert assigned.fly_app_ref == "app-1"
    assert assigned.volume_ref == "volume-1"
    assert assigned.machine_ref == "machine-1"
    assert assigned.machine_generation == 1
    bundle.refresh_from_db()
    assert bundle.state == ReadyWorkspaceBundleState.ASSIGNED
    assert bundle.assigned_at is not None

    bundle.state = ReadyWorkspaceBundleState.READY
    with pytest.raises(RuntimeConflictError):
        bundle.save()


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_assigned_timestamp_constraint_rejects_direct_return_to_ready():
    _workspace, bundle = create_ready_bundle()

    assign_ready_workspace(str(uuid4()))

    with pytest.raises(IntegrityError), transaction.atomic():
        ReadyWorkspaceBundle.objects.filter(pk=bundle.pk).update(
            state=ReadyWorkspaceBundleState.READY
        )


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_same_tenant_replay_returns_existing_assignment_without_consuming_capacity():
    workspace, bundle = create_ready_bundle()
    tenant_ref = str(uuid4())

    first = register_workspace(tenant_ref)
    second = register_workspace(tenant_ref)

    assert first.id == second.id == workspace.id
    bundle.refresh_from_db()
    assert bundle.state == ReadyWorkspaceBundleState.ASSIGNED
    assert (
        ReadyWorkspaceBundle.objects.filter(
            state=ReadyWorkspaceBundleState.ASSIGNED
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_assignment_skips_claimed_candidate_for_next_eligible_bundle():
    now = timezone.now()
    claimed_workspace, claimed_bundle = create_ready_bundle(suffix="claimed", now=now)
    eligible_workspace, eligible_bundle = create_ready_bundle(
        suffix="eligible", now=now + timedelta(seconds=1)
    )
    ReadyWorkspaceBundle.objects.filter(pk=claimed_bundle.pk).update(
        phase_claim_owner="maintenance",
        phase_claim_until=now + timedelta(minutes=20),
    )

    assigned = register_workspace(str(uuid4()))

    assert assigned.id == eligible_workspace.id
    claimed_workspace.refresh_from_db()
    claimed_bundle.refresh_from_db()
    eligible_bundle.refresh_from_db()
    assert claimed_workspace.tenant_ref.startswith("pool:")
    assert claimed_bundle.state == ReadyWorkspaceBundleState.READY
    assert eligible_bundle.state == ReadyWorkspaceBundleState.ASSIGNED


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_assignment_marks_stale_candidate_and_uses_next_eligible_bundle():
    now = timezone.now()
    stale_workspace, stale_bundle = create_ready_bundle(suffix="stale", now=now)
    eligible_workspace, eligible_bundle = create_ready_bundle(
        suffix="eligible", now=now + timedelta(seconds=1)
    )
    ReadyWorkspaceBundle.objects.filter(pk=stale_bundle.pk).update(
        expires_at=now - timedelta(seconds=1)
    )

    assigned = register_workspace(str(uuid4()))

    assert assigned.id == eligible_workspace.id
    stale_workspace.refresh_from_db()
    stale_bundle.refresh_from_db()
    eligible_bundle.refresh_from_db()
    assert stale_workspace.tenant_ref.startswith("pool:")
    assert stale_bundle.state == ReadyWorkspaceBundleState.EVICTING
    assert stale_bundle.safe_error_code == "stale_candidate"
    assert eligible_bundle.state == ReadyWorkspaceBundleState.ASSIGNED


@pytest.mark.django_db(transaction=True)
@override_settings(**{**POOL_SETTINGS, "READY_WORKSPACE_POOL_TARGET": 0})
def test_target_zero_uses_normal_registration_path():
    workspace, bundle = create_ready_bundle()

    registered = register_workspace(str(uuid4()))

    assert registered.id != workspace.id
    bundle.refresh_from_db()
    assert bundle.state == ReadyWorkspaceBundleState.READY


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_reserved_pool_reference_cannot_claim_a_bundle():
    workspace, bundle = create_ready_bundle()

    assert assign_ready_workspace(f"pool:{uuid4()}") is None
    workspace.refresh_from_db()
    bundle.refresh_from_db()
    assert workspace.tenant_ref.startswith("pool:")
    assert bundle.state == ReadyWorkspaceBundleState.READY


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
@pytest.mark.parametrize(
    "change",
    [
        lambda now: {"expires_at": now - timedelta(seconds=1)},
        lambda now: {"last_health_at": now - timedelta(seconds=61)},
        lambda now: {"release_fingerprint": "old-release"},
        lambda now: {"config_version": 2},
        lambda now: {"blank_volume_ref": None},
        lambda now: {"blank_volume_ref": "different-volume"},
    ],
)
def test_stale_candidate_falls_back_and_is_marked_for_eviction(change):
    now = timezone.now()
    workspace, bundle = create_ready_bundle(now=now)
    ReadyWorkspaceBundle.objects.filter(pk=bundle.pk).update(**change(now))

    registered = register_workspace(str(uuid4()))

    assert registered.id != workspace.id
    bundle.refresh_from_db()
    assert bundle.state == ReadyWorkspaceBundleState.EVICTING
    assert bundle.safe_error_code == "stale_candidate"


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_eviction_marker_failure_keeps_cold_fallback_available(monkeypatch):
    workspace, bundle = create_ready_bundle()
    ReadyWorkspaceBundle.objects.filter(pk=bundle.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    def fail_marker(*_args, **_kwargs):
        raise RuntimeConflictError("marker raced")

    monkeypatch.setattr(
        ready_pool_service,
        "_mark_candidate_evicting",
        fail_marker,
    )

    registered = register_workspace(str(uuid4()))

    assert registered.id != workspace.id
    bundle.refresh_from_db()
    assert bundle.state == ReadyWorkspaceBundleState.READY


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_profile_or_execution_data_disqualifies_a_bundle():
    workspace, bundle = create_ready_bundle()
    RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="existing-ally",
        hermes_profile_key="existing_ally",
    )

    registered = register_workspace(str(uuid4()))

    assert registered.id != workspace.id
    bundle.refresh_from_db()
    assert bundle.state == ReadyWorkspaceBundleState.EVICTING


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_duplicate_current_generation_credentials_disqualify_a_bundle():
    workspace, bundle = create_ready_bundle()
    RuntimeCredential.objects.create(
        workspace=workspace,
        token_digest=sha256(b"duplicate-credential").hexdigest(),
        machine_generation=workspace.machine_generation,
    )

    registered = register_workspace(str(uuid4()))

    assert registered.id != workspace.id
    bundle.refresh_from_db()
    assert bundle.state == ReadyWorkspaceBundleState.EVICTING


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_activation_claim_disqualifies_a_bundle():
    workspace, bundle = create_ready_bundle()
    Workspace.objects.filter(pk=workspace.pk).update(
        activation_claim_token="active-claim"
    )

    registered = register_workspace(str(uuid4()))

    assert registered.id != workspace.id
    bundle.refresh_from_db()
    assert bundle.state == ReadyWorkspaceBundleState.EVICTING


@pytest.mark.django_db(transaction=True)
def test_bundle_database_bounds_reject_invalid_attempts_and_assignment_state():
    workspace, _ = create_ready_bundle()
    with pytest.raises(IntegrityError), transaction.atomic():
        ReadyWorkspaceBundle.objects.bulk_create(
            [
                ReadyWorkspaceBundle(
                    workspace=workspace,
                    state=ReadyWorkspaceBundleState.PREPARING,
                    region="ams",
                    release_fingerprint="release-v1",
                    attempt_count=6,
                )
            ]
        )

    other_workspace = Workspace.objects.create(tenant_ref=f"pool:{uuid4()}")
    with pytest.raises(IntegrityError), transaction.atomic():
        ReadyWorkspaceBundle.objects.bulk_create(
            [
                ReadyWorkspaceBundle(
                    workspace=other_workspace,
                    state=ReadyWorkspaceBundleState.ASSIGNED,
                    region="ams",
                    release_fingerprint="release-v1",
                )
            ]
        )


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_failed_assignment_transaction_leaves_bundle_ready():
    workspace, bundle = create_ready_bundle()
    tenant_ref = str(uuid4())

    with pytest.raises(RuntimeError), transaction.atomic():
        assigned = register_workspace(tenant_ref)
        assert assigned.id == workspace.id
        raise RuntimeError("simulated pre-commit failure")

    workspace.refresh_from_db()
    bundle.refresh_from_db()
    assert workspace.tenant_ref.startswith("pool:")
    assert bundle.state == ReadyWorkspaceBundleState.READY


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_post_commit_replay_is_idempotently_discoverable():
    tenant_ref = str(uuid4())
    workspace, bundle = create_ready_bundle()

    assigned = register_workspace(tenant_ref)
    replay = register_workspace(tenant_ref)

    assert assigned.id == replay.id == workspace.id
    bundle.refresh_from_db()
    assert bundle.state == ReadyWorkspaceBundleState.ASSIGNED


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_postgresql_concurrent_different_tenants_get_distinct_bundles(monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row-lock semantics")
    create_ready_bundle(suffix="1")
    create_ready_bundle(suffix="2")
    tenants = [str(uuid4()), str(uuid4())]
    barrier = Barrier(2)
    eligible = ready_pool_service._eligible

    def gated_eligible(*args, **kwargs):
        result = eligible(*args, **kwargs)
        if result:
            barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(ready_pool_service, "_eligible", gated_eligible)

    def register(tenant_ref):
        close_old_connections()
        try:
            return register_workspace(tenant_ref)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as workers:
        assigned = list(workers.map(register, tenants))

    assert len({item.id for item in assigned}) == 2
    assert (
        ReadyWorkspaceBundle.objects.filter(
            state=ReadyWorkspaceBundleState.ASSIGNED
        ).count()
        == 2
    )


@pytest.mark.django_db(transaction=True)
@override_settings(**POOL_SETTINGS)
def test_postgresql_same_tenant_race_consumes_at_most_one_bundle(monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row-lock semantics")
    create_ready_bundle(suffix="1")
    create_ready_bundle(suffix="2")
    tenant_ref = str(uuid4())
    barrier = Barrier(2)
    eligible = ready_pool_service._eligible

    def gated_eligible(*args, **kwargs):
        result = eligible(*args, **kwargs)
        if result:
            barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(ready_pool_service, "_eligible", gated_eligible)

    def register():
        close_old_connections()
        try:
            return register_workspace(tenant_ref)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as workers:
        assigned = list(workers.map(lambda _: register(), range(2)))

    assert assigned[0].id == assigned[1].id
    assert (
        ReadyWorkspaceBundle.objects.filter(
            state=ReadyWorkspaceBundleState.ASSIGNED
        ).count()
        == 1
    )
