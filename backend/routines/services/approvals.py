"""Cloud-owned projection and recovery seams for routine approvals.

Foundry remains authoritative for the 24-hour consent deadline and for the
effective approval/cancellation CAS. This module validates and stores the
routine contract, records the owner's one-shot choice, and exposes bounded
command leases for a transport adapter to call outside transactions.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator

from allies.exceptions import (
    FoundryGatewayConflict,
    FoundryGatewayInvalid,
    FoundryGatewayNotFound,
    FoundryGatewayRejected,
    FoundryGatewayRetryable,
    FoundryGatewayUnknownOutcome,
)
from allies.gateways.contracts import (
    MAX_CONTRACT_LIFETIME_SECONDS,
    MAX_EVENT_PAYLOAD_BYTES,
    ContractModel,
    RoutineScope,
    canonical_fingerprint,
    canonical_json_bytes,
)
from allies.gateways.contracts import (
    RoutineApprovalReceipt as FoundryRoutineApprovalReceipt,
)
from allies.gateways.foundry import cancel_routine_wait, decide_routine_approval
from common.uuids import canonical_uuid
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability

from ..models import (
    ROUTINE_ACTIVE_RUN_OUTCOMES,
    ROUTINE_APPROVAL_EXPIRY_SECONDS,
    ROUTINE_APPROVAL_MAX_ATTEMPTS,
    Routine,
    RoutineApprovalCommand,
    RoutineApprovalCommandKind,
    RoutineApprovalDeliveryState,
    RoutineApprovalProjection,
    RoutineApprovalStatus,
    RoutineDispatchOutbox,
    RoutineDispatchState,
    RoutineOccurrence,
    RoutineRunOutcome,
    RoutineRunSnapshot,
)

ROUTINE_APPROVAL_LEASE_SECONDS = 60
ROUTINE_APPROVAL_MAX_BACKOFF_SECONDS = 300
ROUTINE_APPROVAL_CANCEL_REASON = "expiry"
ROUTINE_APPROVAL_MAX_SEQUENCE = 100_000
_FINGERPRINT_PATTERN = r"^canonical-json-sha256:v1:[0-9a-f]{64}$"
_SAFE_CODE_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"


class RoutineApprovalInvalid(ValueError):
    """A routine approval message or local request is invalid."""


class RoutineApprovalConflict(ValueError):
    """A valid approval identity or decision conflicts with Cloud state."""


class RoutineApprovalUnavailable(ValueError):
    """The approval cannot be safely correlated or delivered."""


class RoutineApprovalUnauthorized(ValueError):
    """The authenticated owner cannot decide this approval."""


class RoutineApprovalRequestedEvent(ContractModel):
    """The exact revision-9 Foundry routine.approval_requested event."""

    schema_version: Literal["v1"]
    kind: Literal["routine.approval_requested"]
    producer: Literal["foundry"]
    service_identity: Literal["foundry-service"]
    event_id: UUID
    event_sequence: StrictInt = Field(ge=1, le=ROUTINE_APPROVAL_MAX_SEQUENCE)
    approval_request_id: UUID
    action_attempt_id: UUID
    run_id: UUID
    execution_id: UUID
    attempt_id: UUID
    generation: StrictInt = Field(ge=0)
    status: Literal["pending"]
    created_at: datetime
    expires_at: datetime
    action_digest: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    provider_idempotency_key: StrictStr = Field(min_length=1, max_length=255)
    scope: RoutineScope
    issued_at: datetime
    deadline_at: datetime
    fingerprint: StrictStr = Field(pattern=_FINGERPRINT_PATTERN)

    @model_validator(mode="after")
    def validate_event(self) -> RoutineApprovalRequestedEvent:
        timestamps = (
            self.created_at,
            self.expires_at,
            self.issued_at,
            self.deadline_at,
        )
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError("routine approval timestamps must include a timezone")
        if self.expires_at - self.created_at != timedelta(
            seconds=ROUTINE_APPROVAL_EXPIRY_SECONDS
        ):
            raise ValueError("routine approval expiry must be exactly 24 hours")
        lifetime = (self.deadline_at - self.issued_at).total_seconds()
        if lifetime <= 0 or lifetime > MAX_CONTRACT_LIFETIME_SECONDS:
            raise ValueError("routine approval event deadline is outside the bound")
        if self.fingerprint != canonical_fingerprint(self):
            raise ValueError("routine approval event fingerprint is invalid")
        return self


class RoutineApprovalDecisionCommand(ContractModel):
    """The exact revision-9 Cloud routine.approval_decision command."""

    schema_version: Literal["v1"]
    kind: Literal["routine.approval_decision"]
    producer: Literal["cloud"]
    service_identity: Literal["cloud-service"]
    command_id: UUID
    idempotency_key: UUID
    approval_request_id: UUID
    action_attempt_id: UUID
    run_id: UUID
    attempt_id: UUID
    generation: StrictInt = Field(ge=0)
    decision: Literal["approve", "reject"]
    decided_at: datetime
    scope: RoutineScope
    issued_at: datetime
    deadline_at: datetime
    fingerprint: StrictStr = Field(pattern=_FINGERPRINT_PATTERN)

    @model_validator(mode="after")
    def validate_command(self) -> RoutineApprovalDecisionCommand:
        timestamps = (self.decided_at, self.issued_at, self.deadline_at)
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError(
                "routine approval command timestamps must include a timezone"
            )
        lifetime = (self.deadline_at - self.issued_at).total_seconds()
        if lifetime <= 0 or lifetime > MAX_CONTRACT_LIFETIME_SECONDS:
            raise ValueError("routine approval command deadline is outside the bound")
        if self.fingerprint != canonical_fingerprint(self):
            raise ValueError("routine approval command fingerprint is invalid")
        return self


class RoutineCancelWaitCommand(ContractModel):
    """The exact revision-9 Cloud routine.cancel_wait command."""

    schema_version: Literal["v1"]
    kind: Literal["routine.cancel_wait"]
    producer: Literal["cloud"]
    service_identity: Literal["cloud-service"]
    command_id: UUID
    idempotency_key: UUID
    approval_request_id: UUID
    run_id: UUID
    attempt_id: UUID
    generation: StrictInt = Field(ge=0)
    reason: StrictStr = Field(min_length=1, max_length=64, pattern=_SAFE_CODE_PATTERN)
    replacing_occurrence_id: UUID
    scope: RoutineScope
    issued_at: datetime
    deadline_at: datetime
    fingerprint: StrictStr = Field(pattern=_FINGERPRINT_PATTERN)

    @model_validator(mode="after")
    def validate_command(self) -> RoutineCancelWaitCommand:
        if self.issued_at.tzinfo is None or self.deadline_at.tzinfo is None:
            raise ValueError("routine cancel timestamps must include a timezone")
        lifetime = (self.deadline_at - self.issued_at).total_seconds()
        if lifetime <= 0 or lifetime > MAX_CONTRACT_LIFETIME_SECONDS:
            raise ValueError("routine cancel deadline is outside the bound")
        if self.fingerprint != canonical_fingerprint(self):
            raise ValueError("routine cancel command fingerprint is invalid")
        return self


class RoutineCancelWaitReceipt(ContractModel):
    """The bounded JSON response returned by Foundry's cancel-wait route."""

    code: StrictStr = Field(min_length=1, max_length=64)
    routine_execution_id: UUID
    fence: StrictInt = Field(ge=0)
    status: Literal["pending", "authorizing", "rejected", "expired", "cancelled"]
    replayed: StrictBool


