from __future__ import annotations

from datetime import timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.db import DatabaseError
from django.db.models import Exists, OuterRef
from django.utils import timezone

from activities.models import FoundryEventReceipt
from allies.models import (
    Ally,
    AllyBinding,
    BindingStatus,
    ProvisioningOperation,
    ProvisioningStatus,
)
from auths.models import User
from chat.exceptions import (
    CursorInvalid,
    IdempotencyConflict,
    MessageNotDeletable,
    MessageValidation,
    OnboardingHandoffRepairRequired,
    QueueFull,
    SendRateLimited,
    TurnConflict,
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
from chat.services.conversations import (
    ensure_default_conversation,
    reconcile_ally_conversation,
    retrieve_conversation,
)
from chat.services.messages import (
    accept_message,
    claim_next_turn,
    complete_turn,
    delete_queued_message,
    message_response,
    parse_cursor,
    retry_message,
    serialize_cursor,
)
from workspaces.models import Membership, Workspace

mark_legacy_claims = import_module(
    "chat.migrations.0006_message_queue_claims"
).mark_legacy_claims


@pytest.fixture
def account(db, settings):
    cache.clear()
    settings.ALLIES_AUTH_DIGEST_KEY = "d" * 32
    settings.ALLIES_CHAT_CURSOR_KEY = "c" * 32
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
    return user, workspace, ally


@pytest.mark.django_db
def test_onboarding_history_and_exactly_once_send(account):
    user, workspace, ally = account
    conversation = ensure_default_conversation(
        ally=ally, greeting=" Hello ", reply="  Start here. "
    )
    result = retrieve_conversation(
        user=user, workspace_id=workspace.id, ally_id=ally.id
    )
    assert [message.sequence for message in result.messages] == [1, 2]
    assert result.messages[0].content == "Hello"
    accepted = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="  café  ",
        idempotency_key="chat-send-key-0001",
    )
    replay = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="café",
        idempotency_key="chat-send-key-0001",
    )
    assert accepted.message.sequence == 3
    assert accepted.message.status == MessageLifecycle.QUEUED
    assert replay.replayed
    assert replay.message.pk == accepted.message.pk
    with pytest.raises(IdempotencyConflict):
        accept_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            content="different",
            idempotency_key="chat-send-key-0001",
        )


@pytest.mark.django_db
def test_repair_required_ally_rejects_new_sends(account):
    user, workspace, ally = account
    binding = AllyBinding.objects.create(
        ally=ally,
        status=BindingStatus.BOUND,
        receipt_digest="a" * 64,
    )
    ProvisioningOperation.objects.create(
        binding=binding,
        workspace=workspace,
        user=user,
        api_idempotency_key_digest="b" * 64,
        content_fingerprint="c" * 64,
        status=ProvisioningStatus.REPAIR_REQUIRED,
        expires_at=timezone.now() + timedelta(hours=1),
    )
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Retained reply"
    )

    with pytest.raises(OnboardingHandoffRepairRequired):
        accept_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            content="Please continue",
            idempotency_key="chat-repair-key-0001",
        )

    assert Message.objects.filter(conversation=conversation).count() == 2


@pytest.mark.django_db
def test_new_message_enforces_the_gateway_utf8_budget(account):
    user, workspace, ally = account
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Ready"
    )

    with pytest.raises(MessageValidation):
        accept_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            content="界" * 6000,
            idempotency_key="chat-send-key-utf8-budget",
        )


@pytest.mark.django_db
def test_onboarding_reconciliation_does_not_mask_database_errors(account, monkeypatch):
    _, _, ally = account

    def fail_lookup(_ally):
        raise DatabaseError("forced handoff lookup failure")

    monkeypatch.setattr(Ally, "onboarding_attempt", property(fail_lookup))

    with pytest.raises(DatabaseError, match="forced handoff lookup failure"):
        reconcile_ally_conversation(ally=ally)


