from __future__ import annotations

import hashlib
import hmac
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from allies.models import Ally, AllyDeletionState, ProvisioningStatus
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
    MessageNotDeletable,
    MessageValidation,
    OnboardingHandoffRepairRequired,
    QueueFull,
    SendRateLimited,
    TurnConflict,
)
from chat.models import (
    MESSAGE_CONTENT_MAX_LENGTH,
    NONTERMINAL_MESSAGE_STATUSES,
    TERMINAL_MESSAGE_STATUSES,
    AssistantReply,
    Conversation,
    DispatchOutbox,
    DispatchState,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessagePreparation,
    MessageSender,
)
from common.cursors import b64decode, b64encode, cursor_keys
from common.uuids import canonical_uuid
from files.models import FileAllyTombstone
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


def normalize_content(content: object, *, allow_empty: bool = False) -> str:
    if not isinstance(content, str):
        raise MessageValidation("request validation failed")
    normalized = unicodedata.normalize("NFC", content).strip()
    if (not normalized and not allow_empty) or len(
        normalized
    ) > MESSAGE_CONTENT_MAX_LENGTH:
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


def _normalize_routine_action(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    try:
        from chat.api.schemas import RoutineMessageAction

        parsed = (
            value
            if isinstance(value, RoutineMessageAction)
            else RoutineMessageAction.model_validate(value)
        )
    except (TypeError, ValueError):
        raise MessageValidation("request validation failed") from None
    return parsed.model_dump(mode="json", exclude_none=True)


def _validate_routine_action_binding(
    *,
    action: dict[str, object] | None,
    conversation: Conversation,
    user: User,
) -> None:
    """Keep every structured action identity inside the caller's routine scope."""

    if action is None:
        return
    from activities.models import RoutineResultProjection
    from routines.models import Routine, RoutineApprovalProjection, RoutineRunSnapshot

    try:
        routine_id = canonical_uuid(action["routine_id"])
    except (KeyError, TypeError, ValueError):
        raise MessageValidation(
            "routine action is not bound to this conversation"
        ) from None

    routine = Routine.objects.filter(
        pk=routine_id,
        workspace_id=conversation.ally.workspace_id,
        owner_id=user.id,
        ally_id=conversation.ally_id,
        main_conversation_id=conversation.id,
    ).first()
    if routine is None:
        raise MessageValidation("routine action is not bound to this conversation")

    def _uuid_field(name: str) -> UUID | None:
        value = action.get(name)
        if value is None:
            return None
        try:
            return canonical_uuid(value)
        except (TypeError, ValueError):
            raise MessageValidation("request validation failed") from None

    run_id = _uuid_field("run_id")
    approval_id = _uuid_field("approval_id")
    approval_request_id = _uuid_field("approval_request_id")
    execution_id = _uuid_field("execution_id")
    attempt_id = _uuid_field("attempt_id")
    action_attempt_id = _uuid_field("action_attempt_id")
    generation = action.get("generation")

    scope = {
        "routine_id": routine.id,
        "workspace_id": conversation.ally.workspace_id,
        "owner_id": user.id,
        "ally_id": conversation.ally_id,
        "routine__main_conversation_id": conversation.id,
    }
    if run_id is not None:
        run_scope = {
            **scope,
            "pk": run_id,
            "main_conversation_id": conversation.id,
        }
        if not RoutineRunSnapshot.objects.filter(**run_scope).exists():
            raise MessageValidation("routine action is not bound to this conversation")

    approval_identity_present = any(
        value is not None
        for value in (approval_id, approval_request_id, action_attempt_id)
    )
    if approval_identity_present:
        approval_scope = {
            **scope,
            "run__main_conversation_id": conversation.id,
        }
        if approval_id is not None:
            approval_scope["pk"] = approval_id
        if approval_request_id is not None:
            approval_scope["approval_request_id"] = approval_request_id
        if run_id is not None:
            approval_scope["run_id"] = run_id
        if execution_id is not None:
            approval_scope["execution_id"] = execution_id
        if attempt_id is not None:
            approval_scope["attempt_id"] = attempt_id
        if action_attempt_id is not None:
            approval_scope["action_attempt_id"] = action_attempt_id
        if generation is not None:
            approval_scope["generation"] = generation
        if not RoutineApprovalProjection.objects.filter(**approval_scope).exists():
            raise MessageValidation("routine action is not bound to this conversation")
    elif any(value is not None for value in (execution_id, attempt_id, generation)):
        result_scope = {
            **scope,
            "main_conversation_id": conversation.id,
        }
        if run_id is not None:
            result_scope["run_id"] = run_id
        if execution_id is not None:
            result_scope["execution_id"] = execution_id
        if attempt_id is not None:
            result_scope["attempt_id"] = attempt_id
        if generation is not None:
            result_scope["generation"] = generation
        if not RoutineResultProjection.objects.filter(**result_scope).exists():
            raise MessageValidation("routine action is not bound to this conversation")


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
        ally_id = Conversation.objects.values_list("ally_id", flat=True).get(
            pk=parsed_conversation_id,
            ally__workspace=workspace,
            ally__deletion_state=AllyDeletionState.ACTIVE,
        )
        Ally.objects.select_for_update().get(
            pk=ally_id,
            workspace=workspace,
            deletion_state=AllyDeletionState.ACTIVE,
        )
        return (
            Conversation.objects.select_for_update(of=("self",))
            .select_related("ally", "ally__workspace")
            .get(
                pk=parsed_conversation_id,
                ally__workspace=workspace,
                ally__deletion_state=AllyDeletionState.ACTIVE,
            )
        )
    except (Ally.DoesNotExist, Conversation.DoesNotExist) as exc:
        raise ConversationUnavailable("conversation unavailable") from exc


def _file_retry_conversation(*, workspace, conversation_id: UUID | str) -> Conversation:
    parsed_conversation_id = _parse_uuid(conversation_id)
    try:
        ally_id = (
            Conversation.objects.only("ally_id")
            .get(pk=parsed_conversation_id, ally__workspace=workspace)
            .ally_id
        )
        ally = Ally.objects.select_for_update().get(pk=ally_id, workspace=workspace)
    except (Ally.DoesNotExist, Conversation.DoesNotExist) as exc:
        raise ConversationUnavailable("conversation unavailable") from exc
    if FileAllyTombstone.objects.filter(ally=ally).exists():
        raise ConversationUnavailable("conversation unavailable")
    return _conversation_for_send(
        workspace=workspace, conversation_id=parsed_conversation_id
    )


def _retry_file_ids(*, user: User, context, original: Message) -> tuple[UUID, ...]:
    from files.models import FileDirection, FileState, FileVersion, MessageFile

    links = list(
        MessageFile.objects.select_for_update()
        .filter(message=original, removed_at__isnull=True)
        .order_by("position", "id")
    )
    if not links:
        if original.preparation == MessagePreparation.NONE:
            return ()
        raise TurnConflict("message files are not retryable")
    if original.preparation != MessagePreparation.READY or not original.send_armed:
        raise TurnConflict("message files are not retryable")

    files = (
        FileVersion.objects.select_for_update(of=("self",))
        .filter(pk__in=[link.file_id for link in links])
        .order_by("id")
    )
    by_id = {file.id: file for file in files}
    for link in links:
        file = by_id.get(link.file_id)
        if (
            file is None
            or file.owner_id != user.id
            or file.workspace_id != context.workspace.id
            or file.ally_id != original.conversation.ally_id
            or file.source_message_id != original.id
            or file.direction != FileDirection.INBOUND
            or file.state != FileState.READY
            or file.generation < 1
            or file.actual_size != file.expected_size
            or not file.object_key
        ):
            raise TurnConflict("message files are not retryable")
    return tuple(link.file_id for link in links)


def _claim_next_turn_locked(
    *, conversation: Conversation, now: datetime | None = None
) -> Message | None:
    """Claim the earliest live send while the caller holds Conversation."""

    if (
        conversation.ally.deletion_state != AllyDeletionState.ACTIVE
        or FileAllyTombstone.objects.filter(ally_id=conversation.ally_id).exists()
    ):
        return None
    if Message.objects.filter(
        conversation=conversation,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        status__in=NONTERMINAL_MESSAGE_STATUSES,
        deleted_at__isnull=True,
        execution_claimed_at__isnull=False,
    ).exists():
        return None
    message = (
        Message.objects.select_for_update()
        .filter(
            conversation=conversation,
            sender=MessageSender.USER,
            origin=MessageOrigin.SEND,
            status__in=NONTERMINAL_MESSAGE_STATUSES,
            deleted_at__isnull=True,
            execution_claimed_at__isnull=True,
        )
        .order_by("sequence", "id")
        .first()
    )
    if message is None:
        return None
    if message.preparation == MessagePreparation.NONE:
        pass
    elif message.preparation == MessagePreparation.READY and message.send_armed:
        if not bool(getattr(settings, "ALLIES_FILE_INPUT_DELIVERY_ENABLED", False)):
            return None
    else:
        return None
    message.execution_claimed_at = now or timezone.now()
    message.save(update_fields=("execution_claimed_at", "updated_at"))
    return message


def accept_message(
    *,
    user: User,
    workspace_id: UUID | str,
    conversation_id: UUID | str,
    content: object,
    idempotency_key: object,
    retry_of: Message | None = None,
    retry_file_ids: tuple[UUID, ...] = (),
    client_timezone: str = "",
    routine_action: object = None,
) -> MessageAcceptance:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        if client_timezone:
            ZoneInfo(client_timezone)
    except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
        raise MessageValidation("invalid timezone") from exc
    context = require_workspace_capability(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.WORKSPACE_WRITE,
    )
    normalized = normalize_content(content, allow_empty=bool(retry_file_ids))
    normalized_routine_action = _normalize_routine_action(routine_action)
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
                if (
                    duplicate.content_fingerprint != content_fingerprint
                    or duplicate.retry_of_id != (retry_of.id if retry_of else None)
                ):
                    raise IdempotencyConflict("idempotency key conflicts with content")
                if (
                    duplicate.client_timezone != client_timezone
                    or duplicate.routine_action != normalized_routine_action
                ):
                    raise IdempotencyConflict(
                        "idempotency key conflicts with request metadata"
                    )
                from .dispatch import ensure_dispatch_after_accept

                ensure_dispatch_after_accept(duplicate)
                return MessageAcceptance(conversation, duplicate, True)

            _validate_routine_action_binding(
                action=normalized_routine_action,
                conversation=conversation,
                user=user,
            )

            if len(normalized.encode("utf-8")) > MESSAGE_CONTENT_MAX_LENGTH:
                raise MessageValidation("request validation failed")

            live_count = Message.objects.filter(
                conversation=conversation,
                sender=MessageSender.USER,
                origin=MessageOrigin.SEND,
                status__in=NONTERMINAL_MESSAGE_STATUSES,
                deleted_at__isnull=True,
            ).count()
            max_pending = _bounded_setting(
                "ALLIES_CHAT_MAX_PENDING_MESSAGES", 20, 1, 100
            )
            queue_admission_enabled = bool(
                getattr(settings, "ALLIES_CHAT_QUEUE_ADMISSION_ENABLED", True)
            )
            if (not queue_admission_enabled and live_count) or (
                queue_admission_enabled and live_count >= max_pending + 1
            ):
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
                retry_of=retry_of,
                preparation=(
                    MessagePreparation.READY
                    if retry_file_ids
                    else MessagePreparation.NONE
                ),
                preparation_revision=1 if retry_file_ids else 0,
                send_armed=bool(retry_file_ids),
                client_timezone=client_timezone,
                routine_action=normalized_routine_action,
            )
            if retry_file_ids:
                from files.models import MessageFile

                MessageFile.objects.bulk_create(
                    [
                        MessageFile(message=message, file_id=file_id, position=index)
                        for index, file_id in enumerate(retry_file_ids)
                    ]
                )
            from .dispatch import ensure_dispatch_after_accept

            ensure_dispatch_after_accept(message)
            return MessageAcceptance(conversation, message, False)
    except Exception:
        if reservation is not None:
            reconcile_rate_limit(reservation, committed=False)
        raise


