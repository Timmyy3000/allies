"""Bounded, privacy-safe Foundry ``WideEventV1`` events.

This module intentionally has no model, provider, or network dependencies.
Callers may therefore use it from failure paths without changing the outcome
of the operation being observed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import re
import sys
import threading
import time
from collections import deque
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from .settings import FoundryObservabilitySettings
from .sinks import BoundedSinkDispatcher, OfferResult

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

_FIELD_NAMES = frozenset(
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

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CLASS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,95}$")
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_EMAIL_RE = re.compile(r"\b[^\s@/]+@[^\s@/]+\.[^\s@/]+\b")
_SECRET_RE = re.compile(
    r"(?i)(bearer\s+|token[=:]\s*|password[=:]\s*|secret[=:]\s*|api[_-]?key[=:]\s*)[^\s,;]+"
)


class ByteSink(Protocol):
    def offer(self, envelope: bytes) -> Any: ...


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _redact_text(value: str, *, limit: int = MAX_STRING_LENGTH) -> str:
    value = _SECRET_RE.sub("[REDACTED]", value)
    value = _EMAIL_RE.sub("[REDACTED]", value)
    value = re.sub(r"(?i)https?://[^\s]+", "[REDACTED_URL]", value)
    value = value.replace("\r", " ").replace("\n", " ")
    return value[:limit]


def _safe_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not _IDENTIFIER_RE.fullmatch(value) or "@" in value:
        return None
    return value[:128]


def _safe_class(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:96] if _CLASS_RE.fullmatch(value) else None


def _safe_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:64] if _CODE_RE.fullmatch(value) else None


def _safe_nested(value: object, *, depth: int = 0) -> object | None:
    """Keep diagnostic extension values JSON-safe while dropping secrets."""

    if depth > MAX_EVENT_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value if abs(value) <= 1_000_000_000 else None
    if isinstance(value, Mapping):
        safe: dict[str, object] = {}
        for key, item in list(value.items())[:MAX_COLLECTION_ITEMS]:
            if not isinstance(key, str):
                continue
            lowered = key.lower()
            if any(
                marker in lowered
                for marker in (
                    "authorization",
                    "cookie",
                    "password",
                    "secret",
                    "token",
                    "api_key",
                    "apikey",
                    "prompt",
                    "tool",
                    "query",
                    "body",
                    "content",
                    "url",
                )
            ):
                safe[key[:64]] = "[REDACTED]"
                continue
            sanitized = _safe_nested(item, depth=depth + 1)
            if sanitized is not None:
                safe[key[:64]] = sanitized
        return safe
    if isinstance(value, (list, tuple)):
        return [
            item
            for item in (
                _safe_nested(item, depth=depth + 1)
                for item in list(value)[:MAX_COLLECTION_ITEMS]
            )
            if item is not None
        ]
    return None


def _route(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    route = value.split("?", 1)[0].split("#", 1)[0]
    route = re.sub(r"/[0-9a-fA-F-]{16,}", "/:id", route)
    route = re.sub(r"/\d+", "/:id", route)
    if not route.startswith("/") or len(route) > MAX_STRING_LENGTH:
        return None
    return route


def _field_value(name: str, value: object) -> object | None:
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
        return identifier_fingerprint(value)
    if name in {"request_id", "correlation_id"}:
        return _safe_identifier(value)
    if name in {"error_type"}:
        return _safe_class(value)
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
        return _safe_code(value)
    if name == "route":
        return _route(value)
    if name == "method":
        return value.strip().upper()[:16] if isinstance(value, str) else None
    if name == "status_code":
        return value if type(value) is int and 100 <= value <= 599 else None
    if name == "duration_ms":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return round(max(0.0, min(float(value), 86_400_000.0)), 3)
        return None
    if name == "retry_count":
        return value if type(value) is int and 0 <= value <= 1_000_000 else None
    if name == "sampled":
        return value if isinstance(value, bool) else None
    if name == "truncated":
        return value if isinstance(value, bool) else None
    if name in {"schema_version"}:
        return 1
    if name in {"occurred_at", "service", "process", "environment", "revision", "message", "outcome"}:
        return _redact_text(value) if isinstance(value, str) else None
    return _safe_nested(value)


def _config() -> FoundryObservabilitySettings:
    try:
        from django.conf import settings

        configured = getattr(settings, "FOUNDRY_OBSERVABILITY", None)
        if isinstance(configured, FoundryObservabilitySettings):
            return configured
    except (ImportError, RuntimeError):
        pass
    return FoundryObservabilitySettings.from_env()


def build_event(kind: str, **fields: object) -> dict[str, object]:
    """Build one schema-versioned event from allowlisted diagnostic fields."""

    if kind not in ALLOWED_EVENT_NAMES:
        raise ValueError("event name is not allowlisted")
    environment = os.getenv("ALLIES_ENVIRONMENT", os.getenv("DJANGO_ENVIRONMENT", "development"))
    revision = os.getenv("ALLIES_REVISION", "unknown")
    base: dict[str, object] = {
        "schema_version": 1,
        "event": kind,
        "occurred_at": _now(),
        "service": "foundry",
        "process": "web",
        "environment": environment,
        "revision": revision,
        "outcome": "unknown",
        "sampled": True,
    }
    for name, value in fields.items():
        if name not in _FIELD_NAMES:
            continue
        sanitized = _field_value(name, value)
        if sanitized is not None:
            base[name] = sanitized
    return base


def serialize_event(event: Mapping[str, object], *, max_bytes: int | None = None) -> bytes:
    """Serialize and deterministically bound one event as UTF-8 JSON."""

    limit = max_bytes or _config().max_bytes or DEFAULT_MAX_EVENT_BYTES
    if limit < 512:
        raise ValueError("event byte limit is too small")
    safe: dict[str, object] = {}
    for name, value in event.items():
        if name not in _FIELD_NAMES:
            continue
        sanitized = _field_value(name, value)
        if sanitized is not None:
            safe[name] = sanitized
    safe.setdefault("schema_version", 1)
    safe.setdefault("occurred_at", _now())
    safe.setdefault("outcome", "unknown")
    raw = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) <= limit:
        return raw
    # Drop optional high-cardinality fields before applying a final string cap.
    for name in (
        "message",
        "revision",
        "provider_resource_id",
        "resource_id",
        "run_id",
        "session_id",
        "attempt_id",
        "lease_id",
    ):
        safe.pop(name, None)
        raw = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(raw) <= limit:
            return raw
    # Required metadata is retained even when the configured bound is tight.
    for name in ("environment", "service", "process", "occurred_at"):
        if isinstance(safe.get(name), str):
            safe[name] = str(safe[name])[:32]
    raw = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > limit:
        raise ValueError("wide event exceeds configured byte bound")
    return raw


class EventCounters:
    """Process-local counters for dispatch acceptance and write failures.

    ``events_emitted`` records acceptance by the bounded stdout queue.  The
    asynchronous drain reports adapter failures separately as
    ``events_write_failures`` so queue throughput is not mistaken for durable
    log delivery.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values = {
            "events_emitted": 0,
            "events_sampled_out": 0,
            "events_dropped": 0,
            "events_write_failures": 0,
        }

    def increment(self, name: str) -> None:
        if name not in self._values:
            return
        with self._lock:
            self._values[name] = min(self._values[name] + 1, 2**63 - 1)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._values)


