"""Runtime-local WideEventV1 formatter and fail-open stdout dispatcher."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import queue
import random
import re
import sys
import threading
import time
from collections import deque
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from .config import WideEventSettings

MAX_STRING_LENGTH = 256
MAX_COLLECTION_ITEMS = 16
MAX_EVENT_DEPTH = 3
DEFAULT_MAX_EVENT_BYTES = 16 * 1024
ALLOWED_EVENT_NAMES = frozenset(
    {
        "http.request",
        "task.started",
        "task.succeeded",
        "task.failed",
        "task.retried",
        "runtime.operation.started",
        "runtime.operation.succeeded",
        "runtime.operation.failed",
        "runtime.operation.retried",
        "provider.operation.started",
        "provider.operation.succeeded",
        "provider.operation.failed",
        "provider.operation.retried",
        "worker.started",
        "worker.idle",
        "worker.failed",
    }
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CLASS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,95}$")
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_EMAIL_RE = re.compile(r"\b[^\s@/]+@[^\s@/]+\.[^\s@/]+\b")
_SECRET_RE = re.compile(
    r"(?i)(bearer\s+|token[=:]\s*|password[=:]\s*|secret[=:]\s*|api[_-]?key[=:]\s*)[^\s,;]+"
)
_FIELDS = frozenset(
    {
        "schema_version",
        "event",
        "occurred_at",
        "service",
        "process",
        "environment",
        "revision",
        "request_id",
        "correlation_id",
        "method",
        "route",
        "status_code",
        "duration_ms",
        "outcome",
        "error_type",
        "error_code",
        "error_fingerprint",
        "reason_code",
        "message",
        "operation",
        "provider",
        "workspace_id",
        "execution_id",
        "attempt_id",
        "lease_id",
        "provider_resource_id",
        "resource_id",
        "profile_id",
        "session_id",
        "run_id",
        "task_name",
        "task_id",
        "queue",
        "retry_count",
        "sampled",
        "truncated",
    }
)


class EventSink(Protocol):
    def offer(self, envelope: bytes) -> Any: ...


def _text(value: str, limit: int = MAX_STRING_LENGTH) -> str:
    value = _SECRET_RE.sub("[REDACTED]", value)
    value = _EMAIL_RE.sub("[REDACTED]", value)
    value = re.sub(r"(?i)https?://[^\s]+", "[REDACTED_URL]", value)
    return value.replace("\r", " ").replace("\n", " ")[:limit]


def _identifier(value: object) -> str | None:
    return (
        value.strip()[:128]
        if isinstance(value, str) and _IDENTIFIER_RE.fullmatch(value.strip())
        else None
    )


def _identifier_digest(value: object) -> str | None:
    safe = _identifier(value)
    key = os.getenv("ALLIES_OBSERVABILITY_DIGEST_KEY") or os.getenv("DJANGO_SECRET_KEY")
    if safe is None or not key:
        return None
    return "id_" + hmac.new(key.encode("utf-8"), safe.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def _value(name: str, value: object) -> object | None:
    if name in {
        "workspace_id",
        "execution_id",
        "attempt_id",
        "lease_id",
        "provider_resource_id",
        "resource_id",
        "profile_id",
        "session_id",
        "run_id",
    }:
        return _identifier_digest(value)
    if name in {"request_id", "correlation_id"}:
        return _identifier(value)
    if name == "method":
        return value.strip().upper()[:16] if isinstance(value, str) else None
    if name == "error_type":
        return value[:96] if isinstance(value, str) and _CLASS_RE.fullmatch(value) else None
    if name in {
        "error_code",
        "error_fingerprint",
        "reason_code",
        "operation",
        "provider",
        "task_name",
        "task_id",
        "queue",
    }:
        return value[:64] if isinstance(value, str) and _CODE_RE.fullmatch(value) else None
    if name == "route":
        if not isinstance(value, str):
            return None
        return value.split("?", 1)[0][:MAX_STRING_LENGTH]
    if name == "status_code":
        return value if type(value) is int and 100 <= value <= 599 else None
    if name == "duration_ms":
        return round(max(0.0, min(float(value), 86_400_000.0)), 3) if isinstance(value, (int, float)) else None
    if name == "retry_count":
        return value if type(value) is int and 0 <= value <= 1_000_000 else None
    if name == "sampled":
        return value if isinstance(value, bool) else None
    if name == "truncated":
        return value if isinstance(value, bool) else None
    if isinstance(value, str):
        return _text(value)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and abs(value) <= 1_000_000_000:
        return value
    return None


def _settings() -> WideEventSettings:
    try:
        return WideEventSettings.from_env(os.environ)
    except Exception:  # noqa: BLE001 - a bad env must not break failure paths
        return WideEventSettings()


def build_event(kind: str, **fields: object) -> dict[str, object]:
    if kind not in ALLOWED_EVENT_NAMES:
        raise ValueError("event name is not allowlisted")
    event: dict[str, object] = {
        "schema_version": 1,
        "event": kind,
        "occurred_at": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "service": "foundry",
        "process": "runtime",
        "environment": os.getenv("ALLIES_ENVIRONMENT", "development"),
        "revision": os.getenv("ALLIES_REVISION", "unknown"),
        "outcome": "unknown",
        "sampled": True,
    }
    for name, value in fields.items():
        if name in _FIELDS:
            safe = _value(name, value)
            if safe is not None:
                event[name] = safe
    return event


def serialize_event(event: Mapping[str, object], *, max_bytes: int | None = None) -> bytes:
    safe = {
        name: safe_value
        for name, value in event.items()
        if name in _FIELDS
        for safe_value in [_value(name, value)]
        if safe_value is not None
    }
    safe.setdefault("schema_version", 1)
    safe.setdefault("occurred_at", datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"))
    safe.setdefault("outcome", "unknown")
    limit = max_bytes or _settings().max_bytes or DEFAULT_MAX_EVENT_BYTES
    raw = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) <= limit:
        return raw
    for name in ("message", "revision", "provider_resource_id", "resource_id", "run_id", "session_id", "attempt_id", "lease_id"):
        safe.pop(name, None)
        raw = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(raw) <= limit:
            return raw
    raise ValueError("wide event exceeds configured byte bound")


class EventCounters:
    """Process-local counters; emission is queue acceptance, not durable I/O."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts = {
            "events_emitted": 0,
            "events_sampled_out": 0,
            "events_dropped": 0,
            "events_write_failures": 0,
        }

    def increment(self, name: str) -> None:
        with self._lock:
            if name in self._counts:
                self._counts[name] += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)


