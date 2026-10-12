from datetime import datetime
from typing import Literal
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field


class BeginConnectRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    entry_point: Literal["integrations", "in_chat"]
    ally_id: UUID | None = None
    grant_level: Literal["read", "send", "write"] | None = None
    return_to: str | None = Field(default=None, min_length=1, max_length=500)


class ConnectResponse(Schema):
    connect_session_id: UUID
    auth_url: str
    expires_at: datetime


class AllyGrantResponse(Schema):
    ally_id: UUID
    level: str
    grant_generation: int
    updated_at: datetime


class GmailConnectionResponse(Schema):
    connection_id: UUID
    account_email: str
    scope_set: list[str]
    connected_at: datetime
    ally_grants: list[AllyGrantResponse]


class SetGrantRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    ally_id: UUID
    level: Literal["read", "send", "write", "none"]


class DisconnectRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    confirm: bool


class DisconnectResponse(Schema):
    status: str


WebSearchBackend = Literal["parallel", "tavily", "exa"]


class ConnectWebSearchRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    backend: WebSearchBackend
    api_key: str = Field(min_length=16, max_length=512)


class WebSearchGrantRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    ally_id: UUID
    level: Literal["use", "none"]


class WebSearchConnectionResponse(Schema):
    connection_id: UUID
    backend: WebSearchBackend
    key_hint: str
    connected_at: datetime
    ally_grants: list[AllyGrantResponse]
