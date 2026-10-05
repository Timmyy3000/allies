from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from allies.exceptions import ProvisioningRejected, ProvisioningRetryable
from allies.gateways.contracts import ExecutionReceipt
from allies.gateways.foundry import (
    ProfileProvisioningReceipt,
    ProfileProvisioningRequest,
)
from allies.gateways.foundry import (
    provision_profile as gateway_provision_profile,
)
from allies.models import (
    Ally,
    AllyBinding,
    BindingStatus,
    OnboardingAttempt,
    ProvisioningOperation,
    ProvisioningStatus,
)
from allies.services.provisioning import dispatch_due_provisioning
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
from workspaces.models import Workspace

MULTILINE_JOB = (
    "I want you to teach my German \n"
    "I am currently at the A1 level and just started at A2"
)


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


@pytest.fixture(autouse=True)
def foundry_activation(monkeypatch):
    monkeypatch.setattr(
        "allies.services.provisioning.activate_workspace",
        lambda _workspace_id: None,
    )


@pytest.mark.django_db
def test_ready_timing_is_emitted_only_after_commit(
    operation, monkeypatch, django_capture_on_commit_callbacks
):
    events = []
    monkeypatch.setattr(
        "allies.services.provisioning.emit_event",
        lambda kind, **fields: events.append((kind, fields)),
    )
    monkeypatch.setattr(
        "allies.services.provisioning.provision_profile",
        lambda request: ProfileProvisioningReceipt(
            version=1,
            binding_id=request.binding_id,
            operation_id=request.operation_id,
            request_fingerprint=request.request_fingerprint,
            status="active",
            evidence_digest="c" * 64,
        ),
    )
    monkeypatch.setattr(
        "chat.services.conversations.activate_onboarding_reply", lambda **kwargs: None
    )
    with django_capture_on_commit_callbacks(execute=True):
        assert dispatch_due_provisioning().succeeded == 1
        assert not any(
            fields["operation"] == "provisioning.ready_committed_wall"
            for _, fields in events
        )
    ready = [
        fields
        for _, fields in events
        if fields["operation"] == "provisioning.ready_committed_wall"
    ]
    assert len(ready) == 1
    assert ready[0]["correlation_id"] == str(operation.pk)
    assert ready[0]["duration_ms"] >= 0


@pytest.mark.django_db
def test_dispatch_serializes_stored_multiline_ally_with_operation_fingerprint(
    operation, monkeypatch, settings
):
    ally = operation.binding.ally
    ally.job = MULTILINE_JOB
    ally.personality = "Calm\nspecific."
    ally.save(update_fields=("job", "personality", "updated_at"))
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"
    captured = {}

    class Response:
        def __init__(self, body):
            self.body = json.dumps(body).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return self.body

    class Opener:
        def open(self, request, *, timeout):
            captured["raw"] = request.data
            captured["body"] = json.loads(request.data)
            captured["timeout"] = timeout
            return Response(
                {
                    "version": 1,
                    "binding_id": str(operation.binding_id),
                    "operation_id": str(operation.id),
                    "request_fingerprint": operation.content_fingerprint,
                    "status": "active",
                    "evidence_digest": "c" * 64,
                }
            )

    monkeypatch.setattr(
        "allies.gateways.foundry.build_opener", lambda *_handlers: Opener()
    )

    def provision(request):
        captured["request"] = request
        return gateway_provision_profile(request)

    monkeypatch.setattr("allies.services.provisioning.provision_profile", provision)
    monkeypatch.setattr(
        "chat.services.conversations.activate_onboarding_reply", lambda **_kwargs: None
    )

    report = dispatch_due_provisioning()

    assert report.succeeded == 1
    assert isinstance(captured["request"], ProfileProvisioningRequest)
    assert captured["request"].job == MULTILINE_JOB
    assert captured["request"].request_fingerprint == operation.content_fingerprint
    assert captured["body"] == {
        "version": 1,
        "workspace_id": str(operation.workspace_id),
        "binding_id": str(operation.binding_id),
        "ally_ref": str(operation.binding.ally_id),
        "operation_id": str(operation.id),
        "request_fingerprint": operation.content_fingerprint,
        "name": "Mira",
        "job": MULTILINE_JOB,
        "personality": "Calm\nspecific.",
    }
    assert b"\\r" not in captured["raw"]
    assert captured["timeout"] == settings.ALLIES_FOUNDRY_TIMEOUT_SECONDS
    operation.refresh_from_db()
    assert operation.status == ProvisioningStatus.SUCCEEDED


