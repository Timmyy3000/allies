"""Refresh, logout, and session-cookie routes."""

from django.http import HttpRequest, HttpResponse
from ninja_extra import ControllerBase, api_controller, http_post

from auths.api.common import (
    _clear_auth_cookies,
    _client_identity,
    _require_origin,
    _set_session_cookies,
    error_json,
    error_responses,
)
from auths.config import cookie_name
from auths.exceptions import SessionInvalid
from auths.services.sessions import (
    authenticate_access,
    logout_session,
    refresh_family_public_id,
    rotate_refresh,
)
from auths.throttle import ThrottleExceeded, ThrottleUnavailable, check_rate_limit


@api_controller("/auths", tags=["Authentication"])
class SessionController(ControllerBase):
    @http_post(
        "/refresh",
        response={204: None, **error_responses(401, 429, 500, 503)},
    )
    def refresh(self, request: HttpRequest):
        rejected = _require_origin(request)
        if rejected:
            return rejected
        raw = request.COOKIES.get(cookie_name("refresh"))
        if not raw:
            return error_json("session_invalid", "session invalid", 401)
        try:
            check_rate_limit(
                scope="refresh-ip",
                identity=_client_identity(request),
                limit=20,
                period=60,
            )
            family_id = refresh_family_public_id(raw)
            check_rate_limit(
                scope="refresh-family",
                identity=family_id,
                limit=20,
                period=60,
            )
        except ThrottleExceeded:
            return error_json("throttled", "try again later", 429)
        except ThrottleUnavailable:
            return error_json("throttle_unavailable", "authentication unavailable", 503)
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        try:
            issued = rotate_refresh(raw)
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        response = HttpResponse(status=204)
        _set_session_cookies(response, issued)
        return response

    @http_post(
        "/logout",
        response={204: None, **error_responses(403, 500)},
    )
    def logout(self, request: HttpRequest):
        rejected = _require_origin(request)
        if rejected:
            return rejected
        access = None
        try:
            raw_access = request.COOKIES.get(cookie_name("access"))
            if raw_access:
                access = authenticate_access(raw_access)
        except SessionInvalid:
            access = None
        logout_session(
            access=access, refresh=request.COOKIES.get(cookie_name("refresh"))
        )
        response = HttpResponse(status=204)
        _clear_auth_cookies(response)
        return response
