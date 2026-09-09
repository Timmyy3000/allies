"""Revision-9 routine result ingestion and main-turn projection seam.

The accepted successor requires the result title snapshot to match the
immutable dispatch snapshot. This module keeps that boundary isolated from the
existing conversation-message gateway.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from pydantic import Field, StrictInt, StrictStr, field_validator, model_validator

from activities.models import (
    RoutineResultContext,
    RoutineResultInsertionState,
    RoutineResultOutcome,
    RoutineResultProjection,
    RoutineResultReceipt,
)
from allies.gateways.contracts import (
    MAX_COMMAND_TEXT_BYTES,
    MAX_CONTRACT_LIFETIME_SECONDS,
    MAX_EVENT_PAYLOAD_BYTES,
    ContractModel,
    canonical_fingerprint,
    canonical_json_bytes,
)
from chat.models import (
    NONTERMINAL_MESSAGE_STATUSES,
    Conversation,
    Message,
    MessageOrigin,
    MessageSender,
)

from ..models import (
    ROUTINE_ACTIVE_RUN_OUTCOMES,
    Routine,
    RoutineDispatchOutbox,
    RoutineDispatchState,
    RoutineOccurrence,
    RoutineRunOutcome,
    RoutineRunSnapshot,
)

ROUTINE_RESULT_TEXT_MAX_BYTES = 16 * 1024
ROUTINE_RESULT_TITLE_MAX_LENGTH = 120
ROUTINE_RESULT_REFERENCE_MAX = 20
ROUTINE_CONTEXT_MAX_BYTES = MAX_COMMAND_TEXT_BYTES


class RoutineResultInvalid(ValueError):
    """A candidate result is not a valid successor-contract event."""


class RoutineResultConflict(ValueError):
    """A valid result identity conflicts with an existing Cloud projection."""


class RoutineResultUnavailable(ValueError):
    """The result correlation is not available in Cloud."""


class RoutineResultScope(ContractModel):
    kind: str = Field(pattern="^workspace$")
    workspace_id: UUID
    owner_user_id: UUID
    ally_id: UUID
    cloud_binding_id: UUID


class RoutineResultReference(ContractModel):
    label: StrictStr = Field(min_length=1, max_length=120)
    url: StrictStr = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("routine result reference URL is invalid")
        if (
            parsed.username is not None
            or parsed.password is not None
            or "@" in parsed.netloc
            or "%40" in parsed.netloc.lower()
        ):
            raise ValueError(
                "routine result reference URL must not contain credentials"
            )
        if any(ord(character) < 0x20 for character in value):
            raise ValueError("routine result reference URL is invalid")
        return value


class RoutineResultEvent(ContractModel):
    """The narrow result successor shape, including immutable title_snapshot."""

    schema_version: str = Field(pattern="^v1$")
    kind: str = Field(pattern=r"^routine\.result$")
    producer: str = Field(pattern="^foundry$")
    service_identity: str = Field(pattern="^foundry-service$")
    event_id: UUID
    event_sequence: StrictInt = Field(ge=1, le=100_001)
    routine_id: UUID
    occurrence_id: UUID
    run_id: UUID
    routine_revision: StrictInt = Field(ge=1)
    execution_id: UUID
    attempt_id: UUID
    generation: StrictInt = Field(ge=0)
    main_conversation_id: UUID
    run_conversation_id: UUID
    outcome: str = Field(pattern="^(changed|unchanged|failed)$")
    text: StrictStr = Field(min_length=1, max_length=ROUTINE_RESULT_TEXT_MAX_BYTES)
    references: list[RoutineResultReference] = Field(
        default_factory=list, max_length=ROUTINE_RESULT_REFERENCE_MAX
    )
    delayed: bool
    title_snapshot: StrictStr = Field(
        min_length=1, max_length=ROUTINE_RESULT_TITLE_MAX_LENGTH
    )
    scope: RoutineResultScope
    issued_at: datetime
    deadline_at: datetime
    fingerprint: StrictStr = Field(pattern=r"^canonical-json-sha256:v1:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_result(self) -> RoutineResultEvent:
        if self.main_conversation_id == self.run_conversation_id:
            raise ValueError("routine result conversations must be distinct")
        if self.issued_at.tzinfo is None or self.deadline_at.tzinfo is None:
            raise ValueError("routine result timestamps must be timezone-aware")
        if self.deadline_at <= self.issued_at:
            raise ValueError("routine result deadline must be later than issued_at")
        if (
            self.deadline_at - self.issued_at
        ).total_seconds() > MAX_CONTRACT_LIFETIME_SECONDS:
            raise ValueError("routine result deadline is outside the bounded window")
        if len(self.text.encode("utf-8")) > ROUTINE_RESULT_TEXT_MAX_BYTES:
            raise ValueError("routine result text is too large")
        if self.fingerprint != canonical_fingerprint(self):
            raise ValueError("routine result fingerprint is invalid")
        return self


@dataclass(frozen=True, slots=True)
class RoutineProjectionResult:
    status: str
    event_id: UUID
    result: RoutineResultProjection
    receipt: RoutineResultReceipt


def parse_routine_result(payload: object) -> RoutineResultEvent:
    if not isinstance(payload, dict):
        raise RoutineResultInvalid("routine result must be an object")
    try:
        event = RoutineResultEvent.model_validate(payload)
        if len(canonical_json_bytes(payload)) > MAX_EVENT_PAYLOAD_BYTES:
            raise RoutineResultInvalid("routine result is too large")
        return event
    except RoutineResultInvalid:
        raise
    except ValueError as exc:
        raise RoutineResultInvalid("routine result is invalid") from exc


def _scope_matches(event: RoutineResultEvent, routine: Routine) -> bool:
    return event.scope == RoutineResultScope(
        kind="workspace",
        workspace_id=routine.workspace_id,
        owner_user_id=routine.owner_id,
        ally_id=routine.ally_id,
        cloud_binding_id=routine.binding_id,
    )


def _same_projection(
    projection: RoutineResultProjection, event: RoutineResultEvent
) -> bool:
    return (
        projection.event_id == event.event_id
        and projection.event_sequence == event.event_sequence
        and projection.run_id == event.run_id
        and projection.execution_id == event.execution_id
        and projection.attempt_id == event.attempt_id
        and projection.generation == event.generation
        and projection.routine_revision == event.routine_revision
        and projection.fingerprint == event.fingerprint
    )


@transaction.atomic
def project_routine_result(
    payload: object,
) -> RoutineProjectionResult:
    """Persist one result receipt and leave main-turn insertion explicitly pending."""

    event = parse_routine_result(payload)
    try:
        routine = (
            Routine.objects.select_for_update()
            .select_related("ally", "binding")
            .get(pk=event.routine_id)
        )
    except Routine.DoesNotExist as exc:
        raise RoutineResultUnavailable("routine result unavailable") from exc
    if not _scope_matches(event, routine):
        raise RoutineResultInvalid("routine result scope does not match routine")

    try:
        occurrence = RoutineOccurrence.objects.select_for_update().get(
            pk=event.occurrence_id,
            routine=routine,
        )
        run = RoutineRunSnapshot.objects.select_for_update().get(
            pk=event.run_id,
            occurrence=occurrence,
            routine=routine,
        )
        outbox = RoutineDispatchOutbox.objects.select_for_update().get(run=run)
    except (RoutineOccurrence.DoesNotExist, RoutineRunSnapshot.DoesNotExist) as exc:
        raise RoutineResultUnavailable(
            "routine result correlation unavailable"
        ) from exc
    except RoutineDispatchOutbox.DoesNotExist as exc:
        raise RoutineResultUnavailable(
            "routine dispatch correlation unavailable"
        ) from exc

    if (
        outbox.status != RoutineDispatchState.ACCEPTED
        or outbox.execution_id is None
        or outbox.attempt_id is None
        or outbox.generation is None
    ):
        raise RoutineResultUnavailable("routine dispatch was not accepted")
    if (
        event.execution_id != outbox.execution_id
        or event.attempt_id != outbox.attempt_id
        or event.generation != outbox.generation
    ):
        raise RoutineResultConflict("routine result execution identity conflicts")

    if (
        event.routine_revision != run.routine_revision
        or event.main_conversation_id != run.main_conversation_id
        or event.run_conversation_id != run.run_conversation_id
        or event.title_snapshot != run.title_snapshot
    ):
        raise RoutineResultConflict("routine result correlation conflicts")

    existing = (
        RoutineResultProjection.objects.select_for_update()
        .filter(event_id=event.event_id)
        .first()
    )
    if existing is not None:
        if not _same_projection(existing, event):
            raise RoutineResultConflict("routine result replay conflicts")
        receipt = RoutineResultReceipt.objects.select_for_update().get(result=existing)
        return RoutineProjectionResult(
            status="duplicate",
            event_id=event.event_id,
            result=existing,
            receipt=existing.receipt,
        )
    if RoutineResultProjection.objects.filter(run_id=event.run_id).exists():
        raise RoutineResultConflict("routine already has a result")
    if run.outcome not in ROUTINE_ACTIVE_RUN_OUTCOMES:
        raise RoutineResultConflict("routine run is no longer accepting results")

    result = RoutineResultProjection.objects.create(
        event_id=event.event_id,
        event_sequence=event.event_sequence,
        routine=routine,
        occurrence=occurrence,
        run=run,
        routine_revision=event.routine_revision,
        execution_id=event.execution_id,
        attempt_id=event.attempt_id,
        generation=event.generation,
        main_conversation_id=event.main_conversation_id,
        run_conversation_id=event.run_conversation_id,
        workspace_id=routine.workspace_id,
        owner_id=routine.owner_id,
        ally_id=routine.ally_id,
        binding_id=routine.binding_id,
        title_snapshot=event.title_snapshot,
        outcome=event.outcome,
        text=event.text,
        references=[
            reference.model_dump(mode="json") for reference in event.references
        ],
        delayed=event.delayed,
        issued_at=event.issued_at,
        deadline_at=event.deadline_at,
        fingerprint=event.fingerprint,
        insertion_state=RoutineResultInsertionState.PENDING,
    )
    run.outcome = (
        RoutineRunOutcome.FAILED
        if event.outcome == RoutineResultOutcome.FAILED
        else RoutineRunOutcome.SUCCEEDED
    )
    run.save(update_fields=("outcome", "updated_at"))
    receipt = RoutineResultReceipt.objects.create(
        result=result,
        event_id=event.event_id,
        event_sequence=event.event_sequence,
        disposition="applied",
        result_insertion=RoutineResultInsertionState.PENDING,
    )
    return RoutineProjectionResult(
        status="applied",
        event_id=event.event_id,
        result=result,
        receipt=receipt,
    )


def pending_routine_results(*, conversation_id: UUID | str):
    """Return pending compact context in insertion order for the chat boundary."""

    return RoutineResultProjection.objects.filter(
        main_conversation_id=conversation_id,
        insertion_state=RoutineResultInsertionState.PENDING,
    ).order_by("created_at", "id")


def _routine_result_context_text(result: RoutineResultProjection) -> str:
    lines = [
        "[Routine result]",
        f"Title: {result.title_snapshot}",
        f"Outcome: {result.outcome}",
        f"Delayed: {'yes' if result.delayed else 'no'}",
        "Result:",
        result.text,
    ]
    for reference in result.references:
        if not isinstance(reference, dict):
            raise RoutineResultInvalid("routine result references are invalid")
        label = reference.get("label")
        url = reference.get("url")
        if not isinstance(label, str) or not isinstance(url, str):
            raise RoutineResultInvalid("routine result references are invalid")
        lines.append(f"Reference: {label} — {url}")
    rendered = "\n".join(lines)
    if len(rendered.encode("utf-8")) > ROUTINE_CONTEXT_MAX_BYTES:
        raise RoutineResultConflict("routine result context exceeds command budget")
    return rendered


def _conversation_has_active_turn(conversation: Conversation) -> bool:
    return Message.objects.filter(
        conversation=conversation,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        status__in=NONTERMINAL_MESSAGE_STATUSES,
        deleted_at__isnull=True,
    ).exists()


def _conversation_watermark(conversation: Conversation) -> int:
    maximum = Message.objects.filter(conversation=conversation).aggregate(
        maximum=Max("sequence")
    )["maximum"]
    return max(1, int(maximum or 0))


def _complete_routine_result_insertion_locked(
    *,
    result: RoutineResultProjection,
    conversation: Conversation,
    insertion_watermark: int,
    now: datetime,
) -> RoutineResultProjection:
    context_text = _routine_result_context_text(result)
    context, _created = RoutineResultContext.objects.get_or_create(
        result=result,
        defaults={
            "conversation": conversation,
            "context_text": context_text,
            "insertion_watermark": insertion_watermark,
        },
    )
    if (
        context.conversation_id != conversation.id
        or context.context_text != context_text
        or context.insertion_watermark != insertion_watermark
    ):
        raise RoutineResultConflict("routine result context replay conflicts")
    if result.insertion_state == RoutineResultInsertionState.INSERTED:
        if result.insertion_watermark != insertion_watermark:
            raise RoutineResultConflict("routine result insertion replay conflicts")
        return result
    result.insertion_state = RoutineResultInsertionState.INSERTED
    result.insertion_watermark = insertion_watermark
    result.inserted_at = now
    result.save(
        update_fields=(
            "insertion_state",
            "insertion_watermark",
            "inserted_at",
            "updated_at",
        )
    )
    receipt = RoutineResultReceipt.objects.select_for_update().get(result=result)
    receipt.result_insertion = RoutineResultInsertionState.INSERTED
    receipt.insertion_watermark = insertion_watermark
    receipt.save(
        update_fields=("result_insertion", "insertion_watermark", "updated_at")
    )
    return result


def complete_pending_routine_results_locked(
    *,
    conversation: Conversation,
    insertion_watermark: int | None = None,
    now: datetime | None = None,
) -> tuple[RoutineResultProjection, ...]:
    """Insert pending routine context while the caller holds Conversation."""

    if _conversation_has_active_turn(conversation):
        return ()
    watermark = insertion_watermark or _conversation_watermark(conversation)
    if watermark < 1:
        raise RoutineResultInvalid("routine result insertion watermark is invalid")
    inserted_at = now or timezone.now()
    pending = list(
        RoutineResultProjection.objects.select_for_update()
        .filter(
            main_conversation_id=conversation.id,
            insertion_state=RoutineResultInsertionState.PENDING,
        )
        .order_by("created_at", "id")
    )
    return tuple(
        _complete_routine_result_insertion_locked(
            result=result,
            conversation=conversation,
            insertion_watermark=watermark,
            now=inserted_at,
        )
        for result in pending
    )


@transaction.atomic
def complete_pending_routine_results(
    *,
    conversation_id: UUID | str,
    insertion_watermark: int | None = None,
    now: datetime | None = None,
) -> tuple[RoutineResultProjection, ...]:
    conversation = Conversation.objects.select_for_update().get(pk=conversation_id)
    return complete_pending_routine_results_locked(
        conversation=conversation,
        insertion_watermark=insertion_watermark,
        now=now,
    )


@transaction.atomic
def complete_routine_result_insertion(
    *,
    result_id: UUID | str,
    insertion_watermark: int,
    now: datetime | None = None,
) -> RoutineResultProjection:
    """A chat dispatcher calls this only after inserting context at a turn boundary."""

    if insertion_watermark < 1:
        raise RoutineResultInvalid("routine result insertion watermark is invalid")
    result_identity = RoutineResultProjection.objects.only("main_conversation_id").get(
        pk=result_id
    )
    conversation = Conversation.objects.select_for_update().get(
        pk=result_identity.main_conversation_id
    )
    if _conversation_has_active_turn(conversation):
        raise RoutineResultConflict("main conversation turn is still active")
    result = RoutineResultProjection.objects.select_for_update().get(
        pk=result_id,
        main_conversation_id=conversation.id,
    )
    return _complete_routine_result_insertion_locked(
        result=result,
        conversation=conversation,
        insertion_watermark=insertion_watermark,
        now=now or timezone.now(),
    )


__all__ = [
    "RoutineProjectionResult",
    "RoutineResultConflict",
    "RoutineResultEvent",
    "RoutineResultInvalid",
    "RoutineResultReference",
    "RoutineResultScope",
    "RoutineResultUnavailable",
    "complete_pending_routine_results",
    "complete_pending_routine_results_locked",
    "complete_routine_result_insertion",
    "parse_routine_result",
    "pending_routine_results",
    "project_routine_result",
]
