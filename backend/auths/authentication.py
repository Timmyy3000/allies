"""Cookie authentication adapter for controllers and future domains."""

from __future__ import annotations

from django.http import HttpRequest

from auths.config import cookie_name
from auths.exceptions import SessionInvalid
from auths.models import SessionClientKind
from auths.services.sessions import AuthenticatedSession, authenticate_access


def _bearer_token(request: HttpRequest) -> str | None:
    header = request.headers.get("Authorization")
    if header is None:
        return None
    if (
        not header.startswith("Bearer ")
        or header.count(" ") != 1
        or not header[7:]
        or len(header[7:]) > 4096
    ):
        raise SessionInvalid("authorization header malformed")
    return header[7:]


def resolve_request_session(request: HttpRequest) -> AuthenticatedSession:
    """Resolve exactly one browser-cookie or native-bearer transport."""

    raw_cookie = request.COOKIES.get(cookie_name("access"))
    raw_bearer = _bearer_token(request)
    if raw_cookie and raw_bearer:
        raise SessionInvalid("mixed session transports")
    if raw_bearer:
        return authenticate_access(
            raw_bearer, expected_client_kind=SessionClientKind.NATIVE
        )
    if raw_cookie:
        return authenticate_access(
            raw_cookie, expected_client_kind=SessionClientKind.BROWSER
        )
    raise SessionInvalid("session invalid")


def authenticate_request(request: HttpRequest) -> AuthenticatedSession:
    return resolve_request_session(request)


class SessionCookieAuthentication:
    """Ninja-compatible callable that returns a live session or ``None``."""

    def __call__(self, request: HttpRequest) -> AuthenticatedSession | None:
        try:
            return authenticate_request(request)
        except SessionInvalid:
            return None
