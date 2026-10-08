import json
from uuid import uuid4

import pytest
from django.test import Client

from runtime.contracts import ExecutionCommand
from runtime.models import Execution, ExecutionEvent, ExecutionEventDelivery, Lease
from runtime.services.executions import (
    create_execution_intent,
    reconcile_execution_intent,
)
from runtime.services.leases import request_conversation_stop
from runtime.tests import test_cld005_contract

contract = test_cld005_contract.contract
binding = test_cld005_contract.binding
configured = test_cld005_contract.configured
pytestmark = pytest.mark.django_db


def stop(command):
    return request_conversation_stop(
        command.cloud.conversation_id,
        workspace_id=command.scope.cloud_workspace_id,
        message_id=command.cloud.message_id,
    )


@pytest.mark.parametrize("stop_first", [True, False])
def test_stop_and_admission_replay_never_make_selected_message_runnable(
    binding, contract, stop_first
):
    command = ExecutionCommand.model_validate(contract["command"])
    if stop_first:
        assert stop(command) == 0
    receipt = create_execution_intent(command)
    if not stop_first:
        assert stop(command) == 1
    assert stop(command) == 0
    replay = create_execution_intent(command)
    reconciled = reconcile_execution_intent(
        command.idempotency_key, command.fingerprint
    )
    execution = Execution.objects.get(command_id=command.command_id)
    assert execution.status == "cancelled"
    assert (receipt.status, replay.status, reconciled.status) == (
        "accepted",
        "duplicate",
        "accepted",
    )
    assert Lease.objects.filter(attempt__execution=execution).count() == 0
    event = ExecutionEvent.objects.get(attempt__execution=execution)
    assert (event.event_type, event.sequence, event.payload) == (
        "execution.stopped",
        1,
        {"reason": "user_requested"},
    )
    assert ExecutionEventDelivery.objects.filter(event=event).count() == 1


@pytest.mark.parametrize("successor_status", ["queued", "running"])
def test_delayed_stop_for_completed_original_leaves_successor_untouched(
    binding, contract, successor_status
):
    command = ExecutionCommand.model_validate(contract["command"])
    create_execution_intent(command)
    original = Execution.objects.get(command_id=command.command_id)
    Execution.objects.filter(pk=original.pk).update(status="succeeded")
    successor = Execution.objects.create(
        workspace=original.workspace,
        profile=original.profile,
        idempotency_key="successor",
        status=successor_status,
        cloud_workspace_id=command.scope.cloud_workspace_id,
        cloud_conversation_id=command.cloud.conversation_id,
        cloud_message_id=uuid4(),
        source_kind="conversation_message",
    )
    assert stop(command) == 0
    assert stop(command) == 0
    assert Execution.objects.get(pk=original.pk).status == "succeeded"
    assert Execution.objects.get(pk=successor.pk).status == successor_status
    assert ExecutionEvent.objects.filter(attempt__execution=successor).count() == 0


@pytest.mark.parametrize("wrong_scope", ["workspace", "conversation", "message"])
def test_stop_does_not_cross_identity_scope(binding, contract, wrong_scope):
    command = ExecutionCommand.model_validate(contract["command"])
    create_execution_intent(command)
    workspace_id = command.scope.cloud_workspace_id
    conversation_id = command.cloud.conversation_id
    message_id = command.cloud.message_id
    if wrong_scope == "workspace":
        from runtime.models import Workspace

        workspace_id = uuid4()
        Workspace.objects.create(tenant_ref=str(workspace_id))
    elif wrong_scope == "conversation":
        conversation_id = uuid4()
    else:
        message_id = uuid4()
    assert (
        request_conversation_stop(
            conversation_id, workspace_id=workspace_id, message_id=message_id
        )
        == 0
    )
    assert Execution.objects.get(command_id=command.command_id).status == "queued"
    assert stop(command) == 1
    assert Execution.objects.get(command_id=command.command_id).status == "cancelled"


def test_stop_http_requires_service_auth_and_explicit_scope(
    binding, contract, configured, settings
):
    settings.ALLOWED_HOSTS = ["testserver"]
    command = ExecutionCommand.model_validate(contract["command"])
    path = f"/api/v1/internal/conversations/{command.cloud.conversation_id}/stop"
    client = Client()
    body = json.dumps(
        {
            "workspace_id": str(command.scope.cloud_workspace_id),
            "message_id": str(command.cloud.message_id),
        }
    )
    assert client.post(path, body, content_type="application/json").status_code == 401
    assert (
        client.post(
            path,
            body,
            content_type="application/json",
            headers={"Authorization": "Bearer wrong"},
        ).status_code
        == 401
    )
    headers = {"Authorization": f"Bearer {configured}"}
    assert (
        client.post(
            path, "{}", content_type="application/json", headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            path,
            '{"workspace_id":"invalid","message_id":"invalid"}',
            content_type="application/json",
            headers=headers,
        ).status_code
        == 422
    )
    response = client.post(path, body, content_type="application/json", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"stopped": 0}
    create_execution_intent(command)
    assert Execution.objects.get(command_id=command.command_id).status == "cancelled"
