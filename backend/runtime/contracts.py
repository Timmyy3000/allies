from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from runtime.exceptions import RuntimeValidationError

CONTRACT_VERSION = "v1"
COMMAND_KIND = "execution.command"
RECEIPT_KIND = "execution.receipt"
RECONCILIATION_KIND = "execution.reconciliation"
EVENT_KIND = "execution.event"
FINGERPRINT_PREFIX = "canonical-json-sha256:v1:"
FINGERPRINT_LENGTH = len(FINGERPRINT_PREFIX) + 64
MAX_COMMAND_TEXT_BYTES = 16 * 1024
MAX_EVENT_TEXT_BYTES = 16 * 1024
MAX_EVENT_ENVELOPE_BYTES = 64 * 1024
MAX_EVENT_DEDUPE_KEY_LENGTH = 255
MAX_CONTRACT_LIFETIME_SECONDS = 60

_FINGERPRINT_RE = f"^{FINGERPRINT_PREFIX}[0-9a-f]{{64}}$"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionScope(ContractModel):
    kind: Literal["workspace"]
    cloud_workspace_id: UUID


class CloudCorrelation(ContractModel):
    ally_id: UUID
    conversation_id: UUID
    message_id: UUID
    cloud_binding_id: UUID


class FirstTurnBootstrap(ContractModel):
    kind: Literal["assistant_message"]
    message_id: UUID
    text: StrictStr = Field(..., min_length=1, max_length=MAX_COMMAND_TEXT_BYTES)


class ExecutionInput(ContractModel):
    kind: Literal["execution_input"]
    text: StrictStr = Field(..., min_length=1, max_length=16_000)
    bootstrap: FirstTurnBootstrap | None = None


class FoundryCorrelation(ContractModel):
    execution_id: UUID
    attempt_id: UUID
    generation: StrictInt = Field(..., ge=0, le=2_147_483_647)
    attempt_sequence: StrictInt = Field(..., ge=1, le=513)


class ExecutionCommand(ContractModel):
    schema_version: Literal[CONTRACT_VERSION]
    kind: Literal[COMMAND_KIND]
    producer: Literal["cloud"]
    service_identity: Literal["cloud-service"]
    command_id: UUID
    idempotency_key: UUID
    scope: ExecutionScope
    conversation_turn_ordinal: StrictInt = Field(..., ge=1, le=2_147_483_647)
    cloud: CloudCorrelation
    source_kind: Literal["conversation_message"]
    payload: ExecutionInput
    issued_at: datetime
    deadline_at: datetime
    fingerprint: StrictStr = Field(
        ...,
        min_length=FINGERPRINT_LENGTH,
        max_length=FINGERPRINT_LENGTH,
        pattern=_FINGERPRINT_RE,
    )


class FoundryEventEnvelope(ContractModel):
    schema_version: Literal[CONTRACT_VERSION]
    kind: Literal[EVENT_KIND]
    producer: Literal["foundry"]
    service_identity: Literal["foundry-service"]
    event_id: UUID
    event_dedupe_key: StrictStr = Field(
        ..., min_length=1, max_length=MAX_EVENT_DEDUPE_KEY_LENGTH
    )
    scope: ExecutionScope
    cloud: CloudCorrelation
    conversation_turn_ordinal: StrictInt = Field(..., ge=1, le=2_147_483_647)
    foundry: FoundryCorrelation
    event_type: Literal[
        "execution.accepted",
        "execution.awaiting_action",
        "message.delta",
        "activity.started",
        "activity.completed",
        "execution.completed",
        "execution.stopped",
        "execution.failed",
    ]
    payload: dict[str, Any]
    issued_at: datetime
    fingerprint: StrictStr = Field(
        ...,
        min_length=FINGERPRINT_LENGTH,
        max_length=FINGERPRINT_LENGTH,
        pattern=_FINGERPRINT_RE,
    )


class ExecutionReceipt(ContractModel):
    schema_version: Literal[CONTRACT_VERSION]
    kind: Literal[RECEIPT_KIND]
    status: Literal["accepted", "duplicate"]
    command_id: UUID
    idempotency_key: UUID
    fingerprint: StrictStr = Field(
        ...,
        min_length=FINGERPRINT_LENGTH,
        max_length=FINGERPRINT_LENGTH,
        pattern=_FINGERPRINT_RE,
    )


class ReconciliationReceipt(ContractModel):
    schema_version: Literal[CONTRACT_VERSION]
    kind: Literal[RECONCILIATION_KIND]
    status: Literal["accepted", "not_found", "conflict"]
    idempotency_key: UUID
    fingerprint: StrictStr = Field(
        ...,
        min_length=FINGERPRINT_LENGTH,
        max_length=FINGERPRINT_LENGTH,
        pattern=_FINGERPRINT_RE,
    )
    command_id: UUID | None = None


