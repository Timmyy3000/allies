"""Durable preparation transitions for inbound file messages."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from allies.models import Ally, AllyDeletionState
from auths.models import User
from chat.models import (
    Conversation,
    DispatchOutbox,
    DispatchState,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessagePreparation,
    MessageSender,
)
from common.uuids import canonical_uuid
from files.exceptions import FileConflict, FileScopeUnavailable, FileValidation
from files.models import (
    FileAllyTombstone,
    FileDirection,
    FileDraftFile,
    FileDraftRecovery,
    FileStagingObject,
    FileState,
    FileVersion,
    MessageFile,
)
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability


@dataclass(frozen=True, slots=True)
class DraftRecovery:
    draft: FileDraftRecovery
    files: tuple[FileVersion, ...]


_FAILED_STATES = {
    FileState.CLEANUP_PENDING,
    FileState.DELETED,
    FileState.FAILED,
    FileState.REJECTED,
}

_RETRYABLE_STATES = {FileState.FAILED, FileState.REJECTED}


def _uuid(value) -> UUID:
    try:
        return canonical_uuid(value)
    except (TypeError, ValueError) as exc:
        raise FileScopeUnavailable("file unavailable") from exc


def _scope(*, user: User, workspace_id, conversation_id, message_id, context=None):
    context = context or require_workspace_capability(
        user=user, workspace_id=workspace_id, capability=Capability.WORKSPACE_WRITE
    )
    try:
        conversation_id = _uuid(conversation_id)
        ally_id = Conversation.objects.only("ally_id").get(pk=conversation_id).ally_id
        ally = Ally.objects.select_for_update().get(
            pk=ally_id,
            workspace=context.workspace,
            deletion_state=AllyDeletionState.ACTIVE,
        )
        conversation = Conversation.objects.select_for_update().get(
            pk=conversation_id, ally=ally
        )
        message = Message.objects.select_for_update().get(
            pk=_uuid(message_id), conversation=conversation
        )
    except (Ally.DoesNotExist, Conversation.DoesNotExist, Message.DoesNotExist) as exc:
        raise FileScopeUnavailable("file unavailable") from exc
    if FileAllyTombstone.objects.filter(ally=ally).exists():
        raise FileScopeUnavailable("file unavailable")
    return context, conversation, message


def _active_files(message: Message, *, lock: bool = False) -> list[FileVersion]:
    links = MessageFile.objects.filter(message=message, removed_at__isnull=True)
    if lock:
        links = links.select_for_update()
    file_ids = list(links.order_by("position", "id").values_list("file_id", flat=True))
    files = FileVersion.objects.select_related(
        "source_message__conversation__ally"
    ).filter(pk__in=file_ids)
    if lock:
        files = files.select_for_update(of=("self",))
    by_id = {file.id: file for file in files}
    return [by_id[file_id] for file_id in file_ids]


def _owned_file(*, user: User, context, message: Message, file: FileVersion) -> None:
    source = file.source_message
    if (
        file.owner_id != user.id
        or file.workspace_id != context.workspace.id
        or file.ally_id != message.conversation.ally_id
        or file.direction != FileDirection.INBOUND
        or source is None
        or source.conversation.ally_id != file.ally_id
        or source.conversation.ally.workspace_id != context.workspace.id
    ):
        raise FileScopeUnavailable("file unavailable")


def _owned_active_files(*, user: User, context, message: Message) -> list[FileVersion]:
    files = _active_files(message, lock=True)
    for file in files:
        _owned_file(user=user, context=context, message=message, file=file)
    return files


def _can_change(message: Message) -> None:
    if (
        message.deleted_at is not None
        or message.sender != MessageSender.USER
        or message.origin != MessageOrigin.SEND
        or message.status != MessageLifecycle.QUEUED
        or message.execution_claimed_at is not None
    ):
        raise FileConflict("file message cannot change")


def _set_preparation(message: Message, files: list[FileVersion]) -> bool:
    if any(file.state in _FAILED_STATES for file in files):
        preparation, armed = MessagePreparation.FAILED, False
    elif files and all(file.state == FileState.READY for file in files):
        preparation = MessagePreparation.READY
        armed = message.preparation_revision == 1
    else:
        preparation, armed = MessagePreparation.UPLOADING, False
    if message.preparation == preparation and message.send_armed == armed:
        return False
    message.preparation = preparation
    message.send_armed = armed
    message.save(update_fields=("preparation", "send_armed", "updated_at"))
    return armed


def reconcile_file_message(*, message_id) -> Message:
    """Recover one upload or inspection transition from durable file state."""

    with transaction.atomic():
        try:
            probe = Message.objects.only("id", "conversation_id").get(
                pk=_uuid(message_id)
            )
            conversation = Conversation.objects.select_for_update().get(
                pk=probe.conversation_id,
                ally__deletion_state=AllyDeletionState.ACTIVE,
            )
            message = Message.objects.select_for_update().get(
                pk=probe.pk, conversation=conversation
            )
        except (Message.DoesNotExist, Conversation.DoesNotExist) as exc:
            raise FileScopeUnavailable("file unavailable") from exc
        if message.preparation == MessagePreparation.READY:
            armed = message.send_armed
        elif message.preparation in {
            MessagePreparation.UPLOADING,
            MessagePreparation.FAILED,
        }:
            files = _active_files(message, lock=True)
            armed = bool(files) and _set_preparation(message, files)
        else:
            return message
    if armed:
        from chat.services.dispatch import ensure_dispatch_after_accept

        ensure_dispatch_after_accept(message)
    return message


def recover_file_preparation(*, limit: int = 20) -> int:
    bound = max(1, min(int(limit), 100))
    active_files = MessageFile.objects.filter(
        message_id=OuterRef("pk"), removed_at__isnull=True
    )
    actionable = Q(preparation=MessagePreparation.UPLOADING, has_failed=True) | Q(
        preparation__in=(MessagePreparation.UPLOADING, MessagePreparation.FAILED),
        has_files=True,
        has_unready=False,
    )
    if getattr(settings, "ALLIES_FILE_INPUT_DELIVERY_ENABLED", False):
        actionable |= Q(
            preparation=MessagePreparation.READY,
            send_armed=True,
            status=MessageLifecycle.QUEUED,
            execution_claimed_at__isnull=True,
            dispatch_outbox__isnull=True,
            has_files=True,
            has_unready=False,
        )
    ids = list(
        Message.objects.filter(
            deleted_at__isnull=True,
            conversation__ally__deletion_state=AllyDeletionState.ACTIVE,
        )
        .alias(
            has_files=Exists(active_files),
            has_failed=Exists(active_files.filter(file__state__in=_FAILED_STATES)),
            has_unready=Exists(active_files.exclude(file__state=FileState.READY)),
        )
        .filter(actionable)
        .order_by("created_at", "id")
        .values_list("id", flat=True)[:bound]
    )
    for message_id in ids:
        reconcile_file_message(message_id=message_id)
    return len(ids)


def retry_inbound_file(
    *, user: User, workspace_id, ally_id, file_id, generation: int
) -> FileVersion:
    context = require_workspace_capability(
        user=user, workspace_id=workspace_id, capability=Capability.WORKSPACE_WRITE
    )
    try:
        _message_id, conversation_id = (
            MessageFile.objects.filter(file_id=_uuid(file_id), removed_at__isnull=True)
            .values_list("message_id", "message__conversation_id")
            .get()
        )
    except (MessageFile.DoesNotExist, MessageFile.MultipleObjectsReturned) as exc:
        raise FileScopeUnavailable("file unavailable") from exc
    with transaction.atomic():
        from files.services.intake import _account_locked

        account = _account_locked(context.workspace)
        context, _conversation, message = _scope(
            user=user,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            message_id=_message_id,
            context=context,
        )
        _can_change(message)
        try:
            link = MessageFile.objects.select_for_update().get(
                message=message, file_id=_uuid(file_id), removed_at__isnull=True
            )
            file = (
                FileVersion.objects.select_related("source_message__conversation__ally")
                .select_for_update(of=("self",))
                .get(pk=link.file_id)
            )
        except (MessageFile.DoesNotExist, FileVersion.DoesNotExist) as exc:
            raise FileScopeUnavailable("file unavailable") from exc
        _owned_file(user=user, context=context, message=message, file=file)
        if file.ally_id != _uuid(ally_id):
            raise FileScopeUnavailable("file unavailable")
        if file.generation == generation + 1 and file.state not in {
            FileState.CLEANUP_PENDING,
            FileState.DELETED,
        }:
            return file
        if file.state in {FileState.CLEANUP_PENDING, FileState.DELETED}:
            raise FileConflict("file cleanup is pending")
        if file.generation != generation or file.state not in _RETRYABLE_STATES:
            raise FileConflict("file retry conflicts")
        staging = list(
            FileStagingObject.objects.select_for_update().filter(
                file=file, generation=file.generation, deleted_at__isnull=True
            )
        )
        if staging:
            now = timezone.now()
            for candidate in staging:
                candidate.cleanup_after = now
                candidate.save(update_fields=("cleanup_after",))
            if file.object_key:
                file.state = FileState.CLEANUP_PENDING
            file.write_fence = uuid.uuid4()
            file.lease_until = None
            file.save(
                update_fields=("state", "write_fence", "lease_until", "updated_at")
            )
        else:
            if not file.reserved_accounted:
                capacity = int(
                    getattr(settings, "ALLIES_FILE_STORAGE_CAPACITY_BYTES", 0)
                )
                if (
                    capacity
                    and account.reserved_bytes
                    + account.retained_bytes
                    + file.expected_size
                    > capacity
                ):
                    raise FileConflict("storage capacity unavailable")
                account.reserved_bytes += file.expected_size
                account.save(update_fields=("reserved_bytes", "updated_at"))
                file.reserved_accounted = True
            file.generation += 1
            file.state = FileState.PENDING
            file.write_fence = uuid.uuid4()
            file.object_key = ""
            file.actual_size = None
            file.safe_error_code = ""
            file.lease_until = None
            file.inspection_attempts = 0
            file.inspection_due_at = None
            file.inspection_lease_until = None
            file.inspection_lease_token = None
            file.cleanup_after = None
            file.save(
                update_fields=(
                    "generation",
                    "state",
                    "write_fence",
                    "object_key",
                    "actual_size",
                    "safe_error_code",
                    "lease_until",
                    "inspection_attempts",
                    "inspection_due_at",
                    "inspection_lease_until",
                    "inspection_lease_token",
                    "cleanup_after",
                    "reserved_accounted",
                    "updated_at",
                )
            )
            message.preparation = MessagePreparation.UPLOADING
            message.preparation_revision += 1
            message.send_armed = False
            message.save(
                update_fields=(
                    "preparation",
                    "preparation_revision",
                    "send_armed",
                    "updated_at",
                )
            )
            return file
    raise FileConflict("file cleanup is pending")


def remove_inbound_file(
    *, user: User, workspace_id, conversation_id, message_id, file_id, revision: int
) -> Message:
    from files.services.cleanup import schedule_file_cleanup

    context = require_workspace_capability(
        user=user, workspace_id=workspace_id, capability=Capability.WORKSPACE_WRITE
    )
    with transaction.atomic():
        from files.services.intake import _account_locked

        _account_locked(context.workspace)
        context, _conversation, message = _scope(
            user=user,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            message_id=message_id,
            context=context,
        )
        try:
            link = MessageFile.objects.select_for_update().get(
                message=message, file_id=_uuid(file_id)
            )
        except MessageFile.DoesNotExist as exc:
            raise FileScopeUnavailable("file unavailable") from exc
        file = (
            FileVersion.objects.select_related("source_message__conversation__ally")
            .select_for_update(of=("self",))
            .get(pk=link.file_id)
        )
        _owned_file(user=user, context=context, message=message, file=file)
        if link.removed_at is not None:
            schedule_file_cleanup(file_id=file.id)
            return message
        _can_change(message)
        if message.preparation_revision != revision:
            raise FileConflict("file message revision conflicts")
        link.removed_at = timezone.now()
        link.save(update_fields=("removed_at",))
        if file.state != FileState.READY:
            file.write_fence = uuid.uuid4()
            file.lease_until = None
            file.inspection_lease_until = None
            file.inspection_lease_token = None
            file.save(
                update_fields=(
                    "write_fence",
                    "lease_until",
                    "inspection_lease_until",
                    "inspection_lease_token",
                    "updated_at",
                )
            )
        from activities.models import RoutineResultContext

        RoutineResultContext.objects.filter(target_message=message).update(
            target_message=None, consumed_at=None
        )
        DispatchOutbox.objects.filter(message=message).delete()
        message.preparation = MessagePreparation.NEEDS_RETRY
        message.preparation_revision += 1
        message.send_armed = False
        message.save(
            update_fields=(
                "preparation",
                "preparation_revision",
                "send_armed",
                "updated_at",
            )
        )
        schedule_file_cleanup(file_id=file.id)
        return message


def arm_file_message(
    *, user: User, workspace_id, conversation_id, message_id, revision: int
) -> Message:
    with transaction.atomic():
        context, _conversation, message = _scope(
            user=user,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        files = _owned_active_files(user=user, context=context, message=message)
        if message.preparation == MessagePreparation.READY and message.send_armed:
            return message
        _can_change(message)
        if message.preparation_revision != revision:
            raise FileConflict("file message revision conflicts")
        if not files:
            raise FileValidation("file message requires files")
        if any(file.state != FileState.READY for file in files):
            raise FileConflict("file message is not ready")
        message.preparation = MessagePreparation.READY
        message.preparation_revision += 1
        message.send_armed = True
        message.save(
            update_fields=(
                "preparation",
                "preparation_revision",
                "send_armed",
                "updated_at",
            )
        )
    from chat.services.dispatch import ensure_dispatch_after_accept

    ensure_dispatch_after_accept(message)
    return message


def cancel_file_message(
    *, user: User, workspace_id, conversation_id, message_id, revision: int
) -> DraftRecovery:
    with transaction.atomic():
        context, conversation, message = _scope(
            user=user,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        files = _owned_active_files(user=user, context=context, message=message)
        existing = (
            FileDraftRecovery.objects.select_for_update()
            .filter(message=message)
            .first()
        )
        if existing is not None:
            return DraftRecovery(existing, tuple(files))
        _can_change(message)
        if message.preparation_revision != revision:
            raise FileConflict("file message revision conflicts")
        draft = FileDraftRecovery.objects.create(
            message=message,
            owner=user,
            ally=message.conversation.ally,
            content=message.content,
        )
        FileDraftFile.objects.bulk_create(
            [
                FileDraftFile(draft=draft, file=file, position=index)
                for index, file in enumerate(files)
            ]
        )
        FileVersion.objects.filter(pk__in=[file.pk for file in files]).exclude(
            state=FileState.READY
        ).update(
            write_fence=uuid.uuid4(),
            lease_until=None,
            inspection_lease_until=None,
            inspection_lease_token=None,
        )
        now = timezone.now()
        message.content = ""
        message.status = MessageLifecycle.STOPPED
        message.deleted_at = now
        message.preparation = MessagePreparation.CANCELLED
        message.preparation_revision += 1
        message.send_armed = False
        message.retry_allowed = False
        message.save(
            update_fields=(
                "content",
                "status",
                "deleted_at",
                "preparation",
                "preparation_revision",
                "send_armed",
                "retry_allowed",
                "updated_at",
            )
        )
        DispatchOutbox.objects.filter(message=message).update(
            status=DispatchState.FAILED,
            safe_error_code="message_cancelled",
            command_bytes=b"",
            command_byte_length=0,
            next_attempt_at=None,
            lease_expires_at=None,
            completed_at=now,
        )
        from chat.services.dispatch import _release_next_locked

        _release_next_locked(conversation, now=now)
        return DraftRecovery(draft, tuple(files))


def file_draft(
    *, user: User, workspace_id, conversation_id, message_id
) -> DraftRecovery:
    with transaction.atomic():
        context, _conversation, message = _scope(
            user=user,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        try:
            draft = (
                FileDraftRecovery.objects.select_for_update()
                .filter(message=message, owner=user, ally=message.conversation.ally)
                .get()
            )
        except FileDraftRecovery.DoesNotExist as exc:
            raise FileScopeUnavailable("file draft unavailable") from exc
        if draft.discarded_at is not None:
            raise FileScopeUnavailable("file draft unavailable")
        files = _active_draft_files(draft=draft)
        for file in files:
            _owned_file(user=user, context=context, message=message, file=file)
        return DraftRecovery(draft, tuple(files))


def discard_file_draft(
    *, user: User, workspace_id, conversation_id, message_id
) -> bool:
    with transaction.atomic():
        context, _conversation, message = _scope(
            user=user,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        try:
            draft = (
                FileDraftRecovery.objects.select_for_update()
                .filter(message=message, owner=user, ally=message.conversation.ally)
                .get()
            )
        except FileDraftRecovery.DoesNotExist as exc:
            raise FileScopeUnavailable("file draft unavailable") from exc
        if draft.discarded_at is not None:
            return True
        files = _active_draft_files(draft=draft, lock=True)
        for file in files:
            _owned_file(user=user, context=context, message=message, file=file)
        draft.discarded_at = timezone.now()
        draft.save(update_fields=("discarded_at", "updated_at"))
        file_ids = tuple(file.id for file in files)
        transaction.on_commit(lambda: _schedule_discarded_files(file_ids=file_ids))
    return True


def _active_draft_files(
    *, draft: FileDraftRecovery, lock: bool = False
) -> list[FileVersion]:
    links = FileDraftFile.objects.filter(draft=draft)
    if lock:
        links = links.select_for_update()
    file_ids = list(links.order_by("position", "id").values_list("file_id", flat=True))
    files = FileVersion.objects.filter(pk__in=file_ids)
    if lock:
        files = files.select_for_update()
    by_id = {file.id: file for file in files}
    return [by_id[file_id] for file_id in file_ids]


def _schedule_discarded_files(*, file_ids: tuple) -> None:
    from files.services.cleanup import schedule_file_cleanup

    for file_id in file_ids:
        schedule_file_cleanup(file_id=file_id)


__all__ = [
    "DraftRecovery",
    "arm_file_message",
    "cancel_file_message",
    "discard_file_draft",
    "file_draft",
    "reconcile_file_message",
    "recover_file_preparation",
    "remove_inbound_file",
    "retry_inbound_file",
]
