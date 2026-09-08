from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

import allies_runtime.hermes as hermes_module
from allies_runtime.config import load_settings
from allies_runtime.errors import (
    HermesAuthenticationError,
    HermesDisconnected,
    HermesError,
    HermesMalformedResponse,
    HermesTimeout,
    HermesTranscriptConflict,
)
from allies_runtime.hermes import (
    _ACTIVITY_KIND_ALIASES,
    ACTIVITY_KINDS,
    HermesBootstrap,
    HermesClient,
    UnixSocketCredentialResolver,
    _IncrementalHTTPStream,
    stable_session_identifiers,
)
from allies_runtime.hermes import (
    test_credential_for_reference as derive_test_credential,
)


class FakeResponse:
    def __init__(self, body=b"", lines=(), status=200):
        self.body = body
        self.lines = tuple(lines)
        self._rows = iter(self.lines)
        self.status = status
        self.closed = False

    def read(self, limit=-1):
        return self.body

    def __iter__(self):
        return iter(self.lines)

    def readline(self, _limit):
        return next(self._rows, b"")

    def close(self):
        self.closed = True


class FakeCredentialSocket:
    def __init__(self):
        self.sent = b""
        self.timeout = None
        self.connected = None
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def connect(self, path):
        self.connected = path

    def sendall(self, value):
        self.sent += value

    def recv(self, limit):
        assert limit == 4097
        return b"test-only-key\n"

    def close(self):
        self.closed = True


class FragmentedCredentialSocket(FakeCredentialSocket):
    def __init__(self):
        super().__init__()
        self.chunks = [b"test-", b"only-key\n"]
        self.limits = []

    def recv(self, limit):
        self.limits.append(limit)
        return self.chunks.pop(0) if self.chunks else b""


def _client(monkeypatch, response):
    settings = load_settings({"HERMES_CREDENTIAL_REF": "ref://test"})
    calls = []

    def open_url(request, timeout):
        calls.append(
            (
                request.full_url,
                request.get_header("Authorization"),
                timeout,
                request.data,
            )
        )
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("allies_runtime.hermes.urlopen", open_url)
    return HermesClient(settings, lambda ref: "test-only-key"), calls


def test_unix_socket_credential_resolver_keeps_reference_opaque(monkeypatch):
    import socket

    fake = FakeCredentialSocket()
    monkeypatch.setattr(socket, "AF_UNIX", 1, raising=False)
    monkeypatch.setattr(socket, "SOCK_STREAM", 2, raising=False)
    monkeypatch.setattr(socket, "socket", lambda *args: fake)
    resolver = UnixSocketCredentialResolver("/run/test.sock")
    from allies_runtime.config import CredentialReference

    assert resolver(CredentialReference("vault://proof/key")) == "test-only-key"
    assert fake.connected == "/run/test.sock"
    assert fake.sent == b"vault://proof/key\n"
    assert fake.closed


def test_unix_socket_credential_resolver_reassembles_fragmented_response(monkeypatch):
    import socket

    fake = FragmentedCredentialSocket()
    monkeypatch.setattr(socket, "AF_UNIX", 1, raising=False)
    monkeypatch.setattr(socket, "SOCK_STREAM", 2, raising=False)
    monkeypatch.setattr(socket, "socket", lambda *args: fake)
    resolver = UnixSocketCredentialResolver("/run/test.sock")

    from allies_runtime.config import CredentialReference

    assert resolver(CredentialReference("vault://proof/key")) == "test-only-key"
    assert fake.limits == [4097, 4092]
    assert fake.closed


def test_test_credential_scheme_is_explicit_and_deterministic():
    from allies_runtime.config import CredentialReference
    from allies_runtime.errors import HermesAuthenticationError

    first = derive_test_credential(CredentialReference("test://fnd004/run-a"))
    assert first == derive_test_credential(CredentialReference("test://fnd004/run-a"))
    assert first != derive_test_credential(CredentialReference("test://fnd004/run-b"))
    with pytest.raises(HermesAuthenticationError):
        derive_test_credential(CredentialReference("vault://proof/key"))


def test_stable_session_identifiers_are_deterministic_and_domain_separated():
    first = stable_session_identifiers("profile-1", "cloud-1")
    repeated = stable_session_identifiers("profile-1", "cloud-1")
    other = stable_session_identifiers("profile-1", "cloud-2")

    assert first == repeated
    assert first != other
    assert first.candidate_id != first.session_key
    assert "profile-1" not in first.candidate_id
    assert "cloud-1" not in first.session_key


@pytest.mark.asyncio
async def test_health_sends_bearer_and_decodes_json(monkeypatch):
    response = FakeResponse(
        json.dumps({"status": "ready", "readiness": {"status": "ready"}}).encode()
    )
    client, calls = _client(monkeypatch, response)
    health = await client.health()
    assert health.status == "ready"
    assert calls[0][0].endswith("/health/detailed")
    assert calls[0][1] == "Bearer test-only-key"
    assert response.closed


@pytest.mark.asyncio
async def test_profile_session_history_confirms_persisted_marker(monkeypatch):
    response = FakeResponse(
        json.dumps(
            {
                "object": "list",
                "session_id": "s1",
                "data": [
                    {
                        "role": "user",
                        "content": "Remember the copper lighthouse is north.",
                    }
                ],
            }
        ).encode()
    )
    client, calls = _client(monkeypatch, response)

    assert await client.profile_session_matches_markers(
        "ally-a",
        "s1",
        "the copper lighthouse is north",
        "the blue orchard is east",
    )
    assert calls[0][0].endswith("/p/ally-a/api/sessions/s1/messages")
    assert calls[0][1] == "Bearer test-only-key"
    assert response.closed


@pytest.mark.asyncio
async def test_profile_session_history_rejects_peer_marker(monkeypatch):
    response = FakeResponse(
        json.dumps(
            {
                "object": "list",
                "session_id": "s1",
                "data": [
                    {
                        "role": "user",
                        "content": (
                            "The copper lighthouse is north and the blue orchard "
                            "is east."
                        ),
                    }
                ],
            }
        ).encode()
    )
    client, _calls = _client(monkeypatch, response)

    assert not await client.profile_session_matches_markers(
        "ally-a",
        "s1",
        "the copper lighthouse is north",
        "the blue orchard is east",
    )
    assert response.closed


