import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from django.test import Client
from django.utils import timezone

from allies.models import Ally, AllyBinding
from auths.models import User
from chat.models import Conversation
from integrations.models import PROVIDER_GMAIL, IntegrationSecret
from integrations.services import browser, gmail_tool
from integrations.services.google_oauth import MintedAccess
from integrations.services.grants import set_ally_grant
from integrations.services.vault import seal_refresh_token
from integrations.tests.test_grants import gmail_settings  # noqa: F401
from routines.models import (
    Routine,
    RoutineDispatchOutbox,
    RoutineDispatchState,
    RoutineState,
)
from routines.services.dispatch import (
    claim_pending_routine_dispatches,
    settle_routine_dispatch,
)
from routines.services.management import create_routine_intent
from routines.services.scheduler import admit_due_routines
from workspaces.models import Membership, Workspace

BASE = datetime(2026, 9, 10, 7, tzinfo=UTC)
URL = "/api/v1/internal/foundry/integrations/tool"
AUTH = {"HTTP_AUTHORIZATION": "Bearer test-service-token"}


def _fake_gmail(calls):
    def fake(token, path, *, query=None, body=None, max_bytes=5_000_000):
        assert token == "ya29.live"
        calls.append(path)
        if path == "/messages":
            return {"messages": [{"id": "m1"}]}
        if path == "/messages/m1":
            return {
                "id": "m1",
                "threadId": "t1",
                "snippet": "Hi",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "alice@example.com"},
                        {"name": "Subject", "value": "Hello"},
                    ]
                },
            }
        raise AssertionError(path)

    return fake


@pytest.fixture
def routine_turn(db, gmail_settings, settings, monkeypatch):  # noqa: F811
    settings.ALLOWED_HOSTS = ["testserver"]
    settings.ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN = "test-service-token"
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Routine tools")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="School assistant",
        personality="Calm and specific.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    binding = AllyBinding.objects.create(ally=ally)
    conversation = Conversation.objects.create(ally=ally)
    routine = create_routine_intent(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        main_conversation_id=conversation.id,
        title="Hourly school pulse",
        execution_prompt="Check the school inbox and summarize urgent mail.",
        schedule={
            "kind": "recurring",
            "frequency": "daily",
            "local_time": "09:00:00",
            "timezone": "Europe/Berlin",
        },
        now=datetime(2026, 9, 10, 6, tzinfo=UTC),
    )
    admit_due_routines(now=BASE)
    run = routine.run_snapshots.get()
    settle_routine_dispatch(
        claim_pending_routine_dispatches(now=BASE)[0],
        status=RoutineDispatchState.ACCEPTED,
        execution_id=uuid4(),
        attempt_id=uuid4(),
        generation=7,
        receipt_digest="a" * 64,
        now=BASE,
    )
    ciphertext, version = seal_refresh_token("refresh.live")
    secret = IntegrationSecret.objects.create(
        workspace=workspace,
        provider_key=PROVIDER_GMAIL,
        account_ref_hash=hashlib.sha256(b"acct").hexdigest(),
        account_email="me@gmail.com",
        ciphertext=bytes(ciphertext),
        key_version=version,
    )
    set_ally_grant(secret=secret, ally=ally, level="send")
    monkeypatch.setattr(
        gmail_tool,
        "refresh_access_token",
        lambda secret: MintedAccess("ya29.live", timezone.now()),
    )
    calls = []
    monkeypatch.setattr(gmail_tool, "_gmail", _fake_gmail(calls))
    return {
        "routine": routine,
        "user": user,
        "workspace": workspace,
        "run_id": run.id,
        "binding_id": binding.id,
        "command_fingerprint": RoutineDispatchOutbox.objects.get(
            run_id=run.id
        ).command_fingerprint,
        "calls": calls,
    }


def _post(turn, integration, arguments, **identity):
    body = {
        "run_id": str(turn["run_id"]),
        "binding_id": str(turn["binding_id"]),
        "command_fingerprint": turn["command_fingerprint"],
        "call_id": str(uuid4()),
        "integration": integration,
        "arguments": arguments,
        **identity,
    }
    return Client().post(URL, json.dumps(body), content_type="application/json", **AUTH)


def test_routine_run_reads_gmail_through_its_dispatch_identity(routine_turn):
    response = _post(routine_turn, "gmail", {"action": "search", "query": "school"})
    assert response.status_code == 200, response.content
    assert response.json()["messages"][0]["message_id"] == "m1"
    assert routine_turn["calls"][0] == "/messages"


