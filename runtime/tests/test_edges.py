from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from allies_runtime.config import load_settings
from allies_runtime.coordinator import ProfileProofCoordinator
from allies_runtime.errors import (
    HermesAuthenticationError,
    HermesMalformedResponse,
    HermesTimeout,
)
from allies_runtime.fake import FakeHermesClient, FakeProfilePlan
from allies_runtime.hermes import (
    HermesClient,
    _bounded_lines,
    _decode_json,
    _profile_path,
    _read_bounded,
    _session_path,
    _sse_events,
)
from allies_runtime.smoke import run_smoke
from allies_runtime.volume import marker_namespace, observe_volume_marker


class Readable:
    def __init__(self, body=b""):
        self.body = body

    def read(self, limit=-1):
        return self.body


def test_parser_limits_and_sse_defensive_cases():
    with pytest.raises(HermesMalformedResponse):
        _read_bounded(Readable(b"x" * 4), limit=3)
    with pytest.raises(HermesMalformedResponse):
        _decode_json(b"not-json")
    with pytest.raises(HermesMalformedResponse):
        _decode_json(b"[]")
    assert _sse_events(
        [b": keepalive\n", b"ignored\n", b"event:\n", b'data: {"x": 1}\n\n']
    ) == [("message", {"x": 1})]
    with pytest.raises(HermesMalformedResponse):
        _sse_events([b"data: nope\n"])
    with pytest.raises(HermesMalformedResponse):
        _sse_events([b"\xff\n"])


def test_sse_stream_and_event_byte_limits(monkeypatch):
    monkeypatch.setattr("allies_runtime.hermes.MAX_EVENT_BYTES", 8)
    with pytest.raises(HermesMalformedResponse, match="event.*byte"):
        _sse_events([b"data: {}\n\n"])

    monkeypatch.setattr("allies_runtime.hermes.MAX_EVENT_BYTES", 64)
    monkeypatch.setattr("allies_runtime.hermes.MAX_STREAM_BYTES", 10)
    with pytest.raises(HermesMalformedResponse, match="stream.*byte"):
        _sse_events([b": 12345\n", b": 6789\n"])


def test_socket_sse_lines_are_read_with_a_hard_limit(monkeypatch):
    class ReadlineStream:
        def __init__(self):
            self.limits = []
            self.done = False

        def readline(self, limit):
            self.limits.append(limit)
            if self.done:
                return b""
            self.done = True
            return b"x" * limit

    stream = ReadlineStream()
    monkeypatch.setattr("allies_runtime.hermes.MAX_EVENT_BYTES", 8)
    with pytest.raises(HermesMalformedResponse, match="event.*byte"):
        _sse_events(_bounded_lines(stream))
    assert stream.limits and stream.limits[0] == 9


def test_profile_and_session_inputs_are_bounded():
    with pytest.raises(ValueError):
        _profile_path("../escape")
    with pytest.raises(ValueError):
        _session_path("bad/session")


def test_settings_error_boundaries():
    from allies_runtime.config import CredentialReference, SettingsError

    with pytest.raises(SettingsError):
        CredentialReference("sk-secret://value")
    with pytest.raises(SettingsError):
        load_settings({"HERMES_REQUEST_TIMEOUT": "not-a-number"})
    with pytest.raises(SettingsError):
        load_settings({"PROOF_SLOTS": "not-an-integer"})
    with pytest.raises(SettingsError):
        load_settings({"HERMES_ORIGIN": "http://[broken"})
    with pytest.raises(SettingsError):
        load_settings({"HERMES_ORIGIN": "http://127.0.0.1:1234"})
    with pytest.raises(SettingsError):
        load_settings({"VOLUME_MARKER_PATH": "/tmp/outside"})
    with pytest.raises(SettingsError):
        load_settings({"VOLUME_ROOT": "relative"})
    with pytest.raises(SettingsError):
        load_settings({"RUNTIME_IMAGE": "runtime:latest"})


@pytest.mark.asyncio
async def test_client_rejects_bad_credentials_and_messages(monkeypatch):
    settings = load_settings({"HERMES_CREDENTIAL_REF": "ref://test"})
    empty = HermesClient(settings, lambda ref: "")
    with pytest.raises(HermesAuthenticationError):
        await empty.health()
    bad = HermesClient(
        settings, lambda ref: (_ for _ in ()).throw(RuntimeError("private"))
    )
    with pytest.raises(HermesAuthenticationError):
        await bad.health()
    client = HermesClient(settings, lambda ref: "key")
    with pytest.raises(ValueError):
        await client.stream("bad/profile", "s", "hello")
    with pytest.raises(ValueError):
        await client.stream("a", "s", "")


