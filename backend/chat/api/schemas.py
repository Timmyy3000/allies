from datetime import datetime
from typing import Any

from ninja import Schema
from pydantic import ConfigDict, Field


class SendMessageRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=16_000)


class MessageResponse(Schema):
    id: str
    sender: str
    content: str
    sequence: int
    status: str
    created_at: datetime


class ConversationResponse(Schema):
    id: str
    ally_id: str
    messages: list[MessageResponse]
    next_cursor: str | None = None


class MessageAcceptanceResponse(Schema):
    conversation_id: str
    message: MessageResponse
    execution: dict[str, Any] | None = None
    replayed: bool
