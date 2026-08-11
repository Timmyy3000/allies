"""Cookie authentication adapter for controllers and future domains."""

from __future__ import annotations

from django.http import HttpRequest

from auths.config import cookie_name
from auths.exceptions import SessionInvalid
from auths.services.sessions import AuthenticatedSession, authenticate_access


def authenticate_request(request: HttpRequest) -> AuthenticatedSession:
    raw = request.COOKIES.get(cookie_name("access"))
    if not raw:
        raise SessionInvalid("session invalid")
    return authenticate_access(raw)


class SessionCookieAuthentication:
    """Ninja-compatible callable that returns a live session or ``None``."""

    def __call__(self, request: HttpRequest) -> AuthenticatedSession | None:
        try:
            return authenticate_request(request)
        except SessionInvalid:
            return None
