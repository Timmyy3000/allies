from __future__ import annotations

from datetime import timedelta

import pytest
from auths.models import User
from chat.exceptions import OnboardingHandoffRepairRequired
from chat.models import (
    Conversation,
    DispatchOutbox,
    DispatchState,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessageSender,
)
from chat.services.conversations import (
    activate_onboarding_reply,
    ensure_default_conversation,
    reconcile_onboarding_reply,
)
from chat.services.dispatch import dispatch_pending_messages
from django.utils import timezone
from workspaces.models import Workspace

from allies.gateways.contracts import ExecutionReceipt
from allies.gateways.foundry import ProfileProvisioningReceipt
from allies.models import (
    Ally,
    AllyBinding,
    BindingStatus,
    OnboardingAttempt,
    ProvisioningOperation,
    ProvisioningStatus,
)
from allies.services.provisioning import dispatch_due_provisioning


@pytest.fixture
def operation(db):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Dispatch")
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
def test_active_receipt_binds_ally_and_dispatches_onboarding_reply(
    monkeypatch, operation, settings
):
    settings.ALLIES_FOUNDRY_EXECUTION_ENABLED = True
    conversation = ensure_default_conversation(
        ally=operation.binding.ally,
        greeting="Hello. What should we work on?",
        reply="Start with everyday phrases.",
    )

    def active(request):
        assert request.name == "Mira"
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
    reply = conversation.messages.get(sequence=2)
    assert reply.origin == MessageOrigin.SEND
    assert reply.status == MessageLifecycle.QUEUED
    assert DispatchOutbox.objects.filter(message=reply).exists()
    replay = activate_onboarding_reply(ally=operation.binding.ally)
    assert replay.pk == reply.pk
    assert DispatchOutbox.objects.filter(message=reply).count() == 1


@pytest.mark.django_db
def test_promoted_reply_is_recoverable_after_execution_is_enabled(
    monkeypatch, operation, settings
):
    settings.ALLIES_FOUNDRY_EXECUTION_ENABLED = False
    conversation = ensure_default_conversation(
        ally=operation.binding.ally,
        greeting="Hello. What should we work on?",
        reply="Start with everyday phrases.",
    )

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
    assert dispatch_due_provisioning().succeeded == 1

    reply = conversation.messages.get(sequence=2)
    outbox = DispatchOutbox.objects.get(message=reply)
    assert outbox.status == DispatchState.PENDING
    assert outbox.command_bytes

    settings.ALLIES_FOUNDRY_EXECUTION_ENABLED = True
    monkeypatch.setattr(
        "chat.services.dispatch.create_execution_intent",
        lambda command, **_kwargs: ExecutionReceipt(
            schema_version="v1",
            kind="execution.receipt",
            status="accepted",
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            fingerprint=command.fingerprint,
        ),
    )
    assert dispatch_pending_messages().accepted == 1
    outbox.refresh_from_db()
    assert outbox.status == DispatchState.ACCEPTED


@pytest.mark.django_db
def test_bound_ally_reconciliation_promotes_retained_reply_once(operation, settings):
    settings.ALLIES_FOUNDRY_EXECUTION_ENABLED = False
    conversation = ensure_default_conversation(
        ally=operation.binding.ally,
        greeting="Hello",
        reply="Keep this reply",
    )
    operation.binding.status = BindingStatus.BOUND
    operation.binding.receipt_digest = "e" * 64
    operation.binding.save(update_fields=("status", "receipt_digest", "updated_at"))

    first = reconcile_onboarding_reply(ally=operation.binding.ally)
    second = reconcile_onboarding_reply(ally=operation.binding.ally)

    assert first.pk == second.pk == conversation.messages.get(sequence=2).pk
    first.refresh_from_db()
    assert first.origin == MessageOrigin.SEND
    assert first.status == MessageLifecycle.QUEUED
    assert DispatchOutbox.objects.filter(message=first).count() == 1


