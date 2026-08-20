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
import time
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
    HermesSessionExists,
    HermesTimeout,
    HermesUnavailable,
)
from .observability import build_event, emit_runtime_event

_PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
MAX_RESPONSE_BYTES = 1_048_576
MAX_EVENTS = 512
MAX_BUFFERED_EVENTS = 65_536
MAX_STREAM_BYTES = 4 * 1_048_576
MAX_EVENT_BYTES = 256 * 1_024
MAX_SAFE_TEXT_BYTES = 16 * 1024
MAX_MESSAGE_BYTES = 16 * 1024
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


@dataclass(frozen=True, slots=True)
class HermesSession:
    profile_id: str
    session_id: str


@dataclass(frozen=True, slots=True)
class StableSessionIdentifiers:
    candidate_id: str
    session_key: str


def validate_stream_message(message: str) -> str:
    """Validate the one bounded UTF-8 message accepted by Hermes."""

    try:
        encoded = message.encode("utf-8")
    except (AttributeError, UnicodeError):
        raise ValueError("Hermes stream message must be bounded UTF-8 text") from None
    if not message or len(encoded) > MAX_MESSAGE_BYTES:
        raise ValueError("Hermes stream message must be bounded UTF-8 text")
    return message


def _content_contains_text(value: Any, expected: str, *, depth: int = 0) -> bool:
    if isinstance(value, str):
        return expected in value.casefold()
    if depth >= 4:
        return False
    if isinstance(value, list):
        return len(value) <= MAX_EVENTS and any(
            _content_contains_text(item, expected, depth=depth + 1) for item in value
        )
    if isinstance(value, dict) and len(value) <= 16:
        return any(
            _content_contains_text(value.get(key), expected, depth=depth + 1)
            for key in ("text", "content")
            if key in value
        )
    return False


def stable_session_identifiers(
    profile_id: str, cloud_conversation_ref: str
) -> StableSessionIdentifiers:
    """Derive opaque, operation-stable Hermes identifiers without secrets."""

    for name, value in (
        ("profile_id", profile_id),
        ("cloud_conversation_ref", cloud_conversation_ref),
    ):
        if not isinstance(value, str) or not value or len(value) > 255:
            raise ValueError(f"{name} must be a bounded non-empty string")
    source = f"{profile_id}\0{cloud_conversation_ref}".encode()
    candidate = hashlib.sha256(b"allies:hermes-session:v1\0" + source).hexdigest()
    memory = hashlib.sha256(b"allies:hermes-memory:v1\0" + source).hexdigest()
    return StableSessionIdentifiers(
        candidate_id=f"allies-s-{candidate}",
        session_key=f"allies-k-{memory}",
    )


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


class _ObservedHermesStream:
    """Add one provider lifecycle pair to an incremental Hermes stream."""

    def __init__(
        self,
        stream: CancellableHermesStream,
        on_finished: Callable[[BaseException | None], Any],
    ) -> None:
        self._stream = stream
        self._on_finished = on_finished
        self._finished = False
        self._completed = False

    def __aiter__(self):
        return self

    async def __anext__(self) -> HermesEvent:
        try:
            event = await self._stream.__anext__()
            if event.name == "execution.completed":
                self.mark_completed()
            return event
        except StopAsyncIteration:
            self._completed = True
            await self._finish(None)
            raise
        except BaseException as error:
            await self._finish(error)
            raise

    async def _finish(self, error: BaseException | None) -> None:
        if self._finished:
            return
        self._finished = True
        result = self._on_finished(error)
        if inspect.isawaitable(result):
            await result

    def mark_completed(self) -> None:
        """Mark a yielded terminal event before an eager consumer closes."""

        self._completed = True

    async def aclose(self) -> None:
        try:
            await self._stream.aclose()
        finally:
            # A consumer may close immediately after receiving the terminal
            # event, before requesting the iterator's final StopAsyncIteration.
            # Only that explicit completion marker is allowed to produce
            # success; every other early close is an interrupted operation.
            await self._finish(
                None
                if self._completed
                else HermesDisconnected("Hermes stream closed")
            )

    cancel = aclose


