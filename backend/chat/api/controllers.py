from typing import Annotated

from django.db import DatabaseError
from django.http import HttpRequest
from ninja import Header, Query
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
from chat.api.schemas import (
    AssistantReplyResponse,
    ConversationResponse,
    MessageAcceptanceResponse,
    MessageResponse,
    RoutineChatItemResponse,
    SendMessageRequest,
)
from chat.exceptions import (
    ChatUnavailable,
    ConversationUnavailable,
    CursorInvalid,
    IdempotencyConflict,
    MessageNotDeletable,
    MessageValidation,
    OnboardingHandoffRepairRequired,
    OnboardingHandoffUnavailable,
    QueueFull,
    SendRateLimited,
    TurnConflict,
)
from chat.services.conversations import retrieve_conversation
from chat.services.messages import (
    accept_message,
    assistant_reply_response,
    delete_queued_message,
    message_response,
    retry_message,
)
from common.uuids import CanonicalUUID


def _message_response(message) -> MessageResponse:
    return MessageResponse.model_validate(message_response(message))


def _conversation_response(result) -> ConversationResponse:
    return ConversationResponse(
        id=str(result.conversation.id),
        ally_id=str(result.conversation.ally.id),
        messages=[_message_response(message) for message in result.messages],
        queue=[_message_response(message) for message in result.queue],
        assistant_replies=[
            AssistantReplyResponse.model_validate(
                assistant_reply_response(reply, message=message)
            )
            for message in result.messages
            if (reply := getattr(message, "assistant_reply", None)) is not None
        ],
        routine_items=[
            RoutineChatItemResponse.model_validate(item)
            for item in result.routine_items
        ],
        next_cursor=result.next_cursor,
    )


def _acceptance_response(result) -> MessageAcceptanceResponse:
    return MessageAcceptanceResponse(
        conversation_id=str(result.conversation.id),
        message=_message_response(result.message),
        execution=None,
        replayed=result.replayed,
    )


def _read_error(exc: Exception, request: HttpRequest | None = None):
    if isinstance(exc, SessionInvalid):
        return error_json("session_invalid", "session invalid", 401)
    if isinstance(exc, (OnboardingHandoffRepairRequired, OnboardingHandoffUnavailable)):
        return error_json(exc.code, "conversation unavailable", 404)
    if isinstance(exc, (ConversationUnavailable, WorkspaceAccessDenied)):
        return error_json("conversation_unavailable", "conversation unavailable", 404)
    if isinstance(exc, CursorInvalid):
        return error_json("cursor_invalid", "request validation failed", 422)
    if isinstance(exc, MessageValidation):
        return error_json("validation_error", "request validation failed", 422)
    if isinstance(exc, IdempotencyConflict):
        return error_json("idempotency_conflict", "request conflicts", 409)
    if isinstance(exc, TurnConflict):
        return error_json("turn_terminal_conflict", "request conflicts", 409)
    if isinstance(exc, MessageNotDeletable):
        return error_json("message_not_deletable", "request conflicts", 409)
    if isinstance(exc, (QueueFull, SendRateLimited)):
        if request is None:
            return error_json("rate_limited", "Request temporarily unavailable", 429)
        return _rate_limited_response(request, exc.code)
    if isinstance(exc, (ChatUnavailable, DatabaseError)):
        return error_json("internal_error", "internal server error", 500)
    return None


def _rate_limited_response(request: HttpRequest, reason: str):
    response = error_json("rate_limited", "Request temporarily unavailable", 429)
    response._allies_rate_limit_reason = reason
    return response


@api_controller("/workspaces/{workspace_id}", tags=["Chat"])
class ConversationController(ControllerBase):
    @http_get(
        "/allies/{ally_id}/conversation",
        response={
            200: SuccessResponse[ConversationResponse],
            **error_responses(401, 404, 422, 500),
        },
    )
    def by_ally(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        ally_id: CanonicalUUID,
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = Query(None),
    ):
        try:
            session = _session(request)
            result = retrieve_conversation(
                user=session.user,
                workspace_id=workspace_id,
                ally_id=ally_id,
                limit=limit,
                cursor=cursor,
            )
        except Exception as exc:
            response = _read_error(exc, request)
            if response is not None:
                return response
            raise
        return success_json(_conversation_response(result), "Conversation loaded")

    @http_get(
        "/conversations/{conversation_id}",
        response={
            200: SuccessResponse[ConversationResponse],
            **error_responses(401, 404, 422, 500),
        },
    )
    def by_conversation(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        conversation_id: CanonicalUUID,
        limit: int = Query(50, ge=1, le=100),
        cursor: str | None = Query(None),
    ):
        try:
            session = _session(request)
            result = retrieve_conversation(
                user=session.user,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                limit=limit,
                cursor=cursor,
            )
        except Exception as exc:
            response = _read_error(exc, request)
            if response is not None:
                return response
            raise
        return success_json(_conversation_response(result), "Conversation loaded")

    @http_post(
        "/conversations/{conversation_id}/messages",
        response={
            200: SuccessResponse[MessageAcceptanceResponse],
            201: SuccessResponse[MessageAcceptanceResponse],
            **error_responses(401, 403, 404, 409, 422, 429, 500),
        },
    )
    def send(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        conversation_id: CanonicalUUID,
        payload: SendMessageRequest,
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                min_length=16,
                max_length=128,
                description="Stable key for repeating the exact text send.",
            ),
        ],
    ):
        if rejected := _require_origin(request, allow_native_bearer=True):
            return rejected
        try:
            session = _session(request)
            result = accept_message(
                user=session.user,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                content=payload.content,
                client_timezone=payload.timezone,
                routine_action=payload.routine_action,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            response = _read_error(exc, request)
            if response is not None:
                return response
            raise
        return success_json(
            _acceptance_response(result),
            "Message accepted",
            status=200 if result.replayed else 201,
        )

    @http_post(
        "/conversations/{conversation_id}/messages/{message_id}/retry",
        response={
            200: SuccessResponse[MessageAcceptanceResponse],
            201: SuccessResponse[MessageAcceptanceResponse],
            **error_responses(401, 403, 404, 409, 422, 429, 500),
        },
    )
    def retry(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        conversation_id: CanonicalUUID,
        message_id: CanonicalUUID,
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                min_length=16,
                max_length=128,
                description="Stable key for repeating the same retry action.",
            ),
        ],
    ):
        if rejected := _require_origin(request, allow_native_bearer=True):
            return rejected
        try:
            session = _session(request)
            result = retry_message(
                user=session.user,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                message_id=message_id,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            response = _read_error(exc, request)
            if response is not None:
                return response
            raise
        return success_json(
            _acceptance_response(result),
            "Message retry accepted",
            status=200 if result.replayed else 201,
        )

    @http_delete(
        "/conversations/{conversation_id}/messages/{message_id}",
        response={
            200: SuccessResponse[MessageResponse],
            **error_responses(401, 403, 404, 409, 500),
        },
    )
    def delete(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        conversation_id: CanonicalUUID,
        message_id: CanonicalUUID,
    ):
        if rejected := _require_origin(request, allow_native_bearer=True):
            return rejected
        try:
            session = _session(request)
            message = delete_queued_message(
                user=session.user,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                message_id=message_id,
            )
        except Exception as exc:
            response = _read_error(exc, request)
            if response is not None:
                return response
            raise
        return success_json(_message_response(message), "Message deleted")
