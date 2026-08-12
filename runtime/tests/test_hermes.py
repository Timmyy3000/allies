from __future__ import annotations

import asyncio
import json
from threading import Event
from urllib.error import HTTPError

import pytest

from allies_runtime.config import load_settings
from allies_runtime.errors import (
    HermesAuthenticationError,
    HermesDisconnected,
    HermesError,
    HermesMalformedResponse,
    HermesTimeout,
)
from allies_runtime.hermes import (
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
        self.status = status
        self.closed = False

    def read(self, limit=-1):
        return self.body

    def __iter__(self):
        return iter(self.lines)

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
        load_settings({"HERMES_CREDENTIAL_REF": "ref://bootstrap"}),
        lambda ref: "bootstrap-key",
        profile_credential_resolver=lambda key: "profile-a-key",
    )

    stream = await client.stream_profile_incremental(
        "ally-a", "s1", "hello", session_key="stable-key-1"
    )
    await stream.aclose()

    assert calls[0].get_header("Authorization") == "Bearer profile-a-key"
    assert calls[0].get_header("X-hermes-session-key") == "stable-key-1"


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
                    b'data: {"session_id":"s1","run_id":"r1","tool_name":"terminal","args":{"secret":"drop"}}\n',
                    b"\n",
                    b"event: tool.completed\n",
                    b'data: {"session_id":"s1","run_id":"r1","tool_name":"terminal","preview":"drop"}\n',
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
        "kind": "tool",
    }
    assert events[2].payload["status"] == "completed"
    assert events[3].session_id == "s2"
    assert events[3].payload == {"run_id": "r1", "status": "completed"}


def test_incremental_stream_rejects_invalid_tool_progress():
    stream = _IncrementalHTTPStream(object(), "ally-a", "s1")
    stream._normalize_event("run.started", {"session_id": "s1", "run_id": "r1"})

    with pytest.raises(HermesMalformedResponse, match="tool progress"):
        stream._normalize_event(
            "tool.progress", {"session_id": "s1", "run_id": "r1"}
        )


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

    events = [event async for event in _IncrementalHTTPStream(Response(), "ally-a", "s1")]

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

    events = [event async for event in _IncrementalHTTPStream(Response(), "ally-a", "s1")]

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
    with pytest.raises(HermesMalformedResponse, match="tool start"):
        current._normalize_event("tool.started", {"session_id": "s1", "run_id": "r1"})
    with pytest.raises(HermesMalformedResponse, match="out of order"):
        current._normalize_event(
            "tool.completed",
            {"session_id": "s1", "run_id": "r1", "tool_name": "terminal"},
        )
    current.active_activities.append(("terminal", "activity-1"))
    with pytest.raises(HermesMalformedResponse, match="run completion"):
        current._normalize_event(
            "run.completed",
            {"session_id": "s1", "run_id": "r1", "completed": True},
        )
    current.active_activities.clear()
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
        b'data: {"session_id":"s1","run_id":"r1","seq":2}\n',
        b"\n",
        b"data: [DONE]\n\n",
    ]
    response = FakeResponse(lines=lines)
    client, calls = _client(monkeypatch, response)
    result = await client.stream_profile("ally-a", "s1", "hello")
    assert result.profile_id == "ally-a"
    assert [event.sequence for event in result.events] == [1, 2]
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
