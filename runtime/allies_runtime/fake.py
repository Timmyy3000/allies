"""Deterministic Hermes substitute for local and CI proof tests."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass

from .errors import (
    HermesAuthenticationError,
    HermesDisconnected,
    HermesMalformedResponse,
    HermesTimeout,
)
from .hermes import (
    CancellableHermesStream,
    HermesEvent,
    HermesHealth,
    HermesStreamResult,
)


class FakeFoundryTransport:
    """Deterministic async transport for client/worker contract tests."""

    def __init__(self, responses=()):
        self.responses = deque(responses)
        self.calls: list[
            tuple[str, str, dict[str, str], Mapping[str, object] | None]
        ] = []

    async def request(self, method, path, *, headers, body=None):
        self.calls.append((method, path, dict(headers), body))
        if not self.responses:
            return None
        response = self.responses.popleft()
        if isinstance(response, BaseException):
            raise response
        return response

    def enqueue(self, *responses):
        self.responses.extend(responses)


@dataclass(slots=True)
class FakeProfilePlan:
    delay: float = 0.02
    failure: str | None = None
    duplicate_event: bool = False
    cross_profile: str | None = None
    event_delay: float | None = None


class FakeHermesClient:
    """In-memory client whose events are stable across test runs."""

    def __init__(
        self,
        plans: Mapping[str, FakeProfilePlan] | None = None,
        *,
        health_status: str = "ready",
    ) -> None:
        self.plans = dict(plans or {})
        self.health_status = health_status
        self.calls: list[tuple[str, str, str]] = []
        self._run_numbers: dict[str, int] = {}
        self.active_streams = 0
        self.max_active_streams = 0
        self.cancelled_streams = 0

    async def health(self) -> HermesHealth:
        if self.health_status == "auth-failed":
            raise HermesAuthenticationError("Hermes authentication was rejected")
        if self.health_status == "malformed":
            raise HermesMalformedResponse("Hermes health response was malformed")
        return HermesHealth(
            status=self.health_status, readiness={"status": self.health_status}
        )

    async def health_detailed(self) -> HermesHealth:
        return await self.health()

    async def stream_profile(
        self, profile_id: str, session_id: str, message: str
    ) -> HermesStreamResult:
        plan = self.plans.get(profile_id, FakeProfilePlan())
        self.calls.append((profile_id, session_id, message))
        await asyncio.sleep(plan.delay)
        if plan.failure == "auth":
            raise HermesAuthenticationError("Hermes authentication was rejected")
        if plan.failure == "malformed":
            raise HermesMalformedResponse("Hermes stream response was malformed")
        if plan.failure == "disconnect":
            raise HermesDisconnected("Hermes stream disconnected")
        if plan.failure == "timeout":
            raise HermesTimeout("Hermes stream timed out")
        number = self._run_numbers.get(profile_id, 0) + 1
        self._run_numbers[profile_id] = number
        run_id = f"run-{profile_id}-{number}"
        event_profile = plan.cross_profile or profile_id
        events = [
            HermesEvent(
                name="run.started",
                profile_id=event_profile,
                session_id=session_id,
                run_id=run_id,
                sequence=1,
                payload={
                    "profile_id": event_profile,
                    "session_id": session_id,
                    "run_id": run_id,
                    "seq": 1,
                },
            ),
            HermesEvent(
                name="assistant.delta",
                profile_id=event_profile,
                session_id=session_id,
                run_id=run_id,
                sequence=2,
                payload={
                    "profile_id": event_profile,
                    "session_id": session_id,
                    "run_id": run_id,
                    "seq": 2,
                    "content": f"proof:{profile_id}:{message}",
                },
            ),
            HermesEvent(
                name="run.completed",
                profile_id=event_profile,
                session_id=session_id,
                run_id=run_id,
                sequence=3,
                payload={
                    "profile_id": event_profile,
                    "session_id": session_id,
                    "run_id": run_id,
                    "seq": 3,
                },
            ),
        ]
        if plan.duplicate_event:
            events.insert(2, events[1])
        return HermesStreamResult(
            profile_id=profile_id, session_id=session_id, events=tuple(events)
        )

    async def stream_profile_incremental(
        self, profile_id: str, session_id: str, message: str
    ) -> CancellableHermesStream:
        """Yield fixture events incrementally and record cancellation."""

        plan = self.plans.get(profile_id, FakeProfilePlan())
        self.calls.append((profile_id, session_id, message))
        if plan.failure == "auth":
            raise HermesAuthenticationError("Hermes authentication was rejected")
        if plan.failure == "malformed":
            raise HermesMalformedResponse("Hermes stream response was malformed")
        if plan.failure == "disconnect":
            raise HermesDisconnected("Hermes stream disconnected")
        if plan.failure == "timeout":
            raise HermesTimeout("Hermes stream timed out")
        number = self._run_numbers.get(profile_id, 0) + 1
        self._run_numbers[profile_id] = number
        run_id = f"run-{profile_id}-{number}"
        event_profile = plan.cross_profile or profile_id
        events = (
            HermesEvent(
                name="run.started",
                profile_id=event_profile,
                session_id=session_id,
                run_id=run_id,
                sequence=1,
                payload={
                    "profile_id": event_profile,
                    "session_id": session_id,
                    "run_id": run_id,
                    "seq": 1,
                },
            ),
            HermesEvent(
                name="assistant.delta",
                profile_id=event_profile,
                session_id=session_id,
                run_id=run_id,
                sequence=2,
                payload={
                    "profile_id": event_profile,
                    "session_id": session_id,
                    "run_id": run_id,
                    "seq": 2,
                    "content": f"proof:{profile_id}:{message}",
                },
            ),
            HermesEvent(
                name="run.completed",
                profile_id=event_profile,
                session_id=session_id,
                run_id=run_id,
                sequence=3,
                payload={
                    "profile_id": event_profile,
                    "session_id": session_id,
                    "run_id": run_id,
                    "seq": 3,
                },
            ),
        )
        if plan.duplicate_event:
            events = events[:2] + (events[1],) + events[2:]
        delay = plan.event_delay if plan.event_delay is not None else plan.delay
        owner = self

        async def iterator():
            owner.active_streams += 1
            owner.max_active_streams = max(
                owner.max_active_streams, owner.active_streams
            )
            try:
                for event in events:
                    await asyncio.sleep(delay)
                    yield event
            finally:
                owner.active_streams -= 1

        async def close():
            self.cancelled_streams += 1

        return CancellableHermesStream(iterator(), close)


DeterministicFakeHermes = FakeHermesClient


__all__ = [
    "DeterministicFakeHermes",
    "FakeFoundryTransport",
    "FakeHermesClient",
    "FakeProfilePlan",
]
