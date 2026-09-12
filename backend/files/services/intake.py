"""Fenced private inbound-file reservation and streaming intake."""

from __future__ import annotations

import hashlib
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import PurePath
from typing import BinaryIO
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from allies.models import Ally, AllyDeletionState, ProvisioningStatus
from auths.models import User
from chat.exceptions import (
    IdempotencyConflict,
    OnboardingHandoffRepairRequired,
    QueueFull,
)
from chat.models import (
    Conversation,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessagePreparation,
    MessageSender,
)
from chat.services.conversations import reconcile_onboarding_reply
from chat.services.messages import (
    _bounded_setting,
    _digest,
    _reservation_token,
    _validate_send_key,
    enforce_send_rate_limit,
)
from common.uuids import canonical_uuid
from files.exceptions import (
    FileAdmissionDisabled,
    FileConflict,
    FileScopeUnavailable,
    FileTooLarge,
    FileUnavailable,
    FileValidation,
)
from files.models import (
    MAX_FILE_BYTES,
    FileAllyTombstone,
    FileDirection,
    FileIOOutcome,
    FileObjectKind,
    FileStagingObject,
    FileState,
    FileStorageAccount,
    FileVersion,
    MessageFile,
)
from files.services.cleanup import mark_file_io_outcome
from files.storage import FileObjectMissing, get_file_store
from files.types import MEDIA_TYPES as _MEDIA_TYPES
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability

MAX_MESSAGE_FILES = 10
MAX_MESSAGE_FILE_BYTES = 50_000_000
CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class FileManifest:
    client_id: UUID
    name: str
    size: int
    sha256: str
    media_type: str


@dataclass(frozen=True, slots=True)
class FileReservation:
    message: Message
    files: tuple[FileVersion, ...]
    replayed: bool


@dataclass(frozen=True, slots=True)
class InspectionResult:
    size: int
    sha256: str
    media_type: str
    clean: bool


class _UploadBodyInvalid(ValueError):
    pass


def _enabled() -> None:
    if not bool(getattr(settings, "ALLIES_FILE_ADMISSION_ENABLED", False)) or not bool(
        getattr(settings, "ALLIES_FILE_STORAGE_ENABLED", False)
    ):
        raise FileAdmissionDisabled("file admission disabled")
    if int(getattr(settings, "ALLIES_FILE_STORAGE_CAPACITY_BYTES", 0)) <= 0:
        raise FileAdmissionDisabled("file admission disabled")


