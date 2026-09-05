"""Strict v1 Cloud/Foundry execution and event contracts."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

SCHEMA_VERSION = "v1"
FINGERPRINT_PREFIX = "canonical-json-sha256:v1:"
FINGERPRINT_PATTERN = r"^canonical-json-sha256:v1:[0-9a-f]{64}$"
MAX_COMMAND_TEXT_BYTES = 16 * 1024
MAX_EVENT_TEXT_BYTES = 16 * 1024
MAX_EVENT_PAYLOAD_BYTES = 64 * 1024
MAX_EVENT_DEDUPE_KEY_LENGTH = 255
MAX_RUNTIME_EVENT_SEQUENCE = 100_000
MAX_TERMINAL_SEQUENCE = 100_001
MAX_CONTRACT_LIFETIME_SECONDS = 60


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("contract object keys must be strings")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise ValueError("contract object keys are ambiguous")
            normalized[normalized_key] = _normalize(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ValueError("non-finite numbers are not allowed")
    return value


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Serialize a contract projection deterministically for transport/fingerprints."""

    normalized = _normalize(value)
    return json.dumps(
        normalized,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_fingerprint(value: BaseModel | Mapping[str, Any]) -> str:
    """Return the v1 digest for a command/event stable projection."""

    if isinstance(value, BaseModel):
        projection = value.model_dump(mode="json")
    else:
        projection = dict(value)
    projection.pop("fingerprint", None)
    projection.pop("issued_at", None)
    projection.pop("deadline_at", None)
    digest = hashlib.sha256(canonical_json_bytes(projection)).hexdigest()
    return f"{FINGERPRINT_PREFIX}{digest}"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkspaceScope(ContractModel):
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
    text: StrictStr = Field(min_length=1, max_length=MAX_COMMAND_TEXT_BYTES)

    @model_validator(mode="after")
    def bounded_utf8(self) -> FirstTurnBootstrap:
        if len(self.text.encode("utf-8")) > MAX_COMMAND_TEXT_BYTES:
            raise ValueError("bootstrap text is too large")
        return self


class ExecutionInput(ContractModel):
    kind: Literal["execution_input"]
    text: StrictStr = Field(min_length=1, max_length=MAX_COMMAND_TEXT_BYTES)
    bootstrap: FirstTurnBootstrap | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def bounded_utf8(self) -> ExecutionInput:
        if len(self.text.encode("utf-8")) > MAX_COMMAND_TEXT_BYTES:
            raise ValueError("execution text is too large")
        return self


class ExecutionCommand(ContractModel):
    schema_version: Literal["v1"]
    kind: Literal["execution.command"]
    producer: Literal["cloud"]
    service_identity: Literal["cloud-service"]
    command_id: UUID
    idempotency_key: UUID
    scope: WorkspaceScope
    conversation_turn_ordinal: StrictInt = Field(ge=1, le=2_147_483_647)
    cloud: CloudCorrelation
    source_kind: Literal["conversation_message"]
    payload: ExecutionInput
    issued_at: datetime
    deadline_at: datetime
    fingerprint: StrictStr = Field(pattern=FINGERPRINT_PATTERN)

    @model_validator(mode="after")
    def validate_identity_and_fingerprint(self) -> ExecutionCommand:
        if self.issued_at.tzinfo is None or self.deadline_at.tzinfo is None:
            raise ValueError("command timestamps must include a timezone")
        lifetime = (self.deadline_at - self.issued_at).total_seconds()
        if lifetime <= 0 or lifetime > MAX_CONTRACT_LIFETIME_SECONDS:
            raise ValueError("command deadline is outside the bounded window")
        if self.fingerprint != canonical_fingerprint(self):
            raise ValueError("command fingerprint is invalid")
        return self


_EVENT_KINDS = {
    "execution.accepted",
    "execution.awaiting_action",
    "message.delta",
    "activity.started",
    "activity.completed",
    "execution.completed",
    "execution.stopped",
    "execution.failed",
}


class FoundryIdentity(ContractModel):
    execution_id: UUID
    attempt_id: UUID
    generation: StrictInt = Field(ge=0, le=2_147_483_647)
    attempt_sequence: StrictInt = Field(ge=1, le=MAX_TERMINAL_SEQUENCE)


class FoundryEventEnvelope(ContractModel):
    schema_version: Literal["v1"]
    kind: Literal["execution.event"]
    producer: Literal["foundry"]
    service_identity: Literal["foundry-service"]
    event_id: UUID
    event_dedupe_key: StrictStr = Field(
        min_length=1,
        max_length=MAX_EVENT_DEDUPE_KEY_LENGTH,
        pattern=r"^[^\x00\r\n]+$",
    )
    scope: WorkspaceScope
    cloud: CloudCorrelation
    conversation_turn_ordinal: StrictInt = Field(ge=1, le=2_147_483_647)
    foundry: FoundryIdentity
    event_type: StrictStr = Field(min_length=1, max_length=64)
    payload: dict[str, Any]
    issued_at: datetime
    fingerprint: StrictStr = Field(pattern=FINGERPRINT_PATTERN)

    @model_validator(mode="after")
    def validate_event(self) -> FoundryEventEnvelope:
        if self.event_type not in _EVENT_KINDS:
            raise ValueError("event type is not supported")
        if (
            self.foundry.attempt_sequence > MAX_RUNTIME_EVENT_SEQUENCE
            and self.event_type
            not in {"execution.completed", "execution.failed", "execution.stopped"}
        ):
            raise ValueError("event sequence is reserved for terminal state")
        self._validate_payload()
        if (
            len(canonical_json_bytes(self.model_dump(mode="json")))
            > MAX_EVENT_PAYLOAD_BYTES
        ):
            raise ValueError("event envelope is too large")
        if self.fingerprint != canonical_fingerprint(self):
            raise ValueError("event fingerprint is invalid")
        return self

    def _validate_payload(self) -> None:
        payload = self.payload
        if not isinstance(payload, dict):
            raise TypeError("event payload must be an object")
        if self.event_type == "message.delta":
            if (
                set(payload) != {"kind", "text"}
                or payload.get("kind") != "assistant_delta"
            ):
                raise ValueError("assistant delta payload is invalid")
            text = payload.get("text")
            if not isinstance(text, str) or not text:
                raise ValueError("assistant delta text is invalid")
            if len(text.encode("utf-8")) > MAX_EVENT_TEXT_BYTES:
                raise ValueError("assistant delta text is too large")
        elif self.event_type == "execution.awaiting_action":
            action_kind = payload.get("action_kind")
            if set(payload) != {"action_kind"} or not _safe_code(action_kind):
                raise ValueError("awaiting action payload is invalid")
        elif self.event_type == "activity.started":
            if payload != {"kind": "tool"}:
                raise ValueError("activity start payload is invalid")
        elif self.event_type == "activity.completed":
            if payload != {"status": "completed"}:
                raise ValueError("activity completion payload is invalid")
        elif self.event_type == "execution.accepted":
            if payload != {"status": "accepted"}:
                raise ValueError("accepted payload is invalid")
        elif self.event_type == "execution.completed":
            if payload != {"status": "completed"}:
                raise ValueError("completed payload is invalid")
        elif self.event_type == "execution.stopped":
            if set(payload) != {"reason"} or not _safe_code(payload.get("reason")):
                raise ValueError("stopped payload is invalid")
        elif self.event_type == "execution.failed":
            if (
                set(payload) != {"code", "retryable"}
                or not _safe_code(payload.get("code"))
                or type(payload.get("retryable")) is not bool
            ):
                raise ValueError("failed payload is invalid")
        if len(canonical_json_bytes(payload)) > MAX_EVENT_PAYLOAD_BYTES:
            raise ValueError("event payload is too large")


def _safe_code(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 64
        and value[0].islower()
        and all(char.islower() or char.isdigit() or char in "_-" for char in value)
    )


class ExecutionReceipt(ContractModel):
    schema_version: Literal["v1"]
    kind: Literal["execution.receipt"]
    status: Literal["accepted", "duplicate"]
    command_id: UUID
    idempotency_key: UUID
    fingerprint: StrictStr = Field(pattern=FINGERPRINT_PATTERN)


class ReconciliationReceipt(ContractModel):
    schema_version: Literal["v1"]
    kind: Literal["execution.reconciliation"]
    status: Literal["accepted", "not_found", "conflict"]
    idempotency_key: UUID
    fingerprint: StrictStr = Field(pattern=FINGERPRINT_PATTERN)
    command_id: UUID | None = None


__all__ = [
    "CloudCorrelation",
    "ExecutionCommand",
    "ExecutionInput",
    "ExecutionReceipt",
    "FirstTurnBootstrap",
    "FoundryEventEnvelope",
    "FoundryIdentity",
    "ReconciliationReceipt",
    "canonical_fingerprint",
    "canonical_json_bytes",
]