RoutineApprovalReceipt = FoundryRoutineApprovalReceipt
RoutineApprovalRequested = RoutineApprovalRequestedEvent
RoutineApprovalDecision = RoutineApprovalDecisionCommand
RoutineCancelWait = RoutineCancelWaitCommand


@dataclass(frozen=True, slots=True)
class RoutineApprovalProjectionResult:
    status: str
    event_id: UUID
    approval: RoutineApprovalProjection

    @property
    def projection(self) -> RoutineApprovalProjection:
        return self.approval


@dataclass(frozen=True, slots=True)
class RoutineApprovalDecisionResult:
    approval: RoutineApprovalProjection
    command: RoutineApprovalCommand
    replayed: bool = False

    @property
    def payload(self) -> bytes:
        return bytes(self.command.command_bytes)

    @property
    def status(self) -> str:
        return self.approval.status

    @property
    def wire_command(self) -> RoutineApprovalDecisionCommand:
        return RoutineApprovalDecisionCommand.model_validate_json(self.payload)


@dataclass(frozen=True, slots=True)
class RoutineApprovalReplacementResult:
    approval: RoutineApprovalProjection
    command: RoutineApprovalCommand
    replayed: bool = False

    @property
    def status(self) -> str:
        return "replacement_pending"

    @property
    def payload(self) -> bytes:
        return bytes(self.command.command_bytes)


@dataclass(frozen=True, slots=True)
class RoutineApprovalCommandLease:
    command_id: UUID
    approval_id: UUID
    kind: str
    attempt_count: int
    lease_expires_at: datetime
    command_bytes: bytes


@dataclass(frozen=True, slots=True)
class RoutineApprovalDispatchReport:
    claimed: int = 0
    deferred: int = 0
    accepted: int = 0
    failed: int = 0
    reconciliation: int = 0
    disabled: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "claimed": self.claimed,
            "deferred": self.deferred,
            "accepted": self.accepted,
            "failed": self.failed,
            "reconciliation": self.reconciliation,
            "disabled": self.disabled,
        }


def _aware(value: datetime | None) -> datetime:
    current = value or timezone.now()
    if current.tzinfo is None:
        raise ValueError("routine approval timestamps must be timezone-aware")
    return current.astimezone(UTC)


def _parse_uuid(value: UUID | str, *, message: str) -> UUID:
    try:
        return canonical_uuid(value)
    except (TypeError, ValueError) as exc:
        raise RoutineApprovalInvalid(message) from exc


def _scope_for(approval: RoutineApprovalProjection) -> RoutineScope:
    return RoutineScope(
        kind="workspace",
        workspace_id=approval.workspace_id,
        owner_user_id=approval.owner_id,
        ally_id=approval.ally_id,
        cloud_binding_id=approval.binding_id,
    )


def _parse_payload(model, payload: object, *, label: str):
    if not isinstance(payload, Mapping):
        raise RoutineApprovalInvalid(f"{label} must be an object")
    try:
        parsed = model.model_validate(payload)
        if (
            len(canonical_json_bytes(parsed.model_dump(mode="json")))
            > MAX_EVENT_PAYLOAD_BYTES
        ):
            raise RoutineApprovalInvalid(f"{label} is too large")
        return parsed
    except RoutineApprovalInvalid:
        raise
    except (TypeError, ValueError) as exc:
        raise RoutineApprovalInvalid(f"{label} is invalid") from exc


def parse_routine_approval_requested(
    payload: object,
) -> RoutineApprovalRequestedEvent:
    return _parse_payload(
        RoutineApprovalRequestedEvent,
        payload,
        label="routine approval requested event",
    )


def _scope_matches(event: RoutineApprovalRequestedEvent, routine: Routine) -> bool:
    return event.scope == RoutineScope(
        kind="workspace",
        workspace_id=routine.workspace_id,
        owner_user_id=routine.owner_id,
        ally_id=routine.ally_id,
        cloud_binding_id=routine.binding_id,
    )


def _same_projection(
    projection: RoutineApprovalProjection,
    event: RoutineApprovalRequestedEvent,
) -> bool:
    return (
        projection.event_id == event.event_id
        and projection.event_sequence == event.event_sequence
        and projection.approval_request_id == event.approval_request_id
        and projection.action_attempt_id == event.action_attempt_id
        and projection.run_id == event.run_id
        and projection.execution_id == event.execution_id
        and projection.attempt_id == event.attempt_id
        and projection.generation == event.generation
        and projection.event_fingerprint == event.fingerprint
        and projection.action_digest == event.action_digest
        and projection.provider_idempotency_key == event.provider_idempotency_key
        and projection.created_at == event.created_at
        and projection.expires_at == event.expires_at
    )


def _command_bytes(command: ContractModel) -> tuple[bytes, str]:
    body = canonical_json_bytes(command.model_dump(mode="json"))
    if len(body) > MAX_EVENT_PAYLOAD_BYTES:
        raise RoutineApprovalInvalid("routine command is too large")
    return body, hashlib.sha256(body).hexdigest()


def _routine_identity_for_event(event: RoutineApprovalRequestedEvent):
    try:
        hint = RoutineRunSnapshot.objects.get(pk=event.run_id)
        routine = Routine.objects.select_for_update().get(pk=hint.routine_id)
        occurrence = RoutineOccurrence.objects.select_for_update().get(
            pk=hint.occurrence_id,
            routine=routine,
        )
        run = RoutineRunSnapshot.objects.select_for_update().get(
            pk=event.run_id,
            occurrence=occurrence,
            routine=routine,
        )
        outbox = RoutineDispatchOutbox.objects.select_for_update().get(run=run)
    except (
        Routine.DoesNotExist,
        RoutineOccurrence.DoesNotExist,
        RoutineRunSnapshot.DoesNotExist,
    ) as exc:
        raise RoutineApprovalUnavailable(
            "routine approval correlation is unavailable"
        ) from exc
    except RoutineDispatchOutbox.DoesNotExist as exc:
        raise RoutineApprovalUnavailable(
            "routine dispatch correlation is unavailable"
        ) from exc
    return routine, occurrence, run, outbox


