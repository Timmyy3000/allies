import pytest
from django.utils import timezone

from allies.exceptions import FoundryGatewayUnknownOutcome
from chat.models import DispatchOutbox, DispatchState, Message
from chat.services.dispatch import dispatch_accepted_message, dispatch_pending_messages
from chat.services.messages import complete_turn, delete_queued_message
from chat.tests import test_dispatch, test_queue_api

queue_settings = test_queue_api.queue_settings
queue_account = test_queue_api.queue_account
dispatch_records = test_dispatch.dispatch_records
pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("response_lost", [False, True])
def test_stop_during_admission_fences_selected_message(
    dispatch_records, monkeypatch, settings, response_lost
):
    settings.ALLIES_FOUNDRY_EXECUTION_ENABLED = True
    workspace, _binding, conversation, message = dispatch_records
    dispatch_accepted_message(message)
    client, headers = test_queue_api.authenticated_client(workspace.owner)
    fences = []

    def stop(conversation_id, *, workspace_id=None, message_id=None):
        fences.append((workspace_id, conversation_id, message_id))
        return 0

    def admit(command, *, raw_body=None):
        assert DispatchOutbox.objects.get(message=message).status == "in_progress"
        response = client.post(
            f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/stop",
            **headers,
        )
        assert response.status_code == 200
        assert response.json()["data"] == {"stop_requested": True}
        assert fences == [(workspace.id, conversation.id, message.id)]
        if response_lost:
            raise FoundryGatewayUnknownOutcome("admission response lost")
        return test_dispatch.receipt_for(command)

    monkeypatch.setattr("allies.gateways.foundry.stop_conversation", stop)
    monkeypatch.setattr("chat.services.dispatch.create_execution_intent", admit)
    monkeypatch.setattr(
        "chat.services.dispatch.reconcile_execution_intent",
        lambda key, fingerprint: test_dispatch.ReconciliationReceipt(
            schema_version="v1",
            kind="execution.reconciliation",
            status="accepted",
            command_id=key,
            idempotency_key=key,
            fingerprint=fingerprint,
        ),
    )
    report = dispatch_pending_messages(now=timezone.now())
    assert report.accepted + report.reconciled == 1
    assert DispatchOutbox.objects.get(message=message).status == DispatchState.ACCEPTED
    message.refresh_from_db()
    assert message.status == "queued"
    complete_turn(message_id=message.id, status="stopped")
    assert Message.objects.get(pk=message.id).status == "stopped"


def test_steer_stop_keeps_original_identity_after_completion(
    queue_account, monkeypatch
):
    user, workspace, _ally, conversation, messages = queue_account
    head, tail = messages
    delete_queued_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=tail.id,
    )
    targets = []

    def stop(conversation_id, *, workspace_id=None, message_id=None):
        complete_turn(message_id=head.id, status="completed")
        successor = Message.objects.get(conversation=conversation, content="Steered")
        assert successor.execution_claimed_at is not None
        targets.append((workspace_id, conversation_id, message_id))
        return 0

    monkeypatch.setattr("allies.gateways.foundry.stop_conversation", stop)
    client, headers = test_queue_api.authenticated_client(user)
    response = client.post(
        f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/steer",
        '{"content":"Steered"}',
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="stop-selected-identity-0001",
        **headers,
    )
    assert response.status_code == 201
    assert targets == [(workspace.id, conversation.id, head.id)]
    successor = Message.objects.get(pk=response.json()["data"]["message"]["id"])
    assert successor.status == "queued"
    replay = client.post(
        f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/steer",
        '{"content":"Steered"}',
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="stop-selected-identity-0001",
        **headers,
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["message"]["id"] == str(successor.id)
    assert targets == [(workspace.id, conversation.id, head.id)]


def test_stop_does_not_release_ambiguous_pending_admission(queue_account, monkeypatch):
    user, workspace, _ally, conversation, messages = queue_account
    head, tail = messages
    DispatchOutbox.objects.get_or_create(message=head)
    DispatchOutbox.objects.filter(message=head).update(attempt_count=1)
    monkeypatch.setattr(
        "allies.gateways.foundry.stop_conversation", lambda *args, **kwargs: 0
    )
    client, headers = test_queue_api.authenticated_client(user)
    response = client.post(
        f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/stop",
        **headers,
    )
    assert response.status_code == 200
    head.refresh_from_db()
    tail.refresh_from_db()
    assert head.status == "queued"
    assert tail.execution_claimed_at is None
    complete_turn(message_id=head.id, status="stopped")
    tail.refresh_from_db()
    assert tail.execution_claimed_at is not None