@pytest.mark.django_db
def test_lifecycle_primitives_are_idempotent(account):
    user, workspace, ally = account
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Reply"
    )
    accepted = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Do this",
        idempotency_key="chat-send-key-0002",
    )
    claimed = claim_next_turn(conversation_id=conversation.id)
    assert claimed.pk == accepted.message.pk
    completed = complete_turn(message_id=claimed.id, status=MessageLifecycle.COMPLETED)
    timestamp = completed.updated_at
    replay = complete_turn(message_id=claimed.id, status=MessageLifecycle.COMPLETED)
    assert replay.pk == completed.pk
    assert replay.updated_at == timestamp
    with pytest.raises(TurnConflict):
        complete_turn(message_id=claimed.id, status=MessageLifecycle.FAILED)


@pytest.mark.django_db
def test_retry_message_requeues_an_explicitly_safe_failure_and_replays_by_key(account):
    user, workspace, ally = account
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Reply"
    )
    original = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Please continue",
        idempotency_key="chat-send-key-retry-01",
    ).message
    Message.objects.filter(pk=original.pk).update(
        status=MessageLifecycle.FAILED, retry_allowed=True
    )
    DispatchOutbox.objects.create(message=original, status=DispatchState.ACCEPTED)

    retried = retry_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=original.id,
        idempotency_key="chat-retry-key-000001",
    )
    assert retried.replayed is False
    assert retried.message.pk != original.pk
    assert retried.message.content == original.content
    assert retried.message.sequence == original.sequence + 1
    assert retried.message.retry_of_id == original.id

    replay = retry_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=original.id,
        idempotency_key="chat-retry-key-000001",
    )
    assert replay.replayed is True
    assert replay.message.pk == retried.message.pk


@pytest.mark.django_db
def test_retry_message_rejects_a_fresh_queued_send(account):
    user, workspace, ally = account
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Reply"
    )
    original = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Still working",
        idempotency_key="chat-send-key-retry-02",
    ).message

    with pytest.raises(TurnConflict):
        retry_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            message_id=original.id,
            idempotency_key="chat-retry-key-000002",
        )


@pytest.mark.django_db
def test_retry_message_rejects_a_stale_queued_send_without_an_outbox(account):
    user, workspace, ally = account
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Reply"
    )
    original = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Still waiting for dispatch",
        idempotency_key="chat-send-key-retry-03",
    ).message
    Message.objects.filter(pk=original.pk).update(
        updated_at=timezone.now() - timedelta(minutes=3)
    )

    with pytest.raises(TurnConflict):
        retry_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            message_id=original.id,
            idempotency_key="chat-retry-key-000003",
        )


@pytest.mark.django_db
def test_cursor_is_scoped_and_signed(account):
    user, workspace, ally = account
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Reply"
    )
    for number in range(3, 8):
        Message.objects.create(
            conversation=conversation,
            sequence=number,
            sender=MessageSender.ASSISTANT,
            origin=MessageOrigin.SEND,
            content=f"Message {number}",
            status=MessageLifecycle.COMPLETED,
        )
    page = retrieve_conversation(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        limit=3,
    )
    assert [message.sequence for message in page.messages] == [5, 6, 7]
    assert page.next_cursor
    replacement = "0" if page.next_cursor[-1] != "0" else "1"
    with pytest.raises(CursorInvalid):
        retrieve_conversation(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            limit=3,
            cursor=page.next_cursor[:-1] + replacement,
        )


@pytest.mark.django_db
def test_queue_limit_rejects_only_new_work(account, settings):
    user, workspace, ally = account
    settings.ALLIES_CHAT_MAX_PENDING_MESSAGES = 1
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Reply"
    )
    accepted = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="First",
        idempotency_key="chat-queue-key-0001",
    )
    tail = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Second",
        idempotency_key="chat-queue-key-0002",
    )
    with pytest.raises(QueueFull):
        accept_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            content="Third",
            idempotency_key="chat-queue-key-0003",
        )
    replay = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="First",
        idempotency_key="chat-queue-key-0001",
    )
    assert replay.replayed is True
    assert replay.message.pk == accepted.message.pk
    assert tail.message.execution_claimed_at is None
    assert Message.objects.filter(conversation=conversation).count() == 4