@pytest.mark.django_db
def test_activation_rejects_missing_greeting_without_dispatch(operation):
    conversation = Conversation.objects.create(ally=operation.binding.ally)
    reply = Message.objects.create(
        conversation=conversation,
        sequence=2,
        sender=MessageSender.USER,
        origin=MessageOrigin.ONBOARDING,
        content="Retained reply",
        status=MessageLifecycle.COMPLETED,
    )

    with pytest.raises(OnboardingHandoffRepairRequired):
        activate_onboarding_reply(ally=operation.binding.ally)

    reply.refresh_from_db()
    assert reply.origin == MessageOrigin.ONBOARDING
    assert reply.status == MessageLifecycle.COMPLETED
    assert not DispatchOutbox.objects.filter(message=reply).exists()


@pytest.mark.django_db
def test_activation_rejects_garbled_greeting_without_dispatch(operation):
    conversation = ensure_default_conversation(
        ally=operation.binding.ally,
        greeting="Garbled stored greeting",
        reply="Retained reply",
    )
    now = timezone.now()
    OnboardingAttempt.objects.create(
        attempt_token_digest="1" * 64,
        browser_binding_digest="2" * 64,
        name=operation.binding.ally.name,
        job=operation.binding.ally.job,
        personality=operation.binding.ally.personality,
        appearance_catalog_version=operation.binding.ally.appearance_catalog_version,
        appearance_key=operation.binding.ally.appearance_key,
        greeting="Expected greeting",
        reply="Retained reply",
        user=operation.user,
        ally=operation.binding.ally,
        expires_at=now + timedelta(hours=1),
        consumed_at=now,
    )
    reply = conversation.messages.get(sequence=2)

    with pytest.raises(OnboardingHandoffRepairRequired):
        activate_onboarding_reply(ally=operation.binding.ally)

    reply.refresh_from_db()
    assert reply.origin == MessageOrigin.ONBOARDING
    assert reply.status == MessageLifecycle.COMPLETED
    assert not DispatchOutbox.objects.filter(message=reply).exists()


@pytest.mark.django_db
def test_active_receipt_keeps_bound_compute_when_handoff_is_missing(
    monkeypatch, operation
):
    def active(request):
        return ProfileProvisioningReceipt(
            version=1,
            binding_id=request.binding_id,
            operation_id=request.operation_id,
            request_fingerprint=request.request_fingerprint,
            status="active",
            evidence_digest="f" * 64,
        )

    monkeypatch.setattr("allies.services.provisioning.provision_profile", active)
    report = dispatch_due_provisioning()

    operation.refresh_from_db()
    operation.binding.refresh_from_db()
    assert report.succeeded == 0
    assert report.repair_required == 1
    assert operation.status == ProvisioningStatus.REPAIR_REQUIRED
    assert operation.safe_error_code == "onboarding_handoff_unavailable"
    assert operation.completed_at is not None
    assert operation.lease_expires_at is None
    assert operation.binding.status == BindingStatus.BOUND
    assert Ally.objects.get(pk=operation.binding.ally_id).provisioning_state == (
        ProvisioningStatus.REPAIR_REQUIRED
    )

    monkeypatch.setattr(
        "allies.services.provisioning.provision_profile",
        lambda _request: pytest.fail("repair-required operation must not retry"),
    )
    assert dispatch_due_provisioning().claimed == 0


@pytest.mark.django_db
@pytest.mark.parametrize("invalid_name", ["Mira\r", "Mira\x00"])
def test_invalid_stored_ally_name_is_terminal_repair(
    monkeypatch, operation, invalid_name
):
    operation.binding.ally.name = invalid_name
    operation.binding.ally.save(update_fields=("name", "updated_at"))
    monkeypatch.setattr(
        "allies.services.provisioning.provision_profile",
        lambda _request: pytest.fail("invalid stored data must not reach Foundry"),
    )

    report = dispatch_due_provisioning()

    operation.refresh_from_db()
    operation.binding.refresh_from_db()
    assert report.succeeded == 0
    assert report.repair_required == 1
    assert operation.status == ProvisioningStatus.REPAIR_REQUIRED
    assert operation.safe_error_code == "stored_ally_invalid"
    assert operation.lease_expires_at is None
    assert operation.completed_at is not None
    assert operation.binding.status == BindingStatus.INCOMPATIBLE
    assert dispatch_due_provisioning().claimed == 0


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
