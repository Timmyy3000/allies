from __future__ import annotations

from collections import deque
from dataclasses import replace
from types import SimpleNamespace

import pytest

from allies_runtime import (
    RuntimeComposition,
    __main__,
    compose_runtime,
    load_settings,
)
from allies_runtime.__main__ import runtime_entrypoint, worker_entrypoint
from allies_runtime.composition import run_worker
from allies_runtime.config import CredentialReference
from allies_runtime.fake import FakeHermesClient
from allies_runtime.foundry import FoundryClient

PROFILE_ID = "00000000-0000-0000-0000-000000000001"
PROFILE_KEY = "ally-v1-00000000000000000000000000000001"


class QueueTransport:
    def __init__(self, *responses):
        self.responses = deque(responses)
        self.calls = []

    async def request(self, method, path, *, headers, body=None):
        self.calls.append((method, path, dict(headers), body))
        return self.responses.popleft()


def desired_state():
    return {
        "version": 1,
        "machine_generation": 3,
        "profiles": [
            {
                "profile_id": PROFILE_ID,
                "ally_ref": "ally-a",
                "hermes_profile_key": PROFILE_KEY,
                "hermes_profile_key_version": 1,
                "lifecycle_state": "active",
                "lifecycle_epoch": 0,
                "seed_version": 1,
                "seed_fingerprint": "a" * 64,
                "materialized_generation": 0,
                "seed": {
                    "version": 1,
                    "personality": "Exact personality",
                    "provider": "openai",
                    "model": "gpt-test",
                    "base_url": None,
                    "first_chat_instruction": "Ask one useful question.",
                    "first_chat_instruction_version": 1,
                    "credential_refs": {"provider_api": "vault://providers/ally-a"},
                },
            }
        ],
    }


def claim_response():
    return {
        "status": 200,
        "body": {
            "attempt_id": "attempt-1",
            "execution_id": "execution-1",
            "profile_id": PROFILE_ID,
            "hermes_profile_key": PROFILE_KEY,
            "model": "gpt-test",
            "conversation_id": "conversation-1",
            "session_id": "session-1",
            "stream_id": "stream-1",
            "lease_id": "lease-1",
            "lease_token": "lease-secret",
            "expires_at": "2026-08-09T12:00:00Z",
            "payload": {"message": "hello"},
            "claim_id": "claim-1",
        },
    }


def test_worker_entrypoint_composes_reconciliation_before_claims(tmp_path):
    transport = QueueTransport(
        desired_state(),
        {
            "profile_id": PROFILE_ID,
            "lifecycle_state": "active",
            "lifecycle_epoch": 0,
            "materialized_generation": 3,
            "seed_fingerprint": "a" * 64,
            "receipt_id": "pr-" + "a" * 32,
            "result_code": "created",
        },
        claim_response(),
        *(
            {"status": 202, "body": {"event_id": f"event-{index}", "sequence": index}}
            for index in (1, 2, 3)
        ),
        {
            "attempt_id": "attempt-1",
            "status": "succeeded",
            "receipt_id": "receipt-1",
        },
    )
    foundry = FoundryClient(runtime_token="runtime-secret", transport=transport)
    settings = replace(
        load_settings({"HERMES_CREDENTIAL_REF": "vault://hermes/runtime"}),
        volume_root=str(tmp_path / "volume"),
        marker_path=str(tmp_path / "volume" / "proof"),
    )

    composition = compose_runtime(
        settings,
        foundry,
        lambda _reference: "provider-secret",
        hermes=FakeHermesClient(),
        api_key_factory=lambda: "profile-local-key-0123456789",
    )

    assert isinstance(composition, RuntimeComposition)
    assert composition.worker.profile_reconciler is composition.profile_reconciler
    assert (
        worker_entrypoint(
            settings=settings,
            foundry=foundry,
            credential_resolver=lambda _reference: "provider-secret",
            hermes=composition.hermes,
            api_key_factory=lambda: "profile-local-key-0123456789",
            max_turns=1,
        )
        == 0
    )

    paths = [call[1] for call in transport.calls]
    assert paths[0] == "/api/v1/runtime/profiles/reconciliation"
    assert "/api/v1/runtime/claims" in paths
    assert paths.index("/api/v1/runtime/profiles/reconciliation") < paths.index(
        "/api/v1/runtime/claims"
    )
    assert (
        composition.profile_store.volume_root
        / "profiles"
        / PROFILE_KEY
        / ".allies-profile.json"
    ).exists()


@pytest.mark.asyncio
async def test_run_worker_can_keep_polling_until_the_worker_is_fenced():
    calls = []

    class Worker:
        async def run(self, *, max_turns, idle_cycles, idle_delay):
            calls.append((max_turns, idle_cycles, idle_delay))
            return ()

    composition = SimpleNamespace(worker=Worker())

    assert await run_worker(composition, idle_cycles=None, idle_delay=0.25) == ()
    assert calls == [(None, None, 0.25)]


