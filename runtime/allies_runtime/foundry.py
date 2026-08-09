"""Outbound Foundry runtime API client and bounded worker.

The runtime deliberately keeps this module independent from Django.  The
client speaks the small ``/api/v1/runtime`` contract using an injected
transport in tests (or a standard-library HTTP transport in production).  A
worker slot owns one claim until a terminal receipt or a stopped receipt is
durably acknowledged.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from .errors import HermesError, HermesMalformedResponse
from .hermes import HermesEvent

MAX_CLAIM_SLOTS = 8
LEASE_SECONDS = 60.0
DEFAULT_RENEW_INTERVAL = 20.0
DEFAULT_STOP_SAFETY_MARGIN = 5.0


class FoundryTransport(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, Any] | None = None,
    ) -> Any: ...


class FoundryError(RuntimeError):
    """A bounded, typed Foundry response failure."""

    status = 0
    code = "FOUNDRY_ERROR"
    retryable = False

    def __init__(
        self,
        message: str = "Foundry request failed",
        *,
        status: int = 0,
        code: str | None = None,
    ):
        super().__init__(message)
        self.status = status
        if code:
            self.code = code


class InvalidCredentialError(FoundryError):
    status = 401
    code = "INVALID_CREDENTIAL"


class FencedError(FoundryError):
    status = 409
    code = "FENCED"


class NotReadyError(FoundryError):
    status = 409
    code = "NOT_READY"


class LeaseConflictError(FoundryError):
    status = 409
    code = "LEASE_CONFLICT"


class IdempotencyConflictError(FoundryError):
    status = 409
    code = "IDEMPOTENCY_CONFLICT"


class InvalidRequestError(FoundryError):
    status = 422
    code = "INVALID_REQUEST"


class RateLimitedError(FoundryError):
    status = 429
    code = "RATE_LIMITED"
    retryable = True


class ServiceUnavailableError(FoundryError):
    status = 503
    code = "SERVICE_UNAVAILABLE"
    retryable = True


class ResponseLossError(FoundryError):
    """The request may have committed but its response was lost.

    Callers must retry with the same claim/event/terminal identity.  The
    message intentionally contains no URL, token, or provider detail.
    """

    code = "RESPONSE_LOST"
    retryable = True


# Friendly aliases used by integrations that prefer the API terminology.
FoundryInvalidCredential = InvalidCredentialError
FoundryFenced = FencedError
FoundryNotReady = NotReadyError
FoundryLeaseConflict = LeaseConflictError
FoundryIdempotencyConflict = IdempotencyConflictError
FoundryInvalidRequest = InvalidRequestError
FoundryRateLimited = RateLimitedError
FoundryUnavailable = ServiceUnavailableError
FoundryResponseLoss = ResponseLossError


@dataclass(frozen=True, slots=True)
class FoundryClaim:
    attempt_id: str
    execution_id: str
    profile_id: str
    hermes_profile_key: str
    conversation_id: str | None
    session_id: str | None
    stream_id: str
    lease_id: str
    lease_token: str
    expires_at: datetime | str | None
    payload: Mapping[str, Any]
    claim_id: str

    def __repr__(self) -> str:  # pragma: no cover - defensive redaction
        return (
            "FoundryClaim("
            f"attempt_id={self.attempt_id!r}, "
            f"profile_id={self.profile_id!r}, lease_token=<redacted>, "
            f"claim_id={self.claim_id!r})"
        )

    @property
    def message(self) -> str:
        value = self.payload.get("message", "")
        return value if isinstance(value, str) else str(value)


@dataclass(frozen=True, slots=True)
class LeaseReceipt:
    lease_id: str
    expires_at: datetime | str | None


@dataclass(frozen=True, slots=True)
class EventReceipt:
    event_id: str
    sequence: int


@dataclass(frozen=True, slots=True)
class StoppedReceipt:
    attempt_id: str
    state: str
    requeued: bool


@dataclass(frozen=True, slots=True)
class TerminalReceipt:
    attempt_id: str
    status: str
    receipt_id: str
    requeued: bool = False
    receipt: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SessionReceipt:
    session_id: str


def deterministic_event_id(
    attempt_id: str | UUID, stream_id: str, sequence: int
) -> str:
    """Return the stable UUID used for an Attempt stream event."""

    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
        raise ValueError("event sequence must be a positive integer")
    if not isinstance(stream_id, str) or not stream_id or len(stream_id) > 255:
        raise ValueError("stream_id must be a bounded non-empty string")
    return str(
        uuid5(
            NAMESPACE_URL, f"allies-foundry:event:{attempt_id}:{stream_id}:{sequence}"
        )
    )


class UrllibFoundryTransport:
    """Small async wrapper around ``urllib`` for the runtime image."""

    def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
        if not isinstance(base_url, str) or not base_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError("Foundry base URL must be an HTTP origin")
        self.base_url = base_url.rstrip("/")
        if timeout <= 0 or timeout > 60:
            raise ValueError("Foundry timeout must be bounded")
        self.timeout = timeout

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, Any] | None = None,
    ) -> Any:
        payload = (
            None
            if body is None
            else json.dumps(body, separators=(",", ":")).encode("utf-8")
        )

        def send() -> Mapping[str, Any]:
            request = urllib.request.Request(
                f"{self.base_url}{path}",
                data=payload,
                method=method,
                headers={**headers, "Content-Type": "application/json"}
                if payload is not None
                else dict(headers),
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return {"status": response.status, "body": response.read(1_048_577)}
            except urllib.error.HTTPError as exc:
                return {"status": exc.code, "body": exc.read(1_048_577)}

        return await asyncio.to_thread(send)


def _parse_response(raw: Any) -> tuple[int, Mapping[str, Any] | None]:
    """Normalize common fake transport response shapes without leaking data."""

    if raw is None:
        return 204, None
    if isinstance(raw, tuple) and len(raw) == 2:
        status, payload = raw
        return int(status), payload if isinstance(payload, Mapping) else None
    if isinstance(raw, Mapping):
        status_value = raw.get("status", raw.get("status_code"))
        if isinstance(status_value, int):
            payload = raw.get("body", raw.get("payload"))
            if isinstance(payload, bytes):
                try:
                    payload = json.loads(payload.decode("utf-8")) if payload else None
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise InvalidRequestError(
                        "Foundry returned malformed JSON", status=int(status_value)
                    ) from exc
            return int(status_value), payload if isinstance(payload, Mapping) else None
        return 200, raw
    status = getattr(raw, "status", getattr(raw, "status_code", 200))
    payload = getattr(raw, "payload", None)
    if payload is None:
        payload = getattr(raw, "body", None)
    if payload is None and callable(getattr(raw, "json", None)):
        payload = raw.json()
    if isinstance(payload, bytes):
        try:
            payload = json.loads(payload.decode("utf-8")) if payload else None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidRequestError(
                "Foundry returned malformed JSON", status=int(status)
            ) from exc
    return int(status), payload if isinstance(payload, Mapping) else None


def _parse_datetime(value: Any) -> datetime | str | None:
    if not isinstance(value, str):
        return value if isinstance(value, datetime) else None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return value


def _error_for(status: int, payload: Mapping[str, Any] | None) -> FoundryError:
    code = str(payload.get("code", "")) if payload else ""
    message = "Foundry rejected the runtime request"
    if status == 401:
        return InvalidCredentialError(message, status=status, code="INVALID_CREDENTIAL")
    if status == 422:
        return InvalidRequestError(message, status=status, code="INVALID_REQUEST")
    if status == 429:
        return RateLimitedError(message, status=status, code=code or "RATE_LIMITED")
    if status == 503 or status >= 500:
        return ServiceUnavailableError(
            message, status=status, code=code or "SERVICE_UNAVAILABLE"
        )
    if status == 409:
        classes = {
            "FENCED": FencedError,
            "NOT_READY": NotReadyError,
            "LEASE_CONFLICT": LeaseConflictError,
            "IDEMPOTENCY_CONFLICT": IdempotencyConflictError,
        }
        cls = classes.get(code, FoundryError)
        return cls(
            message, status=status, code=code or getattr(cls, "code", "CONFLICT")
        )
    return FoundryError(message, status=status, code=code or "FOUNDRY_ERROR")


class FoundryClient:
    """Bearer-authenticated client for the internal Foundry runtime API."""

    def __init__(
        self,
        base_url: str | None = None,
        runtime_token: str | None = None,
        *,
        token: str | None = None,
        transport: FoundryTransport | Callable[..., Any] | None = None,
        timeout: float = 10.0,
    ):
        runtime_token = runtime_token if runtime_token is not None else token
        if (
            not isinstance(runtime_token, str)
            or not runtime_token
            or "\r" in runtime_token
            or "\n" in runtime_token
        ):
            raise ValueError("runtime token must be a bounded header value")
        self._runtime_token = runtime_token
        self._transport = transport or UrllibFoundryTransport(
            base_url or "http://127.0.0.1:8000", timeout=timeout
        )

    def __repr__(self) -> str:  # pragma: no cover - defensive redaction
        return "FoundryClient(<redacted-token>)"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        lease_token: str | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any] | None:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._runtime_token}",
        }
        if lease_token is not None:
            if (
                not isinstance(lease_token, str)
                or not lease_token
                or "\r" in lease_token
                or "\n" in lease_token
            ):
                raise ValueError("lease token must be a bounded header value")
            headers["X-Foundry-Lease-Token"] = lease_token
        try:
            request = getattr(self._transport, "request", self._transport)
            try:
                raw = request(method, path, headers=headers, body=body)
            except TypeError:
                # A few tiny test fakes use ``json`` or ``payload`` as the
                # keyword name.  Supporting both keeps the transport seam
                # intentionally dependency-free.
                try:
                    raw = request(method, path, headers=headers, json=body)
                except TypeError:
                    raw = request(method, path, headers, body)
            if inspect.isawaitable(raw):
                raw = await raw
            status, payload = _parse_response(raw)
        except FoundryError:
            raise
        except (TimeoutError, ConnectionError, OSError, urllib.error.URLError) as exc:
            raise ResponseLossError("Foundry response was lost") from exc
        if status == 204:
            return None
        if status < 200 or status >= 300:
            raise _error_for(status, payload)
        return payload or {}

    async def claim(
        self, available_slots: int, *, claim_id: str | UUID | None = None
    ) -> FoundryClaim | None:
        if (
            isinstance(available_slots, bool)
            or not isinstance(available_slots, int)
            or not 1 <= available_slots <= MAX_CLAIM_SLOTS
        ):
            raise ValueError("available_slots must be an integer from 1 to 8")
        claim_id = str(claim_id or uuid4())
        payload = await self._request(
            "POST",
            "/api/v1/runtime/claims",
            body={"claim_id": claim_id, "available_slots": available_slots},
        )
        if payload is None:
            return None
        required = (
            "attempt_id",
            "execution_id",
            "profile_id",
            "hermes_profile_key",
            "stream_id",
            "lease_id",
            "lease_token",
            "claim_id",
        )
        if any(key not in payload for key in required):
            raise FoundryError(
                "Foundry claim response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        return FoundryClaim(
            attempt_id=str(payload["attempt_id"]),
            execution_id=str(payload["execution_id"]),
            profile_id=str(payload["profile_id"]),
            hermes_profile_key=str(payload["hermes_profile_key"]),
            conversation_id=payload.get("conversation_id"),
            session_id=payload.get("session_id"),
            stream_id=str(payload["stream_id"]),
            lease_id=str(payload["lease_id"]),
            lease_token=str(payload["lease_token"]),
            expires_at=_parse_datetime(payload.get("expires_at")),
            payload=payload.get("payload")
            if isinstance(payload.get("payload"), Mapping)
            else {},
            claim_id=str(payload["claim_id"]),
        )

    async def renew(self, attempt_id: str | UUID, lease_token: str) -> LeaseReceipt:
        payload = await self._request(
            "POST",
            f"/api/v1/runtime/attempts/{attempt_id}/lease/renew",
            lease_token=lease_token,
        )
        if not payload or "lease_id" not in payload:
            raise FoundryError(
                "Foundry renewal response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        return LeaseReceipt(
            str(payload["lease_id"]), _parse_datetime(payload.get("expires_at"))
        )

    async def event(
        self,
        attempt_id: str | UUID,
        lease_token: str,
        *,
        stream_id: str,
        sequence: int,
        event_type: str,
        payload: Mapping[str, Any],
        event_id: str | UUID | None = None,
    ) -> EventReceipt:
        event_id = str(
            event_id or deterministic_event_id(attempt_id, stream_id, sequence)
        )
        body = {
            "event_id": event_id,
            "stream_id": stream_id,
            "sequence": sequence,
            "type": event_type,
            "payload": dict(payload),
        }
        result = await self._request(
            "POST",
            f"/api/v1/runtime/attempts/{attempt_id}/events",
            lease_token=lease_token,
            body=body,
        )
        if not result or "event_id" not in result:
            raise FoundryError(
                "Foundry event response was malformed",
                status=202,
                code="MALFORMED_RESPONSE",
            )
        return EventReceipt(
            str(result["event_id"]), int(result.get("sequence", sequence))
        )

    append_event = event

    async def bind(
        self,
        attempt_id: str | UUID,
        lease_token: str,
        *,
        cloud_conversation_ref: str,
        expected_session_id: str | None,
        effective_session_id: str,
    ) -> SessionReceipt:
        body = {
            "cloud_conversation_ref": cloud_conversation_ref,
            "expected_session_id": expected_session_id,
            "effective_session_id": effective_session_id,
        }
        result = await self._request(
            "PUT",
            f"/api/v1/runtime/attempts/{attempt_id}/session-binding",
            lease_token=lease_token,
            body=body,
        )
        if not result or "session_id" not in result:
            raise FoundryError(
                "Foundry session response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        return SessionReceipt(str(result["session_id"]))

    update_session_binding = bind

    async def stopped(
        self, attempt_id: str | UUID, lease_token: str, *, reason: str
    ) -> StoppedReceipt:
        result = await self._request(
            "POST",
            f"/api/v1/runtime/attempts/{attempt_id}/stopped",
            lease_token=lease_token,
            body={"reason": reason},
        )
        if not result or "attempt_id" not in result:
            raise FoundryError(
                "Foundry stop response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        return StoppedReceipt(
            str(result["attempt_id"]),
            str(result.get("state", "released")),
            bool(result.get("requeued", False)),
        )

    acknowledge_stopped = stopped

    async def complete(
        self, attempt_id: str | UUID, lease_token: str, *, receipt: Mapping[str, Any]
    ) -> TerminalReceipt:
        result = await self._request(
            "POST",
            f"/api/v1/runtime/attempts/{attempt_id}/complete",
            lease_token=lease_token,
            body={"receipt": dict(receipt)},
        )
        return self._terminal(result)

    complete_attempt = complete

    async def fail(
        self,
        attempt_id: str | UUID,
        lease_token: str,
        *,
        code: str,
        retryable: bool,
        receipt: Mapping[str, Any] | None = None,
    ) -> TerminalReceipt:
        body = {
            "code": code,
            "retryable": retryable,
            "receipt": dict(receipt) if receipt is not None else None,
        }
        result = await self._request(
            "POST",
            f"/api/v1/runtime/attempts/{attempt_id}/fail",
            lease_token=lease_token,
            body=body,
        )
        return self._terminal(result)

    fail_attempt = fail

    @staticmethod
    def _terminal(result: Mapping[str, Any] | None) -> TerminalReceipt:
        if not result or any(
            key not in result for key in ("attempt_id", "status", "receipt_id")
        ):
            raise FoundryError(
                "Foundry terminal response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        value = result.get("receipt")
        return TerminalReceipt(
            str(result["attempt_id"]),
            str(result["status"]),
            str(result["receipt_id"]),
            bool(result.get("requeued", False)),
            value if isinstance(value, Mapping) else None,
        )


async def _close_stream(stream: Any) -> None:
    for name in ("aclose", "close", "cancel"):
        method = getattr(stream, name, None)
        if callable(method):
            result = method()
            if inspect.isawaitable(result):
                await result
            return


async def _retry_response_loss(operation: Callable[[], Any]) -> Any:
    """Replay one idempotent operation once after a lost response.

    Event IDs and terminal request digests are deterministic, so a retry is
    safe even when the first request committed before its response vanished.
    A second loss remains ambiguous and is deliberately surfaced to the
    worker's stopped/requeue path.
    """

    try:
        result = operation()
        if inspect.isawaitable(result):
            return await result
        return result
    except ResponseLossError:
        result = operation()
        if inspect.isawaitable(result):
            return await result
        return result


async def _stream_events(
    hermes: Any, profile_id: str, session_id: str, message: str
) -> Any:
    method = getattr(hermes, "stream_profile_incremental", None)
    if callable(method):
        result = method(profile_id, session_id, message)
    else:
        result = hermes.stream_profile(profile_id, session_id, message)
    if inspect.isawaitable(result):
        result = await result
    if hasattr(result, "__aiter__"):
        return result
    events = getattr(result, "events", ())

    async def replay() -> AsyncIterator[HermesEvent]:
        for event in events:
            yield event

    return replay()


class FoundryWorker:
    """Bounded claim/stream supervisor for one runtime process."""

    def __init__(
        self,
        foundry: FoundryClient,
        hermes: Any,
        *,
        slots: int = 2,
        renew_interval: float = DEFAULT_RENEW_INTERVAL,
        lease_seconds: float = LEASE_SECONDS,
        stop_safety_margin: float = DEFAULT_STOP_SAFETY_MARGIN,
        clock: Callable[[], float] = time.monotonic,
    ):
        if (
            isinstance(slots, bool)
            or not isinstance(slots, int)
            or not 2 <= slots <= MAX_CLAIM_SLOTS
        ):
            raise ValueError("worker slots must be between 2 and 8")
        if not 0 < renew_interval < lease_seconds - stop_safety_margin:
            raise ValueError("renew interval must leave a stop safety margin")
        self.foundry = foundry
        self.hermes = hermes
        self.slots = slots
        self.renew_interval = renew_interval
        self.lease_seconds = lease_seconds
        self.stop_safety_margin = stop_safety_margin
        self._clock = clock
        self._active: set[asyncio.Task[Any]] = set()
        self._ambiguous_claims: dict[str, float] = {}
        self._stopping = False

    @property
    def active_count(self) -> int:
        return len(self._active) + len(self._ambiguous_claims)

    @property
    def ambiguous_claim_ids(self) -> tuple[str, ...]:
        return tuple(self._ambiguous_claims)

    async def stop(self) -> None:
        self._stopping = True
        tasks = tuple(self._active)
        if tasks:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._active.difference_update(tasks)

    async def run_claim(self, claim: FoundryClaim) -> Any:
        return await self._run_claim(claim)

    async def _renew_loop(
        self, claim: FoundryClaim, stream: Any, lost: asyncio.Event
    ) -> None:
        while not lost.is_set():
            await asyncio.sleep(self.renew_interval)
            try:
                await self.foundry.renew(claim.attempt_id, claim.lease_token)
            except (FoundryError, TimeoutError, OSError, ConnectionError):
                lost.set()
                await _close_stream(stream)
                return

    async def _run_claim(self, claim: FoundryClaim) -> Any:
        session_id = claim.session_id or f"runtime-{claim.profile_id}"
        stream = None
        lost = asyncio.Event()
        renewal: asyncio.Task[Any] | None = None
        stopped = False
        event_count = 0
        try:
            stream = await _stream_events(
                self.hermes, claim.hermes_profile_key, session_id, claim.message
            )
            renewal = asyncio.create_task(self._renew_loop(claim, stream, lost))
            async for event in stream:
                if lost.is_set() or stopped:
                    break
                if not isinstance(event, HermesEvent):
                    raise HermesError("Hermes returned a malformed event")
                if (
                    event.profile_id != claim.hermes_profile_key
                    or event.session_id != session_id
                ):
                    raise HermesError("Hermes event identity did not match claim")
                if lost.is_set():
                    break
                event_count += 1
                try:
                    await _retry_response_loss(
                        lambda current_event=event: self.foundry.event(
                            claim.attempt_id,
                            claim.lease_token,
                            stream_id=claim.stream_id,
                            sequence=current_event.sequence,
                            event_type=current_event.name,
                            payload=current_event.payload,
                        )
                    )
                except ResponseLossError:
                    # The event may have committed.  Do not issue a new
                    # terminal write; close Hermes and use stopped/requeue.
                    lost.set()
                    await _close_stream(stream)
                    stopped = True
                    try:
                        return await self.foundry.stopped(
                            claim.attempt_id,
                            claim.lease_token,
                            reason="event_response_lost",
                        )
                    except FoundryError:
                        return None
            if lost.is_set():
                stopped = True
                return await self.foundry.stopped(
                    claim.attempt_id, claim.lease_token, reason="lease_lost"
                )
            if event_count == 0:
                raise HermesMalformedResponse("Hermes stream returned no events")
            try:
                return await _retry_response_loss(
                    lambda: self.foundry.complete(
                        claim.attempt_id,
                        claim.lease_token,
                        receipt={"code": "ok"},
                    )
                )
            except ResponseLossError:
                # Completion may already be durable; only stopped is safe to
                # attempt after the bounded replay also loses its response.
                lost.set()
                await _close_stream(stream)
                stopped = True
                try:
                    return await self.foundry.stopped(
                        claim.attempt_id,
                        claim.lease_token,
                        reason="complete_response_lost",
                    )
                except FoundryError:
                    return None
        except asyncio.CancelledError:
            stopped = True
            await _close_stream(stream)
            try:
                return await self.foundry.stopped(
                    claim.attempt_id, claim.lease_token, reason="cancelled"
                )
            except FoundryError:
                return None
        except (FoundryError, HermesError) as exc:
            if lost.is_set() or isinstance(exc, (FencedError, LeaseConflictError)):
                stopped = True
                try:
                    return await self.foundry.stopped(
                        claim.attempt_id, claim.lease_token, reason="lease_lost"
                    )
                except FoundryError:
                    return None
            failure_code = getattr(exc, "code", "runtime_error")
            # A retryable failure is only safe after the Hermes producer has
            # stopped.  Close it before issuing the durable fail/requeue.
            if stream is not None:
                await _close_stream(stream)
            try:
                return await _retry_response_loss(
                    lambda: self.foundry.fail(
                        claim.attempt_id,
                        claim.lease_token,
                        code=failure_code,
                        retryable=True,
                        receipt={"code": failure_code},
                    )
                )
            except ResponseLossError:
                lost.set()
                await _close_stream(stream)
                try:
                    return await self.foundry.stopped(
                        claim.attempt_id,
                        claim.lease_token,
                        reason="fail_response_lost",
                    )
                except FoundryError:
                    return None
            except FoundryError:
                return None
        finally:
            if renewal is not None:
                renewal.cancel()
                await asyncio.gather(renewal, return_exceptions=True)
            if stream is not None:
                await _close_stream(stream)

    async def run(
        self,
        *,
        max_turns: int | None = None,
        idle_cycles: int = 1,
        idle_delay: float = 0.0,
    ) -> tuple[Any, ...]:
        """Poll until the requested number of turns has completed.

        ``max_turns`` is intentionally bounded for tests and one-shot jobs.
        Without it, ``idle_cycles`` controls how many empty polls end the run.
        """
        if max_turns is not None and (isinstance(max_turns, bool) or max_turns < 1):
            raise ValueError("max_turns must be positive")
        if idle_cycles < 1:
            raise ValueError("idle_cycles must be positive")
        results: list[Any] = []
        empty = 0
        poll_delay = max(idle_delay, 0.01)
        while not self._stopping and (max_turns is None or len(results) < max_turns):
            now = self._clock()
            expired = [
                claim_id
                for claim_id, started_at in self._ambiguous_claims.items()
                if now - started_at >= self.lease_seconds
            ]
            for claim_id in expired:
                self._ambiguous_claims.pop(claim_id, None)
            while (
                not self._stopping
                and len(self._active) + len(self._ambiguous_claims) < self.slots
                and (max_turns is None or len(results) + len(self._active) < max_turns)
            ):
                claim_id = next(iter(self._ambiguous_claims), None) or str(uuid4())
                try:
                    available_slots = max(
                        1, self.slots - len(self._active) - len(self._ambiguous_claims)
                    )
                    claim = await self.foundry.claim(available_slots, claim_id=claim_id)
                except ResponseLossError:
                    self._ambiguous_claims.setdefault(claim_id, self._clock())
                    break
                except (FencedError, InvalidCredentialError):
                    self._stopping = True
                    break
                except (NotReadyError, RateLimitedError, ServiceUnavailableError):
                    await asyncio.sleep(poll_delay)
                    break
                if claim_id in self._ambiguous_claims:
                    self._ambiguous_claims.pop(claim_id, None)
                if claim is None:
                    empty += 1
                    break
                task = asyncio.create_task(self._run_claim(claim))
                self._active.add(task)
                task.add_done_callback(self._active.discard)
            if self._active:
                done, _ = await asyncio.wait(
                    self._active, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    try:
                        results.append(task.result())
                    except asyncio.CancelledError:
                        results.append(None)
                    except Exception:  # noqa: BLE001 - one failed slot must not stop peers
                        results.append(None)
                self._active.difference_update(done)
                empty = 0
                continue
            if self._ambiguous_claims:
                await asyncio.sleep(poll_delay)
                continue
            if empty >= idle_cycles or self._stopping:
                break
            await asyncio.sleep(poll_delay)
        if self._active:
            done, _ = await asyncio.wait(self._active)
            for task in done:
                results.append(task.result() if not task.cancelled() else None)
        return tuple(results)


RuntimeWorker = FoundryWorker
FoundrySupervisor = FoundryWorker


__all__ = [
    "MAX_CLAIM_SLOTS",
    "EventReceipt",
    "FencedError",
    "FoundryClaim",
    "FoundryClient",
    "FoundryError",
    "FoundryFenced",
    "FoundryIdempotencyConflict",
    "FoundryInvalidCredential",
    "FoundryInvalidRequest",
    "FoundryLeaseConflict",
    "FoundryNotReady",
    "FoundryRateLimited",
    "FoundryResponseLoss",
    "FoundrySupervisor",
    "FoundryTransport",
    "FoundryUnavailable",
    "FoundryWorker",
    "IdempotencyConflictError",
    "InvalidCredentialError",
    "InvalidRequestError",
    "LeaseConflictError",
    "LeaseReceipt",
    "NotReadyError",
    "RateLimitedError",
    "ResponseLossError",
    "RuntimeWorker",
    "ServiceUnavailableError",
    "SessionReceipt",
    "StoppedReceipt",
    "TerminalReceipt",
    "UrllibFoundryTransport",
    "deterministic_event_id",
]
