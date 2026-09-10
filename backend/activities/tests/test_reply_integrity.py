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
from files.models import (
    FileDirection,
    FilePublication,
    FileState,
    FileVersion,
    PublicationState,
)

conversation_records = test_cld005.conversation_records
event_for = test_cld005.event_for


def _publication_file(*, message, binding, state=PublicationState.READY):
    publication = FilePublication.objects.create(
        binding=binding,
        source_message=message,
        request_digest="a" * 64,
        state=state,
    )
    return publication, FileVersion.objects.create(
        workspace=message.conversation.ally.workspace,
        ally=message.conversation.ally,
        owner=message.conversation.ally.workspace.owner,
        source_message=message,
        publication=publication,
        source_version_id=uuid4(),
        direction=FileDirection.OUTBOUND,
        original_name="result.pdf",
        media_type="application/pdf",
        expected_size=3,
        actual_size=3,
        sha256="a" * 64,
        object_key="immutable/reply/result.pdf",
        state=FileState.READY,
    )


@pytest.mark.django_db
def test_reply_file_link_split_across_deltas_is_validated_before_projection(
    conversation_records,
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    _publication, file = _publication_file(message=message, binding=binding)
    projection.project_foundry_event(
        event_for(
            message,
            binding,
            payload={"kind": "assistant_delta", "text": "[result](/fi"},
        )
    )
    reply = AssistantReply.objects.get(message=message)
    assert reply.content == "[result"
    assert reply.pending_file_reference == "](/fi"
    assert Activity.objects.get(message=message).text == "[result"

    projection.project_foundry_event(
        event_for(
            message,
            binding,
            attempt_sequence=2,
            payload={
                "kind": "assistant_delta",
                "text": f"les/{file.id})",
            },
        )
    )
    reply.refresh_from_db()
    assert reply.content == f"[result](/files/{file.id})"
    assert reply.pending_file_reference == ""
    assert assistant_reply_response(reply)["publications"] == [
        {
            "publication_id": str(_publication.id),
            "revision": 1,
            "state": PublicationState.READY,
            "files": [
                {
                    "id": str(file.id),
                    "source_version_id": str(file.source_version_id),
                    "name": "result.pdf",
                    "type": "application/pdf",
                    "size": 3,
                    "sha256": "a" * 64,
                    "state": FileState.READY,
                    "generation": 1,
                    "open_path": f"/files/{file.id}",
                }
            ],
            "retryable": False,
        }
    ]


@pytest.mark.django_db
def test_reply_unready_file_reference_stays_unlinked_and_keeps_publication_state(
    conversation_records,
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    publication, file = _publication_file(
        message=message, binding=binding, state=PublicationState.VALIDATING
    )
    projection.project_foundry_event(
        event_for(
            message,
            binding,
            payload={
                "kind": "assistant_delta",
                "text": f"[result](/files/{file.id})",
            },
        )
    )
    reply = AssistantReply.objects.get(message=message)
    assert "/files/" not in reply.content
    assert "](" not in reply.content
    publication.refresh_from_db()
    assert publication.state == PublicationState.VALIDATING


@pytest.mark.django_db
@pytest.mark.parametrize("partial", ("/fi", "/files/abc", "](/files/550e8400-e29b"))
def test_terminal_flushes_a_partial_file_path_without_changing_external_url(
    conversation_records,
    partial,
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    external = "https://example.test/files/550e8400-e29b-41d4-a716-446655440001"
    projection.project_foundry_event(
        event_for(
            message,
            binding,
            payload={"kind": "assistant_delta", "text": external + " then " + partial},
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
    reply = AssistantReply.objects.get(message=message)
    assert external in reply.content
    assert " then " + partial not in reply.content
    assert "File publication failed" in reply.content


@pytest.mark.django_db
def test_split_markdown_opener_cannot_leave_a_foreign_file_link_clickable(
    conversation_records,
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    foreign_file_id = uuid4()
    for sequence, text in enumerate(
        ("[name](", "/fi", f"les/{foreign_file_id})"), start=1
    ):
        projection.project_foundry_event(
            event_for(
                message,
                binding,
                attempt_sequence=sequence,
                payload={"kind": "assistant_delta", "text": text},
            )
        )

    reply = AssistantReply.objects.get(message=message)
    assert "](" not in reply.content
    assert f"/files/{foreign_file_id}" not in reply.content
    assert "File publication failed" in reply.content


@pytest.mark.django_db
def test_split_external_file_url_is_not_treated_as_a_product_path(conversation_records):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    file_id = uuid4()
    for sequence, text in enumerate(
        ("https://example.test", "/fi", f"les/{file_id}"), start=1
    ):
        projection.project_foundry_event(
            event_for(
                message,
                binding,
                attempt_sequence=sequence,
                payload={"kind": "assistant_delta", "text": text},
            )
        )

    assert AssistantReply.objects.get(message=message).content == (
        f"https://example.test/files/{file_id}"
    )


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


@pytest.mark.django_db
def test_plain_reply_chunks_do_not_query_publication_files(django_assert_num_queries):
    from files.services.publication import sanitize_reply_file_links

    pending = ""
    with django_assert_num_queries(0):
        for chunk in ("Plain text", " and a bracket]", " remains text", " /fi"):
            _visible, pending = sanitize_reply_file_links(
                message_id=uuid4(),
                binding_id=uuid4(),
                text=chunk,
                pending=pending,
            )
    assert pending == "/fi"


@pytest.mark.django_db
@pytest.mark.parametrize("split", (False, True))
@pytest.mark.parametrize("ready", (False, True))
def test_uppercase_file_reference_is_validated(conversation_records, split, ready):
    from files.services.publication import sanitize_reply_file_links

    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    _publication, file = _publication_file(
        message=message,
        binding=binding,
        state=PublicationState.READY if ready else PublicationState.VALIDATING,
    )
    reference = f"[result](/FILES/{str(file.id).upper()})"
    chunks = (reference[:13], reference[13:]) if split else (reference,)
    visible, pending = "", ""
    for chunk in chunks:
        text, pending = sanitize_reply_file_links(
            message_id=message.id,
            binding_id=binding.id,
            text=chunk,
            pending=pending,
            prior_context=visible[-1:],
        )
        visible += text
    assert not pending
    if ready:
        assert visible == f"[result](/files/{file.id})"
    else:
        assert "](" not in visible
        assert "File publication failed" in visible