@pytest.mark.asyncio
async def test_profile_session_create_uses_selected_profile_credential(monkeypatch):
    response = FakeResponse(
        json.dumps(
            {"object": "hermes.session", "session": {"id": "candidate-1"}}
        ).encode(),
        status=201,
    )
    settings = load_settings({"HERMES_CREDENTIAL_REF": "ref://bootstrap"})
    resolved = []
    calls = []

    def open_url(request, timeout):
        calls.append(request)
        return response

    monkeypatch.setattr("allies_runtime.hermes.urlopen", open_url)
    client = HermesClient(
        settings,
        lambda ref: "bootstrap-key",
        profile_credential_resolver=lambda key: resolved.append(key) or "profile-a-key",
    )

    session = await client.create_profile_session(
        "ally-a", "candidate-1", model="gpt-5.6-luna"
    )

    assert session.session_id == "candidate-1"
    assert resolved == ["ally-a"]
    assert calls[0].get_header("Authorization") == "Bearer profile-a-key"
    assert json.loads(calls[0].data) == {
        "id": "candidate-1",
        "model": "gpt-5.6-luna",
    }


@pytest.mark.asyncio
async def test_profile_bootstrap_uses_strict_private_payload(monkeypatch):
    response = FakeResponse(
        json.dumps(
            {
                "object": "hermes.session.bootstrap",
                "session_id": "candidate-1",
                "message_id": "8ef84387-581e-4e6f-a31d-6fbca75d95f4",
                "status": "created",
            }
        ).encode(),
        status=201,
    )
    client, calls = _client(monkeypatch, response)
    bootstrap = HermesBootstrap(
        message_id="8ef84387-581e-4e6f-a31d-6fbca75d95f4",
        text="Hi, I'm Nova.",
    )

    result = await client.bootstrap_session("ally-a", "candidate-1", bootstrap)

    assert result.status == "created"
    assert calls[0][0].endswith("/p/ally-a/api/sessions/candidate-1/bootstrap")
    assert json.loads(calls[0][3]) == {
        "schema_version": "v1",
        "kind": "assistant_transcript_bootstrap",
        "message_id": bootstrap.message_id,
        "text": bootstrap.text,
    }
    assert response.closed


@pytest.mark.asyncio
async def test_profile_bootstrap_rejects_conflict_and_malformed_success(monkeypatch):
    bootstrap = {
        "kind": "assistant_message",
        "message_id": "8ef84387-581e-4e6f-a31d-6fbca75d95f4",
        "text": "Hi, I'm Nova.",
    }
    conflict, _calls = _client(monkeypatch, FakeResponse(status=409))
    with pytest.raises(HermesTranscriptConflict):
        await conflict.bootstrap_session("ally-a", "candidate-1", bootstrap)

    malformed, _calls = _client(monkeypatch, FakeResponse(b"{}", status=200))
    with pytest.raises(HermesMalformedResponse):
        await malformed.bootstrap_session("ally-a", "candidate-1", bootstrap)


@pytest.mark.asyncio
async def test_profile_bootstrap_validates_identity_before_request(monkeypatch):
    client, calls = _client(monkeypatch, FakeResponse())
    with pytest.raises(ValueError):
        await client.bootstrap_session(
            "ally-a",
            "candidate-1",
            {"kind": "assistant_message", "message_id": "bad", "text": "hello"},
        )
    with pytest.raises(ValueError):
        await client.bootstrap_session(
            "ally-a",
            "candidate-1",
            {"kind": "user_message", "message_id": "bad", "text": "hello"},
        )
    with pytest.raises(TypeError):
        await client.bootstrap_session("ally-a", "candidate-1", object())
    assert calls == []


@pytest.mark.asyncio
async def test_profile_bootstrap_rejects_wrong_success_identity(monkeypatch):
    response = FakeResponse(
        json.dumps(
            {
                "object": "wrong",
                "session_id": "candidate-1",
                "message_id": "8ef84387-581e-4e6f-a31d-6fbca75d95f4",
                "status": "created",
            }
        ).encode()
    )
    client, _calls = _client(monkeypatch, response)
    with pytest.raises(HermesMalformedResponse):
        await client.bootstrap_session(
            "ally-a",
            "candidate-1",
            {
                "kind": "assistant_message",
                "message_id": "8ef84387-581e-4e6f-a31d-6fbca75d95f4",
                "text": "hello",
            },
        )


