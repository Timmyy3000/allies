from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.db.models.functions import Coalesce, Length

from allies.models import Ally, AllyBinding, BindingStatus, OnboardingAttempt
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

from .messages import (
    _digest,
    _fingerprint,
    _parse_uuid,
    normalize_content,
    parse_cursor,
    serialize_cursor,
)


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
    greeting_row, reply_row = rows
    expected_greeting = _handoff_text(
        greeting if greeting is not None else greeting_row.content
    )
    expected_reply = _handoff_text(reply if reply is not None else reply_row.content)
    if (
        greeting_row.sequence != 1
        or greeting_row.sender != MessageSender.ASSISTANT
        or greeting_row.origin != MessageOrigin.ONBOARDING
        or greeting_row.status != MessageLifecycle.COMPLETED
        or greeting_row.send_key_digest
        or greeting_row.content_fingerprint
        or greeting_row.content != expected_greeting
    ):
        raise OnboardingHandoffRepairRequired("onboarding handoff needs repair")
    reply_is_preview = (
        reply_row.origin == MessageOrigin.ONBOARDING
        and reply_row.status == MessageLifecycle.COMPLETED
        and not reply_row.send_key_digest
        and not reply_row.content_fingerprint
    )
    reply_is_turn = (
        reply_row.origin == MessageOrigin.SEND
        and reply_row.status in MessageLifecycle.values
        and bool(reply_row.send_key_digest)
        and bool(reply_row.content_fingerprint)
    )
    if (
        reply_row.sequence != 2
        or reply_row.sender != MessageSender.USER
        or reply_row.content != expected_reply
        or not (reply_is_preview or reply_is_turn)
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


def activate_onboarding_reply(*, ally: Ally) -> Message:
    """Promote the retained onboarding reply into the first real conversation turn."""

    with transaction.atomic():
        conversation = (
            Conversation.objects.select_for_update()
            .filter(ally=ally, is_default=True)
            .order_by("id")
            .first()
        )
        if conversation is None:
            raise OnboardingHandoffUnavailable("onboarding handoff unavailable")
        try:
            attempt = ally.onboarding_attempt
        except OnboardingAttempt.DoesNotExist:
            expected_greeting = expected_reply = None
        else:
            expected_greeting = _handoff_text(attempt.greeting)
            expected_reply = _handoff_text(attempt.reply)
        _validate_imported_history(
            conversation,
            greeting=expected_greeting,
            reply=expected_reply,
        )
        try:
            message = Message.objects.select_for_update().get(
                conversation=conversation,
                sequence=2,
                sender=MessageSender.USER,
            )
        except Message.DoesNotExist as exc:
            raise OnboardingHandoffRepairRequired(
                "onboarding handoff needs repair"
            ) from exc
        if message.origin == MessageOrigin.ONBOARDING:
            content = normalize_content(message.content)
            message.origin = MessageOrigin.SEND
            message.content = content
            message.status = MessageLifecycle.QUEUED
            message.send_key_digest = _digest(f"onboarding-reply:{ally.pk}")
            message.content_fingerprint = _fingerprint(content)
            message.save(
                update_fields=(
                    "origin",
                    "content",
                    "status",
                    "send_key_digest",
                    "content_fingerprint",
                    "updated_at",
                )
            )
        elif message.origin != MessageOrigin.SEND:
            raise OnboardingHandoffRepairRequired("onboarding handoff needs repair")

        from .dispatch import ensure_dispatch_after_accept

        ensure_dispatch_after_accept(message)
        return message


def reconcile_onboarding_reply(*, ally: Ally) -> Message | None:
    """Repair a bound Ally whose retained onboarding reply was never promoted."""

    try:
        binding = AllyBinding.objects.only("status").get(ally_id=ally.pk)
    except AllyBinding.DoesNotExist:
        return None
    if binding.status != BindingStatus.BOUND:
        return None
    conversation = (
        Conversation.objects.filter(ally_id=ally.pk, is_default=True)
        .order_by("id")
        .first()
    )
    if conversation is None:
        return None
    reply = (
        Message.objects.filter(
            conversation=conversation,
            sequence=2,
            sender=MessageSender.USER,
        )
        .only("id", "origin", "status")
        .first()
    )
    if reply is None:
        return None
    if reply.origin == MessageOrigin.ONBOARDING:
        return activate_onboarding_reply(ally=ally)
    if reply.origin == MessageOrigin.SEND:
        if reply.status in {MessageLifecycle.QUEUED, MessageLifecycle.IN_PROGRESS}:
            from .dispatch import ensure_dispatch_after_accept

            ensure_dispatch_after_accept(reply)
        return reply
    raise OnboardingHandoffRepairRequired("onboarding handoff needs repair")


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


def _conversation_for_workspace(
    *, workspace, conversation_id: UUID | str
) -> Conversation:
    parsed_conversation_id = _parse_uuid(conversation_id)
    try:
        return Conversation.objects.select_related("ally", "ally__workspace").get(
            pk=parsed_conversation_id,
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
        parsed = parse_cursor(cursor, conversation_id=str(conversation.id))
        before_sequence = parsed.before_sequence
    query: QuerySet[Message, Message] = (
        Message.objects.filter(conversation=conversation)
        .select_related("dispatch_outbox", "assistant_reply")
        .prefetch_related("retries")
    )
    if before_sequence is not None:
        query = query.filter(sequence__lt=before_sequence)
    # Select lengths first to bound memory, always admitting one large turn.
    candidates = list(
        query.annotate(
            text_chars=Length("content")
            + Coalesce(Length("assistant_reply__content"), 0)
        )
        .order_by("-sequence", "-id")
        .values("id", "text_chars")[: limit + 1]
    )
    selected = []
    page_chars = 0
    for candidate in candidates[:limit]:
        if selected and page_chars + candidate["text_chars"] > 1024 * 1024:
            break
        selected.append(candidate["id"])
        page_chars += candidate["text_chars"]
    has_more = len(candidates) > len(selected)
    rows = list(query.filter(id__in=selected).order_by("sequence", "id"))
    next_cursor = None
    if has_more and rows:
        next_cursor = serialize_cursor(
            conversation_id=str(conversation.id),
            before_sequence=rows[0].sequence,
        )
    return tuple(rows), next_cursor


def retrieve_conversation(
    *,
    user: User,
    workspace_id: UUID | str,
    conversation_id: UUID | str | None = None,
    ally_id: UUID | str | None = None,
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
        reconcile_onboarding_reply(ally=conversation.ally)
    else:
        try:
            ally = Ally.objects.select_related("workspace").get(
                pk=_parse_uuid(ally_id), workspace=context.workspace
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
        reconcile_onboarding_reply(ally=conversation.ally)
    messages, next_cursor = _messages_page(
        conversation=conversation, limit=limit, cursor=cursor
    )
    return ConversationRead(conversation, messages, next_cursor)
