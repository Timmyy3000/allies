"""Private, authenticated Hermes HTTP client used by the proof harness.

The client uses the Python standard library deliberately: the runtime image
has no framework dependency and the only state held by this process is a
bounded in-memory response.  Blocking socket work is isolated in a worker
thread and wrapped by an asyncio deadline.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import socket
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import CredentialReference, RuntimeSettings
from .errors import (
    HermesAuthenticationError,
    HermesDisconnected,
    HermesError,
    HermesMalformedResponse,
    HermesTimeout,
    HermesUnavailable,
)

_PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
MAX_RESPONSE_BYTES = 1_048_576
MAX_EVENTS = 512
MAX_STREAM_BYTES = 4 * 1_048_576
MAX_EVENT_BYTES = 256 * 1_024
DEFAULT_CREDENTIAL_SOCKET = "/run/allies-runtime/hermes-credential.sock"
MAX_CREDENTIAL_SOCKET_PATH = 100
TEST_CREDENTIAL_PREFIX = "test://fnd004/"


@dataclass(frozen=True, slots=True)
class HermesHealth:
    status: str
    readiness: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class HermesEvent:
    """One sanitized event from Hermes' session SSE stream."""

    name: str
    profile_id: str
    session_id: str
    run_id: str
    sequence: int
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class HermesStreamResult:
    profile_id: str
    session_id: str
    events: tuple[HermesEvent, ...]


class CancellableHermesStream:
    """A small async-iterator adapter with an explicit cancellation seam.

    ``HermesClient`` uses this type for incremental consumers.  Test/fake
    clients can implement the same ``__aiter__`` plus ``aclose`` contract;
    the worker never needs to know whether events came from HTTP or a fake.
    """

    def __init__(self, iterator: Any, closer: Callable[[], Any] | None = None):
        self._iterator = (
            iterator.__aiter__() if hasattr(iterator, "__aiter__") else iterator
        )
        self._closer = closer
        self._closed = False
        self._pending: asyncio.Task[Any] | None = None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._closed:
            raise StopAsyncIteration
        pending = asyncio.ensure_future(self._iterator.__anext__())
        self._pending = pending
        try:
            return await pending
        finally:
            if self._pending is pending:
                self._pending = None

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._pending is not None and not self._pending.done():
                self._pending.cancel()
                await asyncio.gather(self._pending, return_exceptions=True)
            close = getattr(self._iterator, "aclose", None)
            if callable(close):
                value = close()
                if inspect.isawaitable(value):
                    await value
        except RuntimeError:
            # An async generator can be awaiting ``__anext__`` on another
            # task.  The explicit closer still wakes/cancels the transport;
            # avoid turning cancellation into a worker failure.
            pass
        finally:
            if self._closer is not None:
                value = self._closer()
                if inspect.isawaitable(value):
                    await value

    cancel = aclose