@pytest.mark.asyncio
async def test_profile_bootstrap_maps_timeout(monkeypatch):
    client, _calls = _client(monkeypatch, FakeResponse())

    async def timeout(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr("allies_runtime.hermes.asyncio.to_thread", timeout)
    with pytest.raises(HermesTimeout):
        await client.bootstrap_session(
            "ally-a",
            "candidate-1",
            {
                "kind": "assistant_message",
                "message_id": "8ef84387-581e-4e6f-a31d-6fbca75d95f4",
                "text": "hello",
            },
        )


@pytest.mark.asyncio
async def test_profile_credential_resolution_does_not_block_the_event_loop():
    started = Event()
    release = Event()

    def resolver(_profile_id):
        started.set()
        assert release.wait(1)
        return "profile-a-key"

    client = HermesClient(
        load_settings({"HERMES_CREDENTIAL_REF": "ref://bootstrap"}),
        lambda ref: "bootstrap-key",
        profile_credential_resolver=resolver,
    )
    task = asyncio.create_task(client._profile_credential("ally-a"))

    assert await asyncio.to_thread(started.wait, 0.5)
    release.set()

    assert await task == "profile-a-key"


@pytest.mark.asyncio
async def test_profile_session_conflict_requires_exact_inspection(monkeypatch):
    existing = FakeResponse(
        json.dumps(
            {"object": "hermes.session", "session": {"id": "candidate-1"}}
        ).encode()
    )
    conflict = HTTPError("private-url", 409, "exists", {}, None)
    responses = iter([conflict, existing])
    calls = []

    def open_url(request, timeout):
        calls.append(request)
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("allies_runtime.hermes.urlopen", open_url)
    client = HermesClient(
        load_settings({"HERMES_CREDENTIAL_REF": "ref://bootstrap"}),
        lambda ref: "bootstrap-key",
        profile_credential_resolver=lambda key: "profile-a-key",
    )

    session = await client.ensure_profile_session(
        "ally-a", "candidate-1", model="gpt-5.6-luna"
    )

    assert session.session_id == "candidate-1"
    assert [request.method for request in calls] == ["POST", "GET"]
    assert calls[1].full_url.endswith("/p/ally-a/api/sessions/candidate-1")


@pytest.mark.asyncio
async def test_incremental_profile_stream_sends_stable_session_key(monkeypatch):
    class Response(FakeResponse):
        def __init__(self):
            super().__init__()
            self.rows = iter(
                [
                    b"event: run.started\n",
                    b'data: {"session_id":"s1","run_id":"r1","seq":1}\n',
                    b"\n",
                ]
            )

        def readline(self, _limit):
            return next(self.rows, b"")

    calls = []

    def open_url(request, timeout):
        calls.append(request)
        return Response()

    monkeypatch.setattr("allies_runtime.hermes.urlopen", open_url)
    client = HermesClient(
        load_settings(
            {
                "HERMES_CREDENTIAL_REF": "ref://bootstrap",
                "ALLIES_RICH_APPROVALS_ENABLED": "true",
            }
        ),
        lambda ref: "bootstrap-key",
        profile_credential_resolver=lambda key: "profile-a-key",
    )

    stream = await client.stream_profile_incremental(
        "ally-a", "s1", "hello", session_key="stable-key-1"
    )
    await stream.aclose()

    assert calls[0].get_header("Authorization") == "Bearer profile-a-key"
    assert calls[0].get_header("X-hermes-session-key") == "stable-key-1"
    assert calls[0].get_header("X-allies-rich-approvals") == "1"


@pytest.mark.asyncio
async def test_incremental_profile_stream_emits_one_provider_lifecycle_pair(
    monkeypatch,
):
    class Response(FakeResponse):
        def __init__(self):
            super().__init__()
            self.rows = iter(
                [
                    b"event: run.started\n",
                    b'data: {"session_id":"s1","run_id":"r1"}\n',
                    b"\n",
                    b"event: run.completed\n",
                    b'data: {"session_id":"s1","run_id":"r1","completed":true,"messages":[{"role":"assistant","content":"hello"}]}\n',
                    b"\n",
                    b"event: done\n",
                    b'data: {"session_id":"s1","run_id":"r1"}\n',
                    b"\n",
                ]
            )

        def readline(self, _limit):
            return next(self.rows, b"")

    events = []
    monkeypatch.setattr(
        "allies_runtime.hermes.emit_runtime_event",
        lambda event: events.append(event),
    )
    client, _ = _client(monkeypatch, Response())

    stream = await client.stream_profile_incremental("ally-a", "s1", "hello")
    events_from_stream = [event async for event in stream]

    assert [event.name for event in events_from_stream] == ["execution.completed"]
    assert [event["event"] for event in events] == [
        "provider.operation.started",
        "provider.operation.succeeded",
    ]


@pytest.mark.asyncio
async def test_incremental_profile_stream_close_before_terminal_is_failure(
    monkeypatch,
):
    class Response(FakeResponse):
        def readline(self, _limit):
            return b""

    events = []
    monkeypatch.setattr(
        "allies_runtime.hermes.emit_runtime_event",
        lambda event: events.append(event),
    )
    client, _ = _client(monkeypatch, Response())

    stream = await client.stream_profile_incremental("ally-a", "s1", "hello")
    await stream.aclose()

    assert [event["event"] for event in events] == [
        "provider.operation.started",
        "provider.operation.failed",
    ]
    assert events[-1]["error_type"] == "HermesDisconnected"


@pytest.mark.asyncio
async def test_incremental_profile_stream_terminal_close_is_success(
    monkeypatch,
):
    class Response(FakeResponse):
        def __init__(self):
            super().__init__()
            self.rows = iter(
                [
                    b"event: run.started\n",
                    b'data: {"session_id":"s1","run_id":"r1"}\n',
                    b"\n",
                    b"event: run.completed\n",
                    b'data: {"session_id":"s1","run_id":"r1","completed":true,"messages":[{"role":"assistant","content":"hello"}]}\n',
                    b"\n",
                    b"event: done\n",
                    b'data: {"session_id":"s1","run_id":"r1"}\n',
                    b"\n",
                ]
            )

        def readline(self, _limit):
            return next(self.rows, b"")

    events = []
    monkeypatch.setattr(
        "allies_runtime.hermes.emit_runtime_event",
        lambda event: events.append(event),
    )
    client, _ = _client(monkeypatch, Response())

    stream = await client.stream_profile_incremental("ally-a", "s1", "hello")
    event = await stream.__anext__()
    assert event.name == "execution.completed"
    await stream.aclose()

    assert [event["event"] for event in events] == [
        "provider.operation.started",
        "provider.operation.succeeded",
    ]


@pytest.mark.asyncio
async def test_incremental_profile_stream_passes_overall_deadline_to_adapter(
    monkeypatch,
):
    class Response:
        def __init__(self):
            self.closed = False

        def readline(self, _limit):
            time.sleep(0.2)
            return b": keepalive\n"

        def close(self):
            self.closed = True

    response = Response()
    monkeypatch.setattr(
        "allies_runtime.hermes.urlopen", lambda *_args, **_kwargs: response
    )
    client = HermesClient(
        load_settings(
            {
                "HERMES_CREDENTIAL_REF": "ref://bootstrap",
                "HERMES_STREAM_TIMEOUT": "0.1",
            }
        ),
        lambda ref: "bootstrap-key",
        profile_credential_resolver=lambda key: "profile-a-key",
    )

    stream = await client.stream_profile_incremental("ally-a", "s1", "hello")
    with pytest.raises(HermesTimeout, match="stream timed out"):
        await stream.__anext__()

    assert response.closed is True


@pytest.mark.asyncio
async def test_incremental_stream_normalizes_safe_events_and_terminal_rotation():
    class Response:
        def __init__(self):
            self.rows = iter(
                [
                    b"event: run.started\n",
                    b'data: {"session_id":"s1","run_id":"r1","seq":80}\n',
                    b"\n",
                    b"event: message.started\n",
                    b'data: {"session_id":"s1","run_id":"r1","message":{"id":"m1"}}\n',
                    b"\n",
                    b"event: assistant.delta\n",
                    b'data: {"session_id":"s1","run_id":"r1","delta":"hello","private":"drop"}\n',
                    b"\n",
                    b"event: tool.progress\n",
                    b'data: {"session_id":"s1","run_id":"r1","tool_name":"_thinking","delta":"private reasoning"}\n',
                    b"\n",
                    b"event: tool.started\n",
                    b'data: {"session_id":"s1","run_id":"r1","tool_name":"terminal","tool_call_id":"call-terminal","args":{"secret":"drop"}}\n',
                    b"\n",
                    b"event: tool.completed\n",
                    b'data: {"session_id":"s1","run_id":"r1","tool_name":"terminal","tool_call_id":"call-terminal","is_error":false,"duration_ms":125,"preview":"drop"}\n',
                    b"\n",
                    b"event: assistant.completed\n",
                    b'data: {"session_id":"s2","run_id":"r1","content":"drop"}\n',
                    b"\n",
                    b"event: run.completed\n",
                    b'data: {"session_id":"s2","run_id":"r1","completed":true,"messages":["drop"]}\n',
                    b"\n",
                    b"event: done\n",
                    b'data: {"session_id":"s1","run_id":"r1"}\n',
                    b"\n",
                ]
            )

        def readline(self, _limit):
            return next(self.rows, b"")

        def close(self):
            return None

    stream = _IncrementalHTTPStream(Response(), "ally-a", "s1")
    events = [event async for event in stream]

    assert [event.name for event in events] == [
        "message.delta",
        "activity.started",
        "activity.completed",
        "execution.completed",
    ]
    assert [event.sequence for event in events] == [1, 2, 3, 4]
    assert events[0].payload == {"text": "hello"}
    assert events[1].payload == {
        "activity_id": events[2].payload["activity_id"],
        "activity_kind": "terminal",
    }
    assert events[2].payload == {
        "activity_id": events[1].payload["activity_id"],
        "activity_kind": "terminal",
        "status": "completed",
        "duration_ms": 125,
    }
    assert events[3].session_id == "s2"
    assert events[3].payload == {"run_id": "r1", "status": "completed"}


def _running_activity_stream():
    stream = _IncrementalHTTPStream(object(), "ally-a", "s1")
    stream._normalize_event("run.started", {"session_id": "s1", "run_id": "r1"})
    return stream


@pytest.mark.asyncio
async def test_incremental_stream_allows_expired_approval_receipt_before_turn_terminal(
    monkeypatch,
):
    expires_at = (datetime.now(UTC) + timedelta(seconds=10)).isoformat()

    class Response:
        def __init__(self):
            self.rows = iter(
                [
                    b"event: run.started\n",
                    b'data: {"session_id":"s1","run_id":"r1"}\n',
                    b"\n",
                    b"event: approval.request\n",
                    (
                        f'data: {{"session_id":"s1","run_id":"r1",'
                        f'"hermes_approval_id":"approval-1",'
                        f'"action_kind":"plugin_tool","action_label":"Connect",'
                        f'"action_preview":"Connect Nabu","expires_at":"{expires_at}"}}\n'
                    ).encode(),
                    b"\n",
                    b"event: approval.responded\n",
                    b'data: {"session_id":"s1","run_id":"r1","hermes_approval_id":"approval-1","outcome":"expired"}\n',
                    b"\n",
                    b"event: assistant.delta\n",
                    b'data: {"session_id":"s1","run_id":"r1","delta":"still running"}\n',
                    b"\n",
                    b"event: run.completed\n",
                    b'data: {"session_id":"s1","run_id":"r1","completed":true,"messages":["still running"]}\n',
                    b"\n",
                    b"event: done\n",
                    b'data: {"session_id":"s1","run_id":"r1"}\n',
                    b"\n",
                ]
            )
            self.closed = False

        def readline(self, _limit):
            return next(self.rows, b"")

        def close(self):
            self.closed = True

    response = Response()
    stream = _IncrementalHTTPStream(
        response,
        "ally-a",
        "s1",
        stream_timeout=5,
    )
    first = await stream.__anext__()
    assert first.name == "approval.request"
    monotonic = time.monotonic
    monkeypatch.setattr(
        hermes_module, "time", SimpleNamespace(monotonic=lambda: monotonic() + 11)
    )
    events = [event async for event in stream]
    await stream.aclose()

    assert [event.name for event in events] == [
        "approval.responded",
        "message.delta",
        "execution.completed",
    ]
    assert events[0].payload == {
        "hermes_approval_id": "approval-1",
        "outcome": "expired",
    }
    assert response.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["expired", "cancelled"])