_COUNTERS = EventCounters()
_ERROR_RATE_WINDOW_SECONDS = 1.0
_MAX_CLIENT_ERROR_EVENTS = 16
_MAX_SERVER_ERROR_EVENTS = 64
_MAX_SUCCESS_EVENTS = 1024
_MAX_LIFECYCLE_EVENTS = 256
_MAX_OTHER_HTTP_EVENTS = 128


class _ErrorRateLimiter:
    """Keep request/provider floods from monopolizing stdout capacity."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {
            "client": deque(),
            "server": deque(),
            "success": deque(),
            "lifecycle": deque(),
            "http_other": deque(),
        }
        self._lock = threading.Lock()

    @staticmethod
    def _bucket(event: Mapping[str, object]) -> tuple[str, int] | None:
        status = event.get("status_code")
        if type(status) is int and 400 <= status < 500:
            return "client", _MAX_CLIENT_ERROR_EVENTS
        if type(status) is int and 500 <= status <= 599:
            return "server", _MAX_SERVER_ERROR_EVENTS
        if event.get("outcome") in {"error", "failed"} or str(
            event.get("event", "")
        ).endswith(".failed"):
            return "server", _MAX_SERVER_ERROR_EVENTS
        if type(status) is int and 200 <= status < 300:
            return "success", _MAX_SUCCESS_EVENTS
        event_name = str(event.get("event", ""))
        if event_name == "http.request":
            return "http_other", _MAX_OTHER_HTTP_EVENTS
        if event_name:
            return "lifecycle", _MAX_LIFECYCLE_EVENTS
        return None

    def allow(self, event: Mapping[str, object]) -> bool:
        bucket = self._bucket(event)
        if bucket is None:
            return True
        name, limit = bucket
        now = time.monotonic()
        cutoff = now - _ERROR_RATE_WINDOW_SECONDS
        with self._lock:
            recent = self._events[name]
            while recent and recent[0] <= cutoff:
                recent.popleft()
            if len(recent) >= limit:
                return False
            recent.append(now)
            return True


_ERROR_RATE_LIMITER = _ErrorRateLimiter()
_SINK: EventSink | None = None
_CONFIG: WideEventSettings | None = None
_STDOUT_DISPATCHER: _StdoutDispatcher | None = None
_STDOUT_QUEUE_SIZE: int | None = None
_STDOUT_LOCK = threading.Lock()


class _StdoutDispatcher:
    """Bounded, fail-open writer that keeps stdout I/O off the caller path."""

    def __init__(self, max_queue_size: int) -> None:
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=max_queue_size)
        self._closed = threading.Event()
        self._thread = threading.Thread(
            target=self._drain,
            name="foundry-runtime-observability-stdout",
            daemon=True,
        )
        self._thread.start()

    def offer(self, envelope: bytes) -> bool:
        if self._closed.is_set():
            return False
        try:
            self._queue.put_nowait(bytes(envelope))
        except queue.Full:
            return False
        return True

    def _drain(self) -> None:
        while True:
            envelope = self._queue.get()
            try:
                if envelope is None:
                    return
                if not self._write(envelope):
                    _COUNTERS.increment("events_write_failures")
            finally:
                self._queue.task_done()
            if self._closed.is_set():
                return

    @staticmethod
    def _write(envelope: bytes) -> bool:
        try:
            stream = getattr(sys.stdout, "buffer", sys.stdout)
            try:
                stream.write(envelope + b"\n")
            except TypeError:
                stream.write((envelope + b"\n").decode("utf-8"))
        except Exception:  # noqa: BLE001 - stdout is fail-open
            return False
        return True

    def close(self) -> None:
        self._closed.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            return


_STDOUT_DISPATCHER = _StdoutDispatcher(128)
_STDOUT_QUEUE_SIZE = 128


def _offer_stdout(envelope: bytes, *, max_queue_size: int) -> bool:
    global _STDOUT_DISPATCHER, _STDOUT_QUEUE_SIZE
    with _STDOUT_LOCK:
        if _STDOUT_DISPATCHER is None or _STDOUT_QUEUE_SIZE != max_queue_size:
            if _STDOUT_DISPATCHER is not None:
                _STDOUT_DISPATCHER.close()
            _STDOUT_DISPATCHER = _StdoutDispatcher(max_queue_size)
            _STDOUT_QUEUE_SIZE = max_queue_size
        return _STDOUT_DISPATCHER.offer(envelope)


def configure_runtime_observability(
    *, config: WideEventSettings | None = None, sink: EventSink | None = None
) -> None:
    global _CONFIG, _SINK
    _CONFIG = config
    _SINK = sink


def event_counters() -> dict[str, int]:
    return _COUNTERS.snapshot()


def _always_emit(event: Mapping[str, object], config: WideEventSettings) -> bool:
    outcome = event.get("outcome")
    duration = event.get("duration_ms")
    return (
        outcome in {"error", "failed", "retry", "cancelled"}
        or str(event.get("event", "")).endswith((".failed", ".retried"))
        or (isinstance(duration, (int, float)) and duration >= config.slow_ms)
    )


def emit_runtime_event(event: Mapping[str, object]) -> None:
    """Emit a runtime event without allowing logging failures to escape."""

    try:
        config = _CONFIG or _settings()
        if not config.enabled:
            _COUNTERS.increment("events_dropped")
            return
        if not (_always_emit(event, config) or random.random() < config.success_sample_rate):
            _COUNTERS.increment("events_sampled_out")
            return
        mutable = dict(event)
        mutable["sampled"] = True
        if not _ERROR_RATE_LIMITER.allow(mutable):
            _COUNTERS.increment("events_dropped")
            return
        envelope = serialize_event(mutable, max_bytes=config.max_bytes)
        if _offer_stdout(envelope, max_queue_size=config.max_queue_size):
            _COUNTERS.increment("events_emitted")
        else:
            _COUNTERS.increment("events_dropped")
        if config.sink_enabled and _SINK is not None:
            try:
                result = _SINK.offer(bytes(envelope))
                if getattr(result, "accepted", True) is False:
                    _COUNTERS.increment("events_dropped")
            except Exception:  # noqa: BLE001 - optional sink is fail-open
                _COUNTERS.increment("events_dropped")
    except Exception:  # noqa: BLE001 - never change runtime behavior
        _COUNTERS.increment("events_dropped")


__all__ = [
    "ALLOWED_EVENT_NAMES",
    "EventCounters",
    "EventSink",
    "build_event",
    "configure_runtime_observability",
    "emit_runtime_event",
    "event_counters",
    "serialize_event",
]
