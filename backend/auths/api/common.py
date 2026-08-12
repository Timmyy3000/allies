"""Shared HTTP concerns for the capability-owned authentication controllers."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import (
    InvalidTokenFormat,
    _check_token_format,
    _does_token_match,
)
from django.utils import timezone

from auths.api.schemas import ErrorData, ErrorResponse
from auths.config import (
    access_ttl_seconds,
    cookie_name,
    cookie_path,
    cookie_samesite,
    cookie_secure,
    flow_ttl_seconds,
)
from auths.exceptions import SessionInvalid
from auths.services.sessions import authenticate_access


def _as_json(value: Any) -> Any:
    """Convert Pydantic/Ninja schemas while leaving plain JSON data intact."""

    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def success_body(data: Any, message: str) -> dict[str, Any]:
    return {"status": "success", "message": message, "data": _as_json(data)}


def success_json(data: Any, message: str, *, status: int = 200) -> JsonResponse:
    return JsonResponse(success_body(data, message), status=status)


def error_body(
    code: str, message: str, *, details: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    error_data: dict[str, Any] = {"code": code}
    if details:
        error_data["details"] = dict(details)
    return {"status": "error", "message": message, "data": error_data}


def error_json(
    code: str,
    message: str,
    status: int,
    *,
    details: Mapping[str, Any] | None = None,
) -> JsonResponse:
    return JsonResponse(error_body(code, message, details=details), status=status)


def error_schema():
    """Return the reusable typed error schema used by route declarations."""

    return ErrorResponse[ErrorData]


def error_responses(*statuses: int) -> dict[int, Any]:
    schema = error_schema()
    return {status: schema for status in statuses}


def _domain_status(code: str, default: int = 400) -> int:
    return {
        "provider_unavailable": 404,
        "already_linked_elsewhere": 409,
        "storage_unavailable": 503,
        "throttle_unavailable": 503,
        "avatar_absent": 404,
        "invalid_state": 409,
        "workspace_denied": 404,
        "flow_replayed": 409,
    }.get(code, default)


def _origin_allowed(request: HttpRequest) -> bool:
    origin = request.headers.get("Origin")
    if not origin:
        referer = request.headers.get("Referer")
        if not referer:
            return False
        origin = "/".join(referer.split("/", 3)[:3])
    allowed = set(getattr(settings, "CSRF_TRUSTED_ORIGINS", ()))
    return origin in allowed


def _require_origin(request: HttpRequest) -> JsonResponse | None:
    if not _origin_allowed(request):
        return error_json("origin_rejected", "origin rejected", 403)
    csrf_name = getattr(settings, "CSRF_COOKIE_NAME", "csrftoken")
    cookie = request.COOKIES.get(csrf_name)
    header = request.headers.get("X-CSRFToken")
    try:
        if not cookie or not header:
            raise InvalidTokenFormat("missing CSRF token")
        _check_token_format(cookie)
        _check_token_format(header)
        valid = _does_token_match(header, cookie)
    except (InvalidTokenFormat, AssertionError):
        valid = False
    if not valid:
        return error_json("csrf_rejected", "csrf rejected", 403)
    return None


def _session(request: HttpRequest):
    raw = request.COOKIES.get(cookie_name("access"))
    if not raw:
        raise SessionInvalid("session invalid")
    return authenticate_access(raw)


def _csrf_binding(request: HttpRequest) -> bytes:
    name = getattr(settings, "CSRF_COOKIE_NAME", "csrftoken")
    return (request.COOKIES.get(name) or "").encode()


def _client_identity(request: HttpRequest) -> str:
    peer = request.META.get("REMOTE_ADDR", "").strip()
    raw = peer
    trusted = set(getattr(settings, "ALLIES_TRUSTED_PROXY_IPS", ()))
    if getattr(settings, "ALLIES_TRUST_FORWARDED_FOR", False) and peer in trusted:
        chain = [
            item.strip()
            for item in request.headers.get("X-Forwarded-For", "").split(",")
            if item.strip()
        ] + [peer]
        while chain and chain[-1] in trusted:
            chain.pop()
        if chain:
            raw = chain[-1]
    try:
        address = ipaddress.ip_address(raw)
        prefix = 24 if address.version == 4 else 64
        return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))
    except ValueError:
        return "unknown"


def _set_session_cookies(response: HttpResponse, issued) -> None:
    response.set_cookie(
        cookie_name("access"),
        issued.access_token,
        max_age=access_ttl_seconds(),
        httponly=True,
        secure=cookie_secure(),
        samesite=cookie_samesite(),
        path=cookie_path("access"),
    )
    response.set_cookie(
        cookie_name("refresh"),
        issued.refresh_token,
        max_age=max(
            0, int((issued.refresh_expires_at - timezone.now()).total_seconds())
        ),
        httponly=True,
        secure=cookie_secure(),
        samesite="Strict",
        path=cookie_path("refresh"),
    )


def _clear_auth_cookies(response: HttpResponse) -> None:
    response.delete_cookie(cookie_name("access"), path=cookie_path("access"))
    response.delete_cookie(cookie_name("refresh"), path=cookie_path("refresh"))
    response.delete_cookie(cookie_name("flow"), path=cookie_path("flow"))


def _set_flow_cookie(response: HttpResponse, flow_cookie: str, expires_at) -> None:
    response.set_cookie(
        cookie_name("flow"),
        flow_cookie,
        max_age=max(0, int((expires_at - timezone.now()).total_seconds())),
        httponly=True,
        secure=cookie_secure(),
        samesite=cookie_samesite(),
        path=cookie_path("flow"),
    )


def _flow_ttl() -> int:
    return flow_ttl_seconds()