async def test_resolve_approval_accepts_matching_terminal_receipt(monkeypatch, status):
    response = FakeResponse(
        body=json.dumps(
            {
                "profile_id": "ally-a",
                "session_id": "s1",
                "run_id": "r1",
                "hermes_approval_id": "approval-1",
                "status": status,
                "outcome": status,
            }
        ).encode()
    )
    client, _calls = _client(monkeypatch, response)

    result = await client.resolve_approval(
        "ally-a",
        "s1",
        "r1",
        "approval-1",
        "approve",
        deadline_at=datetime.now(UTC) + timedelta(seconds=20),
    )

    assert result["status"] == status
    assert response.closed


def _approval_request_payload(**changes):
    payload = {
        "session_id": "s1",
        "run_id": "r1",
        "hermes_approval_id": "approval-1",
        "action_kind": "plugin_tool",
        "action_label": "Connect Nabu",
        "action_preview": "Connect to Nabu",
        "expires_at": (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
    }
    payload.update(changes)
    return payload


@pytest.mark.parametrize(
    "changes",
    [
        {"session_id": None},
        {"unexpected": True},
        {"hermes_approval_id": "bad\nidentity"},
        {"action_kind": "unknown"},
        {"action_label": ""},
        {"action_label": "x" * 121},
        {"action_preview": ""},
        {"action_preview": "x" * 16_385},
        {"expires_at": "not-a-date"},
        {"expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()},
        {"expires_at": "future-too-far"},
    ],
)
def test_approval_request_rejects_untrusted_material_and_expiry(changes):
    stream = _running_activity_stream()
    if changes.get("expires_at") == "future-too-far":
        changes = {
            **changes,
            "expires_at": (datetime.now(UTC) + timedelta(seconds=301)).isoformat(),
        }
    with pytest.raises(HermesMalformedResponse):
        stream._normalize_event(
            "approval.request",
            _approval_request_payload(**changes),
        )


def test_approval_request_and_response_identity_cannot_be_reused_or_changed():
    stream = _running_activity_stream()
    request = stream._normalize_event(
        "approval.request",
        _approval_request_payload(),
    )
    assert request is not None and request.payload["hermes_approval_id"] == "approval-1"

    with pytest.raises(HermesMalformedResponse, match="duplicated"):
        stream._normalize_event(
            "approval.request",
            _approval_request_payload(hermes_approval_id="approval-2"),
        )
    with pytest.raises(HermesMalformedResponse, match="identity changed"):
        stream._normalize_event(
            "approval.responded",
            {
                "session_id": "s1",
                "run_id": "r1",
                "hermes_approval_id": "approval-2",
                "outcome": "expired",
            },
        )
    with pytest.raises(HermesMalformedResponse, match="outcome"):
        stream._normalize_event(
            "approval.responded",
            {
                "session_id": "s1",
                "run_id": "r1",
                "hermes_approval_id": "approval-1",
                "outcome": "maybe",
            },
        )

    responded = stream._normalize_event(
        "approval.responded",
        {
            "session_id": "s1",
            "run_id": "r1",
            "hermes_approval_id": "approval-1",
            "outcome": "cancelled",
        },
    )
    assert responded is not None and responded.payload["outcome"] == "cancelled"
    with pytest.raises(HermesMalformedResponse, match="duplicated"):
        stream._normalize_event(
            "approval.request",
            _approval_request_payload(hermes_approval_id="approval-1"),
        )


def test_legacy_completion_cannot_close_a_different_tool():
    stream = _running_activity_stream()
    base = {"session_id": "s1", "run_id": "r1"}
    stream._normalize_event("tool.started", {**base, "tool_name": "terminal"})
    with pytest.raises(HermesMalformedResponse):
        stream._normalize_event("tool.completed", {**base, "tool_name": "read_file"})


@pytest.mark.parametrize(
    "fields",
    [
        {"tool_call_id": "bad/id"},
        {"activity_kind": "terminal"},
        {"tool_name": "bad\nname"},
    ],
)
def test_activity_start_rejects_invalid_identity_and_hybrid_legacy(fields):
    stream = _running_activity_stream()
    with pytest.raises(HermesMalformedResponse):
        stream._normalize_event(
            "tool.started",
            {"session_id": "s1", "run_id": "r1", "tool_name": "terminal", **fields},
        )


def test_legacy_completion_rejects_rich_outcome_without_call_identity():
    stream = _running_activity_stream()
    payload = {"session_id": "s1", "run_id": "r1", "tool_name": "terminal"}
    stream._normalize_event("tool.started", payload)
    with pytest.raises(HermesMalformedResponse):
        stream._normalize_event("tool.completed", {**payload, "is_error": False})


def test_rich_completion_requires_outcome_and_call_identity_cannot_be_reused():
    stream = _running_activity_stream()
    payload = {
        "session_id": "s1",
        "run_id": "r1",
        "tool_name": "terminal",
        "tool_call_id": "call-a",
    }
    stream._normalize_event("tool.started", payload)
    with pytest.raises(HermesMalformedResponse):
        stream._normalize_event("tool.completed", payload)
    stream._normalize_event("tool.completed", {**payload, "is_error": False})
    with pytest.raises(HermesMalformedResponse):
        stream._normalize_event("tool.started", payload)


def test_correlated_activity_completion_is_id_based_and_preserves_out_of_order_results():
    stream = _running_activity_stream()
    started_a = stream._normalize_event(
        "tool.started",
        {
            "session_id": "s1",
            "run_id": "r1",
            "tool_name": "terminal",
            "tool_call_id": "call-a",
        },
    )
    started_b = stream._normalize_event(
        "tool.started",
        {
            "session_id": "s1",
            "run_id": "r1",
            "tool_name": "terminal",
            "tool_call_id": "call-b",
        },
    )

    completed_b = stream._normalize_event(
        "tool.completed",
        {
            "session_id": "s1",
            "run_id": "r1",
            "tool_name": "terminal",
            "tool_call_id": "call-b",
            "is_error": True,
            "duration_ms": 25,
        },
    )
    completed_a = stream._normalize_event(
        "tool.completed",
        {
            "session_id": "s1",
            "run_id": "r1",
            "tool_name": "terminal",
            "tool_call_id": "call-a",
            "is_error": False,
            "duration_ms": 125,
        },
    )

    assert started_a is not None and started_b is not None
    assert completed_a is not None and completed_b is not None
    assert started_a.payload["activity_id"] != started_b.payload["activity_id"]
    assert completed_b.payload == {
        "activity_id": started_b.payload["activity_id"],
        "activity_kind": "terminal",
        "status": "failed",
        "duration_ms": 25,
    }
    assert completed_a.payload == {
        "activity_id": started_a.payload["activity_id"],
        "activity_kind": "terminal",
        "status": "completed",
        "duration_ms": 125,
    }
    assert stream._active_activity_calls == {}


def test_producer_activity_kinds_and_aliases_match_contract_fixture():
    activity_contract_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "contracts"
        / "activity-presentation-v1.json"
    )
    activity_contract = json.loads(activity_contract_path.read_text(encoding="utf-8"))
    fixture_kinds = set(activity_contract["activity_kinds"])

    assert ACTIVITY_KINDS == fixture_kinds
    assert set(_ACTIVITY_KIND_ALIASES.values()) <= fixture_kinds


def test_activity_kind_normalization_is_allowlisted_and_legacy_shape_stays_exact():
    stream = _running_activity_stream()
    browser = stream._normalize_event(
        "tool.started",
        {
            "session_id": "s1",
            "run_id": "r1",
            "tool_name": "browser_click",
            "tool_call_id": "call-browser",
        },
    )
    unknown = stream._normalize_event(
        "tool.started",
        {
            "session_id": "s1",
            "run_id": "r1",
            "tool_name": "private_custom_tool",
            "tool_call_id": "call-private",
        },
    )
    assert (
        browser is not None and browser.payload["activity_kind"] == "browser_interact"
    )
    assert unknown is not None and unknown.payload["activity_kind"] == "unknown"

    legacy = _running_activity_stream()
    assert legacy._normalize_event(
        "tool.started",
        {
            "session_id": "s1",
            "run_id": "r1",
            "tool_name": "terminal",
            "preview": "private detail",
            "args": {"secret": "drop"},
        },
    ).payload == {"kind": "tool"}
    assert legacy._normalize_event(
        "tool.completed",
        {
            "session_id": "s1",
            "run_id": "r1",
            "tool_name": "terminal",
            "preview": "private detail",
        },
    ).payload == {"status": "completed"}


@pytest.mark.parametrize(
    "completion_patch",
    [
        {"tool_call_id": "stale"},
        {"tool_call_id": "call-1", "is_error": "false"},
        {"tool_call_id": "call-1", "duration_ms": True},
        {"tool_call_id": "call-1", "duration_ms": 0.5},
        {"tool_call_id": "call-1", "duration_ms": -1},
        {"tool_call_id": "call-1", "duration_ms": 86_400_001},
    ],
)
def test_correlated_activity_completion_rejects_stale_or_invalid_fields(
    completion_patch,
):
    stream = _running_activity_stream()
    stream._normalize_event(
        "tool.started",
        {
            "session_id": "s1",
            "run_id": "r1",
            "tool_name": "terminal",
            "tool_call_id": "call-1",
        },
    )
    payload = {
        "session_id": "s1",
        "run_id": "r1",
        "tool_name": "terminal",
        "is_error": False,
    }
    payload.update(completion_patch)
    with pytest.raises(HermesMalformedResponse):
        stream._normalize_event("tool.completed", payload)


@pytest.mark.asyncio
async def test_incremental_stream_accepts_terminal_after_more_than_512_raw_events():
    rows = [
        b"event: run.started\n",
        b'data: {"session_id":"s1","run_id":"r1"}\n',
        b"\n",
        b"event: message.started\n",
        b'data: {"session_id":"s1","run_id":"r1"}\n',
        b"\n",
    ]
    for index in range(510):
        if index == 255:
            rows.extend(
                [
                    b"event: tool.started\n",
                    b'data: {"session_id":"s1","run_id":"r1","tool_name":"calendar","tool_call_id":"call-calendar"}\n',
                    b"\n",
                    b"event: tool.progress\n",
                    b'data: {"session_id":"s1","run_id":"r1","tool_name":"calendar","delta":"private"}\n',
                    b"\n",
                    b"event: tool.completed\n",
                    b'data: {"session_id":"s1","run_id":"r1","tool_name":"calendar","tool_call_id":"call-calendar","is_error":false}\n',
                    b"\n",
                ]
            )
        rows.extend(
            [
                b"event: assistant.delta\n",
                f'data: {{"session_id":"s1","run_id":"r1","delta":"chunk-{index}"}}\n'.encode(),
                b"\n",
            ]
        )
    rows.extend(
        [
            b"event: assistant.completed\n",
            b'data: {"session_id":"s1","run_id":"r1","content":"ignored"}\n',
            b"\n",
            b"event: run.completed\n",
            b'data: {"session_id":"s1","run_id":"r1","completed":true,"messages":[]}\n',
            b"\n",
            b"event: done\n",
            b'data: {"session_id":"s1","run_id":"r1"}\n',
            b"\n",
        ]
    )

    class Response:
        def __init__(self):
            self.rows = iter(rows)
            self.closed = False

        def readline(self, _limit):
            return next(self.rows, b"")

        def close(self):
            self.closed = True

    events = [
        event async for event in _IncrementalHTTPStream(Response(), "ally-a", "s1")
    ]

    assert len(events) == 513
    assert sum(event.name == "message.delta" for event in events) == 510
    assert sum(event.name == "activity.started" for event in events) == 1
    assert sum(event.name == "activity.completed" for event in events) == 1
    assert events[-1].name == "execution.completed"
    assert events[-1].session_id == "s1"


@pytest.mark.asyncio
async def test_incremental_stream_enforces_overall_deadline_for_keepalives():
    class Response:
        def __init__(self):
            self.closed = False

        def readline(self, _limit):
            time.sleep(0.05)
            return b": keepalive\n"

        def close(self):
            self.closed = True

    response = Response()
    stream = _IncrementalHTTPStream(response, "ally-a", "s1", stream_timeout=0.01)

    with pytest.raises(HermesTimeout, match="stream timed out"):
        await stream.__anext__()

    assert response.closed is True


@pytest.mark.asyncio
async def test_incremental_stream_rejects_invalid_or_expired_overall_deadlines():
    with pytest.raises(ValueError, match="stream timeout must be positive"):
        _IncrementalHTTPStream(object(), "ally-a", "s1", stream_timeout=0)
    with pytest.raises(ValueError, match="stream timeout must be positive"):
        _IncrementalHTTPStream(object(), "ally-a", "s1", stream_timeout=True)

    class Response:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    response = Response()
    stream = _IncrementalHTTPStream(response, "ally-a", "s1", stream_timeout=1)
    stream.deadline = time.monotonic() - 1

    with pytest.raises(HermesTimeout, match="stream timed out"):
        await stream.__anext__()

    assert response.closed is True


def test_incremental_stream_rejects_invalid_tool_progress():
    stream = _IncrementalHTTPStream(object(), "ally-a", "s1")
    stream._normalize_event("run.started", {"session_id": "s1", "run_id": "r1"})

    with pytest.raises(HermesMalformedResponse, match="tool name"):
        stream._normalize_event("tool.progress", {"session_id": "s1", "run_id": "r1"})


@pytest.mark.asyncio
async def test_incremental_stream_uses_final_content_when_provider_emits_no_deltas():
    class Response:
        def __init__(self):
            self.rows = iter(
                [
                    b"event: run.started\n",
                    b'data: {"session_id":"s1","run_id":"r1"}\n',
                    b"\n",
                    b"event: assistant.completed\n",
                    b'data: {"session_id":"s1","run_id":"r1","content":"final answer"}\n',
                    b"\n",
                    b"event: run.completed\n",
                    b'data: {"session_id":"s1","run_id":"r1","completed":true,"messages":[{"role":"assistant","content":"final answer"}]}\n',
                    b"\n",
                    b"event: done\n",
                    b'data: {"session_id":"s1","run_id":"r1"}\n',
                    b"\n",
                ]
            )

        def readline(self, _limit):
            return next(self.rows, b"")

        def close(self):
            return None

    events = [
        event async for event in _IncrementalHTTPStream(Response(), "ally-a", "s1")
    ]

    assert [event.name for event in events] == [
        "message.delta",
        "execution.completed",
    ]
    assert events[0].payload == {"text": "final answer"}


@pytest.mark.asyncio
async def test_incremental_stream_accepts_empty_inline_transcript_after_completion():
    """Pinned Hermes can persist history while omitting it from run.completed."""

    class Response:
        def __init__(self):
            self.rows = iter(
                [
                    b"event: run.started\n",
                    b'data: {"session_id":"s1","run_id":"r1"}\n',
                    b"\n",
                    b"event: assistant.completed\n",
                    b'data: {"session_id":"s1","run_id":"r1","content":"final answer"}\n',
                    b"\n",
                    b"event: run.completed\n",
                    b'data: {"session_id":"s1","run_id":"r1","completed":true,"messages":[]}\n',
                    b"\n",
                    b"event: done\n",
                    b'data: {"session_id":"s1","run_id":"r1"}\n',
                    b"\n",
                ]
            )

        def readline(self, _limit):
            return next(self.rows, b"")

        def close(self):
            return None

    events = [
        event async for event in _IncrementalHTTPStream(Response(), "ally-a", "s1")
    ]

    assert [event.name for event in events] == [
        "message.delta",
        "execution.completed",
    ]
    assert events[0].payload == {"text": "final answer"}


@pytest.mark.asyncio
async def test_incremental_stream_rejects_empty_transcript_for_another_session():
    class Response:
        def __init__(self):
            self.rows = iter(
                [
                    b"event: run.started\n",
                    b'data: {"session_id":"s1","run_id":"r1"}\n',
                    b"\n",
                    b"event: assistant.completed\n",
                    b'data: {"session_id":"s2","run_id":"r1","content":"final answer"}\n',
                    b"\n",
                    b"event: run.completed\n",
                    b'data: {"session_id":"s3","run_id":"r1","completed":true,"messages":[]}\n',
                    b"\n",
                ]
            )

        def readline(self, _limit):
            return next(self.rows, b"")

        def close(self):
            return None

    stream = _IncrementalHTTPStream(Response(), "ally-a", "s1")

    with pytest.raises(HermesMalformedResponse, match="omitted its transcript"):
        [event async for event in stream]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows",
    [
        [
            b"event: run.started\n",
            b'data: {"session_id":"s1","run_id":"r1"}\n',
            b"\n",
        ],
        [
            b"event: run.started\n",
            b'data: {"session_id":"s1","run_id":"r1"}\n',
            b"\n",
            b"event: mystery.event\n",
            b'data: {"session_id":"s1","run_id":"r1"}\n',
            b"\n",
        ],
        [
            b"event: run.started\n",
            b'data: {"session_id":"s1","run_id":"r1"}\n\n',
            b"event: run.completed\n",
            b'data: {"session_id":"s1","run_id":"other","completed":true}\n',
            b"\n",
        ],
    ],
)
async def test_incremental_stream_fails_closed_on_incomplete_unknown_or_changed_run(
    rows,
):
    class Response:
        def __init__(self):
            self.rows = iter(rows)

        def readline(self, _limit):
            return next(self.rows, b"")

        def close(self):
            return None

    stream = _IncrementalHTTPStream(Response(), "ally-a", "s1")
    with pytest.raises(HermesMalformedResponse):
        [event async for event in stream]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (TimeoutError("private"), HermesTimeout),
        (OSError("private"), HermesDisconnected),
    ],
    ids=["timeout", "disconnect"],
)
async def test_incremental_stream_classifies_and_closes_read_failures(
    failure, expected
):
    class Response:
        def __init__(self):
            self.rows = iter(
                [
                    b"event: run.started\n",
                    b'data: {"session_id":"s1","run_id":"r1"}\n',
                    b"\n",
                ]
            )
            self.closed = False

        def readline(self, _limit):
            try:
                return next(self.rows)
            except StopIteration:
                raise failure from None

        def close(self):
            self.closed = True

    response = Response()
    stream = _IncrementalHTTPStream(response, "ally-a", "s1")

    with pytest.raises(expected):
        await stream.__anext__()

    assert response.closed is True


