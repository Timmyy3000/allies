"""Cloud routine adapter; credentials stay in the active turn's context."""

import json
from contextvars import ContextVar
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import NAMESPACE_URL, uuid5

context = ContextVar("allies_routine_tool", default=None)
INSTRUCTION = (
    "Use allies_routines for all scheduled work, including one-time reminders. "
    "If its schema is deferred, discover it with tool_search/tool_describe and invoke it through tool_call. "
    "Never use local cron, terminal scheduling, or promise a schedule without a saved tool result. "
    "On a clear request, create immediately and report the saved title and schedule. "
    "Write execution_prompt for your future self with all needed context. "
    "Schedule time is critical: use explicit conversation context or ask; never guess. "
    "Use the user's provided browser timezone; if unavailable, ask. "
    "For deletion, inspect then request_delete. If the structured routine action context "
    "already confirms deletion, follow the tool's confirmation instruction and delete. "
    "Otherwise ask the user if they are sure and delete only after confirmation in a later user turn. "
    "Inspect before changing a routine."
)
SCHEMA = {
    "type": "function",
    "function": {
        "name": "allies_routines",
        "description": INSTRUCTION,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create",
                        "list",
                        "inspect",
                        "update",
                        "pause",
                        "resume",
                        "request_delete",
                        "delete",
                    ],
                },
                "routine_id": {"type": "string"},
                "expected_revision": {"type": "integer", "minimum": 1},
                "title": {"type": "string", "maxLength": 120},
                "execution_prompt": {"type": "string", "maxLength": 16384},
                "schedule": {
                    "type": "object",
                    "description": (
                        "One-time: {kind:once,local_at:YYYY-MM-DDTHH:MM:SS,timezone:IANA}. "
                        "Recurring: {kind:recurring,frequency:daily|weekly|monthly,local_time:HH:MM:SS,timezone:IANA}. "
                        "Weekly adds days_of_week:[1..7] (Monday=1); monthly adds day_of_month:1..31. "
                        "Local times must not have an offset. No extra fields."
                    ),
                },
                "confirmation_ref": {"type": "string"},
                "cursor": {"type": "string"},
            },
        },
    },
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def turn_context(token, origin):
    parsed = urlsplit(origin)
    if (
        not token
        or len(token) > 2048
        or any(c.isspace() for c in token)
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Invalid routine context")
    return (token, origin.rstrip("/"))


def handle_routine(args, **kwargs):
    from tools.approval import _approval_tool_call_id

    current = context.get()
    tool_call_id = _approval_tool_call_id.get()
    if current is None or not tool_call_id:
        return json.dumps({"error": "routine_tool_unavailable"})
    token, origin = current
    call_id = str(uuid5(NAMESPACE_URL, "allies-routine-tool:" + tool_call_id))
    raw = json.dumps({"call_id": call_id, "arguments": args}).encode()
    if len(raw) > 64 * 1024:
        return json.dumps({"error": "routine_request_too_large"})
    request = Request(
        origin + "/api/v1/runtime/routines/tool",
        data=raw,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    for attempt in range(2):
        try:
            try:
                response = build_opener(NoRedirect).open(request, timeout=15)
            except HTTPError as exc:
                response = exc
            with response:
                status = response.status
                body = response.read(64 * 1024 + 1)
            if len(body) > 64 * 1024:
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
            "error": "routine_service_unavailable",
            "instruction": "The save outcome is unconfirmed. Do not claim success; inspect before retrying creation.",
        }
    )
