from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import pytest
from django.test import Client, override_settings

from activities.exceptions import (
    ProjectionConflict,
    ProjectionCursorGap,
    ProjectionInvalid,
    ProjectionNotFound,
    ProjectionSequenceGap,
)
from activities.models import Activity, FoundryEventReceipt, ProjectionState
from activities.services import projection as projection_service
from activities.services.projection import (
    parse_activity_cursor,
    project_foundry_event,
    read_activity_snapshot,
    serialize_activity_cursor,
)
from allies.gateways.contracts import (
    ExecutionCommand,
    ExecutionReceipt,
    FoundryEventEnvelope,
    ReconciliationReceipt,
    canonical_fingerprint,
)
from allies.models import Ally, AllyBinding, BindingStatus
from auths.config import cookie_name
from auths.exceptions import WorkspaceAccessDenied
from auths.models import User
from auths.services.sessions import issue_session
from chat.models import (
    Conversation,
    DispatchOutbox,
    DispatchState,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessageSender,
)
from chat.services.dispatch import dispatch_accepted_message
from chat.services.messages import delete_queued_message
from workspaces.models import Membership, Workspace

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "contracts"
    / "foundry-execution-v1.json"
)
EVENT_NAMESPACE = UUID("e8c3ac9d-7d5b-4f6a-9f64-c4fbd1c5be2d")
DEFAULT_ATTEMPT_ID = UUID("f50e8400-e29b-41d4-a716-446655440000")
DEFAULT_EXECUTION_ID = UUID("e50e8400-e29b-41d4-a716-446655440000")