def test_incremental_state_machine_rejects_each_invalid_transition():
    def stream():
        return _IncrementalHTTPStream(object(), "ally-a", "s1")

    current = stream()
    with pytest.raises(HermesMalformedResponse, match="before run start"):
        current._normalize_event(
            "message.started", {"session_id": "s1", "run_id": "r1"}
        )
    with pytest.raises(HermesMalformedResponse, match="omitted run"):
        stream()._normalize_event("run.started", {"session_id": "s1"})
    with pytest.raises(HermesMalformedResponse, match="session identity"):
        stream()._normalize_event(
            "run.started", {"session_id": "other", "run_id": "r1"}
        )

    current = stream()
    current._normalize_event("run.started", {"session_id": "s1", "run_id": "r1"})
    with pytest.raises(HermesMalformedResponse, match="started out of order"):
        current._normalize_event("run.started", {"session_id": "s1", "run_id": "r1"})
    with pytest.raises(HermesMalformedResponse, match="completion session"):
        current._normalize_event(
            "assistant.completed",
            {"session_id": "bad/session", "run_id": "r1"},
        )
    with pytest.raises(HermesError, match="turn failure"):
        current._normalize_event("error", {"session_id": "s1", "run_id": "r1"})
    with pytest.raises(HermesMalformedResponse, match="delta"):
        current._normalize_event(
            "assistant.delta", {"session_id": "s1", "run_id": "r1", "delta": ""}
        )
    with pytest.raises(HermesMalformedResponse, match="tool name"):
        current._normalize_event("tool.started", {"session_id": "s1", "run_id": "r1"})
    with pytest.raises(HermesMalformedResponse, match="out of order"):
        current._normalize_event(
            "tool.completed",
            {"session_id": "s1", "run_id": "r1", "tool_name": "terminal"},
        )
    current._active_activity_calls["call-1"] = (
        "activity-" + "1" * 32,
        "terminal",
    )
    with pytest.raises(HermesMalformedResponse, match="run completion"):
        current._normalize_event(
            "run.completed",
            {
                "session_id": "s1",
                "run_id": "r1",
                "completed": True,
            },
        )
    current._active_activity_calls.clear()
    with pytest.raises(HermesMalformedResponse, match="omitted its transcript"):
        current._normalize_event(
            "run.completed",
            {
                "session_id": "s1",
                "run_id": "r1",
                "completed": True,
                "messages": [],
            },
        )
    with pytest.raises(HermesMalformedResponse, match="terminal session"):
        current._normalize_event(
            "run.completed",
            {
                "session_id": "bad/session",
                "run_id": "r1",
                "completed": True,
                "messages": [{"role": "assistant", "content": "ok"}],
            },
        )
    current._normalize_event(
        "run.completed",
        {
            "session_id": "s2",
            "run_id": "r1",
            "completed": True,
            "messages": [{"role": "assistant", "content": "ok"}],
        },
    )
    with pytest.raises(HermesMalformedResponse, match="after run completion"):
        current._normalize_event(
            "assistant.delta",
            {"session_id": "s1", "run_id": "r1", "delta": "late"},
        )
    with pytest.raises(HermesMalformedResponse, match="done identity"):
        current._normalize_event("done", {"session_id": "other", "run_id": "r1"})

    current = stream()
    current._normalize_event("run.started", {"session_id": "s1", "run_id": "r1"})
    with pytest.raises(HermesMalformedResponse, match="before run completion"):
        current._normalize_event("done", {"session_id": "s1", "run_id": "r1"})


