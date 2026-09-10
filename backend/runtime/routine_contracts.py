from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

from runtime.contracts import (
    FINGERPRINT_PREFIX,
    canonical_fingerprint,
    canonical_json_bytes,
)
from runtime.exceptions import RuntimeValidationError

ROUTINE_DISPATCH_KIND = "routine.dispatch"
ROUTINE_DISPATCH_RECEIPT_KIND = "routine.dispatch_receipt"
ROUTINE_RESULT_KIND = "routine.result"
ROUTINE_EVENT_RECEIPT_KIND = "routine.event_receipt"
ROUTINE_APPROVAL_REQUESTED_KIND = "routine.approval_requested"
ROUTINE_APPROVAL_DECISION_KIND = "routine.approval_decision"
ROUTINE_APPROVAL_RECEIPT_KIND = "routine.approval_receipt"
ROUTINE_CANCEL_WAIT_KIND = "routine.cancel_wait"

MAX_ROUTINE_TEXT_BYTES = 16 * 1024
MAX_ROUTINE_EVENT_BYTES = 64 * 1024
MAX_ROUTINE_SEQUENCE = 100000
MAX_ROUTINE_TERMINAL_SEQUENCE = 100001
MAX_ROUTINE_REFERENCE_COUNT = 32


class RoutineContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoutineScope(RoutineContractModel):
    kind: Literal["workspace"]
    workspace_id: UUID
    owner_user_id: UUID
    ally_id: UUID
    cloud_binding_id: UUID


class RoutineReference(RoutineContractModel):
    label: StrictStr = Field(..., min_length=1, max_length=255)
    url: StrictStr = Field(..., min_length=1, max_length=2048)

    @model_validator(mode="after")
    def validate_url(self) -> RoutineReference:
        if not self.url.startswith(("https://", "http://")):
            raise ValueError("reference url must use http or https")
        _validate_text(self.label, 255, "reference label")
        _validate_text(self.url, 2048, "reference url")
        return self


class RoutineEnvelope(RoutineContractModel):
    schema_version: Literal["v1"]
    producer: Literal["cloud", "foundry"]
    service_identity: StrictStr
    scope: RoutineScope
    issued_at: datetime
    deadline_at: datetime
    fingerprint: StrictStr = Field(
        ...,
        min_length=len(FINGERPRINT_PREFIX) + 64,
        max_length=len(FINGERPRINT_PREFIX) + 64,
    )

    @model_validator(mode="after")
    def validate_common(self) -> RoutineEnvelope:
        if self.producer == "cloud" and self.service_identity != "cloud-service":
            raise ValueError("cloud messages require cloud-service identity")
        if self.producer == "foundry" and self.service_identity != "foundry-service":
            raise ValueError("Foundry messages require foundry-service identity")
        _validate_times(self.issued_at, self.deadline_at)
        if not self.fingerprint.startswith(FINGERPRINT_PREFIX):
            raise ValueError("fingerprint is invalid")
        expected = _fingerprint(self)
        if self.fingerprint != expected:
            raise ValueError("fingerprint does not match envelope")
        return self


