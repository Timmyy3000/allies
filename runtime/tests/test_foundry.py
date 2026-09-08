from __future__ import annotations

import asyncio
import urllib.error
from collections import deque
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from allies_runtime import foundry as foundry_module
from allies_runtime.errors import (
    HermesDisconnected,
    HermesError,
    HermesMalformedResponse,
    HermesTimeout,
)
from allies_runtime.fake import FakeFoundryTransport, FakeHermesClient, FakeProfilePlan
from allies_runtime.foundry import (
    ActivityWaitReceipt,
    FencedError,
    FoundryClaim,
    FoundryClient,
    FoundryError,
    FoundryWorker,
    IdempotencyConflictError,
    InvalidCredentialError,
    InvalidRequestError,
    LeaseConflictError,
    NotReadyError,
    RateLimitedError,
    ResponseLossError,
    RuntimeReconciliationSnapshot,
    ServiceUnavailableError,
    deterministic_event_id,
)
from allies_runtime.hermes import CancellableHermesStream, HermesEvent

CLAIM = {
    "attempt_id": "attempt-1",
    "execution_id": "execution-1",
    "profile_id": "profile-1",
    "hermes_profile_key": "ally-a",
    "model": "gpt-5.6-luna",
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


class ApprovalHermes:
    def __init__(
        self,
        *,
        expires_at,
        outcome,
        decision=None,
        response_id="approval-1",
        response_extra=None,
        stream_outcome=None,
        emit_second_request=False,
        terminal_while_pending=False,
    ):
        self.expires_at = expires_at
        self.outcome = outcome
        self.decision = decision
        self.response_id = response_id
        self.response_extra = response_extra or {}
        self.stream_outcome = stream_outcome or outcome
        self.emit_second_request = emit_second_request
        self.terminal_while_pending = terminal_while_pending
        self.resolutions = []

    async def stream_profile_incremental(
        self, profile_id, session_id, _message, *, session_key
    ):
        async def events():
            yield HermesEvent(
                "approval.request",
                profile_id,
                session_id,
                "run-approval",
                1,
                {
                    "hermes_approval_id": "approval-1",
                    "action_kind": "plugin_tool",
                    "action_label": "Connect Nabu",
                    "action_preview": "Connect to Nabu",
                    "expires_at": self.expires_at,
                },
            )
            response = {
                "hermes_approval_id": self.response_id,
                "outcome": self.stream_outcome,
            }
            response.update(self.response_extra)
            if self.emit_second_request:
                yield HermesEvent(
                    "approval.request",
                    profile_id,
                    session_id,
                    "run-approval",
                    2,
                    {
                        "hermes_approval_id": "approval-2",
                        "action_kind": "plugin_tool",
                        "action_label": "Connect Nabu",
                        "action_preview": "Connect to Nabu",
                        "expires_at": self.expires_at,
                    },
                )
                return
            if self.terminal_while_pending:
                yield HermesEvent(
                    "execution.completed",
                    profile_id,
                    session_id,
                    "run-approval",
                    2,
                    {"run_id": "run-approval", "status": "completed"},
                )
                return
            yield HermesEvent(
                "approval.responded",
                profile_id,
                session_id,
                "run-approval",
                2,
                response,
            )
            yield HermesEvent(
                "execution.completed",
                profile_id,
                session_id,
                "run-approval",
                3,
                {"run_id": "run-approval", "status": "completed"},
            )

        return CancellableHermesStream(events())

    async def resolve_approval(
        self,
        profile_id,
        session_id,
        run_id,
        hermes_approval_id,
        decision,
        *,
        session_key,
        deadline_at,
    ):
        self.resolutions.append(
            {
                "profile_id": profile_id,
                "session_id": session_id,
                "run_id": run_id,
                "hermes_approval_id": hermes_approval_id,
                "decision": decision,
                "session_key": session_key,
                "deadline_at": deadline_at,
            }
        )
        return {
            "status": self.outcome
            if self.outcome in {"expired", "cancelled"}
            else "accepted",
            "outcome": self.outcome,
        }


def approval_status_payload(approval_request_id, *, expires_at, status, decision):
    payload = {
        "approval_request_id": approval_request_id,
        "status": status,
        "decision": decision,
        "expires_at": expires_at,
    }
    if status == "decision_recorded":
        payload["acknowledgement_deadline_at"] = (
            datetime.now(UTC) + timedelta(seconds=30)
        ).isoformat()
    return payload


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
async def test_client_parses_optional_managed_reasoning_effort():
    foundry, _ = client({"status": 200, "body": {**CLAIM, "reasoning_effort": "xhigh"}})

    parsed = await foundry.claim(2, claim_id="claim-1")

    assert parsed.reasoning_effort == "xhigh"


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, "medium", 1, {"effort": "xhigh"}])
async def test_client_rejects_invalid_present_reasoning_effort(value):
    foundry, _ = client({"status": 200, "body": {**CLAIM, "reasoning_effort": value}})

    with pytest.raises(FoundryError, match="invalid reasoning effort"):
        await foundry.claim(2, claim_id="claim-1")


@pytest.mark.asyncio
async def test_client_reconciliation_snapshot_and_readiness_receipt():
    foundry, transport = client(
        {
            "status": 200,
            "body": {
                "version": 1,
                "machine_generation": 7,
                "runtime_start_epoch": 12,
                "workspace_id": {"unexpected": "metadata"},
                "profiles": [],
            },
        },
        {
            "status": 200,
            "body": {
                "status": "ready",
                "generation": 7,
                "runtime_start_epoch": 12,
                "accepted_at": "2026-08-25T12:00:01Z",
            },
        },
    )

    snapshot = await foundry.reconciliation_snapshot()
    receipt = await foundry.report_readiness(
        boot_id="00000000-0000-4000-8000-000000000009",
        reconciled_generation=snapshot.machine_generation,
        runtime_start_epoch=snapshot.runtime_start_epoch,
    )

    assert snapshot.runtime_start_epoch == 12
    assert snapshot.workspace_id is None
    assert receipt["status"] == "ready"
    assert transport.calls[1][3] == {
        "boot_id": "00000000-0000-4000-8000-000000000009",
        "reconciled_generation": 7,
        "runtime_start_epoch": 12,
    }
    with pytest.raises(ValueError, match="boot_id must be a UUID"):
        await foundry.report_readiness(
            boot_id="not-a-uuid",
            reconciled_generation=7,
            runtime_start_epoch=12,
        )


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
@pytest.mark.parametrize(
    ("decision", "outcome"),
    [
        ("approve", "approved"),
        ("reject", "rejected"),
        ("approve", "expired"),
        ("approve", "cancelled"),
    ],
)
async def test_worker_resolves_approval_and_continues_the_same_turn(decision, outcome):
    expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    approval_request_id = foundry_module._approval_request_id(
        "attempt-1", "run-approval", "approval-1"
    )
    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "awaiting", "sequence": 2}},
        {
            "status": 200,
            "body": approval_status_payload(
                approval_request_id,
                expires_at=expires_at,
                status="decision_recorded",
                decision=decision,
            ),
        },
        {"status": 202, "body": {"event_id": "resolved", "sequence": 3}},
        {"session_id": "session-1"},
        {
            "attempt_id": "attempt-1",
            "status": "succeeded",
            "receipt_id": "receipt-approval",
        },
    )
    hermes = ApprovalHermes(
        expires_at=expires_at,
        outcome=outcome,
        decision=decision,
    )
    worker = FoundryWorker(
        foundry,
        hermes,
        renew_interval=0.1,
        approval_poll_interval=0.01,
    )

    result = await worker.run(max_turns=1)

    assert result[0].status == "succeeded"
    assert len(hermes.resolutions) == 1
    resolution = hermes.resolutions[0]
    assert resolution["decision"] == decision
    assert resolution["run_id"] == "run-approval"
    assert resolution["hermes_approval_id"] == "approval-1"
    assert resolution["session_id"] == "session-1"
    assert resolution["session_key"].startswith("allies-k-")
    event_types = [call[3]["type"] for call in transport.calls if "/events" in call[1]]
    assert event_types == [
        "execution.dispatched",
        "execution.awaiting_action",
        "execution.approval_resolved",
    ]
    assert transport.calls[-1][1].endswith("/complete")
    resolution_events = [
        call[3]
        for call in transport.calls
        if "/events" in call[1] and call[3]["type"] == "execution.approval_resolved"
    ]
    assert resolution_events[0]["payload"]["outcome"] == outcome


