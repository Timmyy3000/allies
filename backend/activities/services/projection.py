"""Validate and project authenticated Foundry events into Cloud activities."""

from __future__ import annotations

import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Func, IntegerField, Max, Sum
from django.utils import timezone

from allies.gateways.contracts import MAX_TERMINAL_SEQUENCE, FoundryEventEnvelope
from allies.models import AllyBinding, BindingStatus
from chat.models import (
    ASSISTANT_REPLY_MAX_BYTES,
    NONTERMINAL_MESSAGE_STATUSES,
    AssistantReply,
    Conversation,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessageSender,
)
from common.cursors import b64decode, b64encode, cursor_keys
from common.uuids import canonical_uuid
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability

from ..exceptions import (
    ProjectionConflict,
    ProjectionCursorExpired,
    ProjectionCursorGap,
    ProjectionCursorInvalid,
    ProjectionInvalid,
    ProjectionNotFound,
    ProjectionSequenceGap,
)
from ..models import Activity, FoundryEventReceipt, ProjectionState

MAX_ACTIVITY_SNAPSHOT = 200
MAX_ACTIVITIES_PER_MESSAGE = 513
MAX_ACTIVITIES_PER_CONVERSATION = 8192
MAX_EVENT_RECEIPTS_PER_MESSAGE = MAX_TERMINAL_SEQUENCE
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
    last_contiguous_activity_sequence: int = 0
    resume_cursor: str | None = None
    next_cursor: str | None = None
    oldest_sequence: int | None = None
    latest_sequence: int | None = None
    retention_gap: bool = False
    assistant_reply: AssistantReply | None = None
    active_message_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ActivityCursor:
    conversation_id: str
    after_sequence: int
    high_water_sequence: int
    expires_at: int


_ACTIVITY_CURSOR_FIELDS = frozenset({"v", "t", "c", "a", "h", "e"})
_MAX_CURSOR_SEQUENCE = 2_147_483_647


def _bounded_cursor_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(getattr(settings, name, default))
    except (TypeError, ValueError) as exc:
        raise ProjectionInvalid("activity cursor configuration is invalid") from exc
    if not minimum <= value <= maximum:
        raise ProjectionInvalid("activity cursor configuration is invalid")
    return value


