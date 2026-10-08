import pytest
from test_fnd007_worker import RecordingFoundry, RecordingHermes, claim

from allies_runtime.foundry import FoundryWorker, LeaseConflictError
from allies_runtime.hermes import CancellableHermesStream, HermesEvent


@pytest.mark.asyncio
async def test_user_stop_closes_hermes_before_acknowledgement():
    order = []

    async def rows():
        try:
            for sequence in (1, 2):
                yield HermesEvent(
                    "message.delta",
                    "ally-a",
                    "session-1",
                    "run-1",
                    sequence,
                    {"text": "partial"},
                )
        finally:
            order.append("hermes_closed")

    class Foundry(RecordingFoundry):
        async def event(self, attempt_id, lease_token, **body):
            if body["event_type"] == "message.delta":
                raise LeaseConflictError("user stop")
            return await super().event(attempt_id, lease_token, **body)

        async def stopped(self, attempt_id, lease_token, *, reason):
            order.append("stopped_acknowledged")
            return await super().stopped(attempt_id, lease_token, reason=reason)

    class Hermes(RecordingHermes):
        async def stream_profile_incremental(
            self, profile_key, session_id, message, *, session_key
        ):
            return CancellableHermesStream(rows())

    await FoundryWorker(Foundry(), Hermes()).run_claim(
        claim(conversation_id="cloud-1", session_id="session-1")
    )
    assert order == ["hermes_closed", "stopped_acknowledged"]


@pytest.mark.asyncio
async def test_renewal_waits_for_slow_producer_close_before_stopped():
    import asyncio

    order = []
    reading = asyncio.Event()
    closing = asyncio.Event()
    finish_close = asyncio.Event()

    async def rows():
        yield HermesEvent(
            "message.delta", "ally-a", "session-1", "run-1", 1, {"text": "partial"}
        )
        reading.set()
        await asyncio.Event().wait()

    async def close():
        closing.set()
        await finish_close.wait()
        order.append("producer_closed")

    class Foundry(RecordingFoundry):
        async def renew(self, attempt_id, lease_token):
            await reading.wait()
            raise LeaseConflictError("user stop")

        async def stopped(self, attempt_id, lease_token, *, reason):
            order.append("stopped_acknowledged")
            return await super().stopped(attempt_id, lease_token, reason=reason)

    class Hermes(RecordingHermes):
        async def stream_profile_incremental(
            self, profile_key, session_id, message, *, session_key
        ):
            return CancellableHermesStream(rows(), closer=close)

    worker = FoundryWorker(Foundry(), Hermes(), renew_interval=0.001)
    running = asyncio.create_task(
        worker.run_claim(claim(conversation_id="cloud-1", session_id="session-1"))
    )
    try:
        await asyncio.wait_for(closing.wait(), 1)
        for _ in range(5):
            await asyncio.sleep(0)
    finally:
        finish_close.set()
        await asyncio.wait_for(running, 1)
    assert order == ["producer_closed", "stopped_acknowledged"]


@pytest.mark.asyncio
async def test_lost_stopped_ack_does_not_keep_producer_open():
    from allies_runtime.foundry import ResponseLossError

    order = []

    async def rows():
        try:
            yield HermesEvent(
                "message.delta", "ally-a", "session-1", "run-1", 1, {"text": "partial"}
            )
        finally:
            order.append("producer_closed")

    class Foundry(RecordingFoundry):
        async def event(self, attempt_id, lease_token, **body):
            if body["event_type"] == "message.delta":
                raise LeaseConflictError("user stop")
            return await super().event(attempt_id, lease_token, **body)

        async def stopped(self, attempt_id, lease_token, *, reason):
            order.append("ack_response_lost")
            raise ResponseLossError("ack lost")

    class Hermes(RecordingHermes):
        async def stream_profile_incremental(
            self, profile_key, session_id, message, *, session_key
        ):
            return CancellableHermesStream(rows())

    result = await FoundryWorker(Foundry(), Hermes()).run_claim(
        claim(conversation_id="cloud-1", session_id="session-1")
    )
    assert result is None
    assert order == ["producer_closed", "ack_response_lost"]