@pytest.mark.asyncio
async def test_worker_records_expired_approval_without_calling_resolver():
    expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    approval_request_id = foundry_module._approval_request_id(
        "attempt-1", "run-approval", "approval-1"
    )
    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "awaiting", "sequence": 2}},
        {
            "status": 200,
            "body": approval_status_payload(
                approval_request_id,
                expires_at=expires_at,
                status="expired",
                decision=None,
            ),
        },
        {"status": 202, "body": {"event_id": "resolved", "sequence": 3}},
        {"session_id": "session-1"},
        {
            "attempt_id": "attempt-1",
            "status": "succeeded",
            "receipt_id": "receipt-expired",
        },
    )
    hermes = ApprovalHermes(expires_at=expires_at, outcome="expired")
    worker = FoundryWorker(
        foundry,
        hermes,
        renew_interval=0.1,
        approval_poll_interval=0.01,
    )

    result = await worker.run(max_turns=1)

    assert result[0].status == "succeeded"
    assert hermes.resolutions == []
    resolved_event = next(
        call
        for call in transport.calls
        if call[3] and call[3].get("type") == "execution.approval_resolved"
    )
    assert resolved_event[3]["payload"] == {
        "approval_request_id": approval_request_id,
        "outcome": "expired",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"remove": "action_preview"},
        {"action_preview": None},
        {"action_kind": "unsupported"},
        {"expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()},
    ],
)
async def test_worker_fails_closed_on_malformed_approval_request(change):
    expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    payload = {
        "hermes_approval_id": "approval-1",
        "action_kind": "plugin_tool",
        "action_label": "Connect Nabu",
        "action_preview": "Connect to Nabu",
        "expires_at": expires_at,
    }
    change = dict(change)
    removed = change.pop("remove", None)
    if removed is not None:
        payload.pop(removed)
    payload.update(change)

    class MalformedHermes:
        async def stream_profile_incremental(
            self, profile_id, session_id, _message, *, session_key
        ):
            async def events():
                yield HermesEvent(
                    "approval.request",
                    profile_id,
                    session_id,
                    "run-approval",
                    1,
                    payload,
                )

            return CancellableHermesStream(events())

    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt-malformed",
        },
    )
    result = await FoundryWorker(foundry, MalformedHermes()).run(max_turns=1)

    assert result[0].status == "failed"
    fail_call = next(call for call in transport.calls if "/fail" in call[1])
    assert fail_call[3]["code"] == "malformed_response"


@pytest.mark.asyncio
async def test_worker_rejects_second_pending_approval_request():
    expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    approval_request_id = foundry_module._approval_request_id(
        "attempt-1", "run-approval", "approval-1"
    )
    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "awaiting", "sequence": 2}},
        {
            "status": 200,
            "body": approval_status_payload(
                approval_request_id,
                expires_at=expires_at,
                status="decision_recorded",
                decision="approve",
            ),
        },
        {"attempt_id": "attempt-1", "status": "failed", "receipt_id": "receipt-second"},
    )
    result = await FoundryWorker(
        foundry,
        ApprovalHermes(
            expires_at=expires_at,
            outcome="approved",
            decision="approve",
            emit_second_request=True,
        ),
        renew_interval=0.1,
        approval_poll_interval=0.01,
    ).run(max_turns=1)

    assert result[0].status == "failed"
    assert next(call for call in transport.calls if "/fail" in call[1])[3]["code"] == (
        "malformed_response"
    )


@pytest.mark.asyncio
async def test_worker_rejects_terminal_event_while_approval_is_pending():
    expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    approval_request_id = foundry_module._approval_request_id(
        "attempt-1", "run-approval", "approval-1"
    )
    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "awaiting", "sequence": 2}},
        {
            "status": 200,
            "body": approval_status_payload(
                approval_request_id,
                expires_at=expires_at,
                status="decision_recorded",
                decision="approve",
            ),
        },
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt-pending",
        },
    )
    result = await FoundryWorker(
        foundry,
        ApprovalHermes(
            expires_at=expires_at,
            outcome="approved",
            decision="approve",
            terminal_while_pending=True,
        ),
        renew_interval=0.1,
        approval_poll_interval=0.01,
    ).run(max_turns=1)

    assert result[0].status == "failed"
    assert next(call for call in transport.calls if "/fail" in call[1])[3]["code"] == (
        "malformed_response"
    )


@pytest.mark.asyncio
async def test_worker_stops_when_approval_poll_loses_lease():
    expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()

    class LeaseLostWorker(FoundryWorker):
        async def _wait_for_approval(
            self, claim, approval_request_id, expires_at, lost
        ):
            lost.set()
            return "cancelled", None, None

    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "awaiting", "sequence": 2}},
        {"attempt_id": "attempt-1", "state": "released", "requeued": True},
    )
    result = await LeaseLostWorker(
        foundry,
        ApprovalHermes(expires_at=expires_at, outcome="cancelled"),
        renew_interval=0.1,
        approval_poll_interval=0.01,
    ).run(max_turns=1)

    assert result[0].state == "released"
    assert next(call for call in transport.calls if "/stopped" in call[1])[3] == {
        "reason": "lease_lost"
    }


@pytest.mark.asyncio
async def test_worker_fails_when_approval_resolution_window_closes(monkeypatch):
    base = 1_000.0
    expires_at = datetime.fromtimestamp(base + 1, UTC).isoformat()
    acknowledgement_deadline = datetime.fromtimestamp(base + 10, UTC).isoformat()
    clock = iter((base, base + 0.1, base + 0.2, base + 2))
    monkeypatch.setattr(foundry_module.time, "time", lambda: next(clock, base + 2))

    class ExpiringWorker(FoundryWorker):
        async def _wait_for_approval(
            self, claim, approval_request_id, expires_at, lost
        ):
            return "decision", "approve", acknowledgement_deadline

    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "awaiting", "sequence": 2}},
        {"attempt_id": "attempt-1", "status": "failed", "receipt_id": "receipt-window"},
    )
    result = await ExpiringWorker(
        foundry,
        ApprovalHermes(expires_at=expires_at, outcome="approved"),
        renew_interval=0.1,
        approval_poll_interval=0.01,
    ).run(max_turns=1)

    assert result[0].status == "failed"
    assert next(call for call in transport.calls if "/fail" in call[1])[3]["code"] == (
        "hermes_error"
    )