class RoutineDispatch(RoutineEnvelope):
    kind: Literal[ROUTINE_DISPATCH_KIND]
    producer: Literal["cloud"]
    service_identity: Literal["cloud-service"]
    command_id: UUID
    idempotency_key: UUID
    routine_id: UUID
    routine_revision: StrictInt = Field(..., ge=1)
    schedule_generation: StrictInt = Field(..., ge=1)
    occurrence_id: UUID
    run_id: UUID
    schedule: dict[str, Any]
    scheduled_at: datetime
    delayed: StrictBool
    occurrence_disposition: Literal[
        "admitted",
        "replay",
        "skipped_active",
        "delayed",
        "recovered",
        "cancelled",
    ]
    main_conversation_id: UUID
    run_conversation_id: UUID
    cloud_binding_id: UUID
    execution_prompt: StrictStr = Field(..., min_length=1)
    title_snapshot: StrictStr = Field(..., min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_dispatch(self) -> RoutineDispatch:
        if self.cloud_binding_id != self.scope.cloud_binding_id:
            raise ValueError("dispatch binding does not match scope")
        if len({self.main_conversation_id, self.run_conversation_id}) != 2:
            raise ValueError("routine and main conversations must differ")
        if len(self.execution_prompt.encode("utf-8")) > MAX_ROUTINE_TEXT_BYTES:
            raise ValueError("execution prompt is too large")
        if not self.schedule.get("kind") or not self.schedule.get("timezone"):
            raise ValueError("routine dispatch schedule snapshot is incomplete")
        _validate_text(self.title_snapshot, 255, "title snapshot")
        return self


class RoutineDispatchReceipt(RoutineEnvelope):
    kind: Literal[ROUTINE_DISPATCH_RECEIPT_KIND]
    producer: Literal["foundry"]
    service_identity: Literal["foundry-service"]
    command_id: UUID
    idempotency_key: UUID
    outcome: Literal["accepted", "duplicate"]
    occurrence_id: UUID
    run_id: UUID
    execution_id: UUID
    attempt_id: UUID
    generation: StrictInt = Field(..., ge=0)
    acceptance_is_completion: Literal[False]


class RoutineResult(RoutineEnvelope):
    kind: Literal[ROUTINE_RESULT_KIND]
    producer: Literal["foundry"]
    service_identity: Literal["foundry-service"]
    event_id: UUID
    event_sequence: StrictInt = Field(..., ge=1, le=MAX_ROUTINE_TERMINAL_SEQUENCE)
    routine_id: UUID
    occurrence_id: UUID
    run_id: UUID
    routine_revision: StrictInt = Field(..., ge=1)
    title_snapshot: StrictStr = Field(..., min_length=1, max_length=255)
    execution_id: UUID
    attempt_id: UUID
    generation: StrictInt = Field(..., ge=0)
    main_conversation_id: UUID
    run_conversation_id: UUID
    outcome: Literal["changed", "unchanged", "failed"]
    text: StrictStr = Field(..., min_length=1)
    references: list[RoutineReference] = Field(default_factory=list, max_length=MAX_ROUTINE_REFERENCE_COUNT)
    delayed: StrictBool

    @model_validator(mode="after")
    def validate_result(self) -> RoutineResult:
        if len(
            {
                self.main_conversation_id,
                self.run_conversation_id,
                self.execution_id,
            }
        ) != 3:
            raise ValueError("routine conversations and execution must differ")
        if len(self.text.encode("utf-8")) > MAX_ROUTINE_TEXT_BYTES:
            raise ValueError("result text is too large")
        _validate_text(self.title_snapshot, 255, "title snapshot")
        if len(canonical_json_bytes(self.model_dump(mode="json"))) > MAX_ROUTINE_EVENT_BYTES:
            raise ValueError("routine result envelope is too large")
        if self.outcome == "failed" and not self.text:
            raise ValueError("failed result requires text")
        return self


class RoutineEventReceipt(RoutineEnvelope):
    kind: Literal[ROUTINE_EVENT_RECEIPT_KIND]
    producer: Literal["cloud"]
    service_identity: Literal["cloud-service"]
    event_id: UUID
    disposition: Literal["applied", "duplicate"]
    event_sequence: StrictInt = Field(..., ge=1, le=MAX_ROUTINE_TERMINAL_SEQUENCE)
    result_insertion: Literal["pending", "inserted"]
    insertion_watermark: StrictInt | None = Field(default=None, ge=1)


class RoutineApprovalRequested(RoutineEnvelope):
    kind: Literal[ROUTINE_APPROVAL_REQUESTED_KIND]
    producer: Literal["foundry"]
    service_identity: Literal["foundry-service"]
    event_id: UUID
    event_sequence: StrictInt = Field(..., ge=1, le=MAX_ROUTINE_SEQUENCE)
    approval_request_id: UUID
    action_attempt_id: UUID
    run_id: UUID
    execution_id: UUID
    attempt_id: UUID
    generation: StrictInt = Field(..., ge=0)
    status: Literal["pending"]
    created_at: datetime
    expires_at: datetime
    action_digest: StrictStr = Field(..., min_length=64, max_length=64)
    provider_idempotency_key: StrictStr = Field(..., min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_approval(self) -> RoutineApprovalRequested:
        if self.expires_at <= self.created_at:
            raise ValueError("approval expiry must be after creation")
        _validate_sha256(self.action_digest, "action digest")
        return self


class RoutineApprovalDecision(RoutineEnvelope):
    kind: Literal[ROUTINE_APPROVAL_DECISION_KIND]
    producer: Literal["cloud"]
    service_identity: Literal["cloud-service"]
    command_id: UUID
    idempotency_key: UUID
    approval_request_id: UUID
    action_attempt_id: UUID
    run_id: UUID
    attempt_id: UUID
    generation: StrictInt = Field(..., ge=0)
    decision: Literal["approve", "reject"]
    decided_at: datetime


class RoutineApprovalReceipt(RoutineEnvelope):
    kind: Literal[ROUTINE_APPROVAL_RECEIPT_KIND]
    producer: Literal["foundry"]
    service_identity: Literal["foundry-service"]
    command_id: UUID
    idempotency_key: UUID
    result_code: StrictStr = Field(..., min_length=1, max_length=64)
    request_status: Literal[
        "authorizing", "rejected", "expired", "cancelled", "pending"
    ]
    run_status: Literal[
        "working", "approval_waiting", "failed", "cancelled", "expired"
    ]
    permission_consumed: StrictBool
    action_attempt_state: Literal[
        "pre_dispatch",
        "dispatching",
        "completed",
        "unknown",
        "manual_reconciliation",
    ]


class RoutineCancelWait(RoutineEnvelope):
    kind: Literal[ROUTINE_CANCEL_WAIT_KIND]
    producer: Literal["cloud"]
    service_identity: Literal["cloud-service"]
    command_id: UUID
    idempotency_key: UUID
    approval_request_id: UUID
    run_id: UUID
    attempt_id: UUID
    generation: StrictInt = Field(..., ge=0)
    reason: StrictStr = Field(..., min_length=1, max_length=64)
    replacing_occurrence_id: UUID

    @model_validator(mode="after")
    def validate_cancel(self) -> RoutineCancelWait:
        _validate_code(self.reason, "cancel reason")
        return self


RoutineCommand = RoutineDispatch | RoutineApprovalDecision | RoutineCancelWait
RoutineEvent = RoutineResult | RoutineApprovalRequested


def parse_routine_message(value: dict[str, Any]) -> RoutineContractModel:
    if not isinstance(value, dict):
        raise RuntimeValidationError("routine message must be an object")
    kind = value.get("kind")
    model = {
        ROUTINE_DISPATCH_KIND: RoutineDispatch,
        ROUTINE_APPROVAL_DECISION_KIND: RoutineApprovalDecision,
        ROUTINE_CANCEL_WAIT_KIND: RoutineCancelWait,
        ROUTINE_RESULT_KIND: RoutineResult,
        ROUTINE_APPROVAL_REQUESTED_KIND: RoutineApprovalRequested,
        ROUTINE_DISPATCH_RECEIPT_KIND: RoutineDispatchReceipt,
        ROUTINE_EVENT_RECEIPT_KIND: RoutineEventReceipt,
        ROUTINE_APPROVAL_RECEIPT_KIND: RoutineApprovalReceipt,
    }.get(kind)
    if model is None:
        raise RuntimeValidationError("unsupported routine message kind")
    try:
        return model.model_validate(value)
    except ValueError as exc:
        raise RuntimeValidationError("routine message is invalid") from exc


def routine_fingerprint(value: RoutineContractModel | dict[str, Any]) -> str:
    projection = (
        value.model_dump(mode="json")
        if isinstance(value, BaseModel)
        else dict(value)
    )
    for field in ("fingerprint", "issued_at", "deadline_at"):
        projection.pop(field, None)
    return canonical_fingerprint(projection)


def routine_message_bytes(value: RoutineContractModel | dict[str, Any]) -> bytes:
    encoded = canonical_json_bytes(
        value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    )
    if len(encoded) > MAX_ROUTINE_EVENT_BYTES:
        raise RuntimeValidationError("routine message envelope is too large")
    return encoded


def build_routine_event_envelope(execution: Any, attempt: Any, event: Any) -> RoutineEvent:
    """Build a released routine event from a durable internal event row."""

    routine = getattr(execution, "routine_execution", None)
    if routine is None:
        try:
            routine = execution.routine_execution
        except AttributeError as exc:
            raise RuntimeValidationError("routine event has no execution snapshot") from exc
    if event.event_type not in {ROUTINE_RESULT_KIND, ROUTINE_APPROVAL_REQUESTED_KIND}:
        raise RuntimeValidationError("routine event type is not published")
    issued_at = event.created_at
    if issued_at is None or issued_at.tzinfo is None:
        raise RuntimeValidationError("routine event timestamp is invalid")
    scope = {
        "kind": "workspace",
        "workspace_id": str(execution.cloud_workspace_id or routine.workspace_id),
        "owner_user_id": str(routine.owner_user_id),
        "ally_id": str(routine.ally_id),
        "cloud_binding_id": str(routine.cloud_binding_id),
    }
    value = {
        **event.payload,
        "schema_version": "v1",
        "kind": event.event_type,
        "producer": "foundry",
        "service_identity": "foundry-service",
        "event_id": str(event.event_id),
        "event_sequence": event.sequence,
        "scope": scope,
        "issued_at": issued_at.isoformat().replace("+00:00", "Z"),
        "deadline_at": (issued_at + timedelta(seconds=60)).isoformat().replace(
            "+00:00", "Z"
        ),
        "fingerprint": "",
    }
    value["fingerprint"] = routine_fingerprint(value)
    model = RoutineResult if event.event_type == ROUTINE_RESULT_KIND else RoutineApprovalRequested
    try:
        result = model.model_validate(value)
        routine_message_bytes(result)
        return result
    except ValueError as exc:
        raise RuntimeValidationError("routine event is invalid") from exc


def _fingerprint(value: RoutineEnvelope) -> str:
    projection = value.model_dump(mode="json")
    for field in ("fingerprint", "issued_at", "deadline_at"):
        projection.pop(field, None)
    return canonical_fingerprint(projection)


def _validate_times(issued_at: datetime, deadline_at: datetime) -> None:
    if issued_at.tzinfo is None or deadline_at.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    lifetime = (deadline_at - issued_at).total_seconds()
    if lifetime <= 0 or lifetime > 60:
        raise ValueError("transport deadline is outside the bounded window")


def _validate_text(value: str, limit: int, name: str) -> None:
    if len(value.encode("utf-8")) > limit:
        raise ValueError(f"{name} is too large")


def _validate_sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _validate_code(value: str, name: str) -> None:
    if not value or len(value) > 64 or not value[0].islower() or not all(
        character.islower() or character.isdigit() or character in "_-"
        for character in value
    ):
        raise ValueError(f"{name} is invalid")


__all__ = [
    "MAX_ROUTINE_EVENT_BYTES",
    "MAX_ROUTINE_SEQUENCE",
    "MAX_ROUTINE_TERMINAL_SEQUENCE",
    "MAX_ROUTINE_TEXT_BYTES",
    "RoutineApprovalDecision",
    "RoutineApprovalReceipt",
    "RoutineApprovalRequested",
    "RoutineCancelWait",
    "RoutineCommand",
    "RoutineContractModel",
    "RoutineDispatch",
    "RoutineDispatchReceipt",
    "RoutineEnvelope",
    "RoutineEvent",
    "RoutineEventReceipt",
    "RoutineReference",
    "RoutineResult",
    "RoutineScope",
    "build_routine_event_envelope",
    "parse_routine_message",
    "routine_fingerprint",
    "routine_message_bytes",
]
