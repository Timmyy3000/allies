"""Self profile read/update routes."""

from django.http import HttpRequest
from ninja_extra import ControllerBase, api_controller, http_get, http_patch

from auths.api.common import (
    _domain_status,
    _require_origin,
    _session,
    error_json,
    error_responses,
    success_json,
)
from auths.api.schemas import (
    MeResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    SessionResponse,
    SuccessResponse,
    UserResponse,
    WorkspaceResponse,
)
from auths.exceptions import AuthDomainError, SessionInvalid
from auths.services.profiles import get_self_profile, update_display_name


def _me_response(result) -> MeResponse:
    return MeResponse(
        user=UserResponse(id=result.user_id),
        profile=ProfileResponse(
            display_name=result.profile.display_name,
            avatar_url=result.profile.avatar_url,
        ),
        session=SessionResponse(
            id=result.session.id,
            expires_at=result.session.expires_at,
        ),
        workspace=WorkspaceResponse(
            id=result.workspace.id,
            name=result.workspace.name,
            role=result.workspace.role,
            capabilities=list(result.workspace.capabilities),
        ),
    )


@api_controller("/auths", tags=["User Profile"])
class ProfileController(ControllerBase):
    @http_get(
        "/me",
        response={200: SuccessResponse[MeResponse], **error_responses(401, 500)},
    )
    def me(self, request: HttpRequest):
        try:
            result = get_self_profile(_session(request))
        except (AuthDomainError, SessionInvalid):
            return error_json("session_invalid", "session invalid", 401)
        return success_json(_me_response(result), "Profile loaded")

    @http_patch(
        "/me/profile",
        response={
            200: SuccessResponse[ProfileResponse],
            **error_responses(401, 403, 422, 429, 500),
        },
    )
    def profile(self, request: HttpRequest, payload: ProfileUpdateRequest):
        rejected = _require_origin(request)
        if rejected:
            return rejected
        try:
            session = _session(request)
            profile = update_display_name(session.user, payload.display_name)
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except AuthDomainError as exc:
            code = getattr(exc, "code", "validation_error")
            return error_json(code, "profile update invalid", _domain_status(code, 422))
        return success_json(
            ProfileResponse(display_name=profile.display_name),
            "Profile updated",
        )