class _IncrementalHTTPStream:
    """Validate and normalize one bounded Hermes session stream."""

    def __init__(
        self,
        response: Any,
        profile_id: str,
        session_id: str,
        *,
        stream_timeout: float | None = None,
    ):
        if stream_timeout is not None and (
            isinstance(stream_timeout, bool) or stream_timeout <= 0
        ):
            raise ValueError("Hermes stream timeout must be positive")
        self.response = response
        self.profile_id = profile_id
        self.session_id = session_id
        self.deadline = (
            time.monotonic() + stream_timeout
            if stream_timeout is not None
            else None
        )
        self.current_name = "message"
        self.data_lines: list[str] = []
        self.total_bytes = 0
        self.event_bytes = 0
        self.event_count = 0
        self.normalized_count = 0
        self.run_id: str | None = None
        self.state = "awaiting_run"
        self.active_activities: list[tuple[str, str]] = []
        self.saw_assistant_delta = False
        self.assistant_completion_session_id: str | None = None
        self.terminal_event: HermesEvent | None = None
        self.done = False
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self) -> HermesEvent:
        if self.closed or self.done:
            raise StopAsyncIteration
        while True:
            remaining = None
            if self.deadline is not None:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    await self.aclose()
                    raise HermesTimeout("Hermes stream timed out")
            try:
                read = asyncio.to_thread(self.response.readline, MAX_EVENT_BYTES + 1)
                line = (
                    await asyncio.wait_for(read, remaining)
                    if remaining is not None
                    else await read
                )
            except TimeoutError as exc:
                await self.aclose()
                raise HermesTimeout("Hermes stream timed out") from exc
            except (OSError, ConnectionError) as exc:
                await self.aclose()
                raise HermesDisconnected("Hermes stream disconnected") from exc
            if not line:
                if self.data_lines:
                    event = self._finish_event()
                    if event is not None:
                        return event
                if self.done:
                    raise StopAsyncIteration
                raise HermesMalformedResponse("Hermes stream ended before done")
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
                if not value or len(value) > 64:
                    raise HermesMalformedResponse(
                        "Hermes stream event name was invalid"
                    )
                self.current_name = value
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
            return self._normalize_event(
                "done",
                {"session_id": self.session_id, "run_id": self.run_id},
            )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HermesMalformedResponse(
                "Hermes stream contained malformed JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise HermesMalformedResponse("Hermes stream event was not an object")
        self.event_count += 1
        return self._normalize_event(name, payload)

    def _normalize_event(
        self, name: str, payload: Mapping[str, Any]
    ) -> HermesEvent | None:
        known = {
            "run.started",
            "message.started",
            "assistant.delta",
            "tool.started",
            "tool.progress",
            "tool.completed",
            "assistant.completed",
            "run.completed",
            "error",
            "done",
        }
        if name not in known:
            raise HermesMalformedResponse("Hermes stream event type was not allowed")

        payload_run = payload.get("run_id")
        payload_session = payload.get("session_id")
        if name == "run.started":
            if self.state != "awaiting_run":
                raise HermesMalformedResponse("Hermes run started out of order")
            if not isinstance(payload_run, str) or not payload_run:
                raise HermesMalformedResponse("Hermes event omitted run identity")
            if payload_session != self.session_id:
                raise HermesMalformedResponse(
                    "Hermes event session identity did not match request"
                )
            self.run_id = payload_run
            self.state = "running"
            return None

        if self.state == "awaiting_run" or self.run_id is None:
            raise HermesMalformedResponse("Hermes event arrived before run start")
        if not isinstance(payload_run, str) or payload_run != self.run_id:
            raise HermesMalformedResponse("Hermes run identity changed")

        if name == "done":
            if self.state != "run_completed" or self.terminal_event is None:
                raise HermesMalformedResponse(
                    "Hermes stream ended before run completion"
                )
            if payload_session not in {
                self.session_id,
                self.terminal_event.session_id,
            }:
                raise HermesMalformedResponse("Hermes done identity did not match")
            self.done = True
            event = self.terminal_event
            self.terminal_event = None
            return event

        if self.state != "running":
            raise HermesMalformedResponse("Hermes event arrived after run completion")
        if name not in {"assistant.completed", "run.completed"} and (
            payload_session != self.session_id
        ):
            raise HermesMalformedResponse(
                "Hermes event session identity did not match request"
            )

        if name in {"message.started", "assistant.completed"}:
            if name == "assistant.completed" and (
                not isinstance(payload_session, str)
                or not _SESSION_ID.fullmatch(payload_session)
            ):
                raise HermesMalformedResponse(
                    "Hermes assistant completion session was invalid"
                )
            if name == "message.started" or self.saw_assistant_delta:
                if name == "assistant.completed":
                    self.assistant_completion_session_id = payload_session
                return None
            content = payload.get("content")
            if (
                not isinstance(content, str)
                or not content
                or len(content.encode("utf-8")) > MAX_SAFE_TEXT_BYTES
            ):
                raise HermesMalformedResponse(
                    "Hermes assistant completion omitted bounded text"
                )
            self.assistant_completion_session_id = payload_session
            return self._event("message.delta", self.session_id, {"text": content})
        if name == "error":
            raise HermesError("Hermes reported a turn failure")
        if name == "assistant.delta":
            delta = payload.get("delta")
            if (
                not isinstance(delta, str)
                or not delta
                or len(delta.encode("utf-8")) > MAX_SAFE_TEXT_BYTES
            ):
                raise HermesMalformedResponse("Hermes assistant delta was invalid")
            self.saw_assistant_delta = True
            return self._event("message.delta", self.session_id, {"text": delta})
        if name == "tool.started":
            tool_name = payload.get("tool_name")
            if not isinstance(tool_name, str) or not tool_name or len(tool_name) > 128:
                raise HermesMalformedResponse("Hermes tool start was invalid")
            digest = hashlib.sha256(
                f"allies:activity:v1:{self.run_id}:{self.event_count}:{tool_name}".encode()
            ).hexdigest()[:32]
            activity_id = f"activity-{digest}"
            self.active_activities.append((tool_name, activity_id))
            return self._event(
                "activity.started",
                self.session_id,
                {"activity_id": activity_id, "kind": "tool"},
            )
        if name == "tool.progress":
            tool_name = payload.get("tool_name")
            if not isinstance(tool_name, str) or not tool_name or len(tool_name) > 128:
                raise HermesMalformedResponse("Hermes tool progress was invalid")
            return None
        if name == "tool.completed":
            tool_name = payload.get("tool_name")
            match = next(
                (
                    (index, activity_id)
                    for index, (active_name, activity_id) in enumerate(
                        self.active_activities
                    )
                    if active_name == tool_name
                ),
                None,
            )
            if match is None:
                raise HermesMalformedResponse("Hermes tool completion was out of order")
            index, activity_id = match
            self.active_activities.pop(index)
            return self._event(
                "activity.completed",
                self.session_id,
                {"activity_id": activity_id, "status": "completed"},
            )
        if name == "run.completed":
            if self.active_activities or payload.get("completed") is not True:
                raise HermesMalformedResponse("Hermes run completion was invalid")
            messages = payload.get("messages")
            if (
                not isinstance(messages, list)
                or len(messages) > MAX_EVENTS
            ):
                raise HermesMalformedResponse(
                    "Hermes run completion omitted its transcript"
                )
            if not messages and self.assistant_completion_session_id != payload_session:
                raise HermesMalformedResponse(
                    "Hermes run completion omitted its transcript"
                )
            if not isinstance(payload_session, str) or not _SESSION_ID.fullmatch(
                payload_session
            ):
                raise HermesMalformedResponse("Hermes terminal session was invalid")
            self.state = "run_completed"
            self.terminal_event = self._event(
                "execution.completed",
                payload_session,
                {"run_id": self.run_id, "status": "completed"},
            )
            return None
        raise HermesMalformedResponse("Hermes stream event type was not allowed")

    def _event(
        self, name: str, session_id: str, payload: Mapping[str, Any]
    ) -> HermesEvent:
        self.normalized_count += 1
        return HermesEvent(
            name=name,
            profile_id=self.profile_id,
            session_id=session_id,
            run_id=self.run_id or "",
            sequence=self.normalized_count,
            payload=dict(payload),
        )

    async def aclose(self) -> None:
        self.closed = True
        close = getattr(self.response, "close", None)
        if callable(close):
            close()


CredentialResolver = Callable[[CredentialReference], str]
ProfileCredentialResolver = Callable[[str], str]


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


def _session_from_payload(
    payload: Mapping[str, Any], profile_id: str, expected_session_id: str
) -> HermesSession:
    session = payload.get("session")
    if not isinstance(session, dict) or session.get("id") != expected_session_id:
        raise HermesMalformedResponse("Hermes session response identity did not match")
    return HermesSession(profile_id=profile_id, session_id=expected_session_id)


def _session_key_header(session_key: str | None) -> Mapping[str, str]:
    if session_key is None:
        return {}
    if (
        not isinstance(session_key, str)
        or not session_key
        or len(session_key) > 128
        or any(character in session_key for character in "\r\n")
    ):
        raise ValueError("Hermes session key must be a bounded non-empty string")
    return {"X-Hermes-Session-Key": session_key}


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
                    if len(events) > MAX_BUFFERED_EVENTS:
                        raise HermesMalformedResponse(
                            "Hermes stream exceeded the buffered event limit"
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
            if len(events) > MAX_BUFFERED_EVENTS:
                raise HermesMalformedResponse(
                    "Hermes stream exceeded the buffered event limit"
                )
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
        self,
        settings: RuntimeSettings,
        credential_resolver: CredentialResolver,
        *,
        profile_credential_resolver: ProfileCredentialResolver | None = None,
    ) -> None:
        self.settings = settings
        self._credential_resolver = credential_resolver
        self._profile_credential_resolver = profile_credential_resolver

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

    async def _profile_credential(self, profile_id: str) -> str:
        resolver = self._profile_credential_resolver
        if resolver is None:
            return await self._credential()
        try:
            value = await asyncio.to_thread(resolver, profile_id)
            if inspect.isawaitable(value):
                value = await value
        except HermesError:
            raise
        except Exception as exc:
            raise HermesAuthenticationError(
                "Hermes profile credential resolution failed"
            ) from exc
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 4096
            or any(character in value for character in "\r\n")
        ):
            raise HermesAuthenticationError(
                "Hermes profile credential resolution returned no credential"
            )
        return value

    def _url(self, path: str) -> str:
        return f"{self.settings.hermes_origin}{path}"

    def _request(
        self,
        *,
        method: str,
        path: str,
        token: str,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        accepted_statuses: tuple[int, ...] = (),
    ) -> Any:
        request_headers = {
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json" if body is not None else "",
        }
        if headers:
            request_headers.update(headers)
        request = Request(
            self._url(path),
            data=body,
            method=method,
            headers=request_headers,
        )
        try:
            return urlopen(request, timeout=self.settings.request_timeout)
        except HTTPError as exc:
            if exc.code in accepted_statuses:
                return exc
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

    async def create_profile_session(
        self, profile_id: str, session_id: str, *, model: str
    ) -> HermesSession:
        profile_id = _profile_path(profile_id)
        session_id = _session_path(session_id)
        model = validate_stream_message(model)
        token = await self._profile_credential(profile_id)
        path = f"/p/{profile_id}/api/sessions"
        body = json.dumps(
            {"id": session_id, "model": model}, separators=(",", ":")
        ).encode("utf-8")

        def create() -> HermesSession:
            response = None
            try:
                response = self._request(
                    method="POST",
                    path=path,
                    token=token,
                    body=body,
                    accepted_statuses=(409,),
                )
                status = getattr(response, "status", getattr(response, "code", 200))
                if status == 409:
                    raise HermesSessionExists("Hermes session already exists")
                payload = _decode_json(_read_bounded(response))
                return _session_from_payload(payload, profile_id, session_id)
            finally:
                if response is not None:
                    response.close()

        return await asyncio.wait_for(
            asyncio.to_thread(create), self.settings.request_timeout
        )

    async def inspect_profile_session(
        self, profile_id: str, session_id: str
    ) -> HermesSession:
        profile_id = _profile_path(profile_id)
        session_id = _session_path(session_id)
        token = await self._profile_credential(profile_id)
        path = f"/p/{profile_id}/api/sessions/{session_id}"

        def inspect_session() -> HermesSession:
            response = None
            try:
                response = self._request(method="GET", path=path, token=token)
                payload = _decode_json(_read_bounded(response))
                return _session_from_payload(payload, profile_id, session_id)
            finally:
                if response is not None:
                    response.close()

        return await asyncio.wait_for(
            asyncio.to_thread(inspect_session), self.settings.request_timeout
        )

    async def ensure_profile_session(
        self, profile_id: str, session_id: str, *, model: str
    ) -> HermesSession:
        try:
            return await self.create_profile_session(
                profile_id, session_id, model=model
            )
        except HermesSessionExists:
            return await self.inspect_profile_session(profile_id, session_id)

    async def profile_session_matches_markers(
        self,
        profile_id: str,
        session_id: str,
        expected_text: str,
        forbidden_text: str,
    ) -> bool:
        """Confirm profile history contains only its expected proof marker."""

        profile_id = _profile_path(profile_id)
        session_id = _session_path(session_id)
        expected = validate_stream_message(expected_text).casefold()
        forbidden = validate_stream_message(forbidden_text).casefold()
        token = await self._profile_credential(profile_id)
        path = f"/p/{profile_id}/api/sessions/{session_id}/messages"

        def inspect_history() -> bool:
            response = None
            try:
                response = self._request(method="GET", path=path, token=token)
                payload = _decode_json(_read_bounded(response))
                rows = payload.get("data")
                if not isinstance(rows, list) or len(rows) > MAX_EVENTS:
                    raise HermesMalformedResponse(
                        "Hermes session history was malformed"
                    )
                contains_expected = any(
                    isinstance(row, dict)
                    and _content_contains_text(row.get("content"), expected)
                    for row in rows
                )
                contains_forbidden = any(
                    isinstance(row, dict)
                    and _content_contains_text(row.get("content"), forbidden)
                    for row in rows
                )
                return contains_expected and not contains_forbidden
            finally:
                if response is not None:
                    response.close()

        return await asyncio.wait_for(
            asyncio.to_thread(inspect_history), self.settings.request_timeout
        )

    async def stream(
        self,
        profile_id: str,
        session_id: str,
        message: str,
        *,
        session_key: str | None = None,
    ) -> HermesStreamResult:
        """Run one profile-scoped SSE turn with bounded response handling."""

        profile_id = _profile_path(profile_id)
        session_id = _session_path(session_id)
        message = validate_stream_message(message)
        try:
            token = await asyncio.wait_for(
                self._profile_credential(profile_id), self.settings.stream_timeout
            )
        except TimeoutError as exc:
            raise HermesTimeout("Hermes credential resolution timed out") from exc
        path = f"/p/{profile_id}/api/sessions/{session_id}/chat/stream"
        body = json.dumps({"message": message}, separators=(",", ":")).encode("utf-8")

        def read_stream() -> HermesStreamResult:
            response = None
            try:
                response = self._request(
                    method="POST",
                    path=path,
                    token=token,
                    body=body,
                    headers=_session_key_header(session_key),
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
        self,
        profile_id: str,
        session_id: str,
        message: str,
        *,
        session_key: str | None = None,
    ) -> HermesStreamResult:
        started_at = time.monotonic()
        emit_runtime_event(
            build_event(
                "provider.operation.started",
                operation="hermes_stream",
                provider="hermes",
                profile_id=profile_id,
                session_id=session_id,
                outcome="started",
            )
        )
        try:
            result = await self.stream(
                profile_id, session_id, message, session_key=session_key
            )
        except BaseException as error:
            emit_runtime_event(
                build_event(
                    "provider.operation.failed",
                    operation="hermes_stream",
                    provider="hermes",
                    profile_id=profile_id,
                    session_id=session_id,
                    duration_ms=(time.monotonic() - started_at) * 1000,
                    outcome="error",
                    error_type=type(error).__name__,
                )
            )
            raise
        emit_runtime_event(
            build_event(
                "provider.operation.succeeded",
                operation="hermes_stream",
                provider="hermes",
                profile_id=profile_id,
                session_id=session_id,
                duration_ms=(time.monotonic() - started_at) * 1000,
                outcome="success",
            )
        )
        return result

    async def stream_profile_incremental(
        self,
        profile_id: str,
        session_id: str,
        message: str,
        *,
        session_key: str | None = None,
    ) -> _ObservedHermesStream:
        """Open an SSE response and yield events without buffering the body."""

        started_at = time.monotonic()
        profile_id = _profile_path(profile_id)
        session_id = _session_path(session_id)
        message = validate_stream_message(message)
        emit_runtime_event(
            build_event(
                "provider.operation.started",
                operation="hermes_stream",
                provider="hermes",
                profile_id=profile_id,
                session_id=session_id,
                outcome="started",
            )
        )

        def finish(error: BaseException | None) -> None:
            fields = {
                "operation": "hermes_stream",
                "provider": "hermes",
                "profile_id": profile_id,
                "session_id": session_id,
                "duration_ms": (time.monotonic() - started_at) * 1000,
                "outcome": "error" if error is not None else "success",
            }
            if error is not None:
                fields["error_type"] = type(error).__name__
                fields["error_code"] = getattr(error, "code", None)
                emit_runtime_event(
                    build_event("provider.operation.failed", **fields)
                )
            else:
                emit_runtime_event(
                    build_event("provider.operation.succeeded", **fields)
                )

        try:
            token = await asyncio.wait_for(
                self._profile_credential(profile_id), self.settings.stream_timeout
            )
            path = f"/p/{profile_id}/api/sessions/{session_id}/chat/stream"
            body = json.dumps({"message": message}, separators=(",", ":")).encode(
                "utf-8"
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._request,
                    method="POST",
                    path=path,
                    token=token,
                    body=body,
                    headers=_session_key_header(session_key),
                ),
                self.settings.stream_timeout,
            )
            if not callable(getattr(response, "readline", None)):
                response.close()
                raise HermesMalformedResponse(
                    "Hermes stream did not expose incremental reads"
                )
            return _ObservedHermesStream(
                CancellableHermesStream(
                    _IncrementalHTTPStream(
                        response,
                        profile_id,
                        session_id,
                        stream_timeout=self.settings.stream_timeout,
                    )
                ),
                finish,
            )
        except TimeoutError as exc:
            error = HermesTimeout("Hermes stream timed out")
            finish(error)
            raise error from exc
        except HermesError as error:
            finish(error)
            raise
        except (URLError, OSError, ConnectionError) as exc:
            error = HermesDisconnected("Hermes stream disconnected")
            finish(error)
            raise error from exc


__all__ = [
    "DEFAULT_CREDENTIAL_SOCKET",
    "MAX_MESSAGE_BYTES",
    "TEST_CREDENTIAL_PREFIX",
    "CancellableHermesStream",
    "CredentialResolver",
    "HermesClient",
    "HermesEvent",
    "HermesHealth",
    "HermesSession",
    "HermesStreamResult",
    "StableSessionIdentifiers",
    "UnixSocketCredentialResolver",
    "stable_session_identifiers",
    "test_credential_for_reference",
    "validate_stream_message",
]