@pytest.mark.asyncio
async def test_stream_is_profile_scoped_and_parses_events(monkeypatch):
    lines = [
        b"event: run.started\n",
        b'data: {"session_id":"s1","run_id":"r1","seq":1}\n',
        b"\n",
        b"event: run.completed\n",
        b'data: {"session_id":"s1","run_id":"r1","completed":true,"messages":[{"role":"assistant","content":"hello"}]}\n',
        b"\n",
        b"data: [DONE]\n\n",
    ]
    response = FakeResponse(lines=lines)
    client, calls = _client(monkeypatch, response)
    result = await client.stream_profile("ally-a", "s1", "hello")
    assert result.profile_id == "ally-a"
    assert [event.sequence for event in result.events] == [1]
    assert result.events[0].name == "execution.completed"
    assert "/p/ally-a/api/sessions/s1/chat/stream" in calls[0][0]
    assert json.loads(calls[0][3]) == {"message": "hello"}


@pytest.mark.asyncio
async def test_incremental_stream_yields_before_done_and_closes_response(monkeypatch):
    lines = iter(
        [
            b"event: run.started\n",
            b'data: {"session_id":"s1","run_id":"r1","seq":1}\n',
            b"\n",
            b"event: assistant.delta\n",
            b'data: {"session_id":"s1","run_id":"r1","delta":"hello"}\n',
            b"\n",
            b"event: run.completed\n",
            b'data: {"session_id":"s1","run_id":"r1","completed":true,"messages":[{"role":"assistant","content":"hello"}]}\n',
            b"\n",
            b"event: done\n",
            b'data: {"session_id":"s1","run_id":"r1"}\n',
            b"\n",
        ]
    )

    class IncrementalResponse(FakeResponse):
        def readline(self, _limit):
            return next(lines, b"")

    response = IncrementalResponse()
    client, _ = _client(monkeypatch, response)
    stream = await client.stream_profile_incremental("ally-a", "s1", "hello")
    first = await stream.__anext__()
    assert first.name == "message.delta"
    assert first.sequence == 1
    await stream.aclose()
    assert response.closed


