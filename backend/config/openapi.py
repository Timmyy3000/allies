"""Stable OpenAPI examples for the public response envelope."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from django.conf import settings
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
    "SuccessResponse_MeResponse_": {
        "status": "success",
        "message": "Profile loaded",
        "data": {
            "user": {"id": "usr_018f77d8-6e61-7ca0-8c36-1ba4f1fd9d72"},
            "profile": {"display_name": "Example User", "avatar_url": None},
            "session": {
                "id": "ses_018f77d8-6e61-7ca0-8c36-1ba4f1fd9d73",
                "expires_at": "2026-08-12T12:00:00Z",
            },
            "workspace": {
                "id": "wsp_018f77d8-6e61-7ca0-8c36-1ba4f1fd9d74",
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
            "asset_id": "avt_018f77d8-6e61-7ca0-8c36-1ba4f1fd9d75",
            "upload_url": "https://uploads.example/avatar",
            "headers": {"Content-Type": "image/png"},
            "expires_at": "2026-08-12T12:00:00Z",
        },
    },
    "SuccessResponse_AvatarResponse_": {
        "status": "success",
        "message": "Avatar loaded",
        "data": {
            "asset_id": "avt_018f77d8-6e61-7ca0-8c36-1ba4f1fd9d75",
            "url": "https://media.example/avatar",
            "expires_at": "2026-08-12T12:00:00Z",
        },
    },
    "SuccessResponse_WorkspaceContextResponse_": {
        "status": "success",
        "message": "Workspace loaded",
        "data": {
            "id": "wsp_018f77d8-6e61-7ca0-8c36-1ba4f1fd9d74",
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
    "SuccessResponse_WaitlistAcknowledgement_": {
        "status": "success",
        "message": "Waitlist updated",
        "data": {
            "operation": "configure",
            "result_revision": 2,
            "result_lifecycle": "ready_for_greeting",
        },
    },
    "SuccessResponse_WaitlistSnapshot_": {
        "status": "success",
        "message": "Waitlist draft restored",
        "data": {
            "id": "wld_018f77d8-6e61-7ca0-8c36-1ba4f1fd9d72",
            "revision": 2,
            "lifecycle": "ready_for_greeting",
            "configuration": {
                "name": "Ari",
                "appearance_catalog_version": "v1",
                "appearance_key": "calm-blue",
                "job": "Planning",
                "personality": "Warm and concise",
            },
            "greeting": None,
            "reply": None,
            "join": None,
            "timestamps": {
                "created_at": "2026-08-14T12:00:00Z",
                "updated_at": "2026-08-14T12:00:00Z",
                "generated_at": None,
                "replied_at": None,
                "joined_at": None,
                "expires_at": "2026-08-21T12:00:00Z",
            },
        },
    },
    "SuccessResponse_WaitlistJoinConfirmation_": {
        "status": "success",
        "message": "Waitlist joined",
        "data": {
            "operation": "join",
            "result_revision": 6,
            "result_lifecycle": "pending_claim",
            "email": "a***@example.com",
        },
    },
}

WAITLIST_ERROR_CODES: dict[tuple[str, str], dict[int, tuple[str, ...]]] = {
    ("/api/v1/waitlist/session", "get"): {
        403: ("origin_rejected",),
        429: ("throttled",),
        503: ("waitlist_unavailable",),
    },
    ("/api/v1/waitlist/draft", "get"): {
        403: ("origin_rejected",),
        404: ("waitlist_draft_unavailable",),
        429: ("throttled",),
        503: ("waitlist_unavailable",),
    },
    ("/api/v1/waitlist/draft", "post"): {
        403: ("origin_rejected", "csrf_rejected"),
        404: ("waitlist_draft_unavailable",),
        409: ("idempotency_conflict", "waitlist_operation_in_progress"),
        422: ("validation_error",),
        429: ("throttled",),
        503: ("waitlist_unavailable",),
    },
    ("/api/v1/waitlist/draft/configuration", "patch"): {
        403: ("origin_rejected", "csrf_rejected"),
        404: ("waitlist_draft_unavailable",),
        409: (
            "waitlist_draft_stale",
            "waitlist_invalid_state",
            "idempotency_conflict",
            "waitlist_operation_in_progress",
        ),
        422: ("validation_error",),
        429: ("throttled",),
        503: ("waitlist_unavailable",),
    },
    ("/api/v1/waitlist/draft/greeting", "post"): {
        403: ("origin_rejected", "csrf_rejected"),
        404: ("waitlist_draft_unavailable",),
        409: (
            "waitlist_draft_stale",
            "waitlist_invalid_state",
            "idempotency_conflict",
            "waitlist_operation_in_progress",
        ),
        422: ("validation_error",),
        429: ("throttled",),
        503: (
            "generation_outcome_unknown",
            "generation_unavailable",
            "waitlist_unavailable",
        ),
    },
    ("/api/v1/waitlist/draft/reply", "post"): {
        403: ("origin_rejected", "csrf_rejected"),
        404: ("waitlist_draft_unavailable",),
        409: (
            "waitlist_draft_stale",
            "waitlist_invalid_state",
            "idempotency_conflict",
            "waitlist_operation_in_progress",
        ),
        422: ("validation_error",),
        429: ("throttled",),
        503: ("waitlist_unavailable",),
    },
    ("/api/v1/waitlist/draft/join", "post"): {
        403: ("origin_rejected", "csrf_rejected"),
        404: ("waitlist_draft_unavailable",),
        409: (
            "waitlist_draft_stale",
            "waitlist_invalid_state",
            "idempotency_conflict",
            "waitlist_operation_in_progress",
        ),
        422: ("validation_error",),
        429: ("throttled",),
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

    # The waitlist browser contract is credentialed and retry-aware.  Ninja
    # cannot infer these transport headers from controller helpers, so publish
    # them explicitly for INT-009's generated client.
    components = schema.setdefault("components", {})
    components.setdefault("securitySchemes", {})["WaitlistCapability"] = {
        "type": "apiKey",
        "in": "cookie",
        "name": str(
            getattr(
                settings,
                "ALLIES_WAITLIST_CAPABILITY_COOKIE",
                "allies_waitlist_capability",
            )
        ),
        "description": "HttpOnly browser capability issued by GET /waitlist/session.",
    }

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
            if path.endswith("/session"):
                operation["security"] = []
            else:
                operation["security"] = [{"WaitlistCapability": []}]
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
            is_restore = path == "/api/v1/waitlist/draft" and method.lower() == "get"
            if (
                not path.endswith("/session")
                and not is_restore
                and "Idempotency-Key" not in names
            ):
                parameters.append(
                    {
                        "name": "Idempotency-Key",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string", "minLength": 1, "maxLength": 200},
                    }
                )
            if (
                not path.endswith("/session")
                and not is_restore
                and "X-CSRFToken" not in names
            ):
                parameters.append(
                    {
                        "name": "X-CSRFToken",
                        "in": "header",
                        "required": True,
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
    return schema


class AlliesAPI(NinjaExtraAPI):
    """Ninja API with the Allies response documentation contract."""

    def get_openapi_schema(self, *args, **kwargs):
        return add_standard_response_examples(
            super().get_openapi_schema(*args, **kwargs)
        )