def retry_message(
    *,
    user: User,
    workspace_id: UUID | str,
    conversation_id: UUID | str,
    message_id: UUID | str,
    idempotency_key: object,
) -> MessageAcceptance:
    """Create a new send turn only after an explicitly retryable failure."""
    context = require_workspace_capability(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.WORKSPACE_WRITE,
    )
    parsed_message_id = _parse_uuid(message_id)
    with transaction.atomic():
        conversation = _file_retry_conversation(
            workspace=context.workspace, conversation_id=conversation_id
        )
        try:
            original = (
                Message.objects.select_for_update()
                .select_related("conversation")
                .get(pk=parsed_message_id, conversation=conversation)
            )
        except Message.DoesNotExist as exc:
            raise ConversationUnavailable("conversation unavailable") from exc
        retry_key_digest = _digest(_validate_send_key(idempotency_key))
        previous_retry = (
            Message.objects.filter(retry_of=original, send_key_digest=retry_key_digest)
            .order_by("id")
            .first()
        )
        if previous_retry is not None:
            from .dispatch import ensure_dispatch_after_accept

            ensure_dispatch_after_accept(previous_retry)
            return MessageAcceptance(conversation, previous_retry, True)
        conflicting_send = (
            Message.objects.filter(
                conversation=conversation,
                sender=MessageSender.USER,
                origin=MessageOrigin.SEND,
                send_key_digest=retry_key_digest,
            )
            .exclude(retry_of=original)
            .order_by("id")
            .first()
        )
        if conflicting_send is not None:
            raise IdempotencyConflict("idempotency key conflicts with another message")
        retryable = is_message_retryable(original)
        if (
            original.sender != MessageSender.USER
            or original.origin != MessageOrigin.SEND
            or not retryable
        ):
            raise TurnConflict("message is not retryable")
        retry_file_ids = _retry_file_ids(user=user, context=context, original=original)
        return accept_message(
            user=user,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            content=original.content,
            idempotency_key=idempotency_key,
            retry_of=original,
            retry_file_ids=retry_file_ids,
            client_timezone=original.client_timezone,
            routine_action=original.routine_action,
        )