@pytest.mark.parametrize(
    ("integration", "arguments"),
    [
        (
            "gmail",
            {
                "action": "prepare_send",
                "to": ["alice@example.com"],
                "subject": "Lunch",
                "body": "Noon?",
            },
        ),
        (
            "gmail",
            {
                "action": "send",
                "to": ["alice@example.com"],
                "subject": "Lunch",
                "body": "Noon?",
                "confirmation_ref": str(uuid4()),
            },
        ),
        (
            "gmail",
            {"action": "modify", "message_ids": ["m1"], "add_labels": ["Receipts"]},
        ),
        ("gmail", {"action": "create_label", "label": "School"}),
        (
            "gmail",
            {"action": "download_attachment", "message_id": "m1", "part_id": "2"},
        ),
        ("gmail", {"action": "attachment_status", "publication_id": str(uuid4())}),
        (
            "calendar",
            {
                "action": "create_event",
                "summary": "Pulse",
                "start": "2026-10-10T09:00:00+02:00",
                "end": "2026-10-10T10:00:00+02:00",
            },
        ),
        ("calendar", {"action": "delete_event", "event_id": "e1"}),
        ("safe_inputs", {"action": "fill", "safe_input_id": str(uuid4())}),
    ],
)
def test_routine_runs_refuse_outward_actions_before_any_provider_call(
    routine_turn, integration, arguments
):
    response = _post(routine_turn, integration, arguments)
    assert response.status_code == 403
    assert response.json()["error"] == "routine_action_unavailable"
    assert routine_turn["calls"] == []


def test_exhausted_routine_keeps_tools_for_its_last_run(routine_turn):
    Routine.objects.filter(pk=routine_turn["routine"].pk).update(
        state=RoutineState.EXHAUSTED
    )
    response = _post(routine_turn, "gmail", {"action": "search", "query": "x"})
    assert response.status_code == 200, response.content


def test_routine_runs_keep_safe_input_list_and_browser_open(routine_turn, monkeypatch):
    listed = _post(routine_turn, "safe_inputs", {"action": "list"})
    assert listed.status_code == 200
    assert listed.json() == {"safe_inputs": []}
    monkeypatch.setattr(browser, "open_browser", lambda ally: {"session_id": "s1"})
    opened = _post(routine_turn, "browser", {"action": "open"})
    assert opened.status_code == 200
    assert opened.json() == {"session_id": "s1"}


@pytest.mark.parametrize(
    "change",
    ["binding", "fingerprint", "unknown_run", "paused", "deleted", "owner_access"],
)
def test_routine_identity_must_match_an_active_dispatched_routine(routine_turn, change):
    identity = {}
    if change == "binding":
        identity["binding_id"] = str(uuid4())
    elif change == "fingerprint":
        identity["command_fingerprint"] = "canonical-json-sha256:v1:" + "0" * 64
    elif change == "unknown_run":
        identity["run_id"] = str(uuid4())
    elif change == "paused":
        Routine.objects.filter(pk=routine_turn["routine"].pk).update(
            state=RoutineState.PAUSED
        )
    elif change == "deleted":
        Routine.objects.filter(pk=routine_turn["routine"].pk).update(
            state=RoutineState.DELETED, deleted_at=timezone.now()
        )
    else:
        Membership.objects.filter(
            workspace=routine_turn["workspace"], user=routine_turn["user"]
        ).delete()
    response = _post(
        routine_turn, "gmail", {"action": "search", "query": "x"}, **identity
    )
    assert response.status_code == 403
    assert response.json() == {"error": "integration_unavailable"}
    assert routine_turn["calls"] == []


def test_tool_turn_is_exactly_one_of_message_or_run(routine_turn):
    both = _post(
        routine_turn,
        "gmail",
        {"action": "search", "query": "x"},
        message_id=str(uuid4()),
    )
    assert both.status_code == 422
    body = {
        "binding_id": str(routine_turn["binding_id"]),
        "command_fingerprint": routine_turn["command_fingerprint"],
        "call_id": str(uuid4()),
        "integration": "gmail",
        "arguments": {"action": "search", "query": "x"},
    }
    neither = Client().post(
        URL, json.dumps(body), content_type="application/json", **AUTH
    )
    assert neither.status_code == 422
    assert routine_turn["calls"] == []
