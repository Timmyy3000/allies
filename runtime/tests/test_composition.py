from __future__ import annotations

from collections import deque
from dataclasses import replace

from allies_runtime import (
    RuntimeComposition,
    compose_runtime,
    load_settings,
)
from allies_runtime.__main__ import worker_entrypoint
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