@pytest.mark.django_db
def test_delete_retains_tombstone_for_exact_replay_and_conflict(account):
    user, workspace, ally = account
    AllyBinding.objects.create(
        ally=ally,
        status=BindingStatus.BOUND,
        receipt_digest="b" * 64,
    )
    conversation = Conversation.objects.create(ally=ally, is_default=False)
    head = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Head",
        idempotency_key="chat-delete-head-0001",
    )
    tail = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Tail",
        idempotency_key="chat-delete-tail-0001",
    )

    deleted = delete_queued_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=tail.message.id,
    )

    assert deleted.id == tail.message.id
    assert deleted.status == MessageLifecycle.STOPPED
    assert deleted.content == ""
    assert deleted.execution_claimed_at is None
    assert deleted.deleted_at is not None
    assert message_response(deleted)["queue_state"] is None
    assert not DispatchOutbox.objects.filter(
        message=deleted, status=DispatchState.PENDING
    ).exists()
    replay = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Tail",
        idempotency_key="chat-delete-tail-0001",
    )
    assert replay.replayed
    assert replay.message.id == tail.message.id
    assert replay.message.content == ""
    with pytest.raises(IdempotencyConflict):
        accept_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            content="Different tail",
            idempotency_key="chat-delete-tail-0001",
        )
    with pytest.raises(MessageNotDeletable):
        delete_queued_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            message_id=head.message.id,
        )


@pytest.mark.django_db
def test_queue_read_is_hard_capped_and_excludes_tombstones(account):
    user, workspace, ally = account
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Reply"
    )
    for sequence in range(3, 108):
        Message.objects.create(
            conversation=conversation,
            sequence=sequence,
            sender=MessageSender.USER,
            origin=MessageOrigin.SEND,
            content=f"Queued {sequence}",
            status=MessageLifecycle.QUEUED,
            send_key_digest=f"{sequence:064x}",
            content_fingerprint=f"{sequence + 1:064x}",
        )
    tombstone = Message.objects.get(conversation=conversation, sequence=107)
    tombstone.content = ""
    tombstone.status = MessageLifecycle.STOPPED
    tombstone.deleted_at = timezone.now()
    tombstone.save(update_fields=("content", "status", "deleted_at", "updated_at"))

    page = retrieve_conversation(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        limit=1,
    )

    assert len(page.queue) == 101
    assert all(message.deleted_at is None for message in page.queue)
    assert all(message.status == MessageLifecycle.QUEUED for message in page.queue)


@pytest.mark.django_db
def test_failed_outbox_does_not_release_fifo_claim_until_terminal_message(account):
    user, workspace, ally = account
    AllyBinding.objects.create(
        ally=ally,
        status=BindingStatus.BOUND,
        receipt_digest="b" * 64,
    )
    conversation = Conversation.objects.create(ally=ally, is_default=False)
    head = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Head",
        idempotency_key="chat-fifo-head-0001",
    )
    tail = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Tail",
        idempotency_key="chat-fifo-tail-0001",
    )
    DispatchOutbox.objects.filter(message=head.message).update(
        status=DispatchState.FAILED,
        next_attempt_at=None,
        lease_expires_at=None,
    )

    assert claim_next_turn(conversation_id=conversation.id) is None
    tail.message.refresh_from_db()
    assert tail.message.execution_claimed_at is None

    complete_turn(message_id=head.message.id, status=MessageLifecycle.COMPLETED)
    tail.message.refresh_from_db()
    assert tail.message.execution_claimed_at is not None
    assert DispatchOutbox.objects.filter(message=tail.message).exists()


