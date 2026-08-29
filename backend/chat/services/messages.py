from __future__ import annotations

import base64
import hashlib
import hmac
import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from allies.models import ProvisioningStatus
from auths.config import digest_key
from auths.models import User
from auths.throttle import (
    RateLimitReservation,
    ThrottleExceeded,
    ThrottleUnavailable,
    check_rate_limit,
    reconcile_rate_limit,
)
from chat.exceptions import (
    ChatUnavailable,
    ConversationUnavailable,
    CursorInvalid,
    IdempotencyConflict,
    MessageValidation,
    OnboardingHandoffRepairRequired,
    QueueFull,
    SendRateLimited,
    TurnConflict,
)
from chat.models import (
    MESSAGE_CONTENT_MAX_LENGTH,
    Conversation,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessageSender,
)
from common.uuids import canonical_uuid
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability


@dataclass(frozen=True, slots=True)
class MessageAcceptance:
    conversation: Conversation
    message: Message
    replayed: bool


@dataclass(frozen=True, slots=True)
class Cursor:
    conversation_id: str
    before_sequence: int
    expires_at: int
    key_id: str


def _parse_uuid(value: UUID | str) -> UUID:
    try:
        return canonical_uuid(value)
    except (TypeError, ValueError) as exc:
        raise ConversationUnavailable("conversation unavailable") from exc


def normalize_content(content: object) -> str:
    if not isinstance(content, str):
        raise MessageValidation("request validation failed")
    normalized = unicodedata.normalize("NFC", content).strip()
    if not normalized or len(normalized) > MESSAGE_CONTENT_MAX_LENGTH:
        raise MessageValidation("request validation failed")
    return normalized


def _validate_send_key(value: object) -> str:
    if not isinstance(value, str) or not 16 <= len(value) <= 128 or not value.strip():
        raise MessageValidation("request validation failed")
    return value


def _digest(value: str) -> str:
    return hmac.new(digest_key(), value.encode(), hashlib.sha256).hexdigest()


def _fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _bounded_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(getattr(settings, name, default))
    except (TypeError, ValueError) as exc:
        raise ChatUnavailable("chat unavailable") from exc
    if not minimum <= value <= maximum:
        raise ChatUnavailable("chat unavailable")
    return value


def _reservation_token(
    *, workspace_id: str, user_id: str, conversation_id: str, key_digest: str
) -> str:
    raw = f"{workspace_id}:{user_id}:{conversation_id}:{key_digest}"
    return hmac.new(digest_key(), raw.encode(), hashlib.sha256).hexdigest()


def enforce_send_rate_limit(
    *, user_id: str, workspace_id: str, reservation_key: str
) -> RateLimitReservation:
    limit = _bounded_setting("ALLIES_CHAT_SEND_RATE_LIMIT", 30, 1, 120)
    period = _bounded_setting("ALLIES_CHAT_SEND_RATE_PERIOD_SECONDS", 600, 60, 3600)
    try:
        reservation = check_rate_limit(
            scope="chat-send",
            identity=f"{workspace_id}:{user_id}",
            limit=limit,
            period=period,
            reservation_key=reservation_key,
        )
    except ThrottleExceeded as exc:
        raise SendRateLimited("send rate limited") from exc
    except (ThrottleUnavailable, ValueError) as exc:
        raise ChatUnavailable("chat unavailable") from exc
    if not isinstance(reservation, RateLimitReservation):
        raise ChatUnavailable("chat unavailable")
    return reservation


def _conversation_for_send(*, workspace, conversation_id: UUID | str) -> Conversation:
    parsed_conversation_id = _parse_uuid(conversation_id)
    try:
        return (
            Conversation.objects.select_for_update()
            .select_related("ally", "ally__workspace")
            .get(pk=parsed_conversation_id, ally__workspace=workspace)
        )
    except Conversation.DoesNotExist as exc:
        raise ConversationUnavailable("conversation unavailable") from exc