@pytest.mark.asyncio
async def test_client_health_malformed_and_http_classification(monkeypatch):
    settings = load_settings({"HERMES_CREDENTIAL_REF": "ref://test"})
    client = HermesClient(settings, lambda ref: "key")

    class Response:
        def __init__(self, body):
            self.body = body

        def read(self, limit=-1):
            return self.body

        def close(self):
            pass

    monkeypatch.setattr(client, "_request", lambda **kwargs: Response(b'{"status": 1}'))
    with pytest.raises(HermesMalformedResponse):
        await client.health()
    monkeypatch.setattr(
        client, "_request", lambda **kwargs: Response(b'{"status":"ok","readiness":[]}')
    )
    with pytest.raises(HermesMalformedResponse):
        await client.health()


@pytest.mark.asyncio
async def test_coordinator_callback_and_empty_input():
    coordinator = ProfileProofCoordinator(FakeHermesClient(), slots=2)
    seen = []
    assert await coordinator.run_profiles({}) == ()
    await coordinator.run_turn("a", "hello", event_callback=seen.append)
    assert seen
    with pytest.raises(ValueError):
        ProfileProofCoordinator(FakeHermesClient(), slots=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["auth", "malformed", "disconnect", "timeout"])
async def test_fake_failure_modes_are_bounded(failure):
    client = FakeHermesClient({"a": FakeProfilePlan(failure=failure)})
    coordinator = ProfileProofCoordinator(client)
    expected = {
        "auth": HermesAuthenticationError,
        "malformed": HermesMalformedResponse,
        "disconnect": Exception,
        "timeout": HermesTimeout,
    }
    with pytest.raises(expected[failure]):
        await coordinator.run_turn("a", "hello")


def test_volume_missing_and_invalid_paths(tmp_path):
    missing = observe_volume_marker(tmp_path / "missing", volume_root=tmp_path)
    assert not missing.marker_exists
    with pytest.raises(ValueError):
        observe_volume_marker(tmp_path.parent / "outside", volume_root=tmp_path)
    with pytest.raises(ValueError):
        marker_namespace("../escape")


@pytest.mark.asyncio
async def test_smoke_reports_health_failure_without_raw_error():
    client = FakeHermesClient(health_status="malformed")
    result = await run_smoke("fake", client=client, run_id="fixed")
    payload = result.to_dict()
    assert any(
        item["name"] == "hermes_health" and item["status"] == "fail"
        for item in payload["checks"]
    )
    assert "malformed" in json.dumps(payload)


def test_pid1_entrypoint_main(monkeypatch, capsys):
    from allies_runtime import __main__

    monkeypatch.setattr(sys, "argv", ["allies-runtime", "--smoke", "fake"])
    assert __main__.main() == 0
    assert "different_profile_overlap" in capsys.readouterr().out


def test_default_entrypoint_keeps_runtime_alive(monkeypatch):
    from allies_runtime import __main__

    monkeypatch.setattr(sys, "argv", ["allies-runtime"])
    monkeypatch.setattr(__main__, "serve", lambda: 0)
    assert __main__.main() == 0


def test_readiness_requires_authenticated_hermes_probe():
    from allies_runtime import __main__

    class Healthy:
        async def health_detailed(self):
            return SimpleNamespace(status="ready")

    class Unauthenticated:
        async def health_detailed(self):
            raise HermesAuthenticationError("rejected")

    assert asyncio.run(__main__.probe_readiness(Healthy()))
    assert not asyncio.run(__main__.probe_readiness(Unauthenticated()))


def test_serve_fails_closed_without_secure_resolver(monkeypatch):
    from allies_runtime import __main__

    monkeypatch.setenv("HERMES_CREDENTIAL_REF", "vault://hermes/runtime")
    assert __main__.serve() == 1


def test_serve_keeps_proof_pid1_alive_during_bootstrap(monkeypatch):
    from allies_runtime import __main__

    monkeypatch.setenv("HERMES_CREDENTIAL_REF", "test://fnd004/proof")
    states = iter((False, True))
    runs = []

    async def readiness(_client):
        return next(states)

    def run(coro):
        runs.append(coro)
        coro.close()
        if len(runs) <= 2:
            return (False, True)[len(runs) - 1]
        raise KeyboardInterrupt

    monkeypatch.setattr(__main__, "probe_readiness", readiness)
    monkeypatch.setattr(__main__.asyncio, "run", run)
    monkeypatch.setattr(__main__.time, "sleep", lambda _: None)

    assert __main__.serve(client=object()) == 0
    assert len(runs) == 3


def test_live_entrypoint_fails_closed(monkeypatch, capsys):
    from allies_runtime import __main__

    monkeypatch.delenv("FND004_LIVE_SMOKE", raising=False)
    monkeypatch.setattr(sys, "argv", ["allies-runtime", "--smoke", "live"])
    assert __main__.main() == 1
    assert "live_capability_gate" in capsys.readouterr().out