@pytest.mark.django_db
def test_legacy_claim_migration_preserves_attempted_heads_and_fifo(account):
    _user, _workspace, ally = account
    AllyBinding.objects.create(
        ally=ally,
        status=BindingStatus.BOUND,
        receipt_digest="b" * 64,
    )
    first_conversation = Conversation.objects.create(ally=ally, is_default=False)
    attempted = Message.objects.create(
        conversation=first_conversation,
        sequence=1,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="Attempted",
        status=MessageLifecycle.QUEUED,
        send_key_digest="a" * 64,
        content_fingerprint="b" * 64,
    )
    Message.objects.create(
        conversation=first_conversation,
        sequence=2,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="Later",
        status=MessageLifecycle.QUEUED,
        send_key_digest="c" * 64,
        content_fingerprint="d" * 64,
    )
    DispatchOutbox.objects.create(
        message=attempted,
        status=DispatchState.PENDING,
        attempt_count=1,
        last_attempt_at=timezone.now(),
    )

    second_conversation = Conversation.objects.create(ally=ally, is_default=False)
    claimed = Message.objects.create(
        conversation=second_conversation,
        sequence=1,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="Already claimed",
        status=MessageLifecycle.QUEUED,
        execution_claimed_at=timezone.now(),
        send_key_digest="e" * 64,
        content_fingerprint="f" * 64,
    )
    second_later = Message.objects.create(
        conversation=second_conversation,
        sequence=2,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="Do not claim",
        status=MessageLifecycle.QUEUED,
        send_key_digest="1" * 64,
        content_fingerprint="2" * 64,
    )

    third_conversation = Conversation.objects.create(ally=ally, is_default=False)
    third_first = Message.objects.create(
        conversation=third_conversation,
        sequence=1,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="First",
        status=MessageLifecycle.QUEUED,
        send_key_digest="3" * 64,
        content_fingerprint="4" * 64,
    )
    third_later = Message.objects.create(
        conversation=third_conversation,
        sequence=2,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="Second",
        status=MessageLifecycle.QUEUED,
        send_key_digest="5" * 64,
        content_fingerprint="6" * 64,
    )
    DispatchOutbox.objects.create(
        message=third_later,
        status=DispatchState.PENDING,
    )

    fourth_conversation = Conversation.objects.create(ally=ally, is_default=False)
    fourth_first = Message.objects.create(
        conversation=fourth_conversation,
        sequence=1,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="Orphan",
        status=MessageLifecycle.QUEUED,
        send_key_digest="7" * 64,
        content_fingerprint="8" * 64,
    )
    fourth_later = Message.objects.create(
        conversation=fourth_conversation,
        sequence=2,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="Orphan later",
        status=MessageLifecycle.QUEUED,
        send_key_digest="9" * 64,
        content_fingerprint="a" * 64,
    )
    DispatchOutbox.objects.create(
        message=fourth_later,
        status=DispatchState.PENDING,
        attempt_count=1,
        last_attempt_at=timezone.now(),
    )

    from django.apps import apps as django_apps

    mark_legacy_claims(django_apps, None)

    attempted.refresh_from_db()
    second_later.refresh_from_db()
    third_first.refresh_from_db()
    third_later.refresh_from_db()
    fourth_first.refresh_from_db()
    fourth_later.refresh_from_db()
    assert attempted.execution_claimed_at is not None
    assert claimed.execution_claimed_at is not None
    assert second_later.execution_claimed_at is None
    assert third_first.execution_claimed_at is None
    assert third_later.execution_claimed_at is None
    assert fourth_first.execution_claimed_at is None
    assert fourth_later.execution_claimed_at is not None

    live = Message.objects.filter(
        conversation=fourth_conversation, status=MessageLifecycle.QUEUED
    )
    earlier_unclaimed = live.filter(
        conversation_id=OuterRef("conversation_id"),
        sequence__lt=OuterRef("sequence"),
        execution_claimed_at__isnull=True,
    )
    blocked = live.filter(Exists(earlier_unclaimed), execution_claimed_at__isnull=False)
    assert list(blocked.values_list("pk", flat=True)) == [fourth_later.pk]
    DispatchOutbox.objects.create(message=fourth_first, status=DispatchState.PENDING)
    assert not live.filter(dispatch_outbox__isnull=True).exists()
    assert blocked.exists()

    from chat.services.dispatch import ensure_dispatch_after_accept

    ensure_dispatch_after_accept(third_first)
    third_first.refresh_from_db()
    third_later.refresh_from_db()
    assert third_first.execution_claimed_at is not None
    assert third_later.execution_claimed_at is None
    assert DispatchOutbox.objects.filter(message=third_first).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("attempts", "code", "receipt", "event", "terminal"),
    [
        (0, "command_invalid", False, False, True),
        (1, "binding_incompatible", False, False, True),
        (1, "onboarding_handoff_unavailable", False, False, True),
        (1, "onboarding_handoff_repair_required", False, False, True),
        (1, "binding_unavailable", False, False, False),
        (1, "foundry_rejected", False, False, False),
        (1, "receipt_identity_mismatch", False, False, False),
        (2, "binding_incompatible", False, False, False),
        (0, "command_invalid", True, False, False),
        (1, "binding_incompatible", False, True, False),
    ],
)
def test_legacy_failed_claims_require_positive_pre_call_evidence(
    account, attempts, code, receipt, event, terminal
):
    from django.apps import apps as django_apps

    _user, _workspace, ally = account
    conversation = Conversation.objects.create(ally=ally, is_default=False)
    head = Message.objects.create(
        conversation=conversation,
        sequence=1,
        sender="user",
        origin="send",
        content="Preserve this intent",
        status="queued",
        send_key_digest="a" * 64,
        content_fingerprint="b" * 64,
    )
    tail = Message.objects.create(
        conversation=conversation,
        sequence=2,
        sender="user",
        origin="send",
        content="Later intent",
        status="queued",
        send_key_digest="c" * 64,
        content_fingerprint="d" * 64,
    )
    DispatchOutbox.objects.create(
        message=head,
        status="failed",
        attempt_count=attempts,
        last_attempt_at=timezone.now() if attempts else None,
        safe_error_code=code,
        receipt_digest="e" * 64 if receipt else "",
    )
    if event:
        FoundryEventReceipt.objects.create(
            conversation=conversation,
            message=head,
            event_id=uuid4(),
            event_dedupe_key="legacy",
            attempt_id=uuid4(),
            generation=1,
            attempt_sequence=1,
            event_fingerprint="canonical-json-sha256:v1:" + "f" * 64,
            result="applied",
        )
    mark_legacy_claims(django_apps, None)
    head.refresh_from_db()
    tail.refresh_from_db()
    assert head.status == ("failed" if terminal else "queued")
    assert (head.execution_claimed_at is None) is terminal
    assert tail.execution_claimed_at is None
    assert head.content == "Preserve this intent"
    assert head.retry_allowed is False


