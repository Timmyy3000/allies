"""Worker and beat-only Celery lifecycle event handlers."""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from celery import signals

from observability.events import (
    emit_event,
    emit_task_suppression_diagnostic,
    normalize_identifier,
    process_type,
    record_dropped_event,
    wide_events_enabled,
)

_registered = False
_start_times: OrderedDict[str, float] = OrderedDict()
_task_contexts: OrderedDict[str, dict[str, Any]] = OrderedDict()
_seen: OrderedDict[tuple[str, str, int], None] = OrderedDict()
_MAX_CACHE_ENTRIES = 2048
_TASK_ERROR_WINDOW_SECONDS = 60
_TASK_ERROR_BURST = 20
_TASK_ERROR_MAX_KEYS = 1024


class _TaskErrorLimiter:
    """Bound repeated task failures and retries while retaining one sample."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: OrderedDict[tuple[str, str], tuple[int, int]] = OrderedDict()
        self._suppressed: OrderedDict[tuple[str, str], tuple[int, int]] = OrderedDict()
        self._representatives: OrderedDict[tuple[str, str], int] = OrderedDict()

    @staticmethod
    def _key(task_name: str | None, lifecycle: str) -> tuple[str, str]:
        return (str(task_name or "<unknown>")[:128], lifecycle[:32])

    def _prune(self, current_window: int) -> None:
        for mapping in (self._windows, self._suppressed, self._representatives):
            for key, value in list(mapping.items()):
                window = value[0] if isinstance(value, tuple) else value
                if window != current_window:
                    mapping.pop(key, None)

    def allow(self, task_name: str | None, lifecycle: str, *, now=None) -> bool:
        current_window = int(
            (time.monotonic() if now is None else now) // _TASK_ERROR_WINDOW_SECONDS
        )
        key = self._key(task_name, lifecycle)
        with self._lock:
            self._prune(current_window)
            window, count = self._windows.get(key, (current_window, 0))
            if window != current_window:
                count = 0
            if count >= _TASK_ERROR_BURST:
                return False
            self._windows[key] = (current_window, count + 1)
            self._windows.move_to_end(key)
            while len(self._windows) > _TASK_ERROR_MAX_KEYS:
                self._windows.popitem(last=False)
            return True

    def note_suppression(
        self, task_name: str | None, lifecycle: str, *, now=None
    ) -> int:
        current_window = int(
            (time.monotonic() if now is None else now) // _TASK_ERROR_WINDOW_SECONDS
        )
        key = self._key(task_name, lifecycle)
        with self._lock:
            self._prune(current_window)
            window, count = self._suppressed.get(key, (current_window, 0))
            if window != current_window:
                count = 0
            count += 1
            self._suppressed[key] = (current_window, count)
            self._suppressed.move_to_end(key)
            while len(self._suppressed) > _TASK_ERROR_MAX_KEYS:
                self._suppressed.popitem(last=False)
            return count

    def retain_representative(
        self, task_name: str | None, lifecycle: str, *, now=None
    ) -> bool:
        current_window = int(
            (time.monotonic() if now is None else now) // _TASK_ERROR_WINDOW_SECONDS
        )
        key = self._key(task_name, lifecycle)
        with self._lock:
            self._prune(current_window)
            if key in self._representatives:
                return False
            self._representatives[key] = current_window
            self._representatives.move_to_end(key)
            while len(self._representatives) > _TASK_ERROR_MAX_KEYS:
                self._representatives.popitem(last=False)
            return True

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()
            self._suppressed.clear()
            self._representatives.clear()


_task_error_limiter = _TaskErrorLimiter()


def _bounded_put(mapping: OrderedDict, key: Any, value: Any) -> None:
    mapping[key] = value
    mapping.move_to_end(key)
    while len(mapping) > _MAX_CACHE_ENTRIES:
        mapping.popitem(last=False)


def _is_worker_or_beat() -> bool:
    configured = os.environ.get("ALLIES_PROCESS_TYPE", "").strip().lower()
    return configured in {"worker", "beat"} or process_type() in {"worker", "beat"}


def _task_name(sender: Any, task: Any) -> str | None:
    value = getattr(sender, "name", None) or getattr(task, "name", None)
    if value is None and isinstance(sender, str):
        value = sender
    if not isinstance(value, str):
        return None
    return value.rsplit(".", 1)[-1] if value.startswith("__main__.") else value


def _request_for(task: Any, request: Any = None) -> Any:
    return request or getattr(task, "request", None)


def _request_value(request: Any, name: str, default: Any = None) -> Any:
    if request is None:
        return default
    value = getattr(request, name, None)
    if value is not None:
        return value
    if isinstance(request, Mapping):
        return request.get(name, default)
    return default


def _task_context(task: Any, request: Any = None) -> dict[str, Any]:
    task_request = _request_for(task, request)
    delivery = _request_value(task_request, "delivery_info", {}) or {}
    headers = _request_value(task_request, "headers", {}) or {}
    correlation = (
        _request_value(task_request, "correlation_id")
        or headers.get("correlation_id")
        or headers.get("X-Correlation-ID")
        if isinstance(headers, Mapping)
        else _request_value(task_request, "correlation_id")
    )
    raw_retries = _request_value(task_request, "retries", 0) or 0
    try:
        retry_count = max(0, int(raw_retries))
    except (TypeError, ValueError):
        retry_count = 0
    return {
        "task_id": normalize_identifier(_request_value(task_request, "id")),
        "queue": (
            delivery.get("queue") or delivery.get("routing_key") or "cloud"
            if isinstance(delivery, Mapping)
            else "cloud"
        ),
        "correlation_id": normalize_identifier(correlation, digest_opaque=True),
        "retry_count": retry_count,
    }


def _task_id_for(task: Any, task_id: Any = None, request: Any = None) -> str | None:
    return normalize_identifier(
        task_id or _request_value(_request_for(task, request), "id")
    )


def _remember_context(task_id: str | None, context: dict[str, Any]) -> None:
    if task_id:
        _bounded_put(_task_contexts, task_id, dict(context))


def _context_for(task: Any, task_id: Any = None, request: Any = None) -> dict[str, Any]:
    resolved_task_id = _task_id_for(task, task_id, request)
    if resolved_task_id in _task_contexts:
        return dict(_task_contexts[resolved_task_id])
    context = _task_context(task, request)
    context["task_id"] = resolved_task_id or context["task_id"]
    return context


def _duration_ms(task_id: str | None) -> int | None:
    if not task_id:
        return None
    started = _start_times.pop(task_id, None)
    if started is None:
        return None
    return max(0, round((time.monotonic() - started) * 1000, 3))


def _already_seen(task_id: str | None, lifecycle: str, retry_count: int) -> bool:
    if not task_id:
        return False
    key = (task_id, lifecycle, retry_count)
    if key in _seen:
        return True
    _bounded_put(_seen, key, None)
    return False


def _allow_task_error(task_name: str | None, lifecycle: str) -> bool:
    if _task_error_limiter.allow(task_name, lifecycle):
        return True
    suppressed_count = _task_error_limiter.note_suppression(task_name, lifecycle)
    record_dropped_event()
    if suppressed_count & (suppressed_count - 1) == 0:
        emit_task_suppression_diagnostic(
            task_name or "<unknown>", lifecycle, suppressed_count
        )
    return _task_error_limiter.retain_representative(task_name, lifecycle)


def on_task_prerun(sender=None, task_id=None, task=None, **kwargs) -> None:
    if not _is_worker_or_beat() or not wide_events_enabled():
        return
    task_id = _task_id_for(task, task_id, kwargs.get("request"))
    if task_id and task_id not in _start_times:
        _bounded_put(_start_times, task_id, time.monotonic())
    context = _task_context(task, kwargs.get("request"))
    context["task_id"] = task_id or context["task_id"]
    _remember_context(task_id, context)
    retry_count = context["retry_count"]
    if _already_seen(task_id, "started", retry_count):
        return
    emit_event(
        "task.started",
        task_name=_task_name(sender, task),
        outcome="started",
        **context,
    )


def on_task_postrun(sender=None, task_id=None, task=None, state=None, **kwargs) -> None:
    if (
        not _is_worker_or_beat()
        or not wide_events_enabled()
        or str(state).upper() != "SUCCESS"
    ):
        return
    context = _context_for(task, task_id, kwargs.get("request"))
    task_id = _task_id_for(task, task_id, kwargs.get("request"))
    context["task_id"] = task_id or context["task_id"]
    retry_count = context["retry_count"]
    if _already_seen(task_id, "succeeded", retry_count):
        return
    context["duration_ms"] = _duration_ms(task_id)
    emit_event(
        "task.succeeded",
        task_name=_task_name(sender, task),
        outcome="success",
        **context,
    )


def on_task_failure(
    sender=None, task_id=None, exception=None, einfo=None, task=None, **kwargs
) -> None:
    if not _is_worker_or_beat() or not wide_events_enabled():
        return
    context = _context_for(task, task_id, kwargs.get("request"))
    task_id = _task_id_for(task, task_id, kwargs.get("request"))
    context["task_id"] = task_id or context["task_id"]
    retry_count = context["retry_count"]
    if _already_seen(task_id, "failed", retry_count):
        return
    context["duration_ms"] = _duration_ms(task_id)
    task_name = _task_name(sender, task)
    if not _allow_task_error(task_name, "failed"):
        return
    emit_event(
        "task.failed",
        task_name=task_name,
        outcome="error",
        error_type=type(exception).__name__ if exception is not None else None,
        error_fingerprint=str(exception) if exception is not None else None,
        **context,
    )


def on_task_retry(sender=None, request=None, reason=None, einfo=None, **kwargs) -> None:
    if not _is_worker_or_beat() or not wide_events_enabled():
        return
    context = _task_context(sender, request)
    task_id = _task_id_for(sender, None, request)
    context["task_id"] = task_id or context["task_id"]
    _remember_context(task_id, context)
    retry_count = context["retry_count"]
    if _already_seen(task_id, "retried", retry_count):
        return
    context["duration_ms"] = _duration_ms(task_id)
    task_name = _task_name(sender, sender)
    if not _allow_task_error(task_name, "retried"):
        return
    emit_event(
        "task.retried",
        task_name=task_name,
        outcome="retry",
        error_type=type(reason).__name__ if reason is not None else None,
        error_fingerprint=str(reason) if reason is not None else None,
        **context,
    )


def register_celery_signals() -> bool:
    global _registered
    if _registered or not _is_worker_or_beat():
        return False
    signals.task_prerun.connect(
        on_task_prerun, weak=False, dispatch_uid="allies-wide-task-prerun"
    )
    signals.task_postrun.connect(
        on_task_postrun, weak=False, dispatch_uid="allies-wide-task-postrun"
    )
    signals.task_failure.connect(
        on_task_failure, weak=False, dispatch_uid="allies-wide-task-failure"
    )
    signals.task_retry.connect(
        on_task_retry, weak=False, dispatch_uid="allies-wide-task-retry"
    )
    _registered = True
    return True


def reset_state() -> None:
    _start_times.clear()
    _task_contexts.clear()
    _seen.clear()
    _task_error_limiter.reset()
