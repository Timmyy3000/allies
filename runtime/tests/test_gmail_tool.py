import importlib.util
import json
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
