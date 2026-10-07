"""Validate and project authenticated Foundry events into Cloud activities."""

from __future__ import annotations

import binascii
import hashlib
import hmac
import json
import logging
from copy import copy
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Func, IntegerField, Max, Prefetch, Sum
from django.utils import timezone

from allies.gateways.contracts import MAX_TERMINAL_SEQUENCE, FoundryEventEnvelope
from allies.models import Ally, AllyBinding, AllyDeletionState, BindingStatus
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
from files.services.publication import sanitize_reply_file_links
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability

from ..exceptions import (
    ProjectionConflict,
    ProjectionCursorExpired,
    ProjectionCursorGap,
    ProjectionCursorInvalid,
    ProjectionError,
    ProjectionInvalid,
    ProjectionNotFound,
    ProjectionSequenceGap,
)
from ..models import (
    Activity,
    Approval,
    ApprovalDeliveryState,
    ApprovalStatus,
    FoundryEventReceipt,
    FoundryHeldEvent,
    ProjectionState,
)
from ..presentation import activity_text

logger = logging.getLogger("allies.activities")

MAX_ACTIVITY_SNAPSHOT = 1000
MAX_ACTIVITIES_PER_MESSAGE = 513
MAX_ACTIVITIES_PER_CONVERSATION = 8192
MAX_EVENT_RECEIPTS_PER_MESSAGE = MAX_TERMINAL_SEQUENCE
MAX_HELD_EVENTS_PER_MESSAGE = 512
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
    held: bool = False


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
            conversation__ally__deletion_state=AllyDeletionState.ACTIVE,
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
            "Needs your attention",
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
    if event_type == "execution.approval_resolved":
        return (
            ProjectionState.RUNNING,
            "approval_resolved",
            "",
            MessageLifecycle.IN_PROGRESS,
        )
    raise ProjectionInvalid("event type is not supported")


def _rich_approval_for_event(
    *, envelope: FoundryEventEnvelope, conversation: Conversation, message: Message
) -> Approval:
    payload = envelope.payload
    try:
        request_id = UUID(payload["approval_request_id"])
        expires_at = datetime.fromisoformat(payload["expires_at"])
    except (AttributeError, TypeError, ValueError, KeyError) as exc:
        raise ProjectionInvalid("approval payload is invalid") from exc
    existing = (
        Approval.objects.select_for_update()
        .filter(approval_request_id=request_id)
        .first()
    )
    if existing is not None:
        if (
            existing.workspace_id != envelope.scope.cloud_workspace_id
            or existing.ally_id != conversation.ally_id
            or existing.conversation_id != conversation.id
            or existing.message_id != message.id
            or existing.cloud_binding_id != envelope.cloud.cloud_binding_id
            or existing.execution_id != envelope.foundry.execution_id
            or existing.attempt_id != envelope.foundry.attempt_id
            or existing.generation != envelope.foundry.generation
            or existing.action_kind != payload["action_kind"]
            or existing.action_label != payload["action_label"]
            or existing.action_preview != payload["action_preview"]
            or existing.expires_at != expires_at
        ):
            raise ProjectionConflict("approval request conflicts with existing row")
        return existing
    try:
        return Approval.objects.create(
            workspace_id=envelope.scope.cloud_workspace_id,
            ally_id=conversation.ally_id,
            conversation=conversation,
            message=message,
            approval_request_id=request_id,
            cloud_binding_id=envelope.cloud.cloud_binding_id,
            execution_id=envelope.foundry.execution_id,
            attempt_id=envelope.foundry.attempt_id,
            generation=envelope.foundry.generation,
            attempt_sequence=envelope.foundry.attempt_sequence,
            action_kind=payload["action_kind"],
            action_label=payload["action_label"],
            action_preview=payload["action_preview"],
            requested_at=envelope.issued_at,
            expires_at=expires_at,
            status=ApprovalStatus.PENDING,
            delivery_state=ApprovalDeliveryState.PENDING,
        )
    except ValueError as exc:
        raise ProjectionInvalid("approval payload is invalid") from exc


