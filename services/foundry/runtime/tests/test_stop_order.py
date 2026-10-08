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
