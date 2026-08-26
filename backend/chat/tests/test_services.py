from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db import DatabaseError
from django.utils import timezone

from allies.models import Ally
from auths.models import User
from chat.exceptions import (
    CursorInvalid,
    IdempotencyConflict,
    QueueFull,
    SendRateLimited,
    TurnConflict,
)
from chat.models import Message, MessageLifecycle, MessageOrigin, MessageSender
from chat.services.conversations import (
    ensure_default_conversation,
    reconcile_ally_conversation,
    retrieve_conversation,
)
from chat.services.messages import (
    accept_message,
    claim_next_turn,
    complete_turn,
    parse_cursor,
    serialize_cursor,
)
from workspaces.models import Membership, Workspace


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
    with pytest.raises(QueueFull):
        accept_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            content="Second",
            idempotency_key="chat-queue-key-0002",
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
    assert Message.objects.filter(conversation=conversation).count() == 3


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