def _validate_event_correlation(
    event: RoutineApprovalRequestedEvent,
    routine: Routine,
    occurrence: RoutineOccurrence,
    run: RoutineRunSnapshot,
    outbox: RoutineDispatchOutbox,
) -> None:
    if not _scope_matches(event, routine):
        raise RoutineApprovalInvalid("routine approval scope does not match routine")
    if occurrence.id != run.occurrence_id or run.routine_id != routine.id:
        raise RoutineApprovalUnavailable("routine approval ancestry is unavailable")
    if (
        outbox.status != RoutineDispatchState.ACCEPTED
        or outbox.execution_id is None
        or outbox.attempt_id is None
        or outbox.generation is None
    ):
        raise RoutineApprovalUnavailable("routine dispatch was not accepted")
    if (
        event.execution_id != outbox.execution_id
        or event.attempt_id != outbox.attempt_id
        or event.generation != outbox.generation
    ):
        raise RoutineApprovalConflict("routine approval execution identity conflicts")


@transaction.atomic
def apply_routine_approval_requested_event(
    payload: object,
) -> RoutineApprovalProjectionResult:
    """Apply one validated Foundry event without granting Cloud authority."""

    event = parse_routine_approval_requested(payload)
    routine, occurrence, run, outbox = _routine_identity_for_event(event)
    _validate_event_correlation(event, routine, occurrence, run, outbox)

    existing = (
        RoutineApprovalProjection.objects.select_for_update()
        .filter(event_id=event.event_id)
        .first()
    )
    if existing is not None:
        if not _same_projection(existing, event):
            raise RoutineApprovalConflict("routine approval event replay conflicts")
        return RoutineApprovalProjectionResult(
            status="duplicate",
            event_id=event.event_id,
            approval=existing,
        )

    if RoutineApprovalProjection.objects.filter(
        approval_request_id=event.approval_request_id
    ).exists():
        raise RoutineApprovalConflict("routine approval request identity conflicts")
    if RoutineApprovalProjection.objects.filter(
        action_attempt_id=event.action_attempt_id
    ).exists():
        raise RoutineApprovalConflict("routine approval action identity conflicts")
    if RoutineApprovalProjection.objects.filter(
        attempt_id=event.attempt_id,
        event_sequence=event.event_sequence,
    ).exists():
        raise RoutineApprovalConflict("routine approval event sequence conflicts")
    if run.outcome not in ROUTINE_ACTIVE_RUN_OUTCOMES:
        raise RoutineApprovalConflict("routine run is no longer accepting approvals")

    approval = RoutineApprovalProjection.objects.create(
        routine=routine,
        occurrence=occurrence,
        run=run,
        workspace_id=routine.workspace_id,
        owner_id=routine.owner_id,
        ally_id=routine.ally_id,
        binding_id=routine.binding_id,
        approval_request_id=event.approval_request_id,
        action_attempt_id=event.action_attempt_id,
        execution_id=event.execution_id,
        attempt_id=event.attempt_id,
        generation=event.generation,
        event_id=event.event_id,
        event_sequence=event.event_sequence,
        event_fingerprint=event.fingerprint,
        action_digest=event.action_digest,
        provider_idempotency_key=event.provider_idempotency_key,
        created_at=event.created_at,
        expires_at=event.expires_at,
        status=RoutineApprovalStatus.PENDING,
    )
    if run.outcome != RoutineRunOutcome.APPROVAL_WAITING:
        run.outcome = RoutineRunOutcome.APPROVAL_WAITING
        run.save(update_fields=("outcome", "updated_at"))
    return RoutineApprovalProjectionResult(
        status="applied",
        event_id=event.event_id,
        approval=approval,
    )


def _lock_approval_context(
    approval_id: UUID,
) -> tuple[Routine, RoutineOccurrence, RoutineRunSnapshot, RoutineApprovalProjection]:
    try:
        identity = RoutineApprovalProjection.objects.only(
            "routine_id", "occurrence_id", "run_id"
        ).get(pk=approval_id)
        routine = Routine.objects.select_for_update().get(pk=identity.routine_id)
        occurrence = RoutineOccurrence.objects.select_for_update().get(
            pk=identity.occurrence_id,
            routine=routine,
        )
        run = RoutineRunSnapshot.objects.select_for_update().get(
            pk=identity.run_id,
            occurrence=occurrence,
            routine=routine,
        )
        approval = RoutineApprovalProjection.objects.select_for_update().get(
            pk=approval_id,
            routine=routine,
            occurrence=occurrence,
            run=run,
        )
    except (
        RoutineApprovalProjection.DoesNotExist,
        Routine.DoesNotExist,
        RoutineOccurrence.DoesNotExist,
        RoutineRunSnapshot.DoesNotExist,
    ) as exc:
        raise RoutineApprovalUnavailable("approval is unavailable") from exc
    return routine, occurrence, run, approval


def _approval_for_owner(
    *, user, workspace_id, routine_id=None, approval_id=None, approval_request_id=None
) -> tuple[RoutineApprovalProjection, RoutineRunSnapshot]:
    try:
        context = require_workspace_capability(
            user=user,
            workspace_id=workspace_id,
            capability=Capability.PROFILE_WRITE,
        )
    except Exception as exc:
        raise RoutineApprovalUnauthorized("approval decision is unauthorized") from exc
    filters = {"workspace_id": context.workspace.id, "owner_id": user.id}
    if routine_id is not None:
        filters["routine_id"] = _parse_uuid(
            routine_id,
            message="routine identity is invalid",
        )
    if approval_id is not None:
        filters["pk"] = _parse_uuid(approval_id, message="approval identity is invalid")
    elif approval_request_id is not None:
        filters["approval_request_id"] = _parse_uuid(
            approval_request_id,
            message="approval request identity is invalid",
        )
    else:
        raise RoutineApprovalInvalid("approval identity is required")
    candidate = RoutineApprovalProjection.objects.filter(**filters).only("pk").first()
    if candidate is None:
        raise RoutineApprovalUnavailable("approval is unavailable")
    _routine, _occurrence, run, approval = _lock_approval_context(candidate.pk)
    return approval, run


