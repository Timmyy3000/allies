from __future__ import annotations

import asyncio
import urllib.error
from collections import deque
from uuid import UUID

import pytest

from allies_runtime import foundry as foundry_module
from allies_runtime.errors import HermesError
from allies_runtime.fake import FakeFoundryTransport, FakeHermesClient, FakeProfilePlan
from allies_runtime.foundry import (
    FencedError,
    FoundryClient,
    FoundryWorker,
    IdempotencyConflictError,
    InvalidCredentialError,
    InvalidRequestError,
    LeaseConflictError,
    NotReadyError,
    RateLimitedError,
    ResponseLossError,
    ServiceUnavailableError,
    deterministic_event_id,
)
from allies_runtime.hermes import CancellableHermesStream, HermesEvent

CLAIM = {
    "attempt_id": "attempt-1",
    "execution_id": "execution-1",
    "profile_id": "profile-1",
    "hermes_profile_key": "ally-a",
    "conversation_id": "cloud-1",
    "session_id": "session-1",
    "stream_id": "stream-1",
    "lease_id": "lease-1",
    "lease_token": "lease-secret",
    "expires_at": "2026-08-09T12:00:00Z",
    "payload": {"message": "hello"},
    "claim_id": "claim-1",
}


class QueueTransport:
    def __init__(self, *responses):
        self.responses = deque(responses)
        self.calls = []

    async def request(self, method, path, *, headers, body=None):
        self.calls.append((method, path, dict(headers), body))
        value = self.responses.popleft()
        if isinstance(value, BaseException):
            raise value
        return value


def client(*responses):
    transport = QueueTransport(*responses)
    return FoundryClient(runtime_token="runtime-secret", transport=transport), transport


@pytest.mark.asyncio
async def test_fake_foundry_transport_records_headers_and_queue():
    transport = FakeFoundryTransport([{"status": 204}])
    result = await transport.request(
        "POST",
        "/api/v1/runtime/claims",
        headers={"Authorization": "Bearer x"},
        body={"claim_id": "c"},
    )
    assert result["status"] == 204
    transport.enqueue(None)
    assert await transport.request("POST", "/idle", headers={}) is None
    assert transport.calls[0][2]["Authorization"] == "Bearer x"
    empty = FakeFoundryTransport()
    assert await empty.request("GET", "/idle", headers={}) is None
    empty.enqueue(ValueError("transport failure"))
    with pytest.raises(ValueError):
        await empty.request("GET", "/idle", headers={})


@pytest.mark.asyncio
async def test_client_sends_two_headers_and_parses_contract():
    foundry, transport = client(
        CLAIM,
        {
            "status": 200,
            "body": {"lease_id": "lease-1", "expires_at": "2026-08-09T12:01:00Z"},
        },
    )
    claim = await foundry.claim(2, claim_id="claim-1")
    await foundry.renew(claim.attempt_id, claim.lease_token)
    assert claim.message == "hello"
    assert transport.calls[0][2] == {
        "Accept": "application/json",
        "Authorization": "Bearer runtime-secret",
    }
    assert transport.calls[1][2]["Authorization"] == "Bearer runtime-secret"
    assert transport.calls[1][2]["X-Foundry-Lease-Token"] == "lease-secret"
    assert transport.calls[0][3] == {"claim_id": "claim-1", "available_slots": 2}
    assert "lease-secret" not in repr(claim)