@pytest.mark.django_db
def test_repair_does_not_emit_ready_timing(
    operation, monkeypatch, django_capture_on_commit_callbacks
):
    events = []
    monkeypatch.setattr(
        "allies.services.provisioning.emit_event",
        lambda kind, **fields: events.append(fields),
    )
    monkeypatch.setattr(
        "allies.services.provisioning.provision_profile",
        lambda request: ProfileProvisioningReceipt(
            version=1,
            binding_id=request.binding_id,
            operation_id=request.operation_id,
            request_fingerprint=request.request_fingerprint,
            status="active",
            evidence_digest="c" * 64,
        ),
    )

    def unavailable(**kwargs):
        raise OnboardingHandoffRepairRequired("handoff unavailable")

    monkeypatch.setattr(
        "chat.services.conversations.activate_onboarding_reply", unavailable
    )
    with django_capture_on_commit_callbacks(execute=True):
        assert dispatch_due_provisioning().repair_required == 1
    assert not any(
        event["operation"] == "provisioning.ready_committed_wall" for event in events
    )


@pytest.mark.django_db
@pytest.mark.parametrize("pending", [True, False])
def test_reconcile_timing_pairs_terminal_outcome(operation, monkeypatch, pending):
    events = []
    monkeypatch.setattr(
        "allies.services.timing.emit_event",
        lambda kind, **fields: events.append((kind, fields)),
    )
    monkeypatch.setattr(
        "allies.services.provisioning.provision_profile",
        lambda request: ProfileProvisioningReceipt(
            version=1,
            binding_id=request.binding_id,
            operation_id=request.operation_id,
            request_fingerprint=request.request_fingerprint,
            status="pending" if pending else "active",
            evidence_digest="c" * 64,
        ),
    )
    monkeypatch.setattr(
        "chat.services.conversations.activate_onboarding_reply", lambda **kwargs: None
    )
    dispatch_due_provisioning()
    spans = [
        (kind, fields)
        for kind, fields in events
        if fields["operation"] == "provisioning.reconcile"
    ]
    assert [kind for kind, _ in spans] == [
        "runtime.operation.started",
        "runtime.operation.succeeded",
    ]
    assert spans[1][1]["outcome"] == ("deferred" if pending else "succeeded")
    assert spans[1][1]["correlation_id"] == str(operation.pk)
    assert spans[1][1]["duration_ms"] >= 0


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
def test_activation_retryable_defers_operation(monkeypatch, operation):
    monkeypatch.setattr(
        "allies.services.provisioning.provision_profile",
        lambda _request: ProfileProvisioningReceipt(
            version=1,
            binding_id=str(operation.binding_id),
            operation_id=str(operation.id),
            request_fingerprint=operation.content_fingerprint,
            status="pending",
            evidence_digest="a" * 64,
        ),
    )
    monkeypatch.setattr(
        "allies.services.provisioning.activate_workspace",
        lambda _workspace_id: (_ for _ in ()).throw(ProvisioningRetryable()),
    )

    report = dispatch_due_provisioning()

    operation.refresh_from_db()
    assert report.deferred == 1
    assert operation.status == ProvisioningStatus.RETRYABLE
    assert operation.safe_error_code == "foundry_activation_retryable"


@pytest.mark.django_db
def test_activation_rejection_requires_repair(monkeypatch, operation):
    monkeypatch.setattr(
        "allies.services.provisioning.provision_profile",
        lambda _request: ProfileProvisioningReceipt(
            version=1,
            binding_id=str(operation.binding_id),
            operation_id=str(operation.id),
            request_fingerprint=operation.content_fingerprint,
            status="pending",
            evidence_digest="a" * 64,
        ),
    )
    monkeypatch.setattr(
        "allies.services.provisioning.activate_workspace",
        lambda _workspace_id: (_ for _ in ()).throw(ProvisioningRejected()),
    )

    report = dispatch_due_provisioning()

    operation.refresh_from_db()
    assert report.failed == 1
    assert operation.status == ProvisioningStatus.REPAIR_REQUIRED
    assert operation.safe_error_code == "foundry_activation_rejected"


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
@pytest.mark.parametrize(
    ("prior_attempts", "expected_delay"),
    [(0, 2), (1, 4), (2, 8), (3, None)],
)
def test_pending_receipt_has_only_three_bounded_follow_ups(
    monkeypatch, operation, prior_attempts, expected_delay
):
    operation.status = (
        ProvisioningStatus.PENDING
        if prior_attempts == 0
        else ProvisioningStatus.RETRYABLE
    )
    operation.attempt_count = prior_attempts
    operation.next_attempt_at = timezone.now() - timedelta(seconds=1)
    operation.save(
        update_fields=("status", "attempt_count", "next_attempt_at", "updated_at")
    )
    monkeypatch.setattr(
        "allies.services.provisioning.provision_profile",
        lambda request: ProfileProvisioningReceipt(
            version=1,
            binding_id=request.binding_id,
            operation_id=request.operation_id,
            request_fingerprint=request.request_fingerprint,
            status="pending",
            evidence_digest="d" * 64,
        ),
    )

    report = dispatch_due_provisioning(now=timezone.now())

    operation.refresh_from_db()
    assert report.deferred == 1
    assert report.follow_up_delays == (
        (expected_delay,) if expected_delay is not None else ()
    )
    assert operation.attempt_count == prior_attempts + 1
    assert operation.status == ProvisioningStatus.RETRYABLE
    assert operation.safe_error_code == "materialization_pending"


