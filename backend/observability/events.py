"""Bounded, privacy-safe Cloud event construction and emission."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import re
import sys
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import NotRequired, TypedDict

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from observability.sinks import OfferResult, SinkDispatcher

logger = logging.getLogger("allies.observability")


class WideEventFormatter(logging.Formatter):
    """Keep already-serialized event records as one stdout line."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        return _bounded_string(message, 128 * 1024)


class AuditEventFormatter(logging.Formatter):
    """Keep structured audit extras visible without changing wide events."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        payload = getattr(record, "auth_event", None) or getattr(
            record, "waitlist_admin_access", None
        )
        if payload is not None:
            try:
                rendered = json.dumps(
                    payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
                )
                if rendered not in message:
                    message = f"{message} {rendered}"
            except (TypeError, ValueError):
                message = f"{message} [unserializable audit payload]"
        return f"{record.levelname} {record.name} {message}"


EVENT_NAMES = frozenset(
    {
        "http.request",
        "task.started",
        "task.succeeded",
        "task.failed",
        "task.retried",
    }
)

_MAX_STRING_CHARS = 256
_MAX_COLLECTION_ITEMS = 16
_MAX_NESTING = 3
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_EVENT_RE = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*){1,3}$")
_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_URL_RE = re.compile(
    r"\b(?:https?|redis|postgres(?:ql)?|mysql)://[^\s]+", re.IGNORECASE
)
_SECRET_RE = re.compile(
    r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+|"
    r"\b(?:password|passwd|secret|token|api[_-]?key|authorization|cookie)"
    r"\s*[:=]\s*[^\s,;]+"
)

_ALLOWED_FIELDS = frozenset(
    {
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
        "task_name",
        "task_id",
        "queue",
        "retry_count",
        "sampled",
    }
)
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "body",
        "request_body",
        "response_body",
        "prompt",
        "message",
        "document",
        "tool_arguments",
        "tool_results",
        "headers",
        "cookies",
        "query_string",
        "url",
        "database_url",
        "sql",
    }
)
_OPTIONAL_FIELDS = (
    "error_fingerprint",
    "error_code",
    "error_type",
    "correlation_id",
    "revision",
    "queue",
    "task_name",
    "task_id",
    "request_id",
    "route",
    "method",
    "retry_count",
    "duration_ms",
    "status_code",
)


class WideEventV1(TypedDict):
    """The version-one event shape; optional operation fields are nullable."""

    schema_version: int
    event: str
    occurred_at: str
    service: str
    process: str
    environment: str
    revision: NotRequired[str | None]
    request_id: NotRequired[str | None]
    correlation_id: NotRequired[str | None]
    method: NotRequired[str | None]
    route: NotRequired[str | None]
    status_code: NotRequired[int | None]
    duration_ms: NotRequired[int | float | None]
    outcome: str
    error_type: NotRequired[str | None]
    error_code: NotRequired[str | None]
    error_fingerprint: NotRequired[str | None]
    task_name: NotRequired[str | None]
    task_id: NotRequired[str | None]
    queue: NotRequired[str | None]
    retry_count: NotRequired[int | None]
    sampled: bool


WideEvent = WideEventV1

_counter_lock = threading.Lock()
_counters = {
    "events_emitted": 0,
    "events_sampled_out": 0,
    "events_dropped": 0,
}
_sink_lock = threading.Lock()
_sink_dispatcher: SinkDispatcher | None = None


def get_counters() -> dict[str, int]:
    with _counter_lock:
        return dict(_counters)


def reset_counters() -> None:
    with _counter_lock:
        for name in _counters:
            _counters[name] = 0


def _count(name: str) -> None:
    with _counter_lock:
        _counters[name] += 1


def _setting(name: str, default):
    try:
        return getattr(settings, name, default)
    except (AttributeError, ImproperlyConfigured):
        return default


def wide_events_enabled() -> bool:
    return bool(_setting("ALLIES_WIDE_EVENTS_ENABLED", True))


def process_type() -> str:
    configured = os.environ.get("ALLIES_PROCESS_TYPE", "").strip().lower()
    if configured in {"web", "worker", "beat", "management", "test"}:
        return configured
    argv = " ".join(sys.argv).lower()
    if " beat" in f" {argv}" or argv.endswith("beat"):
        return "beat"
    if " worker" in f" {argv}" or argv.endswith("worker"):
        return "worker"
    if "pytest" in argv:
        return "test"
    return "web"


def _environment() -> str:
    configured = (
        os.environ.get("ALLIES_ENVIRONMENT")
        or os.environ.get("RAILWAY_ENVIRONMENT_NAME")
        or os.environ.get("DJANGO_ENVIRONMENT")
    )
    if configured:
        return _bounded_string(configured, 64)
    return "development" if _setting("DEBUG", True) else "production"


def _revision() -> str | None:
    revision = (
        os.environ.get("RAILWAY_GIT_COMMIT_SHA")
        or os.environ.get("GIT_COMMIT")
        or os.environ.get("SOURCE_VERSION")
    )
    return _bounded_string(revision, 128) if revision else None


def _bounded_string(value: object, limit: int = _MAX_STRING_CHARS) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = "".join(char if ord(char) >= 32 else " " for char in text)
    return text[:limit]


def _redact_text(value: object) -> str:
    text = _bounded_string(value)
    text = _SECRET_RE.sub("[REDACTED]", text)
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _URL_RE.sub("[REDACTED_URL]", text)
    return _IP_RE.sub("[REDACTED_IP]", text)


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or any(
        marker in normalized
        for marker in ("authorization", "password", "secret", "token", "cookie")
    )


def _sanitize_value(value: object, *, key: object = "", depth: int = 0):
    if _is_sensitive_key(key):
        return "[REDACTED]"
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _redact_text(value)
    if depth >= _MAX_NESTING:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        result = {}
        for item_key, item_value in list(value.items())[:_MAX_COLLECTION_ITEMS]:
            if _is_sensitive_key(item_key):
                result[_bounded_string(item_key, 64)] = "[REDACTED]"
            else:
                result[_bounded_string(item_key, 64)] = _sanitize_value(
                    item_value, key=item_key, depth=depth + 1
                )
        if len(value) > _MAX_COLLECTION_ITEMS:
            result["_truncated"] = True
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        result = [
            _sanitize_value(item, depth=depth + 1)
            for item in list(value)[:_MAX_COLLECTION_ITEMS]
        ]
        if len(value) > _MAX_COLLECTION_ITEMS:
            result.append("[TRUNCATED]")
        return result
    return _bounded_string(value)


def normalize_request_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if len(candidate) > 128 or not _IDENTIFIER_RE.fullmatch(candidate):
        return None
    return candidate


def normalize_identifier(value: object, *, digest_opaque: bool = True) -> str | None:
    candidate = normalize_request_id(value)
    if candidate is None:
        return None
    if _UUID_RE.fullmatch(candidate) or not digest_opaque:
        return candidate
    return identifier_digest(candidate)


def identifier_digest(value: str) -> str:
    secret = str(_setting("SECRET_KEY", "allies-cloud-observability")).encode()
    return "id_" + hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()[:24]


def _error_fingerprint(value: object) -> str | None:
    if value is None:
        return None
    return identifier_digest(_redact_text(value))


def _safe_event_name(kind: object) -> str:
    candidate = _bounded_string(kind, 64).lower()
    if candidate in EVENT_NAMES:
        return candidate
    raise ValueError("event name is not allowlisted")


def _safe_outcome(value: object, event_name: str) -> str:
    if isinstance(value, str) and _ERROR_CODE_RE.fullmatch(value.lower()):
        return value.lower()[:32]
    if event_name == "http.request":
        return "success"
    if event_name.endswith("started"):
        return "started"
    if event_name.endswith("retried"):
        return "retry"
    return "unknown"


def _serialize(event: Mapping[str, object]) -> bytes:
    return json.dumps(
        event,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _fit_bytes(event: dict[str, object]) -> dict[str, object]:
    maximum = int(_setting("ALLIES_WIDE_EVENTS_MAX_BYTES", 16 * 1024))
    if len(_serialize(event)) <= maximum:
        return event
    event["truncated"] = True
    for field in _OPTIONAL_FIELDS:
        event.pop(field, None)
        if len(_serialize(event)) <= maximum:
            return event
    # The settings validator keeps this limit practical; this final fallback
    # preserves the required event identity even under a stale override.
    return {
        "schema_version": 1,
        "event": event["event"],
        "occurred_at": event["occurred_at"],
        "service": event["service"],
        "process": event["process"],
        "environment": event["environment"],
        "outcome": event["outcome"],
        "sampled": event["sampled"],
        "truncated": True,
    }


def build_event(kind: str, **fields: object) -> WideEventV1:
    """Build a bounded JSON-serializable event without performing I/O."""

    event_name = _safe_event_name(kind)
    event: dict[str, object] = {
        "schema_version": 1,
        "event": event_name,
        "occurred_at": datetime.now(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "service": _bounded_string(
            fields.get("service", _setting("ALLIES_WIDE_EVENTS_SERVICE", "cloud")),
            64,
        ),
        "process": _bounded_string(
            fields.get("process", process_type()),
            32,
        ),
        "environment": _bounded_string(
            fields.get("environment", _environment()),
            64,
        ),
        "outcome": _safe_outcome(fields.get("outcome"), event_name),
        "sampled": bool(fields.get("sampled", True)),
    }
    revision = fields.get("revision", _revision())
    if revision:
        event["revision"] = _bounded_string(revision, 128)

    for field in _ALLOWED_FIELDS - {
        "occurred_at",
        "service",
        "process",
        "environment",
        "revision",
        "outcome",
        "sampled",
    }:
        if field not in fields:
            continue
        value = fields[field]
        if field in {"request_id", "correlation_id", "task_id"}:
            value = normalize_identifier(value, digest_opaque=field != "request_id")
        elif field in {"status_code", "retry_count"}:
            try:
                value = int(value) if value is not None else None
            except (TypeError, ValueError):
                value = None
        elif field == "duration_ms":
            try:
                value = (
                    max(0, min(float(value), 86_400_000)) if value is not None else None
                )
                if value is not None and value.is_integer():
                    value = int(value)
            except (TypeError, ValueError):
                value = None
        elif field == "error_type":
            if value is not None:
                value = _bounded_string(value, 96).rsplit(".", 1)[-1]
                value = (
                    value
                    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,95}", value)
                    else None
                )
        elif field in {"error_code", "outcome"}:
            value = _safe_outcome(value, event_name) if value is not None else None
        elif field == "error_fingerprint":
            value = _error_fingerprint(value)
        else:
            value = _sanitize_value(value, key=field)
            if isinstance(value, str):
                value = value[:_MAX_STRING_CHARS]
        event[field] = value

    return _fit_bytes(event)  # type: ignore[return-value]


def _is_slow(event: Mapping[str, object]) -> bool:
    duration = event.get("duration_ms")
    try:
        return duration is not None and float(duration) >= float(
            _setting("ALLIES_WIDE_EVENTS_SLOW_MS", 1000)
        )
    except (TypeError, ValueError):
        return False


def _sample_success_event(
    event: Mapping[str, object], *, sampling_key: object | None = None
) -> bool:
    rate = float(_setting("ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE", 0.05))
    if rate >= 1:
        return True
    if rate <= 0:
        return False
    # Middleware supplies a server-generated key so callers cannot choose the
    # sampling bucket through an incoming request header. Task IDs remain the
    # stable server-owned fallback for lifecycle events.
    identity = str(sampling_key or event.get("task_id") or event.get("occurred_at"))
    digest = int(hashlib.sha256(identity.encode()).hexdigest()[:12], 16) / 16**12
    return digest < rate


def should_sample(
    event: Mapping[str, object], *, sampling_key: object | None = None
) -> bool:
    if event.get("event") in {"task.failed", "task.retried"}:
        return True
    if event.get("event") == "task.started":
        # A started event has no duration yet; slow-task retention applies to
        # the terminal event, which is the first point where slowness is known.
        return _sample_success_event(event, sampling_key=sampling_key)
    if event.get("outcome") not in {"success", "succeeded"}:
        return True
    if _is_slow(event):
        return True
    return _sample_success_event(event, sampling_key=sampling_key)


def _get_sink() -> SinkDispatcher | None:
    global _sink_dispatcher
    if not _setting("ALLIES_WIDE_EVENTS_SINK_ENABLED", False):
        return None
    with _sink_lock:
        if _sink_dispatcher is None:
            _sink_dispatcher = SinkDispatcher(
                max_queue_size=int(_setting("ALLIES_WIDE_EVENTS_MAX_QUEUE_SIZE", 256))
            )
        return _sink_dispatcher


def set_sink_dispatcher(dispatcher: SinkDispatcher | None) -> None:
    global _sink_dispatcher
    with _sink_lock:
        _sink_dispatcher = dispatcher


def record_dropped_event() -> None:
    """Count an event suppressed before construction or emission."""

    _count("events_dropped")


def emit_suppression_diagnostic(
    route: str, status_code: int, suppressed_count: int
) -> None:
    """Write a bounded diagnostic without re-entering event construction."""

    if not wide_events_enabled():
        return
    try:
        logger.warning(
            json.dumps(
                {
                    "diagnostic": "wide_event_suppression",
                    "reason": "error_burst_limit",
                    "route": _bounded_string(route, 128),
                    "status_code": int(status_code),
                    "suppressed_count": max(1, int(suppressed_count)),
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    except Exception:  # noqa: BLE001 - diagnostics must remain fail-open.
        return


def emit_task_suppression_diagnostic(
    task_name: str, lifecycle: str, suppressed_count: int
) -> None:
    """Write a bounded task diagnostic without re-entering event construction."""

    if not wide_events_enabled():
        return
    try:
        logger.warning(
            json.dumps(
                {
                    "diagnostic": "wide_event_suppression",
                    "reason": "task_error_burst_limit",
                    "task_name": _bounded_string(task_name, 128),
                    "lifecycle": _bounded_string(lifecycle, 32),
                    "suppressed_count": max(1, int(suppressed_count)),
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    except Exception:  # noqa: BLE001 - diagnostics must remain fail-open.
        return


def emit_event(kind: str, **fields: object) -> WideEventV1 | None:
    """Sample, serialize, and emit one event; all failures are fail-open."""

    if not wide_events_enabled():
        return None
    try:
        sampling_key = fields.get("sampling_key")
        event = build_event(kind, **fields)
        if not should_sample(event, sampling_key=sampling_key):
            _count("events_sampled_out")
            return None
        event["sampled"] = True
        envelope = _serialize(event)
        if len(envelope) > int(_setting("ALLIES_WIDE_EVENTS_MAX_BYTES", 16 * 1024)):
            _count("events_dropped")
            return None
        try:
            logger.info(envelope.decode("utf-8"))
        except Exception:  # noqa: BLE001 - logging must never change app behavior.
            _count("events_dropped")
        else:
            _count("events_emitted")
        dispatcher = _get_sink()
        if dispatcher is not None:
            result: OfferResult = dispatcher.offer(envelope)
            if result.dropped:
                _count("events_dropped")
        return event
    except Exception:  # noqa: BLE001 - event observability is explicitly fail-open.
        _count("events_dropped")
        return None