@pytest.mark.asyncio
async def test_client_mutation_shapes_and_deterministic_event_ids():
    foundry, transport = client(
        {"status": 202, "body": {"event_id": "event-1", "sequence": 1}},
        {"session_id": "session-2"},
        {"attempt_id": "attempt-1", "state": "released", "requeued": True},
        {
            "attempt_id": "attempt-1",
            "status": "succeeded",
            "receipt_id": "receipt-1",
            "receipt": {"code": "ok"},
        },
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt-2",
            "requeued": True,
            "receipt": {"retryable": True},
        },
    )
    event = await foundry.event(
        "attempt-1",
        "lease-secret",
        stream_id="stream-1",
        sequence=1,
        event_type="delta",
        payload={"text": "x"},
    )
    assert event.event_id == "event-1"
    await foundry.bind(
        "attempt-1",
        "lease-secret",
        cloud_conversation_ref="cloud-1",
        expected_session_id="session-1",
        effective_session_id="session-2",
    )
    stopped = await foundry.stopped("attempt-1", "lease-secret", reason="lease_lost")
    complete = await foundry.complete(
        "attempt-1",
        "lease-secret",
        stream_id="stream-1",
        sequence=2,
        payload={"run_id": "run-1", "status": "completed"},
        receipt={"code": "ok"},
    )
    failed = await foundry.fail(
        "attempt-1",
        "lease-secret",
        stream_id="stream-1",
        sequence=2,
        payload={"code": "timeout", "retryable": False},
        code="timeout",
        retryable=False,
        receipt={"code": "timeout"},
    )
    assert stopped.requeued and complete.status == "succeeded" and failed.requeued
    assert UUID(deterministic_event_id("attempt-1", "stream-1", 1))
    assert deterministic_event_id("attempt-1", "stream-1", 1) == deterministic_event_id(
        "attempt-1", "stream-1", 1
    )
    assert deterministic_event_id("attempt-1", "stream-1", 1) != deterministic_event_id(
        "attempt-1", "stream-1", 2
    )
    assert transport.calls[0][3]["event_id"] == deterministic_event_id(
        "attempt-1", "stream-1", 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, "INVALID_CREDENTIAL", InvalidCredentialError),
        (409, "FENCED", FencedError),
        (409, "NOT_READY", NotReadyError),
        (409, "LEASE_CONFLICT", LeaseConflictError),
        (409, "IDEMPOTENCY_CONFLICT", IdempotencyConflictError),
        (422, "INVALID_REQUEST", InvalidRequestError),
        (429, "RATE_LIMITED", RateLimitedError),
        (503, "SERVICE_UNAVAILABLE", ServiceUnavailableError),
    ],
)
async def test_client_maps_typed_status_errors(status, code, expected):
    foundry, _ = client({"status": status, "body": {"code": code}})
    with pytest.raises(expected) as error:
        await foundry.claim(2, claim_id="claim-1")
    assert error.value.status == status
    assert code == error.value.code


@pytest.mark.asyncio
async def test_client_rejects_response_loss_and_bounds_slots():
    foundry, _ = client(TimeoutError())
    with pytest.raises(ResponseLossError):
        await foundry.claim(2, claim_id="claim-1")
    with pytest.raises(ValueError):
        await foundry.claim(9)
    with pytest.raises(ValueError):
        deterministic_event_id("attempt", "stream", 0)


@pytest.mark.asyncio
async def test_worker_overlaps_profiles_and_completes_incremental_events():
    responses = [
        {
            "status": 200,
            "body": {
                **CLAIM,
                "attempt_id": "attempt-a",
                "profile_id": "profile-a",
                "hermes_profile_key": "ally-a",
                "stream_id": "stream-a",
                "claim_id": "claim-a",
            },
        },
        {
            "status": 200,
            "body": {
                **CLAIM,
                "attempt_id": "attempt-b",
                "profile_id": "profile-b",
                "hermes_profile_key": "ally-b",
                "stream_id": "stream-b",
                "claim_id": "claim-b",
            },
        },
    ]
    # The worker's event/terminal calls can be answered by a generic mapping.
    responses.extend(
        [{"status": 202, "body": {"event_id": "event", "sequence": 1}}] * 4
    )
    responses.extend([{"session_id": "session-1"}] * 2)
    responses.extend(
        [
            {
                "attempt_id": "attempt-a",
                "status": "succeeded",
                "receipt_id": "receipt-a",
            },
            {
                "attempt_id": "attempt-b",
                "status": "succeeded",
                "receipt_id": "receipt-b",
            },
        ]
    )
    foundry, transport = client(*responses)
    hermes = FakeHermesClient(
        {
            "ally-a": FakeProfilePlan(event_delay=0.001),
            "ally-b": FakeProfilePlan(event_delay=0.001),
        }
    )
    worker = FoundryWorker(foundry, hermes, slots=2, renew_interval=0.1)
    results = await worker.run(max_turns=2)
    assert len(results) == 2
    assert hermes.max_active_streams == 2
    assert all(
        "X-Foundry-Lease-Token" in call[2]
        for call in transport.calls
        if "/events" in call[1] or "/complete" in call[1]
    )


