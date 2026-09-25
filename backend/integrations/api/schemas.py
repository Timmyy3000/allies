from datetime import datetime
from typing import Literal
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict


class BeginConnectRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    entry_point: Literal["integrations", "in_chat"]
    ally_id: UUID | None = None
    grant_level: Literal["read", "send"] | None = None


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
    level: Literal["read", "send", "none"]


class DisconnectRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    confirm: bool


class DisconnectResponse(Schema):
    status: str
