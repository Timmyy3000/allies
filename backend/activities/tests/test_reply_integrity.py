from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from activities.exceptions import ProjectionSequenceGap
from activities.models import Activity, FoundryEventReceipt
from activities.services import projection
from activities.tests import test_cld005
from chat.models import (
    AssistantReply,
    DispatchOutbox,
    DispatchState,
    Message,
    MessageLifecycle,
)
from chat.services.messages import assistant_reply_response, is_message_retryable

conversation_records = test_cld005.conversation_records
event_for = test_cld005.event_for


def test_queued_turn_does_not_retransmit_previous_reply(conversation_records):
    user, workspace, _, binding, conversation, message = conversation_records
    projection.project_foundry_event(event_for(message, binding))
    projection.project_foundry_event(
        event_for(
            message,
            binding,
            attempt_sequence=2,
            event_type="execution.completed",
            payload={"status": "completed"},
        )
    )
    Message.objects.create(
        conversation=conversation,
        sequence=message.sequence + 1,
        sender="user",
        origin="send",
        content="next turn",
        send_key_digest="c" * 64,
        content_fingerprint="b" * 64,
    )
    snapshot = projection.read_activity_snapshot(
        user=user, workspace_id=workspace.id, conversation_id=conversation.id
    )
    assert snapshot.state == "queued"
    assert snapshot.assistant_reply is None


@pytest.mark.postgresql
@pytest.mark.skipif(
    connection.vendor != "postgresql", reason="requires PostgreSQL row locks"
)
@pytest.mark.django_db(transaction=True)
def test_concurrent_duplicate_callback_appends_reply_once(conversation_records):
    _, _, _, binding, _, message = conversation_records
    event = event_for(
        message, binding, payload={"kind": "assistant_delta", "text": "once"}
    )
    gate = Barrier(2)

    def project_once(_index):
        close_old_connections()
        try:
            gate.wait(timeout=10)
            return projection.project_foundry_event(event).status
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(project_once, range(2)))
    assert sorted(outcomes) == ["applied", "duplicate"]
    assert AssistantReply.objects.get(message=message).content == "once"
    assert FoundryEventReceipt.objects.filter(message=message).count() == 1


def test_long_reply_is_durable_live_and_terminal_after_activity_limits(
    conversation_records,
):
    user, workspace, _, binding, conversation, message = conversation_records
    projection.project_foundry_event(
        event_for(
            message,
            binding,
            event_type="execution.accepted",
            payload={"status": "accepted"},
        )
    )
    fragment = "x" * 100
    for sequence in range(2, 763):
        projection.project_foundry_event(
            event_for(
                message,
                binding,
                attempt_sequence=sequence,
                payload={"kind": "assistant_delta", "text": fragment},
            )
        )
    live = projection.read_activity_snapshot(
        user=user, workspace_id=workspace.id, conversation_id=conversation.id
    )
    assert live.assistant_reply.has_full_prefix
    assert live.assistant_reply.content == fragment * 761
    assert live.assistant_reply.message.status == MessageLifecycle.IN_PROGRESS
    terminal = event_for(
        message,
        binding,
        attempt_sequence=763,
        event_type="execution.completed",
        payload={"status": "completed"},
    )
    projection.project_foundry_event(terminal)
    assert projection.project_foundry_event(terminal).status == "duplicate"
    reply = AssistantReply.objects.select_related("message").get(message=message)
    assert reply.content == fragment * 761
    assert reply.message.status == MessageLifecycle.COMPLETED
    assert FoundryEventReceipt.objects.filter(message=message).count() == 763
    assert Activity.objects.count() <= projection.MAX_ACTIVITIES_PER_MESSAGE
    assert Message.objects.filter(conversation=conversation).count() == 1


def test_conversation_caps_preserve_history_and_new_reply(
    conversation_records, monkeypatch
):
    user, workspace, _, binding, conversation, message = conversation_records
    monkeypatch.setattr(projection, "MAX_ACTIVITIES_PER_CONVERSATION", 2)
    monkeypatch.setattr(projection, "MAX_CONVERSATION_TEXT_BYTES", 1)
    for turn in range(2):
        if turn:
            message = Message.objects.create(
                conversation=conversation,
                sequence=2,
                sender="user",
                origin="send",
                content="next",
                send_key_digest="d" * 64,
                content_fingerprint="e" * 64,
            )
        projection.project_foundry_event(
            event_for(
                message,
                binding,
                payload={"kind": "assistant_delta", "text": "whole reply"},
            )
        )
        projection.project_foundry_event(
            event_for(
                message,
                binding,
                attempt_sequence=2,
                event_type="execution.completed",
                payload={"status": "completed"},
            )
        )
    assert (
        list(AssistantReply.objects.values_list("content", flat=True))
        == ["whole reply"] * 2
    )
    assert Activity.objects.count() == 2
    snapshot = projection.read_activity_snapshot(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        replay=True,
    )
    assert [row.sequence for row in snapshot.activities] == [1, 2]
    assert snapshot.state == "completed"
    assert snapshot.assistant_reply.message_id == message.id
    assert snapshot.assistant_reply.content == "whole reply"