@pytest.mark.asyncio
async def test_worker_renewal_loss_closes_stream_and_stops_before_completion():
    claim = {**CLAIM, "hermes_profile_key": "ally-a"}
    foundry, transport = client(
        claim,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 409, "body": {"code": "LEASE_CONFLICT"}},
        {"attempt_id": "attempt-1", "state": "released", "requeued": True},
    )
    hermes = FakeHermesClient({"ally-a": FakeProfilePlan(event_delay=0.05)})
    worker = FoundryWorker(foundry, hermes, slots=2, renew_interval=0.01)
    result = await worker.run(max_turns=1)
    assert result[0].state == "released"
    assert hermes.cancelled_streams >= 1
    assert not any("/complete" in call[1] for call in transport.calls)


@pytest.mark.asyncio
async def test_worker_failure_is_reported_and_bad_identity_does_not_write_late_events():
    claim = {**CLAIM, "hermes_profile_key": "ally-a"}
    foundry, transport = client(
        claim,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt-1",
            "requeued": False,
        },
    )
    hermes = FakeHermesClient({"ally-a": FakeProfilePlan(failure="disconnect")})
    worker = FoundryWorker(foundry, hermes, slots=2, renew_interval=0.1)
    result = await worker.run(max_turns=1)
    assert result[0].status == "failed"
    assert [call[3]["type"] for call in transport.calls if "/events" in call[1]] == [
        "execution.dispatched"
    ]


@pytest.mark.asyncio
async def test_worker_reserves_ambiguous_claim_slot_for_replay():
    retry_claim = {**CLAIM, "claim_id": "claim-replay"}
    foundry, _ = client(
        ResponseLossError("lost"),
        retry_claim,
        {"attempt_id": "attempt-1", "status": "succeeded", "receipt_id": "receipt-1"},
        *([{"status": 202, "body": {"event_id": "event", "sequence": 1}}] * 3),
    )
    hermes = FakeHermesClient({"ally-a": FakeProfilePlan(event_delay=0)})
    worker = FoundryWorker(foundry, hermes, slots=2, renew_interval=0.1)
    # One retry cycle is enough to prove the same claim ID is sent again.
    task = asyncio.create_task(worker.run(max_turns=1, idle_cycles=2, idle_delay=0))
    await asyncio.sleep(0.01)
    assert worker.ambiguous_claim_ids or task.done()
    result = await task
    assert result


@pytest.mark.asyncio
async def test_ambiguous_claim_reservation_expires_and_allows_fresh_claim_id():
    clock = [0.0]
    claim = {**CLAIM, "hermes_profile_key": "ally-a"}

    class ExpiringTransport(QueueTransport):
        def __init__(self):
            super().__init__()
            self.claim_calls = []

        async def request(self, method, path, *, headers, body=None):
            if path.endswith("/claims"):
                self.claim_calls.append(body["claim_id"])
                if len(self.claim_calls) <= 2:
                    if len(self.claim_calls) == 2:
                        clock[0] = 61.0
                    raise ResponseLossError("claim response lost")
                return claim
            if "/events" in path:
                return {
                    "status": 202,
                    "body": {"event_id": "event", "sequence": body["sequence"]},
                }
            if "/complete" in path:
                return {
                    "attempt_id": "attempt-1",
                    "status": "succeeded",
                    "receipt_id": "receipt-1",
                }
            if "/session-binding" in path:
                return {"session_id": body["effective_session_id"]}
            return None

    transport = ExpiringTransport()
    foundry = FoundryClient(runtime_token="runtime-secret", transport=transport)
    worker = FoundryWorker(
        foundry,
        FakeHermesClient({"ally-a": FakeProfilePlan(event_delay=0)}),
        renew_interval=0.1,
        clock=lambda: clock[0],
    )
    result = await worker.run(max_turns=1)
    assert result[0].status == "succeeded"
    assert transport.claim_calls[0] == transport.claim_calls[1]
    assert transport.claim_calls[2] != transport.claim_calls[0]


