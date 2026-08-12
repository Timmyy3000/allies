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
    return schema


class AlliesAPI(NinjaExtraAPI):
    """Ninja API with the Allies response documentation contract."""

    def get_openapi_schema(self, *args, **kwargs):
        return add_standard_response_examples(
            super().get_openapi_schema(*args, **kwargs)
        )
