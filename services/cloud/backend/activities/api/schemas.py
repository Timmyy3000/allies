from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field

from chat.api.schemas import AssistantReplyResponse

ApprovalStatusValue = Literal[
    "pending",
    "decision_recorded",
    "approved",
    "rejected",
    "expired",
    "cancelled",
    "outcome_unknown",
]


class ApprovalExplanationResponse(Schema):
    model_config = ConfigDict(extra="forbid")

    version: Literal["approval-explanation.v1"]
    approval_request_id: UUID
    preview_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source: Literal["model", "fallback"]
    action: str = Field(min_length=1, max_length=240)
    target: str = Field(min_length=1, max_length=240)
    consequence: str = Field(min_length=1, max_length=240)
    reason: str = Field(min_length=1, max_length=240)


class ApprovalTechnicalDetails(Schema):
    model_config = ConfigDict(extra="forbid")

    action_kind: Literal["terminal", "execute_code", "plugin_tool"]
    action_label: str = Field(min_length=1, max_length=120)
    action_preview: str = Field(min_length=1, max_length=16_384)


class ApprovalSummaryResponse(Schema):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["approval.v1"]
    id: UUID
    message_id: UUID
    conversation_turn_ordinal: int = Field(ge=1)
    status: ApprovalStatusValue
    decision: Literal["approve", "reject"] | None = None
    decision_recorded: bool
    expires_at: datetime
    decided_at: datetime | None = None
    acknowledgement_deadline_at: datetime | None = None


class ApprovalDetailResponse(ApprovalSummaryResponse):
    approval_request_id: UUID
    preview_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    action_label: str
    action_preview: str
    explanation: ApprovalExplanationResponse
    technical_details: ApprovalTechnicalDetails


class ApprovalActivitySummaryResponse(Schema):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["approval.v1"]
    id: UUID
    status: ApprovalStatusValue
    decision: Literal["approve", "reject"] | None = None
    decision_recorded: bool
    expires_at: datetime
    decided_at: datetime | None = None


class ApprovalListResponse(Schema):
    approvals: list[ApprovalSummaryResponse]


class ApprovalDecisionRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]


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
    approval: ApprovalActivitySummaryResponse | None = None
    # Set on a compacted replay row that covers first_sequence..sequence.
    first_sequence: int | None = None


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