def claim_next_turn(*, conversation_id: UUID | str) -> Message | None:
    parsed_conversation_id = _parse_uuid(conversation_id)
    with transaction.atomic():
        try:
            ally_id = Conversation.objects.values_list("ally_id", flat=True).get(
                pk=parsed_conversation_id,
                ally__deletion_state=AllyDeletionState.ACTIVE,
            )
            Ally.objects.select_for_update().get(
                pk=ally_id, deletion_state=AllyDeletionState.ACTIVE
            )
            conversation = (
                Conversation.objects.select_for_update(of=("self",))
                .select_related("ally")
                .get(
                    pk=parsed_conversation_id,
                    ally__deletion_state=AllyDeletionState.ACTIVE,
                )
            )
        except (Ally.DoesNotExist, Conversation.DoesNotExist) as exc:
            raise ConversationUnavailable("conversation unavailable") from exc
        message = _claim_next_turn_locked(conversation=conversation)
        if message is not None:
            from .dispatch import ensure_dispatch_after_accept

            ensure_dispatch_after_accept(message)
        return message


def delete_queued_message(
    *,
    user: User,
    workspace_id: UUID | str,
    conversation_id: UUID | str,
    message_id: UUID | str,
) -> Message:
    """Redact one unclaimed queued send while retaining its idempotency row."""

    context = require_workspace_capability(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.WORKSPACE_WRITE,
    )
    parsed_message_id = _parse_uuid(message_id)
    with transaction.atomic():
        conversation = _conversation_for_send(
            workspace=context.workspace, conversation_id=conversation_id
        )
        try:
            message = Message.objects.select_for_update().get(
                pk=parsed_message_id, conversation=conversation
            )
        except Message.DoesNotExist as exc:
            raise ConversationUnavailable("conversation unavailable") from exc
        if message.deleted_at is not None:
            return message
        if (
            message.sender != MessageSender.USER
            or message.origin != MessageOrigin.SEND
            or message.status != MessageLifecycle.QUEUED
            or message.execution_claimed_at is not None
        ):
            raise MessageNotDeletable("message is not deletable")

        now = timezone.now()
        message.content = ""
        message.status = MessageLifecycle.STOPPED
        message.retry_allowed = False
        message.deleted_at = now
        message.save(
            update_fields=(
                "content",
                "status",
                "retry_allowed",
                "deleted_at",
                "updated_at",
            )
        )
        outbox = (
            DispatchOutbox.objects.select_for_update().filter(message=message).first()
        )
        if outbox is not None:
            outbox.status = DispatchState.FAILED
            outbox.safe_error_code = "message_deleted"
            outbox.command_bytes = b""
            outbox.command_byte_length = 0
            outbox.next_attempt_at = None
            outbox.lease_expires_at = None
            outbox.completed_at = now
            outbox.save(
                update_fields=(
                    "status",
                    "safe_error_code",
                    "command_bytes",
                    "command_byte_length",
                    "next_attempt_at",
                    "lease_expires_at",
                    "completed_at",
                    "updated_at",
                )
            )
        return message