def accept_message(
    *,
    user: User,
    workspace_id: UUID | str,
    conversation_id: UUID | str,
    content: object,
    idempotency_key: object,
) -> MessageAcceptance:
    context = require_workspace_capability(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.WORKSPACE_WRITE,
    )
    normalized = normalize_content(content)
    key = _validate_send_key(idempotency_key)
    key_digest = _digest(key)
    content_fingerprint = _fingerprint(normalized)
    user_ref = str(user.id)
    workspace_ref = str(context.workspace.id)
    conversation_ref = str(_parse_uuid(conversation_id))
    reservation_key = _reservation_token(
        workspace_id=workspace_ref,
        user_id=user_ref,
        conversation_id=conversation_ref,
        key_digest=key_digest,
    )
    reservation: RateLimitReservation | None = None
    try:
        with transaction.atomic():
            conversation = _conversation_for_send(
                workspace=context.workspace, conversation_id=conversation_id
            )
            if (
                conversation.ally.provisioning_state
                == ProvisioningStatus.REPAIR_REQUIRED
            ):
                raise OnboardingHandoffRepairRequired("onboarding handoff needs repair")
            from .conversations import reconcile_onboarding_reply

            reconcile_onboarding_reply(ally=conversation.ally)
            duplicate = (
                Message.objects.filter(
                    conversation=conversation,
                    sender=MessageSender.USER,
                    origin=MessageOrigin.SEND,
                    send_key_digest=key_digest,
                )
                .order_by("id")
                .first()
            )
            if duplicate is not None:
                if duplicate.content_fingerprint != content_fingerprint:
                    raise IdempotencyConflict("idempotency key conflicts with content")
                from .dispatch import ensure_dispatch_after_accept

                ensure_dispatch_after_accept(duplicate)
                return MessageAcceptance(conversation, duplicate, True)

            if len(normalized.encode("utf-8")) > MESSAGE_CONTENT_MAX_LENGTH:
                raise MessageValidation("request validation failed")

            pending = Message.objects.filter(
                conversation=conversation,
                sender=MessageSender.USER,
                origin=MessageOrigin.SEND,
                status=MessageLifecycle.QUEUED,
            ).count()
            max_pending = _bounded_setting(
                "ALLIES_CHAT_MAX_PENDING_MESSAGES", 20, 1, 100
            )
            if pending >= max_pending:
                raise QueueFull("conversation queue full")

            reservation = enforce_send_rate_limit(
                user_id=user_ref,
                workspace_id=workspace_ref,
                reservation_key=reservation_key,
            )
            max_sequence = Message.objects.filter(conversation=conversation).aggregate(
                maximum=Max("sequence")
            )["maximum"]
            message = Message.objects.create(
                conversation=conversation,
                sequence=(max_sequence or 0) + 1,
                sender=MessageSender.USER,
                origin=MessageOrigin.SEND,
                content=normalized,
                status=MessageLifecycle.QUEUED,
                send_key_digest=key_digest,
                content_fingerprint=content_fingerprint,
            )
            from .dispatch import ensure_dispatch_after_accept

            ensure_dispatch_after_accept(message)
            return MessageAcceptance(conversation, message, False)
    except Exception:
        if reservation is not None:
            reconcile_rate_limit(reservation, committed=False)
        raise


def claim_next_turn(*, conversation_id: UUID | str) -> Message | None:
    parsed_conversation_id = _parse_uuid(conversation_id)
    with transaction.atomic():
        try:
            conversation = Conversation.objects.select_for_update().get(
                pk=parsed_conversation_id
            )
        except Conversation.DoesNotExist as exc:
            raise ConversationUnavailable("conversation unavailable") from exc
        if Message.objects.filter(
            conversation=conversation,
            sender=MessageSender.USER,
            origin=MessageOrigin.SEND,
            status=MessageLifecycle.IN_PROGRESS,
        ).exists():
            return None
        message = (
            Message.objects.select_for_update()
            .filter(
                conversation=conversation,
                sender=MessageSender.USER,
                origin=MessageOrigin.SEND,
                status=MessageLifecycle.QUEUED,
            )
            .order_by("sequence", "id")
            .first()
        )
        if message is None:
            return None
        message.status = MessageLifecycle.IN_PROGRESS
        message.save(update_fields=("status", "updated_at"))
        return message