def _decision_command_for(
    approval: RoutineApprovalProjection,
) -> RoutineApprovalDecisionCommand:
    if (
        approval.decision_command_id is None
        or approval.decision_idempotency_key is None
        or approval.decision not in {"approve", "reject"}
        or approval.decided_at is None
    ):
        raise RoutineApprovalUnavailable("approval decision command is unavailable")
    decided_at = approval.decided_at.astimezone(UTC)
    values = {
        "schema_version": "v1",
        "kind": "routine.approval_decision",
        "producer": "cloud",
        "service_identity": "cloud-service",
        "command_id": str(approval.decision_command_id),
        "idempotency_key": str(approval.decision_idempotency_key),
        "approval_request_id": str(approval.approval_request_id),
        "action_attempt_id": str(approval.action_attempt_id),
        "run_id": str(approval.run_id),
        "attempt_id": str(approval.attempt_id),
        "generation": approval.generation,
        "decision": approval.decision,
        "decided_at": decided_at.isoformat().replace("+00:00", "Z"),
        "scope": _scope_for(approval).model_dump(mode="json"),
        "issued_at": decided_at.isoformat().replace("+00:00", "Z"),
        "deadline_at": (decided_at + timedelta(seconds=ROUTINE_APPROVAL_LEASE_SECONDS))
        .isoformat()
        .replace("+00:00", "Z"),
        "fingerprint": "",
    }
    values["fingerprint"] = canonical_fingerprint(values)
    command = RoutineApprovalDecisionCommand.model_validate(values)
    if (
        approval.decision_fingerprint
        and approval.decision_fingerprint != command.fingerprint
    ):
        raise RoutineApprovalConflict("stored approval decision fingerprint conflicts")
    return command


def build_routine_approval_decision_command(
    *, approval_id: UUID | str
) -> RoutineApprovalDecisionCommand:
    approval_key = _parse_uuid(approval_id, message="approval identity is invalid")
    approval = RoutineApprovalProjection.objects.get(pk=approval_key)
    delivery = RoutineApprovalCommand.objects.filter(
        approval=approval,
        kind=RoutineApprovalCommandKind.DECISION,
    ).first()
    if delivery is not None:
        try:
            command = RoutineApprovalDecisionCommand.model_validate_json(
                delivery.command_bytes
            )
        except ValueError as exc:
            raise RoutineApprovalConflict(
                "stored approval decision command is invalid"
            ) from exc
        if (
            command.command_id != delivery.command_id
            or command.idempotency_key != delivery.idempotency_key
            or command.fingerprint != delivery.command_fingerprint
        ):
            raise RoutineApprovalConflict("stored approval decision command conflicts")
        return command
    return _decision_command_for(approval)


def build_routine_approval_decision_payload(*, approval_id: UUID | str) -> bytes:
    command = build_routine_approval_decision_command(approval_id=approval_id)
    body, _digest = _command_bytes(command)
    return body


def _create_command(
    *,
    approval: RoutineApprovalProjection,
    command: ContractModel,
    kind: RoutineApprovalCommandKind,
    idempotency_key: UUID,
    replacing_occurrence_id: UUID | None = None,
    reason: str = "",
    next_attempt_at: datetime | None = None,
) -> RoutineApprovalCommand:
    body, digest = _command_bytes(command)
    return RoutineApprovalCommand.objects.create(
        approval=approval,
        kind=kind,
        command_id=command.command_id,
        idempotency_key=idempotency_key,
        command_bytes=body,
        command_byte_length=len(body),
        command_sha256=digest,
        command_fingerprint=command.fingerprint,
        replacing_occurrence_id=replacing_occurrence_id,
        reason=reason,
        status=RoutineApprovalDeliveryState.PENDING,
        next_attempt_at=next_attempt_at or approval.decided_at or timezone.now(),
    )


def record_routine_approval_decision(
    *,
    user,
    workspace_id: UUID | str,
    decision: str,
    idempotency_key: UUID | str,
    routine_id: UUID | str | None = None,
    approval_id: UUID | str | None = None,
    approval_request_id: UUID | str | None = None,
    now: datetime | None = None,
) -> RoutineApprovalDecisionResult:
    """Record one owner choice; Foundry still decides whether it takes effect."""

    if decision not in {"approve", "reject"}:
        raise RoutineApprovalInvalid("approval decision is invalid")
    key = _parse_uuid(idempotency_key, message="approval idempotency key is invalid")
    boundary = _aware(now)
    with transaction.atomic():
        approval, run = _approval_for_owner(
            user=user,
            workspace_id=workspace_id,
            routine_id=routine_id,
            approval_id=approval_id,
            approval_request_id=approval_request_id,
        )
        if approval.decision_idempotency_key is not None:
            if (
                approval.decision_idempotency_key == key
                and approval.decision == decision
            ):
                command = RoutineApprovalCommand.objects.select_for_update().get(
                    approval=approval,
                    kind=RoutineApprovalCommandKind.DECISION,
                )
                return RoutineApprovalDecisionResult(
                    approval=approval,
                    command=command,
                    replayed=True,
                )
            raise RoutineApprovalConflict(
                "approval decision conflicts with existing choice"
            )
        if approval.status != RoutineApprovalStatus.PENDING:
            raise RoutineApprovalConflict("approval is no longer pending")
        if boundary >= approval.expires_at:
            _expire_locked(approval=approval, run=run, now=boundary)
            raise RoutineApprovalConflict("approval consent is unavailable")
        if RoutineApprovalCommand.objects.filter(idempotency_key=key).exists():
            raise RoutineApprovalConflict("approval idempotency key conflicts")

        approval.decision = decision
        approval.decided_at = boundary
        approval.deciding_user_id = user.id
        approval.decision_command_id = uuid4()
        approval.decision_idempotency_key = key
        approval.status = RoutineApprovalStatus.DECISION_RECORDED
        command = _decision_command_for(approval)
        approval.decision_fingerprint = command.fingerprint
        approval.save(
            update_fields=(
                "decision",
                "decided_at",
                "deciding_user",
                "decision_command_id",
                "decision_idempotency_key",
                "decision_fingerprint",
                "status",
                "updated_at",
            )
        )
        delivery = _create_command(
            approval=approval,
            command=command,
            kind=RoutineApprovalCommandKind.DECISION,
            idempotency_key=key,
            next_attempt_at=boundary,
        )
        return RoutineApprovalDecisionResult(
            approval=approval,
            command=delivery,
        )


def _cancel_command_for(
    approval: RoutineApprovalProjection,
    delivery: RoutineApprovalCommand,
) -> RoutineCancelWaitCommand:
    if (
        delivery.kind != RoutineApprovalCommandKind.CANCEL_WAIT
        or delivery.replacing_occurrence_id is None
        or not delivery.reason
    ):
        raise RoutineApprovalUnavailable("cancel-wait command is unavailable")
    try:
        command = RoutineCancelWaitCommand.model_validate_json(delivery.command_bytes)
    except ValueError as exc:
        raise RoutineApprovalConflict("stored cancel-wait command is invalid") from exc
    if (
        command.command_id != delivery.command_id
        or command.idempotency_key != delivery.idempotency_key
        or command.approval_request_id != approval.approval_request_id
        or command.run_id != approval.run_id
        or command.attempt_id != approval.attempt_id
        or command.generation != approval.generation
        or command.reason != delivery.reason
        or command.replacing_occurrence_id != delivery.replacing_occurrence_id
        or command.scope != _scope_for(approval)
        or command.fingerprint != delivery.command_fingerprint
    ):
        raise RoutineApprovalConflict("stored cancel-wait command conflicts")
    return command


