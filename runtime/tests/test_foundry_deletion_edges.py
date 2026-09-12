from __future__ import annotations

from uuid import uuid4

import pytest

from allies_runtime.foundry import FoundryClient, FoundryError


class QueueTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def request(self, method, path, *, headers, body=None):
        self.calls.append((method, path, dict(headers), body))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def desired_profile(**changes):
    value = {
        "profile_id": str(uuid4()),
        "ally_ref": "ally-a",
        "hermes_profile_key": "ally-v1-00000000000000000000000000000001",
        "hermes_profile_key_version": 1,
        "lifecycle_state": "cleanup_pending",
        "lifecycle_epoch": 4,
        "seed_version": 1,
        "seed_fingerprint": "a" * 64,
        "materialized_generation": 3,
        "seed": {},
        "cleanup_operation_id": str(uuid4()),
        "cleanup_request_digest": "b" * 64,
        "cleanup_attempt_id": str(uuid4()),
        "cleanup_requires_quiescence": True,
        "cleanup_expires_at": "2030-01-01T00:00:00+00:00",
    }
    value.update(changes)
    return value


def receipt_payload(*, quiescence=None, **changes):
    value = {
        "profile_id": str(uuid4()),
        "lifecycle_state": "deprovisioned",
        "lifecycle_epoch": 4,
        "materialized_generation": 0,
        "seed_fingerprint": "a" * 64,
        "receipt_id": "receipt-1",
        "result_code": "deprovisioned",
        "deleted": True,
        "active_lease_count": 0,
        "attempt_id": str(uuid4()),
        "machine_generation": 3,
        "runtime_start_epoch": 12,
        "runtime_boot_id": str(uuid4()),
        "hermes_instance_id": str(uuid4()),
    }
    if quiescence is not None:
        value["quiescence"] = quiescence
    value.update(changes)
    return value


def valid_quiescence():
    return {
        "state": "quiesced",
        "safe_error_code": "",
        "active_runs": 0,
        "active_profile_io": 0,
        "open_profile_stores": 0,
        "owned_children": 0,
    }


@pytest.mark.asyncio
async def test_foundry_parses_cleanup_attempt_and_quiescence_requirement():
    payload = {
        "version": 1,
        "machine_generation": 3,
        "profiles": [desired_profile()],
    }
    transport = QueueTransport(payload)
    profiles = await FoundryClient(
        runtime_token="runtime-secret", transport=transport
    ).reconcile_profiles()
    profile = profiles[0]
    assert profile.cleanup_attempt_id is not None
    assert profile.cleanup_requires_quiescence is True
    assert profile.cleanup_expires_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"cleanup_attempt_id": 4},
        {"cleanup_requires_quiescence": "true"},
        {"seed": []},
    ],
)
async def test_foundry_rejects_malformed_deletion_desired_state(changes):
    transport = QueueTransport(
        {"version": 1, "machine_generation": 3, "profiles": [desired_profile(**changes)]}
    )
    with pytest.raises(FoundryError):
        await FoundryClient(
            runtime_token="runtime-secret", transport=transport
        ).reconcile_profiles()


@pytest.mark.asyncio
async def test_foundry_posts_and_parses_content_free_quiescence_receipt():
    response = receipt_payload(quiescence=valid_quiescence())
    transport = QueueTransport(response)
    profile_id = response["profile_id"]
    attempt_id = response["attempt_id"]
    machine_generation = response["machine_generation"]
    runtime_start_epoch = response["runtime_start_epoch"]
    runtime_boot_id = response["runtime_boot_id"]
    hermes_instance_id = response["hermes_instance_id"]
    client = FoundryClient(runtime_token="runtime-secret", transport=transport)
    receipt = await client.cleanup_receipt(
        profile_id,
        operation_id=str(uuid4()),
        lifecycle_epoch=4,
        request_digest="b" * 64,
        result_code="deprovisioned",
        deleted=True,
        active_lease_count=0,
        attempt_id=attempt_id,
        machine_generation=machine_generation,
        runtime_start_epoch=runtime_start_epoch,
        runtime_boot_id=runtime_boot_id,
        hermes_instance_id=hermes_instance_id,
        quiescence=valid_quiescence(),
    )
    assert receipt.quiescence == valid_quiescence()
    sent = transport.calls[0][3]
    assert sent["attempt_id"] == attempt_id
    assert sent["runtime_boot_id"] == runtime_boot_id
    assert sent["quiescence"] == valid_quiescence()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_quiescence",
    [
        {"state": "quiesced"},
        {**valid_quiescence(), "unexpected": 1},
        {**valid_quiescence(), "active_runs": True},
        {**valid_quiescence(), "state": "unknown"},
    ],
)
async def test_foundry_rejects_malformed_quiescence_receipts(bad_quiescence):
    response = receipt_payload(quiescence=bad_quiescence)
    transport = QueueTransport(response)
    client = FoundryClient(runtime_token="runtime-secret", transport=transport)
    with pytest.raises((FoundryError, TypeError, ValueError)):
        await client.cleanup_receipt(
            response["profile_id"],
            operation_id=str(uuid4()),
            lifecycle_epoch=4,
            request_digest="b" * 64,
            result_code="deprovisioned",
            deleted=True,
            active_lease_count=0,
            quiescence=bad_quiescence,
        )
