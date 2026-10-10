from uuid import uuid4

import pytest

from chat.models import (
    NONTERMINAL_MESSAGE_STATUSES,
    DispatchOutbox,
    DispatchState,
    Message,
    MessagePreparation,
)
from chat.services.messages import accept_message, complete_turn, delete_queued_message
from chat.tests import test_queue_api

authenticated_client = test_queue_api.authenticated_client
queue_account = test_queue_api.queue_account
queue_settings = test_queue_api.queue_settings

pytestmark = pytest.mark.django_db


@pytest.fixture
def foundry_stops(monkeypatch):
    calls = []
    result = {"stopped": 1}

    def stop(conversation_id, *, workspace_id, message_id):
        calls.append((workspace_id, conversation_id, message_id))
        return result["stopped"]

    monkeypatch.setattr("allies.gateways.foundry.stop_conversation", stop)
    return calls, result


def base(workspace, conversation):
    return f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}"


def steer(client, headers, workspace, conversation, message_id):
    return client.post(
        f"{base(workspace, conversation)}/messages/{message_id}/steer",
        **headers,
    )


def active_content(conversation):
    return Message.objects.get(
        conversation=conversation,
        status__in=NONTERMINAL_MESSAGE_STATUSES,
        execution_claimed_at__isnull=False,
    ).content


def test_stop_requests_foundry_stop_and_is_noop_without_active_turn(
    queue_account, foundry_stops
):
    user, workspace, _ally, conversation, messages = queue_account
    calls, _result = foundry_stops
    client, headers = authenticated_client(user)
    target = f"{base(workspace, conversation)}/stop"

    stopped = client.post(target, **headers)

    assert stopped.status_code == 200
    assert stopped.json()["data"] == {"stop_requested": True}
    assert calls == [(workspace.id, conversation.id, messages[0].id)]

    complete_turn(message_id=messages[0].id, status="completed")
    complete_turn(message_id=messages[1].id, status="completed")
    idle = client.post(target, **headers)

    assert idle.status_code == 200
    assert idle.json()["data"] == {"stop_requested": False}
    assert calls == [(workspace.id, conversation.id, messages[0].id)]


def test_stop_terminalizes_unsent_turn_and_releases_queue(queue_account, foundry_stops):
    user, workspace, _ally, conversation, messages = queue_account
    head, tail = messages
    _calls, result = foundry_stops
    result["stopped"] = 0
    DispatchOutbox.objects.get_or_create(message=head)
    client, headers = authenticated_client(user)

    response = client.post(f"{base(workspace, conversation)}/stop", **headers)

    assert response.status_code == 200
    head.refresh_from_db()
    tail.refresh_from_db()
    assert head.status == "stopped"
    assert DispatchOutbox.objects.get(message=head).status == DispatchState.FAILED
    assert tail.execution_claimed_at is not None


def test_steer_queued_message_runs_next_and_stops_active_turn(
    queue_account, foundry_stops
):
    user, workspace, _ally, conversation, messages = queue_account
    head, tail = messages
    calls, _result = foundry_stops
    client, headers = authenticated_client(user)

    response = steer(client, headers, workspace, conversation, tail.id)

    assert response.status_code == 200
    assert response.json()["data"]["id"] == str(tail.id)
    assert response.json()["data"]["queue_state"] == "unclaimed"
    assert calls == [(workspace.id, conversation.id, head.id)]
    tail.refresh_from_db()
    assert tail.steered_at is not None
    assert tail.execution_claimed_at is None

    complete_turn(message_id=head.id, status="stopped")
    assert active_content(conversation) == "Private tail"


