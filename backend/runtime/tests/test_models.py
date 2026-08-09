from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from runtime.exceptions import RuntimeConflictError, RuntimeValidationError
from runtime.models import (
    Attempt,
    Lease,
    LeaseState,
    RuntimeProfile,
    Workspace,
    WorkspaceProvisioningKind,
    WorkspaceProvisioningPhase,
)
from runtime.profile_keys import RESERVED_PROFILE_KEYS
from runtime.services.executions import create_execution
from runtime.services.leases import create_lease, digest_lease_token


def make_workspace(suffix="1"):
    return Workspace.objects.create(
        tenant_ref=f"tenant-{suffix}",
        fly_app_ref=f"app-{suffix}",
        volume_ref=f"volume-{suffix}",
        machine_ref=f"machine-{suffix}",
        machine_generation=1,
    )


@pytest.mark.django_db
def test_workspace_can_start_unprovisioned_with_null_provider_refs():
    workspace = Workspace.objects.create(tenant_ref="tenant-unprovisioned")

    assert workspace.machine_generation == 0
    assert workspace.fly_app_ref is None
    assert workspace.volume_ref is None
    assert workspace.machine_ref is None
    assert workspace.provisioning_phase == WorkspaceProvisioningPhase.IDLE


@pytest.mark.django_db
def test_workspace_idle_state_requires_all_refs_or_no_refs():
    with pytest.raises(IntegrityError), transaction.atomic():
        Workspace.objects.create(
            tenant_ref="tenant-partial-idle",
            fly_app_ref="app-partial",
            machine_generation=0,
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        Workspace.objects.create(
            tenant_ref="tenant-bound-missing-machine",
            fly_app_ref="app-bound",
            volume_ref="volume-bound",
            machine_generation=2,
        )


@pytest.mark.django_db
def test_workspace_allows_partial_provider_refs_during_non_idle_operation():
    workspace = Workspace.objects.create(
        tenant_ref="tenant-provisioning",
        fly_app_ref="app-provisioning",
        provisioning_id=uuid.uuid4(),
        provisioning_kind=WorkspaceProvisioningKind.ENSURE,
        provisioning_phase=WorkspaceProvisioningPhase.APP_READY,
        provisioning_target_generation=1,
        provisioning_machine_name="machine-1",
    )

    assert workspace.fly_app_ref == "app-provisioning"
    assert workspace.volume_ref is None
    assert workspace.machine_ref is None


@pytest.mark.django_db
def test_workspace_retains_failed_operation_state_for_explicit_repair():
    operation_id = uuid.uuid4()
    workspace = Workspace.objects.create(
        tenant_ref="tenant-stale-operation",
        fly_app_ref="app-stale",
        volume_ref="volume-stale",
        machine_generation=1,
        provisioning_id=operation_id,
        provisioning_kind=WorkspaceProvisioningKind.REPLACE,
        provisioning_phase=WorkspaceProvisioningPhase.FAILED,
        provisioning_source_generation=1,
        provisioning_target_generation=2,
        provisioning_previous_machine_ref="machine-old",
        provisioning_machine_name="machine-2",
    )

    workspace.refresh_from_db()
    assert workspace.provisioning_id == operation_id
    assert workspace.provisioning_phase == WorkspaceProvisioningPhase.FAILED
    assert workspace.machine_ref is None


@pytest.mark.django_db
def test_profile_identity_is_unique_within_a_workspace():
    workspace = make_workspace()
    RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="ally",
        hermes_profile_key="ally_key",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        RuntimeProfile.objects.create(
            workspace=workspace,
            ally_ref="ally",
            hermes_profile_key="other_key",
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        RuntimeProfile.objects.create(
            workspace=workspace,
            ally_ref="other-ally",
            hermes_profile_key="ally_key",
        )


@pytest.mark.django_db
def test_hermes_profile_key_is_immutable():
    workspace = make_workspace()
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="ally",
        hermes_profile_key="ally_key",
    )
    profile.hermes_profile_key = "new_key"
    with pytest.raises(RuntimeConflictError):
        profile.save()


@pytest.mark.django_db
def test_hermes_profile_key_queryset_updates_are_immutable():
    workspace = make_workspace()
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="ally",
        hermes_profile_key="ally_key",
    )

    with pytest.raises(RuntimeConflictError):
        RuntimeProfile.objects.filter(pk=profile.pk).update(
            hermes_profile_key="new_key",
        )
    profile.refresh_from_db()
    assert profile.hermes_profile_key == "ally_key"

    profile.hermes_profile_key = "new_key"
    with pytest.raises(RuntimeConflictError):
        RuntimeProfile.objects.bulk_update([profile], ["hermes_profile_key"])
    profile.refresh_from_db()
    assert profile.hermes_profile_key == "ally_key"

    RuntimeProfile.objects.filter(pk=profile.pk).update(ally_ref="updated-ally")
    profile.refresh_from_db()
    assert profile.ally_ref == "updated-ally"

    profile.ally_ref = "updated-again"
    RuntimeProfile.objects.bulk_update([profile], ["ally_ref"])
    profile.refresh_from_db()
    assert profile.ally_ref == "updated-again"


