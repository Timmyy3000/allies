from django.http import HttpResponse
from ninja_extra import ControllerBase, api_controller, http_delete, http_get, http_post

from auths.api.common import (
    _require_origin,
    _session,
    error_json,
    error_responses,
    success_json,
)
from auths.api.schemas import SuccessResponse
from auths.exceptions import SessionInvalid, WorkspaceAccessDenied
from auths.throttle import ThrottleExceeded, ThrottleUnavailable, check_rate_limit
from common.uuids import CanonicalUUID
from common.vault import VaultUnavailable
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability

from .schemas import (
    PresenceReceipt,
    PushConfig,
    PushPresence,
    PushRegistration,
    RegisterPush,
    RevokePush,
)
from .services import (
    PushError,
    register_subscription,
    revoke_subscription,
    update_presence,
)
from .transport import PushInvalid, configuration


def _access(request, workspace_id, mutation=False):
    session = _session(request, expected_client_kind="browser")
    require_workspace_capability(
        user=session.user,
        workspace_id=workspace_id,
        capability=Capability.WORKSPACE_READ,
    )
    if mutation:
        rejected = _require_origin(request)
        if rejected:
            return None, rejected
    return session, None


def _error(exc):
    if isinstance(exc, SessionInvalid):
        return error_json("session_invalid", "session invalid", 401)
    if isinstance(exc, WorkspaceAccessDenied):
        return error_json("workspace_denied", "workspace denied", 403)
    if isinstance(exc, ThrottleExceeded):
        return error_json("throttled", "try again later", 429)
    if isinstance(exc, (ThrottleUnavailable, VaultUnavailable)):
        return error_json("push_unavailable", "push unavailable", 503)
    if isinstance(exc, PushInvalid):
        return error_json("push_invalid", "push request invalid", 422)
    return error_json(exc.code, "push request unavailable", exc.status)


ERRORS = error_responses(401, 403, 404, 409, 422, 429, 503)


@api_controller("/workspaces/{workspace_id}/push", tags=["Push notifications"])
class PushController(ControllerBase):
    @http_get("/config", response={200: SuccessResponse[PushConfig], **ERRORS})
    def config(self, request, workspace_id: CanonicalUUID):
        try:
            _access(request, workspace_id)
            config = configuration()
            response = success_json(
                PushConfig(
                    enabled=config is not None,
                    vapid_public_key=config[0] if config else None,
                ),
                "Push configuration",
            )
            response["Cache-Control"] = "no-store"
            return response
        except (SessionInvalid, WorkspaceAccessDenied) as exc:
            return _error(exc)

    @http_post(
        "/subscriptions", response={200: SuccessResponse[PushRegistration], **ERRORS}
    )
    def register(self, request, workspace_id: CanonicalUUID, payload: RegisterPush):
        try:
            session, rejected = _access(request, workspace_id, True)
            if rejected:
                return rejected
            check_rate_limit(
                scope="push-mutation",
                identity=str(session.user.id),
                limit=20,
                period=60,
            )
            return success_json(
                register_subscription(session.family, workspace_id, payload),
                "Push enabled",
            )
        except (
            SessionInvalid,
            WorkspaceAccessDenied,
            ThrottleExceeded,
            ThrottleUnavailable,
            VaultUnavailable,
            PushInvalid,
            PushError,
        ) as exc:
            return _error(exc)

    @http_post(
        "/subscriptions/{subscription_id}/presence",
        response={200: SuccessResponse[PresenceReceipt], **ERRORS},
    )
    def presence(
        self,
        request,
        workspace_id: CanonicalUUID,
        subscription_id: CanonicalUUID,
        payload: PushPresence,
    ):
        try:
            session, rejected = _access(request, workspace_id, True)
            if rejected:
                return rejected
            check_rate_limit(
                scope="push-presence-tab",
                identity=f"{session.user.id}:{subscription_id}:{payload.client_id}",
                limit=6,
                period=60,
            )
            check_rate_limit(
                scope="push-presence",
                identity=f"{session.user.id}:{subscription_id}",
                limit=60,
                period=60,
            )
            return success_json(
                update_presence(session.family, workspace_id, subscription_id, payload),
                "Push presence updated",
            )
        except (
            SessionInvalid,
            WorkspaceAccessDenied,
            ThrottleExceeded,
            ThrottleUnavailable,
            PushError,
        ) as exc:
            return _error(exc)

    @http_delete("/subscriptions/{subscription_id}", response={204: None, **ERRORS})
    def revoke(
        self,
        request,
        workspace_id: CanonicalUUID,
        subscription_id: CanonicalUUID,
        payload: RevokePush,
    ):
        try:
            session, rejected = _access(request, workspace_id, True)
            if rejected:
                return rejected
            check_rate_limit(
                scope="push-mutation",
                identity=str(session.user.id),
                limit=20,
                period=60,
            )
            revoke_subscription(
                session.family, workspace_id, subscription_id, payload.binding_id
            )
            return HttpResponse(status=204)
        except (
            SessionInvalid,
            WorkspaceAccessDenied,
            ThrottleExceeded,
            ThrottleUnavailable,
            PushError,
        ) as exc:
            return _error(exc)
