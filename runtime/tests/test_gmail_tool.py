import importlib.util
import json
import re
import sys
from contextvars import ContextVar
from io import BytesIO
from pathlib import Path
from types import ModuleType
from urllib.error import URLError

import pytest

HERMES_IMAGE = Path(__file__).parents[1] / "hermes-image"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERMES_IMAGE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


routines = _load("routine_tool_for_gmail", "allies_routines.py")
gmail = _load("gmail_tool", "allies_gmail.py")


@pytest.fixture
def turn(monkeypatch):
    tools = ModuleType("tools")
    approval = ModuleType("tools.approval")
    approval._approval_tool_call_id = ContextVar("tool_call_id", default="call1")
    monkeypatch.setitem(sys.modules, "tools", tools)
    monkeypatch.setitem(sys.modules, "tools.approval", approval)
    monkeypatch.setitem(sys.modules, "tools.allies_routines", routines)
    token = routines.context.set(
        routines.turn_context("capability", "https://foundry.example.test")
    )
    yield
    routines.context.reset(token)


def _opener(monkeypatch, responses):
    requests = []

    class Response(BytesIO):
        pass

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            outcome = responses.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            status, body = outcome
            response = Response(body)
            response.status = status
            return response

    monkeypatch.setattr(gmail, "build_opener", lambda *a: Opener())
    return requests


def test_posts_opaque_integration_call_to_foundry(turn, monkeypatch):
    requests = _opener(monkeypatch, [(200, b'{"messages":[]}')])
    result = gmail.handle_gmail({"action": "search", "query": "from:a"})
    assert json.loads(result) == {"messages": []}
    request = requests[0]
    assert request.full_url == (
        "https://foundry.example.test/api/v1/runtime/integrations/tool"
    )
    assert request.headers["Authorization"] == "Bearer capability"
    body = json.loads(request.data)
    assert body["integration"] == "gmail"
    assert body["arguments"] == {"action": "search", "query": "from:a"}


def test_retry_keeps_call_identity(turn, monkeypatch):
    requests = _opener(monkeypatch, [URLError("lost"), (200, b'{"status":"sent"}')])
    assert json.loads(gmail.handle_gmail({"action": "send"})) == {"status": "sent"}
    first, second = (json.loads(r.data)["call_id"] for r in requests)
    assert first == second


def test_client_errors_are_returned_not_retried(turn, monkeypatch):
    requests = _opener(monkeypatch, [(403, b'{"error":"integration_unavailable"}')])
    result = json.loads(gmail.handle_gmail({"action": "get", "message_id": "m"}))
    assert result == {"error": "integration_unavailable"}
    assert len(requests) == 1


def test_repeated_failure_never_claims_success(turn, monkeypatch):
    _opener(monkeypatch, [(502, b"{}"), URLError("down")])
    result = json.loads(gmail.handle_gmail({"action": "send"}))
    assert result["error"] == "gmail_service_unavailable"
    assert "Do not claim" in result["instruction"]


def test_unavailable_without_turn_context(monkeypatch):
    approval = ModuleType("tools.approval")
    approval._approval_tool_call_id = ContextVar("tool_call_id", default="call1")
    monkeypatch.setitem(sys.modules, "tools", ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.approval", approval)
    monkeypatch.setitem(sys.modules, "tools.allies_routines", routines)
    monkeypatch.setattr(
        gmail, "build_opener", lambda *a: pytest.fail("no context must not call out")
    )
    assert "unavailable" in gmail.handle_gmail({"action": "search"})


@pytest.mark.parametrize("state", ["validating", "ready", "rejected"])
@pytest.mark.parametrize("action", ["download_attachment", "attachment_status"])
def test_attachment_results_pass_through_without_promoting_state(
    turn, monkeypatch, state, action
):
    publication_id = "00000000-0000-4000-8000-000000000001"
    args = (
        {"action": action, "message_id": "m", "part_id": ""}
        if action == "download_attachment"
        else {"action": action, "publication_id": publication_id}
    )
    result = {
        "publication_id": publication_id,
        "state": state,
        "filename": "document.pdf",
    }
    if state == "ready":
        result["chat_reference"] = (
            "[document.pdf](/files/00000000-0000-4000-8000-000000000002)"
        )
    requests = _opener(monkeypatch, [(200, json.dumps(result).encode())])
    assert json.loads(gmail.handle_gmail(args)) == result
    assert json.loads(requests[0].data)["arguments"] == args
    assert len(requests) == 1


def test_attachment_tool_schema_and_guidance_contract():
    function = gmail.SCHEMA["function"]
    properties = function["parameters"]["properties"]
    assert {"download_attachment", "attachment_status"} <= set(
        properties["action"]["enum"]
    )
    assert properties["part_id"]["type"] == "string"
    assert properties["part_id"]["maxLength"] == 128
    assert properties["part_id"].get("minLength", 0) == 0
    publication = properties["publication_id"]
    assert publication["type"] == "string"
    assert publication["format"] == "uuid"
    assert re.fullmatch(publication["pattern"], "00000000-0000-4000-8000-000000000001")
    assert not re.fullmatch(publication["pattern"], "00000000000040008000000000000001")
    assert not re.fullmatch(
        publication["pattern"], "AAAAAAAA-0000-4000-8000-000000000001"
    )
    guidance = function["description"]
    for rule in (
        "get exposes attachment metadata and part_id",
        "one attachment at a time",
        "Cloud waits up to 20 seconds per call",
        "at most five status checks per turn",
        "chat_reference exactly in your final answer",
        "Never claim an attachment was downloaded or returned before ready",
        "preserve publication_id in the receipt",
        "retrieval succeeded and inspection is pending",
        "do not say Gmail cannot retrieve attachments",
    ):
        assert rule in guidance
