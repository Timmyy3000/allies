from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import pytest
from django.test import Client, override_settings

from activities.exceptions import (
    ProjectionConflict,
    ProjectionInvalid,
    ProjectionNotFound,
    ProjectionSequenceGap,
)
from activities.models import Activity, FoundryEventReceipt, ProjectionState
from activities.services import projection as projection_service
from activities.services.projection import project_foundry_event, read_activity_snapshot
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
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessageSender,
)
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
    event = FoundryEventEnvelope.model_validate(fixture["event"])
    receipt = ExecutionReceipt.model_validate(fixture["receipt"])
    reconciliation = ReconciliationReceipt.model_validate(fixture["reconciliation"])

    assert command.fingerprint == canonical_fingerprint(command)
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
        ("MAX_ACTIVITIES_PER_MESSAGE", 1),
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


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
)
def test_activity_snapshot_api_is_bounded_and_hides_foreign_scope(conversation_records):
    user, workspace, _ally, _binding, conversation, _message = conversation_records
    client = Client()
    client.cookies[cookie_name("access")] = issue_session(user).access_token

    response = client.get(
        f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/activities"
    )
    assert response.status_code == 200
    assert response.json()["data"]["conversation_id"] == str(conversation.id)

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