@pytest.mark.django_db
def test_message_insert_failure_retains_fail_closed_quota(
    account, monkeypatch, settings
):
    user, workspace, ally = account
    settings.ALLIES_CHAT_SEND_RATE_LIMIT = 1
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Reply"
    )

    def fail_create(**_kwargs):
        raise DatabaseError("forced insert failure")

    with monkeypatch.context() as patch:
        patch.setattr(Message.objects, "create", fail_create)
        with pytest.raises(DatabaseError):
            accept_message(
                user=user,
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                content="Retry me",
                idempotency_key="chat-rollback-key-0001",
            )

    with pytest.raises(SendRateLimited):
        accept_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            content="Retry me",
            idempotency_key="chat-rollback-key-0001",
        )
    assert Message.objects.filter(conversation=conversation).count() == 2


@pytest.mark.django_db
def test_cursor_rotation_overlap_and_expiry(account, settings):
    _, _, ally = account
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Reply"
    )
    settings.ALLIES_CHAT_CURSOR_ACTIVE_KEY_ID = "old"
    settings.ALLIES_CHAT_CURSOR_KEYS = {"old": "o" * 32}
    settings.ALLIES_CHAT_CURSOR_PREVIOUS_KEYS = {}
    settings.ALLIES_CHAT_CURSOR_TTL_SECONDS = 60
    issued_at = timezone.now()
    cursor = serialize_cursor(conversation.id, 2, now=issued_at)
    settings.ALLIES_CHAT_CURSOR_ACTIVE_KEY_ID = "new"
    settings.ALLIES_CHAT_CURSOR_KEYS = {"new": "n" * 32}
    settings.ALLIES_CHAT_CURSOR_PREVIOUS_KEYS = {"old": "o" * 32}
    parsed = parse_cursor(cursor, conversation.id, now=issued_at)
    assert parsed.key_id == "old"

    with pytest.raises(CursorInvalid):
        parse_cursor(
            cursor,
            conversation.id,
            now=issued_at + timedelta(seconds=61),
        )