@pytest.mark.asyncio
async def test_worker_reconciles_lost_approval_resolution_before_continuing():
    expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    approval_request_id = foundry_module._approval_request_id(
        "attempt-1", "run-approval", "approval-1"
    )

    class LostResolutionHermes(ApprovalHermes):
        async def resolve_approval(self, *args, **kwargs):
            self.resolutions.append(
                {
                    "run_id": args[2],
                    "hermes_approval_id": args[3],
                    "decision": args[4],
                }
            )
            raise HermesTimeout("resolution response was lost")

        async def approval_status(self, *_args, **_kwargs):
            return {"status": "resolved", "outcome": "approved"}

    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "awaiting", "sequence": 2}},
        {
            "status": 200,
            "body": approval_status_payload(
                approval_request_id,
                expires_at=expires_at,
                status="decision_recorded",
                decision="approve",
            ),
        },
        {"status": 202, "body": {"event_id": "resolved", "sequence": 3}},
        {"session_id": "session-1"},
        {
            "attempt_id": "attempt-1",
            "status": "succeeded",
            "receipt_id": "receipt-reconciled",
        },
    )
    hermes = LostResolutionHermes(
        expires_at=expires_at,
        outcome="approved",
        decision="approve",
    )

    result = await FoundryWorker(
        foundry,
        hermes,
        renew_interval=0.1,
        approval_poll_interval=0.01,
    ).run(max_turns=1)

    assert result[0].status == "succeeded"
    assert len(hermes.resolutions) == 1
    assert [call[3]["type"] for call in transport.calls if "/events" in call[1]] == [
        "execution.dispatched",
        "execution.awaiting_action",
        "execution.approval_resolved",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("acknowledgement_deadline", "error_code"),
    [
        ("not-a-date", "MALFORMED_RESPONSE"),
        ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), "hermes_error"),
    ],
)
async def test_worker_rejects_unusable_approval_acknowledgement_deadline(
    acknowledgement_deadline, error_code
):
    expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    approval_request_id = foundry_module._approval_request_id(
        "attempt-1", "run-approval", "approval-1"
    )
    status = approval_status_payload(
        approval_request_id,
        expires_at=expires_at,
        status="decision_recorded",
        decision="approve",
    )
    status["acknowledgement_deadline_at"] = acknowledgement_deadline
    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "awaiting", "sequence": 2}},
        {"status": 200, "body": status},
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt-deadline",
        },
    )
    result = await FoundryWorker(
        foundry,
        ApprovalHermes(expires_at=expires_at, outcome="approved"),
        renew_interval=0.1,
        approval_poll_interval=0.01,
    ).run(max_turns=1)

    assert result[0].status == "failed"
    fail_call = next(call for call in transport.calls if "/fail" in call[1])
    assert fail_call[3]["code"] == error_code


@pytest.mark.asyncio
async def test_worker_fails_closed_when_cancelled_approval_cannot_be_resolved():
    expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    approval_request_id = foundry_module._approval_request_id(
        "attempt-1", "run-approval", "approval-1"
    )

    class NoResolverHermes:
        async def stream_profile_incremental(
            self, profile_id, session_id, _message, *, session_key
        ):
            return await ApprovalHermes(
                expires_at=expires_at, outcome="cancelled"
            ).stream_profile_incremental(
                profile_id,
                session_id,
                _message,
                session_key=session_key,
            )

    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "awaiting", "sequence": 2}},
        {
            "status": 200,
            "body": approval_status_payload(
                approval_request_id,
                expires_at=expires_at,
                status="cancelled",
                decision=None,
            ),
        },
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt-cancelled",
        },
    )
    result = await FoundryWorker(
        foundry,
        NoResolverHermes(),
        renew_interval=0.1,
        approval_poll_interval=0.01,
    ).run(max_turns=1)

    assert result[0].status == "failed"
    fail_call = next(call for call in transport.calls if "/fail" in call[1])
    assert fail_call[3]["code"] == "hermes_error"


@pytest.mark.asyncio
async def test_worker_converts_approval_resolution_timeout_to_failure():
    expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    approval_request_id = foundry_module._approval_request_id(
        "attempt-1", "run-approval", "approval-1"
    )

    class TimeoutHermes(ApprovalHermes):
        async def resolve_approval(self, *_args, **_kwargs):
            raise TimeoutError("resolution timed out")

    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "awaiting", "sequence": 2}},
        {
            "status": 200,
            "body": approval_status_payload(
                approval_request_id,
                expires_at=expires_at,
                status="decision_recorded",
                decision="approve",
            ),
        },
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt-timeout",
        },
    )
    result = await FoundryWorker(
        foundry,
        TimeoutHermes(expires_at=expires_at, outcome="approved"),
        renew_interval=0.1,
        approval_poll_interval=0.01,
    ).run(max_turns=1)

    assert result[0].status == "failed"
    fail_call = next(call for call in transport.calls if "/fail" in call[1])
    assert fail_call[3]["code"] == "timeout"


@pytest.mark.asyncio
async def test_worker_fails_when_approval_acknowledgement_is_unknown():
    expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    approval_request_id = foundry_module._approval_request_id(
        "attempt-1", "run-approval", "approval-1"
    )
    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "awaiting", "sequence": 2}},
        {
            "status": 200,
            "body": approval_status_payload(
                approval_request_id,
                expires_at=expires_at,
                status="outcome_unknown",
                decision=None,
            ),
        },
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt-unknown",
        },
    )
    result = await FoundryWorker(
        foundry,
        ApprovalHermes(expires_at=expires_at, outcome="expired"),
        renew_interval=0.1,
        approval_poll_interval=0.01,
    ).run(max_turns=1)

    assert result[0].status == "failed"
    fail_call = next(call for call in transport.calls if "/fail" in call[1])
    assert fail_call[3]["code"] == "hermes_error"


@pytest.mark.asyncio
async def test_worker_fails_when_terminal_resolution_receipt_conflicts_with_stream():
    expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    approval_request_id = foundry_module._approval_request_id(
        "attempt-1", "run-approval", "approval-1"
    )
    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "awaiting", "sequence": 2}},
        {
            "status": 200,
            "body": approval_status_payload(
                approval_request_id,
                expires_at=expires_at,
                status="decision_recorded",
                decision="approve",
            ),
        },
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt-mismatch",
        },
    )
    result = await FoundryWorker(
        foundry,
        ApprovalHermes(
            expires_at=expires_at,
            outcome="expired",
            decision="approve",
            stream_outcome="approved",
        ),
        renew_interval=0.1,
        approval_poll_interval=0.01,
    ).run(max_turns=1)

    assert result[0].status == "failed"
    assert next(call for call in transport.calls if "/fail" in call[1])[3]["code"] == (
        "malformed_response"
    )


@pytest.mark.asyncio
async def test_worker_fails_when_unresolved_approval_receipt_times_out():
    expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    approval_request_id = foundry_module._approval_request_id(
        "attempt-1", "run-approval", "approval-1"
    )

    class TimeoutHermes(ApprovalHermes):
        async def resolve_approval(self, *_args, **_kwargs):
            raise HermesTimeout("approval resolution timed out")

    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "awaiting", "sequence": 2}},
        {
            "status": 200,
            "body": approval_status_payload(
                approval_request_id,
                expires_at=expires_at,
                status="cancelled",
                decision=None,
            ),
        },
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt-timeout",
        },
    )
    result = await FoundryWorker(
        foundry,
        TimeoutHermes(expires_at=expires_at, outcome="cancelled"),
        renew_interval=0.1,
        approval_poll_interval=0.01,
    ).run(max_turns=1)

    assert result[0].status == "failed"
    assert next(call for call in transport.calls if "/fail" in call[1])[3]["code"] == (
        "timeout"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_id", "outcome", "response_extra"),
    [
        ("different-approval", "approved", {}),
        ("approval-1", "rejected", {}),
        ("approval-1", "invalid", {}),
        ("approval-1", "approved", {"unexpected": True}),
    ],
)
async def test_worker_rejects_conflicting_approval_response(
    response_id, outcome, response_extra
):
    expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    approval_request_id = foundry_module._approval_request_id(
        "attempt-1", "run-approval", "approval-1"
    )
    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "awaiting", "sequence": 2}},
        {
            "status": 200,
            "body": approval_status_payload(
                approval_request_id,
                expires_at=expires_at,
                status="decision_recorded",
                decision="approve",
            ),
        },
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt-conflict",
        },
    )
    hermes = ApprovalHermes(
        expires_at=expires_at,
        outcome=outcome,
        decision="approve",
        response_id=response_id,
        response_extra=response_extra,
    )
    result = await FoundryWorker(
        foundry,
        hermes,
        renew_interval=0.1,
        approval_poll_interval=0.01,
    ).run(max_turns=1)

    assert result[0].status == "failed"
    fail_call = next(call for call in transport.calls if "/fail" in call[1])
    assert fail_call[3]["code"] == "malformed_response"


