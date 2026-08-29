from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta
from uuid import UUID

import pytest
from django.test import override_settings
from django.utils import timezone

from allies.exceptions import FoundryGatewayRetryable, FoundryGatewayUnknownOutcome
from allies.gateways.contracts import (
    ExecutionCommand,
    ExecutionReceipt,
    ReconciliationReceipt,
)
from allies.models import Ally, AllyBinding, BindingStatus
from auths.models import User
from chat.exceptions import (
    OnboardingHandoffRepairRequired,
    OnboardingHandoffUnavailable,
)
from chat.models import (
    Conversation,
    DispatchOutbox,
    DispatchState,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessageSender,
)
from chat.services.dispatch import (
    dispatch_accepted_message,
    dispatch_pending_messages,
    ensure_dispatch_after_accept,
)
from chat.services.messages import accept_message
from workspaces.models import Membership, Workspace


@pytest.fixture
def dispatch_records(db):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Personal Workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study partner",
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    binding = AllyBinding.objects.create(
        ally=ally,
        status=BindingStatus.BOUND,
        receipt_digest="b" * 64,
    )
    conversation = Conversation.objects.create(ally=ally)
    message = Message.objects.create(
        conversation=conversation,
        sequence=1,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="normalized user text",
        status=MessageLifecycle.QUEUED,
        send_key_digest="a" * 64,
        content_fingerprint="c" * 64,
    )
    return workspace, binding, conversation, message


def receipt_for(command: ExecutionCommand) -> ExecutionReceipt:
    return ExecutionReceipt(
        schema_version="v1",
        kind="execution.receipt",
        status="accepted",
        command_id=command.command_id,
        idempotency_key=command.idempotency_key,
        fingerprint=command.fingerprint,
    )


@pytest.mark.django_db
@override_settings(ALLIES_FOUNDRY_EXECUTION_ENABLED=True)
def test_dispatch_is_one_to_one_and_transmits_persisted_canonical_bytes(
    dispatch_records, monkeypatch
):
    _workspace, _binding, _conversation, message = dispatch_records
    first = dispatch_accepted_message(message)
    replay = dispatch_accepted_message(message)
    outbox = DispatchOutbox.objects.get(message=message)
    persisted = bytes(outbox.command_bytes)

    captured: list[bytes] = []

    def create(command, *, raw_body=None):
        captured.append(bytes(raw_body or b""))
        return receipt_for(command)

    monkeypatch.setattr("chat.services.dispatch.create_execution_intent", create)
    report = dispatch_pending_messages(now=timezone.now())

    assert first.message_id == replay.message_id == message.id
    assert first.command_fingerprint == replay.command_fingerprint
    assert DispatchOutbox.objects.count() == 1
    assert captured == [persisted]
    assert hashlib.sha256(persisted).hexdigest() == outbox.command_sha256
    assert report.accepted == 1
    outbox.refresh_from_db()
    assert outbox.status == DispatchState.ACCEPTED
    assert outbox.command_bytes == b""

    command = ExecutionCommand.model_validate_json(persisted)
    assert command.command_id == message.id
    assert command.idempotency_key == message.id
    assert command.conversation_turn_ordinal == message.sequence


@pytest.mark.django_db
def test_accept_persists_outbox_while_execution_is_disabled_then_recovers(
    dispatch_records, monkeypatch
):
    _workspace, _binding, _conversation, message = dispatch_records

    with override_settings(ALLIES_FOUNDRY_EXECUTION_ENABLED=False):
        ensure_dispatch_after_accept(message)

    outbox = DispatchOutbox.objects.get(message=message)
    assert outbox.status == DispatchState.PENDING
    assert outbox.command_bytes

    with override_settings(ALLIES_FOUNDRY_EXECUTION_ENABLED=True):
        monkeypatch.setattr(
            "chat.services.dispatch.create_execution_intent",
            lambda command, **_kwargs: receipt_for(command),
        )
        report = dispatch_pending_messages(now=timezone.now())

    assert report.accepted == 1
    assert DispatchOutbox.objects.get(message=message).status == DispatchState.ACCEPTED


