from typing import Literal
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field


class ConnectKeyRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=16, max_length=512)


class SelectModelRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, max_length=32)
    model: str | None = Field(default=None, max_length=128)
    reasoning: Literal["high", "xhigh"] | None = None


class ModelKeyItem(Schema):
    provider: str
    key_hint: str
    connected_at: str


class AllyModelItem(Schema):
    ally_id: UUID
    source: Literal["own_key", "org_default"]
    provider: str | None
    model: str | None
    reasoning: str | None
    status: Literal["pending", "connected", "degraded"]


class ModelKeysResponse(Schema):
    providers: list[str]
    keys: list[ModelKeyItem]
    allies: list[AllyModelItem]


class CredentialResolveRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    workspace_id: str = Field(max_length=64)
    reference: str = Field(max_length=128)