def _resolve_approval_for_event(
    *, envelope: FoundryEventEnvelope, conversation: Conversation, message: Message
) -> None:
    # Import lazily to keep the projection module's existing dependency direction
    # while reusing the single timestamp reconciliation rule used by API reads
    # and delivery claims.
    from .approvals import _save_reconciliation

    payload = envelope.payload
    try:
        request_id = UUID(payload["approval_request_id"])
    except (TypeError, ValueError, KeyError) as exc:
        raise ProjectionInvalid("approval resolution payload is invalid") from exc
    approval = (
        Approval.objects.select_for_update()
        .filter(
            approval_request_id=request_id,
            workspace_id=envelope.scope.cloud_workspace_id,
            ally_id=conversation.ally_id,
            conversation=conversation,
            message=message,
            execution_id=envelope.foundry.execution_id,
            attempt_id=envelope.foundry.attempt_id,
            generation=envelope.foundry.generation,
        )
        .first()
    )
    if approval is None:
        raise ProjectionConflict("approval resolution is not bound to a request")
    previous_status = approval.status
    previous_decision = approval.decision
    _save_reconciliation(approval, now=timezone.now())
    outcome = payload["outcome"]
    if outcome in {"approved", "rejected"}:
        expected_decision = "approve" if outcome == "approved" else "reject"
        if (
            previous_decision != expected_decision
            or previous_status == ApprovalStatus.PENDING
        ):
            raise ProjectionConflict("approval resolution does not match decision")
        if approval.status == ApprovalStatus.OUTCOME_UNKNOWN:
            return
        if approval.status != ApprovalStatus.DECISION_RECORDED:
            raise ProjectionConflict("approval resolution is already terminal")
        approval.status = (
            ApprovalStatus.APPROVED
            if outcome == "approved"
            else ApprovalStatus.REJECTED
        )
        approval.delivery_state = ApprovalDeliveryState.DELIVERED
        approval.delivery_completed_at = timezone.now()
    elif outcome == "expired":
        if previous_status in {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.CANCELLED,
        }:
            raise ProjectionConflict("approval resolution is already terminal")
        if approval.status == ApprovalStatus.OUTCOME_UNKNOWN:
            return
        approval.status = ApprovalStatus.EXPIRED
        approval.delivery_state = ApprovalDeliveryState.CANCELLED
    elif previous_status in {
        ApprovalStatus.PENDING,
        ApprovalStatus.DECISION_RECORDED,
        ApprovalStatus.CANCELLED,
        ApprovalStatus.OUTCOME_UNKNOWN,
    }:
        if approval.status == ApprovalStatus.OUTCOME_UNKNOWN:
            return
        approval.status = ApprovalStatus.CANCELLED
        approval.delivery_state = ApprovalDeliveryState.CANCELLED
    else:
        raise ProjectionConflict("approval resolution is already terminal")
    approval.delivery_next_attempt_at = None
    approval.delivery_lease_expires_at = None
    approval.delivery_safe_error_code = ""
    approval.save(
        update_fields=(
            "status",
            "delivery_state",
            "delivery_completed_at",
            "delivery_next_attempt_at",
            "delivery_lease_expires_at",
            "delivery_safe_error_code",
            "updated_at",
        )
    )


