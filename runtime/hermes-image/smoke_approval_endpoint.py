"""Exercise rich Hermes approvals through the pinned HTTP/SSE seam.

The smoke intentionally uses the real approval module and aiohttp handlers;
only the model execution is represented by blocked approval waiter threads.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import time
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from gateway.config import GatewayConfig, PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from hermes_state import SessionDB
from tools import approval

PROFILE = "ally-approval-smoke"
SESSION_ID = "approval-endpoint-smoke"
PROFILE_KEY = "allies-approval-profile-key-0001"
MEMORY_KEY = "allies-approval-memory-key-0001"
SYNTHETIC_QUERY_SECRET = "synthetic-opaque-query-secret"
SYNTHETIC_FRAGMENT_SECRET = "synthetic-fragment-secret"


def _seed_profile(root: Path) -> None:
    profile = root / "profiles" / PROFILE
    profile.mkdir(parents=True)
    (profile / ".env").write_text(f"API_SERVER_KEY={PROFILE_KEY}\n", encoding="utf-8")
    database = SessionDB(profile / "state.db")
    try:
        database.create_session(SESSION_ID, "api_server")
    finally:
        database.close()
    # Windows checkouts may lack Hermes' optional file-lock dependency, so
    # the smoke uses a no-op profile scope there.  Seed the corresponding
    # default-home database as well so the real stream handler still exercises
    # its session lookup in that portable fallback.
    database = SessionDB(root / "state.db")
    try:
        database.create_session(SESSION_ID, "api_server")
    finally:
        database.close()


def _app(adapter: APIServerAdapter) -> web.Application:
    app = web.Application(middlewares=[adapter._make_profile_prefix_middleware()])
    for method, path, handler in adapter._http_route_table():
        if path not in {
            "/api/sessions/{session_id}/chat/stream",
            "/api/sessions/{session_id}/approval",
            "/api/sessions/{session_id}/approval/{hermes_approval_id}",
        }:
            continue
        app.router.add_route(method, path, handler)
        app.router.add_route(method, f"/p/{{profile}}{path}", handler)
    return app


def _start_waiter(
    *,
    run_id: str,
    action_kind: str,
    command: str,
    action_label: str,
    gate_lock=None,
):
    request_events: list[dict] = []
    response_events: list[dict] = []
    result_box: list[dict] = []
    notify = lambda payload: request_events.append(dict(payload))
    context = {
        "profile_id": PROFILE,
        "session_id": SESSION_ID,
        "run_id": run_id,
        "session_key": MEMORY_KEY,
        "gate_lock": gate_lock,
        "response_callback": lambda payload: response_events.append(dict(payload)),
    }

    def _run() -> None:
        context_token = approval.set_current_hermes_approval_context(**context)
        session_token = approval.set_current_session_key(run_id)
        try:
            approval.register_gateway_notify(run_id, notify)
            result_box.append(
                approval._await_gateway_decision(
                    run_id,
                    notify,
                    {
                        "command": command,
                        "pattern_key": run_id,
                        "pattern_keys": [run_id],
                        "description": "Synthetic smoke approval",
                        "action_kind": action_kind,
                        "action_label": action_label,
                    },
                )
            )
        finally:
            approval.unregister_gateway_notify(run_id)
            approval.reset_current_session_key(session_token)
            approval.reset_current_hermes_approval_context(context_token)

    thread = threading.Thread(target=_run, name=f"approval-smoke-{run_id}")
    thread.start()
    for _ in range(200):
        if request_events:
            break
        time.sleep(0.01)
    assert request_events, f"approval request was not emitted for {run_id}"
    return thread, request_events, response_events, result_box


def _deadline(seconds: float) -> str:
    return (
        (datetime.now(UTC) + timedelta(seconds=seconds))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


async def _run() -> None:
    previous_home = os.environ.get("HERMES_HOME")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        os.environ["HERMES_HOME"] = str(root)
        _seed_profile(root)
        adapter = APIServerAdapter(PlatformConfig(extra={"key": PROFILE_KEY}))
        adapter.gateway_runner = SimpleNamespace(
            config=GatewayConfig(multiplex_profiles=True)
        )
        if os.name == "nt":
            # The production image runs Linux with the full profile runtime.
            # Keep the smoke executable from a Windows checkout whose local
            # venv may not include Hermes' optional file-lock dependency.
            adapter._profile_scope = lambda _profile: nullcontext()
            adapter._expected_api_key = lambda: PROFILE_KEY
        try:
            async with TestClient(TestServer(_app(adapter))) as client:
                headers = {
                    "Authorization": f"Bearer {PROFILE_KEY}",
                    "X-Hermes-Session-Key": MEMORY_KEY,
                }

                class _SmokeAgent:
                    """Tiny agent double used behind the real _run_agent setup."""

                    session_id = SESSION_ID
                    session_prompt_tokens = 0
                    session_completion_tokens = 0
                    session_total_tokens = 0
                    provider = "smoke"
                    model = "smoke"
                    _hermes_api_runtime: ClassVar[dict] = {}
                    _last_compaction_in_place = False

                    def run_conversation(
                        self, *, user_message, conversation_history, task_id
                    ):
                        context = approval._hermes_approval_context.get()
                        assert context["session_id"] == SESSION_ID
                        assert task_id == SESSION_ID
                        assert approval.get_current_session_key() == context["run_id"]
                        with approval._lock:
                            notify = approval._gateway_notify_cbs[context["run_id"]]
                        decision = approval._await_gateway_decision(
                            context["run_id"],
                            notify,
                            {
                                "command": (
                                    "curl https://synthetic-user:synthetic-pass@host/invite"
                                    f"?token={SYNTHETIC_QUERY_SECRET}&public=1"
                                ),
                                "pattern_key": "stream-terminal",
                                "pattern_keys": ["stream-terminal"],
                                "description": "Synthetic stream approval",
                                "action_kind": "terminal",
                                "action_label": "Run terminal command",
                            },
                        )
                        assert decision["choice"] == "once"
                        return {
                            "session_id": SESSION_ID,
                            "final_response": "synthetic stream complete",
                            "messages": [],
                        }

                adapter._create_agent = lambda **_kwargs: _SmokeAgent()
                async with client.post(
                    f"/p/{PROFILE}/api/sessions/{SESSION_ID}/chat/stream",
                    headers={**headers, "X-Allies-Rich-Approvals": "1"},
                    json={"message": "run synthetic approval stream"},
                ) as stream:
                    if stream.status != 200:
                        raise AssertionError(
                            f"stream status={stream.status} body={await stream.text()}"
                        )
                    current_event = None
                    stream_events = []
                    while True:
                        line = await stream.content.readline()
                        if not line:
                            break
                        decoded = line.decode().rstrip("\n")
                        if decoded.startswith("event: "):
                            current_event = decoded.removeprefix("event: ")
                        elif decoded.startswith("data: "):
                            payload = json.loads(decoded.removeprefix("data: "))
                            stream_events.append((current_event, payload))
                            if current_event == "approval.request":
                                required = {
                                    "session_id",
                                    "run_id",
                                    "hermes_approval_id",
                                    "action_kind",
                                    "action_label",
                                    "action_preview",
                                    "expires_at",
                                }
                                assert required <= set(payload)
                                assert "synthetic-pass" not in payload["action_preview"]
                                stream_resolved = await client.post(
                                    f"/p/{PROFILE}/api/sessions/{SESSION_ID}/approval",
                                    headers=headers,
                                    json={
                                        "run_id": payload["run_id"],
                                        "hermes_approval_id": payload[
                                            "hermes_approval_id"
                                        ],
                                        "decision": "approve",
                                        "deadline_at": payload["expires_at"],
                                    },
                                )
                                assert stream_resolved.status == 202
                    stream_names = [name for name, _payload in stream_events]
                    assert "approval.request" in stream_names
                    assert "approval.responded" in stream_names
                    responded = next(
                        payload
                        for name, payload in stream_events
                        if name == "approval.responded"
                    )
                    assert responded["outcome"] == "approved"
                    assert stream_names[-1] == "done"

                # Structured plugin previews retain material destinations and
                # only mask credential-shaped values.  A normal long document
                # path and recipient/workspace query are useful context for a
                # human decision; an opaque invite value never crosses the
                # boundary.
                document_preview = approval._safe_hermes_plugin_preview(
                    json.dumps(
                        {
                            "tool": "open_document",
                            "args": {
                                "documentUrl": (
                                    "https://host/doc/very-long-document-name"
                                    "?workspace=allies&recipient=team#section"
                                )
                            },
                        }
                    )
                )
                assert document_preview is not None
                assert "very-long-document-name" in document_preview
                assert "workspace=allies" in document_preview
                assert "recipient=team" in document_preview
                assert (
                    approval._safe_hermes_plugin_preview(
                        json.dumps(
                            {
                                "tool": "connect",
                                "args": {
                                    "inviteUrl": (
                                        "https://host/invite/opaque"
                                        f"?opaque={SYNTHETIC_QUERY_SECRET}"
                                    )
                                },
                            }
                        )
                    )
                    is None
                )

                # Preview construction occurs outside the registration lock.
                # If the stream disappears during that work, the second
                # callback identity check must deny without publishing a
                # receipt or leaving a waiter in the queue.
                preview_cancel_run = "approval-preview-cancelled-run"
                preview_cancel_events: list[dict] = []
                preview_cancel_context = {
                    "profile_id": PROFILE,
                    "session_id": SESSION_ID,
                    "run_id": preview_cancel_run,
                    "session_key": MEMORY_KEY,
                    "gate_lock": None,
                    "response_callback": None,
                }
                preview_cancel_token = approval.set_current_hermes_approval_context(
                    **preview_cancel_context
                )
                preview_cancel_session_token = approval.set_current_session_key(
                    preview_cancel_run
                )
                preview_cancel_notify = lambda payload: preview_cancel_events.append(
                    dict(payload)
                )
                before_preview_records = set(approval._hermes_approval_records)
                original_plugin_preview = approval._safe_hermes_plugin_preview

                def _cancel_during_preview(command: str):
                    approval.unregister_gateway_notify(preview_cancel_run)
                    return original_plugin_preview(command)

                approval._safe_hermes_plugin_preview = _cancel_during_preview
                try:
                    approval.register_gateway_notify(
                        preview_cancel_run, preview_cancel_notify
                    )
                    preview_cancel_result = approval._await_gateway_decision(
                        preview_cancel_run,
                        preview_cancel_notify,
                        {
                            "command": json.dumps(
                                {
                                    "tool": "connect",
                                    "args": {
                                        "inviteUrl": (
                                            "https://host/invite/opaque"
                                            f"?token={SYNTHETIC_QUERY_SECRET}"
                                            "&workspace=allies&recipient=team"
                                            f"#access_token={SYNTHETIC_FRAGMENT_SECRET}"
                                        )
                                    },
                                }
                            ),
                            "pattern_key": preview_cancel_run,
                            "pattern_keys": [preview_cancel_run],
                            "description": "Synthetic preview cancellation",
                            "action_kind": "plugin_tool",
                            "action_label": "Use connect plugin",
                        },
                    )
                finally:
                    approval._safe_hermes_plugin_preview = original_plugin_preview
                    approval.unregister_gateway_notify(preview_cancel_run)
                    approval.reset_current_session_key(preview_cancel_session_token)
                    approval.reset_current_hermes_approval_context(preview_cancel_token)
                assert preview_cancel_result["cancelled"] is True
                assert preview_cancel_events == []
                assert set(approval._hermes_approval_records) == before_preview_records
                assert not approval._gateway_queues.get(preview_cancel_run)

                def _assert_rich_rejected(
                    run_id: str, command: str, *, action_kind: str | None = "terminal"
                ) -> None:
                    """Assert a preview rejection never creates a live receipt."""

                    events: list[dict] = []
                    notify = lambda payload: events.append(dict(payload))
                    context_token = approval.set_current_hermes_approval_context(
                        profile_id=PROFILE,
                        session_id=SESSION_ID,
                        run_id=run_id,
                        session_key=MEMORY_KEY,
                        gate_lock=None,
                        response_callback=None,
                    )
                    session_token = approval.set_current_session_key(run_id)
                    before_records = set(approval._hermes_approval_records)
                    try:
                        approval.register_gateway_notify(run_id, notify)
                        approval_data = {
                            "command": command,
                            "pattern_key": run_id,
                            "pattern_keys": [run_id],
                            "description": "Synthetic fail-closed preview",
                            "action_label": "Run terminal command",
                        }
                        if action_kind is not None:
                            approval_data["action_kind"] = action_kind
                        result = approval._await_gateway_decision(
                            run_id,
                            notify,
                            approval_data,
                        )
                    finally:
                        approval.unregister_gateway_notify(run_id)
                        approval.reset_current_session_key(session_token)
                        approval.reset_current_hermes_approval_context(context_token)
                    assert result["notify_failed"] is True
                    assert events == []
                    assert set(approval._hermes_approval_records) == before_records
                    assert not approval._gateway_queues.get(run_id)

                _assert_rich_rejected("approval-nul-run", "printf safe\x00payload")
                _assert_rich_rejected("approval-oversized-run", "x" * (16 * 1024 + 1))
                _assert_rich_rejected(
                    "approval-unsupported-kind-run",
                    "printf unsupported-kind",
                    action_kind="future_kind",
                )
                _assert_rich_rejected(
                    "approval-missing-kind-run",
                    "printf missing-kind",
                    action_kind=None,
                )

                missing_args_context = approval.set_current_hermes_approval_context(
                    profile_id=PROFILE,
                    session_id=SESSION_ID,
                    run_id="approval-plugin-missing-args-run",
                    session_key=MEMORY_KEY,
                )
                try:
                    missing_args_result = approval.request_tool_approval(
                        "connect", "Synthetic plugin approval without intercepted args"
                    )
                finally:
                    approval.reset_current_hermes_approval_context(missing_args_context)
                assert missing_args_result["approved"] is False
                assert "preview" in missing_args_result["message"]

                import agent.redact as redact_module

                original_redactor = redact_module.redact_sensitive_text

                def _raise_redactor(*_args, **_kwargs):
                    raise RuntimeError("synthetic redactor failure")

                redact_module.redact_sensitive_text = _raise_redactor
                try:
                    _assert_rich_rejected(
                        "approval-redactor-failure-run", "printf safe-preview"
                    )
                finally:
                    redact_module.redact_sensitive_text = original_redactor

                # Terminal receipts younger than the retention window are
                # promises to resolver retries.  Capacity pressure must
                # reject a new request instead of evicting those receipts.
                previous_records = approval._hermes_approval_records.copy()
                try:
                    now = time.time()
                    approval._hermes_approval_records.clear()
                    approval._hermes_approval_records.update(
                        {
                            f"capacity-{index}": {
                                "status": "resolved",
                                "terminal_at": now,
                            }
                            for index in range(approval._HERMES_APPROVAL_MAX_RECORDS)
                        }
                    )
                    _assert_rich_rejected(
                        "approval-capacity-run", "printf capacity-preview"
                    )
                    assert len(approval._hermes_approval_records) == (
                        approval._HERMES_APPROVAL_MAX_RECORDS
                    )
                finally:
                    approval._hermes_approval_records.clear()
                    approval._hermes_approval_records.update(previous_records)

                terminal = _start_waiter(
                    run_id="approval-terminal-run",
                    action_kind="terminal",
                    action_label="Run terminal command",
                    command=(
                        "curl https://synthetic-user:synthetic-pass@host/invite"
                        f"?token={SYNTHETIC_QUERY_SECRET}&public=1"
                    ),
                )
                terminal_request = terminal[1][0]
                assert terminal_request["action_preview"] == (
                    "curl https://synthetic-user:***@host/invite?token=***&public=1"
                )
                assert len(terminal_request["action_preview"].encode()) <= 16 * 1024
                approval_id = terminal_request["hermes_approval_id"]
                resolve_body = {
                    "run_id": "approval-terminal-run",
                    "hermes_approval_id": approval_id,
                    "decision": "approve",
                    "deadline_at": terminal_request["expires_at"],
                }
                resolved = await client.post(
                    f"/p/{PROFILE}/api/sessions/{SESSION_ID}/approval",
                    headers=headers,
                    json=resolve_body,
                )
                assert resolved.status == 202
                assert (await resolved.json())["outcome"] == "approved"
                replay = await client.post(
                    f"/p/{PROFILE}/api/sessions/{SESSION_ID}/approval",
                    headers=headers,
                    json=resolve_body,
                )
                assert replay.status == 200
                assert (await replay.json())["status"] == "resolved"
                conflict = await client.post(
                    f"/p/{PROFILE}/api/sessions/{SESSION_ID}/approval",
                    headers=headers,
                    json={**resolve_body, "decision": "reject"},
                )
                assert conflict.status == 409
                status = await client.get(
                    f"/p/{PROFILE}/api/sessions/{SESSION_ID}/approval/{approval_id}",
                    headers=headers,
                    params={"run_id": "approval-terminal-run"},
                )
                assert status.status == 200
                assert (await status.json())["outcome"] == "approved"
                wrong_run = await client.get(
                    f"/p/{PROFILE}/api/sessions/{SESSION_ID}/approval/{approval_id}",
                    headers=headers,
                    params={"run_id": "another-run"},
                )
                assert wrong_run.status == 404
                wrong_key = await client.post(
                    f"/p/{PROFILE}/api/sessions/{SESSION_ID}/approval",
                    headers={**headers, "Authorization": "Bearer wrong-key"},
                    json=resolve_body,
                )
                assert wrong_key.status == 401
                terminal[0].join(2)
                assert not terminal[0].is_alive()
                assert terminal[2] == [
                    {"hermes_approval_id": approval_id, "outcome": "approved"}
                ]

                execute = _start_waiter(
                    run_id="approval-code-run",
                    action_kind="execute_code",
                    action_label="Run code",
                    command="print('synthetic code')",
                )
                execute_request = execute[1][0]
                execute_response = await client.post(
                    f"/p/{PROFILE}/api/sessions/{SESSION_ID}/approval",
                    headers=headers,
                    json={
                        "run_id": "approval-code-run",
                        "hermes_approval_id": execute_request["hermes_approval_id"],
                        "decision": "reject",
                        "deadline_at": execute_request["expires_at"],
                    },
                )
                assert execute_response.status == 202
                assert (await execute_response.json())["outcome"] == "rejected"
                execute[0].join(2)
                assert not execute[0].is_alive()

                plugin = _start_waiter(
                    run_id="approval-plugin-run",
                    action_kind="plugin_tool",
                    action_label="Use connect plugin",
                    command=json.dumps(
                        {
                            "tool": "connect",
                            "args": {
                                "inviteUrl": (
                                    "https://synthetic-user:synthetic-pass@host/invite/opaque"
                                    f"?token={SYNTHETIC_QUERY_SECRET}"
                                    "&workspace=allies&recipient=team"
                                    f"#access_token={SYNTHETIC_FRAGMENT_SECRET}"
                                )
                            },
                        }
                    ),
                )
                plugin_request = plugin[1][0]
                plugin_preview = plugin_request["action_preview"]
                assert "synthetic-pass" not in plugin_preview
                assert SYNTHETIC_QUERY_SECRET not in plugin_preview
                assert SYNTHETIC_FRAGMENT_SECRET not in plugin_preview
                assert "https://host/invite/opaque" in plugin_preview
                assert "workspace=allies" in plugin_preview
                assert "recipient=team" in plugin_preview
                plugin_response = await client.post(
                    f"/p/{PROFILE}/api/sessions/{SESSION_ID}/approval",
                    headers=headers,
                    json={
                        "run_id": "approval-plugin-run",
                        "hermes_approval_id": plugin_request["hermes_approval_id"],
                        "decision": "approve",
                        "deadline_at": plugin_request["expires_at"],
                    },
                )
                assert plugin_response.status == 202
                plugin[0].join(2)
                assert not plugin[0].is_alive()

                late = _start_waiter(
                    run_id="approval-late-run",
                    action_kind="terminal",
                    action_label="Run terminal command",
                    command="printf synthetic-late",
                )
                late_request = late[1][0]
                late_response = await client.post(
                    f"/p/{PROFILE}/api/sessions/{SESSION_ID}/approval",
                    headers=headers,
                    json={
                        "run_id": "approval-late-run",
                        "hermes_approval_id": late_request["hermes_approval_id"],
                        "decision": "approve",
                        "deadline_at": _deadline(-1),
                    },
                )
                assert late_response.status == 200
                assert (await late_response.json())["status"] == "expired"
                late_status = await client.get(
                    f"/p/{PROFILE}/api/sessions/{SESSION_ID}/approval/"
                    f"{late_request['hermes_approval_id']}",
                    headers=headers,
                    params={"run_id": "approval-late-run"},
                )
                assert late_status.status == 200
                assert (await late_status.json())["status"] == "expired"
                late[0].join(2)
                assert not late[0].is_alive()

                cancelled = _start_waiter(
                    run_id="approval-cancelled-run",
                    action_kind="terminal",
                    action_label="Run terminal command",
                    command="printf synthetic-cancelled",
                )
                approval.unregister_gateway_notify("approval-cancelled-run")
                cancelled[0].join(2)
                assert not cancelled[0].is_alive()
                assert cancelled[2] == [
                    {
                        "hermes_approval_id": cancelled[1][0]["hermes_approval_id"],
                        "outcome": "cancelled",
                    }
                ]
                cancelled_status = await client.get(
                    f"/p/{PROFILE}/api/sessions/{SESSION_ID}/approval/"
                    f"{cancelled[1][0]['hermes_approval_id']}",
                    headers=headers,
                    params={"run_id": "approval-cancelled-run"},
                )
                assert cancelled_status.status == 200
                assert (await cancelled_status.json())["status"] == "cancelled"
                cancelled_response = await client.post(
                    f"/p/{PROFILE}/api/sessions/{SESSION_ID}/approval",
                    headers=headers,
                    json={
                        "run_id": "approval-cancelled-run",
                        "hermes_approval_id": cancelled[1][0]["hermes_approval_id"],
                        "decision": "approve",
                        "deadline_at": cancelled[1][0]["expires_at"],
                    },
                )
                assert cancelled_response.status == 200
                cancelled_receipt = await cancelled_response.json()
                assert cancelled_receipt["status"] == "cancelled"
                assert cancelled_receipt["outcome"] == "cancelled"
        finally:
            for database in getattr(adapter, "_session_dbs", {}).values():
                database.close()
            await adapter.disconnect()
            if previous_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = previous_home


asyncio.run(_run())
