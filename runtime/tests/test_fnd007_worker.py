from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from allies_runtime.errors import HermesMalformedResponse
from allies_runtime.foundry import (
    EventReceipt,
    FencedError,
    FoundryClaim,
    FoundryWorker,
    ResponseLossError,
    SessionReceipt,
    StoppedReceipt,
    TerminalReceipt,
)
from allies_runtime.hermes import (
    MAX_MESSAGE_BYTES,
    CancellableHermesStream,
    HermesEvent,
)


def claim(*, conversation_id: str | None = None, session_id: str | None = None):
    payload = {"message": "hello"}
    if conversation_id is None:
        payload["cloud_conversation_ref"] = "cloud-1"
    return FoundryClaim(
        attempt_id="attempt-1",
        execution_id="execution-1",
        profile_id="profile-1",
        hermes_profile_key="ally-a",
        model="gpt-5.6-luna",
        conversation_id=conversation_id,
        session_id=session_id,
        stream_id="stream-1",
        lease_id="lease-1",
        lease_token="lease-token",
        expires_at=None,
        payload=payload,
        claim_id="claim-1",
    )


@dataclass
class RecordingFoundry:
    dispatch_losses: int = 0

    def __post_init__(self):
        self.events = []
        self.binds = []
        self.completes = []
        self.failures = []
        self.stops = []

    async def event(self, attempt_id, lease_token, **body):
        self.events.append(body)
        if body["event_type"] == "execution.dispatched" and self.dispatch_losses:
            self.dispatch_losses -= 1
            raise ResponseLossError()
        return EventReceipt(body["event_id"], body["sequence"])

    async def bind(self, attempt_id, lease_token, **body):
        self.binds.append(body)
        return SessionReceipt(body["effective_session_id"])

    async def complete(self, attempt_id, lease_token, **body):
        self.completes.append(body)
        return TerminalReceipt(attempt_id, "succeeded", "complete-1")

    async def fail(self, attempt_id, lease_token, **body):
        self.failures.append(body)
        return TerminalReceipt(attempt_id, "failed", "failure-1")

    async def stopped(self, attempt_id, lease_token, *, reason):
        self.stops.append(reason)
        return StoppedReceipt(attempt_id, "failed", False)

    async def renew(self, attempt_id, lease_token):
        raise AssertionError("short tests must not renew")


class RecordingHermes:
    def __init__(self, *, failure: Exception | None = None):
        self.failure = failure
        self.ensured = []
        self.streams = []
        self.history_checks = []

    async def ensure_profile_session(self, profile_key, session_id, *, model):
        self.ensured.append((profile_key, session_id, model))

    async def profile_session_matches_markers(
        self, profile_key, session_id, expected, forbidden
    ):
        self.history_checks.append((profile_key, session_id, expected, forbidden))
        return True

    async def stream_profile_incremental(
        self, profile_key, session_id, message, *, session_key
    ):
        self.streams.append((profile_key, session_id, message, session_key))
        if self.failure:
            raise self.failure

        async def events():
            yield HermesEvent(
                "message.delta",
                profile_key,
                session_id,
                "run-1",
                1,
                {"text": "hello"},
            )
            yield HermesEvent(
                "execution.completed",
                profile_key,
                "rotated-1",
                "run-1",
                2,
                {"run_id": "run-1", "status": "completed"},
            )

        return CancellableHermesStream(events())


@pytest.mark.asyncio
async def test_first_turn_dispatches_once_binds_terminal_session_and_completes():
    foundry = RecordingFoundry(dispatch_losses=1)
    hermes = RecordingHermes()
    result = await FoundryWorker(foundry, hermes).run_claim(
        replace(claim(), conversation_id="cloud-1")
    )

    assert result.status == "succeeded"
    assert [event["event_type"] for event in foundry.events] == [
        "execution.dispatched",
        "execution.dispatched",
        "message.delta",
    ]
    assert [event["sequence"] for event in foundry.events] == [1, 1, 2]
    assert len(hermes.ensured) == 1
    assert len(hermes.streams) == 1
    assert foundry.binds == [
        {
            "cloud_conversation_ref": "cloud-1",
            "expected_session_id": None,
            "effective_session_id": "rotated-1",
        }
    ]
    assert foundry.completes[0]["sequence"] == 3
    assert foundry.completes[0]["payload"] == {
        "run_id": "run-1",
        "status": "completed",
    }


