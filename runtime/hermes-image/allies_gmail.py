"""Cloud-owned Gmail adapter; no Google credential ever reaches this machine."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import NAMESPACE_URL, uuid5

INSTRUCTION = (
    "Read, organise and send email from the workspace's connected Gmail account. "
    "search, get, list_labels, download_attachment and attachment_status need the Ally's "
    "read access; create_label, modify, "
    "prepare_send and send need full access. "
    "To organise: modify changes labels on up to 50 message ids at once, by label name "
    "or id. Mark read by removing UNREAD, mark unread by adding UNREAD, archive by "
    "removing INBOX, star by adding STARRED; create_label makes a new label. "
    "Trash and spam are not available. "
    "To retrieve attachments: get exposes attachment metadata and part_id; call "
    "download_attachment with message_id and the selected part_id, one attachment at "
    "a time (an empty part_id selects the root). For pending publications, call "
    "attachment_status with publication_id; Cloud waits up to 20 seconds per call. "
    "Make at most five status checks per turn. Only when ready, include the returned "
    "chat_reference exactly in your final answer. Never claim an attachment was "
    "downloaded or returned before ready. If still pending after five checks, preserve "
    "publication_id in the receipt and explain that retrieval succeeded and inspection "
    "is pending; do not say Gmail cannot retrieve attachments. "
    "To send: call prepare_send with the exact message, show the user the recipients, "
    "subject and body, and ask them to confirm. Only after the user confirms in a later "
    "message, call send with the same fields and the returned confirmation_ref. "
    "Never claim an email was sent without a successful send result. "
    "If the tool reports Gmail is not connected or not granted, tell the user to connect "
    "Gmail or grant this Ally access in Allies."
)
SCHEMA = {
    "type": "function",
    "function": {
        "name": "allies_gmail",
        "description": INSTRUCTION,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "search",
                        "get",
                        "download_attachment",
                        "attachment_status",
                        "list_labels",
                        "create_label",
                        "modify",
                        "prepare_send",
                        "send",
                    ],
                },
                "query": {
                    "type": "string",
                    "maxLength": 512,
                    "description": "Gmail search syntax, for search.",
                },
                "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                "message_id": {"type": "string", "maxLength": 64},
                "part_id": {
                    "type": "string",
                    "maxLength": 128,
                    "description": "Selected attachment part from get; empty for the root.",
                },
                "publication_id": {
                    "type": "string",
                    "format": "uuid",
                    "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                    "description": "Canonical UUID returned by download_attachment.",
                },
                "to": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                "cc": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                "subject": {"type": "string", "maxLength": 998},
                "body": {"type": "string", "maxLength": 16384},
                "thread_id": {
                    "type": "string",
                    "maxLength": 64,
                    "description": "Reply within this thread.",
                },
                "confirmation_ref": {"type": "string", "maxLength": 36},
                "label": {
                    "type": "string",
                    "maxLength": 225,
                    "description": "New label name, for create_label.",
                },
                "message_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 50,
                    "description": "Messages to change, for modify.",
                },
                "add_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 20,
                },
                "remove_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 20,
                },
            },
        },
    },
}
_MAX_BYTES = 64 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def handle_gmail(args, **kwargs):
    from tools.allies_routines import context
    from tools.approval import _approval_tool_call_id

    current = context.get()
    tool_call_id = _approval_tool_call_id.get()
    if current is None or not tool_call_id:
        return json.dumps({"error": "gmail_tool_unavailable"})
    token, origin = current
    call_id = str(uuid5(NAMESPACE_URL, "allies-gmail-tool:" + tool_call_id))
    raw = json.dumps(
        {"call_id": call_id, "integration": "gmail", "arguments": args}
    ).encode()
    if len(raw) > _MAX_BYTES:
        return json.dumps({"error": "gmail_request_too_large"})
    request = Request(
        origin + "/api/v1/runtime/integrations/tool",
        data=raw,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    for _ in range(2):
        try:
            try:
                response = build_opener(NoRedirect).open(request, timeout=30)
            except HTTPError as exc:
                response = exc
            with response:
                status = response.status
                body = response.read(_MAX_BYTES + 1)
            if len(body) > _MAX_BYTES:
                break
            result = json.loads(body)
            if not isinstance(result, dict):
                break
            if status < 500:
                return json.dumps(result)
        except (URLError, OSError, ValueError):
            pass
    return json.dumps(
        {
            "error": "gmail_service_unavailable",
            "instruction": "The outcome is unconfirmed. Do not claim an email was sent; check before retrying.",
        }
    )