@pytest.mark.asyncio
async def test_worker_rejects_approval_response_without_a_pending_request():
    class ResponseOnlyHermes:
        async def stream_profile_incremental(
            self, profile_id, session_id, _message, *, session_key
        ):
            async def events():
                yield HermesEvent(
                    "approval.responded",
                    profile_id,
                    session_id,
                    "run-approval",
                    1,
                    {
                        "hermes_approval_id": "approval-1",
                        "outcome": "approved",
                    },
                )

            return CancellableHermesStream(events())

    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt-no-pending",
        },
    )
    result = await FoundryWorker(foundry, ResponseOnlyHermes()).run(max_turns=1)

    assert result[0].status == "failed"
    assert (
        next(call for call in transport.calls if "/fail" in call[1])[3]["code"]
        == "malformed_response"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stopped_response_lost", [False, True])
async def test_worker_stops_when_approval_awaiting_event_response_is_lost(
    stopped_response_lost,
):
    expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        ResponseLossError("awaiting response lost"),
        ResponseLossError("awaiting response lost"),
        ServiceUnavailableError("stopped response lost")
        if stopped_response_lost
        else {"attempt_id": "attempt-1", "state": "released", "requeued": True},
    )
    result = await FoundryWorker(
        foundry,
        ApprovalHermes(expires_at=expires_at, outcome="expired"),
        renew_interval=0.1,
        approval_poll_interval=0.01,
    ).run(max_turns=1)

    if stopped_response_lost:
        assert result == (None,)
    else:
        assert result[0].state == "released"
        stopped = next(call for call in transport.calls if "/stopped" in call[1])
        assert stopped[3] == {"reason": "event_response_lost"}


@pytest.mark.asyncio
@pytest.mark.parametrize("stopped_response_lost", [False, True])
async def test_worker_stops_when_approval_resolution_event_response_is_lost(
    stopped_response_lost,
):
    expires_at = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    approval_request_id = foundry_module._approval_request_id(
        "attempt-1", "run-approval", "approval-1"
    )
    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "awaiting", "sequence": 2}},
        {
            "status": 200,
            "body": approval_status_payload(
                approval_request_id,
                expires_at=expires_at,
                status="expired",
                decision=None,
            ),
        },
        ResponseLossError("resolved response lost"),
        ResponseLossError("resolved response lost"),
        ServiceUnavailableError("stopped response lost")
        if stopped_response_lost
        else {"attempt_id": "attempt-1", "state": "released", "requeued": True},
    )
    result = await FoundryWorker(
        foundry,
        ApprovalHermes(expires_at=expires_at, outcome="expired"),
        renew_interval=0.1,
        approval_poll_interval=0.01,
    ).run(max_turns=1)

    if stopped_response_lost:
        assert result == (None,)
    else:
        assert result[0].state == "released"
        stopped = next(call for call in transport.calls if "/stopped" in call[1])
        assert stopped[3] == {"reason": "event_response_lost"}


def _worker_claim():
    return FoundryClaim(
        attempt_id="attempt-1",
        execution_id="execution-1",
        profile_id="profile-1",
        hermes_profile_key="ally-a",
        model="gpt-5.6-luna",
        conversation_id="cloud-1",
        session_id="session-1",
        stream_id="stream-1",
        lease_id="lease-1",
        lease_token="lease-secret",
        expires_at="2026-08-09T12:00:00Z",
        payload={"message": "hello"},
        claim_id="claim-1",
    )


def _approval_expiry():
    return (datetime.now(UTC) + timedelta(seconds=30)).isoformat()


class PollFoundry:
    def __init__(self, payload):
        self.payload = payload

    async def approval_status(self, *_args):
        return self.payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "decision", "expected"),
    [
        ("expired", None, ("expired", None, None)),
        ("cancelled", None, ("cancelled", None, None)),
        ("outcome_unknown", None, ("outcome_unknown", None, None)),
    ],
)
async def test_wait_for_approval_returns_terminal_foundry_states(
    state, decision, expected
):
    approval_id = "approval-request"
    worker = FoundryWorker(
        PollFoundry(
            {
                "approval_request_id": approval_id,
                "status": state,
                "decision": decision,
            }
        ),
        object(),
        approval_poll_interval=0.01,
    )

    result = await worker._wait_for_approval(
        _worker_claim(),
        approval_id,
        _approval_expiry(),
        asyncio.Event(),
    )

    assert result == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transient_error",
    [ResponseLossError, RateLimitedError, ServiceUnavailableError],
)
async def test_wait_for_approval_retries_transient_foundry_status_errors(
    transient_error,
):
    class RetryingPollFoundry:
        def __init__(self):
            self.calls = 0

        async def approval_status(self, *_args):
            self.calls += 1
            if self.calls == 1:
                raise transient_error("temporary")
            return {
                "approval_request_id": "approval-request",
                "status": "decision_recorded",
                "decision": "approve",
                "acknowledgement_deadline_at": _approval_expiry(),
            }

    foundry = RetryingPollFoundry()
    worker = FoundryWorker(
        foundry,
        object(),
        approval_poll_interval=0.001,
    )

    result = await worker._wait_for_approval(
        _worker_claim(),
        "approval-request",
        _approval_expiry(),
        asyncio.Event(),
    )

    assert result[:2] == ("decision", "approve")
    assert foundry.calls == 2


@pytest.mark.asyncio
async def test_wait_for_approval_rejects_synchronous_status_poll_without_calling():
    calls = []

    class SyncPollFoundry:
        def approval_status(self, *_args):
            calls.append(True)
            return {}

    worker = FoundryWorker(SyncPollFoundry(), object())
    with pytest.raises(FoundryError, match="must be asynchronous") as error:
        await worker._wait_for_approval(
            _worker_claim(),
            "approval-request",
            _approval_expiry(),
            asyncio.Event(),
        )

    assert error.value.code == "APPROVAL_UNAVAILABLE"
    assert calls == []


