import json
import sys
from contextvars import ContextVar
from io import BytesIO
from types import ModuleType

import pytest
from test_gmail_tool import _load, routines

safe_inputs = _load("safe_inputs_tool", "allies_safe_inputs.py")


@pytest.fixture
def turn(monkeypatch):
    approval = ModuleType("tools.approval")
    approval._approval_tool_call_id = ContextVar("tool_call_id", default="call1")
    monkeypatch.setitem(sys.modules, "tools", ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.approval", approval)
    monkeypatch.setitem(sys.modules, "tools.allies_routines", routines)
    monkeypatch.setitem(sys.modules, "tools.allies_safe_inputs", safe_inputs)
    monkeypatch.setattr(safe_inputs.time, "sleep", lambda s: None)
    token = routines.context.set(
        routines.turn_context("capability", "https://foundry.example.test")
    )
    yield approval
    routines.context.reset(token)


def _opener(monkeypatch, bodies):
    requests = []

    class Opener:
        def open(self, request, timeout):
            requests.append(json.loads(request.data))
            response = BytesIO(json.dumps(bodies.pop(0)).encode())
            response.status = 200
            return response

    monkeypatch.setattr(safe_inputs, "build_opener", lambda *a: Opener())
    return requests


def test_request_waits_for_the_user(turn, monkeypatch):
    requests = _opener(
        monkeypatch,
        [
            {"request_id": "r1", "status": "pending"},
            {"status": "pending"},
            {"status": "saved", "id": "s1", "name": "Amazon", "website": "amazon.com"},
        ],
    )
    result = json.loads(
        safe_inputs.handle_safe_inputs(
            {"action": "request_new", "website": "amazon.com"}
        )
    )
    assert result["status"] == "saved" and result["id"] == "s1"
    assert [r["arguments"]["action"] for r in requests] == [
        "request_new",
        "status",
        "status",
    ]
    assert {r["integration"] for r in requests} == {"safe_inputs"}


def test_request_gives_up_while_pending(turn, monkeypatch):
    _opener(monkeypatch, [{"request_id": "r1", "status": "pending"}])
    monkeypatch.setattr(safe_inputs, "WAIT_SECONDS", 0)
    result = json.loads(safe_inputs.handle_safe_inputs({"action": "request_access"}))
    assert result["status"] == "pending" and result["request_id"] == "r1"
    assert "instruction" in result


def test_ask_approval_uses_a_fresh_rule_each_time(turn):
    seen = []

    def request_tool_approval(tool_name, reason, *, rule_key, tool_args):
        seen.append(rule_key)
        return {"approved": True, "message": None}

    turn.request_tool_approval = request_tool_approval
    for _ in range(2):
        result = safe_inputs.handle_ask_approval({"action": "Buy the blue kettle"})
        assert json.loads(result)["approved"] is True
    assert len(set(seen)) == 2


def test_provider_keeps_turn_context_for_reaper_close(turn, monkeypatch):
    browser_provider = ModuleType("agent.browser_provider")
    browser_provider.BrowserProvider = object
    monkeypatch.setitem(sys.modules, "agent", ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.browser_provider", browser_provider)
    provider = _load("browser_provider", "allies_browser_provider.py")
    requests = _opener(
        monkeypatch,
        [
            {"session_id": "b1", "cdp_url": "wss://cdp", "expires_at": "2026-01-01"},
            {"status": "closed"},
        ],
    )
    session = provider.BrowserUseBrowserProvider().create_session(
        "allies-s-" + "a" * 64
    )
    assert session["bb_session_id"] == "b1" and session["cdp_url"] == "wss://cdp"
    # agent-browser puts its socket at /tmp/agent-browser-<name>/default.sock,
    # which Linux caps at 103 bytes.
    assert len(f"/tmp/agent-browser-{session['session_name']}/default.sock") <= 103

    routines.context.set(None)  # reaper thread: no turn context
    assert provider.BrowserUseBrowserProvider().close_session("b1") is True
    assert requests[1]["arguments"] == {"action": "close", "session_id": "b1"}


def test_pending_without_id_returns_instead_of_polling(turn, monkeypatch):
    requests = _opener(monkeypatch, [{"status": "pending"}])
    result = json.loads(safe_inputs.handle_safe_inputs({"action": "request_new"}))
    assert result["status"] == "pending" and len(requests) == 1