def serialize_activity_cursor(
    conversation_id: UUID | str,
    after_sequence: int = 0,
    high_water_sequence: int | None = None,
    now: datetime | None = None,
) -> str:
    """Return a signed cursor positioned immediately after an activity sequence."""

    try:
        parsed_conversation_id = str(canonical_uuid(conversation_id))
        after_sequence = int(after_sequence)
        high_water_sequence = (
            after_sequence if high_water_sequence is None else int(high_water_sequence)
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProjectionCursorInvalid("activity cursor is invalid") from exc
    if (
        after_sequence < 0
        or high_water_sequence < after_sequence
        or high_water_sequence > _MAX_CURSOR_SEQUENCE
    ):
        raise ProjectionCursorInvalid("activity cursor is invalid")
    ttl = _bounded_cursor_setting("ALLIES_CHAT_CURSOR_TTL_SECONDS", 3600, 1, 86_400)
    expires_at = int((now or timezone.now()).timestamp()) + ttl
    payload = {
        "v": 1,
        "t": "activity",
        "c": parsed_conversation_id,
        "a": after_sequence,
        "h": high_water_sequence,
        "e": expires_at,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    _active_key_id, keys = cursor_keys()
    key = keys.get(_active_key_id)
    if not key:
        raise ProjectionCursorInvalid("activity cursor is invalid")
    signature = hmac.new(key, raw, hashlib.sha256).hexdigest()
    return f"{b64encode(raw)}.{signature}"


def parse_activity_cursor(
    cursor: str,
    conversation_id: UUID | str,
    now: datetime | None = None,
) -> ActivityCursor:
    """Read a signed activity cursor without accepting message cursors."""

    try:
        expected_conversation_id = str(canonical_uuid(conversation_id))
    except (TypeError, ValueError) as exc:
        raise ProjectionCursorInvalid("activity cursor is invalid") from exc
    if not isinstance(cursor, str) or not 1 <= len(cursor) <= 512:
        raise ProjectionCursorInvalid("activity cursor is invalid")
    try:
        encoded, signature = cursor.split(".", 1)
        raw = b64decode(encoded)
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != _ACTIVITY_CURSOR_FIELDS:
            raise ValueError
        if not isinstance(signature, str) or len(signature) != 64:
            raise ValueError
        if not any(
            hmac.compare_digest(
                signature,
                hmac.new(key, raw, hashlib.sha256).hexdigest(),
            )
            for key in cursor_keys()[1].values()
        ):
            raise ValueError
        if (
            type(payload["v"]) is not int
            or payload["v"] != 1
            or payload["t"] != "activity"
            or not isinstance(payload["c"], str)
            or str(canonical_uuid(payload["c"])) != expected_conversation_id
            or type(payload["a"]) is not int
            or type(payload["h"]) is not int
            or type(payload["e"]) is not int
        ):
            raise ValueError
        after_sequence = payload["a"]
        high_water_sequence = payload["h"]
        expires_at = payload["e"]
        if (
            after_sequence < 0
            or high_water_sequence < after_sequence
            or high_water_sequence > _MAX_CURSOR_SEQUENCE
            or expires_at <= 0
        ):
            raise ValueError
    except ProjectionCursorExpired:
        raise
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        IndexError,
        OverflowError,
        UnicodeError,
        binascii.Error,
    ):
        raise ProjectionCursorInvalid("activity cursor is invalid") from None
    if expires_at <= int((now or timezone.now()).timestamp()):
        raise ProjectionCursorExpired("activity cursor expired")
    return ActivityCursor(
        expected_conversation_id,
        after_sequence,
        high_water_sequence,
        expires_at,
    )


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
    # Receipts are inserted contiguously under the conversation lock.
    return (
        FoundryEventReceipt.objects.filter(
            message_id=message_id,
            attempt_id=attempt_id,
            generation=generation,
        ).aggregate(sequence=Max("attempt_sequence"))["sequence"]
        or 0
    )


def _last_contiguous_activity_sequence(queryset) -> int:
    return (
        queryset.order_by("-sequence").values_list("sequence", flat=True).first() or 0
    )


def _prior_turn_is_open(message: Message) -> bool:
    prior_turns = Message.objects.filter(
        conversation_id=message.conversation_id,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        sequence__lt=message.sequence,
        status__in=(*NONTERMINAL_MESSAGE_STATUSES,),
    )
    return prior_turns.exists()


def _text_bytes(queryset) -> int:
    return int(queryset.aggregate(total=Sum(_OctetLength("text")))["total"] or 0)


def _ensure_projection_bounds(
    *,
    message: Message,
    conversation: Conversation,
    text: str,
    terminal: bool,
    attempt_sequence: int,
) -> bool:
    message_activities = Activity.objects.filter(message_id=message.id)
    conversation_activities = Activity.objects.filter(conversation_id=conversation.id)
    reserved_terminal_slot = 0 if terminal else 1
    visible_activity_allowed = (
        message_activities.count() < MAX_ACTIVITIES_PER_MESSAGE - reserved_terminal_slot
        and conversation_activities.count()
        < MAX_ACTIVITIES_PER_CONVERSATION - reserved_terminal_slot
    )

    if attempt_sequence > (MAX_EVENT_RECEIPTS_PER_MESSAGE - reserved_terminal_slot):
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
        attempt_sequence=foundry.attempt_sequence,
    )
    reply, created = AssistantReply.objects.get_or_create(
        message=message,
        defaults={
            "has_full_prefix": foundry.attempt_sequence == 1
            and current_execution is None
        },
    )
    if not created and current_generation != foundry.generation:
        raise ProjectionConflict("reply attempt cannot change after projection")
    if envelope.event_type == "message.delta" and not reply.is_truncated:
        current_bytes = len(reply.content.encode("utf-8"))
        text_bytes = len(text.encode("utf-8"))
        if current_bytes + text_bytes > ASSISTANT_REPLY_MAX_BYTES:
            reply.is_truncated = True
        else:
            reply.content += text
    reply.save(update_fields=("content", "is_truncated", "updated_at"))
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
    message.retry_allowed = (
        envelope.event_type == "execution.failed"
        and envelope.payload["retryable"] is True
    )
    if message.execution_claimed_at is None:
        message.execution_claimed_at = timezone.now()
    message.save(
        update_fields=(
            "status",
            "retry_allowed",
            "execution_claimed_at",
            "updated_at",
        )
    )
    if message_status in _TERMINAL_STATES:
        from chat.services.dispatch import _release_next_locked

        _release_next_locked(conversation, now=timezone.now())
    return ProjectionResult(
        status="applied",
        event_id=envelope.event_id,
        activity=activity,
        last_contiguous_sequence=foundry.attempt_sequence,
    )