@pytest.mark.django_db
def test_hermes_profile_key_conflict_upserts_are_immutable():
    workspace = make_workspace()
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="ally",
        hermes_profile_key="ally_key",
    )

    with pytest.raises(RuntimeConflictError):
        RuntimeProfile.objects.bulk_create(
            [
                RuntimeProfile(
                    workspace=workspace,
                    ally_ref="ally",
                    hermes_profile_key="new_key",
                )
            ],
            update_conflicts=True,
            update_fields=["hermes_profile_key"],
            unique_fields=["workspace", "ally_ref"],
        )
    profile.refresh_from_db()
    assert profile.hermes_profile_key == "ally_key"

    RuntimeProfile.objects.bulk_create(
        [
            RuntimeProfile(
                workspace=workspace,
                ally_ref="updated-by-upsert",
                hermes_profile_key="ally_key",
            )
        ],
        update_conflicts=True,
        update_fields=["ally_ref"],
        unique_fields=["workspace", "hermes_profile_key"],
    )
    profile.refresh_from_db()
    assert profile.ally_ref == "updated-by-upsert"


@pytest.mark.django_db
def test_hermes_profile_key_base_manager_paths_are_immutable():
    workspace = make_workspace()
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="ally",
        hermes_profile_key="ally_key",
    )

    with pytest.raises(RuntimeConflictError):
        RuntimeProfile._base_manager.filter(pk=profile.pk).update(
            hermes_profile_key="new_key",
        )
    profile.refresh_from_db()
    assert profile.hermes_profile_key == "ally_key"

    profile.hermes_profile_key = "new_key"
    with pytest.raises(RuntimeConflictError):
        RuntimeProfile._base_manager.bulk_update([profile], ["hermes_profile_key"])
    profile.refresh_from_db()
    assert profile.hermes_profile_key == "ally_key"

    with pytest.raises(RuntimeConflictError):
        RuntimeProfile._base_manager.bulk_create(
            [
                RuntimeProfile(
                    workspace=workspace,
                    ally_ref="ally",
                    hermes_profile_key="new_key",
                )
            ],
            update_conflicts=True,
            update_fields=["hermes_profile_key"],
            unique_fields=["workspace", "ally_ref"],
        )
    profile.refresh_from_db()
    assert profile.hermes_profile_key == "ally_key"


@pytest.mark.parametrize(
    "invalid_key",
    [
        "UPPERCASE",
        "contains.period",
        "-leading",
        "",
        "a" * 65,
        *RESERVED_PROFILE_KEYS,
    ],
)
@pytest.mark.django_db
def test_hermes_profile_key_contract_rejects_invalid_and_reserved_values(invalid_key):
    workspace = make_workspace()
    with pytest.raises(RuntimeValidationError):
        RuntimeProfile.objects.create(
            workspace=workspace,
            ally_ref="ally",
            hermes_profile_key=invalid_key,
        )


@pytest.mark.django_db
def test_hermes_profile_key_database_constraint_catches_bulk_writes():
    workspace = make_workspace()
    with pytest.raises(IntegrityError), transaction.atomic():
        RuntimeProfile.objects.bulk_create(
            [
                RuntimeProfile(
                    workspace=workspace,
                    ally_ref="ally",
                    hermes_profile_key="UPPERCASE",
                )
            ]
        )


@pytest.mark.django_db
def test_hermes_profile_key_database_constraint_rejects_trailing_newline():
    workspace = make_workspace()
    with pytest.raises(IntegrityError), transaction.atomic():
        RuntimeProfile.objects.bulk_create(
            [
                RuntimeProfile(
                    workspace=workspace,
                    ally_ref="ally",
                    hermes_profile_key="valid\n",
                )
            ]
        )


@pytest.mark.django_db
def test_attempt_number_and_unresolved_lease_constraints():
    workspace = make_workspace()
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="ally",
        hermes_profile_key="ally_key",
    )
    execution = create_execution(workspace.id, profile.id, "request", {})
    attempt = Attempt.objects.create(
        execution=execution,
        number=1,
        machine_generation=1,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Attempt.objects.create(
            execution=execution,
            number=1,
            machine_generation=1,
        )
    create_lease(
        attempt.id,
        "token-1",
        timezone.now() + timedelta(minutes=1),
        1,
    )
    invalid_workspace = make_workspace("invalid-state")
    invalid_profile = RuntimeProfile.objects.create(
        workspace=invalid_workspace,
        ally_ref="ally",
        hermes_profile_key="invalid_state_ally",
    )
    invalid_execution = create_execution(
        invalid_workspace.id,
        invalid_profile.id,
        "invalid-state-request",
        {},
    )
    invalid_attempt = Attempt.objects.create(
        execution=invalid_execution,
        number=1,
        machine_generation=1,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Lease.objects.create(
            attempt=invalid_attempt,
            profile=invalid_profile,
            token_digest=digest_lease_token("invalid-state-token"),
            expires_at=timezone.now() + timedelta(minutes=1),
            machine_generation=1,
            state="invalid",
        )
    second_execution = create_execution(workspace.id, profile.id, "request-2", {})
    second_attempt = Attempt.objects.create(
        execution=second_execution,
        number=1,
        machine_generation=1,
    )
    with pytest.raises(RuntimeValidationError):
        Lease.objects.create(
            attempt=second_attempt,
            profile=profile,
            token_digest="raw-token",
            expires_at=timezone.now() + timedelta(minutes=1),
            machine_generation=1,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        Lease.objects.create(
            attempt=second_attempt,
            profile=profile,
            token_digest=digest_lease_token("token-2"),
            expires_at=timezone.now() + timedelta(minutes=1),
            machine_generation=1,
            state=LeaseState.STOPPING,
        )
