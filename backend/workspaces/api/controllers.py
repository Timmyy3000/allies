"""Workspace-scoped HTTP controller."""

from django.http import HttpRequest
from ninja_extra import ControllerBase, api_controller, http_get

from auths.api.common import _session, error_json, error_responses, success_json
from auths.api.schemas import SuccessResponse
from auths.exceptions import SessionInvalid, WorkspaceAccessDenied
from workspaces.api.schemas import WorkspaceContextResponse
from workspaces.capabilities import Capability, capabilities_for_role
from workspaces.services.access import require_workspace_capability


@api_controller("/workspaces", tags=["Workspaces"])
class WorkspaceController(ControllerBase):
    @http_get(
        "/{workspace_id}",
        response={
            200: SuccessResponse[WorkspaceContextResponse],
            **error_responses(401, 404, 500),
        },
    )
    def context(self, request: HttpRequest, workspace_id: str):
        try:
            session = _session(request)
            context = require_workspace_capability(
                user=session.user,
                workspace_id=workspace_id,
                capability=Capability.WORKSPACE_READ,
            )
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except (KeyError, WorkspaceAccessDenied, ValueError):
            return error_json("workspace_denied", "workspace unavailable", 404)
        return success_json(
            WorkspaceContextResponse(
                id=context.workspace.public_id,
                name=context.workspace.name,
                role=context.membership.role,
                capabilities=list(capabilities_for_role(context.membership.role)),
            ),
            "Workspace loaded",
        )