@pytest.mark.asyncio
async def test_wait_for_approval_stops_after_transient_error_consumes_expiry(
    monkeypatch,
):
    wall_times = iter((100.0, 100.2))
    sleeps = []

    def fake_time():
        return next(wall_times, 100.2)

    async def record_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(foundry_module.time, "time", fake_time)
    monkeypatch.setattr(foundry_module.asyncio, "sleep", record_sleep)

    class ExpiredPollFoundry:
        async def approval_status(self, *_args):
            raise ResponseLossError("temporary")

    worker = FoundryWorker(
        ExpiredPollFoundry(),
        object(),
        approval_poll_interval=0.001,
    )
    result = await worker._wait_for_approval(
        _worker_claim(),
        "approval-request",
        datetime.fromtimestamp(100.1, UTC),
        asyncio.Event(),
    )

    assert result == ("expired", None, None)
    assert sleeps == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {
            "approval_request_id": "other-request",
            "status": "pending",
            "decision": None,
        },
        {
            "approval_request_id": "approval-request",
            "status": "decision_recorded",
            "decision": "approve",
        },
        {
            "approval_request_id": "approval-request",
            "status": "decision_recorded",
            "decision": "maybe",
            "acknowledgement_deadline_at": _approval_expiry(),
        },
    ],
)
async def test_wait_for_approval_rejects_malformed_foundry_status(payload):
    worker = FoundryWorker(
        PollFoundry(payload),
        object(),
        approval_poll_interval=0.01,
    )

    with pytest.raises(FoundryError) as error:
        await worker._wait_for_approval(
            _worker_claim(),
            "approval-request",
            _approval_expiry(),
            asyncio.Event(),
        )

    assert error.value.code == "MALFORMED_RESPONSE"


@pytest.mark.asyncio
async def test_reconcile_hermes_approval_retries_transient_status_and_marks_acknowledged():
    class Hermes:
        def __init__(self):
            self.calls = 0

        async def approval_status(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise HermesDisconnected("temporary")
            return {"status": "resolved", "outcome": "approved"}

    hermes = Hermes()
    worker = FoundryWorker(
        object(),
        hermes,
        approval_poll_interval=0.001,
    )
    pending = {}

    await worker._reconcile_hermes_approval(
        "ally-a",
        "session-1",
        "run-1",
        "approval-1",
        "approve",
        "session-key",
        _approval_expiry(),
        pending,
    )

    assert pending == {"acknowledged": "1"}
    assert hermes.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["expired", "cancelled"])
async def test_terminal_status_reconciliation_records_receipt_without_resending(status):
    class Hermes:
        async def approval_status(self, *_args, **_kwargs):
            return {"status": status, "outcome": status}

        async def resolve_approval(self, *_args, **_kwargs):
            pytest.fail("status reconciliation must never resend the decision")

    worker = FoundryWorker(object(), Hermes(), approval_poll_interval=0.001)
    pending = {}
    await worker._reconcile_hermes_approval(
        "ally-a",
        "session-1",
        "run-1",
        "approval-1",
        "approve",
        "session-key",
        _approval_expiry(),
        pending,
    )
    assert pending == {"wait_outcome": status}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "outcome", "error"),
    [
        ("resolved", "rejected", HermesMalformedResponse),
        ("expired", None, HermesError),
    ],
)
async def test_reconcile_hermes_approval_rejects_conflicting_terminal_state(
    status, outcome, error
):
    class Hermes:
        async def approval_status(self, *_args, **_kwargs):
            return {"status": status, "outcome": outcome}

    worker = FoundryWorker(object(), Hermes(), approval_poll_interval=0.001)
    with pytest.raises(error):
        await worker._reconcile_hermes_approval(
            "ally-a",
            "session-1",
            "run-1",
            "approval-1",
            "approve",
            "session-key",
            _approval_expiry(),
            {},
        )


@pytest.mark.asyncio
async def test_reconcile_hermes_approval_requires_a_status_reader_and_bounded_deadline():
    worker = FoundryWorker(object(), object())
    with pytest.raises(HermesTimeout):
        await worker._reconcile_hermes_approval(
            "ally-a",
            "session-1",
            "run-1",
            "approval-1",
            "approve",
            "session-key",
            _approval_expiry(),
            {},
        )

    class Hermes:
        async def approval_status(self, *_args, **_kwargs):
            return {"status": "pending"}

    worker = FoundryWorker(object(), Hermes())
    with pytest.raises(FoundryError, match="deadline was malformed"):
        await worker._reconcile_hermes_approval(
            "ally-a",
            "session-1",
            "run-1",
            "approval-1",
            "approve",
            "session-key",
            "not-a-date",
            {},
        )


@pytest.mark.asyncio
async def test_worker_forwards_a_long_stream_beyond_legacy_513_event_limit():
    class LongHermes:
        async def stream_profile_incremental(
            self, profile_id, session_id, _message, *, session_key
        ):
            for sequence in range(762):
                yield HermesEvent(
                    name="message.delta",
                    profile_id=profile_id,
                    session_id=session_id,
                    run_id="run-long",
                    sequence=sequence + 1,
                    payload={"text": "x"},
                )
            yield HermesEvent(
                name="execution.completed",
                profile_id=profile_id,
                session_id=session_id,
                run_id="run-long",
                sequence=763,
                payload={"run_id": "run-long", "status": "completed"},
            )

    responses = [CLAIM]
    responses.extend(
        [{"status": 202, "body": {"event_id": "event", "sequence": 1}}] * (1 + 762)
    )
    responses.extend(
        [
            {"session_id": "session-1"},
            {
                "attempt_id": "attempt-1",
                "status": "succeeded",
                "receipt_id": "receipt-1",
            },
        ]
    )
    foundry, transport = client(*responses)
    worker = FoundryWorker(foundry, LongHermes(), renew_interval=0.1)

    result = await worker.run(max_turns=1)

    assert result[0].status == "succeeded"
    event_calls = [call for call in transport.calls if "/events" in call[1]]
    assert len(event_calls) == 763
    assert transport.calls[-1][1].endswith("/complete")
    assert transport.calls[-1][3]["sequence"] == 764


@pytest.mark.asyncio
async def test_client_rejects_reserved_terminal_slot_for_ordinary_event():
    foundry, transport = client()
    with pytest.raises(ValueError, match="sequence"):
        await foundry.event(
            "attempt-1",
            "lease-token",
            stream_id="stream-1",
            sequence=100001,
            event_type="message.delta",
            payload={"text": "x"},
        )
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("response_losses", [0, 1, 2])
async def test_worker_closes_stream_and_emits_reserved_budget_failure(
    monkeypatch, response_losses
):
    monkeypatch.setattr(foundry_module, "MAX_RUNTIME_EVENT_SEQUENCE", 2)
    monkeypatch.setattr(foundry_module, "MAX_TERMINAL_SEQUENCE", 3)

    class BudgetHermes:
        def __init__(self):
            self.closed = False

        async def stream_profile_incremental(
            self, profile_id, session_id, _message, *, session_key
        ):
            async def events():
                for sequence in (1, 2):
                    yield HermesEvent(
                        name="message.delta",
                        profile_id=profile_id,
                        session_id=session_id,
                        run_id="run-budget",
                        sequence=sequence,
                        payload={"text": "x"},
                    )

            stream = CancellableHermesStream(events())
            original_close = stream.aclose

            async def close():
                self.closed = True
                await original_close()

            stream.aclose = close
            return stream

    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "delta", "sequence": 2}},
        *[ResponseLossError("terminal response lost") for _ in range(response_losses)],
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt-budget",
        }
        if response_losses < 2
        else {"attempt_id": "attempt-1", "state": "released", "requeued": False},
    )
    hermes = BudgetHermes()
    worker = FoundryWorker(foundry, hermes, renew_interval=0.1)

    result = await worker.run(max_turns=1)

    if response_losses < 2:
        assert result[0].status == "failed"
    else:
        assert result == (None,)
    assert hermes.closed
    event_calls = [call for call in transport.calls if "/events" in call[1]]
    assert len(event_calls) == 2
    fail_calls = [call for call in transport.calls if "/fail" in call[1]]
    assert len(fail_calls) == min(response_losses + 1, 2)
    assert all(call[3] == fail_calls[0][3] for call in fail_calls)
    assert fail_calls[0][3]["sequence"] == 3
    assert fail_calls[0][3]["code"] == "event_budget_exhausted"
    assert fail_calls[0][3]["retryable"] is False
    assert not any("/complete" in call[1] for call in transport.calls)
    assert not any("/stopped" in call[1] for call in transport.calls)


