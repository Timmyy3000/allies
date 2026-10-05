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


routines = _load("routine_tool_for_calendar", "allies_routines.py")
calendar = _load("calendar_tool", "allies_calendar.py")


@pytest.fixture
def turn(monkeypatch):
    approval = ModuleType("tools.approval")
    approval._approval_tool_call_id = ContextVar("tool_call_id", default="call1")
    monkeypatch.setitem(sys.modules, "tools", ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.approval", approval)
    monkeypatch.setitem(sys.modules, "tools.allies_routines", routines)
    token = routines.context.set(
        routines.turn_context("capability", "https://foundry.example.test")
    )
    yield
    routines.context.reset(token)


def _opener(monkeypatch, responses):
    requests = []

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            outcome = responses.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            status, body = outcome
            response = BytesIO(body)
            response.status = status
            return response

    monkeypatch.setattr(calendar, "build_opener", lambda *a: Opener())
    return requests


def test_posts_opaque_calendar_call_to_foundry(turn, monkeypatch):
    requests = _opener(monkeypatch, [(200, b'{"events":[]}')])
    result = calendar.handle_calendar({"action": "list_events"})
    assert json.loads(result) == {"events": []}
    request = requests[0]
    assert request.full_url == (
        "https://foundry.example.test/api/v1/runtime/integrations/tool"
    )
    assert request.headers["Authorization"] == "Bearer capability"
    body = json.loads(request.data)
    assert body["integration"] == "calendar"
    assert body["arguments"] == {"action": "list_events"}


def test_retry_keeps_call_identity(turn, monkeypatch):
    requests = _opener(monkeypatch, [URLError("lost"), (200, b'{"status":"created"}')])
    assert json.loads(calendar.handle_calendar({"action": "create_event"})) == {
        "status": "created"
    }
    first, second = (json.loads(r.data)["call_id"] for r in requests)
    assert first == second


def test_client_errors_are_returned_not_retried(turn, monkeypatch):
    requests = _opener(monkeypatch, [(403, b'{"error":"calendar_not_granted"}')])
    result = json.loads(calendar.handle_calendar({"action": "delete_event"}))
    assert result == {"error": "calendar_not_granted"}
    assert len(requests) == 1


def test_repeated_failure_never_claims_success(turn, monkeypatch):
    _opener(monkeypatch, [(502, b"{}"), URLError("down")])
    result = json.loads(calendar.handle_calendar({"action": "create_event"}))
    assert result["error"] == "calendar_service_unavailable"
    assert "Do not claim" in result["instruction"]


def test_unavailable_without_turn_context(monkeypatch):
    approval = ModuleType("tools.approval")
    approval._approval_tool_call_id = ContextVar("tool_call_id", default="call1")
    monkeypatch.setitem(sys.modules, "tools", ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.approval", approval)
    monkeypatch.setitem(sys.modules, "tools.allies_routines", routines)
    monkeypatch.setattr(
        calendar, "build_opener", lambda *a: pytest.fail("no context must not call out")
    )
    assert "unavailable" in calendar.handle_calendar({"action": "list_events"})


def test_schema_offers_every_event_detail_cloud_accepts():
    properties = calendar.SCHEMA["function"]["parameters"]["properties"]
    assert {
        "color",
        "recurrence",
        "reminder_minutes",
        "visibility",
        "busy",
        "add_meet",
        "guests_can_modify",
        "guests_can_invite",
        "guests_can_see_guests",
    } <= set(properties)
    assert "graphite" in properties["color"]["enum"]
    assert "default" in properties["color"]["enum"]
    assert "color" in calendar.INSTRUCTION and "meet_link" in calendar.INSTRUCTION


def test_series_edits_use_event_id_not_a_field_the_schema_lacks():
    assert (
        "recurring_event_id"
        not in calendar.SCHEMA["function"]["parameters"]["properties"]
    )
    assert "recurring_event_id as event_id" in calendar.INSTRUCTION
