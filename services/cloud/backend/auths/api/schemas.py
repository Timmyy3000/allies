"""Typed request and response contracts for the Cloud authentication API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field


class SuccessResponse[DataT](Schema):
    """Stable envelope for successful JSON responses."""

    status: Literal["success"] = "success"
    message: str
    data: DataT


class ErrorData(Schema):
    """Machine-readable failure data kept separate from human messaging."""

    code: str
    details: dict[str, Any] | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "code": "validation_error",
                    "details": {"errors": [{"field": "display_name"}]},
                },
                {"code": "session_invalid"},
                {"code": "already_linked_elsewhere"},
                {"code": "throttled"},
            ]
        }
    )


class ErrorResponse[DataT](Schema):
    """Stable envelope for expected JSON failures."""

    status: Literal["error"] = "error"
    message: str
    data: DataT | None = None


class RedirectRequest(Schema):
    redirect_to: str = "/"


class ClaimInviteRequest(Schema):
    code: str = Field(min_length=8, max_length=8)
    email: str = Field(min_length=1, max_length=254)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ClaimInviteResponse(Schema):
    claimed: Literal[True] = True


class AuthorizationStartResponse(Schema):
    redirect_url: str

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"redirect_url": "https://provider.example/authorize?state=example"}
            ]
        }
    )


class NativeSignInRequest(Schema):
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str = Field(json_schema_extra={"enum": ["S256"]})
    state: str
    completion_mode: Literal["redirect", "manual_code"] = "redirect"


class NativeAuthorizationStartResponse(Schema):
    authorization_url: str
    expires_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?...",
                    "expires_at": "2026-08-20T16:10:00Z",
                }
            ]
        }
    )


class NativeTokenExchangeRequest(Schema):
    grant_type: str = Field(json_schema_extra={"enum": ["authorization_code"]})
    code: str
    code_verifier: str
    redirect_uri: str


class NativeRefreshRequest(Schema):
    grant_type: str = Field(json_schema_extra={"enum": ["refresh_token"]})
    refresh_token: str


class NativeLogoutRequest(Schema):
    refresh_token: str


class NativeTokenResponse(Schema):
    token_type: Literal["Bearer"]
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    session_id: UUID

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "token_type": "Bearer",
                    "access_token": "<short-lived-cloud-jwt>",
                    "expires_in": 600,
                    "refresh_token": "<rotating-opaque-cloud-token>",
                    "refresh_expires_in": 1209600,
                    "session_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d72",
                }
            ]
        }
    )


class UserResponse(Schema):
    id: UUID

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d72"}]}
    )


class ProfileUpdateRequest(Schema):
    display_name: str


class AvatarPrepareRequest(Schema):
    content_type: str
    size: int
    sha256: str


class ProfileResponse(Schema):
    display_name: str
    avatar_url: str | None = None


class SessionResponse(Schema):
    id: UUID
    expires_at: datetime


class WorkspaceResponse(Schema):
    id: UUID
    name: str
    role: str
    capabilities: list[str]


class MeResponse(Schema):
    user: UserResponse
    profile: ProfileResponse
    session: SessionResponse
    workspace: WorkspaceResponse


class PreparedAvatarResponse(Schema):
    asset_id: UUID
    upload_url: str
    headers: dict[str, str]
    expires_at: datetime


class AvatarResponse(Schema):
    asset_id: UUID
    url: str | None = None
    expires_at: datetime | None = None