def complete_turn(*, message_id: UUID | str, status: str) -> Message:
    terminal = {
        MessageLifecycle.COMPLETED,
        MessageLifecycle.FAILED,
        MessageLifecycle.STOPPED,
    }
    if status not in terminal:
        raise TurnConflict("invalid terminal status")
    parsed_message_id = _parse_uuid(message_id)
    try:
        existing = Message.objects.only("id", "conversation_id").get(
            pk=parsed_message_id
        )
    except Message.DoesNotExist as exc:
        raise ConversationUnavailable("conversation unavailable") from exc
    with transaction.atomic():
        try:
            Conversation.objects.select_for_update().get(pk=existing.conversation_id)
        except Conversation.DoesNotExist as exc:
            raise ConversationUnavailable("conversation unavailable") from exc
        message = Message.objects.select_for_update().get(pk=existing.pk)
        if message.status in terminal:
            if message.status == status:
                return message
            raise TurnConflict("turn already completed differently")
        if (
            message.status != MessageLifecycle.IN_PROGRESS
            or message.sender != MessageSender.USER
            or message.origin != MessageOrigin.SEND
        ):
            raise TurnConflict("turn is not active")
        message.status = status
        message.save(update_fields=("status", "updated_at"))
        return message


def _key_config(value: object) -> dict[str, bytes]:
    if isinstance(value, Mapping):
        return {
            str(key): (item if isinstance(item, bytes) else str(item).encode())
            for key, item in value.items()
            if str(key) and item
        }
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = None
        if isinstance(parsed, Mapping):
            return _key_config(parsed)
    return {}


def _cursor_keys() -> tuple[str, dict[str, bytes]]:
    active_id = str(getattr(settings, "ALLIES_CHAT_CURSOR_ACTIVE_KEY_ID", "v1"))
    configured = _key_config(getattr(settings, "ALLIES_CHAT_CURSOR_KEYS", {}))
    active_value = getattr(settings, "ALLIES_CHAT_CURSOR_KEY", "")
    if active_id not in configured and active_value:
        configured[active_id] = (
            active_value
            if isinstance(active_value, bytes)
            else str(active_value).encode()
        )
    if active_id not in configured:
        configured[active_id] = digest_key()
    previous = _key_config(getattr(settings, "ALLIES_CHAT_CURSOR_PREVIOUS_KEYS", {}))
    configured = {**previous, **configured}
    return active_id, configured


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def serialize_cursor(
    conversation_id: UUID | str, before_sequence: int, now: datetime | None = None
) -> str:
    try:
        before_sequence = int(before_sequence)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CursorInvalid("invalid cursor") from exc
    try:
        conversation_id = str(_parse_uuid(conversation_id))
    except ConversationUnavailable as exc:
        raise CursorInvalid("invalid cursor") from exc
    if before_sequence < 1:
        raise CursorInvalid("invalid cursor")
    active_id, keys = _cursor_keys()
    key = keys.get(active_id)
    if not key:
        raise CursorInvalid("invalid cursor")
    ttl = _bounded_setting("ALLIES_CHAT_CURSOR_TTL_SECONDS", 3600, 1, 86_400)
    expires_at = int((now or timezone.now()).timestamp()) + ttl
    payload = {
        "v": 1,
        "kid": active_id,
        "c": conversation_id,
        "b": int(before_sequence),
        "e": expires_at,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(key, raw, hashlib.sha256).hexdigest()
    return f"{_b64encode(raw)}.{signature}"


def parse_cursor(
    cursor: str, conversation_id: UUID | str, now: datetime | None = None
) -> Cursor:
    try:
        conversation_id = str(_parse_uuid(conversation_id))
    except ConversationUnavailable:
        raise CursorInvalid("invalid cursor") from None
    try:
        encoded, signature = cursor.split(".", 1)
        raw = _b64decode(encoded)
        payload = json.loads(raw)
        key_id = str(payload["kid"])
        expected = hmac.new(_cursor_keys()[1][key_id], raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        if payload["v"] != 1 or payload["c"] != conversation_id:
            raise ValueError
        before_sequence = int(payload["b"])
        expires_at = int(payload["e"])
        if before_sequence < 1 or expires_at <= int(
            (now or timezone.now()).timestamp()
        ):
            raise ValueError
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        IndexError,
        OverflowError,
        UnicodeError,
    ):
        raise CursorInvalid("invalid cursor") from None
    return Cursor(conversation_id, before_sequence, expires_at, key_id)


def message_response(message: Message) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "sender": message.sender,
        "content": message.content,
        "sequence": message.sequence,
        "status": message.status,
        "created_at": message.created_at,
    }