@pytest.mark.asyncio
async def test_proof_hold_keeps_stream_open_until_generation_fence():
    class FencingFoundry(RecordingFoundry):
        async def renew(self, attempt_id, lease_token):
            raise FencedError("retired generation")

    foundry = FencingFoundry()
    proof_claim = claim()
    proof_claim.payload["proof_hold_after_first_safe_event"] = True

    result = await FoundryWorker(
        foundry,
        RecordingHermes(),
        renew_interval=0.01,
        lease_seconds=1,
        stop_safety_margin=0.1,
    ).run_claim(proof_claim)

    assert result == StoppedReceipt("attempt-1", "failed", False)
    assert [event["event_type"] for event in foundry.events] == [
        "execution.dispatched",
        "message.delta",
    ]
    assert foundry.binds == []
    assert foundry.completes == []
    assert foundry.stops == ["lease_lost"]


@pytest.mark.asyncio
async def test_bound_turn_resumes_claimed_session_without_creating_one():
    foundry = RecordingFoundry()
    hermes = RecordingHermes()
    await FoundryWorker(foundry, hermes).run_claim(
        claim(conversation_id="cloud-1", session_id="session-1")
    )

    assert hermes.ensured == []
    assert hermes.streams[0][1] == "session-1"
    assert foundry.binds[0]["expected_session_id"] == "session-1"


@pytest.mark.asyncio
async def test_proof_turn_verifies_persisted_history_and_records_receipt():
    foundry = RecordingFoundry()
    hermes = RecordingHermes()
    proof_claim = claim(conversation_id="cloud-1", session_id="session-1")
    proof_claim.payload["proof_expected_history_marker"] = "copper lighthouse"
    proof_claim.payload["proof_forbidden_history_marker"] = "blue orchard"

    result = await FoundryWorker(foundry, hermes).run_claim(proof_claim)

    assert result.status == "succeeded"
    assert hermes.history_checks == [
        ("ally-a", "session-1", "copper lighthouse", "blue orchard")
    ]
    assert foundry.completes[0]["receipt"] == {
        "code": "ok",
        "history_verified": True,
    }


@pytest.mark.asyncio
async def test_proof_turn_fails_with_distinct_code_when_history_is_missing():
    class MissingHistoryHermes(RecordingHermes):
        async def profile_session_matches_markers(
            self, profile_key, session_id, expected, forbidden
        ):
            return False

    foundry = RecordingFoundry()
    proof_claim = claim(conversation_id="cloud-1", session_id="session-1")
    proof_claim.payload["proof_expected_history_marker"] = "copper lighthouse"
    proof_claim.payload["proof_forbidden_history_marker"] = "blue orchard"

    result = await FoundryWorker(foundry, MissingHistoryHermes()).run_claim(proof_claim)

    assert result.status == "failed"
    assert foundry.failures[0]["code"] == "history_continuity_failed"


@pytest.mark.asyncio
async def test_post_dispatch_stream_failure_is_terminal_and_not_retryable():
    foundry = RecordingFoundry()
    hermes = RecordingHermes(failure=HermesMalformedResponse())
    result = await FoundryWorker(foundry, hermes).run_claim(
        claim(conversation_id="cloud-1", session_id="session-1")
    )

    assert result.status == "failed"
    assert len(hermes.streams) == 1
    assert foundry.completes == []
    assert foundry.failures[0]["retryable"] is False
    assert foundry.failures[0]["sequence"] == 2
    assert foundry.stops == []