def _cancel_live_approvals_for_terminal_event(
    *, envelope: FoundryEventEnvelope, conversation: Conversation, message: Message
) -> None:
    """Close actionable rows when an execution ends without a resolution event."""

    actionable = Approval.objects.filter(
        workspace_id=envelope.scope.cloud_workspace_id,
        ally_id=conversation.ally_id,
        conversation=conversation,
        message=message,
        execution_id=envelope.foundry.execution_id,
        attempt_id=envelope.foundry.attempt_id,
        generation=envelope.foundry.generation,
    )
    current = timezone.now()
    actionable.filter(status=ApprovalStatus.PENDING).update(
        status=ApprovalStatus.CANCELLED,
        delivery_state=ApprovalDeliveryState.CANCELLED,
        delivery_next_attempt_at=None,
        delivery_lease_expires_at=None,
        delivery_safe_error_code="execution_terminal",
        updated_at=current,
    )
    # A recorded decision may already have reached Foundry when the terminal
    # event arrives. Without a runtime acknowledgement it is unknowable, so
    # preserve that uncertainty instead of claiming cancellation.
    actionable.filter(status=ApprovalStatus.DECISION_RECORDED).update(
        status=ApprovalStatus.OUTCOME_UNKNOWN,
        delivery_state=ApprovalDeliveryState.CANCELLED,
        delivery_next_attempt_at=None,
        delivery_lease_expires_at=None,
        delivery_safe_error_code="execution_terminal_ack_missing",
        updated_at=current,
    )


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
    """Apply one validated event, then any held successors it unblocks.

    Foundry may deliver an attempt's events in any order.  An event ahead of
    the contiguous cursor is accepted and held; it is projected once every
    earlier sequence has been applied.
    """

    result = _apply_foundry_event(envelope)
    if result.status == "applied" and not result.held:
        _drain_held_events(envelope, result.last_contiguous_sequence)
    return result


def _drain_held_events(envelope: FoundryEventEnvelope, applied_sequence: int) -> None:
    foundry = envelope.foundry
    FoundryHeldEvent.objects.filter(
        message_id=envelope.cloud.message_id,
        attempt_id=foundry.attempt_id,
        generation=foundry.generation,
        attempt_sequence__lte=applied_sequence,
    ).delete()
    while True:
        held = (
            FoundryHeldEvent.objects.select_for_update()
            .filter(
                message_id=envelope.cloud.message_id,
                attempt_id=foundry.attempt_id,
                generation=foundry.generation,
                attempt_sequence=applied_sequence + 1,
            )
            .first()
        )
        if held is None:
            return
        try:
            with transaction.atomic():
                _apply_foundry_event(FoundryEventEnvelope.model_validate(held.envelope))
        except ProjectionSequenceGap:
            # Still blocked (e.g. a prior turn is open); keep it for a later drain.
            return
        except (ProjectionError, ValueError) as exc:
            held.delete()
            logger.warning(
                "held foundry event discarded message_id=%s attempt_id=%s "
                "generation=%d attempt_sequence=%d error=%s",
                held.message_id,
                held.attempt_id,
                held.generation,
                held.attempt_sequence,
                type(exc).__name__,
            )
            return
        held.delete()
        applied_sequence = held.attempt_sequence


HELD_GAP_TIMEOUT_SECONDS = 15 * 60


def expire_stalled_held_gaps(*, limit: int = 50, now: datetime | None = None) -> int:
    """Fail turns whose held events have waited too long for a lost predecessor.

    A gap that stays open means Foundry will not deliver the missing event, so
    the turn would otherwise stay in progress forever and block every later
    turn of the conversation.  The turn fails as retryable and the next turn
    is released.
    """

    observed_at = now or timezone.now()
    cutoff = observed_at - timedelta(seconds=HELD_GAP_TIMEOUT_SECONDS)
    message_ids = list(
        FoundryHeldEvent.objects.filter(created_at__lte=cutoff)
        .values_list("message_id", flat=True)
        .distinct()[:limit]
    )
    expired = 0
    for message_id in message_ids:
        with transaction.atomic():
            message = (
                Message.objects.select_related("conversation")
                .filter(pk=message_id)
                .first()
            )
            if message is None:
                continue
            conversation = Conversation.objects.select_for_update().get(
                pk=message.conversation_id
            )
            message = Message.objects.select_for_update().get(pk=message_id)
            current = (
                FoundryEventReceipt.objects.filter(message=message)
                .order_by("-generation")
                .values_list("attempt_id", "generation")
                .first()
            )
            held = FoundryHeldEvent.objects.filter(message=message)
            if current is None:
                # Nothing projected yet (the first event itself is missing):
                # the newest held attempt is the current one.
                current = (
                    held.order_by("-generation", "-created_at")
                    .values_list("attempt_id", "generation")
                    .first()
                )
            current_held = (
                held.filter(attempt_id=current[0], generation=current[1])
                if current is not None
                else held.none()
            )
            # Holds left by a superseded attempt can never drain; drop them
            # without touching the current attempt's turn.
            held.exclude(pk__in=current_held.values("pk")).filter(
                created_at__lte=cutoff
            ).delete()
            if message.status in _TERMINAL_STATES:
                held.delete()
                continue
            if not current_held.filter(created_at__lte=cutoff).exists():
                continue
            current_held.delete()
            message.status = MessageLifecycle.FAILED
            message.retry_allowed = True
            message.save(update_fields=("status", "retry_allowed", "updated_at"))
            Approval.objects.filter(
                message=message, status=ApprovalStatus.PENDING
            ).update(
                status=ApprovalStatus.CANCELLED,
                delivery_state=ApprovalDeliveryState.CANCELLED,
                delivery_next_attempt_at=None,
                delivery_lease_expires_at=None,
                delivery_safe_error_code="execution_terminal",
                updated_at=observed_at,
            )
            logger.warning(
                "turn failed on stalled foundry sequence gap "
                "conversation_id=%s message_id=%s",
                conversation.id,
                message.id,
            )
            from chat.services.dispatch import _release_next_locked

            _release_next_locked(conversation, now=observed_at)
            expired += 1
    return expired


