import json
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.test import Client, override_settings

from chat.models import DispatchOutbox, Message
from chat.services.dispatch import _ensure_outbox_locked
from chat.tests.test_dispatch import dispatch_records  # noqa: F401
from routines.models import Routine, RoutineToolCall
from routines.services.tools import execute_routine_tool


@pytest.fixture
def tool_turn(dispatch_records):  # noqa: F811
    _, binding, conversation, message = dispatch_records
    conversation.is_default = False
    conversation.save()
    from django.db import transaction

    with transaction.atomic():
        _ensure_outbox_locked(message)
    outbox = DispatchOutbox.objects.get(message=message)
    outbox.command_bytes = b""
    outbox.save(update_fields=["command_bytes"])
    return {
        "message_id": message.id,
        "binding_id": binding.id,
        "command_fingerprint": outbox.command_fingerprint,
    }


def create_args():
    return {
        "action": "create",
        "title": "Check price",
        "execution_prompt": "Check the saved product price and report even if unchanged.",
        "schedule": {
            "kind": "recurring",
            "frequency": "daily",
            "local_time": "09:00:00",
            "timezone": "Europe/Berlin",
        },
    }


def test_create_retry_inspect_update_and_pause(tool_turn):
    call_id = uuid4()
    first = execute_routine_tool(**tool_turn, call_id=call_id, arguments=create_args())
    replay = execute_routine_tool(**tool_turn, call_id=call_id, arguments=create_args())
    assert replay == first
    assert Routine.objects.count() == 1
    assert first["status"] == "saved"
    assert first["schedule"]["timezone"] == "Europe/Berlin"
    with pytest.raises(ValueError):
        execute_routine_tool(
            **tool_turn, call_id=call_id, arguments={**create_args(), "title": "Other"}
        )
    paused = execute_routine_tool(
        **tool_turn,
        call_id=uuid4(),
        arguments={
            "action": "pause",
            "routine_id": first["routine_id"],
            "expected_revision": 1,
        },
    )
    assert paused["state"] == "paused"
    assert paused["revision"] == 2


def test_delete_requires_previous_turn_confirmation(tool_turn):
    created = execute_routine_tool(
        **tool_turn, call_id=uuid4(), arguments=create_args()
    )
    fields = {"routine_id": created["routine_id"], "expected_revision": 1}
    challenge = execute_routine_tool(
        **tool_turn, call_id=uuid4(), arguments={"action": "request_delete", **fields}
    )
    args = {
        "action": "delete",
        **fields,
        "confirmation_ref": challenge["confirmation_ref"],
    }
    with pytest.raises(ValidationError):
        execute_routine_tool(**tool_turn, call_id=uuid4(), arguments=args)
    old = Message.objects.get(pk=tool_turn["message_id"])
    old.status = "completed"
    old.save()
    next_message = Message.objects.create(
        conversation=old.conversation,
        sequence=2,
        sender="user",
        origin="send",
        content="Yes, delete it",
        status="queued",
        send_key_digest="d" * 64,
        content_fingerprint="e" * 64,
    )
    from django.db import transaction

    with transaction.atomic():
        _ensure_outbox_locked(next_message)
    deleted = execute_routine_tool(
        message_id=next_message.id,
        binding_id=tool_turn["binding_id"],
        command_fingerprint=DispatchOutbox.objects.get(
            message=next_message
        ).command_fingerprint,
        call_id=uuid4(),
        arguments=args,
    )
    assert deleted["state"] == "deleted"


def test_wrong_binding_and_missing_schedule_do_not_write(tool_turn):
    with pytest.raises(PermissionError):
        execute_routine_tool(
            **{**tool_turn, "binding_id": uuid4()},
            call_id=uuid4(),
            arguments=create_args(),
        )
    args = create_args()
    del args["schedule"]["local_time"]
    with pytest.raises((ValidationError, ValueError)):
        execute_routine_tool(**tool_turn, call_id=uuid4(), arguments=args)
    assert not Routine.objects.exists()
    assert not RoutineToolCall.objects.exists()


def test_dispatch_fingerprint_must_match_even_on_replay(tool_turn):
    call_id = uuid4()
    execute_routine_tool(**tool_turn, call_id=call_id, arguments=create_args())
    with pytest.raises(PermissionError):
        execute_routine_tool(
            **{
                **tool_turn,
                "command_fingerprint": "canonical-json-sha256:v1:" + "0" * 64,
            },
            call_id=call_id,
            arguments=create_args(),
        )
    assert Routine.objects.count() == 1


def test_inactive_workspace_cannot_replay_saved_tool_response(tool_turn):
    call_id = uuid4()
    execute_routine_tool(**tool_turn, call_id=call_id, arguments=create_args())
    message = Message.objects.select_related("conversation__ally__workspace").get(
        pk=tool_turn["message_id"]
    )
    workspace = message.conversation.ally.workspace
    workspace.is_active = False
    workspace.save(update_fields=["is_active"])
    with pytest.raises(PermissionError):
        execute_routine_tool(**tool_turn, call_id=call_id, arguments=create_args())


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN="test-service-token",
)
def test_internal_endpoint_requires_service_auth(tool_turn):
    client = Client()
    body = {
        **{k: str(v) for k, v in tool_turn.items()},
        "call_id": str(uuid4()),
        "arguments": create_args(),
    }
    url = "/api/v1/internal/foundry/routines/tool"
    assert (
        client.post(url, json.dumps(body), content_type="application/json").status_code
        == 401
    )
    response = client.post(
        url,
        json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer test-service-token",
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "saved"


def test_browser_timezone_is_carried_in_dispatched_context(dispatch_records):  # noqa: F811
    from chat.services.dispatch import _command_for_message

    _, _, _, message = dispatch_records
    message.client_timezone = "Asia/Kolkata"
    message.save()
    command, _, _ = _command_for_message(message)
    assert "Browser timezone: Asia/Kolkata" in command.payload.text
    assert message.created_at.isoformat() in command.payload.text
    assert message.content in command.payload.text


def test_invalid_timezone_rejected_before_admission():
    from chat.exceptions import MessageValidation
    from chat.services.messages import accept_message

    with pytest.raises(MessageValidation):
        accept_message(
            user=None,
            workspace_id=uuid4(),
            conversation_id=uuid4(),
            content="Schedule work",
            idempotency_key="test-key",
            client_timezone="Not/A_Zone",
        )


def test_maximum_admitted_message_with_timezone_fits_dispatch(tool_turn):
    from chat.models import MESSAGE_CONTENT_MAX_LENGTH
    from chat.services.dispatch import _command_for_message

    message = Message.objects.get(pk=tool_turn["message_id"])
    message.content = "é" * (MESSAGE_CONTENT_MAX_LENGTH // 2)
    message.client_timezone = "Europe/Berlin"
    command, _, _ = _command_for_message(message)
    assert message.content in command.payload.text
    assert "Browser timezone: Europe/Berlin" in command.payload.text


@pytest.mark.django_db(transaction=True)
def test_postgres_concurrent_duplicate_returns_same_receipt(tool_turn):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections, connection

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL row locking proof")
    gate = Barrier(2)
    call_id = uuid4()

    def invoke():
        close_old_connections()
        try:
            gate.wait(timeout=5)
            return execute_routine_tool(
                **tool_turn, call_id=call_id, arguments=create_args()
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke) for _ in range(2)]
        responses = [future.result(timeout=15) for future in futures]
    assert responses[0] == responses[1]
    assert Routine.objects.count() == 1
    assert RoutineToolCall.objects.count() == 1
