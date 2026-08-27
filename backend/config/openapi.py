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
                }
            ],
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
            },
            "execution": None,
            "replayed": False,
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
            "last_contiguous_sequence": 2,
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

    bearer_paths = {
        ("/api/v1/auths/me", "get"),
        ("/api/v1/auths/me/profile", "patch"),
        ("/api/v1/auths/me/avatar/uploads", "post"),
        ("/api/v1/auths/me/avatar/{asset_id}/complete", "post"),
        ("/api/v1/auths/me/avatar/read", "get"),
        ("/api/v1/auths/me/avatar", "delete"),
        ("/api/v1/workspaces/{workspace_id}", "get"),
    }
    security_schemes = schema.setdefault("components", {}).setdefault(
        "securitySchemes", {}
    )
    security_schemes["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": (
            "Native sessions only. The bearer is accepted only on the reviewed "
            "account, profile, avatar, and Workspace methods."
        ),
    }
    for path, method in bearer_paths:
        operation = schema.get("paths", {}).get(path, {}).get(method)
        if isinstance(operation, dict):
            operation["security"] = [{"BearerAuth": []}]
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
