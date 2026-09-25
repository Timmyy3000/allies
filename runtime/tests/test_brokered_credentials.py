from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from allies_runtime import observability
from allies_runtime.composition import compose_runtime
from allies_runtime.config import load_settings
from allies_runtime.foundry import FoundryClient, FoundryError

REF = "allies-key://model-keys/0f0b3a1e-7d4c-4f00-9b1a-3c2d1e0f9a8b"


class Transport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def request(self, method, path, *, headers, body=None):
        self.calls.append((method, path, headers, body))
        return self.response


def test_blocking_resolution_calls_foundry_with_runtime_token():
    transport = Transport({"status": 200, "body": {"value": "tenant-secret"}})
    client = FoundryClient(runtime_token="runtime-token", transport=transport)

    assert client.resolve_credential_blocking(REF) == "tenant-secret"
    method, path, headers, body = transport.calls[0]
    assert (method, path, body) == (
        "POST",
        "/api/v1/runtime/credentials/resolve",
        {"reference": REF},
    )
    assert headers["Authorization"] == "Bearer runtime-token"


@pytest.mark.asyncio
async def test_blocking_resolution_works_inside_a_running_loop():
    transport = Transport({"status": 200, "body": {"value": "tenant-secret"}})
    client = FoundryClient(runtime_token="runtime-token", transport=transport)

    assert asyncio.get_running_loop()
    assert client.resolve_credential_blocking(REF) == "tenant-secret"


@pytest.mark.parametrize(
    "response",
    [
        {"status": 404, "body": {"code": "NOT_FOUND"}},
        {"status": 200, "body": {"value": ""}},
        {"status": 200, "body": {}},
    ],
)
def test_unavailable_or_malformed_resolution_raises(response):
    client = FoundryClient(runtime_token="runtime-token", transport=Transport(response))

    with pytest.raises(FoundryError):
        client.resolve_credential_blocking(REF)


def test_composition_routes_only_broker_refs_to_foundry(tmp_path):
    transport = Transport({"status": 200, "body": {"value": "tenant-secret"}})
    settings = replace(
        load_settings({"HERMES_CREDENTIAL_REF": "vault://hermes/runtime"}),
        volume_root=str(tmp_path / "volume"),
        marker_path=str(tmp_path / "volume" / "proof"),
    )
    seen = []

    def local_resolver(reference):
        seen.append(str(reference))
        return "local-secret"

    composition = compose_runtime(
        settings,
        FoundryClient(runtime_token="runtime-token", transport=transport),
        local_resolver,
        hermes=object(),
    )
    resolve = composition.profile_store.credential_resolver

    assert resolve(REF) == "tenant-secret"
    assert resolve(REF.upper()) == "tenant-secret"
    assert resolve("file:///run/secrets/openai") == "local-secret"
    assert seen == ["file:///run/secrets/openai"]
    assert len(transport.calls) == 2
    observability.configure_runtime_observability()


def test_blocking_resolution_returns_on_timeout(monkeypatch):
    import time

    from allies_runtime import foundry as foundry_module

    class Hanging:
        async def request(self, method, path, *, headers, body=None):
            await asyncio.sleep(2)
            return {"status": 200, "body": {"value": "late"}}

    monkeypatch.setattr(foundry_module, "BROKERED_CREDENTIAL_TIMEOUT_SECONDS", 0.1)
    client = FoundryClient(runtime_token="runtime-token", transport=Hanging())
    started = time.monotonic()

    with pytest.raises(TimeoutError):
        client.resolve_credential_blocking(REF)
    assert time.monotonic() - started < 1


def test_timeouts_reuse_a_bounded_worker_pool(monkeypatch):
    import threading

    from allies_runtime import foundry as foundry_module

    class Hanging:
        async def request(self, method, path, *, headers, body=None):
            await asyncio.sleep(0.3)
            return {"status": 200, "body": {"value": "late"}}

    monkeypatch.setattr(foundry_module, "BROKERED_CREDENTIAL_TIMEOUT_SECONDS", 0.01)
    client = FoundryClient(runtime_token="runtime-token", transport=Hanging())
    for _ in range(5):
        with pytest.raises(TimeoutError):
            client.resolve_credential_blocking(REF)

    workers = [
        t for t in threading.enumerate() if t.name.startswith("allies-credential")
    ]
    assert len(workers) <= 2
