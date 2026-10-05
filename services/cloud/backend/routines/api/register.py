import secrets
from typing import Annotated
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import HttpRequest, JsonResponse
from ninja import Header, Query
from ninja_extra import (
    ControllerBase,
    NinjaExtraAPI,
    api_controller,
    http_get,
    http_post,
)
from pydantic import BaseModel, ConfigDict

from auths.api.common import (
    _require_origin,
    _session,
    error_json,
    error_responses,
    success_json,
)
from auths.api.schemas import SuccessResponse
from auths.exceptions import SessionInvalid, WorkspaceAccessDenied
from common.uuids import CanonicalUUID

from ..models import Routine
from ..services.approvals import (
    RoutineApprovalConflict,
    RoutineApprovalInvalid,
    RoutineApprovalUnauthorized,
    RoutineApprovalUnavailable,
    record_routine_approval_decision,
)
from ..services.management import (
    RoutineCursorInvalid,
    RoutineRevisionConflict,
    owner_routine,
    owner_routine_page,
)
from ..services.results import (
    RoutineResultConflict,
    RoutineResultEvent,
    RoutineResultInvalid,
    RoutineResultUnavailable,
    complete_pending_routine_results,
    project_routine_result,
)
from ..services.tools import execute_routine_tool
from .schemas import (
    RoutineApprovalDecisionRequest,
    RoutineApprovalResponse,
    RoutineDetailResponse,
    RoutinePageResponse,
    RoutineSummaryResponse,
)


def _foundry_token_valid(request: HttpRequest) -> bool:
    value = request.headers.get("Authorization", "")
    configured = str(getattr(settings, "ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN", ""))
    if not configured or not value.startswith("Bearer "):
        return False
    token = value[7:]
    return bool(token) and secrets.compare_digest(token.encode(), configured.encode())


def _summary(routine) -> RoutineSummaryResponse:
    return RoutineSummaryResponse(
        id=routine.id,
        responsible_ally_id=routine.ally_id,
        title=routine.title,
        schedule=routine.schedule,
        revision=routine.revision,
        schedule_generation=routine.schedule_generation,
        schedule_state=routine.state,
        next_run_at=routine.next_run_at,
        created_at=routine.created_at,
        updated_at=routine.updated_at,
    )


def _detail(routine) -> RoutineDetailResponse:
    return RoutineDetailResponse(
        **_summary(routine).model_dump(),
        workspace_id=routine.workspace_id,
        owner_user_id=routine.owner_id,
        binding_id=routine.binding_id,
        main_conversation_id=routine.main_conversation_id,
        execution_prompt=routine.execution_prompt,
    )


def _approval_response(result) -> RoutineApprovalResponse:
    return RoutineApprovalResponse(
        id=result.approval.id,
        routine_id=result.approval.routine_id,
        run_id=result.approval.run_id,
        approval_request_id=result.approval.approval_request_id,
        action_attempt_id=result.approval.action_attempt_id,
        execution_id=result.approval.execution_id,
        attempt_id=result.approval.attempt_id,
        generation=result.approval.generation,
        status=result.approval.status,
        decision=result.approval.decision or None,
        action_digest=result.approval.action_digest,
        expires_at=result.approval.expires_at,
        created_at=result.approval.created_at,
        decided_at=result.approval.decided_at,
        delivery_status=result.command.status,
        replayed=result.replayed,
    )


