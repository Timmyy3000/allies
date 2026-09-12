from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field, StrictInt, StrictStr, field_validator

from runtime.contracts import (
    MAX_RUNTIME_EVENT_SEQUENCE,
    MAX_TERMINAL_SEQUENCE,
    ApprovalDecisionCommand,
    ApprovalDecisionReceipt,
    ExecutionCommand,
    ExecutionReceipt,
    FoundryEventEnvelope,
    ReconciliationReceipt,
)

__all__ = [
    "ApprovalDecisionCommand",
    "ApprovalDecisionReceipt",
    "ClaimRequest",
    "CleanupReceiptRequest",
    "CompleteRequest",
    "EventRequest",
    "ExecutionCommand",
    "ExecutionReceipt",
    "FailRequest",
    "FoundryEventEnvelope",
    "MaterializationReceiptRequest",
    "ProfileProvisioningReceipt",
    "ProfileProvisioningRequest",
    "PublicationFrozenRequest",
    "PublicationIntentRequest",
    "PublicationRegisterRequest",
    "PublicationRetryClaimRequest",
    "PublicationRetryResultRequest",
    "ReconciliationReceipt",
    "RoutineSessionBindingRequest",
    "RuntimeActivityWaitReceipt",
    "RuntimeActivityWaitRequest",
    "RuntimeIntentReceipt",
    "RuntimeIntentRequest",
    "RuntimeReadinessReceipt",
    "RuntimeReadinessRequest",
    "SessionBindingRequest",
    "StoppedRequest",
    "TerminalEventRequest",
]


class ClaimRequest(Schema):
    claim_id: UUID
    available_slots: int


class PublicationPreparationFile(Schema):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr = Field(..., min_length=1, max_length=255)
    size: StrictInt = Field(..., ge=1, le=25_000_000)


class PublicationIntentRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: StrictStr = Field(..., min_length=1, max_length=255)
    files: list[PublicationPreparationFile] = Field(..., min_length=1, max_length=10)


class PublicationFrozenFile(Schema):
    model_config = ConfigDict(extra="forbid")

    source_version_id: UUID
    name: StrictStr = Field(..., min_length=1, max_length=255)
    size: StrictInt = Field(..., ge=1, le=25_000_000)
    sha256: StrictStr = Field(
        ..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )


class PublicationFrozenRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    files: list[PublicationFrozenFile] = Field(..., min_length=1, max_length=10)


class PublicationRegisterRequest(PublicationFrozenRequest):
    model_config = ConfigDict(extra="forbid")

    publication_id: UUID


class PublicationRetryClaimRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    limit: StrictInt = Field(..., ge=1, le=20)


class PublicationRetryResultRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    revision: StrictInt = Field(..., ge=1)
    lease_token: UUID
    outcome: Literal["submitted", "failed"]
    safe_error_code: StrictStr | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$"
    )


class RuntimeIntentRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["composing_started", "ally_creation_started"]
    received_at: datetime


class RuntimeIntentReceipt(Schema):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "already_ready",
        "waking",
        "ready",
        "first_provision_required",
        "rate_limited",
        "failed",
    ]


class RuntimeActivityWaitRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    after_revision: StrictInt = Field(..., ge=0)
    wait_seconds: float = Field(..., gt=0, le=5)


class RuntimeActivityWaitReceipt(Schema):
    model_config = ConfigDict(extra="forbid")

    revision: StrictInt = Field(..., ge=0)
    reason: Literal["changed", "timeout"]


class RuntimeReadinessRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    boot_id: UUID
    reconciled_generation: StrictInt = Field(..., ge=1)
    runtime_start_epoch: StrictInt = Field(..., ge=0)


class RuntimeReadinessReceipt(Schema):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready"]
    generation: StrictInt = Field(..., ge=1)
    runtime_start_epoch: StrictInt = Field(..., ge=0)
    accepted_at: datetime


class EventRequest(Schema):
    event_id: UUID
    stream_id: str
    sequence: StrictInt = Field(..., ge=1, le=MAX_RUNTIME_EVENT_SEQUENCE)
    type: str
    payload: dict[str, Any]


class SessionBindingRequest(Schema):
    cloud_conversation_ref: str
    expected_session_id: str | None = None
    effective_session_id: str


class RoutineSessionBindingRequest(Schema):
    expected_session_id: str | None = None
    effective_session_id: str


class StoppedRequest(Schema):
    reason: str


class TerminalEventRequest(Schema):
    event_id: UUID
    stream_id: str
    sequence: StrictInt = Field(..., ge=1, le=MAX_TERMINAL_SEQUENCE)
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


class CleanupQuiescence(Schema):
    model_config = ConfigDict(extra="forbid")

    state: Literal["quiescing", "quiesced", "repair_required"]
    safe_error_code: StrictStr = Field(
        default="", max_length=64, pattern=r"^$|^[a-z][a-z0-9_]{0,63}$"
    )
    active_runs: StrictInt = Field(..., ge=0)
    active_profile_io: StrictInt = Field(..., ge=0)
    open_profile_stores: StrictInt = Field(..., ge=0)
    owned_children: StrictInt = Field(..., ge=0)


class CleanupReceiptRequest(Schema):
    profile_id: UUID
    operation_id: UUID
    lifecycle_epoch: int
    request_digest: str
    result_code: str
    deleted: bool
    active_lease_count: int
    attempt_id: UUID | None = None
    machine_generation: StrictInt | None = None
    runtime_start_epoch: StrictInt | None = None
    runtime_boot_id: UUID | None = None
    hermes_instance_id: UUID | None = None
    quiescence: CleanupQuiescence | None = None


class ProfileDeletionRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    version: StrictInt = Field(..., ge=1, le=1)
    workspace_id: UUID
    ally_id: UUID
    binding_id: UUID
    operation_id: UUID


class ProfileDeletionResumeRequest(ProfileDeletionRequest):
    expected_attempt_id: UUID


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
    name: StrictStr = Field(
        default="",
        max_length=80,
        pattern=r"^[^\x00-\x1f\x7f]*$",
    )
    job: StrictStr = Field(
        ...,
        min_length=1,
        max_length=200,
        pattern=r"^[^\x00-\x09\x0b-\x1f\x7f]*$",
    )
    personality: StrictStr = Field(
        ...,
        min_length=1,
        max_length=4000,
        pattern=r"^[^\x00-\x09\x0b-\x1f\x7f]*$",
    )

    @field_validator("name")
    @classmethod
    def reject_prompt_control_characters(cls, value: str) -> str:
        if any(
            unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"}
            for character in value
        ):
            raise ValueError(
                "name, job, and personality must not contain control characters"
            )
        return value

    @field_validator("job", "personality")
    @classmethod
    def reject_multiline_control_characters(cls, value: str) -> str:
        if any(
            character != "\n"
            and unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"}
            for character in value
        ):
            raise ValueError(
                "name, job, and personality must not contain control characters"
            )
        return value


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


class WorkspaceActivationRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    version: StrictInt = Field(..., ge=1, le=1)
    workspace_id: UUID


class WorkspaceActivationReceipt(Schema):
    model_config = ConfigDict(extra="forbid")

    version: StrictInt = Field(..., ge=1, le=1)
    workspace_id: UUID
    status: StrictStr = Field(..., pattern=r"^(pending|active)$")