@pytest.mark.parametrize(
    ("outcome", "label"),
    [("completed", "Published file"), ("failed", "Couldn't publish file")],
)
def test_publication_activity_projects_truthful_labels(
    conversation_records, outcome, label
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    identity = {"activity_id": "activity-" + "e" * 32, "activity_kind": "publish_files"}
    started = project_foundry_event(
        event_for(message, binding, event_type="activity.started", payload=identity)
    ).activity
    assert started.text == "Publishing file"
    completed = project_foundry_event(
        event_for(
            message,
            binding,
            event_type="activity.completed",
            attempt_sequence=2,
            payload={**identity, "status": outcome, "duration_ms": 12},
        )
    ).activity
    assert completed.text == label
    assert completed.outcome == outcome
    assert completed.activity_id == started.activity_id


@pytest.mark.parametrize("outcome", ["completed", "failed", "stopped"])
def test_rich_activity_identity_outcomes_and_conflicts(conversation_records, outcome):
    user, workspace, _ally, binding, conversation, message = conversation_records
    first = {"activity_id": "activity-" + "a" * 32, "activity_kind": "web_search"}
    second = {"activity_id": "activity-" + "b" * 32, "activity_kind": "web_search"}
    events = [
        ("activity.started", first),
        ("activity.started", second),
        ("activity.completed", {**second, "status": outcome, "duration_ms": 25}),
        (
            "activity.completed",
            {**second, "status": "failed" if outcome == "completed" else "completed"},
        ),
        ("activity.started", second),
        ("activity.completed", {**first, "status": "completed"}),
        ("execution.stopped", {"reason": "user_requested"}),
    ]
    for sequence, (event_type, payload) in enumerate(events, 1):
        result = project_foundry_event(
            event_for(
                message,
                binding,
                event_type=event_type,
                attempt_sequence=sequence,
                payload=payload,
            )
        )
        assert (result.activity is None) == (sequence in (4, 5))
        if sequence == 3:
            message.refresh_from_db()
            assert message.status == MessageLifecycle.IN_PROGRESS
            assert result.activity.outcome == outcome
            assert result.activity.activity_id == second["activity_id"]
            assert result.activity.duration_ms == 25
            assert (result.activity.text == "Searched the web") == (
                outcome == "completed"
            )
    snapshot = read_activity_snapshot(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        replay=True,
    )
    assert [row.sequence for row in snapshot.activities] == [1, 2, 3, 4, 5]
    assert snapshot.last_contiguous_sequence == 7
    assert FoundryEventReceipt.objects.filter(message=message).count() == 7
    assert snapshot.activities[-1].state == "stopped"


@pytest.mark.parametrize(
    "payload",
    [
        {"activity_id": "activity-" + "a" * 32},
        {"activity_id": "activity-" + "a" * 32, "activity_kind": "private_custom_tool"},
        {
            "activity_id": "activity-" + "a" * 32,
            "activity_kind": "web_search",
            "kind": "tool",
        },
        {"activity_id": "raw-private-id", "activity_kind": "web_search"},
        {
            "activity_id": "activity-" + "a" * 32,
            "activity_kind": "web_search",
            "args": {"query": "private"},
        },
    ],
)
def test_rich_activity_rejects_partial_hybrid_and_private_payloads(
    conversation_records, payload
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    with pytest.raises(ValueError):
        event_for(message, binding, event_type="activity.started", payload=payload)


@pytest.mark.parametrize("duration", [True, -1, 86_400_001, 0.5, "20", None])
def test_rich_activity_rejects_invalid_duration(conversation_records, duration):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    with pytest.raises(ValueError):
        event_for(
            message,
            binding,
            event_type="activity.completed",
            payload={
                "activity_id": "activity-" + "a" * 32,
                "activity_kind": "web_search",
                "status": "completed",
                "duration_ms": duration,
            },
        )


def test_activity_public_metadata_does_not_expose_foundry_attempt(conversation_records):
    from activities.api.schemas import ActivityResponse
    from activities.presentation import ACTIVITY_LABELS, activity_metadata
    from allies.gateways.contracts import ACTIVITY_KINDS

    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    assert ACTIVITY_LABELS.keys() == ACTIVITY_KINDS
    row = project_foundry_event(event_for(message, binding)).activity
    metadata = activity_metadata(row)
    assert metadata["activity_attempt_id"].startswith("attempt-")
    assert len(metadata["activity_attempt_id"]) == 40
    public = ActivityResponse(
        id=row.id,
        message_id=row.message_id,
        sequence=row.sequence,
        conversation_turn_ordinal=row.conversation_turn_ordinal,
        kind=row.kind,
        text=row.text,
        state=row.state,
        created_at=row.created_at,
        **metadata,
    ).model_dump_json()
    assert str(DEFAULT_ATTEMPT_ID) not in public
    assert metadata["activity_id"] is None


def test_hidden_terminal_receipt_prevents_visible_contradiction(
    conversation_records, monkeypatch
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    rich = {"activity_id": "activity-" + "c" * 32, "activity_kind": "web_search"}
    project_foundry_event(
        event_for(message, binding, event_type="activity.started", payload=rich)
    )
    with monkeypatch.context() as scoped:
        scoped.setattr(projection_service, "MAX_AGGREGATE_TEXT_BYTES", 0)
        hidden = project_foundry_event(
            event_for(
                message,
                binding,
                event_type="activity.completed",
                attempt_sequence=2,
                payload={**rich, "status": "failed"},
            )
        )
    assert hidden.activity is None
    conflict = project_foundry_event(
        event_for(
            message,
            binding,
            event_type="activity.completed",
            attempt_sequence=3,
            payload={**rich, "status": "completed"},
        )
    )
    assert conflict.activity is None
    assert FoundryEventReceipt.objects.get(attempt_sequence=2).outcome == "failed"
    assert conflict.last_contiguous_sequence == 3


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
    ALLIES_ACTIVITY_SSE_ENABLED=True,
)
def test_rich_snapshot_and_sse_share_private_safe_metadata(conversation_records):
    user, workspace, _ally, binding, conversation, message = conversation_records
    rich = {"activity_id": "activity-" + "d" * 32, "activity_kind": "memory_recall"}
    for sequence, (kind, payload) in enumerate(
        [
            ("activity.started", {"kind": "tool"}),
            ("activity.started", rich),
            ("activity.completed", {**rich, "status": "completed", "duration_ms": 100}),
        ],
        1,
    ):
        project_foundry_event(
            event_for(
                message,
                binding,
                event_type=kind,
                attempt_sequence=sequence,
                payload=payload,
            )
        )
    client = Client()
    client.cookies[cookie_name("access")] = issue_session(user).access_token
    path = (
        f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/activities"
    )
    response = client.get(path)
    assert response.status_code == 200
    rows = response.json()["data"]["activities"]
    assert rows[0]["activity_id"] is None
    assert rows[1]["activity_id"] == rich["activity_id"]
    assert rows[2]["outcome"] == "completed"
    assert rows[1]["activity_attempt_id"] == rows[2]["activity_attempt_id"]
    stream = client.get(
        path + "/stream", {"cursor": serialize_activity_cursor(conversation.id)}
    )
    assert stream.status_code == 200
    iterator = iter(stream.streaming_content)
    try:
        assert b"event: ready" in next(iterator)
        streamed = []
        for _ in range(3):
            chunk = next(iterator).decode()
            data = next(
                line[6:] for line in chunk.splitlines() if line.startswith("data: ")
            )
            streamed.append(json.loads(data)["activity"])
    finally:
        stream.close()
    for snapshot, streamed_row in zip(rows, streamed, strict=True):
        for key in (
            "activity_id",
            "activity_kind",
            "activity_attempt_id",
            "outcome",
            "duration_ms",
        ):
            assert snapshot[key] == streamed_row[key]
    assert str(DEFAULT_ATTEMPT_ID) not in json.dumps([rows, streamed])


def test_terminal_projection_claims_only_next_turn_and_duplicate_does_not_advance(
    conversation_records,
):
    user, workspace, _ally, binding, conversation, head = conversation_records
    conversation.is_default = False
    conversation.save(update_fields=("is_default", "updated_at"))
    dispatch_accepted_message(head)
    tails = [
        Message.objects.create(
            conversation=conversation,
            sequence=sequence,
            sender=MessageSender.USER,
            origin=MessageOrigin.SEND,
            status=MessageLifecycle.QUEUED,
            content=f"Tail {sequence}",
            send_key_digest=str(sequence) * 64,
            content_fingerprint=str(sequence) * 64,
        )
        for sequence in (2, 3)
    ]
    for tail in tails:
        dispatch_accepted_message(tail)
        tail.refresh_from_db()
    DispatchOutbox.objects.filter(message=head).update(status=DispatchState.ACCEPTED)
    snapshot = read_activity_snapshot(
        user=user, workspace_id=workspace.id, conversation_id=conversation.id
    )
    assert snapshot.active_message_id == head.id
    assert all(tail.execution_claimed_at is None for tail in tails)
    project_foundry_event(event_for(head, binding, attempt_sequence=1))
    terminal = event_for(
        head,
        binding,
        event_type="execution.completed",
        attempt_sequence=2,
        payload={"status": "completed"},
    )
    assert project_foundry_event(terminal).status == "applied"
    tails[0].refresh_from_db()
    tails[1].refresh_from_db()
    claimed_at = tails[0].execution_claimed_at
    assert claimed_at is not None and tails[1].execution_claimed_at is None
    assert project_foundry_event(terminal).status == "duplicate"
    tails[0].refresh_from_db()
    tails[1].refresh_from_db()
    assert tails[0].execution_claimed_at == claimed_at
    assert tails[1].execution_claimed_at is None
    assert (
        read_activity_snapshot(
            user=user, workspace_id=workspace.id, conversation_id=conversation.id
        ).active_message_id
        == tails[0].id
    )


def test_deleted_tail_does_not_replace_completed_snapshot_reply(conversation_records):
    user, workspace, _ally, binding, conversation, head = conversation_records
    conversation.is_default = False
    conversation.save(update_fields=("is_default", "updated_at"))
    dispatch_accepted_message(head)
    tail = Message.objects.create(
        conversation=conversation,
        sequence=2,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        status=MessageLifecycle.QUEUED,
        content="Delete this tail",
        send_key_digest="d" * 64,
        content_fingerprint="e" * 64,
    )
    dispatch_accepted_message(tail)
    delete_queued_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=tail.id,
    )
    project_foundry_event(event_for(head, binding, attempt_sequence=1))
    project_foundry_event(
        event_for(
            head,
            binding,
            event_type="execution.completed",
            attempt_sequence=2,
            payload={"status": "completed"},
        )
    )
    snapshot = read_activity_snapshot(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
    )
    assert snapshot.active_message_id is None
    assert snapshot.state == ProjectionState.COMPLETED
    assert snapshot.assistant_reply.message_id == head.id
    assert snapshot.assistant_reply.content == "safe bounded fragment"
    assert snapshot.last_contiguous_sequence == 2


@pytest.fixture
def conversation_records(db):
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
    return user, workspace, ally, binding, conversation, message


def event_for(
    message: Message,
    binding: AllyBinding,
    *,
    event_type: str = "message.delta",
    attempt_sequence: int = 1,
    event_id: UUID | None = None,
    attempt_id: UUID = DEFAULT_ATTEMPT_ID,
    execution_id: UUID = DEFAULT_EXECUTION_ID,
    generation: int = 3,
    payload: dict | None = None,
    workspace_id: UUID | None = None,
    binding_id: UUID | None = None,
) -> FoundryEventEnvelope:
    if payload is None:
        payload = {"kind": "assistant_delta", "text": "safe bounded fragment"}
    values = {
        "schema_version": "v1",
        "kind": "execution.event",
        "producer": "foundry",
        "service_identity": "foundry-service",
        "event_id": str(
            event_id or uuid5(EVENT_NAMESPACE, f"event-{attempt_sequence}")
        ),
        "event_dedupe_key": f"execution:{attempt_id}:{generation}:{attempt_sequence}",
        "scope": {
            "kind": "workspace",
            "cloud_workspace_id": str(
                workspace_id or message.conversation.ally.workspace_id
            ),
        },
        "cloud": {
            "ally_id": str(message.conversation.ally_id),
            "conversation_id": str(message.conversation_id),
            "message_id": str(message.id),
            "cloud_binding_id": str(binding_id or binding.id),
        },
        "conversation_turn_ordinal": message.sequence,
        "foundry": {
            "execution_id": str(execution_id),
            "attempt_id": str(attempt_id),
            "generation": generation,
            "attempt_sequence": attempt_sequence,
        },
        "event_type": event_type,
        "payload": payload,
        "issued_at": "2026-08-25T12:00:01Z",
    }
    values["fingerprint"] = canonical_fingerprint(values)
    return FoundryEventEnvelope.model_validate(values)


def test_v1_fixture_is_strict_and_cloud_types_match_contract():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    command = ExecutionCommand.model_validate(fixture["command"])
    bootstrap_command = ExecutionCommand.model_validate(fixture["bootstrap_command"])
    event = FoundryEventEnvelope.model_validate(fixture["event"])
    receipt = ExecutionReceipt.model_validate(fixture["receipt"])
    reconciliation = ReconciliationReceipt.model_validate(fixture["reconciliation"])

    assert command.fingerprint == canonical_fingerprint(command)
    assert bootstrap_command.fingerprint == canonical_fingerprint(bootstrap_command)
    assert "absent or null" in fixture["canonicalization"]["optional_fields"]
    assert event.fingerprint == canonical_fingerprint(event)
    assert receipt.fingerprint == command.fingerprint
    assert reconciliation.fingerprint == command.fingerprint
    assert command.conversation_turn_ordinal == event.conversation_turn_ordinal
    assert set(command.model_dump(mode="json")) == {
        "schema_version",
        "kind",
        "producer",
        "service_identity",
        "command_id",
        "idempotency_key",
        "scope",
        "conversation_turn_ordinal",
        "cloud",
        "source_kind",
        "payload",
        "issued_at",
        "deadline_at",
        "fingerprint",
    }


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update({"schema_version": "v2"}),
        lambda value: value.update({"unexpected": True}),
        lambda value: value.update(
            {"fingerprint": "canonical-json-sha256:v1:" + "0" * 64}
        ),
    ],
)
def test_v1_contract_rejects_unknown_or_conflicting_command_shapes(mutator):
    value = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["command"]
    mutator(value)

    with pytest.raises(ValueError):
        ExecutionCommand.model_validate(value)


