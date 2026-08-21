from __future__ import annotations

from typing import Any
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field, StrictInt, StrictStr


class ClaimRequest(Schema):
    claim_id: UUID
    available_slots: int


class EventRequest(Schema):
    event_id: UUID
    stream_id: str
    sequence: int
    type: str
    payload: dict[str, Any]


class SessionBindingRequest(Schema):
    cloud_conversation_ref: str
    expected_session_id: str | None = None
    effective_session_id: str


class StoppedRequest(Schema):
    reason: str


class TerminalEventRequest(Schema):
    event_id: UUID
    stream_id: str
    sequence: int
    payload: dict[str, Any]


class CompleteRequest(TerminalEventRequest):
    receipt: dict[str, Any]


class FailRequest(TerminalEventRequest):
    code: str
    retryable: bool
    receipt: dict[str, Any] | None = None


class MaterializationReceiptRequest(Schema):
    profile_id: UUID
    operation_id: UUID
    lifecycle_epoch: int
    materialized_generation: int
    seed_fingerprint: str
    result_code: str


class CleanupReceiptRequest(Schema):
    profile_id: UUID
    operation_id: UUID
    lifecycle_epoch: int
    request_digest: str
    result_code: str
    deleted: bool
    active_lease_count: int


class ProfileProvisioningRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    version: StrictInt = Field(..., ge=1, le=1)
    workspace_id: StrictStr = Field(
        ...,
        min_length=1,
        max_length=40,
        pattern=r"^[^\s\x00-\x1f\x7f]{1,40}$",
    )
    binding_id: StrictStr = Field(
        ...,
        min_length=1,
        max_length=40,
        pattern=r"^[^\s\x00-\x1f\x7f]{1,40}$",
    )
    ally_ref: StrictStr = Field(
        ...,
        min_length=1,
        max_length=40,
        pattern=r"^[^\s\x00-\x1f\x7f]{1,40}$",
    )
    operation_id: StrictStr = Field(
        ...,
        min_length=1,
        max_length=40,
        pattern=r"^[^\s\x00-\x1f\x7f]{1,40}$",
    )
    request_fingerprint: StrictStr = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    job: StrictStr = Field(
        ...,
        min_length=1,
        max_length=200,
        pattern=r"^[^\x00\r]*$",
    )
    personality: StrictStr = Field(
        ...,
        min_length=1,
        max_length=4000,
        pattern=r"^[^\x00\r]*$",
    )


class ProfileProvisioningReceipt(Schema):
    model_config = ConfigDict(extra="forbid")

    version: StrictInt
    binding_id: StrictStr
    operation_id: StrictStr
    request_fingerprint: StrictStr
    status: StrictStr = Field(
        ...,
        pattern=r"^(pending|active|cleanup_pending|deprovisioned|repair_required)$",
    )
    evidence_digest: StrictStr = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