def test_runtime_entrypoint_resolves_foundry_secret_at_composition_boundary(
    monkeypatch,
):
    captured = {}

    def foundry_factory(*, base_url, runtime_token):
        captured["foundry"] = (base_url, runtime_token)
        return object()

    def start_worker(**kwargs):
        captured["worker"] = kwargs
        return 0

    monkeypatch.setattr(__main__, "worker_entrypoint", start_worker)
    env = {
        "HERMES_CREDENTIAL_REF": "vault://hermes/runtime",
        "FOUNDRY_ORIGIN": "https://foundry.example.com",
        "FOUNDRY_RUNTIME_CREDENTIAL_REF": "file:///run/secrets/foundry-token",
        "VOLUME_ROOT": "/opt/data",
        "VOLUME_MARKER_PATH": "/opt/data/proof",
    }

    assert (
        runtime_entrypoint(
            env=env,
            credential_resolver=lambda _reference: "hermes-secret",
            foundry_credential_resolver=lambda _reference: "foundry-secret",
            foundry_factory=foundry_factory,
            hermes=FakeHermesClient(),
            idle_cycles=1,
        )
        == 0
    )

    assert captured["foundry"] == (
        "https://foundry.example.com",
        "foundry-secret",
    )
    assert captured["worker"]["idle_cycles"] == 1
    assert "foundry-secret" not in repr(captured["worker"]["settings"])


def test_runtime_entrypoint_uses_file_resolver_for_proof_credentials(
    monkeypatch, tmp_path
):
    secrets_root = tmp_path / "secrets"
    secrets_root.mkdir()
    hermes_key = secrets_root / "hermes-api-key"
    provider_key = secrets_root / "openai-api-key"
    hermes_key.write_text("hermes-key-strong-enough", encoding="utf-8")
    provider_key.write_text("provider-key", encoding="utf-8")
    monkeypatch.setattr(__main__, "_SECRETS_ROOT", secrets_root)
    captured = {}
    monkeypatch.setattr(
        __main__,
        "worker_entrypoint",
        lambda **kwargs: captured.update(kwargs) or 0,
    )

    result = runtime_entrypoint(
        env={
            "HERMES_CREDENTIAL_REF": hermes_key.as_uri(),
            "FOUNDRY_ORIGIN": "https://foundry.example.com",
            "FOUNDRY_RUNTIME_CREDENTIAL_REF": (
                "file:///run/secrets/foundry-runtime-token"
            ),
        },
        foundry_credential_resolver=lambda _reference: "foundry-secret",
        foundry_factory=lambda **_kwargs: object(),
        hermes=FakeHermesClient(),
        idle_cycles=1,
    )

    assert result == 0
    resolver = captured["credential_resolver"]
    assert resolver(CredentialReference(provider_key.as_uri())) == "provider-key"


def test_runtime_entrypoint_retries_hermes_during_startup(monkeypatch):
    states = iter((False, True))
    sleeps = []
    worker_calls = []

    async def readiness(_client):
        return next(states)

    monkeypatch.setattr(__main__, "probe_readiness", readiness)
    monkeypatch.setattr(__main__.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        __main__,
        "worker_entrypoint",
        lambda **kwargs: worker_calls.append(kwargs) or 0,
    )

    result = runtime_entrypoint(
        env={
            "HERMES_CREDENTIAL_REF": "vault://hermes/runtime",
            "FOUNDRY_ORIGIN": "https://foundry.example.com",
            "FOUNDRY_RUNTIME_CREDENTIAL_REF": (
                "file:///run/secrets/foundry-runtime-token"
            ),
        },
        credential_resolver=lambda _reference: "hermes-runtime-key",
        foundry_credential_resolver=lambda _reference: "foundry-secret",
        foundry_factory=lambda **_kwargs: object(),
        hermes=object(),
        idle_cycles=1,
    )

    assert result == 0
    assert sleeps == [0.25]
    assert len(worker_calls) == 1


def test_runtime_entrypoint_does_not_reuse_global_readiness_client_for_worker(
    monkeypatch,
):
    readiness_client = FakeHermesClient()
    worker_calls = []

    monkeypatch.setattr(
        __main__, "HermesClient", lambda _settings, _resolver: readiness_client
    )
    monkeypatch.setattr(
        __main__, "worker_entrypoint", lambda **kwargs: worker_calls.append(kwargs) or 0
    )

    result = runtime_entrypoint(
        env={
            "HERMES_CREDENTIAL_REF": "vault://hermes/runtime",
            "FOUNDRY_ORIGIN": "https://foundry.example.com",
            "FOUNDRY_RUNTIME_CREDENTIAL_REF": (
                "file:///run/secrets/foundry-runtime-token"
            ),
        },
        credential_resolver=lambda _reference: "hermes-runtime-key",
        foundry_credential_resolver=lambda _reference: "foundry-secret",
        foundry_factory=lambda **_kwargs: object(),
        idle_cycles=1,
    )

    assert result == 0
    assert len(worker_calls) == 1
    assert worker_calls[0]["hermes"] is None
