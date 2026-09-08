from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from allies_runtime.config import load_settings
from allies_runtime.errors import HermesMalformedResponse
from allies_runtime.hermes import HermesClient

APPROVAL_ID = "36e2968e-a8be-4a11-9eae-7a07495ebbf2"


def receipt(**changes):
    return {
        "profile_id": "ally-a",
        "session_id": "session-a",
        "run_id": "run-a",
        "hermes_approval_id": APPROVAL_ID,
        "status": "resolved",
        "outcome": "approved",
        **changes,
    }


class Response:
    status = 200

    def __init__(self, payload):
        self.body = json.dumps(payload).encode()
        self.closed = False

    def read(self, _limit):
        return self.body

    def close(self):
        self.closed = True


def client_for(monkeypatch, response):
    calls = []

    def open_url(request, timeout):
        calls.append(request)
        return response

    monkeypatch.setattr("allies_runtime.hermes.urlopen", open_url)
    return HermesClient(
        load_settings({"HERMES_CREDENTIAL_REF": "ref://test"}),
        lambda _ref: "test-bootstrap-key",
        profile_credential_resolver=lambda _profile: "test-profile-key",
    ), calls


async def resolve(client):
    deadline = (datetime.now(UTC) + timedelta(seconds=20)).isoformat()
    return await client.resolve_approval(
        "ally-a",
        "session-a",
        "run-a",
        APPROVAL_ID,
        "approve",
        session_key="memory-a",
        deadline_at=deadline,
    )


@pytest.mark.asyncio
async def test_decision_uses_profile_credential_and_exact_deadline(monkeypatch):
    response = Response(receipt(status="accepted"))
    client, calls = client_for(monkeypatch, response)
    await resolve(client)
    assert len(calls) == 1
    request = calls[0]
    assert request.full_url.endswith("/p/ally-a/api/sessions/session-a/approval")
    assert request.get_header("Authorization") == "Bearer test-profile-key"
    assert request.get_header("X-hermes-session-key") == "memory-a"
    body = json.loads(request.data)
    assert set(body) == {"run_id", "hermes_approval_id", "decision", "deadline_at"}
    assert body["run_id"] == "run-a"
    assert body["hermes_approval_id"] == APPROVAL_ID
    assert body["decision"] == "approve"
    assert datetime.now(UTC) < datetime.fromisoformat(body["deadline_at"])
    assert response.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field", ["profile_id", "session_id", "run_id", "hermes_approval_id"]
)
@pytest.mark.parametrize("method", ["resolve", "status"])
async def test_approval_receipt_rejects_other_identity(monkeypatch, field, method):
    response = Response(receipt(**{field: "other"}))
    client, _calls = client_for(monkeypatch, response)
    with pytest.raises(HermesMalformedResponse):
        if method == "resolve":
            await resolve(client)
        else:
            await client.approval_status(
                "ally-a",
                "session-a",
                "run-a",
                APPROVAL_ID,
                session_key="memory-a",
            )
    assert response.closed


@pytest.mark.asyncio
async def test_decision_rejects_receipt_for_opposite_choice(monkeypatch):
    client, _calls = client_for(monkeypatch, Response(receipt(outcome="rejected")))
    with pytest.raises(HermesMalformedResponse):
        await resolve(client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "deadline", ["not-a-date", "2099-01-01T00:00:00", "2000-01-01T00:00:00Z", 42]
)
async def test_invalid_consent_deadline_never_sends_a_request(monkeypatch, deadline):
    client, calls = client_for(monkeypatch, Response(receipt()))
    with pytest.raises((ValueError, TypeError)):
        await client.resolve_approval(
            "ally-a",
            "session-a",
            "run-a",
            APPROVAL_ID,
            "approve",
            session_key="memory-a",
            deadline_at=deadline,
        )
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,outcome,valid",
    [
        ("unknown", None, False),
        ("pending", "approved", False),
        ("resolved", None, False),
        ("expired", "approved", False),
        ("cancelled", "rejected", False),
        ("pending", None, True),
        ("expired", "expired", True),
        ("cancelled", "cancelled", True),
    ],
)
async def test_status_reconciliation_requires_consistent_terminal_truth(
    monkeypatch, status, outcome, valid
):
    response = Response(receipt(status=status, outcome=outcome))
    client, _calls = client_for(monkeypatch, response)
    request = client.approval_status(
        "ally-a", "session-a", "run-a", APPROVAL_ID, session_key="memory-a"
    )
    if valid:
        assert (await request)["outcome"] == outcome
    else:
        with pytest.raises(HermesMalformedResponse):
            await request
    assert response.closed


@pytest.mark.asyncio
async def test_slow_approval_body_does_not_block_lease_renewal_loop(monkeypatch):
    started, release = Event(), Event()

    class SlowResponse(Response):
        def read(self, limit):
            started.set()
            assert release.wait(1), "response body blocked the event loop"
            return super().read(limit)

    response = SlowResponse(receipt())
    client, _calls = client_for(monkeypatch, response)
    task = asyncio.create_task(resolve(client))
    try:
        assert await asyncio.to_thread(started.wait, 0.5)
        release.set()
        assert (await task)["outcome"] == "approved"
        assert response.closed
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