def build_routine_cancel_wait_command(
    *, command_id: UUID | str
) -> RoutineCancelWaitCommand:
    key = _parse_uuid(command_id, message="routine command identity is invalid")
    delivery = RoutineApprovalCommand.objects.select_related("approval").get(
        command_id=key,
        kind=RoutineApprovalCommandKind.CANCEL_WAIT,
    )
    return _cancel_command_for(delivery.approval, delivery)


def _replacement_occurrence(
    approval: RoutineApprovalProjection,
    replacing_occurrence_id: UUID | str,
) -> RoutineOccurrence:
    parsed = _parse_uuid(
        replacing_occurrence_id,
        message="replacement occurrence identity is invalid",
    )
    occurrence = RoutineOccurrence.objects.filter(
        pk=parsed,
        routine_id=approval.routine_id,
        workspace_id=approval.workspace_id,
        owner_id=approval.owner_id,
        ally_id=approval.ally_id,
        binding_id=approval.binding_id,
    ).first()
    if occurrence is None:
        raise RoutineApprovalUnavailable("replacement occurrence is unavailable")
    return occurrence


def _create_cancel_intent_locked(
    *,
    approval: RoutineApprovalProjection,
    replacing_occurrence_id: UUID | str,
    reason: str,
    now: datetime,
) -> tuple[RoutineApprovalCommand, bool]:
    if not isinstance(reason, str) or re.fullmatch(_SAFE_CODE_PATTERN, reason) is None:
        raise RoutineApprovalInvalid("cancel reason is invalid")
    occurrence = _replacement_occurrence(approval, replacing_occurrence_id)
    existing = (
        RoutineApprovalCommand.objects.select_for_update()
        .filter(approval=approval, kind=RoutineApprovalCommandKind.CANCEL_WAIT)
        .first()
    )
    if existing is not None:
        if (
            existing.replacing_occurrence_id != occurrence.id
            or existing.reason != reason
        ):
            raise RoutineApprovalConflict(
                "cancel-wait intent conflicts with existing intent"
            )
        return existing, True
    values = {
        "schema_version": "v1",
        "kind": "routine.cancel_wait",
        "producer": "cloud",
        "service_identity": "cloud-service",
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "approval_request_id": str(approval.approval_request_id),
        "run_id": str(approval.run_id),
        "attempt_id": str(approval.attempt_id),
        "generation": approval.generation,
        "reason": reason,
        "replacing_occurrence_id": str(occurrence.id),
        "scope": _scope_for(approval).model_dump(mode="json"),
        "issued_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "deadline_at": (
            now.astimezone(UTC) + timedelta(seconds=ROUTINE_APPROVAL_LEASE_SECONDS)
        )
        .isoformat()
        .replace("+00:00", "Z"),
        "fingerprint": "",
    }
    values["fingerprint"] = canonical_fingerprint(values)
    command = RoutineCancelWaitCommand.model_validate(values)
    delivery = _create_command(
        approval=approval,
        command=command,
        kind=RoutineApprovalCommandKind.CANCEL_WAIT,
        idempotency_key=command.idempotency_key,
        replacing_occurrence_id=occurrence.id,
        reason=reason,
        next_attempt_at=now,
    )
    return delivery, False


def request_routine_approval_replacement(
    *,
    approval_id: UUID | str,
    replacing_occurrence_id: UUID | str,
    reason: str = "replacement",
    now: datetime | None = None,
) -> RoutineApprovalReplacementResult:
    """Persist a replacement cancel-wait intent; do not claim cancellation."""

    approval_key = _parse_uuid(approval_id, message="approval identity is invalid")
    boundary = _aware(now)
    with transaction.atomic():
        _routine, _occurrence, _run, approval = _lock_approval_context(approval_key)
        if approval.status in {
            RoutineApprovalStatus.REJECTED,
            RoutineApprovalStatus.EXPIRED,
            RoutineApprovalStatus.CANCELLED,
        }:
            raise RoutineApprovalConflict("approval is already terminal")
        delivery, replayed = _create_cancel_intent_locked(
            approval=approval,
            replacing_occurrence_id=replacing_occurrence_id,
            reason=reason,
            now=boundary,
        )
        return RoutineApprovalReplacementResult(
            approval=approval,
            command=delivery,
            replayed=replayed,
        )


def _expire_locked(
    *,
    approval: RoutineApprovalProjection,
    now: datetime,
    run: RoutineRunSnapshot | None = None,
) -> bool:
    if approval.expires_at > now:
        return False
    if approval.status in {
        RoutineApprovalStatus.AUTHORIZING,
        RoutineApprovalStatus.REJECTED,
        RoutineApprovalStatus.EXPIRED,
        RoutineApprovalStatus.CANCELLED,
        RoutineApprovalStatus.OUTCOME_UNKNOWN,
    }:
        return False
    if approval.status not in {
        RoutineApprovalStatus.PENDING,
        RoutineApprovalStatus.DECISION_RECORDED,
    }:
        return False
    decision_delivery = (
        RoutineApprovalCommand.objects.select_for_update()
        .filter(approval=approval, kind=RoutineApprovalCommandKind.DECISION)
        .first()
    )
    if decision_delivery is not None and decision_delivery.status in {
        RoutineApprovalDeliveryState.PENDING,
        RoutineApprovalDeliveryState.IN_PROGRESS,
        RoutineApprovalDeliveryState.FAILED,
    }:
        decision_delivery.status = RoutineApprovalDeliveryState.RECONCILIATION_NEEDED
        decision_delivery.safe_error_code = "consent_expired"
        decision_delivery.next_attempt_at = None
        decision_delivery.lease_expires_at = None
        decision_delivery.save(
            update_fields=(
                "status",
                "safe_error_code",
                "next_attempt_at",
                "lease_expires_at",
                "updated_at",
            )
        )
    approval.status = RoutineApprovalStatus.EXPIRED
    approval.local_expired_at = now
    approval.last_result_code = "APPROVAL_EXPIRED"
    approval.save(
        update_fields=("status", "local_expired_at", "last_result_code", "updated_at")
    )
    if run is None:
        run = RoutineRunSnapshot.objects.select_for_update().get(pk=approval.run_id)
    if run.outcome in ROUTINE_ACTIVE_RUN_OUTCOMES:
        run.outcome = RoutineRunOutcome.EXPIRED
        run.save(update_fields=("outcome", "updated_at"))
    _create_cancel_intent_locked(
        approval=approval,
        replacing_occurrence_id=approval.occurrence_id,
        reason=ROUTINE_APPROVAL_CANCEL_REASON,
        now=now,
    )
    return True


