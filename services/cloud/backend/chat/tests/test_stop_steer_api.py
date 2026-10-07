import json

import pytest

from chat.models import DispatchOutbox, DispatchState, Message
from chat.services.messages import complete_turn, delete_queued_message
from chat.tests.test_queue_api import (  # noqa: F401
    authenticated_client,
    queue_account,
    queue_settings,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def foundry_stops(monkeypatch):
    calls = []
    result = {"stopped": 1}

    def stop(conversation_id):
        calls.append(conversation_id)
        return result["stopped"]

    monkeypatch.setattr("allies.gateways.foundry.stop_conversation", stop)
    return calls, result


def base(workspace, conversation):
    return f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}"


def steer(client, headers, workspace, conversation, key="steer-api-key-0001"):
    return client.post(
        f"{base(workspace, conversation)}/steer",
        json.dumps({"content": "Use the blue one"}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=key,
        **headers,
    )


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
    assert calls == [conversation.id]

    complete_turn(message_id=messages[0].id, status="completed")
    complete_turn(message_id=messages[1].id, status="completed")
    idle = client.post(target, **headers)

    assert idle.status_code == 200
    assert idle.json()["data"] == {"stop_requested": False}
    assert calls == [conversation.id]


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


def test_steer_records_turn_stops_active_run_and_replays(queue_account, foundry_stops):
    user, workspace, _ally, conversation, messages = queue_account
    calls, _result = foundry_stops
    delete_queued_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=messages[1].id,
    )
    client, headers = authenticated_client(user)

    first = steer(client, headers, workspace, conversation)
    replay = steer(client, headers, workspace, conversation)

    assert first.status_code == 201
    assert replay.status_code == 200
    message_id = first.json()["data"]["message"]["id"]
    assert replay.json()["data"]["message"]["id"] == message_id
    steered = Message.objects.get(pk=message_id)
    assert (steered.content, steered.status) == ("Use the blue one", "queued")
    assert calls == [conversation.id, conversation.id]

    complete_turn(message_id=messages[0].id, status="stopped")
    steered.refresh_from_db()
    assert steered.execution_claimed_at is not None


def test_steer_is_unavailable_without_active_turn_or_with_server_queue(
    queue_account, foundry_stops
):
    user, workspace, _ally, conversation, messages = queue_account
    calls, _result = foundry_stops
    client, headers = authenticated_client(user)
    count = Message.objects.filter(conversation=conversation).count()

    queued = steer(client, headers, workspace, conversation)
    complete_turn(message_id=messages[0].id, status="completed")
    complete_turn(message_id=messages[1].id, status="completed")
    idle = steer(client, headers, workspace, conversation)

    for response in (queued, idle):
        assert response.status_code == 409
        assert response.json()["data"]["code"] == "steer_unavailable"
    assert Message.objects.filter(conversation=conversation).count() == count
    assert calls == []
