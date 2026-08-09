from __future__ import annotations

import asyncio
import json
from urllib.error import HTTPError

import pytest

from allies_runtime.config import load_settings
from allies_runtime.errors import (
    HermesAuthenticationError,
    HermesDisconnected,
    HermesMalformedResponse,
    HermesTimeout,
)
from allies_runtime.hermes import (
    HermesClient,
    UnixSocketCredentialResolver,
    _IncrementalHTTPStream,
)
from allies_runtime.hermes import (
    test_credential_for_reference as derive_test_credential,
)


class FakeResponse:
    def __init__(self, body=b"", lines=()):
        self.body = body
        self.lines = tuple(lines)
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
            b"event: run.completed\n",
            b'data: {"session_id":"s1","run_id":"r1","seq":2}\n',
            b"\n",
            b"data: [DONE]\n\n",
        ]
    )

    class IncrementalResponse(FakeResponse):
        def readline(self, _limit):
            return next(lines, b"")

    response = IncrementalResponse()
    client, _ = _client(monkeypatch, response)
    stream = await client.stream_profile_incremental("ally-a", "s1", "hello")
    first = await stream.__anext__()
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
                    b"event:\n",
                    b'data: {"session_id":"s1","run_id":"r1"}\n',
                    b"\n",
                    b"data: [DONE]\n\n",
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