def _hold_event(
    envelope: FoundryEventEnvelope, message: Message, expected_sequence: int
) -> ProjectionResult:
    foundry = envelope.foundry
    attempt_held = FoundryHeldEvent.objects.filter(
        message=message, attempt_id=foundry.attempt_id, generation=foundry.generation
    )
    if (
        not attempt_held.filter(attempt_sequence=foundry.attempt_sequence).exists()
        and attempt_held.count() >= MAX_HELD_EVENTS_PER_MESSAGE
    ):
        raise ProjectionSequenceGap("held event limit reached")
    held, _created = FoundryHeldEvent.objects.get_or_create(
        message=message,
        attempt_id=foundry.attempt_id,
        generation=foundry.generation,
        attempt_sequence=foundry.attempt_sequence,
        defaults={
            "event_id": envelope.event_id,
            "event_fingerprint": envelope.fingerprint,
            "envelope": envelope.model_dump(mode="json"),
        },
    )
    if (
        held.event_id != envelope.event_id
        or held.event_fingerprint != envelope.fingerprint
    ):
        raise ProjectionConflict("event sequence conflicts with held event")
    # Foundry's receipt contract only knows applied/duplicate; a held event is
    # durably accepted, so it is acknowledged as applied.
    return ProjectionResult(
        status="applied",
        event_id=envelope.event_id,
        last_contiguous_sequence=expected_sequence - 1,
        held=True,
    )


