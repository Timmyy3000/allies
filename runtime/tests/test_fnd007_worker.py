from __future__ import annotations

import json
from dataclasses import dataclass, replace

import pytest

from allies_runtime.errors import (
    HermesDisconnected,
    HermesMalformedResponse,
    HermesTimeout,
)
from allies_runtime.foundry import (
    MAX_ROUTINE_TEXT_BYTES,
    EventReceipt,
    FencedError,
    FoundryClaim,
    FoundryWorker,
    ResponseLossError,
    SessionReceipt,
    StoppedReceipt,
    TerminalReceipt,
    _routine_references,
)
from allies_runtime.hermes import (
    MAX_MESSAGE_BYTES,
    CancellableHermesStream,
    HermesEvent,
    _IncrementalHTTPStream,
)


def claim(
    *,
    conversation_id: str | None = None,
    session_id: str | None = None,
    bootstrap: dict | None = None,
    routine_id: str | None = None,
    approval: dict | None = None,
    reasoning_effort: str | None = None,
):
    if routine_id is None:
        payload = {"message": "hello"}
        if conversation_id is None:
            payload["cloud_conversation_ref"] = "cloud-1"
    else:
        payload = {
            "execution_prompt": "routine hello",
            "run_conversation_id": "routine-conversation",
        }
    if bootstrap is not None:
        payload["bootstrap"] = bootstrap
    if approval is not None:
        payload["routine_approval"] = approval
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
        routine_id=routine_id,
        reasoning_effort=reasoning_effort,
    )


@dataclass
class RecordingFoundry:
    dispatch_losses: int = 0
    order: list | None = None

    def __post_init__(self):
        self.events = []
        self.binds = []
        self.routine_binds = []
        self.completes = []
        self.routine_results = []
        self.failures = []
        self.stops = []

    async def event(self, attempt_id, lease_token, **body):
        if self.order is not None:
            self.order.append("foundry.event")
        self.events.append(body)
        if body["event_type"] == "execution.dispatched" and self.dispatch_losses:
            self.dispatch_losses -= 1
            raise ResponseLossError()
        return EventReceipt(body["event_id"], body["sequence"])

    async def bind(self, attempt_id, lease_token, **body):
        self.binds.append(body)
        return SessionReceipt(body["effective_session_id"])

    async def bind_routine(self, attempt_id, lease_token, **body):
        self.routine_binds.append(body)
        return SessionReceipt(body["effective_session_id"])

    async def complete(self, attempt_id, lease_token, **body):
        self.completes.append(body)
        return TerminalReceipt(attempt_id, "succeeded", "complete-1")

    async def routine_result(self, attempt_id, lease_token, **body):
        self.routine_results.append(body)
        status = "failed" if body["outcome"] == "failed" else "succeeded"
        return TerminalReceipt(attempt_id, status, "routine-result-1")

    async def fail(self, attempt_id, lease_token, **body):
        self.failures.append(body)
        return TerminalReceipt(attempt_id, "failed", "failure-1")

    async def stopped(self, attempt_id, lease_token, *, reason):
        self.stops.append(reason)
        return StoppedReceipt(attempt_id, "failed", False)

    async def renew(self, attempt_id, lease_token):
        raise AssertionError("short tests must not renew")


