import json

import pytest

from chat.models import DispatchOutbox, DispatchState, Message
from chat.services.messages import complete_turn, delete_queued_message
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
    assert calls == [(workspace.id, conversation.id, messages[0].id)] * 2

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


def test_steer_partial_acceptance_replays_through_send_and_stop_retry(
    queue_account, foundry_stops, monkeypatch
):
    from allies.exceptions import FoundryGatewayError

    user, workspace, _ally, conversation, messages = queue_account
    delete_queued_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=messages[1].id,
    )
    client, headers = authenticated_client(user)
    key = "original-send-intent-0001"

    def fail_stop(conversation_id, *, workspace_id, message_id):
        raise FoundryGatewayError("unavailable")

    monkeypatch.setattr("allies.gateways.foundry.stop_conversation", fail_stop)
    failed = steer(client, headers, workspace, conversation, key)

    assert failed.status_code == 500
    recorded = Message.objects.get(
        conversation=conversation, content="Use the blue one"
    )
    replay = client.post(
        f"{base(workspace, conversation)}/messages",
        json.dumps({"content": "Use the blue one", "timezone": ""}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=key,
        **headers,
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["message"]["id"] == str(recorded.id)
    assert replay.json()["data"]["replayed"] is True
    assert (
        Message.objects.filter(
            conversation=conversation, content=recorded.content
        ).count()
        == 1
    )

    monkeypatch.setattr(
        "allies.gateways.foundry.stop_conversation", lambda conversation_id, **scope: 1
    )
    stopped = client.post(f"{base(workspace, conversation)}/stop", **headers)
    assert stopped.status_code == 200
    assert stopped.json()["data"] == {"stop_requested": True}
