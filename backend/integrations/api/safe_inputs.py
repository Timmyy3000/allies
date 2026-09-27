"""Safe input and Ally browser routes for Interface.

Values are write-only: no route ever returns a username or password.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest
from ninja import Field, Schema
from ninja_extra import (
    ControllerBase,
    api_controller,
    http_delete,
    http_get,
    http_patch,
    http_post,
)

from auths.api.common import _require_origin, _session, error_json, success_json
from auths.exceptions import SessionInvalid, WorkspaceAccessDenied
from common.uuids import CanonicalUUID
from integrations.exceptions import IntegrationInvalid
from integrations.services import browser, safe_inputs
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability


class SafeInputValues(Schema):
    name: str | None = Field(default=None, max_length=80)
    website: str | None = Field(default=None, max_length=253)
    username: str | None = Field(default=None, max_length=512)
    password: str | None = Field(default=None, max_length=512)


class RequestDecision(SafeInputValues):
    decision: Literal["allow", "deny"]


class SafeInputOut(Schema):
    id: UUID
    name: str
    website: str
    ally_ids: list[UUID]
    updated_at: datetime


class RequestOut(Schema):
    id: UUID
    ally_id: UUID
    kind: Literal["new", "access"]
    safe_input_id: UUID | None
    name: str
    website: str
    created_at: datetime


class BrowserSessionOut(Schema):
    live_url: str
    expires_at: datetime


def _request_out(row) -> dict:
    return RequestOut(
        id=row.id,
        ally_id=row.ally_id,
        kind="access" if row.safe_input_id else "new",
        safe_input_id=row.safe_input_id,
        name=row.name,
        website=row.website,
        created_at=row.created_at,
    )


@api_controller("/workspaces/{workspace_id}", tags=["Safe inputs"])
class SafeInputController(ControllerBase):
    def _run(self, request, workspace_id, work):
        if rejected := _require_origin(request, allow_native_bearer=True):
            return rejected
        try:
            session = _session(request)
            require_workspace_capability(
                user=session.user,
                workspace_id=workspace_id,
                capability=Capability.WORKSPACE_WRITE,
            )
            return work(session.user)
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except (WorkspaceAccessDenied, ObjectDoesNotExist):
            return error_json("not_found", "not found", 404)
        except IntegrationInvalid as exc:
            return error_json("validation_error", str(exc), 422)

    @http_get("/safe-inputs")
    def list_safe_inputs(self, request: HttpRequest, workspace_id: CanonicalUUID):
        return self._run(
            request,
            workspace_id,
            lambda user: success_json(
                [
                    SafeInputOut(**row)
                    for row in safe_inputs.workspace_safe_inputs(workspace_id)
                ],
                "Safe inputs",
            ),
        )

    @http_get("/safe-input-requests")
    def list_requests(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        ally_id: UUID | None = None,
    ):
        return self._run(
            request,
            workspace_id,
            lambda user: success_json(
                [
                    _request_out(r)
                    for r in safe_inputs.pending_requests(workspace_id, ally_id)
                ],
                "Pending Safe input requests",
            ),
        )

    @http_post("/safe-input-requests/{request_id}")
    def resolve_request(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        request_id: UUID,
        payload: RequestDecision,
    ):
        def work(user):
            row = safe_inputs.resolve_request(
                workspace_id,
                request_id,
                allow=payload.decision == "allow",
                user=user,
                fields=payload.model_dump(exclude={"decision"}, exclude_none=True),
            )
            return success_json({"status": row.status}, "Request resolved")

        return self._run(request, workspace_id, work)

    @http_patch("/safe-inputs/{safe_input_id}")
    def update_safe_input(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        safe_input_id: UUID,
        payload: SafeInputValues,
    ):
        def work(user):
            safe_inputs.update_safe_input(
                workspace_id, safe_input_id, payload.model_dump(exclude_none=True)
            )
            return success_json({"id": safe_input_id}, "Safe input updated")

        return self._run(request, workspace_id, work)

    @http_delete("/safe-inputs/{safe_input_id}")
    def delete_safe_input(
        self, request: HttpRequest, workspace_id: CanonicalUUID, safe_input_id: UUID
    ):
        def work(user):
            safe_inputs.delete_safe_input(workspace_id, safe_input_id)
            return success_json({"id": safe_input_id}, "Safe input deleted")

        return self._run(request, workspace_id, work)

    @http_delete("/safe-inputs/{safe_input_id}/grants/{ally_id}")
    def revoke_grant(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        safe_input_id: UUID,
        ally_id: UUID,
    ):
        def work(user):
            safe_inputs.revoke_grant(workspace_id, safe_input_id, ally_id)
            return success_json({"id": safe_input_id}, "Access revoked")

        return self._run(request, workspace_id, work)

    @http_get("/allies/{ally_id}/browser-session")
    def browser_session(
        self, request: HttpRequest, workspace_id: CanonicalUUID, ally_id: UUID
    ):
        def work(user):
            session = (
                browser.open_sessions(workspace_id=workspace_id, ally_id=ally_id)
                .exclude(live_url="")
                .latest("started_at")
            )
            return success_json(
                BrowserSessionOut(
                    live_url=session.live_url, expires_at=session.expires_at
                ),
                "Browser session",
            )

        return self._run(request, workspace_id, work)