class RecordingHermes:
    def __init__(
        self,
        *,
        failure: Exception | None = None,
        ensure_failures: list[Exception] | None = None,
        bootstrap_failures: list[Exception] | None = None,
        routine_outcome: str | None = None,
        routine_references: object | None = None,
        routine_text_chunks: list[str] | None = None,
        order: list | None = None,
    ):
        self.failure = failure
        self.ensure_failures = list(ensure_failures or [])
        self.bootstrap_failures = list(bootstrap_failures or [])
        self.routine_outcome = routine_outcome
        self.routine_references = routine_references
        self.routine_text_chunks = routine_text_chunks or ["hello"]
        self.order = order
        self.ensured = []
        self.bootstraps = []
        self.streams = []
        self.reasoning_efforts = []
        self.routine_result_flags = []
        self.history_checks = []

    async def ensure_profile_session(self, profile_key, session_id, *, model):
        if self.order is not None:
            self.order.append("hermes.ensure")
        self.ensured.append((profile_key, session_id, model))
        if self.ensure_failures:
            raise self.ensure_failures.pop(0)

    async def bootstrap_session(self, profile_key, session_id, bootstrap):
        if self.order is not None:
            self.order.append("hermes.bootstrap")
        self.bootstraps.append((profile_key, session_id, bootstrap))
        if self.bootstrap_failures:
            raise self.bootstrap_failures.pop(0)
        return {"status": "created"}

    async def profile_session_matches_markers(
        self, profile_key, session_id, expected, forbidden
    ):
        self.history_checks.append((profile_key, session_id, expected, forbidden))
        return True

    async def stream_profile_incremental(
        self,
        profile_key,
        session_id,
        message,
        *,
        session_key,
        reasoning_effort=None,
        routine_result=False,
    ):
        if self.order is not None:
            self.order.append("hermes.stream")
        self.streams.append((profile_key, session_id, message, session_key))
        self.reasoning_efforts.append(reasoning_effort)
        self.routine_result_flags.append(routine_result)
        if self.failure:
            raise self.failure

        if routine_result:
            text = "".join(self.routine_text_chunks)
            messages = [{"role": "assistant", "content": text}]
            if self.routine_outcome is not None:
                call_id = "call-routine-result"
                arguments = json.dumps(
                    {
                        "outcome": self.routine_outcome,
                        "text": text,
                        "references": (
                            []
                            if self.routine_references is None
                            else self.routine_references
                        ),
                    },
                    separators=(",", ":"),
                )
                messages.extend(
                    [
                        {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": "allies_routine_result",
                                        "arguments": arguments,
                                    },
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": '{"status":"accepted"}',
                        },
                    ]
                )
            rows = [
                b"event: run.started\n",
                b'data: {"session_id":"%s","run_id":"run-1"}\n' % session_id.encode(),
                b"\n",
            ]

            def _data(payload):
                return (
                    b"data: "
                    + json.dumps(payload, separators=(",", ":")).encode()
                    + b"\n"
                )

            for chunk in self.routine_text_chunks:
                rows.extend(
                    [
                        b"event: assistant.delta\n",
                        _data(
                            {
                                "session_id": session_id,
                                "run_id": "run-1",
                                "delta": chunk,
                            }
                        ),
                        b"\n",
                    ]
                )
            rows.extend(
                [
                    b"event: run.completed\n",
                    _data(
                        {
                            "session_id": "rotated-1",
                            "run_id": "run-1",
                            "completed": True,
                            "messages": messages,
                        }
                    ),
                    b"\n",
                    b"event: done\n",
                    b'data: {"session_id":"rotated-1","run_id":"run-1"}\n',
                    b"\n",
                ]
            )

            class _Response:
                def __init__(self, values):
                    self._values = iter(values)

                def readline(self, _limit):
                    return next(self._values, b"")

                def close(self):
                    return None

            return CancellableHermesStream(
                _IncrementalHTTPStream(
                    _Response(rows),
                    profile_key,
                    session_id,
                    routine_result=True,
                )
            )

        async def events():
            for sequence, text in enumerate(self.routine_text_chunks, start=1):
                yield HermesEvent(
                    "message.delta",
                    profile_key,
                    session_id,
                    "run-1",
                    sequence,
                    {"text": text},
                )
            terminal_payload = {"run_id": "run-1", "status": "completed"}
            yield HermesEvent(
                "execution.completed",
                profile_key,
                "rotated-1",
                "run-1",
                len(self.routine_text_chunks) + 1,
                terminal_payload,
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
async def test_routine_claim_uses_run_conversation_and_terminal_result():
    foundry = RecordingFoundry()
    hermes = RecordingHermes(routine_outcome="changed")

    result = await FoundryWorker(foundry, hermes).run_claim(
        claim(routine_id="routine-1")
    )

    assert result.status == "succeeded"
    assert foundry.binds == []
    assert foundry.completes == []
    assert foundry.routine_binds == [
        {
            "expected_session_id": None,
            "effective_session_id": "rotated-1",
        }
    ]
    assert foundry.routine_results[0]["sequence"] == 3
    assert foundry.routine_results[0]["outcome"] == "changed"
    assert foundry.routine_results[0]["text"] == "hello"
    assert hermes.routine_result_flags == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("routine_outcome", [None, "unexpected"])
async def test_routine_claim_requires_an_explicit_valid_terminal_outcome(
    routine_outcome,
):
    foundry = RecordingFoundry()
    hermes = RecordingHermes(routine_outcome=routine_outcome)

    result = await FoundryWorker(foundry, hermes).run_claim(
        claim(routine_id="routine-1")
    )

    assert result.status == "failed"
    assert foundry.failures == []
    assert foundry.routine_results[0]["outcome"] == "failed"
    assert foundry.routine_results[0]["text"] == "Routine failed before completion."


@pytest.mark.asyncio
async def test_routine_claim_preserves_explicit_unchanged_outcome_with_text():
    foundry = RecordingFoundry()
    hermes = RecordingHermes(routine_outcome="unchanged")

    result = await FoundryWorker(foundry, hermes).run_claim(
        claim(routine_id="routine-1")
    )

    assert result.status == "succeeded"
    assert foundry.routine_results[0]["outcome"] == "unchanged"
    assert foundry.routine_results[0]["text"] == "hello"


@pytest.mark.asyncio
async def test_routine_claim_preserves_explicit_failed_outcome_from_typed_report():
    foundry = RecordingFoundry()
    hermes = RecordingHermes(routine_outcome="failed")

    result = await FoundryWorker(foundry, hermes).run_claim(
        claim(routine_id="routine-1")
    )

    assert result.status == "failed"
    assert foundry.routine_results[0]["outcome"] == "failed"
    assert foundry.routine_results[0]["text"] == "hello"


@pytest.mark.asyncio
async def test_routine_claim_rejects_oversized_text_before_consuming_terminal_event():
    foundry = RecordingFoundry()
    hermes = RecordingHermes(
        routine_outcome="changed",
        routine_text_chunks=["a" * MAX_ROUTINE_TEXT_BYTES, "overflow"],
    )

    result = await FoundryWorker(foundry, hermes).run_claim(
        claim(routine_id="routine-1")
    )

    assert result.status == "failed"
    assert foundry.routine_results[0]["outcome"] == "failed"


@pytest.mark.asyncio
async def test_routine_claim_turns_malformed_references_into_a_failed_result():
    foundry = RecordingFoundry()
    hermes = RecordingHermes(
        routine_outcome="changed",
        routine_references=[{"label": "missing url"}],
    )

    result = await FoundryWorker(foundry, hermes).run_claim(
        claim(routine_id="routine-1")
    )

    assert result.status == "failed"
    assert foundry.failures == []
    assert foundry.routine_results[0]["outcome"] == "failed"


def test_routine_reference_limits_are_measured_in_utf8_bytes():
    accepted = _routine_references(
        [{"label": "界" * 85, "url": "https://example.test/"}]
    )
    assert accepted[0]["label"] == "界" * 85

    with pytest.raises(HermesMalformedResponse):
        _routine_references([{"label": "界" * 86, "url": "https://example.test/"}])

    with pytest.raises(HermesMalformedResponse):
        _routine_references(
            [{"label": "source", "url": "https://example.test/" + "界" * 683}]
        )


def test_routine_reference_composition_is_bounded_before_submission():
    url = "https://example.test/" + "u" * (2048 - len("https://example.test/"))
    references = [{"label": "l" * 255, "url": url} for _ in range(32)]

    with pytest.raises(HermesMalformedResponse):
        _routine_references(references, text="a" * MAX_ROUTINE_TEXT_BYTES)

    with pytest.raises(HermesMalformedResponse):
        _routine_references(references + references[:1])

    with pytest.raises(HermesMalformedResponse):
        _routine_references([], text=object())


@pytest.mark.asyncio
async def test_approved_routine_without_continuation_support_fails_without_replaying_prompt():
    foundry = RecordingFoundry()
    hermes = RecordingHermes()

    result = await FoundryWorker(foundry, hermes).run_claim(
        claim(
            routine_id="routine-1",
            approval={
                "action_attempt_id": "action-1",
                "continuation": {"tool": "example"},
            },
        )
    )

    assert result.status == "failed"
    assert foundry.routine_results[0]["outcome"] == "failed"
    assert hermes.streams == []


@pytest.mark.asyncio
async def test_worker_forwards_managed_reasoning_effort_to_hermes():
    foundry = RecordingFoundry()
    hermes = RecordingHermes()

    result = await FoundryWorker(foundry, hermes).run_claim(
        claim(
            conversation_id="cloud-1", session_id="session-1", reasoning_effort="xhigh"
        )
    )

    assert result.status == "succeeded"
    assert hermes.reasoning_efforts == ["xhigh"]


@pytest.mark.asyncio
async def test_bootstrap_seeds_before_dispatch_and_streams_once():
    order = []
    foundry = RecordingFoundry(order=order)
    hermes = RecordingHermes(order=order)
    bootstrap = {
        "kind": "assistant_message",
        "message_id": "8ef84387-581e-4e6f-a31d-6fbca75d95f4",
        "text": "Hi, I'm Nova.",
    }

    result = await FoundryWorker(foundry, hermes).run_claim(claim(bootstrap=bootstrap))

    assert result.status == "succeeded"
    assert order[:4] == [
        "hermes.ensure",
        "hermes.bootstrap",
        "foundry.event",
        "hermes.stream",
    ]
    assert len(hermes.bootstraps) == 1
    assert hermes.bootstraps[0][2].message_id == bootstrap["message_id"]
    assert len(hermes.streams) == 1


@pytest.mark.asyncio
async def test_bootstrap_retries_one_ambiguous_response_with_identical_identity():
    order = []
    foundry = RecordingFoundry(order=order)
    hermes = RecordingHermes(bootstrap_failures=[HermesDisconnected()], order=order)
    bootstrap = {
        "kind": "assistant_message",
        "message_id": "8ef84387-581e-4e6f-a31d-6fbca75d95f4",
        "text": "Hi, I'm Nova.",
    }

    result = await FoundryWorker(foundry, hermes).run_claim(claim(bootstrap=bootstrap))

    assert result.status == "succeeded"
    assert len(hermes.bootstraps) == 2
    assert hermes.bootstraps[0][2] == hermes.bootstraps[1][2]
    assert len(hermes.streams) == 1


@pytest.mark.asyncio
async def test_ambiguous_session_creation_requeues_and_converges_on_reclaim():
    foundry = RecordingFoundry()
    hermes = RecordingHermes(ensure_failures=[HermesDisconnected()])
    bootstrap = {
        "kind": "assistant_message",
        "message_id": "8ef84387-581e-4e6f-a31d-6fbca75d95f4",
        "text": "Hi, I'm Nova.",
    }
    worker = FoundryWorker(foundry, hermes)

    first = await worker.run_claim(claim(bootstrap=bootstrap))
    assert first.state == "failed"
    assert foundry.stops == ["bootstrap_response_lost"]
    assert foundry.events == []
    assert hermes.bootstraps == []
    assert hermes.streams == []

    reclaimed = await worker.run_claim(claim(bootstrap=bootstrap))

    assert reclaimed.status == "succeeded"
    assert len(hermes.ensured) == 2
    assert len(hermes.bootstraps) == 1
    assert len(hermes.streams) == 1


@pytest.mark.asyncio
async def test_repeated_unknown_session_creation_never_dispatches():
    foundry = RecordingFoundry()
    hermes = RecordingHermes(ensure_failures=[HermesTimeout(), HermesDisconnected()])
    bootstrap = {
        "kind": "assistant_message",
        "message_id": "8ef84387-581e-4e6f-a31d-6fbca75d95f4",
        "text": "Hi, I'm Nova.",
    }
    worker = FoundryWorker(foundry, hermes)

    first = await worker.run_claim(claim(bootstrap=bootstrap))
    second = await worker.run_claim(claim(bootstrap=bootstrap))

    assert first.state == second.state == "failed"
    assert foundry.stops == [
        "bootstrap_response_lost",
        "bootstrap_response_lost",
    ]
    assert foundry.events == []
    assert hermes.bootstraps == []
    assert hermes.streams == []


@pytest.mark.asyncio
async def test_two_bootstrap_response_losses_requeue_before_dispatch():
    foundry = RecordingFoundry()
    hermes = RecordingHermes(bootstrap_failures=[HermesTimeout(), HermesDisconnected()])
    bootstrap = {
        "kind": "assistant_message",
        "message_id": "8ef84387-581e-4e6f-a31d-6fbca75d95f4",
        "text": "Hi, I'm Nova.",
    }

    result = await FoundryWorker(foundry, hermes).run_claim(claim(bootstrap=bootstrap))

    assert result.state == "failed"
    assert foundry.events == []
    assert foundry.stops == ["bootstrap_response_lost"]
    assert hermes.streams == []


@pytest.mark.asyncio
async def test_bootstrap_rejects_bound_session_before_any_hermes_call():
    foundry = RecordingFoundry()
    hermes = RecordingHermes()
    bootstrap = {
        "kind": "assistant_message",
        "message_id": "8ef84387-581e-4e6f-a31d-6fbca75d95f4",
        "text": "Hi, I'm Nova.",
    }

    result = await FoundryWorker(foundry, hermes).run_claim(
        claim(session_id="session-1", bootstrap=bootstrap)
    )

    assert result.status == "failed"
    assert hermes.ensured == []
    assert hermes.bootstraps == []
    assert hermes.streams == []


@pytest.mark.asyncio
async def test_bootstrap_rejects_malformed_acknowledgement_before_dispatch():
    class MalformedBootstrapHermes(RecordingHermes):
        async def bootstrap_session(self, profile_key, session_id, bootstrap):
            return {"status": "unexpected"}

    foundry = RecordingFoundry()
    hermes = MalformedBootstrapHermes()
    bootstrap = {
        "kind": "assistant_message",
        "message_id": "8ef84387-581e-4e6f-a31d-6fbca75d95f4",
        "text": "Hi, I'm Nova.",
    }

    result = await FoundryWorker(foundry, hermes).run_claim(claim(bootstrap=bootstrap))

    assert result.status == "failed"
    assert foundry.events == []
    assert hermes.streams == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bootstrap",
    [
        {},
        {"kind": "user_message", "message_id": "bad", "text": "hello"},
        {"kind": "assistant_message", "message_id": "bad", "text": "hello"},
    ],
)
async def test_bootstrap_rejects_invalid_claim_shape(bootstrap):
    foundry = RecordingFoundry()
    hermes = RecordingHermes()

    result = await FoundryWorker(foundry, hermes).run_claim(claim(bootstrap=bootstrap))

    assert result.status == "failed"
    assert foundry.events == []
    assert hermes.ensured == []


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
async def test_routine_stream_failure_reports_a_routine_failure_not_generic_attempt_failure():
    foundry = RecordingFoundry()
    hermes = RecordingHermes(failure=HermesMalformedResponse())

    result = await FoundryWorker(foundry, hermes).run_claim(
        claim(routine_id="routine-1")
    )

    assert result.status == "failed"
    assert foundry.failures == []
    assert foundry.routine_results[0]["outcome"] == "failed"
    assert foundry.routine_results[0]["sequence"] == 2


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