def _parse_manifest(value: object) -> tuple[FileManifest, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_MESSAGE_FILES:
        raise FileValidation("invalid file manifest")
    parsed: list[FileManifest] = []
    identities: set[UUID] = set()
    total = 0
    for raw in value:
        if not isinstance(raw, dict):
            raise FileValidation("invalid file manifest")
        if set(raw) != {"client_id", "name", "size", "sha256"}:
            raise FileValidation("invalid file manifest")
        try:
            client_id = UUID(str(raw["client_id"]))
            name = unicodedata.normalize("NFC", str(raw["name"]))
            size = int(raw["size"])
            digest = str(raw["sha256"])
        except (TypeError, ValueError, KeyError) as exc:
            raise FileValidation("invalid file manifest") from exc
        suffix = PurePath(name).suffix.lower().removeprefix(".")
        if (
            client_id in identities
            or not 1 <= len(name) <= 255
            or name != PurePath(name).name
            or any(ord(character) < 32 or ord(character) == 127 for character in name)
            or suffix not in _MEDIA_TYPES
            or not 1 <= size <= MAX_FILE_BYTES
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise FileValidation("invalid file manifest")
        identities.add(client_id)
        total += size
        parsed.append(FileManifest(client_id, name, size, digest, _MEDIA_TYPES[suffix]))
    if total > MAX_MESSAGE_FILE_BYTES:
        raise FileValidation("file manifest too large")
    return tuple(parsed)


def _content(content: object) -> str:
    if not isinstance(content, str):
        raise FileValidation("invalid content")
    result = unicodedata.normalize("NFC", content).strip()
    if len(result.encode("utf-8")) > 16_000:
        raise FileValidation("invalid content")
    return result


def _manifest_fingerprint(content: str, manifests: tuple[FileManifest, ...]) -> str:
    encoded = (
        content.encode()
        + b"\0"
        + b"\0".join(
            f"{item.client_id}:{item.name}:{item.size}:{item.sha256}".encode()
            for item in manifests
        )
    )
    return hashlib.sha256(encoded).hexdigest()


def _account_locked(workspace) -> FileStorageAccount:
    workspace_id = getattr(workspace, "id", workspace)
    FileStorageAccount.objects.get_or_create(workspace_id=workspace_id)
    return FileStorageAccount.objects.select_for_update().get(workspace_id=workspace_id)


def _scope_locked(*, workspace, conversation_id) -> tuple[Ally, Conversation]:
    try:
        conversation_id = canonical_uuid(conversation_id)
        ally_id = Conversation.objects.only("ally_id").get(pk=conversation_id).ally_id
        ally = Ally.objects.select_for_update().get(pk=ally_id, workspace=workspace)
        conversation = Conversation.objects.select_for_update().get(
            pk=conversation_id, ally=ally
        )
    except (Conversation.DoesNotExist, Ally.DoesNotExist, TypeError, ValueError) as exc:
        raise FileScopeUnavailable("file unavailable") from exc
    if (
        ally.deletion_state != AllyDeletionState.ACTIVE
        or FileAllyTombstone.objects.filter(ally=ally).exists()
    ):
        raise FileScopeUnavailable("file unavailable")
    return ally, conversation


def reserve_send(
    *,
    user: User,
    workspace_id,
    conversation_id,
    content: object,
    files: object,
    key: object,
) -> FileReservation:
    _enabled()
    context = require_workspace_capability(
        user=user, workspace_id=workspace_id, capability=Capability.WORKSPACE_WRITE
    )
    normalized = _content(content)
    manifests = _parse_manifest(files)
    key_digest = _digest(_validate_send_key(key))
    fingerprint = _manifest_fingerprint(normalized, manifests)
    reservation = None
    try:
        with transaction.atomic():
            account = _account_locked(context.workspace)
            ally, conversation = _scope_locked(
                workspace=context.workspace, conversation_id=conversation_id
            )
            if ally.provisioning_state == ProvisioningStatus.REPAIR_REQUIRED:
                raise OnboardingHandoffRepairRequired("onboarding handoff needs repair")
            reconcile_onboarding_reply(ally=ally)
            duplicate = Message.objects.filter(
                conversation=conversation,
                sender=MessageSender.USER,
                origin=MessageOrigin.SEND,
                send_key_digest=key_digest,
            ).first()
            if duplicate is not None:
                if duplicate.content_fingerprint != fingerprint:
                    raise IdempotencyConflict("idempotency key conflicts with content")
                return FileReservation(
                    duplicate,
                    tuple(
                        FileVersion.objects.filter(
                            message_links__message=duplicate
                        ).order_by("message_links__position")
                    ),
                    True,
                )
            live_count = Message.objects.filter(
                conversation=conversation,
                sender=MessageSender.USER,
                origin=MessageOrigin.SEND,
                status__in=(
                    MessageLifecycle.QUEUED,
                    MessageLifecycle.IN_PROGRESS,
                    MessageLifecycle.AWAITING_ACTION,
                ),
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
            capacity = int(getattr(settings, "ALLIES_FILE_STORAGE_CAPACITY_BYTES", 0))
            total = sum(item.size for item in manifests)
            if (
                capacity
                and account.reserved_bytes + account.retained_bytes + total > capacity
            ):
                raise QueueFull("storage capacity unavailable")
            reservation = enforce_send_rate_limit(
                user_id=str(user.id),
                workspace_id=str(context.workspace.id),
                reservation_key=_reservation_token(
                    workspace_id=str(context.workspace.id),
                    user_id=str(user.id),
                    conversation_id=str(conversation.id),
                    key_digest=key_digest,
                ),
            )
            maximum = Message.objects.filter(conversation=conversation).aggregate(
                value=Max("sequence")
            )["value"]
            message = Message.objects.create(
                conversation=conversation,
                sequence=(maximum or 0) + 1,
                sender=MessageSender.USER,
                origin=MessageOrigin.SEND,
                content=normalized,
                status=MessageLifecycle.QUEUED,
                send_key_digest=key_digest,
                content_fingerprint=fingerprint,
                preparation=MessagePreparation.UPLOADING,
                preparation_revision=1,
                send_armed=False,
            )
            rows = tuple(
                FileVersion.objects.create(
                    workspace=context.workspace,
                    ally=ally,
                    owner=user,
                    source_message=message,
                    direction=FileDirection.INBOUND,
                    original_name=item.name,
                    media_type=item.media_type,
                    expected_size=item.size,
                    sha256=item.sha256,
                    reserved_accounted=True,
                )
                for item in manifests
            )
            MessageFile.objects.bulk_create(
                [
                    MessageFile(message=message, file=row, position=index)
                    for index, row in enumerate(rows)
                ]
            )
            account.reserved_bytes += total
            account.save(update_fields=("reserved_bytes", "updated_at"))
            return FileReservation(message, rows, False)
    except Exception:
        if reservation is not None:
            from auths.throttle import reconcile_rate_limit

            reconcile_rate_limit(reservation, committed=False)
        raise


class _BoundedStream:
    def __init__(self, source: BinaryIO, expected_size: int):
        self.source, self.remaining = source, expected_size
        self.digest = hashlib.sha256()
        self.total = 0

    def read(self, size: int = -1) -> bytes:
        if self.remaining == 0:
            return b""
        requested = min(CHUNK_BYTES, self.remaining)
        if size >= 0:
            requested = min(requested, size)
        data = self.source.read(requested)
        if not data:
            raise _UploadBodyInvalid("short request body")
        if len(data) > requested:
            raise _UploadBodyInvalid("oversized request body")
        self.remaining -= len(data)
        self.total += len(data)
        self.digest.update(data)
        return data

    def complete(self) -> bool:
        if self.remaining:
            return False
        return not self.source.read(1)


def _content_length(value: object) -> int:
    if not isinstance(value, str) or not value.isdecimal():
        raise FileValidation("content length required")
    size = int(value)
    if size > MAX_FILE_BYTES:
        raise FileTooLarge("file too large")
    if size < 1:
        raise FileValidation("invalid content length")
    return size


def _reject_file(
    *, file_id, generation: int, fence, code: str, inspection_lease_token=None
) -> None:
    with transaction.atomic():
        current = FileVersion.objects.select_for_update().get(pk=file_id)
        if (
            current.generation == generation
            and current.write_fence == fence
            and (
                inspection_lease_token is None
                or (
                    current.inspection_lease_token == inspection_lease_token
                    and current.inspection_lease_until is not None
                    and current.inspection_lease_until > timezone.now()
                )
            )
        ):
            current.state = FileState.REJECTED
            current.safe_error_code = code
            current.lease_until = None
            current.inspection_due_at = None
            current.inspection_lease_until = None
            current.inspection_lease_token = None
            current.cleanup_after = timezone.now() + timedelta(hours=24)
            current.save(
                update_fields=(
                    "state",
                    "safe_error_code",
                    "lease_until",
                    "inspection_due_at",
                    "inspection_lease_until",
                    "inspection_lease_token",
                    "cleanup_after",
                    "updated_at",
                )
            )
            if current.publication_id:
                from files.services.publication import reconcile_publication

                transaction.on_commit(
                    lambda: reconcile_publication(publication_id=current.publication_id)
                )
            else:
                from files.services.preparation import reconcile_file_message

                transaction.on_commit(
                    lambda: reconcile_file_message(message_id=current.source_message_id)
                )


def _keep_recoverable(
    *, file_id, generation: int, fence, inspection_lease_token=None
) -> None:
    mark_file_io_outcome(
        file_id=file_id,
        write_fence=fence,
        outcome=FileIOOutcome.AMBIGUOUS,
    )
    with transaction.atomic():
        current = FileVersion.objects.select_for_update().get(pk=file_id)
        if (
            current.generation == generation
            and current.write_fence == fence
            and (
                inspection_lease_token is None
                or (
                    current.inspection_lease_token == inspection_lease_token
                    and current.inspection_lease_until is not None
                    and current.inspection_lease_until > timezone.now()
                )
            )
        ):
            current.safe_error_code = "storage_unavailable"
            current.save(update_fields=("safe_error_code", "updated_at"))


def receive_file(
    *,
    user: User,
    workspace_id,
    ally_id,
    file_id,
    generation: int,
    content_length: object,
    stream: BinaryIO,
) -> FileVersion:
    _enabled()
    expected_length = _content_length(content_length)
    context = require_workspace_capability(
        user=user, workspace_id=workspace_id, capability=Capability.WORKSPACE_WRITE
    )
    now = timezone.now()
    with transaction.atomic():
        try:
            ally = Ally.objects.select_for_update().get(
                pk=ally_id,
                workspace=context.workspace,
                deletion_state=AllyDeletionState.ACTIVE,
            )
            if FileAllyTombstone.objects.filter(ally=ally).exists():
                raise FileScopeUnavailable("file unavailable")
            pending = FileVersion.objects.only("id", "source_message_id").get(
                pk=file_id,
                workspace=context.workspace,
                ally=ally,
                owner=user,
                direction=FileDirection.INBOUND,
            )
            source = Message.objects.only("id", "conversation_id").get(
                pk=pending.source_message_id
            )
            conversation = Conversation.objects.select_for_update().get(
                pk=source.conversation_id, ally=ally
            )
            message = Message.objects.select_for_update().get(
                pk=pending.source_message_id, conversation=conversation
            )
            file = FileVersion.objects.select_for_update().get(pk=pending.pk)
        except (
            Ally.DoesNotExist,
            Conversation.DoesNotExist,
            FileVersion.DoesNotExist,
            Message.DoesNotExist,
            TypeError,
        ) as exc:
            raise FileScopeUnavailable("file unavailable") from exc
        if file.source_message_id != message.id:
            raise FileScopeUnavailable("file unavailable")
        if (
            message.deleted_at
            or message.preparation != MessagePreparation.UPLOADING
            or file.generation != generation
            or file.state not in (FileState.PENDING, FileState.RECEIVING)
        ):
            raise FileConflict("stale file upload")
        if (
            file.state == FileState.RECEIVING
            and file.lease_until
            and file.lease_until > now
        ):
            raise FileConflict("file upload is active")
        if expected_length != file.expected_size:
            raise FileValidation("content length mismatch")
        file.state = FileState.RECEIVING
        file.write_fence = uuid.uuid4()
        file.lease_until = now + timedelta(
            seconds=int(getattr(settings, "ALLIES_FILE_UPLOAD_LEASE_SECONDS", 120))
        )
        file.object_key = f"staging/{context.workspace.id}/{file.id}/{file.generation}/{uuid.uuid4().hex}"
        fence, key = file.write_fence, file.object_key
        FileStagingObject.objects.create(
            file=file,
            key=key,
            generation=file.generation,
            write_fence=fence,
            cleanup_after=now + timedelta(hours=24),
            io_outcome=FileIOOutcome.IN_FLIGHT,
        )
        file.save(
            update_fields=(
                "state",
                "write_fence",
                "lease_until",
                "object_key",
                "updated_at",
            )
        )
    bounded = _BoundedStream(stream, expected_length)
    try:
        get_file_store().put_stream(
            key=key,
            stream=bounded,
            content_type="application/octet-stream",
            size=expected_length,
            sha256=file.sha256,
        )
    except _UploadBodyInvalid as exc:
        mark_file_io_outcome(
            file_id=file.id,
            write_fence=fence,
            key=key,
            outcome=FileIOOutcome.AMBIGUOUS,
        )
        _reject_file(
            file_id=file.id,
            generation=generation,
            fence=fence,
            code="upload_invalid",
        )
        raise FileValidation("uploaded bytes invalid") from exc
    except Exception as exc:
        mark_file_io_outcome(
            file_id=file.id,
            write_fence=fence,
            key=key,
            outcome=FileIOOutcome.AMBIGUOUS,
        )
        _keep_recoverable(file_id=file.id, generation=generation, fence=fence)
        raise FileUnavailable("private storage unavailable") from exc
    mark_file_io_outcome(
        file_id=file.id,
        write_fence=fence,
        key=key,
        outcome=FileIOOutcome.COMPLETED,
    )
    if (
        not bounded.complete()
        or bounded.total != expected_length
        or bounded.digest.hexdigest() != file.sha256
    ):
        _reject_file(
            file_id=file.id,
            generation=generation,
            fence=fence,
            code="upload_invalid",
        )
        raise FileValidation("uploaded bytes invalid")
    with transaction.atomic():
        source = Message.objects.only("id", "conversation_id").get(
            pk=file.source_message_id
        )
        conversation = Conversation.objects.select_for_update().get(
            pk=source.conversation_id
        )
        message = Message.objects.select_for_update().get(
            pk=source.id, conversation=conversation
        )
        current = FileVersion.objects.select_for_update().get(pk=file.id)
        if (
            current.generation != generation
            or current.write_fence != fence
            or current.source_message_id != message.id
            or message.deleted_at
            or message.preparation != MessagePreparation.UPLOADING
            or not Ally.objects.filter(
                pk=current.ally_id,
                deletion_state=AllyDeletionState.ACTIVE,
            ).exists()
            or FileAllyTombstone.objects.filter(ally_id=current.ally_id).exists()
        ):
            raise FileConflict("stale file upload")
        current.state = FileState.VALIDATING
        current.lease_until = None
        current.save(update_fields=("state", "lease_until", "updated_at"))
        return current


def promote_inspected_file(
    *, file_id, generation: int, result: InspectionResult, inspection_lease_token=None
) -> FileVersion:
    """Internal inspection boundary; no public path calls this function."""
    with transaction.atomic():
        probe = FileVersion.objects.only(
            "id", "workspace_id", "ally_id", "source_message_id", "publication_id"
        ).get(pk=file_id)
        source = Message.objects.only("id", "conversation_id").get(
            pk=probe.source_message_id
        )
        _account_locked(probe.workspace)
        ally = Ally.objects.select_for_update().get(pk=probe.ally_id)
        if ally.deletion_state != AllyDeletionState.ACTIVE:
            raise FileConflict("stale inspection")
        conversation = Conversation.objects.select_for_update().get(
            pk=source.conversation_id, ally=ally
        )
        message = Message.objects.select_for_update().get(
            pk=source.id, conversation=conversation
        )
        file = FileVersion.objects.select_for_update().get(pk=probe.pk)
        fence = file.write_fence
        if (
            file.source_message_id != message.id
            or file.generation != generation
            or file.state != FileState.VALIDATING
            or (
                inspection_lease_token is not None
                and (
                    file.inspection_lease_token != inspection_lease_token
                    or file.inspection_lease_until is None
                    or file.inspection_lease_until <= timezone.now()
                )
            )
            or FileAllyTombstone.objects.filter(ally_id=file.ally_id).exists()
        ):
            raise FileConflict("stale inspection")
        if (
            not bool(getattr(settings, "ALLIES_FILE_INSPECTION_ENABLED", False))
            or not result.clean
        ):
            file.state = FileState.REJECTED
            file.safe_error_code = (
                "inspection_unavailable" if result.clean else "inspection_rejected"
            )
            file.inspection_due_at = None
            file.inspection_lease_until = None
            file.inspection_lease_token = None
            file.cleanup_after = timezone.now() + timedelta(hours=24)
            file.save(
                update_fields=(
                    "state",
                    "safe_error_code",
                    "cleanup_after",
                    "inspection_due_at",
                    "inspection_lease_until",
                    "inspection_lease_token",
                    "updated_at",
                )
            )
            if file.publication_id:
                from files.services.publication import reconcile_publication

                transaction.on_commit(
                    lambda: reconcile_publication(publication_id=file.publication_id)
                )
            else:
                from files.services.preparation import reconcile_file_message

                transaction.on_commit(
                    lambda: reconcile_file_message(message_id=file.source_message_id)
                )
            return file
        staging_key = file.object_key
        immutable_key = f"immutable/{file.workspace_id}/{file.id}/{file.generation}/{uuid.uuid4().hex}"
        FileStagingObject.objects.create(
            file=file,
            key=immutable_key,
            generation=file.generation,
            write_fence=file.write_fence,
            kind=FileObjectKind.PROMOTION,
            cleanup_after=timezone.now() + timedelta(hours=24),
            io_outcome=FileIOOutcome.IN_FLIGHT,
        )
    try:
        store = get_file_store()
        size, digest = store.metadata(key=staging_key)
    except Exception as exc:
        _keep_recoverable(
            file_id=file_id,
            generation=generation,
            fence=fence,
            inspection_lease_token=inspection_lease_token,
        )
        raise FileUnavailable("private storage unavailable") from exc
    if (
        size != file.expected_size
        or digest != file.sha256
        or result.size != size
        or result.sha256 != digest
        or result.media_type != file.media_type
    ):
        mark_file_io_outcome(
            file_id=file_id,
            write_fence=fence,
            key=immutable_key,
            outcome=FileIOOutcome.ABORTED,
        )
        _reject_file(
            file_id=file_id,
            generation=generation,
            fence=fence,
            code="inspection_invalid",
            inspection_lease_token=inspection_lease_token,
        )
        raise FileValidation("inspection metadata mismatch")
    try:
        destination_size, destination_digest = store.metadata(key=immutable_key)
    except FileObjectMissing:
        try:
            store.promote(source_key=staging_key, destination_key=immutable_key)
            destination_size, destination_digest = store.metadata(key=immutable_key)
        except Exception as exc:
            _keep_recoverable(
                file_id=file_id,
                generation=generation,
                fence=fence,
                inspection_lease_token=inspection_lease_token,
            )
            raise FileUnavailable("private storage unavailable") from exc
    except Exception as exc:
        _keep_recoverable(
            file_id=file_id,
            generation=generation,
            fence=fence,
            inspection_lease_token=inspection_lease_token,
        )
        raise FileUnavailable("private storage unavailable") from exc
    if destination_size != size or destination_digest != digest:
        mark_file_io_outcome(
            file_id=file_id,
            write_fence=fence,
            key=immutable_key,
            outcome=FileIOOutcome.COMPLETED,
        )
        _reject_file(
            file_id=file_id,
            generation=generation,
            fence=fence,
            code="inspection_invalid",
            inspection_lease_token=inspection_lease_token,
        )
        raise FileValidation("immutable promotion verification failed")
    # The copy is now verified. Settle its candidate before reacquiring the
    # admission locks so a concurrent deletion can safely clean this object.
    mark_file_io_outcome(
        file_id=file_id,
        write_fence=fence,
        key=immutable_key,
        outcome=FileIOOutcome.COMPLETED,
    )
    with transaction.atomic():
        probe = FileVersion.objects.only(
            "id", "workspace_id", "ally_id", "source_message_id", "publication_id"
        ).get(pk=file_id)
        source = Message.objects.only("id", "conversation_id").get(
            pk=probe.source_message_id
        )
        account = _account_locked(probe.workspace)
        ally = Ally.objects.select_for_update().get(pk=probe.ally_id)
        if ally.deletion_state != AllyDeletionState.ACTIVE:
            raise FileConflict("stale inspection")
        conversation = Conversation.objects.select_for_update().get(
            pk=source.conversation_id, ally=ally
        )
        message = Message.objects.select_for_update().get(
            pk=source.id, conversation=conversation
        )
        if probe.publication_id:
            file = FileVersion.objects.select_for_update().get(pk=probe.pk)
        else:
            link = (
                MessageFile.objects.select_for_update()
                .filter(message=message, file_id=probe.pk, removed_at__isnull=True)
                .first()
            )
            if link is None:
                raise FileConflict("stale inspection")
            file = FileVersion.objects.select_for_update().get(pk=link.file_id)
        if (
            file.source_message_id != message.id
            or file.generation != generation
            or file.state != FileState.VALIDATING
            or file.write_fence != fence
            or (
                inspection_lease_token is not None
                and (
                    file.inspection_lease_token != inspection_lease_token
                    or file.inspection_lease_until is None
                    or file.inspection_lease_until <= timezone.now()
                )
            )
            or file.object_key != staging_key
            or ally.deletion_state != AllyDeletionState.ACTIVE
            or FileAllyTombstone.objects.filter(ally_id=file.ally_id).exists()
        ):
            raise FileConflict("stale inspection")
        if file.publication_id:
            from files.models import FilePublication, PublicationState

            if (
                not FilePublication.objects.select_for_update()
                .filter(
                    pk=file.publication_id,
                    state__in=(
                        PublicationState.UPLOADING,
                        PublicationState.RETRY_PENDING,
                        PublicationState.VALIDATING,
                    ),
                )
                .exists()
            ):
                raise FileConflict("stale inspection")
        elif message.deleted_at:
            raise FileConflict("stale inspection")
        file.state, file.object_key, file.actual_size = (
            FileState.READY,
            immutable_key,
            size,
        )
        file.inspection_due_at = None
        file.inspection_lease_until = None
        file.inspection_lease_token = None
        update_fields = (
            "state",
            "object_key",
            "actual_size",
            "inspection_due_at",
            "inspection_lease_until",
            "inspection_lease_token",
            "updated_at",
        )
        if file.reserved_accounted:
            account.reserved_bytes -= size
            account.retained_bytes += size
            file.reserved_accounted = False
            file.retained_accounted = True
            update_fields += ("reserved_accounted", "retained_accounted")
            account.save(
                update_fields=("reserved_bytes", "retained_bytes", "updated_at")
            )
        file.save(update_fields=update_fields)
        FileStagingObject.objects.filter(file=file, key=immutable_key).delete()
        from files.services.preparation import reconcile_file_message
        from files.services.publication import reconcile_publication

        if file.publication_id:
            transaction.on_commit(
                lambda: reconcile_publication(publication_id=file.publication_id)
            )
        else:
            transaction.on_commit(
                lambda: reconcile_file_message(message_id=file.source_message_id)
            )
        return file
