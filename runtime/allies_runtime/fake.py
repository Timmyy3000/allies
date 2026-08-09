"""Deterministic Hermes substitute for local and CI proof tests."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

from .errors import (
    HermesAuthenticationError,
    HermesDisconnected,
    HermesMalformedResponse,
    HermesTimeout,
)
from .hermes import HermesEvent, HermesHealth, HermesStreamResult


@dataclass(slots=True)
class FakeProfilePlan:
    delay: float = 0.02
    failure: str | None = None
    duplicate_event: bool = False
    cross_profile: str | None = None


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


DeterministicFakeHermes = FakeHermesClient


__all__ = ["DeterministicFakeHermes", "FakeHermesClient", "FakeProfilePlan"]