@pytest.mark.asyncio
async def test_worker_replays_event_after_response_loss_with_same_event_id():
    claim = {**CLAIM, "hermes_profile_key": "ally-a"}
    responses = [
        claim,
        ResponseLossError("event response lost"),
        {"status": 202, "body": {"event_id": "event-1", "sequence": 1}},
    ]
    responses.append({"status": 202, "body": {"event_id": "event-2", "sequence": 2}})
    responses.append({"session_id": "session-1"})
    responses.append(
        {"attempt_id": "attempt-1", "status": "succeeded", "receipt_id": "receipt-1"}
    )
    foundry, transport = client(*responses)
    worker = FoundryWorker(
        foundry,
        FakeHermesClient({"ally-a": FakeProfilePlan(event_delay=0)}),
        renew_interval=0.1,
    )
    result = await worker.run(max_turns=1)
    event_calls = [call for call in transport.calls if "/events" in call[1]]
    assert result[0].status == "succeeded"
    assert len(event_calls) == 3
    assert event_calls[0][3]["event_id"] == event_calls[1][3]["event_id"]


@pytest.mark.asyncio
async def test_worker_second_event_response_loss_stops_without_fail():
    claim = {**CLAIM, "hermes_profile_key": "ally-a"}
    foundry, transport = client(
        claim,
        ResponseLossError("event response lost"),
        ResponseLossError("event response lost"),
        {"attempt_id": "attempt-1", "state": "released", "requeued": True},
    )
    worker = FoundryWorker(
        foundry,
        FakeHermesClient({"ally-a": FakeProfilePlan(event_delay=0)}),
        renew_interval=0.1,
    )
    result = await worker.run(max_turns=1)
    assert result[0].state == "released"
    assert not any("/fail" in call[1] for call in transport.calls)


@pytest.mark.asyncio
async def test_worker_replays_complete_after_response_loss_without_conflicting_fail():
    claim = {**CLAIM, "hermes_profile_key": "ally-a"}
    responses = [claim]
    responses.extend(
        [
            {"status": 202, "body": {"event_id": f"event-{i}", "sequence": i}}
            for i in (1, 2)
        ]
    )
    responses.append({"session_id": "session-1"})
    responses.extend(
        [
            ResponseLossError("complete response lost"),
            {
                "attempt_id": "attempt-1",
                "status": "succeeded",
                "receipt_id": "receipt-1",
            },
        ]
    )
    foundry, transport = client(*responses)
    worker = FoundryWorker(
        foundry,
        FakeHermesClient({"ally-a": FakeProfilePlan(event_delay=0)}),
        renew_interval=0.1,
    )
    result = await worker.run(max_turns=1)
    assert result[0].status == "succeeded"
    assert not any("/fail" in call[1] for call in transport.calls)
    assert len([call for call in transport.calls if "/complete" in call[1]]) == 2


@pytest.mark.asyncio
async def test_worker_second_complete_response_loss_stops_without_fail():
    claim = {**CLAIM, "hermes_profile_key": "ally-a"}
    responses = [claim]
    responses.extend(
        [
            {"status": 202, "body": {"event_id": f"event-{i}", "sequence": i}}
            for i in (1, 2)
        ]
    )
    responses.append({"session_id": "session-1"})
    responses.extend(
        [
            ResponseLossError("complete response lost"),
            ResponseLossError("complete response lost"),
            {"attempt_id": "attempt-1", "state": "released", "requeued": True},
        ]
    )
    foundry, transport = client(*responses)
    worker = FoundryWorker(
        foundry,
        FakeHermesClient({"ally-a": FakeProfilePlan(event_delay=0)}),
        renew_interval=0.1,
    )
    result = await worker.run(max_turns=1)
    assert result[0].state == "released"
    assert not any("/fail" in call[1] for call in transport.calls)