def _apply_foundry_event(envelope: FoundryEventEnvelope) -> ProjectionResult:
    """Apply one validated event, preserving exact duplicate/no-op semantics."""

    message = _message_for_event(envelope)
    try:
        Ally.objects.select_for_update().get(
            pk=message.conversation.ally_id,
            deletion_state=AllyDeletionState.ACTIVE,
        )
        conversation = Conversation.objects.select_for_update().get(
            pk=message.conversation_id,
            ally__deletion_state=AllyDeletionState.ACTIVE,
        )
    except Ally.DoesNotExist as exc:
        raise ProjectionNotFound("projection unavailable") from exc
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
        logger.warning(
            "foundry event held for prior open turn "
            "conversation_id=%s message_id=%s execution_id=%s "
            "attempt_id=%s generation=%d attempt_sequence=%d",
            conversation.id,
            message.id,
            foundry.execution_id,
            foundry.attempt_id,
            foundry.generation,
            foundry.attempt_sequence,
            extra={
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "execution_id": str(foundry.execution_id),
                "attempt_id": str(foundry.attempt_id),
                "generation": foundry.generation,
                "attempt_sequence": foundry.attempt_sequence,
            },
        )
        raise ProjectionSequenceGap("prior conversation turn is not terminal")
    expected_sequence = (
        _last_contiguous(message.id, foundry.attempt_id, foundry.generation) + 1
    )
    if foundry.attempt_sequence > expected_sequence:
        logger.warning(
            "foundry event held for sequence gap "
            "conversation_id=%s message_id=%s execution_id=%s "
            "attempt_id=%s generation=%d expected_sequence=%d attempt_sequence=%d",
            conversation.id,
            message.id,
            foundry.execution_id,
            foundry.attempt_id,
            foundry.generation,
            expected_sequence,
            foundry.attempt_sequence,
            extra={
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "execution_id": str(foundry.execution_id),
                "attempt_id": str(foundry.attempt_id),
                "generation": foundry.generation,
                "expected_sequence": expected_sequence,
                "attempt_sequence": foundry.attempt_sequence,
            },
        )
        return _hold_event(envelope, message, expected_sequence)
    if foundry.attempt_sequence < expected_sequence:
        raise ProjectionConflict("event sequence is stale")
    if message.status in _TERMINAL_STATES:
        raise ProjectionConflict("terminal message cannot accept another event")

    state, kind, default_text, message_status = _event_state(envelope.event_type)
    approval = None
    if envelope.event_type == "execution.awaiting_action" and set(envelope.payload) != {
        "action_kind"
    }:
        approval = _rich_approval_for_event(
            envelope=envelope, conversation=conversation, message=message
        )
        default_text = "Waiting for your approval"
    elif envelope.event_type == "execution.approval_resolved":
        _resolve_approval_for_event(
            envelope=envelope, conversation=conversation, message=message
        )
    elif envelope.event_type in {
        "execution.completed",
        "execution.stopped",
        "execution.failed",
    }:
        _cancel_live_approvals_for_terminal_event(
            envelope=envelope, conversation=conversation, message=message
        )
    text = (
        str(envelope.payload.get("text", default_text))
        if envelope.event_type == "message.delta"
        else default_text
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
    reply_text = ""
    pending = reply.pending_file_reference
    if envelope.event_type == "message.delta":
        text, pending = sanitize_reply_file_links(
            message_id=message.id,
            binding_id=envelope.cloud.cloud_binding_id,
            text=text,
            pending=pending,
            prior_context=reply.content[-1:],
        )
        reply_text = text
    elif message_status in _TERMINAL_STATES and pending:
        reply_text, pending = sanitize_reply_file_links(
            message_id=message.id,
            binding_id=envelope.cloud.cloud_binding_id,
            text="",
            pending=pending,
            prior_context=reply.content[-1:],
            final=True,
        )
    activity_id = envelope.payload.get("activity_id")
    activity_kind = envelope.payload.get("activity_kind")
    outcome = envelope.payload.get("status") if activity_id else None
    duplicate_activity = False
    if activity_id:
        text = activity_text(
            activity_kind, outcome, envelope.payload.get("activity_subject")
        )
        prior = FoundryEventReceipt.objects.filter(
            message=message, attempt_id=foundry.attempt_id, activity_id=activity_id
        )
        duplicate_activity = prior.filter(outcome__isnull=False).exists()
        if envelope.event_type == "activity.started":
            duplicate_activity = duplicate_activity or prior.exists()
        elif prior.exclude(activity_kind=activity_kind).exists():
            duplicate_activity = True
    visible_activity_allowed = _ensure_projection_bounds(
        message=message,
        conversation=conversation,
        text=text,
        terminal=message_status in _TERMINAL_STATES,
        attempt_sequence=foundry.attempt_sequence,
    )
    if envelope.event_type == "execution.approval_resolved":
        visible_activity_allowed = False
    visible_activity_allowed = visible_activity_allowed and not duplicate_activity
    if reply_text and not reply.is_truncated:
        current_bytes = len(reply.content.encode("utf-8"))
        text_bytes = len(reply_text.encode("utf-8"))
        if current_bytes + text_bytes > ASSISTANT_REPLY_MAX_BYTES:
            reply.is_truncated = True
            pending = ""
        else:
            reply.content += reply_text
    if reply.is_truncated:
        pending = ""
    reply.pending_file_reference = pending
    reply.save(
        update_fields=(
            "content",
            "is_truncated",
            "pending_file_reference",
            "updated_at",
        )
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
            approval=approval,
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
            activity_id=activity_id,
            activity_kind=activity_kind,
            outcome=outcome,
            duration_ms=envelope.payload.get("duration_ms") if activity_id else None,
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
        activity_id=activity_id if not duplicate_activity else None,
        activity_kind=activity_kind if not duplicate_activity else None,
        outcome=outcome if not duplicate_activity else None,
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
    from notifications.services import notify_approval, notify_reply

    if approval is not None:
        notify_approval(approval)
    if envelope.event_type == "execution.completed":
        notify_reply(reply)
    if message_status in _TERMINAL_STATES:
        from chat.services.dispatch import _release_next_locked
        from model_keys.services import note_execution_outcome

        _release_next_locked(conversation, now=timezone.now())
        note_execution_outcome(
            ally_id=conversation.ally_id,
            event_type=envelope.event_type,
            reason=envelope.payload.get("reason"),
            message_created_at=message.created_at,
        )
    return ProjectionResult(
        status="applied",
        event_id=envelope.event_id,
        activity=activity,
        last_contiguous_sequence=foundry.attempt_sequence,
    )


def _recent_turns_floor(activity_query, conversation, recent_messages: int) -> int:
    cutoff = (
        Message.objects.filter(conversation=conversation, deleted_at__isnull=True)
        .order_by("-sequence", "-id")
        .values_list("sequence", flat=True)[recent_messages - 1 : recent_messages]
        .first()
    )
    if cutoff is None:
        return 0
    first = (
        activity_query.filter(conversation_turn_ordinal__gte=cutoff)
        .order_by("sequence", "id")
        .values_list("sequence", flat=True)
        .first()
    )
    return 0 if first is None else first - 1


def compact_assistant_deltas(rows: tuple[Activity, ...]) -> tuple[Activity, ...]:
    """Merge each run of adjacent stream deltas into one row.

    A streamed reply is stored as hundreds of tiny deltas. Replay only needs
    their concatenated text, so a run collapses to its last row carrying the
    joined text and ``first_sequence``, the first sequence it covers. Only
    finished turns compact: a live turn's deltas may already have reached the
    client over the stream, and a merged row cannot be split.
    """
    compacted: list[Activity] = []
    for row in rows:
        previous = compacted[-1] if compacted else None
        if (
            previous is not None
            and row.kind == previous.kind == "assistant_delta"
            and row.message.status in _TERMINAL_STATES
            and row.sequence == previous.sequence + 1
            and row.message_id == previous.message_id
            and row.attempt_id == previous.attempt_id
            and row.generation == previous.generation
        ):
            merged = copy(row)
            merged.text = previous.text + row.text
            merged.first_sequence = getattr(previous, "first_sequence", previous.sequence)
            compacted[-1] = merged
        else:
            compacted.append(row)
    return tuple(compacted)


def read_activity_snapshot(
    *,
    user,
    workspace_id: UUID | str,
    conversation_id: UUID | str,
    limit: int = 200,
    cursor: str | None = None,
    replay: bool = False,
    recent_messages: int | None = None,
    compact: bool = False,
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
        .filter(ally__deletion_state=AllyDeletionState.ACTIVE)
        .first()
    )
    if conversation is None:
        raise ProjectionNotFound("projection unavailable")
    from .approvals import reconcile_conversation_approvals

    reconcile_conversation_approvals(conversation.id)
    activity_query = Activity.objects.filter(conversation=conversation).select_related(
        "approval", "message"
    )
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
        if parsed_cursor is None and recent_messages:
            # Opening a chat only needs activity for the turns it displays.
            after_sequence = _recent_turns_floor(
                activity_query, conversation, recent_messages
            )
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
        if compact:
            rows = compact_assistant_deltas(rows)
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
    from files.models import FilePublication, FileVersion

    publications = Prefetch(
        "message__file_publications",
        queryset=FilePublication.objects.prefetch_related(
            Prefetch(
                "files",
                queryset=FileVersion.objects.order_by("created_at", "id"),
                to_attr="prefetched_files",
            )
        ),
        to_attr="prefetched_file_publications",
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
        .prefetch_related(publications)
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
