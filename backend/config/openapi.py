"""Stable OpenAPI examples for the public response envelope."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ninja_extra import NinjaExtraAPI

GENERIC_ERROR_RESPONSE_EXAMPLE: dict[str, Any] = {
    "status": "error",
    "message": "Request failed",
    "data": None,
}

STANDARD_RESPONSE_EXAMPLES: dict[str, dict[str, Any]] = {
    "ErrorResponse_ErrorData_": GENERIC_ERROR_RESPONSE_EXAMPLE,
    "SuccessResponse_AuthorizationStartResponse_": {
        "status": "success",
        "message": "Authentication started",
        "data": {"redirect_url": "https://provider.example/authorize"},
    },
    "SuccessResponse_ClaimInviteResponse_": {
        "status": "success",
        "message": "Invite claimed",
        "data": {"claimed": True},
    },
    "SuccessResponse_NativeAuthorizationStartResponse_": {
        "status": "success",
        "message": "Native sign-in started",
        "data": {
            "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?...",
            "expires_at": "2026-08-20T16:10:00Z",
        },
    },
    "SuccessResponse_NativeTokenResponse_": {
        "status": "success",
        "message": "Native session issued",
        "data": {
            "token_type": "Bearer",
            "access_token": "<short-lived-cloud-jwt>",
            "expires_in": 600,
            "refresh_token": "<rotating-opaque-cloud-token>",
            "refresh_expires_in": 1209600,
            "session_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d72",
        },
    },
    "SuccessResponse_MeResponse_": {
        "status": "success",
        "message": "Profile loaded",
        "data": {
            "user": {"id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d72"},
            "profile": {"display_name": "Example User", "avatar_url": None},
            "session": {
                "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d73",
                "expires_at": "2026-08-12T12:00:00Z",
            },
            "workspace": {
                "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d74",
                "name": "Personal Workspace",
                "role": "owner",
                "capabilities": ["workspace:manage"],
            },
        },
    },
    "SuccessResponse_ProfileResponse_": {
        "status": "success",
        "message": "Profile updated",
        "data": {"display_name": "Example User", "avatar_url": None},
    },
    "SuccessResponse_PreparedAvatarResponse_": {
        "status": "success",
        "message": "Avatar upload prepared",
        "data": {
            "asset_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d75",
            "upload_url": "https://uploads.example/avatar",
            "headers": {"Content-Type": "image/png"},
            "expires_at": "2026-08-12T12:00:00Z",
        },
    },
    "SuccessResponse_AvatarResponse_": {
        "status": "success",
        "message": "Avatar loaded",
        "data": {
            "asset_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d75",
            "url": "https://media.example/avatar",
            "expires_at": "2026-08-12T12:00:00Z",
        },
    },
    "SuccessResponse_WorkspaceContextResponse_": {
        "status": "success",
        "message": "Workspace loaded",
        "data": {
            "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d74",
            "name": "Personal Workspace",
            "role": "owner",
            "capabilities": ["workspace:manage"],
        },
    },
    "SuccessResponse_HealthResponse_": {
        "status": "success",
        "message": "Service healthy",
        "data": {"state": "healthy"},
    },
    "SuccessResponse_OnboardingAttemptResponse_": {
        "status": "success",
        "message": "Onboarding started",
        "data": {
            "attempt_token": "opaque-onboarding-attempt",
            "greeting": "Hello! What should we work on first?",
        },
    },
    "SuccessResponse_AllyResponse_": {
        "status": "success",
        "message": "Ally loaded",
        "data": {
            "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d76",
            "binding_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d77",
            "operation_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d78",
            "name": "Mira",
            "job": "Study partner",
            "personality": "Calm, curious, and specific.",
            "appearance": {"catalog_version": "v1", "key": "sunrise"},
            "provisioning_state": "pending",
            "retryable": False,
        },
    },
    "SuccessResponse_AllyDeletionResponse_": {
        "status": "success",
        "message": "Ally deletion accepted",
        "data": {
            "ally_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d76",
            "operation_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d78",
            "state": "pending",
            "retryable": True,
            "safe_error_code": "",
        },
    },
    "SuccessResponse_AllyListResponse_": {
        "status": "success",
        "message": "Allies loaded",
        "data": {
            "allies": [
                {
                    "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d76",
                    "binding_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d77",
                    "operation_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d78",
                    "name": "Mira",
                    "job": "Study partner",
                    "personality": "Calm, curious, and specific.",
                    "appearance": {"catalog_version": "v1", "key": "sunrise"},
                    "provisioning_state": "bound",
                    "retryable": False,
                }
            ]
        },
    },
    "SuccessResponse_ModelKeysResponse_": {
        "status": "success",
        "message": "Model keys",
        "data": {
            "providers": ["opencode-go", "opencode-zen"],
            "keys": [
                {
                    "provider": "opencode-zen",
                    "key_hint": "WXYZ",
                    "connected_at": "2026-09-25T12:00:00+00:00",
                }
            ],
            "allies": [
                {
                    "ally_id": "00000000-0000-4000-8000-000000000041",
                    "source": "own_key",
                    "provider": "opencode-zen",
                    "model": "gpt-5.2",
                    "reasoning": "high",
                    "status": "connected",
                }
            ],
        },
    },
    "SuccessResponse_RuntimeIntentResponse_": {
        "status": "success",
        "message": "Runtime intent accepted",
        "data": {"status": "waking"},
    },
    "SuccessResponse_ConversationResponse_": {
        "status": "success",
        "message": "Conversation loaded",
        "data": {
            "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d79",
            "ally_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d76",
            "messages": [
                {
                    "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d80",
                    "sender": "assistant",
                    "content": "Hello! What should we work on first?",
                    "sequence": 1,
                    "status": "completed",
                    "created_at": "2026-08-20T16:00:00Z",
                    "retryable": False,
                    "queue_state": None,
                    "deleted_at": None,
                }
            ],
            "queue": [],
            "assistant_replies": [],
            "routine_items": [],
            "next_cursor": None,
        },
    },
    "SuccessResponse_MessageAcceptanceResponse_": {
        "status": "success",
        "message": "Message accepted",
        "data": {
            "conversation_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d79",
            "message": {
                "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d81",
                "sender": "user",
                "content": "Help me plan tomorrow's study block.",
                "sequence": 3,
                "status": "queued",
                "created_at": "2026-08-20T16:01:00Z",
                "retryable": False,
                "queue_state": "claimed",
                "deleted_at": None,
            },
            "execution": None,
            "replayed": False,
        },
    },
    "SuccessResponse_MessageResponse_": {
        "status": "success",
        "message": "Message deleted",
        "data": {
            "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d83",
            "sender": "user",
            "content": "",
            "sequence": 4,
            "status": "stopped",
            "created_at": "2026-08-20T16:02:00Z",
            "retryable": False,
            "queue_state": None,
            "deleted_at": "2026-08-20T16:02:01Z",
        },
    },
    "SuccessResponse_FileReservationResponse_": {
        "status": "success",
        "message": "File message reserved",
        "data": {
            "message": {
                "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d86",
                "sequence": 3,
                "status": "queued",
                "preparation": "uploading",
                "revision": 1,
            },
            "files": [
                {
                    "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d87",
                    "generation": 1,
                    "state": "pending",
                }
            ],
            "replayed": False,
        },
    },
    "SuccessResponse_FileMessageResponse_": {
        "status": "success",
        "message": "File message prepared",
        "data": {
            "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d86",
            "status": "queued",
            "preparation": "ready",
            "revision": 2,
        },
    },
    "SuccessResponse_FileDraftResponse_": {
        "status": "success",
        "message": "File draft read",
        "data": {
            "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d88",
            "content": "Review this report.",
            "files": [
                {
                    "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d87",
                    "name": "report.pdf",
                    "state": "ready",
                }
            ],
        },
    },
    "SuccessResponse_FileDraftDiscardResponse_": {
        "status": "success",
        "message": "File draft discarded",
        "data": {"discarded": True},
    },
    "SuccessResponse_FileCancellationResponse_": {
        "status": "success",
        "message": "File message cancelled",
        "data": {
            "message": {
                "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d86",
                "status": "stopped",
                "preparation": "cancelled",
                "revision": 2,
            },
            "draft": {
                "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d88",
                "content": "Review this report.",
                "files": [
                    {
                        "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d87",
                        "name": "report.pdf",
                        "state": "ready",
                    }
                ],
            },
        },
    },
    "SuccessResponse_UploadFileResponse_": {
        "status": "success",
        "message": "File accepted for validation",
        "data": {
            "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d87",
            "state": "validating",
            "generation": 1,
        },
    },
    "SuccessResponse_ActivitySnapshotResponse_": {
        "status": "success",
        "message": "Activities loaded",
        "data": {
            "conversation_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d79",
            "activities": [
                {
                    "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d81",
                    "message_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d82",
                    "sequence": 1,
                    "conversation_turn_ordinal": 3,
                    "kind": "assistant_delta",
                    "text": "I can help with that.",
                    "state": "running",
                    "created_at": "2026-08-20T16:01:01Z",
                }
            ],
            "state": "running",
            "active_message_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d82",
            "last_contiguous_sequence": 2,
            "last_contiguous_activity_sequence": 1,
            "resume_cursor": "<signed-activity-cursor>",
            "next_cursor": None,
            "oldest_sequence": 1,
            "latest_sequence": 1,
            "retention_gap": False,
        },
    },
    "SuccessResponse_ApprovalListResponse_": {
        "status": "success",
        "message": "Approvals loaded",
        "data": {
            "approvals": [
                {
                    "contract_version": "approval.v1",
                    "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d84",
                    "message_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d82",
                    "conversation_turn_ordinal": 3,
                    "status": "pending",
                    "decision": None,
                    "decision_recorded": False,
                    "expires_at": "2026-08-20T16:05:00Z",
                    "decided_at": None,
                    "acknowledgement_deadline_at": None,
                }
            ]
        },
    },
    "SuccessResponse_ApprovalDetailResponse_": {
        "status": "success",
        "message": "Approval loaded",
        "data": {
            "contract_version": "approval.v1",
            "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d84",
            "message_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d82",
            "conversation_turn_ordinal": 3,
            "status": "pending",
            "decision": None,
            "decision_recorded": False,
            "expires_at": "2026-08-20T16:05:00Z",
            "decided_at": None,
            "acknowledgement_deadline_at": None,
            "action_label": "Run the requested command",
            "action_preview": "echo a redacted command",
            "approval_request_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d85",
            "preview_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "explanation": {
                "version": "approval-explanation.v1",
                "approval_request_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d85",
                "preview_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "source": "fallback",
                "action": "Run a command",
                "target": "The target is described in the technical details.",
                "consequence": "This action may change data or contact a service.",
                "reason": "Your Ally needs your approval before continuing.",
            },
            "technical_details": {
                "action_kind": "terminal",
                "action_label": "Run the requested command",
                "action_preview": "echo a redacted command",
            },
        },
    },
    "SuccessResponse_RoutinePageResponse_": {
        "status": "success",
        "message": "Routines loaded",
        "data": {
            "items": [
                {
                    "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d85",
                    "responsible_ally_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d76",
                    "title": "Check the inbox",
                    "schedule": {
                        "kind": "recurring",
                        "frequency": "daily",
                        "local_time": "09:00:00",
                        "timezone": "Europe/Berlin",
                    },
                    "revision": 1,
                    "schedule_generation": 1,
                    "schedule_state": "active",
                    "next_run_at": "2026-08-21T07:00:00Z",
                    "created_at": "2026-08-20T16:00:00Z",
                    "updated_at": "2026-08-20T16:00:00Z",
                }
            ],
            "next_cursor": None,
        },
    },
    "SuccessResponse_RoutineDetailResponse_": {
        "status": "success",
        "message": "Routine loaded",
        "data": {
            "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d85",
            "responsible_ally_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d76",
            "title": "Check the inbox",
            "schedule": {
                "kind": "recurring",
                "frequency": "daily",
                "local_time": "09:00:00",
                "timezone": "Europe/Berlin",
            },
            "revision": 1,
            "schedule_generation": 1,
            "schedule_state": "active",
            "next_run_at": "2026-08-21T07:00:00Z",
            "created_at": "2026-08-20T16:00:00Z",
            "updated_at": "2026-08-20T16:00:00Z",
            "workspace_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d74",
            "owner_user_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d72",
            "binding_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d77",
            "main_conversation_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d79",
            "execution_prompt": "Review new mail and summarize anything urgent.",
        },
    },
    "SuccessResponse_RoutineApprovalResponse_": {
        "status": "success",
        "message": "Routine approval decision recorded",
        "data": {
            "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d85",
            "routine_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d86",
            "run_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d87",
            "approval_request_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d88",
            "action_attempt_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d89",
            "execution_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d90",
            "attempt_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d91",
            "generation": 1,
            "status": "decision_recorded",
            "decision": "approve",
            "action_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "expires_at": "2026-08-21T16:00:00Z",
            "created_at": "2026-08-20T16:00:00Z",
            "decided_at": "2026-08-20T16:01:00Z",
            "delivery_status": "pending",
            "replayed": False,
        },
    },
    "SuccessResponse_WaitlistEntryResponse_": {
        "status": "success",
        "message": "Waitlist greeting ready",
        "data": {
            "attempt_token": "opaque-attempt-token",
            "greeting": "Hello! What would you like to start with?",
        },
    },
    "SuccessResponse_WaitlistEntryCompletionResponse_": {
        "status": "success",
        "message": "Waitlist registration complete",
        "data": {"email": "a***@example.com"},
    },
    "SuccessResponse_ConnectResponse_": {
        "status": "success",
        "message": "Gmail connect started",
        "data": {
            "connect_session_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d79",
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?...",
            "expires_at": "2026-09-25T08:00:00Z",
        },
    },
    "SuccessResponse_GmailConnectionResponse_": {
        "status": "success",
        "message": "Gmail connected",
        "data": {
            "connection_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d80",
            "account_email": "user@gmail.com",
            "scope_set": [
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/gmail.send",
            ],
            "connected_at": "2026-09-25T08:00:00Z",
            "ally_grants": [
                {
                    "ally_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d76",
                    "level": "send",
                    "grant_generation": 1,
                    "updated_at": "2026-09-25T08:00:00Z",
                }
            ],
        },
    },
    "SuccessResponse_Union_GmailConnectionResponse__NoneType__": {
        "status": "success",
        "message": "Gmail connection status",
        "data": None,
    },
    "SuccessResponse_AllyGrantResponse_": {
        "status": "success",
        "message": "Ally gmail grant saved",
        "data": {
            "ally_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d76",
            "level": "send",
            "grant_generation": 1,
            "updated_at": "2026-09-25T08:00:00Z",
        },
    },
    "SuccessResponse_DisconnectResponse_": {
        "status": "success",
        "message": "Gmail disconnect accepted",
        "data": {"status": "deprovisioned"},
    },
}

WAITLIST_ERROR_CODES: dict[tuple[str, str], dict[int, tuple[str, ...]]] = {
    ("/api/v1/waitlist/entries", "post"): {
        403: ("origin_rejected",),
        409: ("waitlist_invalid_state",),
        422: ("validation_error",),
        429: ("throttled",),
        503: ("generation_unavailable", "waitlist_unavailable"),
    },
    ("/api/v1/waitlist/entries/complete", "post"): {
        403: ("origin_rejected",),
        404: ("waitlist_entry_unavailable",),
        409: ("waitlist_invalid_state",),
        422: ("validation_error",),
        503: ("waitlist_unavailable",),
    },
}

ONBOARDING_ERROR_CODES: dict[tuple[str, str], dict[int, tuple[str, ...]]] = {
    ("/api/v1/onboarding/attempts", "post"): {
        403: ("origin_rejected", "csrf_rejected"),
        422: ("validation_error",),
        429: ("throttled",),
        503: ("onboarding_unavailable",),
    },
    ("/api/v1/workspaces/{workspace_id}/allies", "post"): {
        401: ("session_invalid",),
        403: ("origin_rejected", "csrf_rejected"),
        404: ("ally_unavailable",),
        409: ("idempotency_conflict",),
        422: ("onboarding_invalid",),
    },
    ("/api/v1/onboarding/runtime-intents", "post"): {
        401: ("session_invalid",),
        403: ("origin_rejected", "csrf_rejected"),
        404: ("workspace_unavailable", "runtime_intent_unavailable"),
        409: ("runtime_intent_conflict",),
        422: ("validation_error",),
        429: ("rate_limited",),
        503: ("throttle_unavailable", "runtime_intent_unavailable"),
    },
}


def _waitlist_error_example(code: str) -> dict[str, Any]:
    message = {
        "origin_rejected": "origin rejected",
        "csrf_rejected": "csrf rejected",
        "validation_error": "request validation failed",
        "waitlist_unavailable": "waitlist unavailable",
    }.get(code, "waitlist request failed")
    data: dict[str, Any] = {"code": code}
    if code == "validation_error":
        # Framework schema validation reports the nested request location;
        # controller-level checks use the same envelope with ``request``.
        data["details"] = {
            "errors": [{"field": "body.payload.name", "code": "string_type"}]
        }
    return {"status": "error", "message": message, "data": data}


def _onboarding_error_example(code: str) -> dict[str, Any]:
    message = {
        "origin_rejected": "origin rejected",
        "csrf_rejected": "csrf rejected",
        "session_invalid": "session invalid",
        "ally_unavailable": "Ally unavailable",
        "idempotency_conflict": "request conflicts",
        "onboarding_invalid": "onboarding attempt invalid",
        "workspace_unavailable": "Workspace unavailable",
        "runtime_intent_conflict": "Runtime intent unavailable",
        "runtime_intent_unavailable": "Runtime intent unavailable",
        "rate_limited": "Request temporarily unavailable",
        "throttle_unavailable": "Request temporarily unavailable",
        "validation_error": "request validation failed",
        "throttled": "try again later",
        "onboarding_unavailable": "onboarding unavailable",
    }.get(code, "onboarding request failed")
    data: dict[str, Any] = {"code": code}
    if code == "validation_error":
        data["details"] = {
            "errors": [{"field": "body.payload.name", "code": "string_type"}]
        }
    return {"status": "error", "message": message, "data": data}


def _response(operation: dict[str, Any], status: int) -> dict[str, Any] | None:
    responses = operation.get("responses", {})
    response = responses.get(status) or responses.get(str(status))
    return response if isinstance(response, dict) else None


def _add_header_parameter(
    operation: dict[str, Any], name: str, description: str
) -> None:
    parameters = operation.setdefault("parameters", [])
    names = {item.get("name") for item in parameters if isinstance(item, dict)}
    if name not in names:
        parameters.append(
            {
                "name": name,
                "in": "header",
                "required": False,
                "description": description,
                "schema": {"type": "string"},
            }
        )


def _add_no_store_header(operation: dict[str, Any], status: int = 200) -> None:
    response = _response(operation, status)
    if response is None:
        return
    response.setdefault("headers", {})["Cache-Control"] = {
        "schema": {"type": "string"},
        "example": "no-store",
        "description": "The response must not be cached.",
    }


def add_standard_response_examples(schema: dict[str, Any]) -> dict[str, Any]:
    """Attach reviewed full-envelope examples to every public JSON schema."""

    components = schema.get("components", {}).get("schemas", {})
    for name, example in STANDARD_RESPONSE_EXAMPLES.items():
        if name in components:
            components[name]["example"] = deepcopy(example)

    # A component-level error example cannot describe every status-specific
    # failure. Keep the component neutral and repeat that complete envelope on
    # each route response so generated Swagger shows the actual response shape
    # without claiming a validation error for throttles or outages.
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for response in operation.get("responses", {}).values():
                content = response.get("content", {}).get("application/json")
                if not isinstance(content, dict):
                    continue
                response_schema = content.get("schema", {})
                if response_schema.get("$ref", "").endswith(
                    "/ErrorResponse_ErrorData_"
                ):
                    content["example"] = deepcopy(GENERIC_ERROR_RESPONSE_EXAMPLE)

    for path, path_item in schema.get("paths", {}).items():
        if not path.startswith("/api/v1/waitlist/"):
            continue
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            origin_note = (
                "Waitlist requests must include either Origin or Referer, and the "
                "value must match a configured trusted frontend origin; otherwise "
                "the API returns 403 origin_rejected."
            )
            operation["description"] = (
                f"{operation.get('description', '').rstrip()}\n\n{origin_note}"
            ).strip()
            operation["security"] = []
            parameters = operation.setdefault("parameters", [])
            names = {item.get("name") for item in parameters if isinstance(item, dict)}
            for header_name in ("Origin", "Referer"):
                if header_name not in names:
                    parameters.append(
                        {
                            "name": header_name,
                            "in": "header",
                            "required": False,
                            "description": (
                                "One of Origin or Referer must match a configured "
                                "trusted frontend origin."
                            ),
                            "schema": {"type": "string"},
                        }
                    )
            error_codes = WAITLIST_ERROR_CODES.get((path, method), {})
            for status, codes in error_codes.items():
                response = operation.get("responses", {}).get(status)
                if not isinstance(response, dict):
                    continue
                content = response.get("content", {}).get("application/json")
                if not isinstance(content, dict):
                    continue
                content.pop("example", None)
                content["examples"] = {
                    code: {
                        "summary": code.replace("_", " "),
                        "value": _waitlist_error_example(code),
                    }
                    for code in codes
                }

    security_schemes = schema.setdefault("components", {}).setdefault(
        "securitySchemes", {}
    )
    security_schemes["BrowserSession"] = {
        "type": "apiKey",
        "in": "cookie",
        "name": "allies_access",
        "description": (
            "Browser session cookie. Mutating requests also require a trusted "
            "Origin or Referer and a matching CSRF cookie/header."
        ),
    }
    onboarding_attempt = (
        schema.get("paths", {}).get("/api/v1/onboarding/attempts", {}).get("post")
    )
    if isinstance(onboarding_attempt, dict):
        onboarding_attempt["security"] = []
        onboarding_attempt["description"] = (
            f"{onboarding_attempt.get('description', '').rstrip()}\n\n"
            "This public operation has two closed transports. Native requests "
            "must send no Origin, Referer, Cookie, X-CSRFToken, or Authorization; "
            "they are admitted only when ALLIES_AUTH_NATIVE_ENABLED is true and "
            "the Railway server-provided X-Real-IP passes the bounded native "
            "requester and global throttles. Browser-marked requests stay on the "
            "trusted-origin and double-submit CSRF path; they never fall through "
            "to native. The native gate is disabled by default."
        ).strip()
        _add_header_parameter(
            onboarding_attempt,
            "Origin",
            "Browser-only signal; if present it must be a configured trusted origin.",
        )
        _add_header_parameter(
            onboarding_attempt,
            "Referer",
            "Browser-only signal; if present its origin must be trusted.",
        )
        _add_header_parameter(
            onboarding_attempt,
            "X-CSRFToken",
            "Browser-only double-submit header; never send it from native clients.",
        )
        _add_no_store_header(onboarding_attempt)
        for status, codes in ONBOARDING_ERROR_CODES[
            ("/api/v1/onboarding/attempts", "post")
        ].items():
            response = _response(onboarding_attempt, status)
            if response is None:
                continue
            content = response.get("content", {}).get("application/json")
            if not isinstance(content, dict):
                continue
            content.pop("example", None)
            content["examples"] = {
                code: {
                    "summary": code.replace("_", " "),
                    "value": _onboarding_error_example(code),
                }
                for code in codes
            }

    invite_claim = (
        schema.get("paths", {}).get("/api/v1/auths/invites/claim", {}).get("post")
    )
    if isinstance(invite_claim, dict):
        invite_claim["security"] = []
        invite_claim["description"] = (
            f"{invite_claim.get('description', '').rstrip()}\n\n"
            "This browser-only operation requires a trusted Origin or Referer and "
            "matching CSRF cookie/header. Claiming an invite records only the "
            "normalized email grant; it does not create an account. Responses are "
            "never cacheable."
        ).strip()
        _add_header_parameter(
            invite_claim,
            "Origin",
            "Required and must match a configured trusted frontend origin.",
        )
        _add_header_parameter(
            invite_claim,
            "Referer",
            "Browser alternative to Origin; its origin must be trusted.",
        )
        _add_header_parameter(
            invite_claim,
            "X-CSRFToken",
            "Required with the browser CSRF cookie.",
        )
        for status in (200, 403, 409, 422, 429, 503):
            _add_no_store_header(invite_claim, status)

    allies_create = (
        schema.get("paths", {})
        .get("/api/v1/workspaces/{workspace_id}/allies", {})
        .get("post")
    )
    if isinstance(allies_create, dict):
        allies_create["security"] = [
            {"BrowserSession": []},
            {"BearerAuth": []},
        ]
        allies_create["description"] = (
            f"{allies_create.get('description', '').rstrip()}\n\n"
            "Create accepts either a browser session cookie plus trusted Origin/"
            "Referer and CSRF, or a validated native bearer with no browser or "
            "session signals. Native bearer requests require the native feature "
            "gate and Workspace write capability; Authorization/browser hybrids "
            "cannot bypass CSRF. This operation is never anonymous."
        ).strip()
        _add_header_parameter(
            allies_create,
            "Origin",
            "Required for browser transport and must be trusted; omit for native.",
        )
        _add_header_parameter(
            allies_create,
            "Referer",
            "Browser alternative to Origin; omit for native.",
        )
        _add_header_parameter(
            allies_create,
            "X-CSRFToken",
            "Required with the browser CSRF cookie; omit for native.",
        )
        for status, codes in ONBOARDING_ERROR_CODES[
            ("/api/v1/workspaces/{workspace_id}/allies", "post")
        ].items():
            response = _response(allies_create, status)
            if response is None:
                continue
            content = response.get("content", {}).get("application/json")
            if not isinstance(content, dict):
                continue
            content.pop("example", None)
            content["examples"] = {
                code: {
                    "summary": code.replace("_", " "),
                    "value": _onboarding_error_example(code),
                }
                for code in codes
            }

    workspace_runtime_intent = (
        schema.get("paths", {})
        .get("/api/v1/onboarding/runtime-intents", {})
        .get("post")
    )
    if isinstance(workspace_runtime_intent, dict):
        workspace_runtime_intent["security"] = [
            {"BrowserSession": []},
            {"BearerAuth": []},
        ]
        workspace_runtime_intent["description"] = (
            f"{workspace_runtime_intent.get('description', '').rstrip()}\n\n"
            "This operation accepts either a browser session with a trusted "
            "Origin or Referer and matching CSRF cookie/header, or a validated "
            "native bearer-only session. The workspace is derived from the "
            "authenticated principal; request content contains no Ally draft."
        ).strip()
        _add_header_parameter(
            workspace_runtime_intent,
            "Origin",
            "Required for browser transport and must be trusted; omit for native.",
        )
        _add_header_parameter(
            workspace_runtime_intent,
            "Referer",
            "Browser alternative to Origin; omit for native.",
        )
        _add_header_parameter(
            workspace_runtime_intent,
            "X-CSRFToken",
            "Required with the browser CSRF cookie; omit for native.",
        )
        for status, codes in ONBOARDING_ERROR_CODES[
            ("/api/v1/onboarding/runtime-intents", "post")
        ].items():
            response = _response(workspace_runtime_intent, status)
            if response is None:
                continue
            content = response.get("content", {}).get("application/json")
            if not isinstance(content, dict):
                continue
            content.pop("example", None)
            content["examples"] = {
                code: {
                    "summary": code.replace("_", " "),
                    "value": _onboarding_error_example(code),
                }
                for code in codes
            }

    bearer_paths = {
        ("/api/v1/auths/me", "get"),
        ("/api/v1/auths/me/profile", "patch"),
        ("/api/v1/auths/me/avatar/uploads", "post"),
        ("/api/v1/auths/me/avatar/{asset_id}/complete", "post"),
        ("/api/v1/auths/me/avatar/read", "get"),
        ("/api/v1/auths/me/avatar", "delete"),
        ("/api/v1/workspaces/{workspace_id}", "get"),
    }
    chat_mutation_paths = {
        (
            "/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages",
            "post",
        ),
        (
            "/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/{message_id}/retry",
            "post",
        ),
        (
            "/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/{message_id}",
            "delete",
        ),
    }
    approval_read_paths = {
        (
            "/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/approvals",
            "get",
        ),
        (
            "/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/approvals/{approval_id}",
            "get",
        ),
    }
    approval_decision_path = (
        "/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/approvals/{approval_id}/decision",
        "post",
    )
    security_schemes = schema.setdefault("components", {}).setdefault(
        "securitySchemes", {}
    )
    security_schemes["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": (
            "Native sessions only. The bearer is accepted only on the reviewed "
            "account, profile, avatar, Workspace, and chat methods."
        ),
    }
    for path, method in bearer_paths:
        operation = schema.get("paths", {}).get(path, {}).get(method)
        if isinstance(operation, dict):
            operation["security"] = [{"BearerAuth": []}]
    for path, method in approval_read_paths:
        operation = schema.get("paths", {}).get(path, {}).get(method)
        if isinstance(operation, dict):
            operation["security"] = [{"BrowserSession": []}, {"BearerAuth": []}]
            operation["description"] = (
                f"{operation.get('description', '').rstrip()}\n\n"
                "Approval summaries and authorized detail are membership-scoped; "
                "the detail response contains the complete redacted action preview."
            ).strip()
    operation = (
        schema.get("paths", {})
        .get(approval_decision_path[0], {})
        .get(approval_decision_path[1])
    )
    if isinstance(operation, dict):
        operation["security"] = [{"BrowserSession": []}, {"BearerAuth": []}]
        operation["description"] = (
            f"{operation.get('description', '').rstrip()}\n\n"
            "This mutation accepts either a browser session with a trusted Origin "
            "or Referer and matching CSRF cookie/header, or a validated native "
            "bearer-only session. Mixed browser and bearer transport is rejected. "
            "The idempotency key must be reused for an exact retry."
        ).strip()
        for header_name, description in (
            (
                "Origin",
                "Required for browser transport and must be trusted; omit for native.",
            ),
            (
                "Referer",
                "Browser alternative to Origin; omit for native.",
            ),
            (
                "X-CSRFToken",
                "Required with the browser CSRF cookie; omit for native.",
            ),
        ):
            _add_header_parameter(operation, header_name, description)
        _add_header_parameter(
            operation,
            "Idempotency-Key",
            "Stable UUID for repeating exactly one approval choice.",
        )
    for path, method in chat_mutation_paths:
        operation = schema.get("paths", {}).get(path, {}).get(method)
        if not isinstance(operation, dict):
            continue
        operation["security"] = [{"BrowserSession": []}, {"BearerAuth": []}]
        operation["description"] = (
            f"{operation.get('description', '').rstrip()}\n\n"
            "This mutation accepts either a browser session with a trusted Origin "
            "or Referer and matching CSRF cookie/header, or a validated native "
            "bearer-only session. Mixed browser and bearer transport is rejected."
        ).strip()
        _add_header_parameter(
            operation,
            "Origin",
            "Required for browser transport and must be trusted; omit for native.",
        )
        _add_header_parameter(
            operation,
            "Referer",
            "Browser alternative to Origin; omit for native.",
        )
        _add_header_parameter(
            operation,
            "X-CSRFToken",
            "Required with the browser CSRF cookie; omit for native.",
        )
    upload = (
        schema.get("paths", {})
        .get(
            "/api/v1/workspaces/{workspace_id}/allies/{ally_id}/files/{file_id}/content",
            {},
        )
        .get("put")
    )
    if isinstance(upload, dict):
        upload["requestBody"] = {
            "required": True,
            "content": {
                "application/octet-stream": {
                    "schema": {
                        "type": "string",
                        "format": "binary",
                        "maxLength": 25000000,
                    }
                }
            },
        }
        for parameter in upload.get("parameters", []):
            if parameter.get("name") == "Content-Length":
                parameter["required"] = True
                parameter["schema"] = {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 25000000,
                }
                parameter["description"] = "Exact raw byte length; maximum 25,000,000."
    for path, path_item in schema.get("paths", {}).items():
        if not path.startswith("/api/v1/auths/native/"):
            continue
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            operation["security"] = (
                [{}, {"BearerAuth": []}] if path.endswith("/logout") else []
            )
            operation["description"] = (
                f"{operation.get('description', '').rstrip()}\n\n"
                "Native routes do not use browser cookies or CSRF. Token responses "
                "are non-cacheable; native logout accepts an optional bearer only "
                "when it matches the refresh-token family."
            ).strip()
            if method == "get" and path.endswith("/callback/{provider}"):
                callback_200 = _response(operation, 200)
                if callback_200 is not None:
                    callback_200["description"] = (
                        "Manual-code completion returns a short-lived, single-use "
                        "exchange code in an HTML page."
                    )
                    callback_200["content"] = {
                        "text/html": {
                            "schema": {"type": "string"},
                            "example": "<!doctype html>...",
                        }
                    }
                    _add_no_store_header(operation, 200)
                    callback_200["headers"].update(
                        {
                            name: {"schema": {"type": "string"}, "example": example}
                            for name, example in {
                                "Pragma": "no-cache",
                                "Referrer-Policy": "no-referrer",
                                "X-Content-Type-Options": "nosniff",
                                "Content-Security-Policy": (
                                    "default-src 'none'; style-src 'unsafe-inline'; "
                                    "script-src 'nonce-<per-response-nonce>'; "
                                    "base-uri 'none'; form-action 'none'; "
                                    "frame-ancestors 'none'"
                                ),
                            }.items()
                        }
                    )
                callback_303 = _response(operation, 303)
                if callback_303 is not None:
                    callback_303.setdefault("headers", {})["Location"] = {
                        "schema": {"type": "string"},
                        "description": (
                            "The exact app redirect URI stored on the transaction."
                        ),
                    }
            if method in {"post"} and path.endswith(("/token", "/token/refresh")):
                for response in operation.get("responses", {}).values():
                    if isinstance(response, dict) and "content" in response:
                        response.setdefault("headers", {})["Cache-Control"] = {
                            "schema": {"type": "string"},
                            "example": "no-store",
                        }
                        response["headers"]["Pragma"] = {
                            "schema": {"type": "string"},
                            "example": "no-cache",
                        }
    return schema


class AlliesAPI(NinjaExtraAPI):
    """Ninja API with the Allies response documentation contract."""

    def get_openapi_schema(self, *args, **kwargs):
        return add_standard_response_examples(
            super().get_openapi_schema(*args, **kwargs)
        )
