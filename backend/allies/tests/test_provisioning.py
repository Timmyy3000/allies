from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from allies.gateways.foundry import ProfileProvisioningReceipt
from allies.models import (
    Ally,
    AllyBinding,
    BindingStatus,
    ProvisioningOperation,
    ProvisioningStatus,
)
from allies.services.provisioning import dispatch_due_provisioning
from auths.models import User
from workspaces.models import Workspace


@pytest.fixture
def operation(db):
    user = User.objects.create_user(public_id="usr_dispatch")
    workspace = Workspace.objects.create(
        public_id="wsp_dispatch", owner=user, name="Dispatch"
    )
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
        expires_at=timezone.now() + timedelta(hours=1),
    )


@pytest.mark.django_db
def test_active_receipt_binds_ally(monkeypatch, operation):
    def active(request):
        return ProfileProvisioningReceipt(
            version=1,
            binding_id=request.binding_id,
            operation_id=request.operation_id,
            request_fingerprint=request.request_fingerprint,
            status="active",
            evidence_digest="c" * 64,
        )

    monkeypatch.setattr("allies.services.provisioning.provision_profile", active)
    report = dispatch_due_provisioning()

    operation.refresh_from_db()
    operation.binding.refresh_from_db()
    assert report.succeeded == 1
    assert operation.status == ProvisioningStatus.SUCCEEDED
    assert operation.binding.status == BindingStatus.BOUND


@pytest.mark.django_db
def test_pending_receipt_defers_and_expired_lease_recovers(monkeypatch, operation):
    operation.status = ProvisioningStatus.IN_PROGRESS
    operation.lease_expires_at = timezone.now() - timedelta(seconds=1)
    operation.save(update_fields=("status", "lease_expires_at", "updated_at"))

    def pending(request):
        return ProfileProvisioningReceipt(
            version=1,
            binding_id=request.binding_id,
            operation_id=request.operation_id,
            request_fingerprint=request.request_fingerprint,
            status="pending",
            evidence_digest="d" * 64,
        )

    monkeypatch.setattr("allies.services.provisioning.provision_profile", pending)
    report = dispatch_due_provisioning()

    operation.refresh_from_db()
    assert report.deferred == 1
    assert operation.status == ProvisioningStatus.RETRYABLE
    assert operation.attempt_count == 1
    assert operation.lease_expires_at is None


@pytest.mark.django_db
def test_pending_operation_with_live_lease_is_not_claimed(monkeypatch, operation):
    operation.lease_expires_at = timezone.now() + timedelta(minutes=1)
    operation.save(update_fields=("lease_expires_at", "updated_at"))
    monkeypatch.setattr(
        "allies.services.provisioning.provision_profile",
        lambda _request: pytest.fail("live lease must not be claimed"),
    )

    report = dispatch_due_provisioning()

    operation.refresh_from_db()
    assert report.claimed == 0
    assert operation.status == ProvisioningStatus.PENDING


@pytest.mark.django_db
def test_expired_operation_is_fenced_without_http(monkeypatch, operation):
    operation.expires_at = timezone.now() - timedelta(seconds=1)
    operation.save(update_fields=("expires_at", "updated_at"))
    monkeypatch.setattr(
        "allies.services.provisioning.provision_profile",
        lambda _request: pytest.fail("HTTP must not run"),
    )

    report = dispatch_due_provisioning()

    operation.refresh_from_db()
    assert report.claimed == 0
    assert operation.status == ProvisioningStatus.EXPIRED
    assert (
        operation.binding.ally.provisioning_state == ProvisioningStatus.REPAIR_REQUIRED
    )
