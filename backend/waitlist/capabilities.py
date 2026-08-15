"""Browser capability and CSRF cookie helpers for the waitlist boundary."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token

from .exceptions import DraftUnavailable


def _capability_key() -> bytes:
    configured = str(getattr(settings, "ALLIES_WAITLIST_CAPABILITY_KEY", ""))
    if configured:
        return configured.encode()
    if getattr(settings, "DEBUG", True) and not getattr(
        settings, "ALLIES_WAITLIST_ENABLED", False
    ):
        # Disabled local development may still exercise pure capability
        # helpers. Never make this process-local convenience available while
        # the waitlist is enabled.
        return _LOCAL_CAPABILITY_KEY
    return b""


_LOCAL_CAPABILITY_KEY = secrets.token_bytes(32)
_CAPABILITY_CLOCK_SKEW_SECONDS = 30


def capability_digest(raw: str | bytes) -> str:
    value = raw.encode() if isinstance(raw, str) else raw
    if isinstance(raw, str):
        parsed = _parse_capability(raw)
        if parsed and _capability_signature_valid(raw):
            value = parsed[1].encode()
    key = _capability_key()
    if not key:
        raise DraftUnavailable("waitlist capability unavailable")
    return hmac.new(key, value, hashlib.sha256).hexdigest()


def _sign_capability(nonce: str) -> str:
    key = _capability_key()
    if not key:
        raise DraftUnavailable("waitlist capability unavailable")
    issued_at = str(int(time.time()))
    payload = f"{issued_at}.{nonce}"
    signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _parse_capability(value: str) -> tuple[int, str, str] | None:
    try:
        issued_at, nonce, signature = value.split(".", 2)
        issued_at_int = int(issued_at)
    except (AttributeError, TypeError, ValueError):
        return None
    if not nonce or not signature:
        return None
    return issued_at_int, nonce, signature


def _capability_signature_valid(value: str) -> bool:
    parsed = _parse_capability(value)
    key = _capability_key()
    if not parsed or not key:
        return False
    issued_at, nonce, signature = parsed
    expected = hmac.new(
        key, f"{issued_at}.{nonce}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def _capability_cookie_valid(value: str) -> bool:
    """Accept only unexpired capabilities signed by this Cloud deployment."""

    parsed = _parse_capability(value)
    if not parsed or not _capability_signature_valid(value):
        return False
    age = time.time() - parsed[0]
    ttl_seconds = int(settings.ALLIES_WAITLIST_CAPABILITY_TTL_SECONDS)
    return -_CAPABILITY_CLOCK_SKEW_SECONDS <= age <= ttl_seconds


def new_capability() -> str:
    return _sign_capability(secrets.token_urlsafe(32))


def refresh_capability(raw: str, *, validated: bool = False) -> str:
    """Re-sign a valid capability nonce so active drafts keep a sliding window.

    ``validated`` is reserved for request paths that already accepted this
    cookie through :func:`resolve_capability`.  A long-running mutation can
    cross the TTL boundary after that check; rechecking the age here would
    rotate the nonce and orphan the draft that the mutation just changed.
    Signature validation still runs before any nonce is re-signed.
    """

    parsed = _parse_capability(raw)
    if not parsed or not _capability_signature_valid(raw):
        return new_capability()
    if not validated and not _capability_cookie_valid(raw):
        return new_capability()
    return _sign_capability(parsed[1])


def capability_cookie_name() -> str:
    return str(
        getattr(
            settings, "ALLIES_WAITLIST_CAPABILITY_COOKIE", "allies_waitlist_capability"
        )
    )


def capability_cookie_path() -> str:
    return str(
        getattr(
            settings,
            "ALLIES_WAITLIST_CAPABILITY_COOKIE_PATH",
            "/api/v1/waitlist/",
        )
    )


@dataclass(frozen=True)
class CapabilityResolution:
    digest: str | None
    issue_cookie: str | None = None
    rotate_cookie: bool = False
    expired_digest: str | None = None


def resolve_capability(request: HttpRequest) -> CapabilityResolution:
    """Return only the keyed digest; never return the browser secret to callers."""

    raw = request.COOKIES.get(capability_cookie_name(), "")
    if not raw:
        return CapabilityResolution(None)
    if not isinstance(raw, str) or len(raw) > 512:
        return CapabilityResolution(
            None, issue_cookie=new_capability(), rotate_cookie=True
        )
    parsed = _parse_capability(raw)
    if not parsed or not _capability_signature_valid(raw):
        return CapabilityResolution(
            None, issue_cookie=new_capability(), rotate_cookie=True
        )
    if not _capability_cookie_valid(raw):
        age = time.time() - parsed[0]
        expired_digest = None
        if age > int(settings.ALLIES_WAITLIST_CAPABILITY_TTL_SECONDS):
            try:
                expired_digest = capability_digest(raw)
            except DraftUnavailable:
                pass
        return CapabilityResolution(
            None,
            issue_cookie=new_capability(),
            rotate_cookie=True,
            expired_digest=expired_digest,
        )
    try:
        digest = capability_digest(raw)
    except (TypeError, ValueError, DraftUnavailable):
        return CapabilityResolution(
            None, issue_cookie=new_capability(), rotate_cookie=True
        )
    return CapabilityResolution(digest)


def require_capability(request: HttpRequest) -> str:
    resolution = resolve_capability(request)
    if not resolution.digest:
        raise DraftUnavailable("waitlist draft unavailable")
    return resolution.digest


def set_capability_cookie(response: HttpResponse, raw: str) -> None:
    response.set_cookie(
        capability_cookie_name(),
        raw,
        max_age=int(settings.ALLIES_WAITLIST_CAPABILITY_TTL_SECONDS),
        httponly=True,
        secure=bool(
            getattr(settings, "ALLIES_WAITLIST_COOKIE_SECURE", not settings.DEBUG)
        ),
        samesite=str(getattr(settings, "ALLIES_WAITLIST_COOKIE_SAMESITE", "Lax")),
        path=capability_cookie_path(),
    )


def clear_capability_cookie(response: HttpResponse) -> None:
    response.delete_cookie(capability_cookie_name(), path=capability_cookie_path())


def set_csrf_cookie(response: HttpResponse, request: HttpRequest) -> str:
    token = get_token(request)
    response.set_cookie(
        getattr(settings, "CSRF_COOKIE_NAME", "csrftoken"),
        token,
        max_age=getattr(settings, "CSRF_COOKIE_AGE", 31449600),
        httponly=False,
        secure=bool(getattr(settings, "CSRF_COOKIE_SECURE", not settings.DEBUG)),
        samesite=str(getattr(settings, "CSRF_COOKIE_SAMESITE", "Lax")),
        path=str(getattr(settings, "CSRF_COOKIE_PATH", "/api/")),
    )
    return token