@pytest.mark.asyncio
async def test_incremental_stream_consumes_done_and_ignores_comments(monkeypatch):
    class Response(FakeResponse):
        def __init__(self):
            super().__init__()
            self.rows = iter(
                [
                    b": keepalive\n",
                    b"event: run.started\n",
                    b'data: {"session_id":"s1","run_id":"r1"}\n',
                    b"\n",
                    b"event: run.completed\n",
                    b'data: {"session_id":"s1","run_id":"r1","completed":true,"messages":[{"role":"assistant","content":"hello"}]}\n',
                    b"\n",
                    b"event: done\n",
                    b'data: {"session_id":"s1","run_id":"r1"}\n',
                    b"\n",
                ]
            )

        def readline(self, _limit):
            return next(self.rows, b"")

    response = Response()
    monkeypatch.setattr(
        "allies_runtime.hermes.urlopen", lambda *_args, **_kwargs: response
    )
    client = HermesClient(
        load_settings({"HERMES_CREDENTIAL_REF": "ref://test"}), lambda ref: "key"
    )
    stream = await client.stream_profile_incremental("ally-a", "s1", "hello")
    event = await stream.__anext__()
    assert event.name == "execution.completed"
    assert event.sequence == 1
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line",
    [
        b"data: nope\n\n",
        b'data: {"session_id":"wrong","run_id":"r","seq":1}\n\n',
        b'data: {"session_id":"s1","seq":1}\n\n',
        b'data: {"session_id":"s1","run_id":"r","seq":0}\n\n',
        b"data: []\n\n",
        b"\xff\n",
    ],
)
async def test_incremental_stream_rejects_malformed_events(line):
    class Response:
        def __init__(self):
            self.rows = iter([line])

        def readline(self, _limit):
            return next(self.rows, b"")

        def close(self):
            return None

    stream = _IncrementalHTTPStream(Response(), "ally-a", "s1")
    with pytest.raises(HermesMalformedResponse):
        await stream.__anext__()


