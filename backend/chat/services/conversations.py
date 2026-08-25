from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from allies.models import Ally, OnboardingAttempt
from auths.models import User
from chat.exceptions import (
    ConversationUnavailable,
    CursorInvalid,
    OnboardingHandoffRepairRequired,
    OnboardingHandoffUnavailable,
)
from chat.models import (
    Conversation,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessageSender,
)
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability

from .messages import parse_cursor, serialize_cursor


@dataclass(frozen=True, slots=True)
class ConversationRead:
    conversation: Conversation
    messages: tuple[Message, ...]
    next_cursor: str | None


def _handoff_text(value: object) -> str:
    if not isinstance(value, str):
        raise OnboardingHandoffUnavailable("onboarding handoff unavailable")
    normalized = value.strip()
    if not normalized:
        raise OnboardingHandoffUnavailable("onboarding handoff unavailable")
    if len(normalized) > 4_000:
        raise OnboardingHandoffUnavailable("onboarding handoff unavailable")
    return normalized


def _validate_imported_history(
    conversation: Conversation, *, greeting: str | None = None, reply: str | None = None
) -> Conversation:
    rows = list(
        Message.objects.filter(conversation=conversation).order_by("sequence", "id")[:2]
    )
    if len(rows) < 2:
        raise OnboardingHandoffRepairRequired("onboarding handoff needs repair")
    expected = (
        (MessageSender.ASSISTANT, greeting or rows[0].content),
        (MessageSender.USER, reply or rows[1].content),
    )
    for row, (sender, content) in zip(rows[:2], expected, strict=True):
        if (
            row.sequence != (1 if sender == MessageSender.ASSISTANT else 2)
            or row.sender != sender
            or row.origin != MessageOrigin.ONBOARDING
            or row.status != MessageLifecycle.COMPLETED
            or row.send_key_digest
            or row.content_fingerprint
            or row.content != content
        ):
            raise OnboardingHandoffRepairRequired("onboarding handoff needs repair")
    return conversation


def ensure_default_conversation(
    *, ally: Ally, greeting: str, reply: str
) -> Conversation:
    """Create or validate the two imported onboarding rows under one Ally lock."""

    greeting = _handoff_text(greeting)
    reply = _handoff_text(reply)
    if not ally.pk:
        raise ConversationUnavailable("conversation unavailable")

    try:
        with transaction.atomic():
            locked_ally = Ally.objects.select_for_update().get(pk=ally.pk)
            conversation = (
                Conversation.objects.filter(ally=locked_ally, is_default=True)
                .order_by("id")
                .first()
            )
            if conversation is not None:
                return _validate_imported_history(
                    conversation, greeting=greeting, reply=reply
                )
            conversation = Conversation.objects.create(
                ally=locked_ally, is_default=True
            )
            Message.objects.bulk_create(
                [
                    Message(
                        conversation=conversation,
                        sequence=1,
                        sender=MessageSender.ASSISTANT,
                        origin=MessageOrigin.ONBOARDING,
                        content=greeting,
                        status=MessageLifecycle.COMPLETED,
                    ),
                    Message(
                        conversation=conversation,
                        sequence=2,
                        sender=MessageSender.USER,
                        origin=MessageOrigin.ONBOARDING,
                        content=reply,
                        status=MessageLifecycle.COMPLETED,
                    ),
                ]
            )
            return conversation
    except IntegrityError:
        # A PostgreSQL uniqueness race may win outside the row lock when the
        # caller supplied a stale Ally instance; the committed row is truth.
        conversation = (
            Conversation.objects.filter(ally_id=ally.pk, is_default=True)
            .order_by("id")
            .first()
        )
        if conversation is None:
            raise
        return _validate_imported_history(conversation, greeting=greeting, reply=reply)


def reconcile_ally_conversation(*, ally: Ally) -> Conversation:
    """Resolve the CLD-003 handoff without fabricating missing source text."""

    try:
        attempt = ally.onboarding_attempt
    except OnboardingAttempt.DoesNotExist as exc:
        raise OnboardingHandoffUnavailable("onboarding handoff unavailable") from exc
    if (
        attempt.ally_id != ally.pk
        or attempt.user_id is None
        or attempt.consumed_at is None
    ):
        raise OnboardingHandoffUnavailable("onboarding handoff unavailable")
    greeting = _handoff_text(attempt.greeting)
    reply = _handoff_text(attempt.reply)
    return ensure_default_conversation(ally=ally, greeting=greeting, reply=reply)


def _conversation_for_workspace(*, workspace, conversation_id: str) -> Conversation:
    try:
        return Conversation.objects.select_related("ally", "ally__workspace").get(
            public_id=conversation_id,
            ally__workspace=workspace,
        )
    except Conversation.DoesNotExist as exc:
        raise ConversationUnavailable("conversation unavailable") from exc


def _messages_page(
    *, conversation: Conversation, limit: int, cursor: str | None
) -> tuple[tuple[Message, ...], str | None]:
    if not 1 <= limit <= 100:
        raise CursorInvalid("invalid history limit")
    before_sequence: int | None = None
    if cursor:
        parsed = parse_cursor(cursor, conversation_id=conversation.public_id)
        before_sequence = parsed.before_sequence
    query: QuerySet[Message, Message] = Message.objects.filter(
        conversation=conversation
    )
    if before_sequence is not None:
        query = query.filter(sequence__lt=before_sequence)
    rows = list(query.order_by("-sequence", "-id")[: limit + 1])
    has_more = len(rows) > limit
    rows = rows[:limit]
    rows.reverse()
    next_cursor = None
    if has_more and rows:
        next_cursor = serialize_cursor(
            conversation_id=conversation.public_id,
            before_sequence=rows[0].sequence,
        )
    return tuple(rows), next_cursor


def retrieve_conversation(
    *,
    user: User,
    workspace_id: str,
    conversation_id: str | None = None,
    ally_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> ConversationRead:
    context = require_workspace_capability(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.PROFILE_READ,
    )
    if (conversation_id is None) == (ally_id is None):
        raise ConversationUnavailable("conversation unavailable")
    if conversation_id is not None:
        conversation = _conversation_for_workspace(
            workspace=context.workspace, conversation_id=conversation_id
        )
        # Existing conversations are checked, but no source text is fabricated.
        try:
            attempt = conversation.ally.onboarding_attempt
        except OnboardingAttempt.DoesNotExist:
            _validate_imported_history(conversation)
        else:
            _validate_imported_history(
                conversation,
                greeting=_handoff_text(attempt.greeting),
                reply=_handoff_text(attempt.reply),
            )
    else:
        try:
            ally = Ally.objects.select_related("workspace").get(
                public_id=ally_id, workspace=context.workspace
            )
        except Ally.DoesNotExist as exc:
            raise ConversationUnavailable("conversation unavailable") from exc
        conversation = (
            Conversation.objects.select_related("ally", "ally__workspace")
            .filter(ally=ally, is_default=True)
            .first()
        )
        if conversation is None:
            conversation = reconcile_ally_conversation(ally=ally)
        else:
            try:
                attempt = ally.onboarding_attempt
            except OnboardingAttempt.DoesNotExist:
                _validate_imported_history(conversation)
            else:
                _validate_imported_history(
                    conversation,
                    greeting=_handoff_text(attempt.greeting),
                    reply=_handoff_text(attempt.reply),
                )
    messages, next_cursor = _messages_page(
        conversation=conversation, limit=limit, cursor=cursor
    )
    return ConversationRead(conversation, messages, next_cursor)