@pytest.mark.asyncio
async def test_worker_second_fail_response_loss_stops_without_conflicting_retry():
    claim = {**CLAIM, "hermes_profile_key": "ally-a"}
    foundry, transport = client(
        claim,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        ResponseLossError("fail response lost"),
        ResponseLossError("fail response lost"),
        {"attempt_id": "attempt-1", "state": "released", "requeued": True},
    )
    worker = FoundryWorker(
        foundry,
        FakeHermesClient({"ally-a": FakeProfilePlan(failure="disconnect")}),
        renew_interval=0.1,
    )
    result = await worker.run(max_turns=1)
    assert result[0].state == "released"
    assert len([call for call in transport.calls if "/fail" in call[1]]) == 2


@pytest.mark.asyncio
async def test_worker_cancelled_stream_acknowledges_stopped():
    claim = {**CLAIM, "hermes_profile_key": "ally-a"}
    foundry, _ = client(
        claim,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"attempt_id": "attempt-1", "state": "released", "requeued": False},
    )
    worker = FoundryWorker(
        foundry,
        FakeHermesClient({"ally-a": FakeProfilePlan(event_delay=1)}),
        renew_interval=0.1,
    )
    worker_claim = await foundry.claim(2, claim_id="claim-cancel")
    task = asyncio.create_task(worker.run_claim(worker_claim))
    await asyncio.sleep(0)
    task.cancel()
    result = await task
    assert result.state == "released"


@pytest.mark.asyncio
async def test_worker_stop_cancels_stalled_stream_and_acknowledges_stopped():
    claim = {**CLAIM, "hermes_profile_key": "ally-a"}
    foundry, transport = client(
        claim,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"attempt_id": "attempt-1", "state": "released", "requeued": False},
    )
    hermes = FakeHermesClient({"ally-a": FakeProfilePlan(event_delay=1)})
    worker = FoundryWorker(foundry, hermes, renew_interval=0.1)
    worker_claim = await foundry.claim(2, claim_id="claim-stop")
    task = asyncio.create_task(worker.run_claim(worker_claim))
    worker._active.add(task)
    await asyncio.sleep(0.01)
    await worker.stop()
    assert task.done()
    assert any("/stopped" in call[1] for call in transport.calls)


@pytest.mark.asyncio
async def test_worker_closes_hermes_before_retryable_fail():
    claim = {**CLAIM, "hermes_profile_key": "ally-a"}
    hermes = FakeHermesClient({"ally-a": FakeProfilePlan(cross_profile="ally-b")})

    class CheckingTransport(QueueTransport):
        async def request(self, method, path, *, headers, body=None):
            if "/fail" in path:
                assert hermes.active_streams == 0
            return await super().request(method, path, headers=headers, body=body)

    transport = CheckingTransport(
        claim,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt-1",
            "requeued": False,
        },
    )
    foundry = FoundryClient(runtime_token="runtime-secret", transport=transport)
    worker = FoundryWorker(foundry, hermes, renew_interval=0.1)
    result = await worker.run(max_turns=1)
    assert result[0].status == "failed"


@pytest.mark.asyncio
async def test_worker_empty_hermes_stream_fails_as_malformed():
    class EmptyHermes:
        async def stream_profile_incremental(self, *_args, **_kwargs):
            async def empty():
                if False:
                    yield None

            from allies_runtime.hermes import CancellableHermesStream

            return CancellableHermesStream(empty())

    claim = {**CLAIM, "hermes_profile_key": "ally-a"}
    foundry, transport = client(
        claim,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt-1",
            "requeued": False,
        },
    )
    worker = FoundryWorker(foundry, EmptyHermes(), renew_interval=0.1)
    result = await worker.run(max_turns=1)
    assert result[0].status == "failed"
    assert any(
        "/fail" in call[1] and call[3]["code"] == "malformed_response"
        for call in transport.calls
    )


