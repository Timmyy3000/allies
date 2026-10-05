"""Django request boundary for bounded ``http.request`` events."""

from __future__ import annotations

import contextvars
import re
import time
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.core.handlers.exception import response_for_exception
from django.http import Http404
from django.urls import Resolver404

from .events import build_event, emit_event

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "foundry_request_id", default=None
)


def current_request_id() -> str | None:
    return _request_id.get()


def _request_id_for(request) -> str:
    supplied = request.META.get("HTTP_X_REQUEST_ID", "")
    if isinstance(supplied, str):
        supplied = supplied.strip()
    if isinstance(supplied, str) and _REQUEST_ID_RE.fullmatch(supplied):
        return supplied[:128]
    return f"req_{uuid4().hex}"


def _route_for(request) -> str:
    match = getattr(request, "resolver_match", None)
    route = getattr(match, "route", None)
    if isinstance(route, str) and route.strip():
        route = route.split("?", 1)[0].strip()
        route = re.sub(
            r"<(?:(?P<converter>[A-Za-z_][A-Za-z0-9_]*):)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)>",
            lambda match: ":" + match.group("name"),
            route,
        )
        route = re.sub(r"/[0-9a-fA-F-]{16,}", "/:id", route)
        route = re.sub(r"/\d+", "/:id", route)
        route = "/" + route.lstrip("/")
        return route[:512]
    # Unmatched paths are intentionally reduced to a stable shape rather than
    # retaining user-controlled path segments or query strings.
    path = str(getattr(request, "path", ""))
    parts = [part for part in path.split("/") if part]
    safe = [":id" if (part.isdigit() or len(part) > 32) else "*" for part in parts]
    return "/" + "/".join(safe) if safe else "/"


def _status_for_error(error: BaseException) -> int:
    if isinstance(error, (Http404, Resolver404)):
        return 404
    if isinstance(error, PermissionDenied):
        return 403
    if isinstance(error, SuspiciousOperation):
        return 400
    return 500


class WideEventMiddleware:
    """Emit one final request event while preserving response/error semantics."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = _request_id_for(request)
        request.request_id = request_id
        token = _request_id.set(request_id)
        started = time.monotonic()
        response = None
        error: BaseException | None = None
        try:
            response = self.get_response(request)
            return response
        except BaseException as exc:
            error = exc
            raise
        finally:
            duration_ms = (time.monotonic() - started) * 1000
            status_code = getattr(
                response, "status_code", _status_for_error(error) if error else 200
            )
            outcome = "error" if error is not None or status_code >= 400 else "success"
            fields: dict[str, object] = {
                "request_id": request_id,
                "method": getattr(request, "method", "GET"),
                "route": _route_for(request),
                "status_code": status_code,
                "duration_ms": duration_ms,
                "outcome": outcome,
            }
            if error is not None:
                fields["error_type"] = type(error).__name__
                error_code = getattr(error, "code", None)
                if isinstance(error_code, str):
                    fields["error_code"] = error_code
            emit_event(
                build_event("http.request", **fields),
                sink=getattr(settings, "FOUNDRY_EVENT_SINK", None),
                config=getattr(settings, "FOUNDRY_OBSERVABILITY", None),
            )
            if response is not None:
                response["X-Request-ID"] = request_id
            _request_id.reset(token)

    def process_exception(self, request, error):
        """Stamp responses Django creates after the request boundary re-raises."""

        response = response_for_exception(request, error)
        request_id = getattr(request, "request_id", None)
        if not isinstance(request_id, str):
            request_id = _request_id_for(request)
        response["X-Request-ID"] = request_id
        return response


RequestObservabilityMiddleware = WideEventMiddleware


__all__ = ["RequestObservabilityMiddleware", "WideEventMiddleware", "current_request_id"]