@pytest.mark.asyncio
async def test_worker_clamps_failure_after_boundary_completion_rejection(monkeypatch):
    monkeypatch.setattr(foundry_module, "MAX_RUNTIME_EVENT_SEQUENCE", 2)
    monkeypatch.setattr(foundry_module, "MAX_TERMINAL_SEQUENCE", 3)

    class BoundaryHermes:
        async def stream_profile_incremental(
            self, profile_id, session_id, _message, *, session_key
        ):
            yield HermesEvent(
                name="message.delta",
                profile_id=profile_id,
                session_id=session_id,
                run_id="run-boundary",
                sequence=1,
                payload={"text": "x"},
            )
            yield HermesEvent(
                name="execution.completed",
                profile_id=profile_id,
                session_id=session_id,
                run_id="run-boundary",
                sequence=2,
                payload={"run_id": "run-boundary", "status": "completed"},
            )

    foundry, transport = client(
        CLAIM,
        {"status": 202, "body": {"event_id": "dispatch", "sequence": 1}},
        {"status": 202, "body": {"event_id": "delta", "sequence": 2}},
        {"session_id": "session-1"},
        ServiceUnavailableError("completion unavailable"),
        {
            "attempt_id": "attempt-1",
            "status": "failed",
            "receipt_id": "receipt-failure",
        },
    )
    worker = FoundryWorker(foundry, BoundaryHermes(), renew_interval=0.1)

    result = await worker.run(max_turns=1)

    assert result[0].status == "failed"
    complete_calls = [call for call in transport.calls if "/complete" in call[1]]
    fail_calls = [call for call in transport.calls if "/fail" in call[1]]
    assert len(complete_calls) == 1
    assert len(fail_calls) == 1
    assert fail_calls[0][3]["sequence"] == 3
    assert fail_calls[0][3]["code"] == ServiceUnavailableError.code
    assert not any("/stopped" in call[1] for call in transport.calls)


@pytest.mark.asyncio
async def test_worker_refills_free_slot_while_an_existing_turn_is_held(monkeypatch):
    release = asyncio.Event()

    class IntermittentFoundry:
        def __init__(self):
            self.calls = 0

        async def claim(self, _available_slots, *, claim_id):
            self.calls += 1
            if self.calls == 1:
                return "held"
            if self.calls == 2:
                return None
            if self.calls == 3:
                return "second"
            return None

    foundry = IntermittentFoundry()
    worker = FoundryWorker(foundry, object(), slots=2)

    async def run_claim(claim):
        if claim == "held":
            await release.wait()
        else:
            release.set()
        return claim

    monkeypatch.setattr(worker, "_run_claim", run_claim)

    results = await asyncio.wait_for(
        worker.run(max_turns=2, idle_cycles=5, idle_delay=0.01),
        timeout=1,
    )

    assert set(results) == {"held", "second"}
    assert foundry.calls >= 3


@pytest.mark.asyncio
async def test_worker_idle_claim_backoff_grows_to_bounded_ceiling(monkeypatch):
    class IdleFoundry:
        def __init__(self):
            self.calls = 0

        async def claim(self, _available_slots, *, claim_id):
            self.calls += 1

    foundry = IdleFoundry()
    worker = FoundryWorker(foundry, object())
    delays: list[float] = []

    async def record_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(foundry_module.random, "random", lambda: 0.0)
    monkeypatch.setattr(foundry_module.asyncio, "sleep", record_sleep)

    assert await worker.run(idle_cycles=6) == ()
    assert foundry.calls == 6
    assert delays == [1.0, 2.0, 4.0, 8.0, 10.0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code"),
    [(404, "FOUNDRY_ERROR"), (200, "MALFORMED_RESPONSE")],
)
async def test_worker_activity_wait_optional_failures_fall_back_to_polling(
    monkeypatch, status, code
):
    class OptionalWaitFoundry:
        async def claim(self, _available_slots, *, claim_id):
            return None

        async def wait_for_activity(self, _after_revision, _wait_seconds):
            raise FoundryError(
                "optional activity wait failed", status=status, code=code
            )

    sleeps: list[float] = []

    async def record_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(foundry_module.asyncio, "sleep", record_sleep)
    worker = FoundryWorker(
        OptionalWaitFoundry(),
        object(),
        activity_wait_enabled=True,
    )

    assert await worker.run(idle_cycles=3) == ()
    assert len(sleeps) == 2


@pytest.mark.asyncio
async def test_worker_activity_wait_setting_mismatch_disables_optional_wait(
    monkeypatch,
):
    class ShortWaitFoundry:
        calls = 0

        async def claim(self, _available_slots, *, claim_id):
            return None

        async def wait_for_activity(self, _after_revision, wait_seconds):
            self.calls += 1
            assert wait_seconds > 1
            raise InvalidRequestError("maximum wait is one second", status=422)

    async def no_sleep(_delay):
        pass

    monkeypatch.setattr(foundry_module.asyncio, "sleep", no_sleep)
    foundry = ShortWaitFoundry()
    worker = FoundryWorker(foundry, object(), activity_wait_enabled=True)
    assert await worker.run(idle_cycles=6) == ()
    assert foundry.calls == 1
    assert not worker._activity_wait_enabled


@pytest.mark.asyncio
async def test_worker_activity_changed_path_reconciles_before_claim(monkeypatch):
    class Reconciler:
        def __init__(self):
            self.calls = 0

        async def reconcile(self):
            self.calls += 1

    class ActivityFoundry:
        def __init__(self):
            self.claims = []
            self.waits = []

        async def claim(self, _available_slots, *, claim_id):
            self.claims.append(claim_id)
            return None if len(self.claims) <= 2 else "claim"

        async def wait_for_activity(self, after_revision, wait_seconds):
            self.waits.append((after_revision, wait_seconds))
            return ActivityWaitReceipt(revision=7, reason="changed")

    async def run_claim(claim):
        return claim

    async def no_sleep(_delay):
        return None

    foundry = ActivityFoundry()
    reconciler = Reconciler()
    worker = FoundryWorker(
        foundry,
        object(),
        profile_reconciler=reconciler,
        activity_wait_enabled=True,
    )
    monkeypatch.setattr(worker, "_run_claim", run_claim)
    monkeypatch.setattr(foundry_module.asyncio, "sleep", no_sleep)

    assert await worker.run(max_turns=1, idle_cycles=None) == ("claim",)
    assert foundry.waits == [(0, 5.0)]
    assert worker._activity_revision == 7
    assert reconciler.calls == 2
    assert len(foundry.claims) == 3
    assert len(set(foundry.claims)) == 3