def test_fake_stream_type_is_an_async_iterator():
    stream = asyncio.run(
        FakeHermesClient().stream_profile_incremental(
            "ally-a", "s", "m", session_key="stable"
        )
    )
    assert hasattr(stream, "__aiter__") and hasattr(stream, "aclose")


def test_transport_and_response_normalizers_cover_http_and_fake_shapes(monkeypatch):
    class Response:
        status = 200
        body = b'{"ok": true}'

    assert foundry_module._parse_response(None) == (204, None)
    assert foundry_module._parse_response((201, {"ok": True})) == (201, {"ok": True})
    assert foundry_module._parse_response(Response()) == (200, {"ok": True})
    with pytest.raises(InvalidRequestError):
        foundry_module._parse_response(
            type("Bad", (), {"status": 200, "body": b"nope"})()
        )
    assert foundry_module._parse_datetime("not-a-date") == "not-a-date"

    class HttpResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _limit):
            return b'{"ok": true}'

    monkeypatch.setattr(
        foundry_module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: HttpResponse(),
    )
    transport = foundry_module.UrllibFoundryTransport("http://foundry.test")
    result = asyncio.run(
        transport.request("GET", "/health", headers={"Accept": "application/json"})
    )
    assert result["status"] == 200
    error = urllib.error.HTTPError("http://foundry.test/health", 503, "busy", {}, None)
    monkeypatch.setattr(
        foundry_module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )
    unavailable = asyncio.run(
        transport.request("GET", "/health", headers={"Accept": "application/json"})
    )
    assert unavailable["status"] == 503
    with pytest.raises(ValueError):
        foundry_module.UrllibFoundryTransport("ftp://bad")
    with pytest.raises(ValueError):
        foundry_module.UrllibFoundryTransport("http://bad", timeout=0)


@pytest.mark.asyncio
async def test_client_supports_legacy_transport_and_empty_claim():
    class Legacy:
        def __init__(self):
            self.calls = []

        def __call__(self, method, path, headers, body):
            self.calls.append((method, path, headers, body))

    legacy = Legacy()
    foundry = FoundryClient(runtime_token="token", transport=legacy)
    assert await foundry.claim(2, claim_id="claim") is None
    assert legacy.calls[0][0] == "POST"
    with pytest.raises(ValueError):
        FoundryClient(runtime_token="bad\nvalue", transport=legacy)
    with pytest.raises(ValueError):
        await foundry.event(
            "attempt",
            "bad\nlease",
            stream_id="stream",
            sequence=1,
            event_type="x",
            payload={},
        )


@pytest.mark.asyncio
async def test_client_rejects_malformed_success_responses():
    cases = [
        ("renew", {"ok": True}),
        ("event", {"ok": True}),
        ("bind", {"ok": True}),
        ("stopped", {"ok": True}),
        ("complete", {"ok": True}),
    ]
    for method, response in cases:
        foundry, _ = client(response)
        with pytest.raises((HermesError, ValueError, foundry_module.FoundryError)):
            if method == "renew":
                await foundry.renew("attempt", "lease")
            elif method == "event":
                await foundry.event(
                    "attempt",
                    "lease",
                    stream_id="stream",
                    sequence=1,
                    event_type="x",
                    payload={},
                )
            elif method == "bind":
                await foundry.bind(
                    "attempt",
                    "lease",
                    cloud_conversation_ref="cloud",
                    expected_session_id=None,
                    effective_session_id="session",
                )
            elif method == "stopped":
                await foundry.stopped("attempt", "lease", reason="x")
            else:
                await foundry.complete(
                    "attempt",
                    "lease",
                    stream_id="stream",
                    sequence=1,
                    payload={"run_id": "run", "status": "completed"},
                    receipt={},
                )


@pytest.mark.asyncio
async def test_foundry_internal_fallback_and_malformed_claim_paths():
    foundry, _ = client({"ok": True})
    with pytest.raises(foundry_module.FoundryError):
        await foundry.claim(2, claim_id="claim")
    await foundry_module._close_stream(object())

    class JsonTransport:
        def request(self, method, path, *, headers, json):
            return {"status": 204}

    foundry = FoundryClient(runtime_token="token", transport=JsonTransport())
    assert await foundry.claim(2, claim_id="claim") is None


