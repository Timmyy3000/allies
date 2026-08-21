"""Private self-avatar lifecycle routes."""

from django.http import HttpRequest, HttpResponse
from ninja_extra import ControllerBase, api_controller, http_delete, http_get, http_post

from auths.api.common import (
    _domain_status,
    _require_origin,
    _session,
    error_json,
    error_responses,
    success_json,
)
from auths.api.schemas import (
    AvatarPrepareRequest,
    AvatarResponse,
    PreparedAvatarResponse,
    SuccessResponse,
)
from auths.exceptions import AuthDomainError, SessionInvalid
from auths.services.avatars import (
    complete_avatar_upload,
    delete_current_avatar,
    prepare_avatar_upload,
    signed_avatar_read,
)
from auths.throttle import ThrottleExceeded, ThrottleUnavailable, check_rate_limit


@api_controller("/auths", tags=["User Profile"])
class AvatarController(ControllerBase):
    @http_post(
        "/me/avatar/uploads",
        response={
            201: SuccessResponse[PreparedAvatarResponse],
            **error_responses(401, 403, 415, 422, 429, 500, 503),
        },
    )
    def prepare(self, request: HttpRequest, payload: AvatarPrepareRequest):
        rejected = _require_origin(request, allow_native_bearer=True)
        if rejected:
            return rejected
        try:
            session = _session(request)
            check_rate_limit(
                scope="avatar-prepare",
                identity=session.user.public_id,
                limit=10,
                period=3600,
            )
            prepared = prepare_avatar_upload(
                user=session.user,
                content_type=payload.content_type,
                size=payload.size,
                sha256=payload.sha256,
            )
        except ThrottleExceeded:
            return error_json("throttled", "try again later", 429)
        except ThrottleUnavailable:
            return error_json("throttle_unavailable", "storage unavailable", 503)
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except RuntimeError:
            return error_json("storage_unavailable", "avatar storage unavailable", 503)
        except AuthDomainError as exc:
            code = getattr(exc, "code", "validation_error")
            return error_json(code, "avatar request invalid", _domain_status(code, 422))
        return success_json(
            PreparedAvatarResponse(
                asset_id=prepared.asset.public_id,
                upload_url=prepared.upload_url,
                headers=prepared.headers,
                expires_at=prepared.expires_at,
            ),
            "Avatar upload prepared",
            status=201,
        )

    @http_post(
        "/me/avatar/{asset_id}/complete",
        response={
            200: SuccessResponse[AvatarResponse],
            **error_responses(401, 403, 404, 409, 422, 429, 500, 503),
        },
    )
    def complete(self, request: HttpRequest, asset_id: str):
        rejected = _require_origin(request, allow_native_bearer=True)
        if rejected:
            return rejected
        try:
            session = _session(request)
            check_rate_limit(
                scope="avatar-complete",
                identity=session.user.public_id,
                limit=20,
                period=3600,
            )
            ready = complete_avatar_upload(user=session.user, asset_id=asset_id)
            url, expires = signed_avatar_read(user=session.user)
        except ThrottleExceeded:
            return error_json("throttled", "try again later", 429)
        except ThrottleUnavailable:
            return error_json("throttle_unavailable", "storage unavailable", 503)
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except RuntimeError:
            return error_json("storage_unavailable", "avatar storage unavailable", 503)
        except AuthDomainError as exc:
            code = getattr(exc, "code", "avatar_invalid")
            return error_json(code, "avatar unavailable", _domain_status(code, 422))
        return success_json(
            AvatarResponse(asset_id=ready.asset.public_id, url=url, expires_at=expires),
            "Avatar completed",
        )

    @http_get(
        "/me/avatar/read",
        response={
            200: SuccessResponse[AvatarResponse],
            **error_responses(401, 404, 500, 503),
        },
    )
    def read(self, request: HttpRequest):
        try:
            session = _session(request)
            url, expires = signed_avatar_read(user=session.user)
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except RuntimeError:
            return error_json("storage_unavailable", "avatar storage unavailable", 503)
        except AuthDomainError as exc:
            code = getattr(exc, "code", "avatar_absent")
            return error_json(code, "avatar unavailable", _domain_status(code, 404))
        return success_json(
            AvatarResponse(asset_id="", url=url, expires_at=expires),
            "Avatar read prepared",
        )

    @http_delete(
        "/me/avatar",
        response={204: None, **error_responses(401, 403, 404, 409, 500, 503)},
    )
    def delete(self, request: HttpRequest):
        rejected = _require_origin(request, allow_native_bearer=True)
        if rejected:
            return rejected
        try:
            session = _session(request)
            delete_current_avatar(session.user)
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except AuthDomainError as exc:
            code = getattr(exc, "code", "avatar_invalid")
            return error_json(code, "avatar unavailable", _domain_status(code, 409))
        return HttpResponse(status=204)
