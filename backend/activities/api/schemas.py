from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ninja import Schema

from chat.api.schemas import AssistantReplyResponse


class ActivityResponse(Schema):
    id: UUID
    message_id: UUID
    sequence: int
    conversation_turn_ordinal: int
    kind: str
    text: str
    state: str
    created_at: datetime
    activity_attempt_id: str | None = None
    activity_id: str | None = None
    activity_kind: str | None = None
    outcome: str | None = None
    duration_ms: int | None = None


class ActivitySnapshotResponse(Schema):
    conversation_id: UUID
    activities: list[ActivityResponse]
    state: str
    last_contiguous_sequence: int
    last_contiguous_activity_sequence: int
    resume_cursor: str | None = None
    next_cursor: str | None = None
    oldest_sequence: int | None = None
    latest_sequence: int | None = None
    retention_gap: bool = False
    assistant_reply: AssistantReplyResponse | None = None
    active_message_id: UUID | None = None
