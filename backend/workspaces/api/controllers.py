from django.http import HttpRequest, JsonResponse
from ninja_extra import ControllerBase, api_controller, http_get

from auths.config import cookie_name
from auths.exceptions import SessionInvalid, WorkspaceAccessDenied
from auths.services.sessions import authenticate_access
from workspaces.api.schemas import WorkspaceContextResponse
from workspaces.capabilities import Capability, capabilities_for_role
from workspaces.services.access import require_workspace_capability


@api_controller("/workspaces", tags=["workspaces"])
class WorkspaceController(ControllerBase):
    @http_get("/{workspace_id}")
    def context(self, request: HttpRequest, workspace_id: str):
        try:
            session = authenticate_access(request.COOKIES[cookie_name("access")])
            context = require_workspace_capability(
                actor=session.actor,
                workspace_id=workspace_id,
                capability=Capability.WORKSPACE_READ,
            )
        except (KeyError, SessionInvalid, WorkspaceAccessDenied, ValueError):
            return JsonResponse(
                {
                    "error": {
                        "code": "workspace_denied",
                        "message": "workspace unavailable",
                    }
                },
                status=404,
            )
        return JsonResponse(
            WorkspaceContextResponse(
                id=context.workspace.public_id,
                name=context.workspace.name,
                role=context.membership.role,
                capabilities=list(capabilities_for_role(context.membership.role)),
            ).model_dump()
        )