@pytest.mark.django_db
def test_pending_batch_reports_each_distinct_follow_up_delay(monkeypatch, operation):
    for index, prior_attempts in ((1, 1), (2, 2)):
        ally = Ally.objects.create(
            workspace=operation.workspace,
            name=f"Mira {index}",
            job="Study partner",
            personality="Calm",
            appearance_catalog_version="v1",
            appearance_key="sunrise",
        )
        binding = AllyBinding.objects.create(ally=ally)
        ProvisioningOperation.objects.create(
            binding=binding,
            workspace=operation.workspace,
            user=operation.user,
            api_idempotency_key_digest=f"{index:064x}",
            content_fingerprint=f"{index + 10:064x}",
            status=ProvisioningStatus.RETRYABLE,
            attempt_count=prior_attempts,
            next_attempt_at=timezone.now() - timedelta(seconds=1),
            expires_at=timezone.now() + timedelta(hours=1),
        )
    monkeypatch.setattr(
        "allies.services.provisioning.provision_profile",
        lambda request: ProfileProvisioningReceipt(
            version=1,
            binding_id=request.binding_id,
            operation_id=request.operation_id,
            request_fingerprint=request.request_fingerprint,
            status="pending",
            evidence_digest="d" * 64,
        ),
    )

    report = dispatch_due_provisioning(now=timezone.now(), limit=3)

    assert report.as_dict() == {
        "claimed": 3,
        "succeeded": 0,
        "deferred": 3,
        "failed": 0,
        "repair_required": 0,
    }
    assert report.follow_up_delays == (2, 4, 8)
    assert list(
        ProvisioningOperation.objects.filter(safe_error_code="materialization_pending")
        .values_list("attempt_count", flat=True)
        .order_by("attempt_count")
    ) == [1, 2, 3]


@pytest.mark.django_db
def test_pending_next_attempt_uses_time_after_foundry_io(monkeypatch, operation):
    claim_started = timezone.now()
    after_receipt = claim_started + timedelta(seconds=5)
    current_time = claim_started

    def provision(request):
        nonlocal current_time
        current_time = after_receipt
        return ProfileProvisioningReceipt(
            version=1,
            binding_id=request.binding_id,
            operation_id=request.operation_id,
            request_fingerprint=request.request_fingerprint,
            status="pending",
            evidence_digest="d" * 64,
        )

    monkeypatch.setattr(
        "allies.services.provisioning.timezone.now", lambda: current_time
    )
    monkeypatch.setattr("allies.services.provisioning.provision_profile", provision)

    report = dispatch_due_provisioning(now=claim_started)

    operation.refresh_from_db()
    assert report.follow_up_delays == (2,)
    assert operation.last_attempt_at == claim_started
    assert operation.next_attempt_at == after_receipt + timedelta(seconds=2)


@pytest.mark.django_db
def test_success_completion_uses_time_after_onboarding_handoff(monkeypatch, operation):
    ensure_default_conversation(
        ally=operation.binding.ally,
        greeting="Hello",
        reply="Start here",
    )
    claim_started = timezone.now()
    after_handoff = claim_started + timedelta(seconds=7)
    handoffs = []
    current_time = claim_started

    def handoff(*, ally):
        nonlocal current_time
        handoffs.append(ally.pk)
        current_time = after_handoff

    monkeypatch.setattr(
        "allies.services.provisioning.provision_profile",
        lambda request: ProfileProvisioningReceipt(
            version=1,
            binding_id=request.binding_id,
            operation_id=request.operation_id,
            request_fingerprint=request.request_fingerprint,
            status="active",
            evidence_digest="a" * 64,
        ),
    )
    monkeypatch.setattr(
        "chat.services.conversations.activate_onboarding_reply",
        handoff,
    )
    monkeypatch.setattr(
        "allies.services.provisioning.timezone.now", lambda: current_time
    )

    report = dispatch_due_provisioning(now=claim_started)

    operation.refresh_from_db()
    assert report.succeeded == 1
    assert handoffs == [operation.binding.ally_id]
    assert operation.last_attempt_at == claim_started
    assert operation.completed_at == after_handoff


@pytest.mark.django_db
def test_retryable_foundry_failure_does_not_request_follow_up(monkeypatch, operation):
    monkeypatch.setattr(
        "allies.services.provisioning.provision_profile",
        lambda _request: (_ for _ in ()).throw(ProvisioningRetryable()),
    )

    report = dispatch_due_provisioning(now=timezone.now())

    operation.refresh_from_db()
    assert report.deferred == 1
    assert report.follow_up_delays == ()
    assert operation.status == ProvisioningStatus.RETRYABLE
    assert operation.safe_error_code == "foundry_retryable"


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