@pytest.mark.asyncio
async def test_ambiguous_dispatch_does_not_contact_hermes():
    foundry = RecordingFoundry(dispatch_losses=2)
    hermes = RecordingHermes()
    result = await FoundryWorker(foundry, hermes).run_claim(claim())

    assert result.state == "failed"
    assert hermes.ensured == []
    assert hermes.streams == []
    assert foundry.stops == ["dispatch_response_lost"]


@pytest.mark.asyncio
async def test_bound_turn_rejects_conflicting_conversation_before_dispatch():
    foundry = RecordingFoundry()
    hermes = RecordingHermes()
    conflicting = replace(
        claim(conversation_id="cloud-1", session_id="session-1"),
        payload={"message": "hello", "cloud_conversation_ref": "cloud-other"},
    )

    result = await FoundryWorker(foundry, hermes).run_claim(conflicting)

    assert result.status == "failed"
    assert foundry.events == []
    assert foundry.failures[0]["sequence"] == 1
    assert hermes.streams == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        None,
        "",
        {"text": "wrong"},
        "x" * (MAX_MESSAGE_BYTES + 1),
        "é" * (MAX_MESSAGE_BYTES // 2 + 1),
    ],
    ids=["none", "empty", "mapping", "oversized-ascii", "oversized-multibyte"],
)
async def test_execution_message_must_be_a_bounded_string(message):
    foundry = RecordingFoundry()
    hermes = RecordingHermes()
    invalid = replace(
        claim(), payload={"message": message, "cloud_conversation_ref": "cloud-1"}
    )

    result = await FoundryWorker(foundry, hermes).run_claim(invalid)

    assert result.status == "failed"
    assert foundry.events == []
    assert hermes.streams == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "conversation", [None, "", "x" * 256], ids=["none", "empty", "oversized"]
)
async def test_first_turn_requires_a_bounded_conversation_reference(conversation):
    foundry = RecordingFoundry()
    hermes = RecordingHermes()
    invalid = replace(
        claim(),
        payload={"message": "hello", "cloud_conversation_ref": conversation},
    )

    result = await FoundryWorker(foundry, hermes).run_claim(invalid)

    assert result.status == "failed"
    assert foundry.events == []
    assert hermes.streams == []


@pytest.mark.asyncio
@pytest.mark.parametrize("events", [[object()], ["terminal", "late"]])
async def test_worker_rejects_malformed_or_post_terminal_adapter_events(events):
    class Adapter(RecordingHermes):
        async def stream_profile_incremental(
            self, profile_key, session_id, message, *, session_key
        ):
            async def rows():
                for value in events:
                    if value == "terminal":
                        yield HermesEvent(
                            "execution.completed",
                            profile_key,
                            session_id,
                            "run-1",
                            1,
                            {"run_id": "run-1", "status": "completed"},
                        )
                    elif value == "late":
                        yield HermesEvent(
                            "message.delta",
                            profile_key,
                            session_id,
                            "run-1",
                            2,
                            {"text": "late"},
                        )
                    else:
                        yield value

            return CancellableHermesStream(rows())

    foundry = RecordingFoundry()
    result = await FoundryWorker(foundry, Adapter()).run_claim(
        claim(conversation_id="cloud-1", session_id="session-1")
    )

    assert result.status == "failed"
    assert foundry.completes == []


@pytest.mark.asyncio
async def test_unbound_turn_fails_if_session_operations_are_unavailable():
    class StreamOnlyHermes:
        async def stream_profile_incremental(self, *_args, **_kwargs):
            raise AssertionError("stream must not open without session operations")

    foundry = RecordingFoundry()
    result = await FoundryWorker(foundry, StreamOnlyHermes()).run_claim(claim())

    assert result.status == "failed"
    assert [event["event_type"] for event in foundry.events] == ["execution.dispatched"]
