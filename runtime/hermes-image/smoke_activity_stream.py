"""Exercise the patched Hermes progress callback through the real session SSE route."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from gateway.config import GatewayConfig, PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from hermes_state import SessionDB

PROFILE = "ally-smoke"
SESSION_ID = "activity-stream-smoke"
PROFILE_KEY = "allies-activity-profile-key-0001"
API_KEY = "allies-activity-smoke-key-000001"
PRIVATE_MARKER = "activity-private-should-not-cross-sse"


def _seed_profile(root: Path) -> Path:
    profile = root / "profiles" / PROFILE
    profile.mkdir(parents=True)
    (profile / ".env").write_text(
        f"API_SERVER_KEY={PROFILE_KEY}\n", encoding="utf-8"
    )
    database = SessionDB(profile / "state.db")
    try:
        database.create_session(SESSION_ID, "api_server")
    finally:
        database.close()
    return profile


def _app(adapter: APIServerAdapter) -> web.Application:
    app = web.Application(middlewares=[adapter._make_profile_prefix_middleware()])
    method, path, handler = next(
        row
        for row in adapter._http_route_table()
        if row[:2] == ("POST", "/api/sessions/{session_id}/chat/stream")
    )
    app.router.add_route(method, path, handler)
    app.router.add_route(method, f"/p/{{profile}}{path}", handler)
    return app


def _run_sequential_smoke(callback) -> None:
    """Run the patched sequential executor with only dispatch stubbed."""
    from agent import tool_executor

    events = []

    def record(event_type, tool_name=None, preview=None, args=None, **kwargs):
        events.append((event_type, tool_name, kwargs))
        callback(event_type, tool_name, preview, args, **kwargs)

    class ToolIO:
        def handle_function_call(self, function_name, function_args, task_id, **kwargs):
            assert function_name == "terminal"
            assert function_args == {"command": "printf sequential"}
            assert task_id == "sequential-task"
            assert kwargs["tool_call_id"] == "sequential-call"
            return "safe sequential result"

    class Guardrails:
        def before_call(self, function_name, function_args):
            return SimpleNamespace(allows_execution=True)

    class Agent:
        _incremental_persistence_failed = False
        _interrupt_requested = False
        _current_turn_id = ""
        _current_api_request_id = ""
        _current_tool = None
        _delegate_spinner = None
        _turns_since_memory = 0
        _iters_since_skill = 0
        context_compressor = SimpleNamespace(context_length=128000)
        _checkpoint_mgr = SimpleNamespace(enabled=False)
        _tool_guardrails = Guardrails()
        _subdirectory_hints = SimpleNamespace(check_tool_call=lambda *args: "")
        _memory_manager = None
        _todo_store = None
        clarify_callback = None
        session_id = SESSION_ID
        enabled_toolsets = None
        disabled_toolsets = None
        quiet_mode = True
        tool_progress_mode = "all"
        verbose_logging = False
        log_prefix = ""
        log_prefix_chars = 200
        tool_start_callback = None
        tool_complete_callback = None

        def __init__(self):
            self.tool_progress_callback = record
            self._context_engine_tool_names = set()
            self.valid_tool_names = {"terminal"}

        def _append_guardrail_observation(self, function_name, args, result, *, failed):
            return result

        def _apply_pending_steer_to_tool_results(self, messages, count):
            return None

        def _flush_messages_to_session_db(self, messages):
            return True

        def _record_file_mutation_result(self, *args):
            return None

        def _should_emit_quiet_tool_messages(self):
            return False

        def _should_start_quiet_spinner(self):
            return False

        def _touch_activity(self, message):
            return None

        def _tool_result_content_for_active_model(self, function_name, result):
            return result

        def _vprint(self, *args, **kwargs):
            return None

    tool_call = SimpleNamespace(
        id="sequential-call",
        function=SimpleNamespace(
            name="terminal", arguments='{"command":"printf sequential"}'
        ),
    )
    messages = []
    with patch.object(tool_executor, "_ra", return_value=ToolIO()):
        tool_executor.execute_tool_calls_sequential(
            Agent(),
            SimpleNamespace(tool_calls=[tool_call]),
            messages,
            "sequential-task",
        )

    assert [event[0] for event in events] == ["tool.started", "tool.completed"]
    assert [event[2]["tool_call_id"] for event in events] == [
        "sequential-call",
        "sequential-call",
    ]
    assert events[1][2]["is_error"] is False
    assert isinstance(events[1][2]["duration"], float)
    assert messages[-1]["tool_call_id"] == "sequential-call"


def _run_codex_bridge_smoke(callback) -> None:
    """Project real Codex notifications through the route callback."""
    from agent.codex_runtime import make_codex_app_server_event_bridge

    events = []

    def record(event_type, tool_name=None, preview=None, args=None, **kwargs):
        events.append((event_type, tool_name, kwargs))
        callback(event_type, tool_name, preview, args, **kwargs)

    bridge = make_codex_app_server_event_bridge(
        SimpleNamespace(
            tool_progress_callback=record,
            tool_start_callback=None,
            tool_complete_callback=None,
            show_commentary=False,
        )
    )
    item = {
        "id": "codex-item-1",
        "type": "commandExecution",
        "command": "printf codex",
        "cwd": "/tmp",
    }
    bridge({"method": "item/started", "params": {"item": item}})
    bridge(
        {
            "method": "item/completed",
            "params": {
                "item": {
                    **item,
                    "aggregatedOutput": "safe codex result",
                    "durationMs": 25,
                    "exitCode": 0,
                }
            },
        }
    )

    assert [event[0] for event in events] == ["tool.started", "tool.completed"]
    assert events[0][2]["tool_call_id"] == events[1][2]["tool_call_id"]
    assert events[0][2]["tool_call_id"] != item["id"]
    assert events[1][2]["is_error"] is False
    assert events[1][2]["duration"] == 0.025


async def _run() -> None:
    previous_home = os.environ.get("HERMES_HOME")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        os.environ["HERMES_HOME"] = str(root)
        _seed_profile(root)
        adapter = APIServerAdapter(PlatformConfig(extra={"key": API_KEY}))
        adapter.gateway_runner = SimpleNamespace(
            config=GatewayConfig(multiplex_profiles=True)
        )

        async def fake_run_agent(**kwargs):
            callback = kwargs["tool_progress_callback"]
            callback(
                "tool.started",
                "terminal",
                PRIVATE_MARKER,
                {"secret": PRIVATE_MARKER},
                tool_call_id="call-a",
            )
            callback(
                "tool.started",
                "terminal",
                PRIVATE_MARKER,
                {"secret": PRIVATE_MARKER},
                tool_call_id="call-b",
            )
            callback(
                "tool.completed",
                "terminal",
                PRIVATE_MARKER,
                {"secret": PRIVATE_MARKER},
                tool_call_id="call-b",
                duration=0.025,
                is_error=True,
                result={"secret": PRIVATE_MARKER},
            )
            callback(
                "tool.completed",
                "terminal",
                PRIVATE_MARKER,
                {"secret": PRIVATE_MARKER},
                tool_call_id="call-a",
                duration=0.125,
                is_error=False,
                result={"secret": PRIVATE_MARKER},
            )
            _run_sequential_smoke(callback)
            _run_codex_bridge_smoke(callback)
            return {
                "session_id": SESSION_ID,
                "final_response": "safe completion",
            }, {}

        adapter._run_agent = fake_run_agent
        try:
            async with TestClient(TestServer(_app(adapter))) as client:
                response = await client.post(
                    f"/p/{PROFILE}/api/sessions/{SESSION_ID}/chat/stream",
                    headers={"Authorization": f"Bearer {PROFILE_KEY}"},
                    json={"message": "run the safe smoke"},
                )
                body = await response.text()
                assert response.status == 200
                assert PRIVATE_MARKER not in body
                assert '"args"' not in body
                assert '"preview"' not in body
                assert '"result"' not in body

                lifecycle = []
                for frame in body.split("\n\n"):
                    event_name = next(
                        (
                            line.removeprefix("event: ")
                            for line in frame.splitlines()
                            if line.startswith("event: ")
                        ),
                        None,
                    )
                    data = next(
                        (
                            line.removeprefix("data: ")
                            for line in frame.splitlines()
                            if line.startswith("data: ")
                        ),
                        None,
                    )
                    if event_name in {"tool.started", "tool.completed"}:
                        lifecycle.append((event_name, json.loads(data)))
                assert [name for name, _payload in lifecycle] == [
                    "tool.started",
                    "tool.started",
                    "tool.completed",
                    "tool.completed",
                    "tool.started",
                    "tool.completed",
                    "tool.started",
                    "tool.completed",
                ]
                starts = [payload for name, payload in lifecycle if name == "tool.started"]
                completions = [
                    payload for name, payload in lifecycle if name == "tool.completed"
                ]
                assert {payload["tool_call_id"] for payload in starts[:2]} == {
                    "call-a",
                    "call-b",
                }
                assert [payload["tool_call_id"] for payload in completions[:2]] == [
                    "call-b",
                    "call-a",
                ]
                assert completions[0]["is_error"] is True
                assert completions[0]["duration_ms"] == 25
                assert completions[1]["is_error"] is False
                assert completions[1]["duration_ms"] == 125
                assert lifecycle[4][1]["tool_call_id"] == "sequential-call"
                assert lifecycle[5][1]["tool_call_id"] == "sequential-call"
                assert lifecycle[5][1]["is_error"] is False
                assert isinstance(lifecycle[5][1]["duration_ms"], int)
                assert lifecycle[6][1]["tool_name"] == "exec_command"
                assert lifecycle[6][1]["tool_call_id"] == lifecycle[7][1]["tool_call_id"]
                assert lifecycle[7][1]["duration_ms"] == 25
                assert lifecycle[7][1]["is_error"] is False
        finally:
            for database in getattr(adapter, "_session_dbs", {}).values():
                database.close()
            await adapter.disconnect()
            if previous_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = previous_home


asyncio.run(_run())
