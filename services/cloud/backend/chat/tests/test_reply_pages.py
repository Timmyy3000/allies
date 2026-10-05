import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext

from chat.api.controllers import _conversation_response
from chat.exceptions import TurnConflict
from chat.models import AssistantReply, Message
from chat.services.conversations import (
    _messages_page,
    ensure_default_conversation,
    retrieve_conversation,
)
from chat.services.messages import retry_message
from chat.tests import test_services

account = test_services.account


def test_large_replies_remain_reachable_without_loading_other_reply_bodies(account):
    _, _, ally = account
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Ready"
    )
    for sequence in (3, 4):
        message = Message.objects.create(
            conversation=conversation,
            sequence=sequence,
            sender="user",
            origin="send",
            content="question",
            status="completed",
            send_key_digest=str(sequence) * 64,
            content_fingerprint="f" * 64,
        )
        AssistantReply.objects.create(
            message=message, content="x" * (2 * 1024 * 1024), has_full_prefix=True
        )
    with CaptureQueriesContext(connection) as queries:
        page, cursor = _messages_page(conversation=conversation, limit=100, cursor=None)
    assert [message.sequence for message in page] == [4]
    assert len(page[0].assistant_reply.content) == 2 * 1024 * 1024
    assert cursor is not None
    # The first query returns scalar lengths, not every full reply in the window.
    assert "LENGTH(" in queries[0]["sql"].upper()
    assert str(page[0].id).replace("-", "") in queries[1]["sql"].replace("-", "")
    previous, cursor = _messages_page(
        conversation=conversation, limit=100, cursor=cursor
    )
    assert [message.sequence for message in previous] == [3]
    assert len(previous[0].assistant_reply.content) == 2 * 1024 * 1024
    remaining, cursor = _messages_page(
        conversation=conversation, limit=100, cursor=cursor
    )
    assert [message.sequence for message in remaining] == [1, 2]
    assert cursor is None


def test_reply_and_retry_model_guards(account):
    _, _, ally = account
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Ready"
    )
    greeting = conversation.messages.get(sequence=1)
    with pytest.raises(ValidationError, match="sent user message"):
        AssistantReply(message=greeting, content="wrong parent").full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        Message.objects.filter(pk=greeting.pk).update(retry_allowed=True)


@pytest.mark.parametrize("status", ["queued", "in_progress", "failed", "stopped"])
def test_unknown_outcome_refuses_fresh_retry(account, status):
    user, workspace, ally = account
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Ready"
    )
    message = Message.objects.create(
        conversation=conversation,
        sequence=3,
        sender="user",
        origin="send",
        content="one intent",
        status=status,
        send_key_digest="a" * 64,
        content_fingerprint="b" * 64,
    )
    with pytest.raises(TurnConflict):
        retry_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            message_id=message.id,
            idempotency_key="unknown-retry-key-00001",
        )
    assert conversation.messages.count() == 3


def test_reply_pages_follow_source_messages_without_extra_queries(account):
    user, workspace, ally = account
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Ready"
    )
    messages = Message.objects.bulk_create(
        [
            Message(
                conversation=conversation,
                sequence=number,
                sender="user",
                origin="send",
                content=f"turn {number}",
                status="completed",
                send_key_digest=str(number) * 64,
                content_fingerprint="f" * 64,
            )
            for number in range(3, 6)
        ]
    )
    AssistantReply.objects.bulk_create(
        [
            AssistantReply(
                message=message,
                content=f"reply {message.sequence}",
                has_full_prefix=True,
            )
            for message in messages
        ]
    )
    with CaptureQueriesContext(connection) as small_queries:
        small = _conversation_response(
            retrieve_conversation(
                user=user,
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                limit=1,
            )
        )
    with CaptureQueriesContext(connection) as larger_queries:
        larger = _conversation_response(
            retrieve_conversation(
                user=user,
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                limit=3,
            )
        )
    assert len(small_queries) == len(larger_queries)
    assert [reply.content for reply in small.assistant_replies] == ["reply 5"]
    assert [reply.source_message_id for reply in larger.assistant_replies] == [
        m.id for m in messages
    ]
    assert all(
        reply.status == "completed" and reply.has_full_prefix and not reply.is_truncated
        for reply in larger.assistant_replies
    )
    previous = _conversation_response(
        retrieve_conversation(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            limit=2,
            cursor=small.next_cursor,
        )
    )
    assert [reply.content for reply in previous.assistant_replies] == [
        "reply 3",
        "reply 4",
    ]