@pytest.mark.django_db
@override_settings(ALLIES_FOUNDRY_EXECUTION_ENABLED=True)
def test_sequence_two_onboarding_reply_is_dispatched_before_later_send(
    dispatch_records, monkeypatch
):
    _workspace, binding, conversation, existing = dispatch_records
    existing.delete()
    Message.objects.create(
        conversation=conversation,
        sequence=1,
        sender=MessageSender.ASSISTANT,
        origin=MessageOrigin.ONBOARDING,
        content="Hello",
        status=MessageLifecycle.COMPLETED,
    )
    Message.objects.create(
        conversation=conversation,
        sequence=2,
        sender=MessageSender.USER,
        origin=MessageOrigin.ONBOARDING,
        content="normalized user text",
        status=MessageLifecycle.COMPLETED,
    )
    later = Message.objects.create(
        conversation=conversation,
        sequence=3,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="Later send",
        status=MessageLifecycle.QUEUED,
        send_key_digest="b" * 64,
        content_fingerprint=hashlib.sha256(b"Later send").hexdigest(),
    )
    binding.status = BindingStatus.PENDING
    binding.save(update_fields=("status", "updated_at"))
    dispatch_accepted_message(later)
    binding.status = BindingStatus.BOUND
    binding.receipt_digest = "d" * 64
    binding.save(update_fields=("status", "receipt_digest", "updated_at"))

    calls: list[int] = []

    def create(command, **_kwargs):
        calls.append(command.conversation_turn_ordinal)
        return receipt_for(command)

    monkeypatch.setattr("chat.services.dispatch.create_execution_intent", create)
    now = timezone.now()

    first = dispatch_pending_messages(now=now)
    assert first.deferred == 1
    assert calls == []
    promoted = conversation.messages.get(sequence=2)
    assert promoted.origin == MessageOrigin.SEND
    assert promoted.status == MessageLifecycle.QUEUED
    assert DispatchOutbox.objects.filter(message=promoted).exists()

    DispatchOutbox.objects.filter(message__conversation=conversation).update(
        next_attempt_at=now
    )
    second = dispatch_pending_messages(now=now)

    assert second.accepted == 2
    assert calls == [2, 3]


