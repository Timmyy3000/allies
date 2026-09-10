"""Authorize and proxy one accepted Cloud file to the current runtime lease."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError

from runtime.contracts import FileInputV1
from runtime.exceptions import (
    RuntimeFencedError,
    RuntimeLeaseConflictError,
    RuntimeNotReadyError,
    RuntimeValidationError,
)
from runtime.models import Attempt, Lease, LeaseState

from .event_delivery import _NoRedirect, _validated_cloud_url
from .profiles import profile_allows_runtime_write
from .runtime_auth import RuntimeContext
from .validation import digest_lease_token

MAX_FILE_CHUNK_BYTES = 64 * 1024
MAX_FILE_OPEN_ATTEMPTS = 3
_FILE_OPEN_RETRY_DELAYS = (1, 2)
FILE_CONTENT_PATH = "/api/v1/internal/v1/accepted-files/{file_id}/content"


@dataclass(frozen=True, slots=True)
class IncomingFileContent:
    content_type: str
    content_length: int
    chunks: Iterator[bytes]


@dataclass(frozen=True, slots=True)
class _AuthorizedFile:
    binding_id: UUID
    message_id: UUID
    descriptor: FileInputV1


def open_incoming_file(
    context: RuntimeContext,
    attempt_id: UUID,
    lease_token: str,
    file_id: UUID,
) -> IncomingFileContent:
    """Open the immutable Cloud bytes that belong to one current attempt.

    All database authorization finishes before this function opens the remote
    response. The runtime supplies only an attempt, lease, and file identity.
    Cloud scope comes from the persisted execution record.
    """

    if not getattr(settings, "ALLIES_RUNTIME_FILE_INPUT_ENABLED", False):
        raise RuntimeNotReadyError("incoming file input is disabled")
    authorized = _authorize_file(context, attempt_id, lease_token, file_id)
    base_url = _validated_cloud_url(getattr(settings, "ALLIES_CLOUD_URL", None))
    token = getattr(settings, "ALLIES_CLOUD_EVENT_SERVICE_TOKEN", None)
    if not base_url or not token:
        raise RuntimeNotReadyError("incoming file input is not configured")
    query = urlencode(
        {
            "binding_id": str(authorized.binding_id),
            "message_id": str(authorized.message_id),
        }
    )
    request = Request(
        (
            f"{base_url}{FILE_CONTENT_PATH.format(file_id=authorized.descriptor.file_id)}"
            f"?{query}"
        ),
        headers={
            "Accept": "application/octet-stream",
            "Authorization": f"Bearer {token}",
        },
        method="GET",
    )
    opener = build_opener(_NoRedirect)
    response = _open_cloud_file(opener, request)

    return IncomingFileContent(
        content_type=authorized.descriptor.media_type,
        content_length=authorized.descriptor.size,
        chunks=_chunks(response, authorized.descriptor.size),
    )


def _open_cloud_file(opener, request):
    for attempt in range(MAX_FILE_OPEN_ATTEMPTS):
        try:
            return opener.open(request, timeout=120)
        except HTTPError as exc:
            status = int(exc.code)
            exc.close()
            if status != 503:
                raise RuntimeValidationError("accepted file is unavailable") from None
        except (TimeoutError, URLError, OSError):
            pass
        if attempt + 1 == MAX_FILE_OPEN_ATTEMPTS:
            break
        sleep(_FILE_OPEN_RETRY_DELAYS[attempt])
    raise RuntimeValidationError("accepted file is unavailable")


def _authorize_file(
    context: RuntimeContext,
    attempt_id: UUID,
    lease_token: str,
    file_id: UUID,
) -> _AuthorizedFile:
    if not isinstance(context, RuntimeContext):
        raise RuntimeValidationError("runtime context is required")
    token_digest = digest_lease_token(lease_token)
    with transaction.atomic():
        attempt = (
            Attempt.objects.select_for_update()
            .select_related("execution__workspace", "execution__profile")
            .filter(pk=attempt_id, execution__workspace_id=context.workspace_id)
            .first()
        )
        if attempt is None:
            raise RuntimeLeaseConflictError("attempt is not in this workspace")
        execution = attempt.execution
        workspace = execution.workspace
        profile = execution.profile
        if (
            workspace.machine_generation != context.machine_generation
            or attempt.machine_generation != context.machine_generation
        ):
            raise RuntimeFencedError("runtime generation is stale")
        if not profile_allows_runtime_write(profile):
            raise RuntimeLeaseConflictError("profile lifecycle is not active")
        lease = Lease.objects.select_for_update().filter(attempt_id=attempt.id).first()
        if (
            lease is None
            or lease.token_digest != token_digest
            or lease.state != LeaseState.ACTIVE
            or lease.machine_generation != context.machine_generation
            or lease.expires_at <= timezone.now()
        ):
            raise RuntimeLeaseConflictError("lease does not authorize file access")
        if (
            execution.source_kind != "conversation_message"
            or execution.cloud_binding_id is None
            or execution.cloud_message_id is None
        ):
            raise RuntimeLeaseConflictError("execution has no conversation file authority")
        descriptor = _manifest_file(execution.input_payload.get("files"), file_id)
        return _AuthorizedFile(
            binding_id=execution.cloud_binding_id,
            message_id=execution.cloud_message_id,
            descriptor=descriptor,
        )


def _manifest_file(value: object, file_id: UUID) -> FileInputV1:
    if not isinstance(value, list) or not 1 <= len(value) <= 10:
        raise RuntimeLeaseConflictError("execution has no file manifest")
    try:
        files = [FileInputV1.model_validate(item) for item in value]
    except ValidationError as exc:
        raise RuntimeLeaseConflictError("execution file manifest is invalid") from exc
    if sum(item.size for item in files) > 50_000_000:
        raise RuntimeLeaseConflictError("execution file manifest is invalid")
    for descriptor in files:
        if descriptor.file_id == file_id:
            return descriptor
    raise RuntimeLeaseConflictError("file is not in the execution manifest")


def _chunks(response, expected_size: int) -> Iterator[bytes]:
    sent = 0
    try:
        while True:
            chunk = response.read(MAX_FILE_CHUNK_BYTES)
            if not chunk:
                return
            if not isinstance(chunk, bytes):
                raise RuntimeValidationError("accepted file response is invalid")
            sent += len(chunk)
            if sent > expected_size:
                raise RuntimeValidationError("accepted file exceeds its manifest size")
            yield chunk
    finally:
        response.close()


__all__ = [
    "FILE_CONTENT_PATH",
    "MAX_FILE_CHUNK_BYTES",
    "MAX_FILE_OPEN_ATTEMPTS",
    "IncomingFileContent",
    "open_incoming_file",
]
