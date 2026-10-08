from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from ninja import Schema
from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)


class RoutineMessageAction(Schema):
    """Structured intent attached to a user message for routine controls."""

    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "pause",
        "resume",
        "delete",
        "approve",
        "reject",
        "cancel_wait",
    ]
    routine_id: UUID
    expected_revision: StrictInt = Field(ge=1, le=2_147_483_647)
    title_snapshot: StrictStr = Field(min_length=1, max_length=120)
    confirmed: StrictBool = False
    run_id: UUID | None = None
    approval_id: UUID | None = None
    approval_request_id: UUID | None = None
    execution_id: UUID | None = None
    attempt_id: UUID | None = None
    action_attempt_id: UUID | None = None
    generation: StrictInt | None = Field(default=None, ge=0, le=2_147_483_647)

    @model_validator(mode="after")
    def validate_title_snapshot(self) -> "RoutineMessageAction":
        if not self.title_snapshot.strip() or "\x00" in self.title_snapshot:
            raise ValueError("title_snapshot must contain a non-empty title")
        return self


class SendMessageRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=16_000)
    timezone: str = Field(default="", max_length=64)
    routine_action: RoutineMessageAction | None = None


class SteerRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=16_000)


class StopConversationResponse(Schema):
    stop_requested: bool


class MessageFileResponse(Schema):
    id: UUID
    name: str
    size: int
    state: str


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
    preparation: str = "none"
    revision: int = 0
    files: list[MessageFileResponse] = Field(default_factory=list)


class AssistantReplyResponse(Schema):
    id: UUID
    source_message_id: UUID
    conversation_turn_ordinal: int
    content: str
    status: str
    has_full_prefix: bool
    is_truncated: bool
    publications: list[dict] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class RoutineChatItemResponse(Schema):
    id: UUID
    kind: Literal["created", "running", "result"]
    routine_id: UUID
    conversation_id: UUID
    source_message_id: UUID | None = None
    title_snapshot: str
    routine_revision: int
    schedule_generation: int
    status: str
    schedule: Any
    occurred_at: datetime
    occurrence_id: UUID | None = None
    run_id: UUID | None = None
    execution_id: UUID | None = None
    attempt_id: UUID | None = None
    generation: int | None = None
    result_id: UUID | None = None
    result_insertion: Literal["pending", "inserted"] | None = None
    text: str | None = None
    references: list[Any] = Field(default_factory=list)
    delayed: bool | None = None
    approval_id: UUID | None = None
    approval_request_id: UUID | None = None
    approval_status: str | None = None
    approval_decision: Literal["approve", "reject"] | None = None
    action_digest: str | None = None
    action_attempt_id: UUID | None = None
    approval_expires_at: datetime | None = None


class ConversationResponse(Schema):
    id: UUID
    ally_id: UUID
    messages: list[MessageResponse]
    queue: list[MessageResponse] = Field(default_factory=list)
    assistant_replies: list[AssistantReplyResponse] = Field(default_factory=list)
    routine_items: list[RoutineChatItemResponse] = Field(default_factory=list)
    next_cursor: str | None = None


class MessageAcceptanceResponse(Schema):
    conversation_id: UUID
    message: MessageResponse
    execution: dict[str, Any] | None = None
    replayed: bool