_counters = EventCounters()
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


_error_rate_limiter = _ErrorRateLimiter()
_stdout_dispatcher: BoundedSinkDispatcher | None = None
_stdout_queue_size: int | None = None
_stdout_lock = threading.Lock()


class _StdoutSink:
    def offer(self, envelope: bytes) -> OfferResult:
        stream = getattr(sys.stdout, "buffer", sys.stdout)
        try:
            stream.write(envelope + b"\n")
        except TypeError:
            stream.write((envelope + b"\n").decode("utf-8"))
        return OfferResult(accepted=True, dropped=False)


_stdout_dispatcher = BoundedSinkDispatcher(
    _StdoutSink(),
    max_queue_size=128,
    enabled=True,
    on_write_failure=lambda: _counters.increment("events_write_failures"),
)
_stdout_queue_size = 128


def _offer_stdout(envelope: bytes, *, max_queue_size: int) -> OfferResult:
    global _stdout_dispatcher, _stdout_queue_size
    with _stdout_lock:
        if _stdout_dispatcher is None or _stdout_queue_size != max_queue_size:
            if _stdout_dispatcher is not None:
                _stdout_dispatcher.close()
            _stdout_dispatcher = BoundedSinkDispatcher(
                _StdoutSink(),
                max_queue_size=max_queue_size,
                enabled=True,
                on_write_failure=lambda: _counters.increment("events_write_failures"),
            )
            _stdout_queue_size = max_queue_size
        return _stdout_dispatcher.offer(envelope)


def event_counters() -> dict[str, int]:
    return _counters.snapshot()


def _always_sample(event: Mapping[str, object], config: FoundryObservabilitySettings) -> bool:
    outcome = event.get("outcome")
    duration = event.get("duration_ms")
    return (
        outcome in {"error", "failed", "retry", "cancelled"}
        or str(event.get("event", "")).endswith((".failed", ".retried"))
        or (isinstance(duration, (int, float)) and duration >= config.slow_ms)
    )


def emit_event(
    event: Mapping[str, object],
    *,
    sink: ByteSink | None = None,
    config: FoundryObservabilitySettings | None = None,
    random_value: float | None = None,
) -> None:
    """Write a bounded event to stdout and optionally offer immutable bytes."""

    try:
        selected_config = config or _config()
        if not selected_config.enabled:
            _counters.increment("events_dropped")
            return
        selected = _always_sample(event, selected_config) or (
            (random_value if random_value is not None else random.random())
            < selected_config.success_sample_rate
        )
        if not selected:
            _counters.increment("events_sampled_out")
            return
        mutable = dict(event)
        mutable["sampled"] = True
        if not _error_rate_limiter.allow(mutable):
            _counters.increment("events_dropped")
            return
        envelope = serialize_event(mutable, max_bytes=selected_config.max_bytes)
        stdout_result = _offer_stdout(
            envelope, max_queue_size=selected_config.max_queue_size
        )
        if stdout_result.accepted:
            _counters.increment("events_emitted")
        else:
            _counters.increment("events_dropped")
        if selected_config.sink_enabled and sink is not None:
            try:
                result = sink.offer(bytes(envelope))
                if getattr(result, "accepted", True) is False:
                    _counters.increment("events_dropped")
            except Exception:  # noqa: BLE001 - observability is fail-open
                _counters.increment("events_dropped")
    except Exception:  # noqa: BLE001 - observability never masks application work
        _counters.increment("events_dropped")


def identifier_fingerprint(value: object) -> str | None:
    """Return a stable opaque digest for a tenant-linked identifier."""

    safe = _safe_identifier(value)
    key = os.getenv("ALLIES_OBSERVABILITY_DIGEST_KEY") or os.getenv("DJANGO_SECRET_KEY")
    if safe is None or not key:
        return None
    return "id_" + hmac.new(key.encode("utf-8"), safe.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


__all__ = [
    "ALLOWED_EVENT_NAMES",
    "EventCounters",
    "build_event",
    "emit_event",
    "event_counters",
    "identifier_fingerprint",
    "serialize_event",
]