class EventDeliveryReceipt(ContractModel):
    event_id: UUID
    status: Literal["applied", "duplicate"]


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Serialize contract data using the cross-repository v1 rules."""

    normalized = _normalize_json(value)
    try:
        return json.dumps(
            normalized,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError("contract contains invalid JSON") from exc


def canonical_fingerprint(value: Mapping[str, Any]) -> str:
    return FINGERPRINT_PREFIX + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def command_fingerprint(command: ExecutionCommand) -> str:
    value = command.model_dump(
        mode="json",
        exclude={"issued_at", "deadline_at", "fingerprint"},
        exclude_none=True,
    )
    return canonical_fingerprint(value)


def event_fingerprint(event: FoundryEventEnvelope) -> str:
    value = event.model_dump(mode="json", exclude={"issued_at", "fingerprint"})
    return canonical_fingerprint(value)


def validate_command(command: ExecutionCommand) -> ExecutionCommand:
    _validate_times(command.issued_at, command.deadline_at)
    if (
        "bootstrap" in command.payload.model_fields_set
        and command.payload.bootstrap is None
    ):
        raise RuntimeValidationError("bootstrap must be omitted or an object")
    expected = command_fingerprint(command)
    if command.fingerprint != expected:
        raise RuntimeValidationError("command fingerprint does not match its envelope")
    _validate_utf8_size(command.payload.text, MAX_COMMAND_TEXT_BYTES, "command text")
    bootstrap = command.payload.bootstrap
    if bootstrap is not None:
        if command.conversation_turn_ordinal < 2:
            raise RuntimeValidationError(
                "bootstrap is invalid before the second conversation turn"
            )
        _validate_utf8_size(
            bootstrap.text, MAX_COMMAND_TEXT_BYTES, "bootstrap text"
        )
    return command


def validate_fingerprint(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(_FINGERPRINT_RE, value):
        raise RuntimeValidationError("fingerprint is invalid")
    return value


def validate_event(event: FoundryEventEnvelope) -> FoundryEventEnvelope:
    expected = event_fingerprint(event)
    if event.fingerprint != expected:
        raise RuntimeValidationError("event fingerprint does not match its envelope")
    _validate_event_payload(event.event_type, event.payload)
    return event


def event_envelope_bytes(event: FoundryEventEnvelope) -> bytes:
    encoded = canonical_json_bytes(event.model_dump(mode="json"))
    if len(encoded) > MAX_EVENT_ENVELOPE_BYTES:
        raise RuntimeValidationError("event envelope is too large")
    return encoded


def build_event_envelope(execution, attempt, event) -> FoundryEventEnvelope | None:
    """Translate one internal FND-007 event into a safe wire envelope."""

    event_type = {
        "execution.dispatched": "execution.accepted",
    }.get(event.event_type, event.event_type)
    allowed = {
        "execution.accepted",
        "execution.awaiting_action",
        "message.delta",
        "activity.started",
        "activity.completed",
        "execution.completed",
        "execution.stopped",
        "execution.failed",
    }
    if event_type not in allowed:
        return None
    required = (
        execution.command_id,
        execution.cloud_workspace_id,
        execution.cloud_ally_id,
        execution.cloud_conversation_id,
        execution.cloud_message_id,
        execution.cloud_binding_id,
        execution.conversation_turn_ordinal,
        execution.command_fingerprint,
    )
    if any(value in (None, "") for value in required):
        return None
    terminal = event_type in {
        "execution.completed",
        "execution.stopped",
        "execution.failed",
    }
    if event.sequence > (513 if terminal else 512):
        raise RuntimeValidationError(
            "event exceeds the bounded Cloud projection budget"
        )
    payload = _wire_event_payload(event_type, event.payload)
    envelope = FoundryEventEnvelope(
        schema_version=CONTRACT_VERSION,
        kind=EVENT_KIND,
        producer="foundry",
        service_identity="foundry-service",
        event_id=event.event_id,
        event_dedupe_key=(
            f"{execution.id}:{attempt.id}:{attempt.machine_generation}:{event.event_id}"
        ),
        scope=ExecutionScope(
            kind="workspace", cloud_workspace_id=execution.cloud_workspace_id
        ),
        cloud=CloudCorrelation(
            ally_id=execution.cloud_ally_id,
            conversation_id=execution.cloud_conversation_id,
            message_id=execution.cloud_message_id,
            cloud_binding_id=execution.cloud_binding_id,
        ),
        conversation_turn_ordinal=execution.conversation_turn_ordinal,
        foundry=FoundryCorrelation(
            execution_id=execution.id,
            attempt_id=attempt.id,
            generation=attempt.machine_generation,
            attempt_sequence=event.sequence,
        ),
        event_type=event_type,
        payload=payload,
        issued_at=event.created_at,
        fingerprint=FINGERPRINT_PREFIX + "0" * 64,
    )
    envelope = envelope.model_copy(update={"fingerprint": event_fingerprint(envelope)})
    validate_event(envelope)
    return envelope


def _validate_times(issued_at: datetime, deadline_at: datetime) -> None:
    if issued_at.tzinfo is None or deadline_at.tzinfo is None:
        raise RuntimeValidationError("contract timestamps must include a timezone")
    lifetime = (deadline_at - issued_at).total_seconds()
    if lifetime <= 0 or lifetime > MAX_CONTRACT_LIFETIME_SECONDS:
        raise RuntimeValidationError("command deadline is outside the bounded window")


def _validate_utf8_size(value: str, limit: int, name: str) -> None:
    if len(value.encode("utf-8")) > limit:
        raise RuntimeValidationError(f"{name} is too large")


def _validate_event_payload(event_type: str, payload: Mapping[str, Any]) -> None:
    if type(payload) is not dict:
        raise RuntimeValidationError("event payload must be an object")
    if event_type == "execution.accepted":
        if payload != {"status": "accepted"}:
            raise RuntimeValidationError("accepted event payload is invalid")
    elif event_type == "execution.awaiting_action":
        action_kind = payload.get("action_kind")
        if set(payload) != {"action_kind"} or not _safe_code(action_kind):
            raise RuntimeValidationError("awaiting-action payload is invalid")
    elif event_type == "message.delta":
        if set(payload) != {"kind", "text"} or payload.get("kind") != "assistant_delta":
            raise RuntimeValidationError("message event payload is invalid")
        text = payload.get("text")
        if not isinstance(text, str) or not text:
            raise RuntimeValidationError("message event payload is invalid")
        _validate_utf8_size(text, MAX_EVENT_TEXT_BYTES, "event text")
    elif event_type == "activity.started":
        if payload != {"kind": "tool"}:
            raise RuntimeValidationError("activity start payload is invalid")
    elif event_type == "activity.completed":
        if payload != {"status": "completed"}:
            raise RuntimeValidationError("activity completion payload is invalid")
    elif event_type == "execution.completed":
        if payload != {"status": "completed"}:
            raise RuntimeValidationError("completion event payload is invalid")
    elif event_type == "execution.stopped":
        reason = payload.get("reason")
        if set(payload) != {"reason"} or not _safe_code(reason):
            raise RuntimeValidationError("stopped event payload is invalid")
    elif event_type == "execution.failed":
        if set(payload) != {"code", "retryable"} or not _safe_code(payload.get("code")):
            raise RuntimeValidationError("failure event payload is invalid")
        if type(payload.get("retryable")) is not bool:
            raise RuntimeValidationError("failure event payload is invalid")


def _wire_event_payload(event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if event_type == "execution.accepted":
        return {"status": "accepted"}
    if event_type == "message.delta":
        text = payload.get("text")
        if not isinstance(text, str) or not text:
            raise RuntimeValidationError("message event payload is invalid")
        return {"kind": "assistant_delta", "text": unicodedata.normalize("NFC", text)}
    if event_type == "activity.started":
        return {"kind": "tool"}
    if event_type == "activity.completed":
        return {"status": "completed"}
    if event_type == "execution.completed":
        return {"status": "completed"}
    if event_type == "execution.failed":
        code = payload.get("code")
        retryable = payload.get("retryable")
        if not _safe_code(code) or type(retryable) is not bool:
            raise RuntimeValidationError("failure event payload is invalid")
        return {"code": code, "retryable": retryable}
    if event_type == "execution.awaiting_action":
        action_kind = payload.get("action_kind")
        if not _safe_code(action_kind):
            raise RuntimeValidationError("awaiting-action payload is invalid")
        return {"action_kind": action_kind}
    if event_type == "execution.stopped":
        reason = payload.get("reason")
        if not _safe_code(reason):
            raise RuntimeValidationError("stopped event payload is invalid")
        return {"reason": reason}
    raise RuntimeValidationError("event type is not allowed for publication")


def _safe_code(value: Any) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value)
    )


def _normalize_json(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize_json(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise RuntimeValidationError("contract object keys must be strings")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise RuntimeValidationError("contract object keys are ambiguous")
            normalized[normalized_key] = _normalize_json(item)
        return normalized
    if value is None or type(value) in {bool, int, float}:
        return value
    raise RuntimeValidationError("contract contains an unsupported JSON value")


__all__ = [
    "COMMAND_KIND",
    "CONTRACT_VERSION",
    "EVENT_KIND",
    "CloudCorrelation",
    "EventDeliveryReceipt",
    "ExecutionCommand",
    "ExecutionInput",
    "ExecutionReceipt",
    "ExecutionScope",
    "FirstTurnBootstrap",
    "FoundryCorrelation",
    "FoundryEventEnvelope",
    "ReconciliationReceipt",
    "build_event_envelope",
    "canonical_fingerprint",
    "canonical_json_bytes",
    "command_fingerprint",
    "event_envelope_bytes",
    "event_fingerprint",
    "validate_command",
    "validate_event",
    "validate_fingerprint",
]