@pytest.mark.asyncio
async def test_incremental_stream_enforces_bounds_and_closed_state(monkeypatch):
    import allies_runtime.hermes as module

    class Response:
        def readline(self, _limit):
            return b"x" * 9

        def close(self):
            return None

    monkeypatch.setattr(module, "MAX_EVENT_BYTES", 8)
    stream = _IncrementalHTTPStream(Response(), "ally-a", "s1")
    with pytest.raises(HermesMalformedResponse):
        await stream.__anext__()
    stream.closed = True
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_http_auth_failure_is_classified(monkeypatch, status):
    error = HTTPError("http://127.0.0.1:8642/health", status, "no", {}, None)
    client, _ = _client(monkeypatch, error)
    with pytest.raises(HermesAuthenticationError):
        await client.health()


@pytest.mark.asyncio
async def test_malformed_and_bad_identity_streams_are_rejected(monkeypatch):
    malformed, _ = _client(monkeypatch, FakeResponse(lines=[b"data: nope\n\n"]))
    with pytest.raises(HermesMalformedResponse):
        await malformed.stream("ally-a", "s1", "hello")
    identity, _ = _client(
        monkeypatch,
        FakeResponse(lines=[b'data: {"session_id":"wrong","run_id":"r","seq":1}\n\n']),
    )
    with pytest.raises(HermesMalformedResponse):
        await identity.stream("ally-a", "s1", "hello")


@pytest.mark.asyncio
async def test_transport_disconnect_and_timeout(monkeypatch):
    disconnected, _ = _client(monkeypatch, OSError("private detail must not escape"))
    with pytest.raises(HermesDisconnected):
        await disconnected.health()
    settings = load_settings(
        {"HERMES_CREDENTIAL_REF": "ref://test", "HERMES_STREAM_TIMEOUT": "0.01"}
    )

    async def never():
        await asyncio.sleep(1)

    timeout_client = HermesClient(settings, lambda ref: "test-only-key")
    monkeypatch.setattr(timeout_client, "_credential", never)
    with pytest.raises(HermesTimeout):
        await timeout_client.stream("ally-a", "s1", "hello")


@pytest.mark.asyncio
@pytest.mark.parametrize("credential", ["bad\nheader", "x" * 4097])
async def test_credential_values_cannot_reach_http_headers(monkeypatch, credential):
    settings = load_settings({"HERMES_CREDENTIAL_REF": "ref://test"})
    client = HermesClient(settings, lambda ref: credential)
    with pytest.raises(HermesAuthenticationError, match="no credential"):
        await client.health()