def expire_routine_approvals(*, limit: int = 20, now: datetime | None = None) -> int:
    """Bound local expiry and enqueue recoverable Foundry cancellation intents."""

    if isinstance(limit, bool) or not 1 <= limit <= 100:
        raise RoutineApprovalInvalid("approval expiry limit is invalid")
    boundary = _aware(now)
    candidates = list(
        RoutineApprovalProjection.objects.filter(
            status__in=(
                RoutineApprovalStatus.PENDING,
                RoutineApprovalStatus.DECISION_RECORDED,
            ),
            expires_at__lte=boundary,
        )
        .order_by("expires_at", "id")
        .values_list("id", "routine_id")[:limit]
    )
    expired = 0
    for approval_id, _routine_id in candidates:
        with transaction.atomic():
            _routine, _occurrence, run, approval = _lock_approval_context(approval_id)
            if _expire_locked(approval=approval, run=run, now=boundary):
                expired += 1
    return expired


def _backoff_seconds(attempt: int) -> int:
    return min(ROUTINE_APPROVAL_MAX_BACKOFF_SECONDS, 2 ** max(0, attempt - 1))


def _parse_command_receipt(
    command: RoutineApprovalCommand,
    receipt: object,
):
    payload = (
        receipt.model_dump(mode="json")
        if isinstance(receipt, ContractModel)
        else receipt
    )
    if command.kind == RoutineApprovalCommandKind.DECISION:
        parsed = _parse_payload(
            FoundryRoutineApprovalReceipt,
            payload,
            label="routine approval receipt",
        )
        if (
            parsed.command_id != command.command_id
            or parsed.idempotency_key != command.idempotency_key
        ):
            raise RoutineApprovalConflict("routine approval receipt identity conflicts")
        return parsed
    return _parse_payload(
        RoutineCancelWaitReceipt,
        payload,
        label="routine cancel-wait receipt",
    )


def _run_status(value: str) -> RoutineRunOutcome:
    return {
        "working": RoutineRunOutcome.WORKING,
        "approval_waiting": RoutineRunOutcome.APPROVAL_WAITING,
        "failed": RoutineRunOutcome.FAILED,
        "cancelled": RoutineRunOutcome.CANCELLED,
        "expired": RoutineRunOutcome.EXPIRED,
    }[value]


def _apply_run_status(run: RoutineRunSnapshot, value: str) -> None:
    target = _run_status(value)
    if run.outcome in {
        RoutineRunOutcome.SUCCEEDED,
        RoutineRunOutcome.FAILED,
        RoutineRunOutcome.CANCELLED,
        RoutineRunOutcome.EXPIRED,
    }:
        return
    if run.outcome != target:
        run.outcome = target
        run.save(update_fields=("outcome", "updated_at"))


def _apply_approval_receipt_locked(
    *,
    approval: RoutineApprovalProjection,
    run: RoutineRunSnapshot,
    receipt: FoundryRoutineApprovalReceipt,
) -> None:
    approval.permission_consumed = receipt.permission_consumed
    approval.action_attempt_state = receipt.action_attempt_state
    approval.last_result_code = receipt.result_code
    if receipt.result_code == "APPROVAL_AUTHORIZED":
        approval.status = RoutineApprovalStatus.AUTHORIZING
    elif receipt.result_code == "APPROVAL_REJECTED":
        approval.status = RoutineApprovalStatus.REJECTED
    elif receipt.result_code == "APPROVAL_EXPIRED":
        approval.status = RoutineApprovalStatus.EXPIRED
    elif receipt.result_code == "APPROVAL_CANCELLED":
        approval.status = RoutineApprovalStatus.CANCELLED
    elif receipt.result_code == "APPROVAL_ALREADY_AUTHORIZING":
        approval.status = RoutineApprovalStatus.AUTHORIZING
    elif receipt.result_code in {
        "ACTION_OUTCOME_UNKNOWN",
        "ACTION_MANUAL_RECONCILIATION",
    }:
        approval.status = RoutineApprovalStatus.OUTCOME_UNKNOWN
    elif receipt.result_code in {
        "STALE_GENERATION",
        "CORRELATION_MISMATCH",
        "IDEMPOTENCY_CONFLICT",
        "REPLACEMENT_PENDING",
    }:
        approval.save(
            update_fields=(
                "permission_consumed",
                "action_attempt_state",
                "last_result_code",
                "updated_at",
            )
        )
        return
    approval.save(
        update_fields=(
            "status",
            "permission_consumed",
            "action_attempt_state",
            "last_result_code",
            "updated_at",
        )
    )
    _apply_run_status(run, receipt.run_status)


def _apply_cancel_receipt_locked(
    *,
    approval: RoutineApprovalProjection,
    run: RoutineRunSnapshot,
    receipt: RoutineCancelWaitReceipt,
) -> None:
    approval.last_result_code = receipt.code
    if receipt.code == "WAIT_CANCELLED":
        approval.status = RoutineApprovalStatus.CANCELLED
        approval.permission_consumed = True
    elif receipt.code == "APPROVAL_ALREADY_AUTHORIZING":
        approval.status = RoutineApprovalStatus.AUTHORIZING
    elif receipt.code == "APPROVAL_ALREADY_TERMINAL":
        status_map = {
            "rejected": RoutineApprovalStatus.REJECTED,
            "expired": RoutineApprovalStatus.EXPIRED,
            "cancelled": RoutineApprovalStatus.CANCELLED,
            "authorizing": RoutineApprovalStatus.AUTHORIZING,
            "pending": RoutineApprovalStatus.PENDING,
        }
        approval.status = status_map[receipt.status]
    approval.save(
        update_fields=(
            "status",
            "permission_consumed",
            "last_result_code",
            "updated_at",
        )
    )
    if receipt.code == "WAIT_CANCELLED":
        _apply_run_status(run, "cancelled")


def _receipt_body(receipt) -> tuple[bytes, str]:
    body = canonical_json_bytes(receipt.model_dump(mode="json"))
    return body, hashlib.sha256(body).hexdigest()


def _parse_approval_command(lease: RoutineApprovalCommandLease):
    try:
        parsed = json.loads(lease.command_bytes)
        if not isinstance(parsed, dict):
            raise TypeError("routine approval command must be an object")
        if canonical_json_bytes(parsed) != lease.command_bytes:
            raise ValueError("routine approval command bytes are not canonical")
        if lease.kind == RoutineApprovalCommandKind.DECISION:
            command = RoutineApprovalDecisionCommand.model_validate(parsed)
        elif lease.kind == RoutineApprovalCommandKind.CANCEL_WAIT:
            command = RoutineCancelWaitCommand.model_validate(parsed)
        else:
            raise ValueError("routine approval command kind is invalid")
        if command.command_id != lease.command_id:
            raise ValueError("routine approval command identity conflicts")
        return command
    except (TypeError, UnicodeDecodeError, ValueError) as exc:
        raise RoutineApprovalInvalid("routine approval command is invalid") from exc