def test_reply_byte_limit_keeps_receipts_reachable_and_marks_truncation(
    conversation_records, monkeypatch
):
    _, _, _, binding, _, message = conversation_records
    monkeypatch.setattr(projection, "ASSISTANT_REPLY_MAX_BYTES", 3)
    projection.project_foundry_event(
        event_for(message, binding, payload={"kind": "assistant_delta", "text": "界"})
    )
    crossing = event_for(
        message,
        binding,
        attempt_sequence=2,
        payload={"kind": "assistant_delta", "text": "x"},
    )
    projection.project_foundry_event(crossing)
    projection.project_foundry_event(
        event_for(
            message,
            binding,
            attempt_sequence=3,
            payload={"kind": "assistant_delta", "text": "later"},
        )
    )
    assert AssistantReply.objects.get(message=message).content == "界"
    terminal = projection.project_foundry_event(
        event_for(
            message,
            binding,
            attempt_sequence=4,
            event_type="execution.completed",
            payload={"status": "completed"},
        )
    )
    assert terminal.last_contiguous_sequence == 4
    reply = AssistantReply.objects.get(message=message)
    assert reply.content == "界"
    assert reply.is_truncated
    assert assistant_reply_response(reply)["is_truncated"] is True
    assert FoundryEventReceipt.objects.filter(message=message).count() == 4
    message.refresh_from_db()
    assert message.status == MessageLifecycle.COMPLETED
    assert not message.retry_allowed

    next_message = Message.objects.create(
        conversation=message.conversation,
        sequence=2,
        sender="user",
        origin="send",
        content="next turn",
        send_key_digest="d" * 64,
        content_fingerprint="e" * 64,
    )
    next_result = projection.project_foundry_event(
        event_for(
            next_message,
            binding,
            event_id=uuid4(),
            payload={"kind": "assistant_delta", "text": "reachable"},
        )
    )
    assert next_result.status == "applied"
    assert FoundryEventReceipt.objects.filter(message=next_message).count() == 1

    assert projection.project_foundry_event(crossing).status == "duplicate"


def test_midflight_rollout_never_claims_a_suffix_is_complete(conversation_records):
    _, _, _, binding, _, message = conversation_records
    projection.project_foundry_event(
        event_for(
            message,
            binding,
            payload={"kind": "assistant_delta", "text": "legacy prefix "},
        )
    )
    AssistantReply.objects.filter(message=message).delete()
    projection.project_foundry_event(
        event_for(
            message,
            binding,
            attempt_sequence=2,
            payload={"kind": "assistant_delta", "text": "suffix"},
        )
    )
    projection.project_foundry_event(
        event_for(
            message,
            binding,
            attempt_sequence=3,
            event_type="execution.completed",
            payload={"status": "completed"},
        )
    )
    reply = AssistantReply.objects.get(message=message)
    assert not reply.has_full_prefix
    assert reply.content == "suffix"
    assert (
        "".join(Activity.objects.values_list("text", flat=True))
        == "legacy prefix suffix"
    )


@pytest.mark.parametrize(
    ("event_type", "payload", "allowed"),
    [
        ("execution.failed", {"code": "safe_failure", "retryable": True}, True),
        ("execution.failed", {"code": "outcome_unknown", "retryable": False}, False),
        ("execution.stopped", {"reason": "lease_expired"}, False),
    ],
)
def test_retry_requires_explicit_authenticated_safety(
    conversation_records, event_type, payload, allowed
):
    _, _, _, binding, _, message = conversation_records
    projection.project_foundry_event(
        event_for(message, binding, event_type=event_type, payload=payload)
    )
    message.refresh_from_db()
    assert message.retry_allowed is allowed
    assert is_message_retryable(message) is allowed


@pytest.mark.parametrize(
    "dispatch_state",
    [DispatchState.ACCEPTED, DispatchState.FAILED, DispatchState.RECONCILIATION_NEEDED],
)
def test_stale_unknown_turn_fences_later_projection(
    conversation_records, dispatch_state
):
    _, _, _, binding, conversation, original = conversation_records
    Message.objects.filter(pk=original.pk).update(
        updated_at=timezone.now() - timedelta(minutes=3)
    )
    DispatchOutbox.objects.create(message=original, status=dispatch_state)
    assert not is_message_retryable(original)
    later = Message.objects.create(
        conversation=conversation,
        sequence=2,
        sender="user",
        origin="send",
        content="later",
        send_key_digest="d" * 64,
        content_fingerprint="e" * 64,
    )
    with pytest.raises(ProjectionSequenceGap, match="prior conversation turn"):
        projection.project_foundry_event(event_for(later, binding, event_id=uuid4()))
    assert not FoundryEventReceipt.objects.exists()
    assert not AssistantReply.objects.exists()


def test_terminal_slot_is_reserved_in_wire_contract(conversation_records):
    _, _, _, binding, _, message = conversation_records
    event_for(message, binding, attempt_sequence=100_000)
    event_for(
        message,
        binding,
        attempt_sequence=100_001,
        event_type="execution.failed",
        payload={"code": "event_budget_exhausted", "retryable": False},
    )
    with pytest.raises(ValueError):
        event_for(message, binding, attempt_sequence=100_001)
    with pytest.raises(ValueError):
        event_for(
            message,
            binding,
            attempt_sequence=100_002,
            event_type="execution.completed",
            payload={"status": "completed"},
        )
