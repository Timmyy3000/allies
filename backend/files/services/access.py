"""Private bounded reads for accepted inbound file descriptors."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO

from allies.models import Ally, BindingStatus
from auths.models import User
from chat.models import DispatchOutbox
from common.uuids import canonical_uuid
from files.exceptions import FileScopeUnavailable, FileUnavailable, FileValidation
from files.isolated_inspection import preview_isolated
from files.models import FileDirection, FileState, FileVersion, PublicationState
from files.previews import Preview
from files.storage import get_file_store
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability

CHUNK_BYTES = 64 * 1024


class BoundedFileStream:
    def __init__(self, stream: BinaryIO, size: int):
        self.stream = stream
        self.remaining = size

    def __iter__(self) -> Iterator[bytes]:
        try:
            while self.remaining:
                chunk = self.stream.read(min(CHUNK_BYTES, self.remaining))
                if not chunk:
                    raise FileUnavailable("private storage unavailable")
                self.remaining -= len(chunk)
                yield chunk
        finally:
            self.stream.close()

    def close(self) -> None:
        self.stream.close()


@dataclass(frozen=True, slots=True)
class AcceptedFileStream:
    file: FileVersion
    content: BoundedFileStream


@dataclass(frozen=True, slots=True)
class PrivateFile:
    file: FileVersion
    size: int


def _private_file(*, user: User, workspace_id, ally_id, file_id) -> FileVersion:
    context = require_workspace_capability(
        user=user, workspace_id=workspace_id, capability=Capability.PROFILE_READ
    )
    if context.workspace.owner_id != user.id:
        raise FileScopeUnavailable("file unavailable")
    try:
        ally = Ally.objects.get(
            pk=canonical_uuid(ally_id),
            workspace=context.workspace,
            file_tombstone__isnull=True,
        )
        file = FileVersion.objects.select_related("publication").get(
            pk=canonical_uuid(file_id),
            workspace=context.workspace,
            ally=ally,
            state=FileState.READY,
        )
    except (Ally.DoesNotExist, FileVersion.DoesNotExist, TypeError, ValueError) as exc:
        raise FileScopeUnavailable("file unavailable") from exc
    if file.direction == FileDirection.OUTBOUND and (
        file.publication is None or file.publication.state != PublicationState.READY
    ):
        raise FileScopeUnavailable("file unavailable")
    return file


def open_file(*, user: User, workspace_id, ally_id, file_id) -> PrivateFile:
    file = _private_file(
        user=user, workspace_id=workspace_id, ally_id=ally_id, file_id=file_id
    )
    if file.actual_size != file.expected_size or not file.object_key:
        raise FileUnavailable("private storage unavailable")
    try:
        size, digest = get_file_store().metadata(key=file.object_key)
    except Exception as exc:
        raise FileUnavailable("private storage unavailable") from exc
    if size != file.actual_size or digest != file.sha256:
        raise FileUnavailable("private storage unavailable")
    return PrivateFile(file=file, size=size)


def private_file_stream(
    *, opened: PrivateFile, start: int = 0, end: int | None = None
) -> BoundedFileStream:
    if not 0 <= start < opened.size:
        raise FileValidation("invalid file range")
    end = opened.size - 1 if end is None else end
    if end < start or end >= opened.size:
        raise FileValidation("invalid file range")
    try:
        stream = get_file_store().open_stream(key=opened.file.object_key)
        remaining = start
        while remaining:
            chunk = stream.read(min(CHUNK_BYTES, remaining))
            if not chunk:
                stream.close()
                raise FileUnavailable("private storage unavailable")
            remaining -= len(chunk)
    except FileUnavailable:
        raise
    except Exception as exc:
        raise FileUnavailable("private storage unavailable") from exc
    return BoundedFileStream(stream, end - start + 1)


def private_file_preview(*, opened: PrivateFile) -> Preview:
    try:
        with get_file_store().open_stream(key=opened.file.object_key) as stream:
            return preview_isolated(
                media_type=opened.file.media_type, source=stream, size=opened.size
            )
    except Exception as exc:
        raise FileUnavailable("private storage unavailable") from exc


def accepted_file_stream(*, binding_id, message_id, file_id) -> AcceptedFileStream:
    try:
        binding_id = canonical_uuid(binding_id)
        message_id = canonical_uuid(message_id)
        file_id = canonical_uuid(file_id)
    except (TypeError, ValueError) as exc:
        raise FileScopeUnavailable("file unavailable") from exc
    try:
        outbox = DispatchOutbox.objects.select_related(
            "message__conversation__ally"
        ).get(
            message_id=message_id,
            message__execution_claimed_at__isnull=False,
            message__deleted_at__isnull=True,
            message__foundry_binding_id=binding_id,
            message__conversation__ally__binding__id=binding_id,
            message__conversation__ally__binding__status=BindingStatus.BOUND,
            message__conversation__ally__file_tombstone__isnull=True,
        )
    except DispatchOutbox.DoesNotExist as exc:
        raise FileScopeUnavailable("file unavailable") from exc
    manifest = outbox.file_manifest
    if not isinstance(manifest, list):
        raise FileScopeUnavailable("file unavailable")
    descriptors = [
        item
        for item in manifest
        if isinstance(item, dict) and item.get("file_id") == str(file_id)
    ]
    if len(descriptors) != 1:
        raise FileScopeUnavailable("file unavailable")
    descriptor = descriptors[0]
    try:
        file = FileVersion.objects.get(
            pk=file_id,
            workspace_id=outbox.message.conversation.ally.workspace_id,
            ally_id=outbox.message.conversation.ally_id,
            direction=FileDirection.INBOUND,
            state=FileState.READY,
        )
    except FileVersion.DoesNotExist as exc:
        raise FileScopeUnavailable("file unavailable") from exc
    if descriptor != {
        "file_id": str(file.id),
        "name": file.original_name,
        "media_type": file.media_type,
        "size": file.actual_size,
        "sha256": file.sha256,
    }:
        raise FileScopeUnavailable("file unavailable")
    if file.actual_size != file.expected_size or not file.object_key:
        raise FileUnavailable("private storage unavailable")
    try:
        size, digest = get_file_store().metadata(key=file.object_key)
        if size != file.actual_size or digest != file.sha256:
            raise FileUnavailable("private storage unavailable")
        stream = get_file_store().open_stream(key=file.object_key)
    except FileUnavailable:
        raise
    except Exception as exc:
        raise FileUnavailable("private storage unavailable") from exc
    return AcceptedFileStream(file=file, content=BoundedFileStream(stream, size))


__all__ = [
    "AcceptedFileStream",
    "BoundedFileStream",
    "PrivateFile",
    "accepted_file_stream",
    "open_file",
    "private_file_preview",
    "private_file_stream",
]
