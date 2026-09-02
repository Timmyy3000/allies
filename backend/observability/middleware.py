"""Django request boundary for one safe, correlated wide event."""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.urls import resolve
from django.utils.functional import empty

from config.middleware import CANONICAL_CLIENT_ADDRESS_META
from observability.events import (
    emit_event,
    emit_suppression_diagnostic,
    identifier_digest,
    normalize_identifier,
    normalize_request_id,
    record_dropped_event,
    wide_events_enabled,
)

_ERROR_EVENT_WINDOW_SECONDS = 60
_ERROR_EVENT_BURST = 5
_ERROR_EVENT_5XX_SCOPE_BURST = 20
_ERROR_EVENT_MAX_KEYS = 1024
_EXCEPTION_ATTRIBUTE = "_allies_observability_exception"


class _ErrorEventLimiter:
    """Keep repeated failures from amplifying stdout volume."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: OrderedDict[tuple[str, int, str, str], tuple[int, int]] = (
            OrderedDict()
        )
        self._scopes: OrderedDict[tuple[str, int, str], tuple[int, int]] = OrderedDict()
        self._suppressed: OrderedDict[tuple[str, int, str], tuple[int, int]] = (
            OrderedDict()
        )
        self._representatives: OrderedDict[tuple[str, int, str], int] = OrderedDict()

    def allow(
        self,
        route: str,
        status_code: int,
        client_key: str,
        error_key: str,
        *,
        now: float | None = None,
    ) -> bool:
        current_window = int(
            (time.monotonic() if now is None else now) // _ERROR_EVENT_WINDOW_SECONDS
        )
        key = (route[:128], status_code, client_key[:64], error_key[:64])
        scope = (route[:128], status_code, client_key[:64])
        scope_burst = (
            _ERROR_EVENT_5XX_SCOPE_BURST if status_code >= 500 else _ERROR_EVENT_BURST
        )
        with self._lock:
            for existing_key, (window, _) in list(self._windows.items()):
                if window != current_window:
                    self._windows.pop(existing_key, None)
            for existing_key, (window, _) in list(self._scopes.items()):
                if window != current_window:
                    self._scopes.pop(existing_key, None)
            for existing_key, (window, _) in list(self._suppressed.items()):
                if window != current_window:
                    self._suppressed.pop(existing_key, None)
            for existing_key, window in list(self._representatives.items()):
                if window != current_window:
                    self._representatives.pop(existing_key, None)
            window, count = self._windows.get(key, (current_window, 0))
            if window != current_window:
                count = 0
            scope_window, scope_count = self._scopes.get(scope, (current_window, 0))
            if scope_window != current_window:
                scope_count = 0
            if count >= _ERROR_EVENT_BURST or scope_count >= scope_burst:
                return False
            self._windows[key] = (current_window, count + 1)
            self._windows.move_to_end(key)
            while len(self._windows) > _ERROR_EVENT_MAX_KEYS:
                self._windows.popitem(last=False)
            self._scopes[scope] = (current_window, scope_count + 1)
            self._scopes.move_to_end(scope)
            while len(self._scopes) > _ERROR_EVENT_MAX_KEYS:
                self._scopes.popitem(last=False)
            return True

    def note_suppression(
        self,
        route: str,
        status_code: int,
        client_key: str,
        error_key: str,
        *,
        now: float | None = None,
    ) -> int:
        current_window = int(
            (time.monotonic() if now is None else now) // _ERROR_EVENT_WINDOW_SECONDS
        )
        # Aggregate diagnostics per client scope to bound fingerprint-driven output.
        del error_key
        key = (route[:128], status_code, client_key[:64])
        with self._lock:
            for existing_key, (window, _) in list(self._suppressed.items()):
                if window != current_window:
                    self._suppressed.pop(existing_key, None)
            window, count = self._suppressed.get(key, (current_window, 0))
            if window != current_window:
                count = 0
            count += 1
            self._suppressed[key] = (current_window, count)
            self._suppressed.move_to_end(key)
            while len(self._suppressed) > _ERROR_EVENT_MAX_KEYS:
                self._suppressed.popitem(last=False)
            return count

    def retain_representative(
        self, route: str, status_code: int, client_key: str, *, now: float | None = None
    ) -> bool:
        current_window = int(
            (time.monotonic() if now is None else now) // _ERROR_EVENT_WINDOW_SECONDS
        )
        key = (route[:128], status_code, client_key[:64])
        with self._lock:
            for existing_key, window in list(self._representatives.items()):
                if window != current_window:
                    self._representatives.pop(existing_key, None)
            if key in self._representatives:
                return False
            self._representatives[key] = current_window
            self._representatives.move_to_end(key)
            while len(self._representatives) > _ERROR_EVENT_MAX_KEYS:
                self._representatives.popitem(last=False)
            return True

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()
            self._scopes.clear()
            self._suppressed.clear()
            self._representatives.clear()


_error_event_limiter = _ErrorEventLimiter()


def reset_error_event_limiter() -> None:
    _error_event_limiter.reset()


def _request_id(request: HttpRequest) -> str:
    incoming = normalize_request_id(request.META.get("HTTP_X_REQUEST_ID"))
    return incoming or str(uuid.uuid4())


def _route_template(request: HttpRequest) -> str:
    match = getattr(request, "resolver_match", None)
    if match is None:
        try:
            match = resolve(request.path_info)
        except Exception:  # noqa: BLE001 - resolver failures must not affect the view.
            return "<unmatched>"
    route = getattr(match, "route", None)
    if route:
        return "/" + str(route).lstrip("/")
    return "<unmatched>"


def _correlation_id(request: HttpRequest) -> str | None:
    return normalize_identifier(
        request.META.get("HTTP_X_CORRELATION_ID"), digest_opaque=True
    )


def _client_bucket(request: HttpRequest) -> str:
    # AuthenticationMiddleware stores a lazy user; inspect only its cache.
    user_proxy = request.__dict__.get("user")
    user = user_proxy
    if user_proxy is not None:
        user = vars(user_proxy).get("_wrapped", user_proxy)
    if user is not empty and getattr(user, "is_authenticated", False):
        user_ref = getattr(user, "pk", None)
        if user_ref is not None:
            return identifier_digest(f"user:{str(user_ref)[:128]}")
    canonical = request.META.get(CANONICAL_CLIENT_ADDRESS_META)
    if isinstance(canonical, str) and canonical:
        return identifier_digest(f"address:{canonical[:128]}")
    railway_mode = getattr(settings, "ALLIES_RAILWAY_PROXY_MODE", False)
    if railway_mode:
        # Reuse the signed browser identity without resolving request.user.
        from auths.api.common import _auth_rate_limit_identity

        browser_identity = _auth_rate_limit_identity(request)
        if browser_identity:
            return identifier_digest(f"browser:{browser_identity[:128]}")
    else:
        remote_addr = request.META.get("REMOTE_ADDR")
        if isinstance(remote_addr, str) and remote_addr:
            return identifier_digest(f"peer:{remote_addr[:128]}")
    # Cookie-less Railway requests use a bounded anonymous scope.
    return "unknown"


def _error_bucket(
    status_code: int, error_type: str | None, error_fingerprint: str | None
) -> str:
    if status_code < 500:
        return "client_error"
    return identifier_digest(f"{error_type or 'http'}:{error_fingerprint or 'unknown'}")


def _echo_request_id(response: HttpResponse, request_id: str) -> bool:
    try:
        response["X-Request-ID"] = request_id
    except Exception:  # noqa: BLE001 - header echo is additive and fail-open.
        return False
    return True


class WideEventMiddleware:
    """Emit one final request event while preserving Django behavior."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def process_exception(self, request: HttpRequest, exception: Exception) -> None:
        """Stash view exceptions before Django converts them to responses."""

        setattr(request, _EXCEPTION_ATTRIBUTE, exception)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = _request_id(request)
        sampling_key = str(uuid.uuid4())
        correlation_id = _correlation_id(request)
        started = time.monotonic()
        response: HttpResponse | None = None
        error: BaseException | None = None
        try:
            response = self.get_response(request)
            return response
        except BaseException as exc:
            error = exc
            raise
        finally:
            duration_ms = max(0, round((time.monotonic() - started) * 1000, 3))
            status_code = getattr(response, "status_code", 500 if error else 200)
            rate_reason = getattr(response, "_allies_rate_limit_reason", None)
            if wide_events_enabled():
                converted_error = getattr(request, _EXCEPTION_ATTRIBUTE, None)
                event_error = error or converted_error
                if event_error is not None and status_code >= 500:
                    outcome = "error"
                    error_type = type(event_error).__name__
                    error_fingerprint = str(event_error)
                elif status_code >= 500:
                    outcome = "error"
                    error_type = None
                    error_fingerprint = None
                elif status_code >= 400:
                    outcome = "client_error"
                    error_type = None
                    error_fingerprint = None
                else:
                    outcome = "success"
                    error_type = None
                    error_fingerprint = None
                route = _route_template(request)
                if rate_reason and status_code == 429:
                    if _error_event_limiter.allow(route, 429, "aggregate", rate_reason):
                        emit_event(
                            "chat.rate_limited",
                            method=request.method,
                            route=route,
                            status_code=429,
                            reason=rate_reason,
                        )
                    else:
                        record_dropped_event()
                else:
                    is_non_success = outcome in {"error", "client_error"}
                    client_key = _client_bucket(request)
                    error_key = _error_bucket(
                        status_code, error_type, error_fingerprint
                    )
                    if is_non_success and not _error_event_limiter.allow(
                        route, status_code, client_key, error_key
                    ):
                        suppressed_count = _error_event_limiter.note_suppression(
                            route, status_code, client_key, error_key
                        )
                        record_dropped_event()
                        if suppressed_count & (suppressed_count - 1) == 0:
                            emit_suppression_diagnostic(
                                route, status_code, suppressed_count
                            )
                        if _error_event_limiter.retain_representative(
                            route, status_code, client_key
                        ):
                            emit_event(
                                "http.request",
                                request_id=request_id,
                                correlation_id=correlation_id,
                                method=request.method,
                                route=route,
                                status_code=status_code,
                                duration_ms=duration_ms,
                                outcome=outcome,
                                error_type=error_type,
                                error_fingerprint=error_fingerprint,
                                sampling_key=sampling_key,
                            )
                    else:
                        emit_event(
                            "http.request",
                            request_id=request_id,
                            correlation_id=correlation_id,
                            method=request.method,
                            route=route,
                            status_code=status_code,
                            duration_ms=duration_ms,
                            outcome=outcome,
                            error_type=error_type,
                            error_fingerprint=error_fingerprint,
                            sampling_key=sampling_key,
                        )
            if response is not None and not rate_reason:
                _echo_request_id(response, request_id)
