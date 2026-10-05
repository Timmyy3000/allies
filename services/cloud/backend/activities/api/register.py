import json
import secrets
import time
from typing import Annotated

from django.conf import settings
from django.db import DatabaseError, close_old_connections
from django.http import HttpRequest, JsonResponse, StreamingHttpResponse
from ninja import Body, Header, Query
from ninja_extra import (
    ControllerBase,
    NinjaExtraAPI,
    api_controller,
    http_get,
    http_post,
)

from allies.gateways.contracts import FoundryEventEnvelope, RoutineDispatchReceipt
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
from chat.services.messages import assistant_reply_response
from common.uuids import CanonicalUUID
from routines.services.approvals import (
    RoutineApprovalConflict,
    RoutineApprovalInvalid,
    RoutineApprovalUnavailable,
    apply_routine_approval_requested_event,
)
from routines.services.dispatch import (
    RoutineDispatchReconciliationConflict,
    RoutineDispatchReconciliationUnavailable,
    reconcile_late_routine_dispatch_receipt,
)
from routines.services.results import (
    RoutineResultConflict,
    RoutineResultEvent,
    RoutineResultInvalid,
    RoutineResultUnavailable,
    complete_pending_routine_results,
    project_routine_result,
)

from ..exceptions import (
    ApprovalConflict,
    ApprovalInvalid,
    ApprovalNotFound,
    ProjectionConflict,
    ProjectionCursorExpired,
    ProjectionCursorGap,
    ProjectionCursorInvalid,
    ProjectionInvalid,
    ProjectionNotFound,
    ProjectionSequenceGap,
)
from ..presentation import activity_metadata, approval_detail, approval_summary
from ..services.approval_explanations import ensure_approval_explanation
from ..services.approvals import (
    APPROVAL_MAX_LIST,
    get_approval_detail,
    list_approvals,
    record_approval_decision,
)
from ..services.projection import (
    parse_activity_cursor,
    project_foundry_event,
    read_activity_snapshot,
    serialize_activity_cursor,
)
from .schemas import (
    ActivitySnapshotResponse,
    ApprovalDecisionRequest,
    ApprovalDetailResponse,
    ApprovalListResponse,
)


