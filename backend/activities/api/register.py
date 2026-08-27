import secrets

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from ninja import Query
from ninja_extra import ControllerBase, NinjaExtraAPI, api_controller, http_get

from allies.gateways.contracts import FoundryEventEnvelope
from auths.api.common import _session, error_json, error_responses, success_json
from auths.api.schemas import SuccessResponse
from auths.exceptions import SessionInvalid, WorkspaceAccessDenied
from common.uuids import CanonicalUUID

from ..exceptions import (
    ProjectionConflict,
    ProjectionInvalid,
    ProjectionNotFound,
    ProjectionSequenceGap,
)
from ..services.projection import project_foundry_event, read_activity_snapshot
from .schemas import ActivitySnapshotResponse


def _foundry_token_valid(request: HttpRequest) -> bool:
    value = request.headers.get("Authorization", "")
    configured = str(getattr(settings, "ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN", ""))
    if not configured or not value.startswith("Bearer "):
        return False
    token = value[7:]
    return bool(token) and secrets.compare_digest(token.encode(), configured.encode())


@api_controller("/workspaces/{workspace_id}", tags=["Activities"])
class ActivityController(ControllerBase):
    @http_get(
        "/conversations/{conversation_id}/activities",
        response={
            200: SuccessResponse[ActivitySnapshotResponse],
            **error_responses(401, 404, 422, 500),
        },
    )
    def snapshot(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        conversation_id: CanonicalUUID,
        limit: int = Query(200, ge=1, le=200),
    ):
        try:
            session = _session(request)
            result = read_activity_snapshot(
                user=session.user,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                limit=limit,
            )
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except (WorkspaceAccessDenied, ProjectionNotFound):
            return error_json("activity_unavailable", "activity unavailable", 404)
        except ProjectionInvalid:
            return error_json("validation_error", "request validation failed", 422)
        return success_json(
            ActivitySnapshotResponse(
                conversation_id=result.conversation.id,
                activities=[
                    {
                        "id": activity.id,
                        "message_id": activity.message_id,
                        "sequence": activity.sequence,
                        "conversation_turn_ordinal": activity.conversation_turn_ordinal,
                        "kind": activity.kind,
                        "text": activity.text,
                        "state": activity.state,
                        "created_at": activity.created_at,
                    }
                    for activity in result.activities
                ],
                state=result.state,
                last_contiguous_sequence=result.last_contiguous_sequence,
            ),
            "Activities loaded",
        )


def register(api: NinjaExtraAPI) -> None:
    @api.post(
        "/internal/foundry/events",
        auth=_foundry_token_valid,
    )
    def foundry_event(request: HttpRequest, payload: FoundryEventEnvelope):
        if not getattr(settings, "ALLIES_FOUNDRY_EXECUTION_ENABLED", False):
            return JsonResponse(
                {"event_id": str(payload.event_id), "status": "disabled"},
                status=503,
            )
        try:
            result = project_foundry_event(payload)
        except ProjectionNotFound:
            return JsonResponse(
                {"event_id": str(payload.event_id), "status": "unavailable"},
                status=404,
            )
        except ProjectionSequenceGap:
            return JsonResponse({"code": ProjectionSequenceGap.code}, status=409)
        except ProjectionConflict:
            return JsonResponse({"code": "conflict"}, status=409)
        except ProjectionInvalid:
            return JsonResponse(
                {"event_id": str(payload.event_id), "status": "invalid"},
                status=422,
            )
        return JsonResponse(
            {"event_id": str(result.event_id), "status": result.status},
            status=202,
        )

    api.register_controllers(ActivityController)