class _IncrementalHTTPStream:
    """Read one bounded SSE event at a time from an open HTTP response."""

    def __init__(self, response: Any, profile_id: str, session_id: str):
        self.response = response
        self.profile_id = profile_id
        self.session_id = session_id
        self.current_name = "message"
        self.data_lines: list[str] = []
        self.total_bytes = 0
        self.event_bytes = 0
        self.event_count = 0
        self.done = False
        self.closed = False

    async def __anext__(self) -> HermesEvent:
        if self.closed or self.done:
            raise StopAsyncIteration
        while True:
            line = await asyncio.to_thread(self.response.readline, MAX_EVENT_BYTES + 1)
            if not line:
                if self.data_lines:
                    event = self._finish_event()
                    if event is not None:
                        return event
                raise StopAsyncIteration
            line_size = len(line)
            self.total_bytes += line_size
            self.event_bytes += line_size
            if self.total_bytes > MAX_STREAM_BYTES:
                raise HermesMalformedResponse("Hermes stream exceeded the byte limit")
            if self.event_bytes > MAX_EVENT_BYTES:
                raise HermesMalformedResponse(
                    "Hermes stream event exceeded the byte limit"
                )
            try:
                text = line.decode("utf-8").rstrip("\r\n")
            except UnicodeDecodeError as exc:
                raise HermesMalformedResponse("Hermes stream was not UTF-8") from exc
            if not text:
                event = self._finish_event()
                self.event_bytes = 0
                if event is not None:
                    return event
                if self.done:
                    raise StopAsyncIteration
                continue
            if text.startswith(":"):
                continue
            field, separator, value = text.partition(":")
            if not separator:
                continue
            value = value.removeprefix(" ")
            if field == "event":
                self.current_name = value[:64] or "message"
            elif field == "data":
                self.data_lines.append(value)

    def _finish_event(self) -> HermesEvent | None:
        raw = "\n".join(self.data_lines)
        name = self.current_name
        self.current_name = "message"
        self.data_lines = []
        if not raw:
            return None
        if raw == "[DONE]":
            self.done = True
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HermesMalformedResponse(
                "Hermes stream contained malformed JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise HermesMalformedResponse("Hermes stream event was not an object")
        payload_session = payload.get("session_id", self.session_id)
        payload_run = payload.get("run_id", "")
        sequence = payload.get("seq", self.event_count + 1)
        if not isinstance(payload_session, str) or payload_session != self.session_id:
            raise HermesMalformedResponse(
                "Hermes event session identity did not match request"
            )
        if not isinstance(payload_run, str) or not payload_run:
            raise HermesMalformedResponse("Hermes event omitted run identity")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise HermesMalformedResponse("Hermes event sequence was invalid")
        self.event_count += 1
        if self.event_count > MAX_EVENTS:
            raise HermesMalformedResponse("Hermes stream exceeded the event limit")
        return HermesEvent(
            name=name,
            profile_id=self.profile_id,
            session_id=self.session_id,
            run_id=payload_run,
            sequence=sequence,
            payload=payload,
        )

    async def aclose(self) -> None:
        self.closed = True
        close = getattr(self.response, "close", None)
        if callable(close):
            close()


CredentialResolver = Callable[[CredentialReference], str]


class UnixSocketCredentialResolver:
    """Resolve an opaque reference through a workload-local secret socket.

    The socket is supplied by the secure composition boundary.  The runtime
    sends only the opaque reference and keeps the returned credential in the
    short-lived request scope; it never reads a credential from environment
    variables, Machine config, or the durable Hermes volume.
    """

    def __init__(self, socket_path: str, *, timeout: float = 5.0) -> None:
        if (
            not isinstance(socket_path, str)
            or not socket_path.startswith("/")
            or ".." in PurePosixPath(socket_path).parts
            or len(socket_path) > MAX_CREDENTIAL_SOCKET_PATH
        ):
            raise ValueError("credential socket path must be a bounded absolute path")
        if not 0 < timeout <= 60:
            raise ValueError("credential socket timeout must be bounded")
        self.socket_path = socket_path
        self.timeout = timeout

    def __call__(self, reference: CredentialReference) -> str:
        family = getattr(socket, "AF_UNIX", None)
        if family is None:
            raise HermesAuthenticationError(
                "Hermes credential socket is unavailable on this platform"
            )
        client = socket.socket(family, socket.SOCK_STREAM)
        try:
            client.settimeout(self.timeout)
            client.connect(self.socket_path)
            client.sendall((str(reference) + "\n").encode("utf-8"))
            received = bytearray()
            value = None
            while len(received) < 4097:
                chunk = client.recv(4097 - len(received))
                if not chunk:
                    break
                received.extend(chunk)
                newline = received.find(b"\n")
                if newline >= 0:
                    value = bytes(received[: newline + 1])
                    break
            if value is None or not value or len(value) > 4096:
                raise HermesAuthenticationError(
                    "Hermes credential socket returned an incomplete credential"
                )
            try:
                text = value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HermesAuthenticationError(
                    "Hermes credential socket returned invalid data"
                ) from exc
            return text.rstrip("\r\n")
        except HermesError:
            raise
        except (OSError, TimeoutError) as exc:
            raise HermesAuthenticationError(
                "Hermes credential socket could not resolve reference"
            ) from exc
        finally:
            client.close()


def test_credential_for_reference(reference: CredentialReference) -> str:
    """Derive a non-secret proof credential for the explicitly test-only scheme."""

    value = str(reference)
    if not value.lower().startswith(TEST_CREDENTIAL_PREFIX):
        raise HermesAuthenticationError("test credential scheme is not allowed")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"allies-fnd4-proof-{digest}"


def _profile_path(profile_id: str) -> str:
    if not isinstance(profile_id, str) or not _PROFILE_ID.fullmatch(profile_id):
        raise ValueError("invalid Hermes profile id")
    return profile_id


def _session_path(session_id: str) -> str:
    if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
        raise ValueError("invalid Hermes session id")
    return session_id


def _classify_http_error(error: HTTPError) -> HermesError:
    if error.code in (401, 403):
        return HermesAuthenticationError("Hermes authentication was rejected")
    if error.code in (408, 429, 500, 502, 503, 504):
        return HermesUnavailable("Hermes is unavailable")
    return HermesError("Hermes request was rejected")


def _read_bounded(stream: Any, *, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    body = stream.read(limit + 1)
    if len(body) > limit:
        raise HermesMalformedResponse("Hermes response exceeded the bounded limit")
    return body


def _decode_json(body: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HermesMalformedResponse("Hermes returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise HermesMalformedResponse("Hermes returned a non-object response")
    return value


def _sse_events(lines: Iterable[bytes]) -> list[tuple[str, Mapping[str, Any]]]:
    """Parse a bounded SSE body without retaining raw response text."""

    events: list[tuple[str, Mapping[str, Any]]] = []
    current_name = "message"
    data_lines: list[str] = []
    total_bytes = 0
    event_bytes = 0
    for line in lines:
        line_size = len(line)
        total_bytes += line_size
        if total_bytes > MAX_STREAM_BYTES:
            raise HermesMalformedResponse("Hermes stream exceeded the byte limit")
        event_bytes += line_size
        if event_bytes > MAX_EVENT_BYTES:
            raise HermesMalformedResponse("Hermes stream event exceeded the byte limit")
        try:
            text = line.decode("utf-8").rstrip("\r\n")
        except UnicodeDecodeError as exc:
            raise HermesMalformedResponse("Hermes stream was not UTF-8") from exc
        if not text:
            if data_lines:
                raw = "\n".join(data_lines)
                if raw != "[DONE]":
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        raise HermesMalformedResponse(
                            "Hermes stream contained malformed JSON"
                        ) from exc
                    if not isinstance(payload, dict):
                        raise HermesMalformedResponse(
                            "Hermes stream event was not an object"
                        )
                    events.append((current_name, payload))
                    if len(events) > MAX_EVENTS:
                        raise HermesMalformedResponse(
                            "Hermes stream exceeded the event limit"
                        )
                current_name = "message"
                data_lines = []
            event_bytes = 0
            continue
        if text.startswith(":"):
            continue
        field, separator, value = text.partition(":")
        if not separator:
            continue
        value = value.removeprefix(" ")
        if field == "event":
            current_name = value[:64] or "message"
        elif field == "data":
            data_lines.append(value)
    if data_lines:
        # Servers are allowed to close without a final blank line.
        raw = "\n".join(data_lines)
        if raw and raw != "[DONE]":
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise HermesMalformedResponse(
                    "Hermes stream contained malformed JSON"
                ) from exc
            if not isinstance(payload, dict):
                raise HermesMalformedResponse("Hermes stream event was not an object")
            events.append((current_name, payload))
            if len(events) > MAX_EVENTS:
                raise HermesMalformedResponse("Hermes stream exceeded the event limit")
    return events


def _bounded_lines(stream: Any) -> Iterable[bytes]:
    """Read socket-backed SSE lines with a hard allocation limit.

    ``HTTPResponse.__iter__`` uses an unbounded ``readline()``.  Calling it
    with an explicit size ensures a malformed peer cannot allocate a giant
    line before ``_sse_events`` sees it.
    """

    readline = getattr(stream, "readline", None)
    if not callable(readline):
        yield from stream
        return
    while True:
        line = readline(MAX_EVENT_BYTES + 1)
        if not line:
            return
        yield line


class HermesClient:
    """Authenticated loopback client for Hermes health and session streams."""

    def __init__(
        self, settings: RuntimeSettings, credential_resolver: CredentialResolver
    ) -> None:
        self.settings = settings
        self._credential_resolver = credential_resolver

    async def _credential(self) -> str:
        try:
            value = self._credential_resolver(self.settings.credential_ref)
            if inspect.isawaitable(value):
                value = await value
        except HermesError:
            raise
        except Exception as exc:
            raise HermesAuthenticationError(
                "Hermes credential resolution failed"
            ) from exc
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 4096
            or any(character in value for character in "\r\n")
        ):
            raise HermesAuthenticationError(
                "Hermes credential resolution returned no credential"
            )
        return value

    def _url(self, path: str) -> str:
        return f"{self.settings.hermes_origin}{path}"

    def _request(
        self, *, method: str, path: str, token: str, body: bytes | None = None
    ) -> Any:
        request = Request(
            self._url(path),
            data=body,
            method=method,
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json" if body is not None else "",
            },
        )
        try:
            return urlopen(request, timeout=self.settings.request_timeout)
        except HTTPError as exc:
            raise _classify_http_error(exc) from None
        except TimeoutError as exc:
            raise HermesTimeout("Hermes request timed out") from exc
        except (URLError, OSError) as exc:
            # Do not preserve the provider message; it can contain a URL or
            # request headers from a lower-level exception.
            raise HermesDisconnected("Hermes connection failed") from exc

    async def health(self) -> HermesHealth:
        try:
            token = await asyncio.wait_for(
                self._credential(), self.settings.request_timeout
            )
        except TimeoutError as exc:
            raise HermesTimeout("Hermes credential resolution timed out") from exc

        def read_health() -> HermesHealth:
            response = None
            try:
                response = self._request(
                    method="GET", path="/health/detailed", token=token
                )
                payload = _decode_json(_read_bounded(response))
                status = payload.get("status")
                if not isinstance(status, str):
                    raise HermesMalformedResponse(
                        "Hermes health response omitted status"
                    )
                readiness = payload.get("readiness", {})
                if not isinstance(readiness, dict):
                    raise HermesMalformedResponse(
                        "Hermes health response omitted readiness"
                    )
                return HermesHealth(status=status, readiness=readiness)
            finally:
                if response is not None:
                    response.close()

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(read_health), self.settings.request_timeout
            )
        except TimeoutError as exc:
            raise HermesTimeout("Hermes health timed out") from exc

    async def stream(
        self,
        profile_id: str,
        session_id: str,
        message: str,
    ) -> HermesStreamResult:
        """Run one profile-scoped SSE turn with bounded response handling."""

        profile_id = _profile_path(profile_id)
        session_id = _session_path(session_id)
        if not isinstance(message, str) or not message or len(message) > 16_384:
            raise ValueError("Hermes stream message must be a bounded non-empty string")
        try:
            token = await asyncio.wait_for(
                self._credential(), self.settings.stream_timeout
            )
        except TimeoutError as exc:
            raise HermesTimeout("Hermes credential resolution timed out") from exc
        path = f"/p/{profile_id}/api/sessions/{session_id}/chat/stream"
        body = json.dumps({"message": message}, separators=(",", ":")).encode("utf-8")

        def read_stream() -> HermesStreamResult:
            response = None
            try:
                response = self._request(
                    method="POST", path=path, token=token, body=body
                )
                event_rows = _sse_events(_bounded_lines(response))
                events: list[HermesEvent] = []
                for name, payload in event_rows:
                    payload_session = payload.get("session_id", session_id)
                    payload_run = payload.get("run_id", "")
                    sequence = payload.get("seq", len(events) + 1)
                    if (
                        not isinstance(payload_session, str)
                        or payload_session != session_id
                    ):
                        raise HermesMalformedResponse(
                            "Hermes event session identity did not match request"
                        )
                    if not isinstance(payload_run, str) or not payload_run:
                        raise HermesMalformedResponse(
                            "Hermes event omitted run identity"
                        )
                    if (
                        isinstance(sequence, bool)
                        or not isinstance(sequence, int)
                        or sequence < 1
                    ):
                        raise HermesMalformedResponse(
                            "Hermes event sequence was invalid"
                        )
                    events.append(
                        HermesEvent(
                            name=name,
                            profile_id=profile_id,
                            session_id=session_id,
                            run_id=payload_run,
                            sequence=sequence,
                            payload=payload,
                        )
                    )
                if not events:
                    raise HermesMalformedResponse("Hermes stream returned no events")
                return HermesStreamResult(
                    profile_id=profile_id, session_id=session_id, events=tuple(events)
                )
            except HermesError:
                raise
            except TimeoutError as exc:
                raise HermesTimeout("Hermes stream timed out") from exc
            except (URLError, OSError, ConnectionError) as exc:
                raise HermesDisconnected("Hermes stream disconnected") from exc
            finally:
                if response is not None:
                    response.close()

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(read_stream), self.settings.stream_timeout
            )
        except TimeoutError as exc:
            raise HermesTimeout("Hermes stream timed out") from exc

    # Explicit names used by the runtime contract and convenient aliases for
    # callers that prefer verb-based methods.
    async def health_detailed(self) -> HermesHealth:
        return await self.health()

    async def stream_profile(
        self, profile_id: str, session_id: str, message: str
    ) -> HermesStreamResult:
        return await self.stream(profile_id, session_id, message)

    async def stream_profile_incremental(
        self, profile_id: str, session_id: str, message: str
    ) -> CancellableHermesStream:
        """Open an SSE response and yield events without buffering the body."""

        profile_id = _profile_path(profile_id)
        session_id = _session_path(session_id)
        if not isinstance(message, str) or not message or len(message) > 16_384:
            raise ValueError("Hermes stream message must be a bounded non-empty string")
        try:
            token = await asyncio.wait_for(
                self._credential(), self.settings.stream_timeout
            )
            path = f"/p/{profile_id}/api/sessions/{session_id}/chat/stream"
            body = json.dumps({"message": message}, separators=(",", ":")).encode(
                "utf-8"
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._request, method="POST", path=path, token=token, body=body
                ),
                self.settings.stream_timeout,
            )
        except TimeoutError as exc:
            raise HermesTimeout("Hermes stream timed out") from exc
        except HermesError:
            raise
        except (URLError, OSError, ConnectionError) as exc:
            raise HermesDisconnected("Hermes stream disconnected") from exc
        if not callable(getattr(response, "readline", None)):
            response.close()
            raise HermesMalformedResponse(
                "Hermes stream did not expose incremental reads"
            )
        return CancellableHermesStream(
            _IncrementalHTTPStream(response, profile_id, session_id)
        )


__all__ = [
    "DEFAULT_CREDENTIAL_SOCKET",
    "TEST_CREDENTIAL_PREFIX",
    "CancellableHermesStream",
    "CredentialResolver",
    "HermesClient",
    "HermesEvent",
    "HermesHealth",
    "HermesStreamResult",
    "UnixSocketCredentialResolver",
    "test_credential_for_reference",
]