def _no_store(response: JsonResponse) -> JsonResponse:
    response["Cache-Control"] = "no-store"
    return response


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
        "/conversations/{conversation_id}/approvals",
        response={
            200: SuccessResponse[ApprovalListResponse],
            **error_responses(401, 404, 409, 422, 500),
        },
    )
    def approvals(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        conversation_id: CanonicalUUID,
        limit: int = Query(APPROVAL_MAX_LIST, ge=1, le=APPROVAL_MAX_LIST),
    ):
        try:
            session = _session(request)
            approvals = list_approvals(
                user=session.user,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                limit=limit,
            )
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except (WorkspaceAccessDenied, ApprovalNotFound):
            return error_json("approval_unavailable", "approval unavailable", 404)
        except ApprovalInvalid:
            return error_json("validation_error", "request validation failed", 422)
        return _no_store(
            success_json(
                ApprovalListResponse(
                    approvals=[approval_summary(approval) for approval in approvals]
                ),
                "Approvals loaded",
            )
        )

    @http_get(
        "/conversations/{conversation_id}/approvals/{approval_id}",
        response={
            200: SuccessResponse[ApprovalDetailResponse],
            **error_responses(401, 404, 409, 422, 500),
        },
    )
    def approval(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        conversation_id: CanonicalUUID,
        approval_id: CanonicalUUID,
    ):
        try:
            session = _session(request)
            arguments = {
                "user": session.user,
                "workspace_id": workspace_id,
                "conversation_id": conversation_id,
                "approval_id": approval_id,
            }
            result = (
                ensure_approval_explanation(**arguments)
                if _require_origin(request, allow_native_bearer=True) is None
                else get_approval_detail(**arguments)
            )
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except (WorkspaceAccessDenied, ApprovalNotFound):
            return error_json("approval_unavailable", "approval unavailable", 404)
        return _no_store(
            success_json(
                ApprovalDetailResponse.model_validate(approval_detail(result)),
                "Approval loaded",
            )
        )

    @http_post(
        "/conversations/{conversation_id}/approvals/{approval_id}/decision",
        response={
            200: SuccessResponse[ApprovalDetailResponse],
            202: SuccessResponse[ApprovalDetailResponse],
            **error_responses(401, 403, 404, 409, 422, 500),
        },
    )
    def decide(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        conversation_id: CanonicalUUID,
        approval_id: CanonicalUUID,
        payload: ApprovalDecisionRequest,
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                min_length=36,
                max_length=36,
                description="Stable UUID for repeating one approval decision.",
            ),
        ],
    ):
        if rejected := _require_origin(request, allow_native_bearer=True):
            return rejected
        try:
            session = _session(request)
            result = record_approval_decision(
                user=session.user,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                approval_id=approval_id,
                decision=payload.decision,
                idempotency_key=idempotency_key,
            )
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except (WorkspaceAccessDenied, ApprovalNotFound):
            return error_json("approval_unavailable", "approval unavailable", 404)
        except ApprovalConflict:
            return error_json("approval_conflict", "request conflicts", 409)
        except ApprovalInvalid:
            return error_json("validation_error", "request validation failed", 422)
        return _no_store(
            success_json(
                ApprovalDetailResponse.model_validate(approval_detail(result.approval)),
                "Approval decision recorded",
                status=200 if result.replayed else 202,
            )
        )

    @http_get(
        "/conversations/{conversation_id}/activities",
        response={
            200: SuccessResponse[ActivitySnapshotResponse],
            **error_responses(401, 404, 409, 410, 422, 500),
        },
    )
    def snapshot(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        conversation_id: CanonicalUUID,
        limit: int = Query(200, ge=1, le=1000),
        cursor: str | None = Query(None, max_length=512),
        replay: bool = Query(False),
        recent_messages: int | None = Query(None, ge=1, le=200),
    ):
        try:
            session = _session(request)
            result = read_activity_snapshot(
                user=session.user,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                limit=limit,
                cursor=cursor,
                replay=replay,
                recent_messages=recent_messages,
            )
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except (WorkspaceAccessDenied, ProjectionNotFound):
            return error_json("activity_unavailable", "activity unavailable", 404)
        except ProjectionCursorGap:
            return error_json(
                "activity_cursor_gap", "activity replay needs repair", 409
            )
        except ProjectionCursorExpired:
            return error_json("activity_cursor_expired", "activity cursor expired", 410)
        except ProjectionCursorInvalid:
            return error_json("activity_cursor_invalid", "activity cursor invalid", 422)
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
                        **activity_metadata(activity),
                    }
                    for activity in result.activities
                ],
                state=result.state,
                last_contiguous_sequence=result.last_contiguous_sequence,
                last_contiguous_activity_sequence=result.last_contiguous_activity_sequence,
                resume_cursor=result.resume_cursor,
                next_cursor=result.next_cursor,
                oldest_sequence=result.oldest_sequence,
                latest_sequence=result.latest_sequence,
                retention_gap=result.retention_gap,
                assistant_reply=(
                    assistant_reply_response(result.assistant_reply)
                    if result.assistant_reply is not None
                    else None
                ),
                active_message_id=result.active_message_id,
            ),
            "Activities loaded",
        )

    @http_get("/conversations/{conversation_id}/activities/stream", response=None)
    def stream(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        conversation_id: CanonicalUUID,
        cursor: str | None = Query(None, max_length=512),
    ):
        if not getattr(settings, "ALLIES_ACTIVITY_SSE_ENABLED", False):
            return error_json(
                "activity_stream_unavailable", "activity stream unavailable", 503
            )
        try:
            session = _session(request)
            check_rate_limit(
                scope="activity-stream",
                identity=f"{workspace_id}:{session.user.id}",
                limit=4,
                period=60,
            )
            resume_cursor = request.headers.get("Last-Event-ID") or cursor
            snapshot = read_activity_snapshot(
                user=session.user,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                limit=200,
                cursor=resume_cursor,
                replay=bool(resume_cursor),
            )
            parsed_cursor = (
                parse_activity_cursor(resume_cursor, snapshot.conversation.id)
                if resume_cursor
                else None
            )
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except ThrottleExceeded:
            return error_json(
                "activity_stream_rate_limited", "activity stream unavailable", 429
            )
        except ThrottleUnavailable:
            return error_json(
                "activity_stream_unavailable", "activity stream unavailable", 503
            )
        except (WorkspaceAccessDenied, ProjectionNotFound):
            return error_json("activity_unavailable", "activity unavailable", 404)
        except ProjectionCursorGap:
            return error_json(
                "activity_cursor_gap", "activity replay needs repair", 409
            )
        except ProjectionCursorExpired:
            return error_json("activity_cursor_expired", "activity cursor expired", 410)
        except ProjectionCursorInvalid:
            return error_json("activity_cursor_invalid", "activity cursor invalid", 422)

        def encode(event: str, data: dict, event_id: str | None = None) -> str:
            prefix = f"id: {event_id}\n" if event_id else ""
            return (
                f"{prefix}event: {event}\n"
                f"data: {json.dumps(data, separators=(',', ':'))}\n\n"
            )

        def stream_content():
            current_cursor = resume_cursor
            after_sequence = (
                parsed_cursor.after_sequence
                if parsed_cursor
                else (snapshot.latest_sequence or 0)
            )
            high_water = (
                parsed_cursor.high_water_sequence
                if parsed_cursor
                else (snapshot.latest_sequence or 0)
            )
            ready_cursor = current_cursor or serialize_activity_cursor(
                snapshot.conversation.id, after_sequence, high_water
            )
            current_cursor = ready_cursor
            yield encode(
                "ready",
                {
                    "conversation_id": str(snapshot.conversation.id),
                    "cursor": ready_cursor,
                    "high_water_sequence": high_water,
                },
                ready_cursor,
            )
            started = time.monotonic()
            last_heartbeat = started
            try:
                while time.monotonic() - started < 90:
                    try:
                        close_old_connections()
                        current_session = _session(request)
                        current = read_activity_snapshot(
                            user=current_session.user,
                            workspace_id=workspace_id,
                            conversation_id=conversation_id,
                            limit=200,
                            cursor=current_cursor,
                            replay=True,
                        )
                        for activity in current.activities:
                            next_cursor = serialize_activity_cursor(
                                current.conversation.id,
                                activity.sequence,
                                current.latest_sequence or activity.sequence,
                            )
                            yield encode(
                                "activity",
                                {
                                    "conversation_id": str(current.conversation.id),
                                    "activity": {
                                        "id": str(activity.id),
                                        "message_id": str(activity.message_id),
                                        "sequence": activity.sequence,
                                        "conversation_turn_ordinal": activity.conversation_turn_ordinal,
                                        "kind": activity.kind,
                                        "text": activity.text,
                                        "state": activity.state,
                                        "created_at": activity.created_at.isoformat(),
                                        **activity_metadata(activity),
                                    },
                                },
                                next_cursor,
                            )
                            current_cursor = next_cursor
                        if current.state in {"completed", "failed", "stopped"}:
                            yield encode(
                                "terminal",
                                {
                                    "conversation_id": str(current.conversation.id),
                                    "state": current.state,
                                    "cursor": current_cursor,
                                },
                                current_cursor,
                            )
                            return
                        now = time.monotonic()
                        if now - last_heartbeat >= 15:
                            yield ": heartbeat\n\n"
                            last_heartbeat = now
                        time.sleep(0.25)
                    except SessionInvalid:
                        yield encode(
                            "error",
                            {
                                "conversation_id": str(conversation_id),
                                "code": "session_invalid",
                            },
                        )
                        return
                    except ProjectionCursorExpired:
                        yield encode(
                            "error",
                            {
                                "conversation_id": str(conversation_id),
                                "code": "activity_cursor_expired",
                            },
                        )
                        return
                    except (DatabaseError, OSError, TypeError, ValueError):
                        yield encode(
                            "error",
                            {
                                "conversation_id": str(conversation_id),
                                "code": "activity_stream_unavailable",
                            },
                        )
                        return
            finally:
                close_old_connections()

        response = StreamingHttpResponse(
            stream_content(), content_type="text/event-stream"
        )
        response["Cache-Control"] = "no-cache, no-transform"
        response["X-Accel-Buffering"] = "no"
        response["Vary"] = "Origin"
        return response


