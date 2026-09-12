from __future__ import annotations

import json
from uuid import uuid4

import pytest

from allies_runtime.config import load_settings
from allies_runtime.errors import HermesError, HermesMalformedResponse
from allies_runtime.hermes import HermesClient

PROFILE_KEY = "ally-v1-00000000000000000000000000000001"


class Response:
    def __init__(self, payload, *, status=200):
        self.body = json.dumps(payload).encode("utf-8")
        self.status = status
        self.closed = False

    def read(self, _limit=-1):
        return self.body

    def close(self):
        self.closed = True


def client(monkeypatch, response):
    settings = load_settings({"HERMES_CREDENTIAL_REF": "ref://test"})
    calls = []

    def open_url(request, timeout):
        calls.append((request.full_url, request.data))
        return response

    monkeypatch.setattr("allies_runtime.hermes.urlopen", open_url)
    return HermesClient(settings, lambda _reference: "test-only-key"), calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload_factory",
    [
        lambda identity: {"hermes_instance_id": identity, "profile_quiescence_v1": True},
        lambda identity: {
            "runtime": {"hermes_instance_id": identity},
            "features": {"profile_quiescence_v1": True},
        },
        lambda identity: {
            "hermes_instance_id": identity,
            "features": {"profile_quiescence_v1": True},
        },
    ],
)
async def test_hermes_instance_id_accepts_only_advertised_capability(monkeypatch, payload_factory):
    identity = str(uuid4())
    response = Response(payload_factory(identity))
    client_instance, _calls = client(monkeypatch, response)
    assert await client_instance.hermes_instance_id() == identity
    assert response.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"hermes_instance_id": str(uuid4())},
        {"hermes_instance_id": str(uuid4()).upper(), "profile_quiescence_v1": True},
        {"hermes_instance_id": "not-a-uuid", "profile_quiescence_v1": True},
    ],
)
async def test_hermes_instance_id_rejects_missing_or_noncanonical_identity(monkeypatch, payload):
    response = Response(payload)
    client_instance, _calls = client(monkeypatch, response)
    with pytest.raises(HermesMalformedResponse):
        await client_instance.hermes_instance_id()
    assert response.closed is True


def quiescence_payload(
    *,
    operation_id,
    attempt_id,
    lifecycle_epoch,
    request_digest,
    machine_generation,
    runtime_start_epoch,
    hermes_instance_id,
    state="quiesced",
    **counters,
):
    return {
        "version": 1,
        "profile_key": PROFILE_KEY,
        "operation_id": operation_id,
        "attempt_id": attempt_id,
        "lifecycle_epoch": lifecycle_epoch,
        "request_digest": request_digest,
        "machine_generation": machine_generation,
        "runtime_start_epoch": runtime_start_epoch,
        "hermes_instance_id": hermes_instance_id,
        "state": state,
        "safe_error_code": "",
        "active_runs": counters.get("active_runs", 0),
        "active_profile_io": counters.get("active_profile_io", 0),
        "open_profile_stores": counters.get("open_profile_stores", 0),
        "owned_children": counters.get("owned_children", 0),
    }


def q_args(identity):
    return {
        "operation_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "lifecycle_epoch": 7,
        "request_digest": "b" * 64,
        "machine_generation": 3,
        "runtime_start_epoch": 12,
        "hermes_instance_id": identity,
    }


@pytest.mark.asyncio
async def test_hermes_quiesce_posts_bound_identity_and_accepts_completed_proof(monkeypatch):
    identity = str(uuid4())
    args = q_args(identity)
    response = Response(quiescence_payload(**args))
    client_instance, calls = client(monkeypatch, response)
    proof = await client_instance.quiesce_profile(PROFILE_KEY, **args)
    assert proof.complete is True
    assert calls[0][0].endswith(f"/v1/profiles/{PROFILE_KEY}/quiesce")
    assert json.loads(calls[0][1]) == {"version": 1, **args}
    assert response.closed is True


@pytest.mark.asyncio
async def test_hermes_quiesce_accepts_in_progress_response_and_resolves_identity(monkeypatch):
    identity = str(uuid4())
    args = q_args(identity)
    response = Response(quiescence_payload(**args, state="quiescing"), status=202)
    client_instance, _calls = client(monkeypatch, response)

    async def read_identity():
        return identity

    client_instance.hermes_instance_id = read_identity
    args.pop("hermes_instance_id")
    proof = await client_instance.quiesce_profile(PROFILE_KEY, **args)
    assert proof.state == "quiescing"
    assert response.closed is True


@pytest.mark.asyncio
async def test_hermes_quiesce_fails_closed_for_stale_or_malformed_responses(monkeypatch):
    identity = str(uuid4())
    args = q_args(identity)
    response = Response({}, status=409)
    client_instance, _calls = client(monkeypatch, response)
    with pytest.raises(HermesError):
        await client_instance.quiesce_profile(PROFILE_KEY, **args)

    malformed = Response(quiescence_payload(**args, state="quiesced", active_runs=1))
    client_instance, _calls = client(monkeypatch, malformed)
    with pytest.raises(HermesMalformedResponse):
        await client_instance.quiesce_profile(PROFILE_KEY, **args)

    wrong_status = Response(quiescence_payload(**args, state="quiesced"), status=202)
    client_instance, _calls = client(monkeypatch, wrong_status)
    with pytest.raises(HermesMalformedResponse):
        await client_instance.quiesce_profile(PROFILE_KEY, **args)


@pytest.mark.asyncio
async def test_hermes_quiesce_rejects_invalid_request_before_network(monkeypatch):
    client_instance, calls = client(monkeypatch, Response({}))
    with pytest.raises(ValueError):
        await client_instance.quiesce_profile(
            PROFILE_KEY,
            operation_id="not-a-uuid",
            attempt_id=str(uuid4()),
            lifecycle_epoch=1,
            request_digest="b" * 64,
            machine_generation=1,
            runtime_start_epoch=1,
            hermes_instance_id=str(uuid4()),
        )
    assert calls == []
