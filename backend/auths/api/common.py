"""Shared HTTP concerns for the capability-owned authentication controllers."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import threading
import time
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
    digest_key,
    flow_ttl_seconds,
    native_global_rate_limit,
    native_rate_limit,
    native_rate_limit_period_seconds,
)
from auths.exceptions import NativeIdentityUnavailable, SessionInvalid
from auths.throttle import check_rate_limit


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
        "auth_unavailable": 503,
        "exchange_invalid": 400,
        "exchange_replayed": 409,
        "pkce_required": 400,
        "flow_in_progress": 409,
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


def _require_origin(
    request: HttpRequest, *, allow_native_bearer: bool = False
) -> JsonResponse | None:
    if (
        allow_native_bearer
        and request.headers.get("Authorization")
        and not request.COOKIES.get(cookie_name("access"))
    ):
        from auths.authentication import resolve_request_session

        try:
            resolve_request_session(request)
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        else:
            return None
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


def _session(request: HttpRequest, *, expected_client_kind: str | None = None):
    from auths.authentication import resolve_request_session

    session = resolve_request_session(request)
    if (
        expected_client_kind is not None
        and session.family.client_kind != expected_client_kind
    ):
        raise SessionInvalid("session transport mismatch")
    return session


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


def native_rate_limit_identity(request: HttpRequest) -> str:
    """Return the only non-cookie identity accepted by native auth."""

    if getattr(settings, "ALLIES_RAILWAY_PROXY_MODE", False):
        trusted = set(getattr(settings, "ALLIES_TRUSTED_PROXY_IPS", ()))
        if request.META.get("REMOTE_ADDR", "") not in trusted:
            raise NativeIdentityUnavailable("native requester identity unavailable")
        raw = request.headers.get("X-Real-IP", "")
        if not isinstance(raw, str) or not raw.strip() or "," in raw:
            raise NativeIdentityUnavailable("native requester identity unavailable")
    else:
        raw = request.META.get("REMOTE_ADDR", "")
    try:
        address = ipaddress.ip_address(raw.strip())
    except (AttributeError, ValueError) as exc:
        raise NativeIdentityUnavailable(
            "native requester identity unavailable"
        ) from exc
    prefix = 24 if address.version == 4 else 64
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))


def check_native_rate_limit(
    request: HttpRequest, operation: str, *, include_global: bool = True
) -> str:
    """Apply native requester throttling, optionally including the global ceiling."""

    identity = native_rate_limit_identity(request)
    check_rate_limit(
        scope=f"native-{operation}",
        identity=identity,
        limit=native_rate_limit(operation),
        period=native_rate_limit_period_seconds(),
        global_limit=native_global_rate_limit() if include_global else None,
        global_period=native_rate_limit_period_seconds() if include_global else None,
        global_scope="native-global" if include_global else None,
    )
    return identity


def check_native_global_rate_limit(request: HttpRequest) -> None:
    """Charge the shared native ceiling after cheap request validation."""

    native_rate_limit_identity(request)
    check_rate_limit(
        scope="native-global-admission",
        identity="all",
        limit=None,
        period=native_rate_limit_period_seconds(),
        global_limit=native_global_rate_limit(),
        global_period=native_rate_limit_period_seconds(),
        global_scope="native-global",
    )


def _auth_rate_limit_identity(request: HttpRequest) -> str:
    """Provide a server-issued browser key when Railway hides the original IP.

    The CSRF cookie remains a separate double-submit token and is deliberately
    not used as an abuse-control identity. Railway requests without a valid
    server-issued throttle cookie use the bounded bootstrap admission path.
    """

    if getattr(settings, "ALLIES_RAILWAY_PROXY_MODE", False):
        throttle_cookie = request.COOKIES.get(cookie_name("throttle"), "")
        if _auth_throttle_cookie_valid(throttle_cookie):
            digest = hmac.new(
                digest_key(), throttle_cookie.encode(), hashlib.sha256
            ).hexdigest()[:24]
            return f"browser:{digest}"
        return ""
    return _client_identity(request)


_AUTH_THROTTLE_COOKIE_TTL_SECONDS = 30 * 24 * 60 * 60
_RAILWAY_AUTH_BOOTSTRAP_CAPACITY = 30.0
_RAILWAY_AUTH_BOOTSTRAP_REFILL_PER_SECOND = 1.0
_railway_auth_admission_lock = threading.Lock()
_railway_auth_bootstrap_tokens = _RAILWAY_AUTH_BOOTSTRAP_CAPACITY
_railway_auth_bootstrap_last_at = 0.0


def _new_auth_throttle_cookie() -> str:
    issued_at = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    payload = f"{issued_at}.{nonce}"
    signature = hmac.new(digest_key(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _auth_throttle_cookie_valid(value: str) -> bool:
    try:
        issued_at, nonce, signature = value.split(".", 2)
        issued_at_int = int(issued_at)
    except (AttributeError, TypeError, ValueError):
        return False
    if not nonce or not signature:
        return False
    age = time.time() - issued_at_int
    if age < 0 or age > _AUTH_THROTTLE_COOKIE_TTL_SECONDS:
        return False
    payload = f"{issued_at}.{nonce}"
    expected = hmac.new(digest_key(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def _set_auth_throttle_cookie(response: HttpResponse, request: HttpRequest) -> None:
    name = cookie_name("throttle")
    current = request.COOKIES.get(name, "")
    if _auth_throttle_cookie_valid(current):
        return
    response.set_cookie(
        name,
        _new_auth_throttle_cookie(),
        max_age=_AUTH_THROTTLE_COOKIE_TTL_SECONDS,
        httponly=True,
        secure=cookie_secure(),
        samesite=cookie_samesite(),
        path=cookie_path("throttle"),
    )


def _railway_auth_admission_allowed(request: HttpRequest) -> bool:
    """Bound only unbound Railway callers while preserving browser fairness.

    Valid server-issued throttle cookies are governed by their cache-backed
    per-browser buckets. Missing, expired, or forged cookies use a small
    process-local bootstrap bucket so cookie rotation cannot create unbounded
    auth work, without making normal authenticated browser traffic share one
    global one-request-per-second gate.
    """

    if not getattr(settings, "ALLIES_RAILWAY_PROXY_MODE", False):
        return True
    if _auth_throttle_cookie_valid(request.COOKIES.get(cookie_name("throttle"), "")):
        return True
    global _railway_auth_bootstrap_last_at
    global _railway_auth_bootstrap_tokens
    now = time.monotonic()
    with _railway_auth_admission_lock:
        elapsed = max(0.0, now - _railway_auth_bootstrap_last_at)
        _railway_auth_bootstrap_tokens = min(
            _RAILWAY_AUTH_BOOTSTRAP_CAPACITY,
            _railway_auth_bootstrap_tokens
            + elapsed * _RAILWAY_AUTH_BOOTSTRAP_REFILL_PER_SECOND,
        )
        _railway_auth_bootstrap_last_at = now
        if _railway_auth_bootstrap_tokens < 1.0:
            return False
        _railway_auth_bootstrap_tokens -= 1.0
    return True


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