def complete_turn(*, message_id: UUID | str, status: str) -> Message:
    terminal = set(TERMINAL_MESSAGE_STATUSES)
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
            ally_id = Conversation.objects.values_list("ally_id", flat=True).get(
                pk=existing.conversation_id,
                ally__deletion_state=AllyDeletionState.ACTIVE,
            )
            Ally.objects.select_for_update().get(
                pk=ally_id, deletion_state=AllyDeletionState.ACTIVE
            )
            conversation = (
                Conversation.objects.select_for_update(of=("self",))
                .select_related("ally")
                .get(
                    pk=existing.conversation_id,
                    ally__deletion_state=AllyDeletionState.ACTIVE,
                )
            )
        except (Ally.DoesNotExist, Conversation.DoesNotExist) as exc:
            raise ConversationUnavailable("conversation unavailable") from exc
        message = Message.objects.select_for_update().get(pk=existing.pk)
        if message.status in terminal:
            if message.status == status:
                return message
            raise TurnConflict("turn already completed differently")
        if (
            message.status not in NONTERMINAL_MESSAGE_STATUSES
            or message.sender != MessageSender.USER
            or message.origin != MessageOrigin.SEND
            or message.execution_claimed_at is None
            or message.deleted_at is not None
        ):
            raise TurnConflict("turn is not active")
        message.status = status
        message.save(update_fields=("status", "updated_at"))
        from .dispatch import _insert_pending_routine_context

        _insert_pending_routine_context(conversation, now=timezone.now())
        next_message = _claim_next_turn_locked(conversation=conversation)
        if next_message is not None:
            from .dispatch import ensure_dispatch_after_accept

            ensure_dispatch_after_accept(next_message)
        return message


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
    active_id, keys = cursor_keys()
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
    return f"{b64encode(raw)}.{signature}"