@api_controller("/workspaces/{workspace_id}/routines", tags=["Routines"])
class RoutineController(ControllerBase):
    @http_get(
        "",
        response={
            200: SuccessResponse[RoutinePageResponse],
            **error_responses(401, 404, 422, 500),
        },
    )
    def list(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = Query(None, max_length=512),
        ally_id: CanonicalUUID | None = None,
    ):
        try:
            session = _session(request)
            page = owner_routine_page(
                user=session.user,
                workspace_id=workspace_id,
                limit=limit,
                cursor=cursor,
                ally_id=ally_id,
            )
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except WorkspaceAccessDenied:
            return error_json("routine_unavailable", "routine page unavailable", 404)
        except RoutineCursorInvalid:
            return error_json("validation_error", "request validation failed", 422)
        return success_json(
            RoutinePageResponse(
                items=[_summary(routine) for routine in page.items],
                next_cursor=page.next_cursor,
            ),
            "Routines loaded",
        )

    @http_get(
        "/{routine_id}",
        response={
            200: SuccessResponse[RoutineDetailResponse],
            **error_responses(401, 404, 500),
        },
    )
    def detail(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        routine_id: CanonicalUUID,
    ):
        try:
            session = _session(request)
            routine = owner_routine(
                user=session.user,
                workspace_id=workspace_id,
                routine_id=routine_id,
                include_history=True,
            )
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except (WorkspaceAccessDenied, Routine.DoesNotExist):
            return error_json("routine_unavailable", "routine unavailable", 404)
        return success_json(_detail(routine), "Routine loaded")

    @http_post(
        "/{routine_id}/approvals/{approval_id}/decision",
        response={
            202: SuccessResponse[RoutineApprovalResponse],
            200: SuccessResponse[RoutineApprovalResponse],
            **error_responses(401, 403, 404, 409, 422, 500),
        },
    )
    def decide_approval(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        routine_id: CanonicalUUID,
        approval_id: CanonicalUUID,
        payload: RoutineApprovalDecisionRequest,
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                min_length=36,
                max_length=36,
                description="Stable UUID for repeating one routine approval decision.",
            ),
        ],
    ):
        if rejected := _require_origin(request, allow_native_bearer=True):
            return rejected
        try:
            session = _session(request)
            result = record_routine_approval_decision(
                user=session.user,
                workspace_id=workspace_id,
                routine_id=routine_id,
                approval_id=approval_id,
                decision=payload.decision,
                idempotency_key=idempotency_key,
            )
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except RoutineApprovalUnauthorized:
            return error_json("routine_approval_forbidden", "approval unavailable", 403)
        except RoutineApprovalUnavailable:
            return error_json(
                "routine_approval_unavailable", "approval unavailable", 404
            )
        except RoutineApprovalConflict:
            return error_json("routine_approval_conflict", "request conflicts", 409)
        except RoutineApprovalInvalid:
            return error_json("validation_error", "request validation failed", 422)
        return success_json(
            _approval_response(result),
            "Routine approval decision recorded",
            status=200 if result.replayed else 202,
        )


class RoutineToolEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: UUID
    binding_id: UUID
    command_fingerprint: str
    call_id: UUID
    arguments: dict


def register(api: NinjaExtraAPI) -> None:
    @api.post("/internal/foundry/routines/tool", auth=_foundry_token_valid)
    def routine_tool(request: HttpRequest, payload: RoutineToolEnvelope):
        if len(request.body) > 64 * 1024:
            return JsonResponse({"error": "request_too_large"}, status=413)
        try:
            result = execute_routine_tool(**payload.model_dump())
        except (ObjectDoesNotExist, PermissionError, WorkspaceAccessDenied):
            return JsonResponse({"error": "routine_unavailable"}, status=403)
        except RoutineRevisionConflict:
            return JsonResponse(
                {
                    "error": "revision_conflict",
                    "instruction": "Inspect the routine before retrying.",
                },
                status=409,
            )
        except (ValidationError, ValueError):
            return JsonResponse(
                {
                    "error": "invalid_routine_request",
                    "instruction": "Check the action fields and explicit schedule; ask the user for missing information.",
                },
                status=422,
            )
        return JsonResponse(result)

    @api.post(
        "/internal/foundry/routines/results",
        auth=_foundry_token_valid,
    )
    def routine_result(request: HttpRequest, payload: RoutineResultEvent):
        if not getattr(settings, "ALLIES_ROUTINE_RESULT_INGESTION_ENABLED", False):
            return JsonResponse(
                {"event_id": str(payload.event_id), "status": "disabled"},
                status=503,
            )
        try:
            result = project_routine_result(payload.model_dump(mode="json"))
        except RoutineResultUnavailable:
            return JsonResponse(
                {"event_id": str(payload.event_id), "status": "unavailable"},
                status=404,
            )
        except RoutineResultConflict:
            return JsonResponse(
                {"event_id": str(payload.event_id), "status": "conflict"},
                status=409,
            )
        except RoutineResultInvalid:
            return JsonResponse(
                {"event_id": str(payload.event_id), "status": "invalid"},
                status=422,
            )
        try:
            complete_pending_routine_results(
                conversation_id=result.result.main_conversation_id
            )
        except (RoutineResultConflict, RoutineResultInvalid):
            pass
        return JsonResponse(
            {"event_id": str(result.event_id), "status": result.status},
            status=202,
        )

    api.register_controllers(RoutineController)