def test_latest_steer_runs_first_and_unsteered_messages_keep_queue_order(
    queue_account, foundry_stops
):
    user, workspace, _ally, conversation, messages = queue_account
    head, _tail = messages
    second = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Second",
        idempotency_key="steer-order-second-0001",
    ).message
    third = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Third",
        idempotency_key="steer-order-third-0001",
    ).message
    client, headers = authenticated_client(user)

    assert steer(client, headers, workspace, conversation, second.id).status_code == 200
    assert steer(client, headers, workspace, conversation, third.id).status_code == 200

    complete_turn(message_id=head.id, status="completed")
    assert active_content(conversation) == "Third"
    complete_turn(message_id=third.id, status="completed")
    assert active_content(conversation) == "Second"
    complete_turn(message_id=second.id, status="completed")
    assert active_content(conversation) == "Private tail"


def test_steer_rejects_claimed_deleted_and_unknown_messages(
    queue_account, foundry_stops
):
    user, workspace, _ally, conversation, messages = queue_account
    head, tail = messages
    calls, _result = foundry_stops
    delete_queued_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=tail.id,
    )
    client, headers = authenticated_client(user)

    claimed = steer(client, headers, workspace, conversation, head.id)
    deleted = steer(client, headers, workspace, conversation, tail.id)
    unknown = steer(client, headers, workspace, conversation, uuid4())

    assert claimed.status_code == 409
    assert claimed.json()["data"]["code"] == "steer_unavailable"
    assert deleted.status_code == 409
    assert deleted.json()["data"]["code"] == "steer_unavailable"
    assert unknown.status_code == 404
    assert unknown.json()["data"]["code"] == "conversation_unavailable"
    assert calls == []


def test_steer_is_unavailable_after_the_message_turn_completes(
    queue_account, foundry_stops
):
    user, workspace, _ally, conversation, messages = queue_account
    head, tail = messages
    calls, _result = foundry_stops
    complete_turn(message_id=head.id, status="completed")
    complete_turn(message_id=tail.id, status="completed")
    client, headers = authenticated_client(user)

    response = steer(client, headers, workspace, conversation, tail.id)

    assert response.status_code == 409
    assert response.json()["data"]["code"] == "steer_unavailable"
    assert calls == []


def test_steer_repeat_is_idempotent_and_stops_only_once(queue_account, foundry_stops):
    user, workspace, _ally, conversation, messages = queue_account
    head, tail = messages
    calls, _result = foundry_stops
    client, headers = authenticated_client(user)

    first = steer(client, headers, workspace, conversation, tail.id)
    replay = steer(client, headers, workspace, conversation, tail.id)
    complete_turn(message_id=head.id, status="completed")
    claimed_replay = steer(client, headers, workspace, conversation, tail.id)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert claimed_replay.status_code == 200
    assert claimed_replay.json()["data"]["queue_state"] == "claimed"
    assert calls == [(workspace.id, conversation.id, head.id)]


def test_steer_rejects_message_whose_files_are_not_ready(queue_account, foundry_stops):
    user, workspace, _ally, conversation, messages = queue_account
    _head, tail = messages
    calls, _result = foundry_stops
    Message.objects.filter(pk=tail.pk).update(preparation=MessagePreparation.UPLOADING)
    client, headers = authenticated_client(user)

    response = steer(client, headers, workspace, conversation, tail.id)

    assert response.status_code == 409
    assert response.json()["data"]["code"] == "steer_unavailable"
    tail.refresh_from_db()
    assert tail.steered_at is None
    assert calls == []


def test_steer_stop_failure_keeps_steer_for_the_next_turn(
    queue_account, foundry_stops, monkeypatch
):
    from allies.exceptions import FoundryGatewayError

    user, workspace, _ally, conversation, messages = queue_account
    head, tail = messages
    client, headers = authenticated_client(user)

    def fail_stop(conversation_id, *, workspace_id, message_id):
        raise FoundryGatewayError("unavailable")

    monkeypatch.setattr("allies.gateways.foundry.stop_conversation", fail_stop)
    failed = steer(client, headers, workspace, conversation, tail.id)

    assert failed.status_code == 500
    tail.refresh_from_db()
    assert tail.steered_at is not None
    complete_turn(message_id=head.id, status="stopped")
    assert active_content(conversation) == "Private tail"