def _settle_approval_transport_failure(
    lease: RoutineApprovalCommandLease,
    exc: Exception,
    *,
    now: datetime | None,
) -> RoutineApprovalDeliveryState:
    if isinstance(
        exc,
        (
            FoundryGatewayUnknownOutcome,
            FoundryGatewayConflict,
            FoundryGatewayNotFound,
            FoundryGatewayRetryable,
            RoutineApprovalConflict,
            RoutineApprovalInvalid,
        ),
    ):
        status = RoutineApprovalDeliveryState.RECONCILIATION_NEEDED
    else:
        status = RoutineApprovalDeliveryState.FAILED
    settle_routine_approval_command(
        lease,
        status=status,
        safe_error_code=getattr(exc, "code", "routine_approval_failed"),
        now=now,
    )
    return status


def _approval_transport_enabled() -> bool:
    return bool(getattr(settings, "ALLIES_ROUTINE_APPROVAL_ENABLED", False))


def dispatch_pending_routine_approval_commands(
    *, now: datetime | None = None, limit: int = 20
) -> RoutineApprovalDispatchReport:
    """Deliver persisted approval/cancel commands through the rev9 gateway."""

    if not _approval_transport_enabled():
        return RoutineApprovalDispatchReport(disabled=1)
    leases = claim_pending_routine_approval_commands(now=now, limit=limit)
    if not leases:
        return RoutineApprovalDispatchReport()
    accepted = 0
    deferred = 0
    failed = 0
    reconciliation = 0
    for lease in leases:
        try:
            _parse_approval_command(lease)
        except RoutineApprovalInvalid as exc:
            status = _settle_approval_transport_failure(lease, exc, now=now)
            if status == RoutineApprovalDeliveryState.RECONCILIATION_NEEDED:
                deferred += 1
                reconciliation += 1
            else:
                failed += 1
            continue
        try:
            if lease.kind == RoutineApprovalCommandKind.DECISION:
                receipt = decide_routine_approval(raw_body=lease.command_bytes)
            else:
                receipt = cancel_routine_wait(raw_body=lease.command_bytes)
            settle_routine_approval_command(
                lease,
                status=RoutineApprovalDeliveryState.ACCEPTED,
                receipt=receipt,
                now=now,
            )
        except (
            FoundryGatewayRetryable,
            FoundryGatewayUnknownOutcome,
            FoundryGatewayConflict,
            FoundryGatewayNotFound,
            FoundryGatewayInvalid,
            FoundryGatewayRejected,
            RoutineApprovalConflict,
            RoutineApprovalInvalid,
        ) as exc:
            status = _settle_approval_transport_failure(lease, exc, now=now)
            if status == RoutineApprovalDeliveryState.RECONCILIATION_NEEDED:
                deferred += 1
                reconciliation += 1
            else:
                failed += 1
        else:
            accepted += 1
    return RoutineApprovalDispatchReport(
        claimed=len(leases),
        deferred=deferred,
        accepted=accepted,
        failed=failed,
        reconciliation=reconciliation,
    )


def claim_pending_routine_approval_commands(
    *, now: datetime | None = None, limit: int = 20
) -> tuple[RoutineApprovalCommandLease, ...]:
    """Claim bounded command work; callers perform transport after commit."""

    boundary = _aware(now)
    bound = max(1, min(int(limit), 100))
    due = Q(
        status__in=(
            RoutineApprovalDeliveryState.PENDING,
            RoutineApprovalDeliveryState.FAILED,
            RoutineApprovalDeliveryState.RECONCILIATION_NEEDED,
        ),
        next_attempt_at__lte=boundary,
    ) | Q(
        status=RoutineApprovalDeliveryState.IN_PROGRESS,
        lease_expires_at__lte=boundary,
    )
    command_ids = list(
        RoutineApprovalCommand.objects.filter(due)
        .order_by("next_attempt_at", "id")
        .values_list("id", flat=True)[:bound]
    )
    lease_until = boundary + timedelta(seconds=ROUTINE_APPROVAL_LEASE_SECONDS)
    claimed: list[RoutineApprovalCommandLease] = []
    with transaction.atomic():
        for command_id in command_ids:
            identity = RoutineApprovalCommand.objects.only("approval_id").get(
                pk=command_id
            )
            _routine, _occurrence, run, approval = _lock_approval_context(
                identity.approval_id
            )
            row = RoutineApprovalCommand.objects.select_for_update().get(pk=command_id)
            if row.status in {
                RoutineApprovalDeliveryState.PENDING,
                RoutineApprovalDeliveryState.FAILED,
                RoutineApprovalDeliveryState.RECONCILIATION_NEEDED,
            }:
                if row.next_attempt_at is None or row.next_attempt_at > boundary:
                    continue
            elif row.status == RoutineApprovalDeliveryState.IN_PROGRESS:
                if row.lease_expires_at is None or row.lease_expires_at > boundary:
                    continue
            else:
                continue
            if row.attempt_count >= ROUTINE_APPROVAL_MAX_ATTEMPTS:
                row.status = RoutineApprovalDeliveryState.RECONCILIATION_NEEDED
                row.safe_error_code = "delivery_attempts_exhausted"
                row.next_attempt_at = None
                row.lease_expires_at = None
                row.save(
                    update_fields=(
                        "status",
                        "safe_error_code",
                        "next_attempt_at",
                        "lease_expires_at",
                        "updated_at",
                    )
                )
                continue
            if (
                row.kind == RoutineApprovalCommandKind.DECISION
                and approval.expires_at <= boundary
                and approval.status
                in {
                    RoutineApprovalStatus.PENDING,
                    RoutineApprovalStatus.DECISION_RECORDED,
                }
            ):
                _expire_locked(approval=approval, run=run, now=boundary)
                continue
            row.attempt_count += 1
            row.status = RoutineApprovalDeliveryState.IN_PROGRESS
            row.last_attempt_at = boundary
            row.lease_expires_at = lease_until
            row.save(
                update_fields=(
                    "attempt_count",
                    "status",
                    "last_attempt_at",
                    "lease_expires_at",
                    "updated_at",
                )
            )
            claimed.append(
                RoutineApprovalCommandLease(
                    command_id=row.command_id,
                    approval_id=approval.id,
                    kind=row.kind,
                    attempt_count=row.attempt_count,
                    lease_expires_at=lease_until,
                    command_bytes=bytes(row.command_bytes),
                )
            )
    return tuple(claimed)


