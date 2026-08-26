from datetime import datetime
from typing import Any
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field


class SendMessageRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=16_000)


class MessageResponse(Schema):
    id: UUID
    sender: str
    content: str
    sequence: int
    status: str
    created_at: datetime


class ConversationResponse(Schema):
    id: UUID
    ally_id: UUID
    messages: list[MessageResponse]
    next_cursor: str | None = None


class MessageAcceptanceResponse(Schema):
    conversation_id: UUID
    message: MessageResponse
    execution: dict[str, Any] | None = None
    replayed: bool
