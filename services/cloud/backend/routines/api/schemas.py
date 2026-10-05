from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from ninja import Schema
from pydantic import Field


class RoutineSummaryResponse(Schema):
    id: UUID
    responsible_ally_id: UUID
    title: str
    schedule: dict[str, Any]
    revision: int
    schedule_generation: int
    schedule_state: str
    next_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RoutineDetailResponse(RoutineSummaryResponse):
    workspace_id: UUID
    owner_user_id: UUID
    binding_id: UUID
    main_conversation_id: UUID
    execution_prompt: str


class RoutinePageResponse(Schema):
    items: list[RoutineSummaryResponse] = Field(default_factory=list)
    next_cursor: str | None = None


class RoutineApprovalDecisionRequest(Schema):
    decision: Literal["approve", "reject"]


class RoutineApprovalResponse(Schema):
    id: UUID
    routine_id: UUID
    run_id: UUID
    approval_request_id: UUID
    action_attempt_id: UUID
    execution_id: UUID
    attempt_id: UUID
    generation: int
    status: str
    decision: Literal["approve", "reject"] | None = None
    action_digest: str
    expires_at: datetime
    created_at: datetime
    decided_at: datetime | None = None
    delivery_status: str
    replayed: bool = False
