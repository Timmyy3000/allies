"""Validate and project authenticated Foundry events into Cloud activities."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.db.models import Func, IntegerField, Sum

from allies.gateways.contracts import FoundryEventEnvelope
from allies.models import AllyBinding, BindingStatus
from chat.models import (
    Conversation,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessageSender,
)
from common.uuids import canonical_uuid
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability

from ..exceptions import (
    ProjectionConflict,
    ProjectionInvalid,
    ProjectionNotFound,
    ProjectionSequenceGap,
)
from ..models import Activity, FoundryEventReceipt, ProjectionState

MAX_ACTIVITY_SNAPSHOT = 200
MAX_ACTIVITIES_PER_MESSAGE = 513
MAX_ACTIVITIES_PER_CONVERSATION = 8192
MAX_EVENT_RECEIPTS_PER_MESSAGE = 513
MAX_AGGREGATE_TEXT_BYTES = 64 * 1024
MAX_CONVERSATION_TEXT_BYTES = 4 * 1024 * 1024
_TERMINAL_STATES = {
    MessageLifecycle.COMPLETED,
    MessageLifecycle.FAILED,
    MessageLifecycle.STOPPED,
}


class _OctetLength(Func):
    function = "OCTET_LENGTH"
    output_field = IntegerField()

    def as_sqlite(self, compiler, connection, **extra_context):
        return self.as_sql(
            compiler,
            connection,
            template="LENGTH(CAST(%(expressions)s AS BLOB))",
            **extra_context,
        )


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    status: str
    event_id: UUID
    activity: Activity | None = None
    last_contiguous_sequence: int = 0


@dataclass(frozen=True, slots=True)
class ActivitySnapshot:
    conversation: Conversation
    activities: tuple[Activity, ...]
    state: str
    last_contiguous_sequence: int


def _message_for_event(envelope: FoundryEventEnvelope) -> Message:
    cloud = envelope.cloud
    message = (
        Message.objects.select_related("conversation__ally__workspace")
        .filter(
            pk=cloud.message_id,
            conversation_id=cloud.conversation_id,
            conversation__ally_id=cloud.ally_id,
            conversation__ally__workspace_id=envelope.scope.cloud_workspace_id,
            sender=MessageSender.USER,
            origin=MessageOrigin.SEND,
        )
        .first()
    )
    if message is None:
        raise ProjectionNotFound("projection unavailable")
    binding = AllyBinding.objects.filter(
        pk=cloud.cloud_binding_id,
        ally_id=cloud.ally_id,
        status=BindingStatus.BOUND,
    ).first()
    if binding is None:
        raise ProjectionNotFound("projection unavailable")
    if envelope.conversation_turn_ordinal != message.sequence:
        raise ProjectionConflict("conversation ordinal conflicts with message")
    return message


def _event_state(event_type: str) -> tuple[str, str, str, str]:
    if event_type == "execution.accepted":
        return ProjectionState.QUEUED, "execution", "", MessageLifecycle.QUEUED
    if event_type == "message.delta":
        return (
            ProjectionState.RUNNING,
            "assistant_delta",
            "",
            MessageLifecycle.IN_PROGRESS,
        )
    if event_type == "activity.started":
        return (
            ProjectionState.RUNNING,
            "activity_started",
            "Activity started",
            MessageLifecycle.IN_PROGRESS,
        )
    if event_type == "activity.completed":
        return (
            ProjectionState.RUNNING,
            "activity_completed",
            "Activity completed",
            MessageLifecycle.IN_PROGRESS,
        )
    if event_type == "execution.awaiting_action":
        return (
            ProjectionState.AWAITING_ACTION,
            "awaiting_action",
            "Action required",
            MessageLifecycle.AWAITING_ACTION,
        )
    if event_type == "execution.completed":
        return (
            ProjectionState.COMPLETED,
            "execution_completed",
            "",
            MessageLifecycle.COMPLETED,
        )
    if event_type == "execution.stopped":
        return (
            ProjectionState.STOPPED,
            "execution_stopped",
            "",
            MessageLifecycle.STOPPED,
        )
    if event_type == "execution.failed":
        return ProjectionState.FAILED, "execution_failed", "", MessageLifecycle.FAILED
    raise ProjectionInvalid("event type is not supported")


def _last_contiguous(message_id: UUID, attempt_id: UUID, generation: int) -> int:
    sequences = set(
        FoundryEventReceipt.objects.filter(
            message_id=message_id,
            attempt_id=attempt_id,
            generation=generation,
        ).values_list("attempt_sequence", flat=True)
    )
    current = 0
    while current + 1 in sequences:
        current += 1
    return current


def _prior_turn_is_open(message: Message) -> bool:
    return Message.objects.filter(
        conversation_id=message.conversation_id,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        sequence__lt=message.sequence,
        status__in=(
            MessageLifecycle.QUEUED,
            MessageLifecycle.IN_PROGRESS,
            MessageLifecycle.AWAITING_ACTION,
        ),
    ).exists()


def _text_bytes(queryset) -> int:
    return int(queryset.aggregate(total=Sum(_OctetLength("text")))["total"] or 0)


def _ensure_projection_bounds(
    *, message: Message, conversation: Conversation, text: str, terminal: bool
) -> bool:
    message_activities = Activity.objects.filter(message_id=message.id)
    conversation_activities = Activity.objects.filter(conversation_id=conversation.id)
    reserved_terminal_slot = 0 if terminal else 1
    if message_activities.count() >= (
        MAX_ACTIVITIES_PER_MESSAGE - reserved_terminal_slot
    ):
        raise ProjectionInvalid("message activity limit reached")
    visible_activity_allowed = conversation_activities.count() < (
        MAX_ACTIVITIES_PER_CONVERSATION - reserved_terminal_slot
    )

    message_receipts = FoundryEventReceipt.objects.filter(message_id=message.id)
    if message_receipts.count() >= (
        MAX_EVENT_RECEIPTS_PER_MESSAGE - reserved_terminal_slot
    ):
        raise ProjectionInvalid("message event limit reached")
    if not text:
        return visible_activity_allowed

    text_bytes = len(text.encode("utf-8"))
    if _text_bytes(message_activities) + text_bytes > MAX_AGGREGATE_TEXT_BYTES:
        visible_activity_allowed = False
    if _text_bytes(conversation_activities) + text_bytes > MAX_CONVERSATION_TEXT_BYTES:
        visible_activity_allowed = False
    return visible_activity_allowed


@transaction.atomic
def project_foundry_event(envelope: FoundryEventEnvelope) -> ProjectionResult:
    """Apply one validated event, preserving exact duplicate/no-op semantics."""

    message = _message_for_event(envelope)
    conversation = Conversation.objects.select_for_update().get(
        pk=message.conversation_id
    )
    message = Message.objects.select_for_update().get(pk=message.id)
    foundry = envelope.foundry

    existing_event = (
        FoundryEventReceipt.objects.select_for_update()
        .filter(message_id=message.id, event_id=envelope.event_id)
        .first()
    )
    if existing_event is not None:
        if (
            existing_event.execution_id != foundry.execution_id
            or existing_event.attempt_id != foundry.attempt_id
            or existing_event.generation != foundry.generation
            or existing_event.attempt_sequence != foundry.attempt_sequence
            or existing_event.event_fingerprint != envelope.fingerprint
        ):
            raise ProjectionConflict("event identity conflicts with existing receipt")
        return ProjectionResult(
            status="duplicate",
            event_id=envelope.event_id,
            last_contiguous_sequence=_last_contiguous(
                message.id, foundry.attempt_id, foundry.generation
            ),
        )
    if FoundryEventReceipt.objects.filter(
        message_id=message.id,
        event_dedupe_key=envelope.event_dedupe_key,
    ).exists():
        raise ProjectionConflict(
            "event dedupe identity conflicts with existing receipt"
        )
    same_sequence = (
        FoundryEventReceipt.objects.select_for_update()
        .filter(
            message_id=message.id,
            attempt_id=foundry.attempt_id,
            generation=foundry.generation,
            attempt_sequence=foundry.attempt_sequence,
        )
        .first()
    )
    if same_sequence is not None:
        raise ProjectionConflict("event sequence conflicts with existing receipt")

    current_execution = (
        FoundryEventReceipt.objects.filter(message_id=message.id)
        .values_list("execution_id", flat=True)
        .first()
    )
    if current_execution is not None and current_execution != foundry.execution_id:
        raise ProjectionConflict("event execution identity conflicts with message")

    current_generation = (
        FoundryEventReceipt.objects.filter(message_id=message.id)
        .order_by("-generation")
        .values_list("generation", flat=True)
        .first()
    )
    if current_generation is not None and foundry.generation < current_generation:
        raise ProjectionConflict("event generation is stale")
    current_attempt = (
        FoundryEventReceipt.objects.filter(
            message_id=message.id, generation=foundry.generation
        )
        .values_list("attempt_id", flat=True)
        .first()
    )
    if current_attempt is not None and current_attempt != foundry.attempt_id:
        raise ProjectionConflict("event attempt identity conflicts with generation")
    if _prior_turn_is_open(message):
        raise ProjectionSequenceGap("prior conversation turn is not terminal")
    expected_sequence = (
        _last_contiguous(message.id, foundry.attempt_id, foundry.generation) + 1
    )
    if foundry.attempt_sequence > expected_sequence:
        raise ProjectionSequenceGap("event sequence gap")
    if foundry.attempt_sequence < expected_sequence:
        raise ProjectionConflict("event sequence is stale")
    if message.status in _TERMINAL_STATES:
        raise ProjectionConflict("terminal message cannot accept another event")

    state, kind, default_text, message_status = _event_state(envelope.event_type)
    text = (
        str(envelope.payload.get("text", default_text))
        if envelope.event_type == "message.delta"
        else default_text
    )
    visible_activity_allowed = _ensure_projection_bounds(
        message=message,
        conversation=conversation,
        text=text,
        terminal=message_status in _TERMINAL_STATES,
    )
    activity = None
    product_sequence = None
    if visible_activity_allowed:
        last_activity = (
            Activity.objects.order_by("-sequence")
            .filter(conversation_id=conversation.id)
            .first()
        )
        product_sequence = (last_activity.sequence if last_activity else 0) + 1
        activity = Activity.objects.create(
            conversation=conversation,
            message=message,
            sequence=product_sequence,
            conversation_turn_ordinal=message.sequence,
            generation=foundry.generation,
            attempt_id=foundry.attempt_id,
            attempt_sequence=foundry.attempt_sequence,
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            kind=kind,
            text=text,
            state=state,
            event_fingerprint=envelope.fingerprint,
        )
    FoundryEventReceipt.objects.create(
        conversation=conversation,
        message=message,
        event_id=envelope.event_id,
        execution_id=foundry.execution_id,
        event_dedupe_key=envelope.event_dedupe_key,
        attempt_id=foundry.attempt_id,
        generation=foundry.generation,
        attempt_sequence=foundry.attempt_sequence,
        event_fingerprint=envelope.fingerprint,
        result="applied",
        product_sequence=product_sequence,
    )
    message.status = message_status
    message.save(update_fields=("status", "updated_at"))
    return ProjectionResult(
        status="applied",
        event_id=envelope.event_id,
        activity=activity,
        last_contiguous_sequence=foundry.attempt_sequence,
    )


def read_activity_snapshot(
    *, user, workspace_id: UUID | str, conversation_id: UUID | str, limit: int = 200
) -> ActivitySnapshot:
    if not 1 <= limit <= MAX_ACTIVITY_SNAPSHOT:
        raise ProjectionInvalid("activity limit is invalid")
    context = require_workspace_capability(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.PROFILE_READ,
    )
    try:
        parsed = canonical_uuid(conversation_id)
    except (TypeError, ValueError) as exc:
        raise ProjectionNotFound("projection unavailable") from exc
    conversation = (
        Conversation.objects.select_related("ally", "ally__workspace")
        .filter(pk=parsed, ally__workspace=context.workspace)
        .first()
    )
    if conversation is None:
        raise ProjectionNotFound("projection unavailable")
    rows = tuple(
        Activity.objects.filter(conversation=conversation).order_by("-sequence", "-id")[
            :limit
        ]
    )
    rows = tuple(reversed(rows))
    latest = (
        Message.objects.filter(
            conversation=conversation,
            sender=MessageSender.USER,
            origin=MessageOrigin.SEND,
        )
        .order_by("-sequence", "-id")
        .first()
    )
    state = latest.status if latest is not None else ProjectionState.COMPLETED
    last_contiguous = 0
    if latest is not None:
        latest_receipt = (
            FoundryEventReceipt.objects.filter(message=latest)
            .order_by("-generation", "-attempt_sequence")
            .first()
        )
        if latest_receipt is not None:
            last_contiguous = _last_contiguous(
                latest.id, latest_receipt.attempt_id, latest_receipt.generation
            )
    return ActivitySnapshot(conversation, rows, state, last_contiguous)


__all__ = [
    "ActivitySnapshot",
    "ProjectionResult",
    "project_foundry_event",
    "read_activity_snapshot",
]
