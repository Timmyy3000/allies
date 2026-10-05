"""Retrieve unchanged Gmail attachments through the existing private-file lifecycle."""

import base64
import hashlib
import re
import time
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

from django.conf import settings
from django.utils import timezone

from chat.exceptions import QueueFull
from files.exceptions import (
    FileConflict,
    FileScopeUnavailable,
    FileUnavailable,
    FileValidation,
)
from files.models import FilePublication, FileState, FileVersion
from files.services.publication import (
    publication_view,
    receive_publication_file,
    reserve_publication,
)
from files.types import MAX_FILE_BYTES, MEDIA_TYPES

MAX_RESPONSE_BYTES = 34_000_000
STATUS_WAIT_SECONDS = 20
_PART_ID = re.compile(r"(?:\d+(?:\.\d+)*)?")
_ERRORS = {
    "gmail_attachment_too_large": "This attachment or message exceeds the supported file limit. Ask for a smaller file.",
    "gmail_attachment_invalid": "The attachment could not be verified. Do not claim it was retrieved; try another attachment.",
    "gmail_attachment_not_found": "That attachment was not found. Read the message again and use its part_id.",
    "gmail_attachment_unsupported": "That file type is not supported for sharing in Allies.",
    "gmail_attachment_unavailable": "Private file storage is unavailable. Retry this download later; do not claim the file is ready.",
    "gmail_attachment_conflict": "This retrieval conflicts with its existing file version. Do not overwrite it or claim a new download succeeded.",
}


class AttachmentError(ValueError):
    def __init__(self, code):
        self.code = code
        self.instruction = _ERRORS[code]
        super().__init__(code)


def is_attachment(part):
    return bool(part.get("filename")) or any(
        isinstance(header, dict)
        and str(header.get("name", "")).lower() == "content-disposition"
        and str(header.get("value", "")).lower().startswith("attachment")
        for header in part.get("headers", [])
    )


def parts(payload):
    stack = [(payload, 0)]
    count = 0
    while stack:
        part, depth = stack.pop()
        count += 1
        if (
            count > 256
            or depth > 20
            or not isinstance(part, dict)
            or not isinstance(part.get("body", {}), dict)
            or not isinstance(part.get("headers", []), list)
            or not isinstance(part.get("parts", []), list)
        ):
            raise AttachmentError("gmail_attachment_invalid")
        yield part
        children = part.get("parts", [])
        if len(children) + len(stack) + count > 256:
            raise AttachmentError("gmail_attachment_invalid")
        stack.extend((child, depth + 1) for child in reversed(children))


def metadata(part):
    raw_name = part.get("filename", "")
    part_id = part.get("partId")
    size = part.get("body", {}).get("size")
    mime = part.get("mimeType", "")
    if (
        not isinstance(raw_name, str)
        or not isinstance(part_id, str)
        or len(part_id) > 128
        or not _PART_ID.fullmatch(part_id)
        or type(size) is not int
        or size < 0
        or not isinstance(mime, str)
    ):
        raise AttachmentError("gmail_attachment_invalid")
    name = raw_name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(
        char for char in name if ord(char) >= 32 and ord(char) != 127
    ).strip()
    name = name.encode("utf-8")[:255].decode("utf-8", "ignore")
    supported = bool(name) and PurePosixPath(name).suffix.lower()[1:] in MEDIA_TYPES
    return {
        "part_id": part_id,
        "filename": name,
        "mime_type": mime[:127],
        "size": size,
        "download_supported": supported and 0 < size <= MAX_FILE_BYTES,
    }


def _view(message, publication_id):
    return publication_view(
        publication_id=publication_id,
        binding_id=message.conversation.ally.binding.id,
        message_id=message.id,
    )


def _result(view):
    result = {"publication_id": view["publication_id"], "state": view["state"]}
    if view["state"] == "ready":
        result["files"] = []
        for file in view["files"]:
            label = (
                file["name"]
                .replace("\\", "\\\\")
                .replace("[", "\\[")
                .replace("]", "\\]")
            )
            result["files"].append(
                {
                    "filename": file["name"],
                    "chat_reference": f"[{label}]({file['open_path']})",
                }
            )
        result["instruction"] = (
            "Include each chat_reference in your reply with its exact destination."
        )
    elif view["state"] == "failed":
        result["error"] = "gmail_attachment_publication_failed"
        result["instruction"] = (
            "The attachment failed file validation or publication. No download link is ready. Explain the failure; do not claim success."
        )
    else:
        result["instruction"] = (
            "Retrieval is pending upload or file inspection. Call attachment_status with this publication_id, at most five times. If still pending, explain that processing is pending; do not say Gmail cannot retrieve attachments."
        )
    return result


