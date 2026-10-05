"""Authentication start and provider callback routes."""

from urllib.parse import urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from ninja_extra import ControllerBase, api_controller, http_get, http_post

from auths.api.common import (
    _auth_rate_limit_identity,
    _csrf_binding,
    _domain_status,
    _railway_auth_admission_allowed,
    _request_origin,
    _require_origin,
    _set_auth_throttle_cookie,
    _set_flow_cookie,
    error_json,
    error_responses,
    success_json,
)
from auths.api.schemas import (
    AuthorizationStartResponse,
    RedirectRequest,
    SuccessResponse,
)
from auths.config import cookie_name, cookie_path
from auths.exceptions import AuthDomainError
from auths.models import FlowPurpose
from auths.providers.base import ProviderKey
from auths.services.flows import (
    begin_auth_flow,
    complete_auth_flow,
    flow_redirect_for_state,
)
from auths.throttle import ThrottleExceeded, ThrottleUnavailable, check_rate_limit


@api_controller("/auths", tags=["Authentication"])
class AuthenticationController(ControllerBase):
    @http_get("/csrf", response={204: None, **error_responses(429)})
    def csrf(self, request: HttpRequest):
        if not _railway_auth_admission_allowed(request):
            return error_json("throttled", "try again later", 429)
        response = HttpResponse(status=204)
        response["X-CSRFToken"] = get_token(request)
        if getattr(settings, "ALLIES_RAILWAY_PROXY_MODE", False):
            _set_auth_throttle_cookie(response, request)
        return response

    @http_post(
        "/sign-in/{provider}",
        response={
            200: SuccessResponse[AuthorizationStartResponse],
            **error_responses(400, 403, 404, 422, 429, 500, 503),
        },
    )
    def sign_in(self, request: HttpRequest, provider: str, payload: RedirectRequest):
        rejected = _require_origin(request)
        if rejected:
            return rejected
        trusted_origin = _request_origin(request)
        if not _railway_auth_admission_allowed(request):
            return error_json("throttled", "try again later", 429)
        try:
            identity = _auth_rate_limit_identity(request)
            if identity:
                check_rate_limit(
                    scope="sign-in",
                    identity=f"{identity}:{provider}",
                    limit=10,
                    period=60,
                )
        except ThrottleExceeded:
            return error_json("throttled", "try again later", 429)
        except ThrottleUnavailable:
            return error_json("throttle_unavailable", "authentication unavailable", 503)
        try:
            start = begin_auth_flow(
                provider=ProviderKey(provider),
                purpose=FlowPurpose.SIGN_IN,
                redirect_to=payload.redirect_to,
                trusted_origin=trusted_origin,
                browser_binding=_csrf_binding(request),
            )
        except (AuthDomainError, ValueError) as exc:
            code = getattr(exc, "code", "provider_unavailable")
            return error_json(code, "sign-in unavailable", _domain_status(code))
        response = success_json(
            AuthorizationStartResponse(redirect_url=start.authorization_url),
            "Sign-in started",
        )
        if getattr(settings, "ALLIES_RAILWAY_PROXY_MODE", False):
            _set_auth_throttle_cookie(response, request)
        _set_flow_cookie(response, start.flow_cookie, start.expires_at)
        return response

    @http_get(
        "/callback/{provider}",
        response={
            303: None,
            **error_responses(400, 404, 409, 500),
        },
    )
    def callback(
        self, request: HttpRequest, provider: str, code: str = "", state: str = ""
    ):
        flow_cookie = request.COOKIES.get(cookie_name("flow"))
        try:
            completion = complete_auth_flow(
                provider=ProviderKey(provider),
                state=state,
                code=code,
                browser_binding=_csrf_binding(request),
                flow_cookie=flow_cookie,
            )
        except (AuthDomainError, ValueError) as exc:
            error_code = getattr(exc, "code", "flow_invalid")
            target = flow_redirect_for_state(state)
            if target:
                parsed = urlsplit(target)
                error_query = urlencode({"auth_error": error_code})
                query = f"{parsed.query}&{error_query}" if parsed.query else error_query
                response = HttpResponse(status=303)
                response["Location"] = urlunsplit(
                    (
                        parsed.scheme,
                        parsed.netloc,
                        parsed.path,
                        query,
                        parsed.fragment,
                    )
                )
                response.delete_cookie(cookie_name("flow"), path=cookie_path("flow"))
                return response
            return error_json(
                error_code,
                "authentication failed",
                _domain_status(error_code),
            )
        response = HttpResponse(status=303)
        response["Location"] = completion.redirect_to
        if completion.session:
            from auths.api.common import _set_session_cookies

            _set_session_cookies(response, completion.session)
        response.delete_cookie(cookie_name("flow"), path=cookie_path("flow"))
        return response
