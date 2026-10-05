import importlib.util
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from io import BytesIO
from pathlib import Path
from types import ModuleType
from urllib.error import URLError

from allies_runtime.config import RuntimeSettings
from allies_runtime.hermes import _session_stream_headers

spec = importlib.util.spec_from_file_location(
    "routine_tool", Path(__file__).parents[1] / "hermes-image" / "allies_routines.py"
)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def test_context_isolated_and_network_retry_keeps_call_id(monkeypatch):
    requests = []
    approval = ModuleType("tools.approval")
    approval._approval_tool_call_id = ContextVar("tool_call_id", default="call1")
    monkeypatch.setitem(sys.modules, "tools.approval", approval)

    class Response(BytesIO):
        status = 200

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            if len(requests) == 1:
                raise URLError("lost response")
            return Response(b'{"status":"saved"}')

    monkeypatch.setattr(tool, "build_opener", lambda *a: Opener())
    assert "unavailable" in tool.handle_routine(
        {"action": "list"}, tool_call_id="call1"
    )
    token = tool.context.set(
        tool.turn_context("capability", "https://foundry.example.test")
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(
                copy_context().run,
                tool.handle_routine,
                {"action": "list"},
                tool_call_id="call1",
            ).result()
            assert json.loads(result)["status"] == "saved"
            assert (
                "unavailable"
                in pool.submit(
                    tool.handle_routine, {"action": "list"}, tool_call_id="call2"
                ).result()
            )
    finally:
        tool.context.reset(token)
    assert requests[0].data == requests[1].data
    assert requests[0].get_header("Authorization") == "Bearer capability"
    assert "capability" not in result


def test_routine_runs_do_not_get_management_capability():
    settings = RuntimeSettings(foundry_origin="https://foundry.example.test")
    ordinary = _session_stream_headers(
        settings, "session", routine_tool_token="capability"
    )
    assert ordinary["X-Allies-Routine-Tool"] == "capability"
    scheduled = _session_stream_headers(
        settings, "session", routine_result=True, routine_tool_token="capability"
    )
    assert "X-Allies-Routine-Tool" not in scheduled
