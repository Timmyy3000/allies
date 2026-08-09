"""Profile-scoped proof coordination with bounded concurrency."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .errors import IdentityIsolationError
from .hermes import HermesClient, HermesEvent, HermesStreamResult

EventCallback = Callable[[HermesEvent], Any | Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ProfileProofResult:
    profile_id: str
    session_id: str
    events: tuple[HermesEvent, ...]
    waited_for_same_profile: bool
    started_at: float
    finished_at: float

    @property
    def duration(self) -> float:
        return self.finished_at - self.started_at


class ProfileProofCoordinator:
    """Run proof turns with slots and one active turn per profile."""

    def __init__(self, client: HermesClient, *, slots: int = 2) -> None:
        if slots < 2:
            raise ValueError("the proof requires at least two worker slots")
        self.client = client
        self.slots = slots
        self._slot_gate = asyncio.Semaphore(slots)
        self._profile_locks: dict[str, asyncio.Lock] = {}
        self._lock_guard = asyncio.Lock()

    async def _profile_lock(self, profile_id: str) -> asyncio.Lock:
        async with self._lock_guard:
            return self._profile_locks.setdefault(profile_id, asyncio.Lock())

    async def run_turn(
        self,
        profile_id: str,
        message: str,
        *,
        session_id: str | None = None,
        event_callback: EventCallback | None = None,
    ) -> ProfileProofResult:
        """Run one turn and retain only identity-safe event values."""

        session_id = session_id or f"proof-{profile_id}-session"
        profile_lock = await self._profile_lock(profile_id)
        same_profile_busy = profile_lock.locked()
        async with self._slot_gate, profile_lock:
            started_at = time.monotonic()
            stream: HermesStreamResult = await self.client.stream_profile(
                profile_id, session_id, message
            )
            if stream.profile_id != profile_id or stream.session_id != session_id:
                raise IdentityIsolationError(
                    "Hermes stream identity did not match the requested profile"
                )
            seen: dict[tuple[str, int], HermesEvent] = {}
            accepted: list[HermesEvent] = []
            for event in stream.events:
                if event.profile_id != profile_id or event.session_id != session_id:
                    raise IdentityIsolationError(
                        "Hermes event crossed a profile or session boundary"
                    )
                key = (event.run_id, event.sequence)
                previous = seen.get(key)
                if previous is not None:
                    if previous.payload != event.payload or previous.name != event.name:
                        raise IdentityIsolationError(
                            "Hermes replay changed an event identity"
                        )
                    # Exact replays are harmless and are not emitted twice.
                    continue
                seen[key] = event
                accepted.append(event)
                if event_callback is not None:
                    callback_result = event_callback(event)
                    if inspect.isawaitable(callback_result):
                        await callback_result
            finished_at = time.monotonic()
        return ProfileProofResult(
            profile_id=profile_id,
            session_id=session_id,
            events=tuple(accepted),
            waited_for_same_profile=same_profile_busy,
            started_at=started_at,
            finished_at=finished_at,
        )

    async def run_profiles(
        self,
        turns: Mapping[str, str],
        *,
        sessions: Mapping[str, str] | None = None,
        event_callback: EventCallback | None = None,
    ) -> tuple[ProfileProofResult, ...]:
        """Run profile turns concurrently, returning deterministic input order."""

        if not turns:
            return ()
        sessions = sessions or {}
        tasks = [
            asyncio.create_task(
                self.run_turn(
                    profile_id,
                    message,
                    session_id=sessions.get(profile_id),
                    event_callback=event_callback,
                )
            )
            for profile_id, message in turns.items()
        ]
        return tuple(await asyncio.gather(*tasks))

    async def run_same_profile_pair(
        self,
        profile_id: str,
        first_message: str = "first proof turn",
        second_message: str = "second proof turn",
        *,
        session_id: str | None = None,
    ) -> tuple[ProfileProofResult, ProfileProofResult]:
        """Convenience helper that makes same-profile waiting observable."""

        session_id = session_id or f"proof-{profile_id}-session"
        first, second = await asyncio.gather(
            self.run_turn(profile_id, first_message, session_id=session_id),
            self.run_turn(profile_id, second_message, session_id=session_id),
        )
        return first, second


__all__ = ["EventCallback", "ProfileProofCoordinator", "ProfileProofResult"]
