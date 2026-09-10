"""Durable Cloud-owned publication and retry state for Foundry return files."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import PurePath
from typing import BinaryIO

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Prefetch, Q, Sum
from django.utils import timezone

from allies.models import AllyBinding, BindingStatus
from auths.models import User
from chat.exceptions import QueueFull
from chat.models import Conversation, Message, MessageOrigin, MessageSender
from common.uuids import canonical_uuid
from files.exceptions import (
    FileConflict,
    FileScopeUnavailable,
    FileUnavailable,
    FileValidation,
)
from files.models import (
    MAX_FILE_BYTES,
    FileAllyTombstone,
    FileDirection,
    FileObjectKind,
    FilePublication,
    FileStagingObject,
    FileState,
    FileVersion,
    PublicationState,
)
from files.services.intake import (
    _MEDIA_TYPES,
    MAX_MESSAGE_FILE_BYTES,
    MAX_MESSAGE_FILES,
    _account_locked,
    _BoundedStream,
    _content_length,
    _keep_recoverable,
    _reject_file,
)
from files.storage import get_file_store
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability

_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_FILE_REFERENCE = re.compile(
    r"/files/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
_MARKDOWN_FILE_REFERENCE = re.compile(
    r"\]\((/files/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}))\)",
    re.IGNORECASE,
)
_RETRY_DELAYS = (5, 30, 120, 300)
_FILE_FAILURE = "[File publication failed. Retry the request.]"


@dataclass(frozen=True, slots=True)
class PublicationFile:
    source_version_id: uuid.UUID
    name: str
    size: int
    sha256: str
    media_type: str


@dataclass(frozen=True, slots=True)
class PublicationClaim:
    publication: FilePublication
    files: tuple[FileVersion, ...]


def _uuid(value) -> uuid.UUID:
    try:
        return canonical_uuid(value)
    except (TypeError, ValueError) as exc:
        raise FileScopeUnavailable("publication unavailable") from exc


def _files(value: object) -> tuple[PublicationFile, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_MESSAGE_FILES:
        raise FileValidation("invalid publication manifest")
    parsed: list[PublicationFile] = []
    total = 0
    seen: set[uuid.UUID] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {
            "source_version_id",
            "name",
            "size",
            "sha256",
        }:
            raise FileValidation("invalid publication manifest")
        try:
            source_version_id = _uuid(raw["source_version_id"])
            name = str(raw["name"])
            size = int(raw["size"])
            digest = str(raw["sha256"])
        except (TypeError, ValueError, KeyError) as exc:
            raise FileValidation("invalid publication manifest") from exc
        suffix = PurePath(name).suffix.lower().removeprefix(".")
        if (
            source_version_id in seen
            or name != PurePath(name).name
            or not 1 <= len(name) <= 255
            or any(ord(char) < 32 or ord(char) == 127 for char in name)
            or suffix not in _MEDIA_TYPES
            or not 1 <= size <= MAX_FILE_BYTES
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise FileValidation("invalid publication manifest")
        seen.add(source_version_id)
        total += size
        parsed.append(
            PublicationFile(source_version_id, name, size, digest, _MEDIA_TYPES[suffix])
        )
    if total > MAX_MESSAGE_FILE_BYTES:
        raise FileValidation("publication manifest too large")
    return tuple(parsed)


def _digest(files: tuple[PublicationFile, ...]) -> str:
    return hashlib.sha256(
        b"\0".join(
            f"{item.source_version_id}:{item.name}:{item.size}:{item.sha256}".encode()
            for item in files
        )
    ).hexdigest()


def _binding_message_locked(*, binding_id, message_id) -> tuple[AllyBinding, Message]:
    binding_id, message_id = _uuid(binding_id), _uuid(message_id)
    try:
        binding = _active_retry_binding_locked(binding_id=binding_id)
        if binding is None:
            raise FileScopeUnavailable("publication unavailable")
        conversation = Conversation.objects.select_for_update(of=("self",)).get(
            messages__id=message_id, ally=binding.ally
        )
        message = (
            Message.objects.select_related("conversation__ally__workspace")
            .select_for_update(of=("self",))
            .get(
                pk=message_id,
                conversation=conversation,
                sender=MessageSender.USER,
                origin=MessageOrigin.SEND,
                deleted_at__isnull=True,
                execution_claimed_at__isnull=False,
                foundry_binding_id=binding_id,
            )
        )
    except (Conversation.DoesNotExist, Message.DoesNotExist) as exc:
        raise FileScopeUnavailable("publication unavailable") from exc
    return binding, message


def _active_retry_binding_locked(*, binding_id) -> AllyBinding | None:
    binding = (
        AllyBinding.objects.select_related("ally")
        .select_for_update(of=("self", "ally"))
        .filter(pk=_uuid(binding_id), status=BindingStatus.BOUND)
        .first()
    )
    if (
        binding is None
        or FileAllyTombstone.objects.filter(ally_id=binding.ally_id).exists()
    ):
        return None
    return binding


def _view(publication: FilePublication) -> dict:
    files = getattr(publication, "prefetched_files", None)
    if files is None:
        files = list(publication.files.order_by("created_at", "id"))
    ready = publication.state == PublicationState.READY
    return {
        "publication_id": str(publication.id),
        "revision": publication.revision,
        "state": publication.state,
        "files": [
            {
                "id": str(file.id),
                "source_version_id": str(file.source_version_id),
                "name": file.original_name,
                "type": file.media_type,
                "size": file.expected_size,
                "sha256": file.sha256,
                "state": file.state,
                "generation": file.generation,
                **(
                    {"open_path": f"/files/{file.id}"}
                    if ready and file.state == FileState.READY
                    else {}
                ),
            }
            for file in files
        ],
        "retryable": publication.state == PublicationState.FAILED,
    }


def reply_publications(*, message: Message) -> list[dict]:
    publications = getattr(message, "prefetched_file_publications", None)
    if publications is None:
        publications = FilePublication.objects.filter(
            source_message=message
        ).prefetch_related(
            Prefetch(
                "files",
                queryset=FileVersion.objects.order_by("created_at", "id"),
                to_attr="prefetched_files",
            )
        )
    return [_view(publication) for publication in publications]


def sanitize_reply_file_links(
    *,
    message_id,
    binding_id,
    text: str,
    pending: str = "",
    prior_context: str = "",
    final: bool = False,
) -> tuple[str, str]:
    """Return public reply text with only ready, source-scoped file paths intact."""
    value = pending + text
    if final and pending:
        return (
            (_FILE_FAILURE if _is_partial_file_reference(pending) else pending),
            "",
        )
    visible, pending = _split_pending_file_reference(value, prior_context=prior_context)
    if "/files/" not in visible.lower():
        return visible, pending
    ready_ids = {
        str(value)
        for value in FileVersion.objects.filter(
            publication__source_message_id=message_id,
            publication__binding_id=binding_id,
            publication__state=PublicationState.READY,
            state=FileState.READY,
        ).values_list("id", flat=True)
    }

    def markdown(match: re.Match[str]) -> str:
        return (
            match.group(0)
            if match.group(2).lower() in ready_ids
            else " " + _FILE_FAILURE
        )

    visible = _MARKDOWN_FILE_REFERENCE.sub(markdown, visible)

    def plain(match: re.Match[str]) -> str:
        path, file_id = match.group(0), match.group(1)
        if not _is_product_relative(
            visible, match.start(), prior_context=prior_context
        ):
            return path
        return (
            f"/files/{file_id.lower()}"
            if file_id.lower() in ready_ids
            else _FILE_FAILURE
        )

    return _FILE_REFERENCE.sub(plain, visible), pending


def _split_pending_file_reference(value: str, *, prior_context: str) -> tuple[str, str]:
    if value.endswith("]"):
        return value[:-1], "]"
    if value.endswith("]("):
        return value[:-2], "]("
    for length in range(min(len(value), len("/files/")), 0, -1):
        suffix = value[-length:]
        if "/files/".startswith(suffix.lower()) and _is_product_relative(
            value, len(value) - length, prior_context=prior_context
        ):
            return _held_file_reference(value, len(value) - length)
    start = value.lower().rfind("/files/")
    if start >= 0 and _is_product_relative(value, start, prior_context=prior_context):
        suffix = value[start + len("/files/") :]
        if len(suffix) < 36 and re.fullmatch(r"[0-9a-f-]*", suffix, re.IGNORECASE):
            return _held_file_reference(value, start)
    return value, ""


def _held_file_reference(value: str, start: int) -> tuple[str, str]:
    if start >= 2 and value[start - 2 : start] == "](":
        start -= 2
    return value[:start], value[start:]


def _is_partial_file_reference(value: str) -> bool:
    start = value.find("/")
    return start >= 0 and (
        "/files/".startswith(value[start:].lower())
        or value[start:].lower().startswith("/files/")
    )


def _is_product_relative(value: str, start: int, *, prior_context: str) -> bool:
    prior = value[start - 1] if start else prior_context[-1:] or None
    return prior is None or prior.isspace() or prior in "([{'\""


def publication_view(*, publication_id, binding_id=None, message_id=None) -> dict:
    try:
        publication = (
            FilePublication.objects.prefetch_related("files")
            .filter(
                pk=_uuid(publication_id),
                source_message__foundry_binding_id=F("binding_id"),
                source_message__conversation__ally__file_tombstone__isnull=True,
            )
            .first()
        )
    except (TypeError, ValueError) as exc:
        raise FileScopeUnavailable("publication unavailable") from exc
    if publication is None:
        raise FileScopeUnavailable("publication unavailable")
    if binding_id is not None and publication.binding_id != _uuid(binding_id):
        raise FileScopeUnavailable("publication unavailable")
    if message_id is not None and publication.source_message_id != _uuid(message_id):
        raise FileScopeUnavailable("publication unavailable")
    return _view(publication)


def publication_transport_scope(*, publication_id) -> tuple[uuid.UUID, uuid.UUID]:
    try:
        publication = (
            FilePublication.objects.only("binding_id", "source_message_id")
            .filter(
                pk=_uuid(publication_id),
                source_message__foundry_binding_id=F("binding_id"),
                source_message__conversation__ally__file_tombstone__isnull=True,
            )
            .first()
        )
    except (TypeError, ValueError) as exc:
        raise FileScopeUnavailable("publication unavailable") from exc
    if publication is None:
        raise FileScopeUnavailable("publication unavailable")
    return publication.binding_id, publication.source_message_id


def reserve_publication(
    *, binding_id, message_id, publication_id, files: object
) -> dict:
    manifest = _files(files)
    request_digest = _digest(manifest)
    publication_id = _uuid(publication_id)
    try:
        workspace_id = Message.objects.values_list(
            "conversation__ally__workspace_id", flat=True
        ).get(pk=_uuid(message_id))
    except Message.DoesNotExist as exc:
        raise FileScopeUnavailable("publication unavailable") from exc
    with transaction.atomic():
        account = _account_locked(workspace_id)
        binding, message = _binding_message_locked(
            binding_id=binding_id, message_id=message_id
        )
        publication = (
            FilePublication.objects.select_for_update()
            .filter(pk=publication_id)
            .first()
        )
        created = False
        if publication is None:
            try:
                with transaction.atomic():
                    publication = FilePublication.objects.create(
                        id=publication_id,
                        binding=binding,
                        source_message=message,
                        request_digest=request_digest,
                    )
                created = True
            except IntegrityError:
                publication = FilePublication.objects.select_for_update().get(
                    pk=publication_id
                )
        if not created:
            if (
                publication.binding_id != binding.id
                or publication.source_message_id != message.id
            ):
                raise FileConflict("publication identity conflicts")
            if publication.request_digest:
                if publication.request_digest != request_digest:
                    raise FileConflict("publication manifest conflicts")
                return _view(publication)
            publication.request_digest = request_digest
            publication.state = PublicationState.UPLOADING
            publication.safe_error_code = ""
            publication.save(
                update_fields=(
                    "request_digest",
                    "state",
                    "safe_error_code",
                    "updated_at",
                )
            )
        existing = FileVersion.objects.select_for_update().filter(
            publication__source_message=message,
            direction=FileDirection.OUTBOUND,
        )
        count = existing.count()
        total = existing.aggregate(total=Sum("expected_size"))["total"] or 0
        requested = sum(item.size for item in manifest)
        if (
            count + len(manifest) > MAX_MESSAGE_FILES
            or total + requested > MAX_MESSAGE_FILE_BYTES
        ):
            raise FileValidation("publication manifest exceeds reply limits")
        capacity = int(getattr(settings, "ALLIES_FILE_STORAGE_CAPACITY_BYTES", 0))
        if (
            capacity
            and account.reserved_bytes + account.retained_bytes + requested > capacity
        ):
            raise QueueFull("storage capacity unavailable")
        FileVersion.objects.bulk_create(
            [
                FileVersion(
                    workspace=message.conversation.ally.workspace,
                    ally=message.conversation.ally,
                    owner=message.conversation.ally.workspace.owner,
                    source_message=message,
                    publication=publication,
                    source_version_id=item.source_version_id,
                    direction=FileDirection.OUTBOUND,
                    original_name=item.name,
                    media_type=item.media_type,
                    expected_size=item.size,
                    sha256=item.sha256,
                    reserved_accounted=True,
                )
                for item in manifest
            ]
        )
        account.reserved_bytes += requested
        account.save(update_fields=("reserved_bytes", "updated_at"))
    return publication_view(
        publication_id=publication.id, binding_id=binding.id, message_id=message.id
    )


def create_publication_placeholder(
    *, binding_id, message_id, publication_id, error_code: str
) -> dict:
    if not isinstance(error_code, str) or _SAFE_CODE.fullmatch(error_code) is None:
        raise FileValidation("invalid publication error")
    publication_id = _uuid(publication_id)
    with transaction.atomic():
        binding, message = _binding_message_locked(
            binding_id=binding_id, message_id=message_id
        )
        publication = (
            FilePublication.objects.select_for_update()
            .filter(pk=publication_id)
            .first()
        )
        if publication is None:
            try:
                with transaction.atomic():
                    publication = FilePublication.objects.create(
                        id=publication_id,
                        binding=binding,
                        source_message=message,
                        state=PublicationState.FAILED,
                        safe_error_code=error_code,
                    )
            except IntegrityError:
                publication = FilePublication.objects.select_for_update().get(
                    pk=publication_id
                )
        if (
            publication.binding_id != binding.id
            or publication.source_message_id != message.id
        ):
            raise FileConflict("publication identity conflicts")
    return publication_view(
        publication_id=publication.id, binding_id=binding.id, message_id=message.id
    )


def _publication_file_locked(
    *, publication_id, file_id, generation, revision, lease_token
):
    publication = FilePublication.objects.select_for_update(of=("self",)).get(
        pk=_uuid(publication_id),
        source_message__foundry_binding_id=F("binding_id"),
        source_message__conversation__ally__file_tombstone__isnull=True,
    )
    file = FileVersion.objects.select_for_update().get(
        pk=_uuid(file_id), publication=publication, direction=FileDirection.OUTBOUND
    )
    if publication.state not in {
        PublicationState.UPLOADING,
        PublicationState.RETRY_PENDING,
        PublicationState.VALIDATING,
    }:
        raise FileConflict("publication cannot receive files")
    if publication.revision != revision or file.generation != generation:
        raise FileConflict("publication revision conflicts")
    if publication.lease_token is not None and (
        publication.lease_until is None
        or publication.lease_until <= timezone.now()
        or publication.lease_token != lease_token
    ):
        raise FileConflict("publication lease conflicts")
    if publication.lease_token is None and lease_token is not None:
        raise FileConflict("publication lease conflicts")
    return publication, file


def receive_publication_file(
    *,
    binding_id,
    message_id,
    publication_id,
    file_id,
    generation: int,
    revision: int,
    lease_token,
    content_length: object,
    stream: BinaryIO,
) -> FileVersion:
    if lease_token is not None:
        lease_token = _uuid(lease_token)
    expected_length = _content_length(content_length)
    now = timezone.now()
    with transaction.atomic():
        binding, message = _binding_message_locked(
            binding_id=binding_id, message_id=message_id
        )
        try:
            publication, file = _publication_file_locked(
                publication_id=publication_id,
                file_id=file_id,
                generation=generation,
                revision=revision,
                lease_token=lease_token,
            )
        except (FilePublication.DoesNotExist, FileVersion.DoesNotExist) as exc:
            raise FileScopeUnavailable("publication unavailable") from exc
        if (
            publication.binding_id != binding.id
            or publication.source_message_id != message.id
        ):
            raise FileScopeUnavailable("publication unavailable")
        if expected_length != file.expected_size:
            raise FileValidation("content length mismatch")
        if (
            file.state == FileState.RECEIVING
            and file.lease_until
            and file.lease_until > now
        ):
            raise FileConflict("publication upload is active")
        if file.state not in {FileState.PENDING, FileState.RECEIVING}:
            raise FileConflict("publication file is immutable")
        file.state = FileState.RECEIVING
        file.write_fence = uuid.uuid4()
        file.lease_until = now + timedelta(
            seconds=int(getattr(settings, "ALLIES_FILE_UPLOAD_LEASE_SECONDS", 120))
        )
        file.object_key = f"staging/{file.workspace_id}/{file.id}/{file.generation}/{uuid.uuid4().hex}"
        fence, key = file.write_fence, file.object_key
        FileStagingObject.objects.create(
            file=file,
            key=key,
            generation=file.generation,
            write_fence=fence,
            kind=FileObjectKind.STAGING,
            cleanup_after=now + timedelta(hours=24),
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
    except Exception as exc:
        _keep_recoverable(file_id=file.id, generation=generation, fence=fence)
        raise FileUnavailable("private storage unavailable") from exc
    if (
        not bounded.complete()
        or bounded.total != expected_length
        or bounded.digest.hexdigest() != file.sha256
    ):
        _reject_file(
            file_id=file.id, generation=generation, fence=fence, code="upload_invalid"
        )
        raise FileValidation("uploaded bytes invalid")
    with transaction.atomic():
        publication, current = _publication_file_locked(
            publication_id=publication_id,
            file_id=file_id,
            generation=generation,
            revision=revision,
            lease_token=lease_token,
        )
        if current.write_fence != fence or current.object_key != key:
            raise FileConflict("stale publication upload")
        current.state = FileState.VALIDATING
        current.lease_until = None
        current.inspection_due_at = now
        current.inspection_lease_until = None
        current.inspection_lease_token = None
        current.save(
            update_fields=(
                "state",
                "lease_until",
                "inspection_due_at",
                "inspection_lease_until",
                "inspection_lease_token",
                "updated_at",
            )
        )
        states = set(
            FileVersion.objects.select_for_update()
            .filter(publication=publication)
            .values_list("state", flat=True)
        )
        if states <= {FileState.VALIDATING, FileState.READY}:
            publication.state = PublicationState.VALIDATING
            publication.save(update_fields=("state", "updated_at"))
    return current


def reconcile_publication(*, publication_id) -> FilePublication:
    with transaction.atomic():
        publication = FilePublication.objects.select_for_update().get(
            pk=_uuid(publication_id)
        )
        files = list(
            FileVersion.objects.select_for_update().filter(publication=publication)
        )
        if not files:
            return publication
        if all(file.state == FileState.READY for file in files):
            publication.state = PublicationState.READY
            publication.retry_due_at = None
            publication.safe_error_code = ""
        elif any(
            file.state in {FileState.FAILED, FileState.REJECTED} for file in files
        ):
            publication.state = PublicationState.FAILED
            publication.safe_error_code = "publication_unavailable"
            publication.retry_due_at = None
        elif not any(
            file.state in {FileState.PENDING, FileState.RECEIVING} for file in files
        ):
            publication.state = PublicationState.VALIDATING
        publication.save(
            update_fields=(
                "state",
                "safe_error_code",
                "retry_due_at",
                "updated_at",
            )
        )
    return publication


def _retry_publication_locked(
    *, context, ally_id, message_id, publication_id, revision: int
) -> FilePublication:
    publication = (
        FilePublication.objects.select_for_update(of=("self",))
        .select_related("source_message__conversation__ally")
        .filter(
            pk=_uuid(publication_id),
            source_message_id=_uuid(message_id),
            source_message__conversation__ally_id=_uuid(ally_id),
            source_message__conversation__ally__workspace=context.workspace,
            source_message__foundry_binding_id=F("binding_id"),
            source_message__conversation__ally__file_tombstone__isnull=True,
        )
        .first()
    )
    if publication is None:
        raise FileScopeUnavailable("publication unavailable")
    if publication.revision != revision:
        raise FileConflict("publication revision conflicts")
    return publication


def retry_publication(
    *, user: User, workspace_id, ally_id, message_id, publication_id, revision: int
) -> dict:
    context = require_workspace_capability(
        user=user, workspace_id=workspace_id, capability=Capability.WORKSPACE_WRITE
    )
    if context.workspace.owner_id != user.id:
        raise FileScopeUnavailable("publication unavailable")
    now = timezone.now()
    with transaction.atomic():
        publication = _retry_publication_locked(
            context=context,
            ally_id=ally_id,
            message_id=message_id,
            publication_id=publication_id,
            revision=revision,
        )
        if publication.state == PublicationState.RETRY_PENDING:
            return _view(publication)
        if publication.state != PublicationState.FAILED:
            raise FileConflict("publication is not retryable")
        pending_cleanup = (
            FileStagingObject.objects.filter(
                file__publication=publication,
                file__state__in=(FileState.FAILED, FileState.CLEANUP_PENDING),
                kind__in=(FileObjectKind.STAGING, FileObjectKind.OBJECT),
                deleted_at__isnull=True,
            ).update(cleanup_after=now)
            > 0
        )
    if pending_cleanup:
        raise FileConflict("publication cleanup pending")
    with transaction.atomic():
        account = _account_locked(context.workspace)
        publication = _retry_publication_locked(
            context=context,
            ally_id=ally_id,
            message_id=message_id,
            publication_id=publication_id,
            revision=revision,
        )
        if publication.state == PublicationState.RETRY_PENDING:
            return _view(publication)
        if publication.state != PublicationState.FAILED:
            raise FileConflict("publication is not retryable")
        files = list(
            FileVersion.objects.select_for_update()
            .filter(publication=publication)
            .exclude(state=FileState.READY)
        )
        if FileStagingObject.objects.filter(
            file_id__in=(file.id for file in files),
            kind__in=(FileObjectKind.STAGING, FileObjectKind.OBJECT),
            deleted_at__isnull=True,
        ).exists():
            raise FileConflict("publication cleanup pending")
        requested = sum(
            file.expected_size for file in files if not file.reserved_accounted
        )
        capacity = int(getattr(settings, "ALLIES_FILE_STORAGE_CAPACITY_BYTES", 0))
        if (
            capacity
            and account.reserved_bytes + account.retained_bytes + requested > capacity
        ):
            raise QueueFull("storage capacity unavailable")
        for file in files:
            file.generation += 1
            file.state = FileState.PENDING
            file.object_key = ""
            file.actual_size = None
            file.write_fence = uuid.uuid4()
            file.safe_error_code = ""
            file.lease_until = None
            file.inspection_attempts = 0
            file.inspection_due_at = None
            file.inspection_lease_until = None
            file.inspection_lease_token = None
            if not file.reserved_accounted:
                file.reserved_accounted = True
            file.save(
                update_fields=(
                    "generation",
                    "state",
                    "object_key",
                    "actual_size",
                    "write_fence",
                    "safe_error_code",
                    "lease_until",
                    "inspection_attempts",
                    "inspection_due_at",
                    "inspection_lease_until",
                    "inspection_lease_token",
                    "reserved_accounted",
                    "updated_at",
                )
            )
        if requested:
            account.reserved_bytes += requested
            account.save(update_fields=("reserved_bytes", "updated_at"))
        publication.revision += 1
        publication.state = PublicationState.RETRY_PENDING
        publication.retry_due_at = now
        publication.retry_attempts = 0
        publication.safe_error_code = ""
        publication.lease_until = None
        publication.lease_token = None
        publication.result_revision = None
        publication.result_lease_token = None
        publication.result_outcome = ""
        publication.save(
            update_fields=(
                "revision",
                "state",
                "retry_due_at",
                "retry_attempts",
                "safe_error_code",
                "lease_until",
                "lease_token",
                "result_revision",
                "result_lease_token",
                "result_outcome",
                "updated_at",
            )
        )
    return publication_view(publication_id=publication.id)


def owner_publication_view(
    *, user: User, workspace_id, ally_id, message_id, publication_id
) -> dict:
    context = require_workspace_capability(
        user=user, workspace_id=workspace_id, capability=Capability.PROFILE_READ
    )
    if context.workspace.owner_id != user.id:
        raise FileScopeUnavailable("publication unavailable")
    publication = (
        FilePublication.objects.prefetch_related("files")
        .filter(
            pk=_uuid(publication_id),
            source_message_id=_uuid(message_id),
            source_message__conversation__ally_id=_uuid(ally_id),
            source_message__conversation__ally__workspace=context.workspace,
            source_message__foundry_binding_id=F("binding_id"),
            source_message__conversation__ally__file_tombstone__isnull=True,
        )
        .first()
    )
    if publication is None:
        raise FileScopeUnavailable("publication unavailable")
    return _view(publication)


def _expire_retry_leases(*, now, binding_id) -> None:
    rows = FilePublication.objects.filter(
        retry_attempts__gte=5,
        lease_until__lte=now,
        binding_id=binding_id,
    )
    rows.filter(state=PublicationState.READY).update(
        retry_due_at=None,
        lease_until=None,
        lease_token=None,
    )
    rows.exclude(state=PublicationState.READY).update(
        state=PublicationState.FAILED,
        safe_error_code="publication_retry_exhausted",
        retry_due_at=None,
        lease_until=None,
        lease_token=None,
    )


def claim_publication_retries(
    *, binding_id, limit: int
) -> tuple[PublicationClaim, ...]:
    if not 1 <= limit <= 20:
        raise FileValidation("invalid retry limit")
    binding_id = _uuid(binding_id)
    now = timezone.now()
    claimed: list[PublicationClaim] = []
    with transaction.atomic():
        binding = _active_retry_binding_locked(binding_id=binding_id)
        if binding is None:
            return ()
        _expire_retry_leases(now=now, binding_id=binding.id)
        rows = (
            FilePublication.objects.select_for_update(skip_locked=True, of=("self",))
            .filter(
                binding_id=binding.id,
                state=PublicationState.RETRY_PENDING,
                retry_due_at__lte=now,
                retry_attempts__lt=5,
                source_message__foundry_binding_id=F("binding_id"),
                source_message__conversation__ally__file_tombstone__isnull=True,
            )
            .filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now))
            .order_by("retry_due_at", "id")[:limit]
        )
        for publication in rows:
            publication.lease_token = uuid.uuid4()
            publication.lease_until = now + timedelta(minutes=5)
            publication.retry_attempts += 1
            publication.save(
                update_fields=(
                    "lease_token",
                    "lease_until",
                    "retry_attempts",
                    "updated_at",
                )
            )
            claimed.append(
                PublicationClaim(
                    publication, tuple(publication.files.order_by("created_at", "id"))
                )
            )
    return tuple(claimed)


def publication_retry_result(
    *,
    publication_id,
    revision: int,
    lease_token,
    outcome: str,
    safe_error_code: str = "",
) -> dict:
    if outcome not in {"submitted", "failed"} or (
        outcome == "failed" and _SAFE_CODE.fullmatch(safe_error_code) is None
    ):
        raise FileValidation("invalid retry result")
    lease_token = _uuid(lease_token)
    with transaction.atomic():
        now = timezone.now()
        probe = FilePublication.objects.only("id", "binding_id").get(
            pk=_uuid(publication_id)
        )
        binding = _active_retry_binding_locked(binding_id=probe.binding_id)
        if binding is None:
            raise FileScopeUnavailable("publication unavailable")
        publication = (
            FilePublication.objects.select_for_update(of=("self",))
            .filter(
                pk=probe.id,
                binding_id=binding.id,
                source_message__foundry_binding_id=F("binding_id"),
                source_message__conversation__ally_id=binding.ally_id,
            )
            .first()
        )
        if publication is None:
            raise FileScopeUnavailable("publication unavailable")
        if (
            publication.result_revision == revision
            and publication.result_lease_token == lease_token
            and publication.result_outcome == outcome
        ):
            return _view(publication)
        if (
            publication.revision != revision
            or publication.lease_token != lease_token
            or publication.lease_until is None
            or publication.lease_until <= now
            or publication.state
            not in {
                PublicationState.RETRY_PENDING,
                PublicationState.VALIDATING,
                PublicationState.READY,
                PublicationState.FAILED,
            }
        ):
            raise FileConflict("publication lease conflicts")
        files = list(
            FileVersion.objects.select_for_update().filter(publication=publication)
        )
        if outcome == "submitted" and any(
            file.state in {FileState.PENDING, FileState.RECEIVING} for file in files
        ):
            raise FileConflict("publication files are not submitted")
        publication.result_revision = revision
        publication.result_lease_token = lease_token
        publication.result_outcome = outcome
        publication.lease_until = None
        publication.lease_token = None
        if publication.state == PublicationState.READY:
            publication.retry_due_at = None
            publication.safe_error_code = ""
        elif outcome == "submitted" and all(
            file.state == FileState.READY for file in files
        ):
            publication.state = PublicationState.READY
            publication.retry_due_at = None
            publication.safe_error_code = ""
        elif outcome == "submitted" and any(
            file.state in {FileState.FAILED, FileState.REJECTED} for file in files
        ):
            publication.state = PublicationState.FAILED
            publication.retry_due_at = None
            publication.safe_error_code = "publication_unavailable"
        elif outcome == "submitted":
            publication.state = PublicationState.VALIDATING
            publication.retry_due_at = None
            publication.safe_error_code = ""
        elif publication.retry_attempts >= 5:
            publication.state = PublicationState.FAILED
            publication.retry_due_at = None
            publication.safe_error_code = safe_error_code
        else:
            publication.state = PublicationState.RETRY_PENDING
            publication.retry_due_at = timezone.now() + timedelta(
                seconds=_RETRY_DELAYS[publication.retry_attempts - 1]
            )
            publication.safe_error_code = safe_error_code
        publication.save(
            update_fields=(
                "result_revision",
                "result_lease_token",
                "result_outcome",
                "lease_until",
                "lease_token",
                "state",
                "retry_due_at",
                "safe_error_code",
                "updated_at",
            )
        )
    return publication_view(publication_id=publication.id)


def due_publication_bindings(
    *, limit: int, cursor: str | None = None
) -> tuple[tuple[str, ...], str | None]:
    if not 1 <= limit <= 20:
        raise FileValidation("invalid retry limit")
    now = timezone.now()
    after = _uuid(cursor) if cursor else None
    rows = (
        FilePublication.objects.filter(
            state=PublicationState.RETRY_PENDING,
            retry_due_at__lte=now,
            binding__status=BindingStatus.BOUND,
        )
        .filter(
            Q(lease_until__isnull=True) | Q(lease_until__lte=now),
            source_message__foundry_binding_id=F("binding_id"),
            source_message__conversation__ally__file_tombstone__isnull=True,
        )
        .order_by("binding_id")
        .values_list("binding_id", flat=True)
        .distinct()
    )
    if after is not None:
        rows = rows.filter(binding_id__gt=after)
    ids = tuple(str(value) for value in rows[: limit + 1])
    returned = ids[:limit]
    return returned, returned[-1] if len(ids) > limit else None


__all__ = [
    "PublicationClaim",
    "claim_publication_retries",
    "create_publication_placeholder",
    "due_publication_bindings",
    "owner_publication_view",
    "publication_retry_result",
    "publication_transport_scope",
    "publication_view",
    "receive_publication_file",
    "reconcile_publication",
    "reply_publications",
    "reserve_publication",
    "retry_publication",
]