@pytest.mark.asyncio
async def test_response_loss_retry_accepts_sync_transport_result():
    assert await foundry_module._retry_response_loss(lambda: {"ok": True}) == {
        "ok": True
    }


@pytest.mark.asyncio
async def test_worker_validation_stop_and_fenced_claim():
    foundry, _ = client({"status": 409, "body": {"code": "FENCED"}})
    with pytest.raises(ValueError):
        FoundryWorker(foundry, FakeHermesClient(), slots=1)
    with pytest.raises(ValueError):
        FoundryWorker(foundry, FakeHermesClient(), renew_interval=60)
    worker = FoundryWorker(foundry, FakeHermesClient())
    await worker.stop()
    assert await worker.run() == ()


@pytest.mark.asyncio
async def test_worker_run_contains_an_externally_cancelled_slot():
    foundry, _ = client(None)
    worker = FoundryWorker(foundry, FakeHermesClient())
    task = asyncio.create_task(asyncio.sleep(1))
    worker._active.add(task)
    task.cancel()
    await asyncio.sleep(0)
    assert await worker.run(max_turns=1) == (None,)


@pytest.mark.asyncio
async def test_worker_uses_non_incremental_hermes_fallback_and_handles_cancelled_task():
    class LegacyHermes(FakeHermesClient):
        stream_profile_incremental = None

    foundry, _ = client(
        CLAIM,
        *([{"status": 202, "body": {"event_id": "event", "sequence": 1}}] * 2),
        {"session_id": "session-1"},
        {"attempt_id": "attempt-1", "status": "succeeded", "receipt_id": "receipt"},
    )
    worker = FoundryWorker(foundry, LegacyHermes(), slots=2, renew_interval=0.1)
    assert (await worker.run(max_turns=1))[0].status == "succeeded"


@pytest.mark.asyncio
async def test_worker_identity_and_fenced_event_paths_stop_or_fail_safely():
    claim = {**CLAIM, "hermes_profile_key": "ally-a"}
    foundry, _ = client(
        claim,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt",
            "requeued": False,
        },
    )
    worker = FoundryWorker(
        foundry,
        FakeHermesClient({"ally-a": FakeProfilePlan(cross_profile="ally-b")}),
        renew_interval=0.1,
    )
    assert (await worker.run(max_turns=1))[0].status == "failed"

    foundry, _ = client(
        claim,
        {"status": 409, "body": {"code": "FENCED"}},
        {"attempt_id": "attempt-1", "state": "released", "requeued": True},
    )
    worker = FoundryWorker(foundry, FakeHermesClient(), renew_interval=0.1)
    # A stale event write must trigger stopped, never a terminal write.
    assert (await worker.run(max_turns=1))[0].state == "released"


@pytest.mark.asyncio
async def test_worker_claim_retryable_status_and_stop_active_slot():
    foundry, _ = client({"status": 429, "body": {"code": "RATE_LIMITED"}}, None, None)
    worker = FoundryWorker(foundry, FakeHermesClient(), renew_interval=0.1)
    assert await worker.run(max_turns=1, idle_cycles=2) == ()
    active = asyncio.create_task(asyncio.sleep(0))
    worker._active.add(active)
    await worker.stop()
    assert worker.active_count == 0


@pytest.mark.asyncio
async def test_cancellable_stream_handles_closed_and_running_generators():
    closed = CancellableHermesStream(iter(()))
    await closed.aclose()
    with pytest.raises(StopAsyncIteration):
        await closed.__anext__()
    await closed.aclose()

    async def slow():
        await asyncio.sleep(1)
        yield HermesEvent("x", "ally-a", "s", "r", 1, {})

    calls = []
    stream = CancellableHermesStream(slow(), lambda: calls.append("closed"))
    task = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)
    await stream.aclose()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert calls == ["closed"]