def register(api: NinjaExtraAPI) -> None:
    @api.post(
        "/internal/foundry/events",
        auth=_foundry_token_valid,
    )
    def foundry_event(request: HttpRequest, payload: Annotated[dict, Body(...)]):
        kind = payload.get("kind") if isinstance(payload, dict) else None
        dispatch_receipt = kind == "routine.dispatch_receipt"
        routine_event = kind == "routine.result"
        approval_event = kind == "routine.approval_requested"
        if dispatch_receipt:
            if not getattr(settings, "ALLIES_ROUTINE_RESULT_INGESTION_ENABLED", False):
                return JsonResponse(
                    {"event_id": payload.get("command_id"), "status": "disabled"},
                    status=503,
                )
            try:
                receipt = RoutineDispatchReceipt.model_validate(payload)
                status = reconcile_late_routine_dispatch_receipt(receipt)
            except RoutineDispatchReconciliationUnavailable:
                return JsonResponse(
                    {"command_id": payload.get("command_id"), "status": "unavailable"},
                    status=404,
                )
            except RoutineDispatchReconciliationConflict:
                return JsonResponse(
                    {"command_id": payload.get("command_id"), "status": "conflict"},
                    status=409,
                )
            except ValueError:
                return JsonResponse(
                    {"command_id": payload.get("command_id"), "status": "invalid"},
                    status=422,
                )
            return JsonResponse(
                {"command_id": str(receipt.command_id), "status": status},
                status=202,
            )
        if routine_event:
            if not getattr(settings, "ALLIES_ROUTINE_RESULT_INGESTION_ENABLED", False):
                return JsonResponse(
                    {"event_id": payload.get("event_id"), "status": "disabled"},
                    status=503,
                )
            try:
                event = RoutineResultEvent.model_validate(payload)
                result = project_routine_result(event.model_dump(mode="json"))
            except RoutineResultUnavailable:
                return JsonResponse(
                    {"event_id": payload.get("event_id"), "status": "unavailable"},
                    status=404,
                )
            except RoutineResultConflict:
                return JsonResponse(
                    {"event_id": payload.get("event_id"), "status": "conflict"},
                    status=409,
                )
            except (RoutineResultInvalid, ValueError):
                return JsonResponse(
                    {"event_id": payload.get("event_id"), "status": "invalid"},
                    status=422,
                )
            try:
                complete_pending_routine_results(
                    conversation_id=result.result.main_conversation_id
                )
            except (RoutineResultConflict, RoutineResultInvalid):
                # The durable result receipt remains pending and is retried at
                # the next main-turn boundary when the context fits safely.
                pass
            return JsonResponse(
                {"event_id": str(result.event_id), "status": result.status},
                status=202,
            )

        if approval_event:
            if not getattr(settings, "ALLIES_ROUTINE_APPROVAL_ENABLED", False):
                return JsonResponse(
                    {"event_id": payload.get("event_id"), "status": "disabled"},
                    status=503,
                )
            try:
                event_result = apply_routine_approval_requested_event(payload)
            except RoutineApprovalUnavailable:
                return JsonResponse(
                    {"event_id": payload.get("event_id"), "status": "unavailable"},
                    status=404,
                )
            except RoutineApprovalConflict:
                return JsonResponse(
                    {"event_id": payload.get("event_id"), "status": "conflict"},
                    status=409,
                )
            except (RoutineApprovalInvalid, ValueError):
                return JsonResponse(
                    {"event_id": payload.get("event_id"), "status": "invalid"},
                    status=422,
                )
            return JsonResponse(
                {
                    "event_id": str(event_result.event_id),
                    "status": event_result.status,
                },
                status=202,
            )

        if not getattr(settings, "ALLIES_FOUNDRY_EXECUTION_ENABLED", False):
            return JsonResponse(
                {
                    "event_id": payload.get("event_id")
                    if isinstance(payload, dict)
                    else None,
                    "status": "disabled",
                },
                status=503,
            )
        try:
            event = FoundryEventEnvelope.model_validate(payload)
            result = project_foundry_event(event)
        except ValueError:
            return error_json("validation_error", "request validation failed", 422)
        except ProjectionNotFound:
            return JsonResponse(
                {"event_id": str(event.event_id), "status": "unavailable"},
                status=404,
            )
        except ProjectionSequenceGap:
            return JsonResponse({"code": ProjectionSequenceGap.code}, status=409)
        except ProjectionConflict:
            return JsonResponse({"code": "conflict"}, status=409)
        except ProjectionInvalid:
            return JsonResponse(
                {"event_id": str(event.event_id), "status": "invalid"},
                status=422,
            )
        return JsonResponse(
            {"event_id": str(result.event_id), "status": result.status},
            status=202,
        )

    api.register_controllers(ActivityController)