@pytest.mark.asyncio
async def test_worker_activity_timeout_path_keeps_claim_loop_moving(monkeypatch):
    class ActivityFoundry:
        def __init__(self):
            self.claims = 0
            self.waits = []

        async def claim(self, _available_slots, *, claim_id):
            self.claims += 1
            return None if self.claims <= 2 else "claim"

        async def wait_for_activity(self, after_revision, wait_seconds):
            self.waits.append((after_revision, wait_seconds))
            return ActivityWaitReceipt(revision=3, reason="timeout")

    sleeps = []

    async def record_sleep(delay):
        sleeps.append(delay)

    async def run_claim(claim):
        return claim

    foundry = ActivityFoundry()
    worker = FoundryWorker(foundry, object(), activity_wait_enabled=True)
    monkeypatch.setattr(foundry_module.random, "uniform", lambda _low, _high: 0.1)
    monkeypatch.setattr(foundry_module.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(worker, "_run_claim", run_claim)

    assert await worker.run(max_turns=1, idle_cycles=None) == ("claim",)
    assert foundry.waits == [(0, 5.0)]
    assert worker._activity_revision == 3
    assert sleeps == [1.0, 0.1]


@pytest.mark.asyncio
async def test_worker_retryable_claim_skips_activity_wait_and_keeps_backoff(
    monkeypatch,
):
    class RetryableFoundry:
        def __init__(self):
            self.claims = 0
            self.waits = []

        async def claim(self, _available_slots, *, claim_id):
            self.claims += 1
            if self.claims == 1:
                raise ServiceUnavailableError("temporarily unavailable")

        async def wait_for_activity(self, after_revision, wait_seconds):
            self.waits.append((after_revision, wait_seconds))
            return ActivityWaitReceipt(revision=1, reason="changed")

    sleeps = []

    async def record_sleep(delay):
        sleeps.append(delay)

    foundry = RetryableFoundry()
    worker = FoundryWorker(foundry, object(), activity_wait_enabled=True)
    monkeypatch.setattr(foundry_module.random, "random", lambda: 0.0)
    monkeypatch.setattr(foundry_module.asyncio, "sleep", record_sleep)

    assert await worker.run(idle_cycles=1, idle_delay=2.0) == ()
    assert foundry.claims == 2
    assert foundry.waits == []
    assert sleeps == [2.0]


@pytest.mark.asyncio
async def test_worker_activity_wait_cancellation_returns_control():
    started = asyncio.Event()

    class BlockingActivityFoundry:
        async def wait_for_activity(self, _after_revision, _wait_seconds):
            started.set()
            await asyncio.Event().wait()

    worker = FoundryWorker(
        BlockingActivityFoundry(),
        object(),
        activity_wait_enabled=True,
    )
    task = asyncio.create_task(worker._wait_for_activity())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert worker._stopping is False


@pytest.mark.asyncio
async def test_worker_materialization_window_covers_worst_idle_phase(monkeypatch):
    real_sleep = asyncio.sleep
    now = 0.0
    created_at = 16.0
    materialized_at = 24.0
    dispatch_at = created_at + 14.0
    delays: list[float] = []
    claims: list[float] = []
    materialized = False

    async def advance(delay):
        nonlocal now
        delays.append(delay)
        now += delay
        await real_sleep(0)

    class Reconciler:
        async def reconcile(self):
            nonlocal materialized
            if not materialized and now >= materialized_at:
                materialized = True
                return SimpleNamespace(materialized=(object(),))
            return SimpleNamespace(materialized=())

    class DispatchFoundry:
        async def claim(self, _available_slots, *, claim_id):
            claims.append(now)
            if now >= dispatch_at:
                return "dispatch"
            return None

    worker = FoundryWorker(
        DispatchFoundry(),
        object(),
        profile_reconciler=Reconciler(),
        profile_reconcile_interval=5.0,
        clock=lambda: now,
    )

    async def run_claim(claim):
        return claim

    monkeypatch.setattr(foundry_module.random, "random", lambda: 0.0)
    monkeypatch.setattr(foundry_module.asyncio, "sleep", advance)
    monkeypatch.setattr(worker, "_run_claim", run_claim)

    assert await worker.run(max_turns=1, idle_cycles=None) == ("dispatch",)
    assert dispatch_at == 30.0
    assert claims == [0.0, 1.0, 3.0, 7.0, 15.0, 25.0, 26.0, 27.0, 28.0, 29.0, 30.0]
    assert delays == [1.0, 2.0, 4.0, 8.0, 10.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    assert worker._fast_polls_remaining == 0


@pytest.mark.asyncio
async def test_worker_materialization_window_preserves_failure_backoff(monkeypatch):
    class Reconciler:
        async def reconcile(self):
            return SimpleNamespace(materialized=(object(),))

    remaining_at_claim: list[int] = []
    responses = iter(
        (
            ServiceUnavailableError("temporarily unavailable"),
            ServiceUnavailableError("temporarily unavailable"),
            None,
            "recovered",
        )
    )
    worker_ref: list[FoundryWorker] = []

    class RetryableFoundry:
        async def claim(self, _available_slots, *, claim_id):
            remaining_at_claim.append(worker_ref[0]._fast_polls_remaining)
            response = next(responses)
            if isinstance(response, BaseException):
                raise response
            return response

    worker = FoundryWorker(
        RetryableFoundry(),
        object(),
        profile_reconciler=Reconciler(),
    )
    worker_ref.append(worker)
    delays: list[float] = []

    async def record_sleep(delay):
        delays.append(delay)

    async def run_claim(claim):
        return claim

    monkeypatch.setattr(foundry_module.random, "random", lambda: 0.0)
    monkeypatch.setattr(foundry_module.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(worker, "_run_claim", run_claim)

    assert await worker.run(max_turns=1, idle_cycles=None) == ("recovered",)
    assert remaining_at_claim == [8, 8, 8, 7]
    assert delays == [1.0, 2.0, 1.0]


@pytest.mark.asyncio
async def test_worker_materialization_window_returns_to_idle_backoff(monkeypatch):
    class Reconciler:
        async def reconcile(self):
            return SimpleNamespace(materialized=(object(),))

    class IdleFoundry:
        async def claim(self, _available_slots, *, claim_id):
            return None

    worker = FoundryWorker(
        IdleFoundry(),
        object(),
        profile_reconciler=Reconciler(),
    )
    delays: list[float] = []

    async def record_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(foundry_module.random, "random", lambda: 0.0)
    monkeypatch.setattr(foundry_module.asyncio, "sleep", record_sleep)

    assert await worker.run(idle_cycles=11) == ()
    assert delays == [1.0] * 9 + [2.0]


def test_idle_claim_backoff_keeps_jitter_at_ceiling(monkeypatch):
    jitter = iter((0.2, 0.8))
    monkeypatch.setattr(foundry_module.random, "random", lambda: next(jitter))

    delays = [
        foundry_module._jittered_idle_delay(10.0, 1.0),
        foundry_module._jittered_idle_delay(10.0, 1.0),
    ]

    assert delays == [9.5, 8.0]
    assert all(1.0 <= delay <= 10.0 for delay in delays)


@pytest.mark.asyncio
async def test_worker_claim_or_transport_recovery_resets_idle_backoff(monkeypatch):
    class RecoveringFoundry:
        def __init__(self):
            self.responses = deque(
                (None, None, "claimed", None),
            )

        async def claim(self, _available_slots, *, claim_id):
            return self.responses.popleft() if self.responses else None

    foundry = RecoveringFoundry()
    worker = FoundryWorker(foundry, object())

    async def run_claim(claim):
        return claim

    monkeypatch.setattr(worker, "_run_claim", run_claim)
    delays: list[float] = []

    async def record_sleep(delay):
        delays.append(delay)
        if len(delays) == 3:
            await worker.stop()

    monkeypatch.setattr(foundry_module.random, "random", lambda: 0.0)
    monkeypatch.setattr(foundry_module.asyncio, "sleep", record_sleep)

    assert await worker.run(idle_cycles=None) == ("claimed",)
    assert delays == [1.0, 2.0, 1.0]

    class RetryableFoundry:
        def __init__(self):
            self.calls = 0

        async def claim(self, _available_slots, *, claim_id):
            self.calls += 1
            if self.calls == 1:
                raise ServiceUnavailableError("temporarily unavailable")

    foundry = RetryableFoundry()
    worker = FoundryWorker(foundry, object())
    delays = []

    async def stop_after_recovery(delay):
        delays.append(delay)
        if len(delays) == 2:
            await worker.stop()

    monkeypatch.setattr(foundry_module.asyncio, "sleep", stop_after_recovery)
    assert await worker.run(idle_cycles=None) == ()
    assert foundry.calls == 2
    assert delays == [1.0, 1.0]


@pytest.mark.asyncio
async def test_profile_reconciliation_retry_uses_bounded_exponential_backoff(
    monkeypatch,
):
    worker = FoundryWorker(object(), object(), profile_reconciler=object())
    delays: list[float] = []
    events = []
    monkeypatch.setattr(
        "allies_runtime.observability.emit_runtime_event", events.append
    )

    async def fail_reconciliation(*, force=False):
        raise ServiceUnavailableError("temporarily unavailable")

    async def record_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(worker, "_reconcile_profiles", fail_reconciliation)
    monkeypatch.setattr(asyncio, "sleep", record_sleep)

    for _ in range(5):
        assert not await worker._reconcile_profiles_or_wait(retry_delay=1.0)

    assert delays == [1.0, 2.0, 4.0, 5.0, 5.0]
    waits = [
        event
        for event in events
        if event.get("operation") == "profile.reconciliation_retry_wait"
    ]
    assert len(waits) == 10
    assert [event["retry_count"] for event in waits[1::2]] == [1, 2, 3, 4, 5]
    assert all(event["correlation_id"] == worker.boot_id for event in waits)
    assert all(event["duration_ms"] >= 0 for event in waits[1::2])


@pytest.mark.asyncio
async def test_profile_reconciliation_retries_not_ready_receipt(monkeypatch):
    worker = FoundryWorker(object(), object(), profile_reconciler=object())
    delays: list[float] = []

    async def fail_reconciliation(*, force=False):
        raise NotReadyError("runtime start is still being confirmed")

    async def record_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(worker, "_reconcile_profiles", fail_reconciliation)
    monkeypatch.setattr(asyncio, "sleep", record_sleep)

    assert not await worker._reconcile_profiles_or_wait(retry_delay=1.0)
    assert delays == [1.0]


@pytest.mark.asyncio
async def test_profile_reconciliation_retries_fenced_readiness_receipt(monkeypatch):
    class Reconciler:
        async def reconcile(self):
            return None

    class ReadinessFoundry:
        def __init__(self):
            self.last_reconciliation_snapshot = RuntimeReconciliationSnapshot(
                machine_generation=7,
                runtime_start_epoch=12,
                profiles=(),
            )
            self.calls = 0

        async def report_readiness(self, **_payload):
            self.calls += 1
            if self.calls == 1:
                raise FencedError("runtime start epoch changed")

    foundry = ReadinessFoundry()
    worker = FoundryWorker(
        foundry,
        FakeHermesClient(),
        profile_reconciler=Reconciler(),
    )
    delays: list[float] = []

    async def record_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", record_sleep)

    assert not await worker._reconcile_profiles_or_wait(force=True, retry_delay=1.0)
    assert await worker._reconcile_profiles_or_wait(force=True, retry_delay=1.0)
    assert foundry.calls == 2
    assert delays == [1.0]


@pytest.mark.asyncio
async def test_profile_reconciliation_retries_hermes_health_error(monkeypatch):
    class Reconciler:
        async def reconcile(self):
            return None

    class ReadinessFoundry:
        last_reconciliation_snapshot = RuntimeReconciliationSnapshot(
            machine_generation=7,
            runtime_start_epoch=12,
            profiles=(),
        )

        def __init__(self):
            self.receipts = 0

        async def report_readiness(self, **_payload):
            self.receipts += 1

    class RecoveringHermes:
        def __init__(self):
            self.calls = 0

        async def health_detailed(self):
            self.calls += 1
            if self.calls == 1:
                raise HermesError("Hermes temporarily disconnected")
            return SimpleNamespace(status="healthy")

    foundry = ReadinessFoundry()
    hermes = RecoveringHermes()
    worker = FoundryWorker(foundry, hermes, profile_reconciler=Reconciler())
    delays: list[float] = []

    async def record_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", record_sleep)

    assert not await worker._reconcile_profiles_or_wait(force=True, retry_delay=1.0)
    assert await worker._reconcile_profiles_or_wait(force=True, retry_delay=1.0)
    assert hermes.calls == 2
    assert foundry.receipts == 1
    assert delays == [1.0]


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


@pytest.mark.asyncio
async def test_worker_reports_readiness_and_heartbeats_after_profile_reconciliation():
    class Reconciler:
        def __init__(self):
            self.calls = 0

        async def reconcile(self):
            self.calls += 1

    class ReadinessFoundry:
        def __init__(self):
            self.last_reconciliation_snapshot = RuntimeReconciliationSnapshot(
                machine_generation=7,
                runtime_start_epoch=12,
                profiles=(),
            )
            self.receipts = []

        async def report_readiness(self, **payload):
            self.receipts.append(payload)

    now = [0.0]
    foundry = ReadinessFoundry()
    reconciler = Reconciler()
    worker = FoundryWorker(
        foundry,
        FakeHermesClient(),
        profile_reconciler=reconciler,
        profile_reconcile_interval=1.0,
        readiness_heartbeat_interval=15.0,
        clock=lambda: now[0],
        boot_id="00000000-0000-4000-8000-000000000009",
    )

    await worker._reconcile_profiles(force=True)
    now[0] = 2.0
    await worker._reconcile_profiles()
    now[0] = 16.0
    await worker._reconcile_profiles()

    assert reconciler.calls == 3
    assert foundry.receipts == [
        {
            "boot_id": "00000000-0000-4000-8000-000000000009",
            "reconciled_generation": 7,
            "runtime_start_epoch": 12,
        },
        {
            "boot_id": "00000000-0000-4000-8000-000000000009",
            "reconciled_generation": 7,
            "runtime_start_epoch": 12,
        },
    ]


@pytest.mark.asyncio
async def test_worker_does_not_report_readiness_until_hermes_is_ready():
    class Reconciler:
        async def reconcile(self):
            return None

    class ReadinessFoundry:
        last_reconciliation_snapshot = RuntimeReconciliationSnapshot(
            machine_generation=7,
            runtime_start_epoch=12,
            profiles=(),
        )

        async def report_readiness(self, **_payload):
            raise AssertionError("readiness must not be reported")

    worker = FoundryWorker(
        ReadinessFoundry(),
        FakeHermesClient(health_status="degraded"),
        profile_reconciler=Reconciler(),
    )

    with pytest.raises(ServiceUnavailableError, match="Hermes is not ready"):
        await worker._reconcile_profiles(force=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hermes", "expected"),
    [
        (object(), True),
        (SimpleNamespace(health=lambda: SimpleNamespace(status="healthy")), True),
        (
            SimpleNamespace(health_detailed=lambda: SimpleNamespace(status="degraded")),
            False,
        ),
        (
            SimpleNamespace(
                health_detailed=lambda: SimpleNamespace(
                    status="degraded",
                    readiness={
                        "checks": {"gateway": {"status": "ok", "state": "running"}}
                    },
                )
            ),
            True,
        ),
        (SimpleNamespace(health=lambda: SimpleNamespace(status="unknown")), False),
    ],
    ids=["no-health-api", "legacy-health", "degraded", "gateway-ready", "unknown"],
)
async def test_worker_hermes_health_compatibility_and_degraded_gateway(
    hermes, expected
):
    worker = FoundryWorker(object(), hermes)
    assert await worker._hermes_ready() is expected