@pytest.mark.django_db
@override_settings(ALLIES_FOUNDRY_EXECUTION_ENABLED=True)
def test_missing_onboarding_handoff_is_terminal_and_does_not_starve_batch(
    dispatch_records, monkeypatch
):
    workspace, _binding, conversation, message = dispatch_records
    message.sequence = 3
    message.save(update_fields=("sequence", "updated_at"))
    Message.objects.create(
        conversation=conversation,
        sequence=1,
        sender=MessageSender.ASSISTANT,
        origin=MessageOrigin.ONBOARDING,
        content="Hello",
        status=MessageLifecycle.COMPLETED,
    )
    dispatch_accepted_message(message)

    other_ally = Ally.objects.create(
        workspace=workspace,
        name="Nia",
        job="Planning partner",
        personality="Precise",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    AllyBinding.objects.create(
        ally=other_ally,
        status=BindingStatus.BOUND,
        receipt_digest="d" * 64,
    )
    other_conversation = Conversation.objects.create(ally=other_ally)
    other_message = Message.objects.create(
        conversation=other_conversation,
        sequence=1,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="Other work",
        status=MessageLifecycle.QUEUED,
        send_key_digest="e" * 64,
        content_fingerprint="f" * 64,
    )
    dispatch_accepted_message(other_message)

    calls: list[str] = []

    def create(command, **_kwargs):
        calls.append(str(command.cloud.message_id))
        return receipt_for(command)

    monkeypatch.setattr("chat.services.dispatch.create_execution_intent", create)
    now = timezone.now()
    report = dispatch_pending_messages(now=now)

    missing_outbox = DispatchOutbox.objects.get(message=message)
    other_outbox = DispatchOutbox.objects.get(message=other_message)
    assert report.claimed == 2
    assert report.accepted == 1
    assert missing_outbox.status == DispatchState.FAILED
    assert missing_outbox.safe_error_code == "onboarding_handoff_unavailable"
    assert missing_outbox.lease_expires_at is None
    assert missing_outbox.next_attempt_at is None
    assert other_outbox.status == DispatchState.ACCEPTED
    assert calls == [str(other_message.id)]
    assert dispatch_pending_messages(now=now + timedelta(days=1)).claimed == 0


@pytest.mark.django_db
@override_settings(ALLIES_FOUNDRY_EXECUTION_ENABLED=True)
@pytest.mark.parametrize(
    ("handoff_error", "safe_error_code"),
    [
        (OnboardingHandoffUnavailable, "onboarding_handoff_unavailable"),
        (OnboardingHandoffRepairRequired, "onboarding_handoff_repair_required"),
    ],
)
def test_handoff_reconciliation_errors_are_terminal_after_claim(
    dispatch_records, monkeypatch, handoff_error, safe_error_code
):
    _workspace, _binding, _conversation, message = dispatch_records
    dispatch_accepted_message(message)

    def fail_reconcile(**_kwargs):
        raise handoff_error()

    monkeypatch.setattr(
        "chat.services.conversations.reconcile_onboarding_reply",
        fail_reconcile,
    )

    report = dispatch_pending_messages(now=timezone.now())

    outbox = DispatchOutbox.objects.get(message=message)
    assert report.claimed == 1
    assert outbox.status == DispatchState.FAILED
    assert outbox.safe_error_code == safe_error_code
    assert outbox.lease_expires_at is None
    assert outbox.next_attempt_at is None


@pytest.mark.django_db
@override_settings(ALLIES_FOUNDRY_EXECUTION_ENABLED=True)
def test_pending_binding_defers_without_calling_foundry(dispatch_records, monkeypatch):
    _workspace, binding, _conversation, message = dispatch_records
    binding.status = BindingStatus.PENDING
    binding.save(update_fields=("status", "updated_at"))
    dispatch_accepted_message(message)
    calls: list[bool] = []
    monkeypatch.setattr(
        "chat.services.dispatch.create_execution_intent",
        lambda *_args, **_kwargs: calls.append(True),
    )
    now = timezone.now()

    for _attempt in range(6):
        DispatchOutbox.objects.filter(message=message).update(next_attempt_at=now)
        report = dispatch_pending_messages(now=now)
        outbox = DispatchOutbox.objects.get(message=message)
        assert report.deferred == 1
        assert calls == []
        assert outbox.status == DispatchState.PENDING
        assert outbox.attempt_count == 0
        assert outbox.safe_error_code == "binding_pending"

    binding.status = BindingStatus.BOUND
    binding.save(update_fields=("status", "updated_at"))
    DispatchOutbox.objects.filter(pk=outbox.pk).update(next_attempt_at=now)
    monkeypatch.setattr(
        "chat.services.dispatch.create_execution_intent",
        lambda command, **_kwargs: receipt_for(command),
    )

    assert dispatch_pending_messages(now=now).accepted == 1


@pytest.mark.django_db
@override_settings(
    ALLIES_FOUNDRY_EXECUTION_ENABLED=True,
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
)
def test_legacy_oversized_command_replay_records_non_dispatchable_outcome(
    dispatch_records,
):
    workspace, _binding, conversation, message = dispatch_records
    send_key = "legacy-send-key-0001"
    message.content = "界" * 6000
    message.content_fingerprint = hashlib.sha256(message.content.encode()).hexdigest()
    message.send_key_digest = hmac.new(
        b"d" * 32, send_key.encode(), hashlib.sha256
    ).hexdigest()
    message.save(
        update_fields=(
            "content",
            "content_fingerprint",
            "send_key_digest",
            "updated_at",
        )
    )

    replay = accept_message(
        user=workspace.owner,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content=message.content,
        idempotency_key=send_key,
    )

    outbox = DispatchOutbox.objects.get(message=message)
    assert replay.replayed
    assert replay.message == message
    assert outbox.status == DispatchState.FAILED
    assert outbox.safe_error_code == "command_invalid"
    assert outbox.next_attempt_at is None
    assert outbox.command_bytes == b""


@pytest.mark.django_db
@override_settings(ALLIES_FOUNDRY_EXECUTION_ENABLED=True)
def test_incompatible_binding_fails_without_calling_foundry(
    dispatch_records, monkeypatch
):
    _workspace, binding, _conversation, message = dispatch_records
    binding.status = BindingStatus.INCOMPATIBLE
    binding.save(update_fields=("status", "updated_at"))
    dispatch_accepted_message(message)
    calls: list[bool] = []
    monkeypatch.setattr(
        "chat.services.dispatch.create_execution_intent",
        lambda *_args, **_kwargs: calls.append(True),
    )

    report = dispatch_pending_messages(now=timezone.now())

    outbox = DispatchOutbox.objects.get(message=message)
    assert report.deferred == 0
    assert calls == []
    assert outbox.status == DispatchState.FAILED
    assert outbox.safe_error_code == "binding_incompatible"
    assert outbox.command_bytes == b""


@pytest.mark.django_db
@override_settings(ALLIES_FOUNDRY_EXECUTION_ENABLED=True)
def test_timeout_reconciles_the_same_identity_without_rebuilding_command(
    dispatch_records, monkeypatch
):
    _workspace, _binding, _conversation, message = dispatch_records
    dispatch_accepted_message(message)
    outbox = DispatchOutbox.objects.get(message=message)
    persisted = bytes(outbox.command_bytes)
    command = ExecutionCommand.model_validate_json(persisted)
    sent: list[bytes] = []
    reconciled: list[tuple[UUID, str]] = []

    def timeout(_command, *, raw_body=None):
        sent.append(bytes(raw_body or b""))
        raise FoundryGatewayUnknownOutcome("timeout")

    def reconcile(key, fingerprint):
        reconciled.append((key, fingerprint))
        return ReconciliationReceipt(
            schema_version="v1",
            kind="execution.reconciliation",
            status="accepted",
            idempotency_key=command.idempotency_key,
            fingerprint=command.fingerprint,
            command_id=command.command_id,
        )

    monkeypatch.setattr("chat.services.dispatch.create_execution_intent", timeout)
    monkeypatch.setattr("chat.services.dispatch.reconcile_execution_intent", reconcile)
    report = dispatch_pending_messages(now=timezone.now())

    assert report.reconciled == 1
    assert sent == [persisted]
    assert reconciled == [(message.id, command.fingerprint)]
    outbox.refresh_from_db()
    assert outbox.status == DispatchState.ACCEPTED
    assert outbox.command_bytes == b""


@pytest.mark.django_db
@override_settings(ALLIES_FOUNDRY_EXECUTION_ENABLED=True)
def test_reconciliation_needed_reconciles_before_post_after_restart(
    dispatch_records, monkeypatch
):
    _workspace, _binding, _conversation, message = dispatch_records
    dispatch_accepted_message(message)
    outbox = DispatchOutbox.objects.get(message=message)
    outbox.status = DispatchState.RECONCILIATION_NEEDED
    outbox.attempt_count = 2
    outbox.next_attempt_at = timezone.now()
    outbox.save(update_fields=("status", "attempt_count", "next_attempt_at"))

    calls: list[str] = []

    def reconcile(key, fingerprint):
        calls.append("reconcile")
        return ReconciliationReceipt(
            schema_version="v1",
            kind="execution.reconciliation",
            status="accepted",
            idempotency_key=key,
            fingerprint=fingerprint,
            command_id=key,
        )

    monkeypatch.setattr("chat.services.dispatch.reconcile_execution_intent", reconcile)
    monkeypatch.setattr(
        "chat.services.dispatch.create_execution_intent",
        lambda *_args, **_kwargs: calls.append("post"),
    )

    report = dispatch_pending_messages(now=timezone.now())

    assert report.reconciled == 1
    assert calls == ["reconcile"]
    assert DispatchOutbox.objects.get(message=message).status == DispatchState.ACCEPTED


@pytest.mark.django_db
@override_settings(ALLIES_FOUNDRY_EXECUTION_ENABLED=True)
def test_unknown_outcome_requires_reconciliation_before_later_post(
    dispatch_records, monkeypatch
):
    _workspace, _binding, _conversation, message = dispatch_records
    dispatch_accepted_message(message)
    calls: list[str] = []

    def timeout(*_args, **_kwargs):
        calls.append("post")
        raise FoundryGatewayUnknownOutcome("timeout")

    def not_found(*_args, **_kwargs):
        calls.append("reconcile")
        return ReconciliationReceipt(
            schema_version="v1",
            kind="execution.reconciliation",
            status="not_found",
            idempotency_key=message.id,
            fingerprint=DispatchOutbox.objects.get(message=message).command_fingerprint,
            command_id=None,
        )

    monkeypatch.setattr("chat.services.dispatch.create_execution_intent", timeout)
    monkeypatch.setattr("chat.services.dispatch.reconcile_execution_intent", not_found)
    now = timezone.now()

    first = dispatch_pending_messages(now=now)
    assert first.deferred == 1
    assert calls == ["post", "reconcile"]
    assert (
        DispatchOutbox.objects.get(message=message).status
        == DispatchState.RECONCILIATION_NEEDED
    )

    DispatchOutbox.objects.filter(message=message).update(next_attempt_at=now)
    second = dispatch_pending_messages(now=now)

    assert second.deferred == 1
    assert calls == ["post", "reconcile", "reconcile", "post", "reconcile"]


@pytest.mark.django_db
@override_settings(ALLIES_FOUNDRY_EXECUTION_ENABLED=True)
def test_dispatch_exhaustion_remains_reconciliation_needed(
    dispatch_records, monkeypatch
):
    _workspace, _binding, _conversation, message = dispatch_records
    dispatch_accepted_message(message)

    def unavailable(*_args, **_kwargs):
        raise FoundryGatewayRetryable("unavailable")

    monkeypatch.setattr("chat.services.dispatch.create_execution_intent", unavailable)
    now = timezone.now()
    for attempt in range(5):
        DispatchOutbox.objects.filter(message=message).update(next_attempt_at=now)
        report = dispatch_pending_messages(now=now)
        assert report.claimed == 1
        assert DispatchOutbox.objects.get(message=message).attempt_count == attempt + 1

    outbox = DispatchOutbox.objects.get(message=message)
    assert outbox.status == DispatchState.RECONCILIATION_NEEDED
    assert outbox.safe_error_code == "dispatch_attempts_exhausted"
    assert outbox.next_attempt_at is None
    assert outbox.command_bytes == b""
    assert outbox.command_byte_length == 0

    def not_found(*_args, **_kwargs):
        return ReconciliationReceipt(
            schema_version="v1",
            kind="execution.reconciliation",
            status="not_found",
            idempotency_key=message.id,
            fingerprint=outbox.command_fingerprint,
            command_id=None,
        )

    monkeypatch.setattr("chat.services.dispatch.reconcile_execution_intent", not_found)
    DispatchOutbox.objects.filter(message=message).update(next_attempt_at=now)
    report = dispatch_pending_messages(now=now)
    outbox.refresh_from_db()
    assert report.claimed == 1
    assert report.exhausted == 1
    assert outbox.status == DispatchState.RECONCILIATION_NEEDED
    assert outbox.next_attempt_at is None
    assert outbox.command_bytes == b""
    assert outbox.command_byte_length == 0

    second_report = dispatch_pending_messages(now=now + timedelta(days=1))
    assert second_report.claimed == 0


@pytest.mark.django_db
@override_settings(ALLIES_FOUNDRY_EXECUTION_ENABLED=True)
def test_exhausted_not_found_stays_reconciliation_needed(dispatch_records, monkeypatch):
    _workspace, _binding, _conversation, message = dispatch_records
    dispatch_accepted_message(message)
    outbox = DispatchOutbox.objects.get(message=message)
    outbox.status = DispatchState.RECONCILIATION_NEEDED
    outbox.attempt_count = 5
    outbox.next_attempt_at = timezone.now()
    outbox.save(update_fields=("status", "attempt_count", "next_attempt_at"))

    monkeypatch.setattr(
        "chat.services.dispatch.reconcile_execution_intent",
        lambda *_args, **_kwargs: ReconciliationReceipt(
            schema_version="v1",
            kind="execution.reconciliation",
            status="not_found",
            idempotency_key=message.id,
            fingerprint=outbox.command_fingerprint,
            command_id=None,
        ),
    )
    create_calls: list[bool] = []
    monkeypatch.setattr(
        "chat.services.dispatch.create_execution_intent",
        lambda *_args, **_kwargs: create_calls.append(True),
    )

    report = dispatch_pending_messages(now=timezone.now())

    outbox.refresh_from_db()
    assert report.claimed == 1
    assert report.exhausted == 1
    assert outbox.attempt_count == 5
    assert outbox.status == DispatchState.RECONCILIATION_NEEDED
    assert outbox.next_attempt_at is None
    assert outbox.command_bytes == b""
    assert outbox.command_byte_length == 0
    assert create_calls == []

    second_report = dispatch_pending_messages(now=timezone.now() + timedelta(days=1))
    assert second_report.claimed == 0
