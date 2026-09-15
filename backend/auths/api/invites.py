"""Public beta invite claim endpoint."""

from django.conf import settings
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from ninja_extra import ControllerBase, api_controller, http_post

from auths.api.common import (
    _auth_rate_limit_identity,
    _railway_auth_admission_allowed,
    _require_origin,
    _set_auth_throttle_cookie,
    error_json,
    error_responses,
    success_json,
)
from auths.api.schemas import (
    ClaimInviteRequest,
    ClaimInviteResponse,
    SuccessResponse,
)
from auths.config import (
    invite_claim_global_limit,
    invite_claim_limit,
    invite_claim_rate_limit_period_seconds,
)
from auths.exceptions import InviteUnavailable, InviteValidation
from auths.services.invites import claim_invite
from auths.throttle import ThrottleExceeded, ThrottleUnavailable, check_rate_limit


def _no_store(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


def _throttled() -> HttpResponse:
    response = error_json("throttled", "try again later", 429)
    response["Retry-After"] = "60"
    return response


@api_controller("/auths/invites", tags=["Authentication"])
class InviteController(ControllerBase):
    @http_post(
        "/claim",
        response={
            200: SuccessResponse[ClaimInviteResponse],
            **error_responses(403, 409, 422, 429, 503),
        },
    )
    def claim(self, request: HttpRequest, payload: ClaimInviteRequest):
        rejected = _require_origin(request)
        if rejected:
            return _no_store(rejected)
        if not _railway_auth_admission_allowed(request):
            return _no_store(_throttled())
        try:
            identity = _auth_rate_limit_identity(request)
            period = invite_claim_rate_limit_period_seconds()
            if identity:
                check_rate_limit(
                    scope="invite-claim-identity",
                    identity=identity,
                    limit=invite_claim_limit(),
                    period=period,
                )
            check_rate_limit(
                scope="invite-claim-global-admission",
                identity="all",
                limit=None,
                period=period,
                global_limit=invite_claim_global_limit(),
                global_period=period,
                global_scope="invite-claim-global",
            )
        except ThrottleExceeded:
            return _no_store(_throttled())
        except ThrottleUnavailable:
            return _no_store(
                error_json("throttle_unavailable", "authentication unavailable", 503)
            )
        try:
            claim_invite(code=payload.code, email=payload.email)
        except InviteValidation:
            return _no_store(
                error_json("validation_error", "request validation failed", 422)
            )
        except InviteUnavailable:
            return _no_store(
                error_json(
                    "invite_unavailable",
                    "This invite is unavailable. Check the code or contact the person who invited you.",
                    409,
                )
            )
        except DatabaseError:
            return _no_store(
                error_json("auth_unavailable", "authentication unavailable", 503)
            )
        response = success_json(
            ClaimInviteResponse(),
            "Invite claimed",
        )
        if getattr(settings, "ALLIES_RAILWAY_PROXY_MODE", False):
            _set_auth_throttle_cookie(response, request)
        return _no_store(response)