def status(message, publication_id):
    deadline = time.monotonic() + STATUS_WAIT_SECONDS
    while True:
        view = _view(message, publication_id)
        remaining = deadline - time.monotonic()
        if view["state"] in {"ready", "failed"} or remaining <= 0:
            return _result(view)
        time.sleep(min(1, remaining))


def download(message, token, gmail_id, part_id, *, fetch):
    if (
        not settings.ALLIES_FILE_STORAGE_ENABLED
        or not settings.ALLIES_FILE_INSPECTION_ENABLED
    ):
        raise AttachmentError("gmail_attachment_unavailable")
    publication_id = uuid5(
        NAMESPACE_URL, f"allies:gmail-attachment:v1:{message.id}:{gmail_id}:{part_id}"
    )
    if FilePublication.objects.filter(pk=publication_id).exists():
        view = _view(message, publication_id)
        if view["state"] != "uploading":
            return _result(view)
        try:
            file = FileVersion.objects.get(publication_id=publication_id)
        except (FileVersion.DoesNotExist, FileVersion.MultipleObjectsReturned) as exc:
            raise FileScopeUnavailable("publication unavailable") from exc
        if (
            file.state == FileState.RECEIVING
            and file.lease_until
            and file.lease_until > timezone.now()
        ):
            return _result(view)
    fetched = fetch(
        token,
        f"/messages/{quote(gmail_id, safe='')}",
        query={"format": "full"},
        max_bytes=MAX_RESPONSE_BYTES,
    )
    selected = [
        part
        for part in parts(fetched.get("payload", {}))
        if part.get("partId") == part_id and is_attachment(part)
    ]
    if len(selected) != 1:
        raise AttachmentError("gmail_attachment_not_found")
    part = selected[0]
    item = metadata(part)
    if item["size"] > MAX_FILE_BYTES:
        raise AttachmentError("gmail_attachment_too_large")
    if not item["download_supported"]:
        raise AttachmentError("gmail_attachment_unsupported")
    body = part.get("body", {})
    attachment_id = body.get("attachmentId")
    if attachment_id is not None:
        if (
            not isinstance(attachment_id, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,2048}", attachment_id) is None
        ):
            raise AttachmentError("gmail_attachment_invalid")
        body = fetch(
            token,
            f"/messages/{quote(gmail_id, safe='')}/attachments/{attachment_id}",
            max_bytes=MAX_RESPONSE_BYTES,
        )
    encoded = body.get("data")
    if (
        not isinstance(encoded, str)
        or len(encoded) > 4 * ((MAX_FILE_BYTES + 2) // 3)
        or re.fullmatch(r"[A-Za-z0-9_-]*={0,2}", encoded) is None
        or type(body.get("size")) is not int
        or body["size"] != item["size"]
    ):
        raise AttachmentError("gmail_attachment_invalid")
    try:
        content = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
        )
    except ValueError as exc:
        raise AttachmentError("gmail_attachment_invalid") from exc
    if not content or len(content) != item["size"] or len(content) > MAX_FILE_BYTES:
        raise AttachmentError("gmail_attachment_invalid")
    try:
        view = reserve_publication(
            binding_id=message.conversation.ally.binding.id,
            message_id=message.id,
            publication_id=publication_id,
            files=[
                {
                    "source_version_id": str(uuid5(publication_id, "source")),
                    "name": item["filename"],
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            ],
        )
    except FileConflict as exc:
        raise AttachmentError("gmail_attachment_conflict") from exc
    except (FileValidation, QueueFull) as exc:
        raise AttachmentError("gmail_attachment_invalid") from exc
    try:
        file = view["files"][0]
        if view["state"] == "uploading":
            receive_publication_file(
                binding_id=message.conversation.ally.binding.id,
                message_id=message.id,
                publication_id=publication_id,
                file_id=file["id"],
                generation=file["generation"],
                revision=view["revision"],
                lease_token=None,
                content_length=str(len(content)),
                stream=BytesIO(content),
            )
    except FileConflict:
        return _result(_view(message, publication_id))
    except (FileValidation, QueueFull) as exc:
        raise AttachmentError("gmail_attachment_invalid") from exc
    except (FileUnavailable, OSError, RuntimeError) as exc:
        raise AttachmentError("gmail_attachment_unavailable") from exc
    return _result(_view(message, publication_id))