def read_activity_snapshot(
    *,
    user,
    workspace_id: UUID | str,
    conversation_id: UUID | str,
    limit: int = 200,
    cursor: str | None = None,
    replay: bool = False,
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
    activity_query = Activity.objects.filter(conversation=conversation)
    oldest_sequence = (
        activity_query.order_by("sequence", "id")
        .values_list("sequence", flat=True)
        .first()
    )
    latest_sequence = (
        activity_query.order_by("-sequence", "-id")
        .values_list("sequence", flat=True)
        .first()
    )
    resume_cursor: str | None = None
    next_cursor: str | None = None
    retention_gap = False
    if replay:
        parsed_cursor = (
            parse_activity_cursor(cursor, conversation.id) if cursor else None
        )
        after_sequence = parsed_cursor.after_sequence if parsed_cursor else 0
        high_water_sequence = (
            parsed_cursor.high_water_sequence
            if parsed_cursor
            else (latest_sequence or 0)
        )
        if parsed_cursor and after_sequence >= high_water_sequence:
            high_water_sequence = max(after_sequence, latest_sequence or 0)

        expected_count = max(0, high_water_sequence - after_sequence)
        fixed_range_query = activity_query.filter(
            sequence__gt=after_sequence,
            sequence__lte=high_water_sequence,
        )
        if expected_count and fixed_range_query.count() != expected_count:
            retention_gap = True
            raise ProjectionCursorGap("activity cursor is no longer replayable")

        replay_rows = list(
            activity_query.filter(
                sequence__gt=after_sequence,
                sequence__lte=high_water_sequence,
            ).order_by("sequence", "id")[: limit + 1]
        )
        has_more = len(replay_rows) > limit
        rows = tuple(replay_rows[:limit])
        resume_after = rows[-1].sequence if rows else after_sequence
        resume_cursor = serialize_activity_cursor(
            conversation.id,
            resume_after,
            high_water_sequence,
        )
        if has_more:
            next_cursor = resume_cursor
    else:
        rows = tuple(activity_query.order_by("-sequence", "-id")[:limit])
        rows = tuple(reversed(rows))
    latest = (
        Message.objects.filter(
            conversation=conversation,
            sender=MessageSender.USER,
            origin=MessageOrigin.SEND,
            deleted_at__isnull=True,
        )
        .order_by("-sequence", "-id")
        .first()
    )
    active = (
        Message.objects.filter(
            conversation=conversation,
            sender=MessageSender.USER,
            origin=MessageOrigin.SEND,
            status__in=NONTERMINAL_MESSAGE_STATUSES,
            deleted_at__isnull=True,
            execution_claimed_at__isnull=False,
        )
        .order_by("sequence", "id")
        .first()
    )
    if (
        active is None
        and latest is not None
        and latest.status
        in {
            MessageLifecycle.IN_PROGRESS,
            MessageLifecycle.AWAITING_ACTION,
        }
    ):
        active = latest
    reply_message = active
    if (
        reply_message is None
        and latest is not None
        and latest.status in _TERMINAL_STATES
    ):
        reply_message = latest
    state = (
        ProjectionState.QUEUED
        if active is not None and active.status == MessageLifecycle.QUEUED
        else ProjectionState.RUNNING
        if active is not None and active.status == MessageLifecycle.IN_PROGRESS
        else active.status
        if active is not None
        else latest.status
        if latest is not None
        else ProjectionState.COMPLETED
    )
    last_contiguous = 0
    if reply_message is not None:
        latest_receipt = (
            FoundryEventReceipt.objects.filter(message=reply_message)
            .order_by("-generation", "-attempt_sequence")
            .first()
        )
        if latest_receipt is not None:
            last_contiguous = _last_contiguous(
                reply_message.id,
                latest_receipt.attempt_id,
                latest_receipt.generation,
            )
    return ActivitySnapshot(
        conversation,
        rows,
        state,
        last_contiguous,
        _last_contiguous_activity_sequence(activity_query),
        resume_cursor,
        next_cursor,
        oldest_sequence,
        latest_sequence,
        retention_gap,
        AssistantReply.objects.select_related("message")
        .filter(message=reply_message)
        .first(),
        active.id if active is not None else None,
    )


__all__ = [
    "ActivityCursor",
    "ActivitySnapshot",
    "ProjectionResult",
    "parse_activity_cursor",
    "project_foundry_event",
    "read_activity_snapshot",
    "serialize_activity_cursor",
]