def test_event_projection_is_idempotent_and_conflicts_do_not_mutate(
    conversation_records,
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    event = event_for(message, binding)

    first = project_foundry_event(event)
    duplicate = project_foundry_event(event)

    assert first.status == "applied"
    assert duplicate.status == "duplicate"
    assert Activity.objects.count() == 1
    assert FoundryEventReceipt.objects.count() == 1

    conflicting = event_for(
        message,
        binding,
        event_id=event.event_id,
        payload={"kind": "assistant_delta", "text": "different"},
    )
    with pytest.raises(ProjectionConflict):
        project_foundry_event(conflicting)
    assert Activity.objects.count() == 1
    assert FoundryEventReceipt.objects.count() == 1

    sequence_conflict = event_for(
        message,
        binding,
        attempt_sequence=1,
        event_id=uuid4(),
    )
    with pytest.raises(ProjectionConflict):
        project_foundry_event(sequence_conflict)
    assert Activity.objects.count() == 1


def test_event_sequence_gaps_are_held_until_the_missing_event_arrives(
    conversation_records,
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    second = event_for(message, binding, attempt_sequence=2)

    with pytest.raises(ProjectionSequenceGap):
        project_foundry_event(second)
    assert Activity.objects.count() == 0
    assert FoundryEventReceipt.objects.count() == 0

    first = event_for(message, binding, attempt_sequence=1)
    project_foundry_event(first)
    result = project_foundry_event(second)

    assert result.status == "applied"
    assert result.last_contiguous_sequence == 2
    assert list(Activity.objects.values_list("sequence", flat=True)) == [1, 2]


def test_generation_zero_matches_the_shared_foundry_contract(conversation_records):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records

    result = project_foundry_event(event_for(message, binding, generation=0))

    assert result.status == "applied"
    assert Activity.objects.get(pk=result.activity.id).generation == 0


def test_terminal_state_is_monotonic(
    conversation_records,
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    project_foundry_event(event_for(message, binding, attempt_sequence=1))
    completed = event_for(
        message,
        binding,
        event_type="execution.completed",
        attempt_sequence=2,
        payload={"status": "completed"},
    )
    project_foundry_event(completed)
    message.refresh_from_db()
    assert message.status == MessageLifecycle.COMPLETED

    late = event_for(
        message,
        binding,
        event_type="activity.started",
        attempt_sequence=3,
        payload={"kind": "tool"},
    )
    with pytest.raises(ProjectionConflict):
        project_foundry_event(late)
    assert Activity.objects.count() == 2
    assert Message.objects.get(pk=message.pk).status == MessageLifecycle.COMPLETED


def test_event_execution_identity_cannot_switch_mid_turn(conversation_records):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    project_foundry_event(event_for(message, binding, attempt_sequence=1))

    with pytest.raises(ProjectionConflict):
        project_foundry_event(
            event_for(
                message,
                binding,
                attempt_sequence=2,
                event_id=uuid4(),
                execution_id=uuid4(),
            )
        )
    assert Activity.objects.count() == 1
    assert FoundryEventReceipt.objects.count() == 1


def test_cross_scope_event_is_privacy_safe_and_does_not_mutate(
    conversation_records,
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    foreign_scope = uuid4()
    event = event_for(message, binding, workspace_id=foreign_scope)

    with pytest.raises(ProjectionNotFound):
        project_foundry_event(event)
    assert Activity.objects.count() == 0
    assert FoundryEventReceipt.objects.count() == 0

    foreign_binding = event_for(message, binding, binding_id=uuid4())
    with pytest.raises(ProjectionNotFound):
        project_foundry_event(foreign_binding)
    assert Activity.objects.count() == 0


@pytest.mark.parametrize(
    ("bound", "limit"),
    [
        ("MAX_EVENT_RECEIPTS_PER_MESSAGE", 1),
    ],
)
def test_projection_bounds_reject_exhaustion_without_mutation(
    conversation_records, monkeypatch, bound, limit
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    project_foundry_event(event_for(message, binding, attempt_sequence=1))
    monkeypatch.setattr(projection_service, bound, limit)

    with pytest.raises(ProjectionInvalid):
        project_foundry_event(
            event_for(
                message,
                binding,
                attempt_sequence=2,
                event_id=uuid4(),
                payload={"kind": "assistant_delta", "text": "next fragment"},
            )
        )

    message.refresh_from_db()
    assert Activity.objects.count() == 1
    assert FoundryEventReceipt.objects.count() == 1
    assert message.status == MessageLifecycle.IN_PROGRESS


def test_projection_limits_reserve_capacity_for_terminal_truth(
    conversation_records, monkeypatch
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    for bound in (
        "MAX_ACTIVITIES_PER_MESSAGE",
        "MAX_ACTIVITIES_PER_CONVERSATION",
        "MAX_EVENT_RECEIPTS_PER_MESSAGE",
    ):
        monkeypatch.setattr(projection_service, bound, 2)

    project_foundry_event(event_for(message, binding, attempt_sequence=1))
    with pytest.raises(ProjectionInvalid):
        project_foundry_event(
            event_for(
                message,
                binding,
                attempt_sequence=2,
                event_id=uuid4(),
                payload={"kind": "assistant_delta", "text": "crowded out"},
            )
        )

    terminal = project_foundry_event(
        event_for(
            message,
            binding,
            event_type="execution.completed",
            attempt_sequence=2,
            event_id=uuid4(),
            payload={"status": "completed"},
        )
    )

    message.refresh_from_db()
    assert terminal.status == "applied"
    assert message.status == MessageLifecycle.COMPLETED
    assert Activity.objects.count() == 2
    assert FoundryEventReceipt.objects.count() == 2


@pytest.mark.parametrize(
    ("bound", "limit", "terminal_is_visible"),
    [
        ("MAX_ACTIVITIES_PER_CONVERSATION", 1, False),
        ("MAX_CONVERSATION_TEXT_BYTES", len(b"safe bounded fragment"), True),
    ],
)
def test_conversation_projection_bounds_preserve_terminal_sequence(
    conversation_records, monkeypatch, bound, limit, terminal_is_visible
):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    first = project_foundry_event(event_for(message, binding, attempt_sequence=1))
    monkeypatch.setattr(projection_service, bound, limit)

    suppressed = project_foundry_event(
        event_for(
            message,
            binding,
            attempt_sequence=2,
            event_id=uuid4(),
            payload={"kind": "assistant_delta", "text": "next fragment"},
        )
    )
    terminal = project_foundry_event(
        event_for(
            message,
            binding,
            event_type="execution.completed",
            attempt_sequence=3,
            event_id=uuid4(),
            payload={"status": "completed"},
        )
    )

    message.refresh_from_db()
    assert first.activity is not None
    assert suppressed.activity is None
    assert (terminal.activity is not None) is terminal_is_visible
    assert message.status == MessageLifecycle.COMPLETED
    assert FoundryEventReceipt.objects.count() == 3
    assert Activity.objects.count() == 1 + terminal_is_visible
    assert terminal.last_contiguous_sequence == 3


def test_message_text_bound_preserves_terminal_sequence(conversation_records):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    fragment = "x" * (16 * 1024)
    for sequence in range(1, 5):
        result = project_foundry_event(
            event_for(
                message,
                binding,
                attempt_sequence=sequence,
                event_id=uuid4(),
                payload={"kind": "assistant_delta", "text": fragment},
            )
        )
        assert result.activity is not None

    suppressed = project_foundry_event(
        event_for(
            message,
            binding,
            attempt_sequence=5,
            event_id=uuid4(),
            payload={"kind": "assistant_delta", "text": "over budget"},
        )
    )
    terminal = project_foundry_event(
        event_for(
            message,
            binding,
            event_type="execution.completed",
            attempt_sequence=6,
            event_id=uuid4(),
            payload={"status": "completed"},
        )
    )

    message.refresh_from_db()
    assert suppressed.activity is None
    assert terminal.last_contiguous_sequence == 6
    assert message.status == MessageLifecycle.COMPLETED
    assert FoundryEventReceipt.objects.count() == 6


@pytest.mark.postgresql
def test_projection_text_budget_counts_utf8_bytes(conversation_records, monkeypatch):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    first = project_foundry_event(
        event_for(
            message,
            binding,
            attempt_sequence=1,
            payload={"kind": "assistant_delta", "text": "界"},
        )
    )
    monkeypatch.setattr(projection_service, "MAX_AGGREGATE_TEXT_BYTES", 3)

    result = project_foundry_event(
        event_for(
            message,
            binding,
            attempt_sequence=2,
            event_id=uuid4(),
            payload={"kind": "assistant_delta", "text": "x"},
        )
    )

    assert first.activity is not None
    assert result.activity is None
    assert FoundryEventReceipt.objects.filter(message=message).count() == 2


def test_activity_snapshot_is_bounded_and_capability_scoped(conversation_records):
    user, workspace, _ally, _binding, conversation, message = conversation_records
    for sequence in range(1, 205):
        Activity.objects.create(
            conversation=conversation,
            message=message,
            sequence=sequence,
            conversation_turn_ordinal=message.sequence,
            generation=3,
            attempt_id=uuid5(EVENT_NAMESPACE, f"attempt-{sequence}"),
            attempt_sequence=sequence,
            event_id=uuid5(EVENT_NAMESPACE, f"event-{sequence}"),
            event_type="message.delta",
            kind="assistant_delta",
            text="safe",
            state=ProjectionState.RUNNING,
            event_fingerprint="canonical-json-sha256:v1:" + "a" * 64,
        )

    snapshot = read_activity_snapshot(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        limit=200,
    )
    assert len(snapshot.activities) == 200
    assert snapshot.activities[0].sequence == 5
    assert snapshot.activities[-1].sequence == 204

    with pytest.raises(ProjectionInvalid):
        read_activity_snapshot(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            limit=201,
        )

    foreign_user = User.objects.create_user()
    with pytest.raises(WorkspaceAccessDenied):
        read_activity_snapshot(
            user=foreign_user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
        )


def test_activity_snapshot_maps_active_message_to_running(conversation_records):
    user, workspace, _ally, _binding, conversation, message = conversation_records
    message.status = MessageLifecycle.IN_PROGRESS
    message.save(update_fields=("status", "updated_at"))

    snapshot = read_activity_snapshot(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
    )

    assert snapshot.state == ProjectionState.RUNNING


def test_activity_replay_pages_from_a_signed_cursor(conversation_records):
    user, workspace, _ally, _binding, conversation, message = conversation_records
    for sequence in range(1, 6):
        Activity.objects.create(
            conversation=conversation,
            message=message,
            sequence=sequence,
            conversation_turn_ordinal=message.sequence,
            generation=1,
            attempt_id=uuid5(EVENT_NAMESPACE, f"replay-attempt-{sequence}"),
            attempt_sequence=sequence,
            event_id=uuid5(EVENT_NAMESPACE, f"replay-event-{sequence}"),
            event_type="message.delta",
            kind="assistant_delta",
            text=f"part-{sequence}",
            state=ProjectionState.RUNNING,
            event_fingerprint="canonical-json-sha256:v1:" + "b" * 64,
        )

    first = read_activity_snapshot(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        limit=3,
        replay=True,
    )
    assert [activity.sequence for activity in first.activities] == [1, 2, 3]
    assert first.next_cursor == first.resume_cursor

    second = read_activity_snapshot(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        limit=3,
        cursor=first.next_cursor,
        replay=True,
    )
    assert [activity.sequence for activity in second.activities] == [4, 5]
    assert second.next_cursor is None
    resumed = parse_activity_cursor(second.resume_cursor, conversation.id)
    assert (resumed.after_sequence, resumed.high_water_sequence) == (5, 5)


def test_activity_replay_rejects_a_cursor_before_retained_history(conversation_records):
    user, workspace, _ally, _binding, conversation, message = conversation_records
    Activity.objects.create(
        conversation=conversation,
        message=message,
        sequence=3,
        conversation_turn_ordinal=message.sequence,
        generation=1,
        attempt_id=uuid5(EVENT_NAMESPACE, "gap-attempt"),
        attempt_sequence=1,
        event_id=uuid5(EVENT_NAMESPACE, "gap-event"),
        event_type="message.delta",
        kind="assistant_delta",
        text="part-3",
        state=ProjectionState.COMPLETED,
        event_fingerprint="canonical-json-sha256:v1:" + "c" * 64,
    )

    with pytest.raises(ProjectionCursorGap):
        read_activity_snapshot(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            replay=True,
        )


def test_activity_cursor_has_exact_shape_and_forward_exclusive_origin(
    conversation_records,
):
    user, workspace, _ally, _binding, conversation, message = conversation_records
    for sequence in range(1, 4):
        Activity.objects.create(
            conversation=conversation,
            message=message,
            sequence=sequence,
            conversation_turn_ordinal=message.sequence,
            generation=1,
            attempt_id=uuid5(EVENT_NAMESPACE, f"cursor-attempt-{sequence}"),
            attempt_sequence=sequence,
            event_id=uuid5(EVENT_NAMESPACE, f"cursor-event-{sequence}"),
            event_type="message.delta",
            kind="assistant_delta",
            text=str(sequence),
            state=ProjectionState.RUNNING,
            event_fingerprint="canonical-json-sha256:v1:" + "d" * 64,
        )

    snapshot = read_activity_snapshot(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        limit=2,
        replay=True,
    )
    assert [activity.sequence for activity in snapshot.activities] == [1, 2]
    assert snapshot.last_contiguous_activity_sequence == 3
    assert snapshot.resume_cursor is not None
    encoded = snapshot.resume_cursor.split(".", 1)[0]
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    assert set(payload) == {"v", "t", "c", "a", "h", "e"}
    parsed = parse_activity_cursor(snapshot.resume_cursor, conversation.id)
    assert parsed.after_sequence == 2
    assert parsed.high_water_sequence == 3


def test_activity_replay_holds_high_water_until_next_forward_poll(conversation_records):
    user, workspace, _ally, _binding, conversation, message = conversation_records
    for sequence in range(1, 4):
        Activity.objects.create(
            conversation=conversation,
            message=message,
            sequence=sequence,
            conversation_turn_ordinal=message.sequence,
            generation=1,
            attempt_id=uuid5(EVENT_NAMESPACE, f"high-water-attempt-{sequence}"),
            attempt_sequence=sequence,
            event_id=uuid5(EVENT_NAMESPACE, f"high-water-event-{sequence}"),
            event_type="message.delta",
            kind="assistant_delta",
            text=str(sequence),
            state=ProjectionState.RUNNING,
            event_fingerprint="canonical-json-sha256:v1:" + "e" * 64,
        )

    first = read_activity_snapshot(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        limit=2,
        replay=True,
    )
    Activity.objects.create(
        conversation=conversation,
        message=message,
        sequence=4,
        conversation_turn_ordinal=message.sequence,
        generation=1,
        attempt_id=uuid5(EVENT_NAMESPACE, "high-water-attempt-4"),
        attempt_sequence=4,
        event_id=uuid5(EVENT_NAMESPACE, "high-water-event-4"),
        event_type="message.delta",
        kind="assistant_delta",
        text="4",
        state=ProjectionState.RUNNING,
        event_fingerprint="canonical-json-sha256:v1:" + "e" * 64,
    )
    second = read_activity_snapshot(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        limit=2,
        cursor=first.next_cursor,
        replay=True,
    )
    assert [activity.sequence for activity in second.activities] == [3]
    assert (
        parse_activity_cursor(second.resume_cursor, conversation.id).high_water_sequence
        == 3
    )

    forward = read_activity_snapshot(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        limit=2,
        cursor=second.resume_cursor,
        replay=True,
    )
    assert [activity.sequence for activity in forward.activities] == [4]
    assert (
        parse_activity_cursor(
            forward.resume_cursor, conversation.id
        ).high_water_sequence
        == 4
    )


def test_activity_cursor_rejects_message_cursor_tampering_and_expiry(
    conversation_records,
):
    _user, _workspace, _ally, _binding, conversation, _message = conversation_records
    from chat.services.messages import serialize_cursor

    message_cursor = serialize_cursor(conversation.id, 1)
    with pytest.raises(projection_service.ProjectionCursorInvalid):
        parse_activity_cursor(message_cursor, conversation.id)
    with pytest.raises(projection_service.ProjectionCursorInvalid):
        parse_activity_cursor("not-a-cursor", conversation.id)

    activity_cursor = serialize_activity_cursor(conversation.id, 0, 0)
    encoded, signature = activity_cursor.split(".", 1)
    tampered = f"{encoded}.{'0' if signature[0] != '0' else '1'}{signature[1:]}"
    with pytest.raises(projection_service.ProjectionCursorInvalid):
        parse_activity_cursor(tampered, conversation.id)

    issued = datetime(2026, 1, 1, tzinfo=UTC)
    expired = serialize_activity_cursor(conversation.id, 0, 0, now=issued)
    with pytest.raises(projection_service.ProjectionCursorExpired):
        parse_activity_cursor(expired, conversation.id, now=issued + timedelta(hours=2))


def test_empty_activity_replay_returns_zero_metadata_and_origin_cursor(
    conversation_records,
):
    user, workspace, _ally, _binding, _conversation, _message = conversation_records
    ally = Ally.objects.create(
        workspace=workspace,
        name="Nova",
        job="Study partner",
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    AllyBinding.objects.create(
        ally=ally,
        status=BindingStatus.BOUND,
        receipt_digest="c" * 64,
    )
    conversation = Conversation.objects.create(ally=ally)

    snapshot = read_activity_snapshot(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        replay=True,
    )

    assert snapshot.activities == ()
    assert snapshot.state == ProjectionState.COMPLETED
    assert snapshot.last_contiguous_sequence == 0
    assert snapshot.last_contiguous_activity_sequence == 0
    assert snapshot.oldest_sequence is None
    assert snapshot.latest_sequence is None
    assert snapshot.next_cursor is None
    assert (
        parse_activity_cursor(snapshot.resume_cursor, conversation.id).after_sequence
        == 0
    )


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
    ALLIES_ACTIVITY_SSE_ENABLED=True,
)
def test_activity_snapshot_api_exposes_truncated_reply_and_hides_foreign_scope(
    conversation_records, monkeypatch
):
    user, workspace, _ally, _binding, conversation, _message = conversation_records
    monkeypatch.setattr(projection_service, "ASSISTANT_REPLY_MAX_BYTES", 3)
    project_foundry_event(
        event_for(
            _message,
            _binding,
            payload={"kind": "assistant_delta", "text": "界"},
        )
    )
    project_foundry_event(
        event_for(
            _message,
            _binding,
            attempt_sequence=2,
            payload={"kind": "assistant_delta", "text": "x"},
        )
    )
    project_foundry_event(
        event_for(
            _message,
            _binding,
            attempt_sequence=3,
            event_type="execution.completed",
            payload={"status": "completed"},
        )
    )
    client = Client()
    client.cookies[cookie_name("access")] = issue_session(user).access_token

    response = client.get(
        f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/activities"
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["conversation_id"] == str(conversation.id)
    assert data["assistant_reply"]["content"] == "界"
    assert data["assistant_reply"]["has_full_prefix"] is True
    assert data["assistant_reply"]["is_truncated"] is True
    assert data["assistant_reply"]["status"] == "completed"

    foreign_workspace = Workspace.objects.create(
        owner=User.objects.create_user(), name="Other"
    )
    foreign_response = client.get(
        f"/api/v1/workspaces/{foreign_workspace.id}/conversations/{conversation.id}/activities"
    )
    assert foreign_response.status_code == 404
    assert foreign_response.json() == {
        "status": "error",
        "message": "activity unavailable",
        "data": {"code": "activity_unavailable"},
    }
    foreign_stream_response = client.get(
        f"/api/v1/workspaces/{foreign_workspace.id}/conversations/"
        f"{conversation.id}/activities/stream"
    )
    assert foreign_stream_response.status_code == 404
    assert foreign_stream_response.json() == foreign_response.json()


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_FOUNDRY_EXECUTION_ENABLED=True,
    ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN="event-secret",
)
def test_foundry_event_auth_runs_before_malformed_body_binding(conversation_records):
    path = "/api/v1/internal/foundry/events"
    responses = [
        Client().post(path, data="{", content_type="application/json"),
        Client().post(
            path,
            data="{",
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer wrong-secret",
        ),
        Client().post(
            path,
            data="{",
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer sécret",
        ),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401]
    assert responses[0].json() == responses[1].json() == responses[2].json()


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_FOUNDRY_EXECUTION_ENABLED=True,
    ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN="event-secret",
)
def test_foundry_event_conflict_codes_are_stable_and_typed(conversation_records):
    _user, _workspace, _ally, binding, _conversation, message = conversation_records
    client = Client()
    path = "/api/v1/internal/foundry/events"
    headers = {"HTTP_AUTHORIZATION": "Bearer event-secret"}

    gap = client.post(
        path,
        data=event_for(message, binding, attempt_sequence=2).model_dump_json(),
        content_type="application/json",
        **headers,
    )
    assert gap.status_code == 409
    assert gap.json() == {"code": "sequence_gap"}

    first = event_for(message, binding, attempt_sequence=1)
    assert (
        client.post(
            path,
            data=first.model_dump_json(),
            content_type="application/json",
            **headers,
        ).status_code
        == 202
    )
    conflict = client.post(
        path,
        data=event_for(
            message, binding, attempt_sequence=1, event_id=uuid4()
        ).model_dump_json(),
        content_type="application/json",
        **headers,
    )
    assert conflict.status_code == 409
    assert conflict.json() == {"code": "conflict"}
