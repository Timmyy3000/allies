from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from allies.models import Ally, AllyBinding, ProvisioningOperation, ProvisioningStatus
from auths.models import User
from workspaces.models import Workspace


@pytest.fixture
def rejected_operation(db):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Recovery")
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study partner",
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    binding = AllyBinding.objects.create(ally=ally)
    return ProvisioningOperation.objects.create(
        binding=binding,
        workspace=workspace,
        user=user,
        api_idempotency_key_digest="a" * 64,
        content_fingerprint="b" * 64,
        status=ProvisioningStatus.REPAIR_REQUIRED,
        safe_error_code="foundry_rejected",
        attempt_count=3,
        lease_expires_at=timezone.now() + timedelta(minutes=1),
        last_attempt_at=timezone.now(),
        completed_at=timezone.now(),
        readiness_hint_received_at=timezone.now() - timedelta(hours=2),
        expires_at=timezone.now() + timedelta(hours=1),
    )


@pytest.mark.django_db
def test_recovery_is_dry_run_by_default(rejected_operation, capsys):
    call_command(
        "recover_foundry_provisioning",
        workspace_id=str(rejected_operation.workspace_id),
    )

    rejected_operation.refresh_from_db()
    assert rejected_operation.status == ProvisioningStatus.REPAIR_REQUIRED
    assert "matched=1 requeued=0" in capsys.readouterr().out


@pytest.mark.django_db
def test_confirm_requeues_once_without_changing_identity(rejected_operation, capsys):
    original = {
        "id": rejected_operation.id,
        "binding_id": rejected_operation.binding_id,
        "attempt_count": rejected_operation.attempt_count,
        "fingerprint": rejected_operation.content_fingerprint,
    }
    arguments = {
        "workspace_id": str(rejected_operation.workspace_id),
        "operation_id": str(rejected_operation.id),
        "confirm": True,
    }

    call_command("recover_foundry_provisioning", **arguments)
    rejected_operation.refresh_from_db()

    assert rejected_operation.status == ProvisioningStatus.RETRYABLE
    assert rejected_operation.safe_error_code == ""
    assert rejected_operation.completed_at is None
    assert rejected_operation.lease_expires_at is None
    assert rejected_operation.last_attempt_at is None
    assert rejected_operation.readiness_hint_received_at is None
    assert rejected_operation.expires_at > timezone.now()
    assert rejected_operation.id == original["id"]
    assert rejected_operation.binding_id == original["binding_id"]
    assert rejected_operation.attempt_count == original["attempt_count"]
    assert rejected_operation.content_fingerprint == original["fingerprint"]

    call_command("recover_foundry_provisioning", **arguments)
    rejected_operation.refresh_from_db()
    assert rejected_operation.status == ProvisioningStatus.RETRYABLE
    assert "matched=0 requeued=0" in capsys.readouterr().out


@pytest.mark.django_db
def test_recovery_excludes_other_repair_reasons(rejected_operation, capsys):
    rejected_operation.safe_error_code = "stored_ally_invalid"
    rejected_operation.save(update_fields=("safe_error_code", "updated_at"))

    call_command(
        "recover_foundry_provisioning",
        workspace_id=str(rejected_operation.workspace_id),
        confirm=True,
    )

    rejected_operation.refresh_from_db()
    assert rejected_operation.status == ProvisioningStatus.REPAIR_REQUIRED
    assert "matched=0 requeued=0" in capsys.readouterr().out


@pytest.mark.django_db
def test_confirm_renews_expired_operation_for_dispatch(rejected_operation):
    rejected_operation.expires_at = timezone.now() - timedelta(days=1)
    rejected_operation.save(update_fields=("expires_at", "updated_at"))

    call_command(
        "recover_foundry_provisioning",
        workspace_id=str(rejected_operation.workspace_id),
        confirm=True,
    )

    rejected_operation.refresh_from_db()
    assert rejected_operation.status == ProvisioningStatus.RETRYABLE
    assert rejected_operation.expires_at > timezone.now()


@pytest.mark.django_db
def test_recovery_excludes_cross_workspace_binding(rejected_operation, capsys):
    other_user = User.objects.create_user()
    other_workspace = Workspace.objects.create(
        owner=other_user,
        name="Other",
    )
    rejected_operation.binding.ally.workspace = other_workspace
    rejected_operation.binding.ally.save(update_fields=("workspace", "updated_at"))

    call_command(
        "recover_foundry_provisioning",
        workspace_id=str(rejected_operation.workspace_id),
        confirm=True,
    )

    rejected_operation.refresh_from_db()
    assert rejected_operation.status == ProvisioningStatus.REPAIR_REQUIRED
    assert "matched=0 requeued=0" in capsys.readouterr().out