@transaction.atomic
def settle_routine_approval_command(
    lease: RoutineApprovalCommandLease,
    *,
    status: RoutineApprovalDeliveryState,
    receipt: object | None = None,
    safe_error_code: str = "",
    now: datetime | None = None,
) -> bool:
    """Settle only the matching lease; no transport is performed here."""

    boundary = _aware(now)
    identity = (
        RoutineApprovalCommand.objects.only("approval_id")
        .filter(command_id=lease.command_id)
        .first()
    )
    if identity is None:
        return False
    _routine, _occurrence, run, approval = _lock_approval_context(identity.approval_id)
    row = (
        RoutineApprovalCommand.objects.select_for_update()
        .filter(
            command_id=lease.command_id,
            approval=approval,
            status=RoutineApprovalDeliveryState.IN_PROGRESS,
            attempt_count=lease.attempt_count,
            lease_expires_at=lease.lease_expires_at,
        )
        .first()
    )
    if row is None:
        return False
    if status not in {
        RoutineApprovalDeliveryState.ACCEPTED,
        RoutineApprovalDeliveryState.RECONCILIATION_NEEDED,
        RoutineApprovalDeliveryState.FAILED,
    }:
        raise RoutineApprovalInvalid("approval delivery settlement status is invalid")
    parsed_receipt = None
    receipt_body = b""
    receipt_digest = ""
    if status == RoutineApprovalDeliveryState.ACCEPTED:
        if receipt is None:
            raise RoutineApprovalInvalid(
                "accepted approval delivery requires a receipt"
            )
        parsed_receipt = _parse_command_receipt(row, receipt)
        if (
            row.kind == RoutineApprovalCommandKind.DECISION
            and parsed_receipt.scope != _scope_for(approval)
        ):
            raise RoutineApprovalConflict("routine approval receipt scope conflicts")
        receipt_body, receipt_digest = _receipt_body(parsed_receipt)
    elif receipt is not None:
        raise RoutineApprovalInvalid(
            "only accepted approval delivery may carry a receipt"
        )

    row.status = status
    row.receipt_bytes = receipt_body
    row.receipt_digest = receipt_digest
    row.safe_error_code = safe_error_code
    row.lease_expires_at = None
    row.completed_at = (
        boundary if status == RoutineApprovalDeliveryState.ACCEPTED else None
    )
    if status == RoutineApprovalDeliveryState.RECONCILIATION_NEEDED:
        row.next_attempt_at = boundary
    elif status == RoutineApprovalDeliveryState.FAILED:
        row.next_attempt_at = boundary + timedelta(
            seconds=_backoff_seconds(row.attempt_count)
        )
    else:
        row.next_attempt_at = None
    row.save(
        update_fields=(
            "status",
            "receipt_bytes",
            "receipt_digest",
            "safe_error_code",
            "lease_expires_at",
            "completed_at",
            "next_attempt_at",
            "updated_at",
        )
    )
    if parsed_receipt is not None:
        if row.kind == RoutineApprovalCommandKind.DECISION:
            _apply_approval_receipt_locked(
                approval=approval,
                run=run,
                receipt=parsed_receipt,
            )
        else:
            _apply_cancel_receipt_locked(
                approval=approval,
                run=run,
                receipt=parsed_receipt,
            )
    return True


def reconcile_routine_approval_receipt(
    *,
    command_id: UUID | str,
    receipt: object,
    now: datetime | None = None,
) -> bool:
    """Apply a late receipt only through the persisted command identity."""

    key = _parse_uuid(command_id, message="routine command identity is invalid")
    with transaction.atomic():
        identity = RoutineApprovalCommand.objects.only("approval_id").get(
            command_id=key
        )
        _routine, _occurrence, run, approval = _lock_approval_context(
            identity.approval_id
        )
        row = RoutineApprovalCommand.objects.select_for_update().get(command_id=key)
        parsed = _parse_command_receipt(row, receipt)
        if (
            row.kind == RoutineApprovalCommandKind.DECISION
            and parsed.scope != _scope_for(approval)
        ):
            raise RoutineApprovalConflict("routine approval receipt scope conflicts")
        body, digest = _receipt_body(parsed)
        if row.status == RoutineApprovalDeliveryState.ACCEPTED:
            if bytes(row.receipt_bytes) == body:
                return True
            raise RoutineApprovalConflict("routine approval receipt replay conflicts")
        row.status = RoutineApprovalDeliveryState.ACCEPTED
        row.receipt_bytes = body
        row.receipt_digest = digest
        row.safe_error_code = ""
        row.next_attempt_at = None
        row.lease_expires_at = None
        row.completed_at = _aware(now)
        row.save(
            update_fields=(
                "status",
                "receipt_bytes",
                "receipt_digest",
                "safe_error_code",
                "next_attempt_at",
                "lease_expires_at",
                "completed_at",
                "updated_at",
            )
        )
        if row.kind == RoutineApprovalCommandKind.DECISION:
            _apply_approval_receipt_locked(approval=approval, run=run, receipt=parsed)
        else:
            _apply_cancel_receipt_locked(approval=approval, run=run, receipt=parsed)
    return True


apply_approval_requested_event = apply_routine_approval_requested_event
project_routine_approval_requested = apply_routine_approval_requested_event
project_routine_approval = apply_routine_approval_requested_event
record_approval_decision = record_routine_approval_decision
create_routine_approval_cancel_wait = request_routine_approval_replacement
request_routine_approval_cancel_wait = request_routine_approval_replacement
build_approval_decision_command = build_routine_approval_decision_command
build_approval_decision_payload = build_routine_approval_decision_payload
reconcile_routine_approval_command = reconcile_routine_approval_receipt


__all__ = [
    "RoutineApprovalCommandLease",
    "RoutineApprovalConflict",
    "RoutineApprovalDecision",
    "RoutineApprovalDecisionCommand",
    "RoutineApprovalDecisionResult",
    "RoutineApprovalDispatchReport",
    "RoutineApprovalInvalid",
    "RoutineApprovalProjectionResult",
    "RoutineApprovalReceipt",
    "RoutineApprovalReplacementResult",
    "RoutineApprovalRequested",
    "RoutineApprovalRequestedEvent",
    "RoutineApprovalUnauthorized",
    "RoutineApprovalUnavailable",
    "RoutineCancelWait",
    "RoutineCancelWaitCommand",
    "RoutineCancelWaitReceipt",
    "apply_approval_requested_event",
    "apply_routine_approval_requested_event",
    "build_approval_decision_command",
    "build_approval_decision_payload",
    "build_routine_approval_decision_command",
    "build_routine_approval_decision_payload",
    "build_routine_cancel_wait_command",
    "claim_pending_routine_approval_commands",
    "create_routine_approval_cancel_wait",
    "dispatch_pending_routine_approval_commands",
    "expire_routine_approvals",
    "parse_routine_approval_requested",
    "project_routine_approval",
    "project_routine_approval_requested",
    "reconcile_routine_approval_command",
    "reconcile_routine_approval_receipt",
    "record_approval_decision",
    "record_routine_approval_decision",
    "request_routine_approval_cancel_wait",
    "request_routine_approval_replacement",
    "settle_routine_approval_command",
]
