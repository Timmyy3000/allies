"""Gmail tool calls relayed from Foundry for the Ally that dispatched a turn.

Every call re-checks the connection and the Ally's live grant, refreshes a
short-lived access token in-process, and talks to the Gmail API from Cloud,
so no Google credential ever leaves Cloud. Sending needs a confirmation issued
by ``prepare_send`` in an earlier user turn of the same conversation, bound to
the exact message, and each confirmation sends at most once.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from chat.models import DispatchOutbox, Message
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability

from ..exceptions import IntegrationUnavailable, ProviderUnavailable, RefreshRevoked
from ..models import PROVIDER_GMAIL, IntegrationSecret, IntegrationToolCall
from .google_oauth import gmail_enabled, refresh_access_token
from .grants import check_gmail_grant

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_TIMEOUT_SECONDS = 8
MAX_BODY_CHARS = 12_000
_ADDRESS = re.compile(r"[^@\s,<>\"]+@[^@\s,<>\"]+\.[^@\s,<>\"]+")
_GMAIL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_OPERATION = {
    "search": "gmail search",
    "get": "gmail get",
    "list_labels": "gmail get",
    "create_label": "gmail organize",
    "modify": "gmail organize",
    "prepare_send": "gmail send",
    "send": "gmail send",
}
# Organising never moves mail toward deletion; trash/spam stay the user's call.
_BLOCKED_LABELS = {"TRASH", "SPAM"}
_FIELDS = {
    "search": {"query", "max_results"},
    "get": {"message_id"},
    "list_labels": set(),
    "create_label": {"label"},
    "modify": {"message_ids", "add_labels", "remove_labels"},
    "prepare_send": {"to", "cc", "subject", "body", "thread_id"},
    "send": {"to", "cc", "subject", "body", "thread_id", "confirmation_ref"},
}


class GmailToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal[
        "search",
        "get",
        "list_labels",
        "create_label",
        "modify",
        "prepare_send",
        "send",
    ]
    query: str | None = Field(default=None, max_length=512)
    max_results: int | None = Field(default=None, ge=1, le=10)
    message_id: str | None = Field(default=None, pattern=_GMAIL_ID.pattern)
    to: list[str] | None = Field(default=None, min_length=1, max_length=20)
    cc: list[str] | None = Field(default=None, max_length=20)
    subject: str | None = Field(default=None, max_length=998)
    body: str | None = Field(default=None, max_length=16_384)
    thread_id: str | None = Field(default=None, pattern=_GMAIL_ID.pattern)
    confirmation_ref: str | None = Field(default=None, max_length=36)
    label: str | None = Field(default=None, min_length=1, max_length=225)
    message_ids: list[str] | None = Field(default=None, min_length=1, max_length=50)
    add_labels: list[str] | None = Field(default=None, max_length=20)
    remove_labels: list[str] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def action_fields(self):
        if self.model_fields_set - _FIELDS[self.action] - {"action"}:
            raise ValueError("unexpected fields for this action")
        if self.action == "get" and not self.message_id:
            raise ValueError("message_id is required")
        if self.action == "create_label" and not self.label:
            raise ValueError("label is required")
        if self.action == "modify":
            if not self.message_ids or not (self.add_labels or self.remove_labels):
                raise ValueError("message_ids and a label change are required")
            if any(not _GMAIL_ID.fullmatch(mid) for mid in self.message_ids):
                raise ValueError("invalid message id")
            if _BLOCKED_LABELS & {x.upper() for x in self.add_labels or []}:
                raise ValueError("trash and spam are not allowed")
        if self.action in {"prepare_send", "send"}:
            if not self.to or self.subject is None or self.body is None:
                raise ValueError("to, subject and body are required")
            for address in [*self.to, *(self.cc or [])]:
                if not _ADDRESS.fullmatch(address):
                    raise ValueError("invalid email address")
            if "\r" in self.subject or "\n" in self.subject:
                raise ValueError("subject must be one line")
        if self.action == "send" and not self.confirmation_ref:
            raise ValueError("confirmation_ref is required")
        return self

    def payload_digest(self) -> str:
        payload = {
            "to": self.to,
            "cc": self.cc or [],
            "subject": self.subject,
            "body": self.body,
            "thread_id": self.thread_id,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def _error(status: int, error: str, instruction: str) -> tuple[int, dict]:
    return status, {"error": error, "instruction": instruction}


NOT_CONNECTED = _error(
    403,
    "gmail_not_connected",
    "Gmail is not connected for this workspace. Ask the user to connect Gmail in Allies.",
)
NOT_GRANTED = _error(
    403,
    "gmail_not_granted",
    "This Ally is not allowed to do that with Gmail. Ask the user to grant it access in Allies.",
)


def execute_gmail_tool(
    *,
    message_id: UUID,
    binding_id: UUID,
    command_fingerprint: str,
    call_id: UUID,
    arguments: dict,
) -> tuple[int, dict]:
    try:
        args = GmailToolRequest.model_validate(arguments)
    except ValidationError:
        return _error(
            422,
            "invalid_gmail_request",
            "Check the action and its fields; ask the user for anything missing.",
        )
    message = Message.objects.select_related(
        "conversation__ally__workspace__owner", "conversation__ally__binding"
    ).get(pk=message_id, sender="user", origin="send", deleted_at__isnull=True)
    ally = message.conversation.ally
    workspace = ally.workspace
    if ally.binding.id != binding_id or not workspace.is_active:
        raise PermissionError("gmail tool binding unavailable")
    require_workspace_capability(
        user=workspace.owner,
        workspace_id=workspace.id,
        capability=Capability.WORKSPACE_WRITE,
    )
    outbox = DispatchOutbox.objects.get(message=message)
    if not command_fingerprint or outbox.command_fingerprint != command_fingerprint:
        raise PermissionError("gmail tool dispatch unavailable")

    digest = hashlib.sha256(
        json.dumps(arguments, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    replayed = _replay(message, call_id, digest)
    if replayed is not None:
        return replayed

    if not gmail_enabled():
        return NOT_CONNECTED
    secret = IntegrationSecret.objects.filter(
        workspace=workspace, provider_key=PROVIDER_GMAIL, revoked_at=None
    ).first()
    if secret is None:
        return NOT_CONNECTED
    decision = check_gmail_grant(secret=secret, ally=ally)
    if not decision.allowed or _OPERATION[args.action] not in decision.tool_allowlist:
        return NOT_GRANTED

    if args.action == "prepare_send":
        return _prepare_send(message, call_id, digest, args)
    if args.action == "send":
        return _send(message, call_id, digest, args, secret)
    try:
        token = refresh_access_token(secret).access_token
        if args.action == "search":
            return 200, _search(token, args.query or "", args.max_results or 10)
        if args.action == "list_labels":
            return 200, {"labels": _labels(token)}
        if args.action == "create_label":
            label = _gmail(token, "/labels", body={"name": args.label})
            return 200, {"label_id": label.get("id"), "name": label.get("name")}
        if args.action == "modify":
            return _modify(token, args)
        return 200, _get(token, args.message_id)
    except RefreshRevoked:
        return NOT_CONNECTED
    except HTTPError as exc:
        if exc.code == 404:
            return _error(
                422, "gmail_message_not_found", "Search again for the message."
            )
        if exc.code == 409:
            return _error(
                422, "gmail_label_exists", "That label already exists; use it."
            )
        if exc.code == 400:
            return _error(422, "gmail_rejected", "Gmail rejected the request.")
        return 503, {"error": "gmail_unavailable"}
    except (
        IntegrationUnavailable,
        ProviderUnavailable,
        URLError,
        OSError,
        ValueError,
    ):
        return 503, {"error": "gmail_unavailable"}


def _prepare_send(message, call_id, digest, args) -> tuple[int, dict]:
    response = {
        "status": "confirmation_required",
        "confirmation_ref": str(uuid4()),
        "payload_sha256": args.payload_digest(),
        "instruction": (
            "Show the user the recipients, subject and body and ask them to confirm. "
            "Only after they confirm in a later message, call send with exactly the "
            "same fields and this confirmation_ref."
        ),
    }
    try:
        with transaction.atomic():
            IntegrationToolCall.objects.create(
                message=message,
                call_id=call_id,
                request_digest=digest,
                response=response,
            )
    except IntegrityError:
        return _replay(message, call_id, digest)
    return 200, response


def _replay(message, call_id, digest) -> tuple[int, dict] | None:
    stored = IntegrationToolCall.objects.filter(
        message=message, call_id=call_id
    ).first()
    if stored is None:
        return None
    if stored.request_digest != digest:
        return _error(422, "invalid_gmail_request", "Tool call identity reused.")
    if stored.response.get("status") == "send_pending":
        return _unknown_send()
    return 200, stored.response


def _send(message, call_id, digest, args, secret) -> tuple[int, dict]:
    confirmed = IntegrationToolCall.objects.filter(
        message__conversation_id=message.conversation_id,
        message__sequence__lt=message.sequence,
        response__confirmation_ref=args.confirmation_ref,
        response__payload_sha256=args.payload_digest(),
    ).exists()
    if not confirmed:
        return _error(
            422,
            "confirmation_required",
            "Call prepare_send with this exact message and get the user's "
            "confirmation in a later message before sending.",
        )
    try:
        with transaction.atomic():
            record = IntegrationToolCall.objects.create(
                message=message,
                call_id=call_id,
                request_digest=digest,
                response={"status": "send_pending"},
                consumed_ref=args.confirmation_ref,
            )
    except IntegrityError:
        twin = _replay(message, call_id, digest)
        if twin is not None:
            return twin
        return _error(
            409,
            "confirmation_used",
            "This confirmation was already used. Do not send again unless the user asks.",
        )
    try:
        token = refresh_access_token(secret).access_token
        raw = _mime(token, args)
    except RefreshRevoked:
        record.delete()
        return NOT_CONNECTED
    except (
        IntegrationUnavailable,
        ProviderUnavailable,
        HTTPError,
        URLError,
        OSError,
        ValueError,
    ):
        record.delete()
        return 503, {"error": "gmail_unavailable"}
    body = {"raw": raw}
    if args.thread_id:
        body["threadId"] = args.thread_id
    try:
        sent = _gmail(token, "/messages/send", body=body)
    except HTTPError as exc:
        if 400 <= exc.code < 500:
            record.delete()
            return _error(422, "gmail_rejected", "Gmail rejected the message.")
        return _unknown_send()
    except (URLError, OSError, ValueError):
        return _unknown_send()
    record.response = {
        "status": "sent",
        "gmail_message_id": sent.get("id"),
        "thread_id": sent.get("threadId"),
    }
    record.save(update_fields=["response"])
    return 200, record.response


def _unknown_send() -> tuple[int, dict]:
    return _error(
        409,
        "send_outcome_unknown",
        "It is unknown whether the email was sent. Search in:sent before doing anything else; never resend blindly.",
    )


def _gmail(token: str, path: str, *, query: dict | None = None, body=None) -> dict:
    url = GMAIL_API + path + ("?" + urlencode(query, doseq=True) if query else "")
    request = Request(
        url,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="GET" if body is None else "POST",
    )
    with urlopen(request, timeout=GMAIL_TIMEOUT_SECONDS) as response:
        raw = response.read(5_000_001)
    payload = json.loads(raw.decode()) if raw else {}
    if not isinstance(payload, dict):
        raise ProviderUnavailable("gmail response invalid")
    return payload


def _headers(message: dict) -> dict:
    wanted = {"from", "to", "cc", "subject", "date", "message-id"}
    return {
        item["name"].lower(): item.get("value", "")
        for item in message.get("payload", {}).get("headers", [])
        if isinstance(item, dict) and str(item.get("name", "")).lower() in wanted
    }


def _summary(message: dict) -> dict:
    headers = _headers(message)
    return {
        "message_id": message.get("id"),
        "thread_id": message.get("threadId"),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "snippet": html.unescape(message.get("snippet", "")),
    }


def _search(token: str, query: str, limit: int) -> dict:
    listing = _gmail(token, "/messages", query={"q": query, "maxResults": limit})
    ids = [item["id"] for item in listing.get("messages", []) if "id" in item]
    metadata = {
        "format": "metadata",
        "metadataHeaders": ["From", "To", "Subject", "Date"],
    }
    with ThreadPoolExecutor(max_workers=5) as pool:
        messages = list(
            pool.map(
                lambda gid: _gmail(token, f"/messages/{quote(gid)}", query=metadata),
                ids,
            )
        )
    return {"messages": [_summary(message) for message in messages]}


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
        "utf-8", "replace"
    )


def _text(part: dict) -> tuple[str, str]:
    mime = part.get("mimeType", "")
    data = part.get("body", {}).get("data")
    if data and mime in {"text/plain", "text/html"}:
        return mime, _decode(data)
    found = ("", "")
    for child in part.get("parts", []) or []:
        child_mime, child_text = _text(child)
        if child_mime == "text/plain":
            return child_mime, child_text
        if child_text and not found[1]:
            found = (child_mime, child_text)
    return found


def _get(token: str, gmail_id: str) -> dict:
    message = _gmail(token, f"/messages/{quote(gmail_id)}", query={"format": "full"})
    mime, text = _text(message.get("payload", {}))
    if mime == "text/html":
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    result = _summary(message)
    result["cc"] = _headers(message).get("cc", "")
    result["body"] = text[:MAX_BODY_CHARS]
    result["truncated"] = len(text) > MAX_BODY_CHARS
    return result


def _labels(token: str) -> list[dict]:
    listing = _gmail(token, "/labels")
    return [
        {"id": item.get("id"), "name": item.get("name"), "type": item.get("type")}
        for item in listing.get("labels", [])
    ]


def _modify(token: str, args: GmailToolRequest) -> tuple[int, dict]:
    by_name = {item["name"].lower(): item["id"] for item in _labels(token)}
    known = set(by_name.values())

    def resolve(names):
        ids = []
        for name in names or []:
            label_id = name if name in known else by_name.get(name.lower())
            if label_id is None:
                raise LookupError(name)
            ids.append(label_id)
        return ids

    try:
        add, remove = resolve(args.add_labels), resolve(args.remove_labels)
    except LookupError as missing:
        return _error(
            422,
            "gmail_label_not_found",
            f"No label named {missing}. Use list_labels, or create_label first.",
        )
    _gmail(
        token,
        "/messages/batchModify",
        body={"ids": args.message_ids, "addLabelIds": add, "removeLabelIds": remove},
    )
    return 200, {"status": "updated", "message_count": len(args.message_ids)}


def _mime(token: str, args: GmailToolRequest) -> str:
    email = EmailMessage()
    email["To"] = ", ".join(args.to)
    if args.cc:
        email["Cc"] = ", ".join(args.cc)
    email["Subject"] = args.subject
    if args.thread_id:
        thread = _gmail(
            token,
            f"/threads/{quote(args.thread_id)}",
            query={"format": "metadata", "metadataHeaders": ["Message-ID"]},
        )
        messages = thread.get("messages") or []
        parent = _headers(messages[-1]).get("message-id") if messages else None
        if parent:
            email["In-Reply-To"] = parent
            email["References"] = parent
    email.set_content(args.body)
    return base64.urlsafe_b64encode(email.as_bytes()).decode()