def parse_cursor(
    cursor: str, conversation_id: UUID | str, now: datetime | None = None
) -> Cursor:
    try:
        conversation_id = str(_parse_uuid(conversation_id))
    except ConversationUnavailable:
        raise CursorInvalid("invalid cursor") from None
    try:
        encoded, signature = cursor.split(".", 1)
        raw = b64decode(encoded)
        payload = json.loads(raw)
        key_id = str(payload["kid"])
        expected = hmac.new(cursor_keys()[1][key_id], raw, hashlib.sha256).hexdigest()
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
    queue_state = None
    if (
        message.sender == MessageSender.USER
        and message.origin == MessageOrigin.SEND
        and message.status in NONTERMINAL_MESSAGE_STATUSES
        and message.deleted_at is None
    ):
        queue_state = (
            "claimed" if message.execution_claimed_at is not None else "unclaimed"
        )
    files = []
    if message.preparation != MessagePreparation.NONE and message.deleted_at is None:
        files = [
            {
                "id": str(link.file_id),
                "name": link.file.original_name,
                "size": link.file.actual_size or link.file.expected_size,
                "state": link.file.state,
            }
            for link in message.file_links.all()
            if link.removed_at is None
        ]
    return {
        "id": str(message.id),
        "sender": message.sender,
        "content": message.content,
        "sequence": message.sequence,
        "status": message.status,
        "created_at": message.created_at,
        "retryable": is_message_retryable(message),
        "queue_state": queue_state,
        "deleted_at": message.deleted_at,
        "preparation": message.preparation,
        "revision": message.preparation_revision,
        "files": files,
    }


def assistant_reply_response(
    reply: AssistantReply, *, message: Message | None = None
) -> dict[str, Any]:
    source = message or reply.message
    from files.services.publication import reply_publications

    return {
        "id": str(reply.id),
        "source_message_id": str(source.id),
        "conversation_turn_ordinal": source.sequence,
        "content": reply.content,
        "status": source.status,
        "has_full_prefix": reply.has_full_prefix,
        "is_truncated": reply.is_truncated,
        "publications": reply_publications(message=source),
        "created_at": reply.created_at,
        "updated_at": reply.updated_at,
    }


def is_message_retryable(message: Message) -> bool:
    return (
        message.sender == MessageSender.USER
        and message.origin == MessageOrigin.SEND
        and message.status == MessageLifecycle.FAILED
        and message.retry_allowed
        and message.retry_of_id is None
        and not message.retries.exists()
    )
