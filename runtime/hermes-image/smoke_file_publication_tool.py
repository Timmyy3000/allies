"""Exercise the private Allies file-publication Hermes boundary."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from allies_file_publication_context import (
    get_current_allies_file_publication_context,
    reset_current_allies_file_publication_context,
    set_current_allies_file_publication_context,
)
from gateway.config import PlatformConfig
from gateway.platforms.api_server import (
    _ALLIES_FILE_PUBLICATION_TOOLSET,
    _ALLIES_ROUTINE_RESULT_TOOLSET,
    APIServerAdapter,
    _allies_file_publication_context,
    _allies_routine_enabled_toolsets,
)
from hermes_cli.plugins import discover_plugins
from model_tools import get_tool_definitions, handle_function_call
from run_agent import AIAgent
from tools.thread_context import propagate_context_to_thread
from toolsets import TOOLSETS, create_custom_toolset

SOCKET_PATH = Path("/opt/data/.allies-publication-bridge/socket")
NONCE_A = "a" * 64
NONCE_B = "b" * 64


def _failure() -> dict[str, object]:
    return {
        "state": "failed",
        "retryable": True,
        "error_code": "publication_unavailable",
    }


def _serve(
    responses: list[bytes], requests: list[dict[str, object]]
) -> tuple[threading.Thread, list[BaseException]]:
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SOCKET_PATH.exists():
        raise AssertionError("publication smoke socket already exists")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(SOCKET_PATH))
    server.listen(len(responses))
    errors: list[BaseException] = []

    def run() -> None:
        try:
            for response in responses:
                connection, _ = server.accept()
                with connection:
                    received = bytearray()
                    while b"\n" not in received:
                        chunk = connection.recv(4096)
                        if not chunk:
                            raise AssertionError(
                                "publication request ended before newline"
                            )
                        received.extend(chunk)
                    line, tail = bytes(received).split(b"\n", 1)
                    if tail:
                        raise AssertionError("publication request had trailing data")
                    requests.append(json.loads(line.decode("utf-8")))
                    connection.sendall(response)
        except (
            AssertionError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            errors.append(error)
        finally:
            server.close()
            SOCKET_PATH.unlink(missing_ok=True)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, errors


def _published_file(name: str) -> bytes:
    return (
        json.dumps(
            {"state": "ready", "files": [{"name": name, "open_path": "/files/id"}]},
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _call(context: str, tool_call_id: str, path: str):
    token = set_current_allies_file_publication_context(context)
    try:
        return propagate_context_to_thread(
            lambda: handle_function_call(
                "publish_files", {"paths": [path]}, tool_call_id=tool_call_id
            )
        )
    finally:
        reset_current_allies_file_publication_context(token)


def _test_executor_binding() -> None:
    expected = "c" * 64

    class Agent:
        session_id = "session"
        session_prompt_tokens = 0
        session_completion_tokens = 0
        session_total_tokens = 0

        def run_conversation(self, **_kwargs):
            assert get_current_allies_file_publication_context() == expected
            return {"final_response": "safe"}

    adapter = APIServerAdapter(PlatformConfig(extra={"key": "smoke"}))
    adapter._create_agent = lambda **_kwargs: Agent()
    result, _usage = asyncio.run(
        adapter._run_agent(
            "message", [], session_id="session", publication_context=expected
        )
    )
    assert result["final_response"] == "safe"
    assert get_current_allies_file_publication_context() is None


def _agent_tools(**capability: object) -> set[str]:
    agent = AIAgent(
        model="smoke/model",
        api_key="smoke-key",
        base_url="http://127.0.0.1:9/v1",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
        **capability,
    )
    return agent.valid_tool_names


def _assert_private_capability(
    expected: str, hidden: str, **capability: object
) -> None:
    tools = _agent_tools(**capability)
    assert expected in tools
    assert hidden not in tools


def _test_private_capability_boundary() -> None:
    assert (
        not {
            "publish_files",
            "allies_routine_result",
        }
        & _agent_tools()
    )
    assert not {
        "publish_files",
        "allies_routine_result",
    } & _agent_tools(enabled_toolsets=["all"])

    composite = "_allies_private_tools_smoke_composite"
    create_custom_toolset(
        composite,
        "Build-time composite containing both private tools.",
        includes=[
            _ALLIES_FILE_PUBLICATION_TOOLSET,
            _ALLIES_ROUTINE_RESULT_TOOLSET,
        ],
    )
    try:
        assert not {
            "publish_files",
            "allies_routine_result",
        } & _agent_tools(enabled_toolsets=[composite])
        _assert_private_capability(
            "publish_files",
            "allies_routine_result",
            enabled_toolsets=[composite],
            allies_file_publication=True,
        )
        _assert_private_capability(
            "allies_routine_result",
            "publish_files",
            enabled_toolsets=[composite],
            allies_routine_result=True,
        )
    finally:
        TOOLSETS.pop(composite, None)

    _assert_private_capability(
        "publish_files", "allies_routine_result", allies_file_publication=True
    )
    _assert_private_capability(
        "publish_files",
        "allies_routine_result",
        enabled_toolsets=["all"],
        allies_file_publication=True,
    )
    _assert_private_capability(
        "allies_routine_result", "publish_files", allies_routine_result=True
    )
    _assert_private_capability(
        "allies_routine_result",
        "publish_files",
        enabled_toolsets=["all"],
        allies_routine_result=True,
    )
    try:
        _agent_tools(allies_file_publication=True, allies_routine_result=True)
    except ValueError:
        pass
    else:
        raise AssertionError("both private capabilities were accepted")


def main() -> None:
    discover_plugins(force=True)
    ordinary = _allies_routine_enabled_toolsets(
        ["all"], routine_result=False, file_publication=False
    )
    marked = _allies_routine_enabled_toolsets(
        ["all"], routine_result=False, file_publication=True
    )
    routine = _allies_routine_enabled_toolsets(
        ["all"], routine_result=True, file_publication=False
    )
    assert _ALLIES_FILE_PUBLICATION_TOOLSET not in ordinary
    assert _ALLIES_FILE_PUBLICATION_TOOLSET in marked
    assert _ALLIES_FILE_PUBLICATION_TOOLSET not in routine
    assert _ALLIES_ROUTINE_RESULT_TOOLSET in routine

    composite = "_allies_file_publication_smoke_composite"
    create_custom_toolset(
        composite,
        "Private publication tool composite.",
        includes=[_ALLIES_FILE_PUBLICATION_TOOLSET],
    )
    try:
        definitions = get_tool_definitions(
            enabled_toolsets=[composite],
            disabled_toolsets=[_ALLIES_FILE_PUBLICATION_TOOLSET],
            quiet_mode=True,
        )
        assert "publish_files" not in {
            definition["function"]["name"] for definition in definitions
        }
    finally:
        TOOLSETS.pop(composite, None)

    assert _allies_file_publication_context(None) is None
    assert _allies_file_publication_context(NONCE_A) == NONCE_A
    for invalid in ("A" * 64, "a" * 63, 1):
        try:
            _allies_file_publication_context(invalid)
        except ValueError:
            continue
        raise AssertionError("invalid publication context was accepted")

    missing = json.loads(
        handle_function_call(
            "publish_files", {"paths": ["out.csv"]}, tool_call_id="call-missing"
        )
    )
    assert missing == _failure()
    assert NONCE_A not in json.dumps(missing)

    token = set_current_allies_file_publication_context(NONCE_A)
    try:
        unavailable = json.loads(
            handle_function_call(
                "publish_files", {"paths": ["out.csv"]}, tool_call_id="call-socket"
            )
        )
        oversized = json.loads(
            handle_function_call(
                "publish_files",
                {"paths": ["x" * 900 + str(index) for index in range(10)]},
                tool_call_id="call-large",
            )
        )
        malformed = json.loads(
            handle_function_call(
                "publish_files",
                {"paths": ["out.csv"], "tool_call_id": "model-control"},
                tool_call_id="call-authentic",
            )
        )
        invalid_path = json.loads(
            handle_function_call(
                "publish_files",
                {"paths": ["other:profile/out.csv"]},
                tool_call_id="call-path",
            )
        )
    finally:
        reset_current_allies_file_publication_context(token)
    assert unavailable == _failure()
    assert oversized == _failure()
    assert malformed == _failure()
    assert invalid_path == _failure()

    requests: list[dict[str, object]] = []
    server, errors = _serve(
        [_published_file("a.csv"), _published_file("b.csv")], requests
    )
    call_a = _call(NONCE_A, "call-a", "a.csv")
    call_b = _call(NONCE_B, "call-b", "b.csv")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result()
            for future in (executor.submit(call_a), executor.submit(call_b))
        ]
    server.join(timeout=5)
    assert not server.is_alive() and not errors
    assert {json.loads(result)["state"] for result in results} == {"ready"}
    assert {request["context"] for request in requests} == {NONCE_A, NONCE_B}
    assert {request["tool_call_id"] for request in requests} == {"call-a", "call-b"}
    assert {tuple(request["paths"]) for request in requests} == {("a.csv",), ("b.csv",)}
    for result in results:
        assert NONCE_A not in result and NONCE_B not in result
        assert '"paths"' not in result

    unicode_name = "名" * 255
    requests = []
    server, errors = _serve([_published_file(unicode_name)], requests)
    token = set_current_allies_file_publication_context(NONCE_A)
    try:
        unicode_ready = json.loads(
            handle_function_call(
                "publish_files", {"paths": ["out.csv"]}, tool_call_id="call-unicode"
            )
        )
    finally:
        reset_current_allies_file_publication_context(token)
    server.join(timeout=5)
    assert not server.is_alive() and not errors
    assert unicode_ready == {
        "state": "ready",
        "files": [{"name": unicode_name, "open_path": "/files/id"}],
    }

    requests = []
    server, errors = _serve([b"x" * (64 * 1024 + 1) + b"\n"], requests)
    token = set_current_allies_file_publication_context(NONCE_A)
    try:
        too_large = json.loads(
            handle_function_call(
                "publish_files", {"paths": ["out.csv"]}, tool_call_id="call-response"
            )
        )
    finally:
        reset_current_allies_file_publication_context(token)
    server.join(timeout=5)
    assert not server.is_alive() and not errors and too_large == _failure()

    requests = []
    server, errors = _serve(
        [b'{"state":"failed","error":"sensitive/path.csv"}\n'], requests
    )
    token = set_current_allies_file_publication_context(NONCE_A)
    try:
        bridge_failed = json.loads(
            handle_function_call(
                "publish_files", {"paths": ["out.csv"]}, tool_call_id="call-failed"
            )
        )
    finally:
        reset_current_allies_file_publication_context(token)
    server.join(timeout=5)
    assert not server.is_alive() and not errors and bridge_failed == _failure()
    assert "sensitive/path.csv" not in json.dumps(bridge_failed)

    requests = []
    server, errors = _serve([_published_file(NONCE_A)], requests)
    token = set_current_allies_file_publication_context(NONCE_A)
    try:
        echoed_context = json.loads(
            handle_function_call(
                "publish_files", {"paths": ["out.csv"]}, tool_call_id="call-echo"
            )
        )
    finally:
        reset_current_allies_file_publication_context(token)
    server.join(timeout=5)
    assert not server.is_alive() and not errors and echoed_context == _failure()
    assert NONCE_A not in json.dumps(echoed_context)

    _test_executor_binding()
    _test_private_capability_boundary()
    print("file publication tool: PASS")


if __name__ == "__main__":
    main()
