"""Cloud-owned Calendar adapter; no Google credential ever reaches this machine."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import NAMESPACE_URL, uuid5

INSTRUCTION = (
    "Read and manage the user's primary Google Calendar. "
    "list_events and get_event need the Ally's read access; create_event, update_event "
    "and delete_event need write access. "
    "Times are RFC 3339 with an offset (2026-10-03T12:00:00+01:00), or a plain date "
    "(2026-10-03) for an all-day event; give time_zone when a time has no offset. "
    "list_events starts from now unless time_min is given. "
    "create_event and update_event can also set: color (lavender, sage, grape, flamingo, "
    "banana, tangerine, peacock, graphite, blueberry, basil, tomato, or default to clear), "
    "recurrence (RRULE lines such as RRULE:FREQ=WEEKLY;BYDAY=MO, with time_zone), "
    "reminder_minutes (popup reminders before the event), visibility, busy (busy or free), "
    "add_meet (attach a Google Meet link), and guests_can_modify, guests_can_invite and "
    "guests_can_see_guests. Events come back with the same details, including meet_link. "
    "To colour-code, map each kind of event to one colour and apply it with update_event. "
    "Edit one occurrence of a recurring event by its own event_id, or the whole series "
    "by passing its recurring_event_id as event_id. "
    "Changes that notify other people (an event with attendees, or updating or "
    "deleting an event that has them) return confirmation_required first: show the user "
    "the event and everyone who will be notified, and ask them to confirm. Only after "
    "the user confirms in a later message, call the same action again with the same "
    "fields and the returned confirmation_ref. Changes that notify nobody go straight "
    "through. Never claim a change was made without a successful result. "
    "If the tool reports Calendar is not connected or not granted, tell the user to "
    "connect Calendar or grant this Ally access in Allies."
)
SCHEMA = {
    "type": "function",
    "function": {
        "name": "allies_calendar",
        "description": INSTRUCTION,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list_events",
                        "get_event",
                        "create_event",
                        "update_event",
                        "delete_event",
                    ],
                },
                "time_min": {"type": "string", "maxLength": 40},
                "time_max": {"type": "string", "maxLength": 40},
                "query": {"type": "string", "maxLength": 512},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 50},
                "event_id": {"type": "string", "maxLength": 128},
                "summary": {"type": "string", "maxLength": 1024},
                "start": {"type": "string", "maxLength": 40},
                "end": {"type": "string", "maxLength": 40},
                "time_zone": {
                    "type": "string",
                    "maxLength": 64,
                    "description": "IANA name such as Europe/London.",
                },
                "description": {"type": "string", "maxLength": 8192},
                "location": {"type": "string", "maxLength": 1024},
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 50,
                    "description": "Email addresses; replaces the guest list on update.",
                },
                "confirmation_ref": {"type": "string", "maxLength": 36},
                "color": {
                    "type": "string",
                    "enum": [
                        "lavender",
                        "sage",
                        "grape",
                        "flamingo",
                        "banana",
                        "tangerine",
                        "peacock",
                        "graphite",
                        "blueberry",
                        "basil",
                        "tomato",
                        "default",
                    ],
                },
                "recurrence": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 300},
                    "maxItems": 5,
                    "description": "RRULE, EXRULE, RDATE or EXDATE lines.",
                },
                "reminder_minutes": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0, "maximum": 40320},
                    "maxItems": 5,
                    "description": "Minutes before the start; replaces the default reminders.",
                },
                "visibility": {
                    "type": "string",
                    "enum": ["default", "public", "private", "confidential"],
                },
                "busy": {"type": "string", "enum": ["busy", "free"]},
                "add_meet": {
                    "type": "boolean",
                    "description": "Attach a new Google Meet link.",
                },
                "guests_can_modify": {"type": "boolean"},
                "guests_can_invite": {"type": "boolean"},
                "guests_can_see_guests": {"type": "boolean"},
            },
        },
    },
}
_MAX_BYTES = 64 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# ponytail: copy of the allies_gmail relay; extract a shared one at the third integration.
def handle_calendar(args, **kwargs):
    from tools.allies_routines import context
    from tools.approval import _approval_tool_call_id

    current = context.get()
    tool_call_id = _approval_tool_call_id.get()
    if current is None or not tool_call_id:
        return json.dumps({"error": "calendar_tool_unavailable"})
    token, origin = current
    call_id = str(uuid5(NAMESPACE_URL, "allies-calendar-tool:" + tool_call_id))
    raw = json.dumps(
        {"call_id": call_id, "integration": "calendar", "arguments": args}
    ).encode()
    if len(raw) > _MAX_BYTES:
        return json.dumps({"error": "calendar_request_too_large"})
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
            "error": "calendar_service_unavailable",
            "instruction": "The outcome is unconfirmed. Do not claim a change was made; list events to check before retrying.",
        }
    )
