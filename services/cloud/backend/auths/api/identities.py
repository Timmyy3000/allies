"""Authenticated external-identity linking route."""

from django.http import HttpRequest
from ninja_extra import ControllerBase, api_controller, http_post

from auths.api.common import (
    _csrf_binding,
    _domain_status,
    _request_origin,
    _require_origin,
    _session,
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
from auths.exceptions import AuthDomainError
from auths.models import FlowPurpose
from auths.providers.base import ProviderKey
from auths.services.flows import begin_auth_flow
from auths.throttle import ThrottleExceeded, ThrottleUnavailable, check_rate_limit


@api_controller("/auths", tags=["Authentication"])
class IdentityController(ControllerBase):
    @http_post(
        "/identities/{provider}/link",
        response={
            200: SuccessResponse[AuthorizationStartResponse],
            **error_responses(400, 401, 403, 404, 409, 422, 429, 500, 503),
        },
    )
    def link(self, request: HttpRequest, provider: str, payload: RedirectRequest):
        rejected = _require_origin(request)
        if rejected:
            return rejected
        trusted_origin = _request_origin(request)
        try:
            session = _session(request, expected_client_kind="browser")
            check_rate_limit(
                scope="link",
                identity=f"{session.user.id}:{provider}",
                limit=5,
                period=3600,
            )
            start = begin_auth_flow(
                provider=ProviderKey(provider),
                purpose=FlowPurpose.LINK,
                redirect_to=payload.redirect_to,
                trusted_origin=trusted_origin,
                browser_binding=_csrf_binding(request),
                user=session.user,
                family=session.family,
            )
        except ThrottleExceeded:
            return error_json("throttled", "try again later", 429)
        except ThrottleUnavailable:
            return error_json("throttle_unavailable", "authentication unavailable", 503)
        except AuthDomainError as exc:
            code = getattr(exc, "code", "session_invalid")
            return error_json(code, "link unavailable", _domain_status(code, 401))
        except (ValueError, KeyError):
            return error_json("session_invalid", "session invalid", 401)
        response = success_json(
            AuthorizationStartResponse(redirect_url=start.authorization_url),
            "Identity link started",
        )
        _set_flow_cookie(response, start.flow_cookie, start.expires_at)
        return response
