from datetime import datetime

from ninja import Schema


class RedirectRequest(Schema):
    redirect_to: str = "/"


class AuthorizationStartResponse(Schema):
    redirect_url: str


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
    id: str
    expires_at: datetime


class WorkspaceResponse(Schema):
    id: str
    name: str
    role: str
    capabilities: list[str]


class MeResponse(Schema):
    actor: dict[str, str]
    profile: ProfileResponse
    session: SessionResponse
    workspace: WorkspaceResponse


class PreparedAvatarResponse(Schema):
    asset_id: str
    upload_url: str
    headers: dict[str, str]
    expires_at: datetime


class AvatarResponse(Schema):
    asset_id: str
    url: str | None = None
    expires_at: datetime | None = None


class ErrorResponse(Schema):
    error: dict[str, str]
