from __future__ import annotations

from types import SimpleNamespace

import pytest

from allies_runtime.foundry import (
    ActivityWaitReceipt,
    FoundryClient,
    FoundryError,
    FoundryWorker,
    ServiceUnavailableError,
)


class Transport:
    def __init__(self, body):
        self.body = body
        self.calls = []

    async def request(self, method, path, *, headers, body=None):
        self.calls.append((method, path, headers, body))
        return {"status": 200, "body": self.body}


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["changed", "timeout"])
async def test_wait_client_sends_authenticated_revision_and_parses_receipt(reason):
    transport = Transport({"revision": 7, "reason": reason})
    client = FoundryClient(runtime_token="test-token", transport=transport)
    assert await client.wait_for_activity(6, 5) == ActivityWaitReceipt(7, reason)
    method, path, headers, body = transport.calls[0]
    assert (method, path) == ("POST", "/api/v1/runtime/activity-waits")
    assert headers["Authorization"] == "Bearer test-token"
    assert body == {"after_revision": 6, "wait_seconds": 5.0}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "revision,seconds",
    [
        (True, 1),
        (-1, 1),
        ("1", 1),
        (0, True),
        (0, None),
        (0, "bad"),
        (0, 0),
        (0, 6),
        (0, float("nan")),
    ],
)
async def test_invalid_wait_parameters_do_not_send_requests(revision, seconds):
    transport = Transport({})
    client = FoundryClient(runtime_token="test-token", transport=transport)
    with pytest.raises((ValueError, TypeError)):
        await client.wait_for_activity(revision, seconds)
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"revision": True, "reason": "changed"},
        {"revision": -1, "reason": "changed"},
        {"revision": "1", "reason": "changed"},
        {"revision": 1, "reason": "unknown"},
    ],
)
async def test_malformed_wait_receipts_are_explicit_errors(body):
    client = FoundryClient(runtime_token="test-token", transport=Transport(body))
    with pytest.raises(FoundryError) as error:
        await client.wait_for_activity(0, 1)
    assert error.value.code == "MALFORMED_RESPONSE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "receipt",
    [
        {"revision": 2, "reason": "changed"},
        SimpleNamespace(revision=2, reason="changed"),
    ],
)
async def test_worker_accepts_synchronous_adapter_receipts(receipt):
    foundry = SimpleNamespace(wait_for_activity=lambda *_: receipt)
    worker = FoundryWorker(foundry, object(), activity_wait_enabled=True)
    assert await worker._wait_for_activity() == ActivityWaitReceipt(2, "changed")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "receipt",
    [
        {"revision": True, "reason": "changed"},
        {"revision": -1, "reason": "changed"},
        {"revision": 0, "reason": "bad"},
        object(),
    ],
)
async def test_worker_rejects_malformed_adapter_receipts(receipt):
    foundry = SimpleNamespace(wait_for_activity=lambda *_: receipt)
    worker = FoundryWorker(foundry, object(), activity_wait_enabled=True)
    with pytest.raises(ServiceUnavailableError):
        await worker._wait_for_activity()


@pytest.mark.asyncio
async def test_worker_without_optional_adapter_keeps_polling():
    worker = FoundryWorker(object(), object(), activity_wait_enabled=True)
    assert await worker._wait_for_activity() is None
