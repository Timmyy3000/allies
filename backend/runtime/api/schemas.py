from __future__ import annotations

from typing import Any
from uuid import UUID

from ninja import Schema


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
