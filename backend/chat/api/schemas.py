from datetime import datetime
from typing import Any, Literal
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
    retryable: bool = False
    queue_state: Literal["claimed", "unclaimed"] | None = None
    deleted_at: datetime | None = None


class AssistantReplyResponse(Schema):
    id: UUID
    source_message_id: UUID
    conversation_turn_ordinal: int
    content: str
    status: str
    has_full_prefix: bool
    is_truncated: bool
    created_at: datetime
    updated_at: datetime


class ConversationResponse(Schema):
    id: UUID
    ally_id: UUID
    messages: list[MessageResponse]
    queue: list[MessageResponse] = Field(default_factory=list)
    assistant_replies: list[AssistantReplyResponse] = Field(default_factory=list)
    next_cursor: str | None = None


class MessageAcceptanceResponse(Schema):
    conversation_id: UUID
    message: MessageResponse
    execution: dict[str, Any] | None = None
    replayed: bool
