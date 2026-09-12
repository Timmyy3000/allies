from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from allies.gateways.foundry import (
    ProfileProvisioningReceipt,
    WorkspaceActivationReceipt,
)
from allies.models import (
    Ally,
    AllyBinding,
    AllyDeletionState,
    DeletionOperation,
    DeletionOperationState,
    ProvisioningOperation,
    ProvisioningStatus,
)
from allies.services import deletion, provisioning
from auths.models import User
from workspaces.models import Membership, Workspace

pytestmark = [
    pytest.mark.postgresql,
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="requires PostgreSQL row-lock semantics",
    ),
]


def _target(*, suffix: str = "race"):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name=f"Deletion {suffix}")
    Membership.objects.create(
        workspace=workspace,
        user=user,
        role="owner",
        status="active",
    )
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study partner",
        personality="Calm and specific.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    binding = AllyBinding.objects.create(ally=ally)
    return user, workspace, ally, binding


def _accept(*, user, workspace, ally):
    return deletion.request_ally_deletion(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        confirmation="Mira - deletes me",
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_delete_acceptance_has_one_postgresql_winner(monkeypatch):
    user, workspace, ally, _binding = _target(suffix="accept")
    monkeypatch.setattr(deletion, "_enqueue_reconciliation", lambda _id: None)
    gate = Barrier(2)

    def accept_once():
        close_old_connections()
        gate.wait(timeout=10)
        try:
            return _accept(user=user, workspace=workspace, ally=ally).id
        finally:
            close_old_connections()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        operation_ids = list(executor.map(lambda _index: accept_once(), range(2)))

    assert operation_ids[0] == operation_ids[1]
    assert (
        DeletionOperation.objects.filter(workspace=workspace, ally_id=ally.id).count()
        == 1
    )
    ally.refresh_from_db()
    assert ally.deletion_state == AllyDeletionState.PENDING


@pytest.mark.django_db(transaction=True)
def test_concurrent_repair_resume_converges_on_one_postgresql_epoch(monkeypatch):
    user, workspace, ally, _binding = _target(suffix="resume")
    monkeypatch.setattr(deletion, "_enqueue_reconciliation", lambda _id: None)
    operation = _accept(user=user, workspace=workspace, ally=ally)
    failed_attempt = uuid4()
    operation.state = DeletionOperationState.REPAIR_REQUIRED
    operation.foundry_attempt_id = failed_attempt
    operation.attempt_id = failed_attempt
    operation.save(
        update_fields=("state", "foundry_attempt_id", "attempt_id", "updated_at")
    )
    ally.deletion_state = AllyDeletionState.REPAIR_REQUIRED
    ally.save(update_fields=("deletion_state", "updated_at"))
    gate = Barrier(2)

    def resume_once():
        close_old_connections()
        gate.wait(timeout=10)
        try:
            resumed = deletion.resume_ally_deletion(
                operation_id=operation.id,
                expected_attempt_id=failed_attempt,
            )
            return resumed.lifecycle_epoch, resumed.attempt_id
        finally:
            close_old_connections()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: resume_once(), range(2)))

    assert results[0] == results[1]
    operation.refresh_from_db()
    ally.refresh_from_db()
    assert operation.state == DeletionOperationState.PENDING
    assert operation.lifecycle_epoch == 2
    assert operation.attempt_id == results[0][1]
    assert operation.foundry_resume_attempt_id == failed_attempt
    assert ally.deletion_state == AllyDeletionState.PENDING


@pytest.mark.django_db(transaction=True)
def test_late_postgresql_provisioning_receipt_cannot_cross_delete_fence(monkeypatch):
    user, workspace, ally, binding = _target(suffix="provisioning")
    operation = ProvisioningOperation.objects.create(
        binding=binding,
        workspace=workspace,
        user=user,
        api_idempotency_key_digest="a" * 64,
        content_fingerprint="b" * 64,
        next_attempt_at=timezone.now(),
    )
    started, release = Event(), Event()
    activation_calls = []

    def provision(_request):
        started.set()
        assert release.wait(timeout=10)
        return ProfileProvisioningReceipt(
            version=1,
            binding_id=str(binding.id),
            operation_id=str(operation.id),
            request_fingerprint=operation.content_fingerprint,
            status="active",
            evidence_digest="c" * 64,
        )

    def activate(workspace_id):
        activation_calls.append(workspace_id)
        return WorkspaceActivationReceipt(
            version=1,
            workspace_id=str(workspace.id),
            status="active",
        )

    monkeypatch.setattr(provisioning, "provision_profile", provision)
    monkeypatch.setattr(provisioning, "activate_workspace", activate)
    monkeypatch.setattr(deletion, "_enqueue_reconciliation", lambda _id: None)
    now = timezone.now()

    def dispatch_once():
        close_old_connections()
        try:
            return provisioning.dispatch_due_provisioning(now=now, limit=1)
        finally:
            close_old_connections()
            connection.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(dispatch_once)
        assert started.wait(timeout=10)
        accepted = _accept(user=user, workspace=workspace, ally=ally)
        assert accepted.state == DeletionOperationState.PENDING
        release.set()
        report = future.result(timeout=10)

    operation.refresh_from_db()
    ally.refresh_from_db()
    assert report.claimed == 1
    assert report.repair_required == 1
    assert operation.status == ProvisioningStatus.REPAIR_REQUIRED
    assert operation.safe_error_code == "ally_deletion_pending"
    assert ally.deletion_state == AllyDeletionState.PENDING
    assert activation_calls == []
