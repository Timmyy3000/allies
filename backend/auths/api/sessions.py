"""Refresh, logout, and session-cookie routes."""

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from ninja_extra import ControllerBase, api_controller, http_post

from auths.api.common import (
    _auth_rate_limit_identity,
    _clear_auth_cookies,
    _railway_auth_admission_allowed,
    _require_origin,
    _set_auth_throttle_cookie,
    _set_session_cookies,
    error_json,
    error_responses,
)
from auths.config import cookie_name
from auths.exceptions import SessionInvalid
from auths.models import SessionClientKind
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
        response={204: None, **error_responses(401, 403, 429, 500, 503)},
    )
    def refresh(self, request: HttpRequest):
        rejected = _require_origin(request)
        if rejected:
            return rejected
        raw = request.COOKIES.get(cookie_name("refresh"))
        if not raw:
            return error_json("session_invalid", "session invalid", 401)
        try:
            if not _railway_auth_admission_allowed(request):
                return error_json("throttled", "try again later", 429)
            identity = _auth_rate_limit_identity(request)
            if identity:
                check_rate_limit(
                    scope="refresh-ip",
                    identity=identity,
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
            issued = rotate_refresh(raw, expected_client_kind=SessionClientKind.BROWSER)
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        response = HttpResponse(status=204)
        _set_session_cookies(response, issued)
        if getattr(settings, "ALLIES_RAILWAY_PROXY_MODE", False):
            _set_auth_throttle_cookie(response, request)
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
                access = authenticate_access(
                    raw_access, expected_client_kind=SessionClientKind.BROWSER
                )
        except SessionInvalid:
            access = None
        logout_session(
            access=access,
            refresh=request.COOKIES.get(cookie_name("refresh")),
            expected_client_kind=SessionClientKind.BROWSER,
        )
        response = HttpResponse(status=204)
        _clear_auth_cookies(response)
        return response
