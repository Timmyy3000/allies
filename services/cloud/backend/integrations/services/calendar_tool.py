"""Calendar tool calls relayed from Foundry for the Ally that dispatched a turn.

Every call re-checks the connection and the Ally's live grant and talks to the
Google Calendar API from Cloud, so no Google credential ever leaves Cloud.
Writes that would notify other people (an event with guests) need a
confirmation issued by an earlier call in an earlier user turn of the same
conversation, bound to the exact request, and each confirmation acts at most once.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction
from django.utils import timezone
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..exceptions import IntegrationUnavailable, ProviderUnavailable, RefreshRevoked
from ..models import PROVIDER_CALENDAR, IntegrationSecret, IntegrationToolCall
from .google_oauth import gmail_enabled, refresh_access_token
from .grants import check_grant
from .turns import resolve_tool_turn, routine_action_unavailable

CALENDAR_API = "https://www.googleapis.com/calendar/v3/calendars/primary"
CALENDAR_TIMEOUT_SECONDS = 8
MAX_DESCRIPTION_CHARS = 2_000
_ADDRESS = re.compile(r"[^@\s,<>\"]+@[^@\s,<>\"]+\.[^@\s,<>\"]+")
_EVENT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_RECURRENCE = re.compile(r"(RRULE|EXRULE|RDATE|EXDATE)[:;][^\r\n]{1,300}")
# Google's fixed event palette; "default" clears the colour back to the calendar's.
COLOR_IDS = {
    "lavender": "1",
    "sage": "2",
    "grape": "3",
    "flamingo": "4",
    "banana": "5",
    "tangerine": "6",
    "peacock": "7",
    "graphite": "8",
    "blueberry": "9",
    "basil": "10",
    "tomato": "11",
}
COLOR_NAMES = {color_id: name for name, color_id in COLOR_IDS.items()}
_DETAILS = {
    "color",
    "recurrence",
    "reminder_minutes",
    "visibility",
    "busy",
    "add_meet",
    "guests_can_modify",
    "guests_can_invite",
    "guests_can_see_guests",
}
_OPERATION = {
    "list_events": "calendar list",
    "get_event": "calendar get",
    "create_event": "calendar write",
    "update_event": "calendar write",
    "delete_event": "calendar write",
}
# Routine turns have no chat message, so replay ledgers are unavailable and writes are refused.
ROUTINE_CALENDAR_ACTIONS = {"list_events", "get_event"}
_FIELDS = {
    "list_events": {"time_min", "time_max", "query", "max_results"},
    "get_event": {"event_id"},
    "create_event": {
        "summary",
        "start",
        "end",
        "time_zone",
        "description",
        "location",
        "attendees",
        "confirmation_ref",
        *_DETAILS,
    },
    "update_event": {
        "event_id",
        "summary",
        "start",
        "end",
        "time_zone",
        "description",
        "location",
        "attendees",
        "confirmation_ref",
        *_DETAILS,
    },
    "delete_event": {"event_id", "confirmation_ref"},
}


def _valid_time(value: str, time_zone: str | None) -> bool:
    try:
        if len(value) == 10:
            date.fromisoformat(value)
            return True
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None or bool(time_zone)


class CalendarToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal[
        "list_events", "get_event", "create_event", "update_event", "delete_event"
    ]
    time_min: str | None = Field(default=None, max_length=40)
    time_max: str | None = Field(default=None, max_length=40)
    query: str | None = Field(default=None, max_length=512)
    max_results: int | None = Field(default=None, ge=1, le=50)
    event_id: str | None = Field(default=None, pattern=_EVENT_ID.pattern)
    summary: str | None = Field(default=None, min_length=1, max_length=1024)
    start: str | None = Field(default=None, max_length=40)
    end: str | None = Field(default=None, max_length=40)
    time_zone: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=8192)
    location: str | None = Field(default=None, max_length=1024)
    attendees: list[str] | None = Field(default=None, max_length=50)
    confirmation_ref: str | None = Field(default=None, max_length=36)
    color: Literal[*COLOR_IDS, "default"] | None = None
    recurrence: list[str] | None = Field(default=None, max_length=5)
    reminder_minutes: list[int] | None = Field(default=None, max_length=5)
    visibility: Literal["default", "public", "private", "confidential"] | None = None
    busy: Literal["busy", "free"] | None = None
    add_meet: bool | None = None
    guests_can_modify: bool | None = None
    guests_can_invite: bool | None = None
    guests_can_see_guests: bool | None = None

    @model_validator(mode="after")
    def action_fields(self):
        if self.model_fields_set - _FIELDS[self.action] - {"action"}:
            raise ValueError("unexpected fields for this action")
        if self.action not in {"create_event", "list_events"} and not self.event_id:
            raise ValueError("event_id is required")
        if self.action == "create_event" and not (
            self.summary and self.start and self.end
        ):
            raise ValueError("summary, start and end are required")
        if self.action == "update_event" and not (
            self.model_fields_set - {"action", "event_id", "confirmation_ref"}
        ):
            raise ValueError("nothing to update")
        for value in (self.start, self.end):
            if value is not None and not _valid_time(value, self.time_zone):
                raise ValueError("times need a date, or a datetime with an offset")
        for value in (self.time_min, self.time_max):
            if value is not None and not _valid_time(value, None):
                raise ValueError("times need a date, or a datetime with an offset")
        for address in self.attendees or []:
            if not _ADDRESS.fullmatch(address):
                raise ValueError("invalid email address")
        for rule in self.recurrence or []:
            if not _RECURRENCE.fullmatch(rule):
                raise ValueError("recurrence needs RRULE/EXRULE/RDATE/EXDATE lines")
        if (
            self.recurrence
            and self.start
            and len(self.start) != 10
            and not self.time_zone
        ):
            raise ValueError("a recurring timed event needs time_zone")
        if any(not 0 <= minutes <= 40_320 for minutes in self.reminder_minutes or []):
            raise ValueError("reminder minutes must be 0 to 40320")
        return self

    def payload_digest(self) -> str:
        payload = self.model_dump(exclude_unset=True, exclude={"confirmation_ref"})
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def _error(status: int, error: str, instruction: str) -> tuple[int, dict]:
    return status, {"error": error, "instruction": instruction}


NOT_CONNECTED = _error(
    403,
    "calendar_not_connected",
    "Calendar is not connected for this workspace. Ask the user to connect it in Allies.",
)
NOT_GRANTED = _error(
    403,
    "calendar_not_granted",
    "This Ally is not allowed to do that with Calendar. Ask the user to grant it access in Allies.",
)


def execute_calendar_tool(
    *,
    message_id: UUID | None = None,
    run_id: UUID | None = None,
    binding_id: UUID,
    command_fingerprint: str,
    call_id: UUID,
    arguments: dict,
) -> tuple[int, dict]:
    try:
        args = CalendarToolRequest.model_validate(arguments)
    except ValidationError:
        return _error(
            422,
            "invalid_calendar_request",
            "Check the action and its fields; ask the user for anything missing.",
        )
    turn = resolve_tool_turn(
        message_id=message_id,
        run_id=run_id,
        binding_id=binding_id,
        command_fingerprint=command_fingerprint,
    )
    ally = turn.ally
    message = turn.message
    if message is None and args.action not in ROUTINE_CALENDAR_ACTIONS:
        return routine_action_unavailable()
    digest = hashlib.sha256(
        json.dumps(arguments, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if message is not None:
        replayed = _replay(message, call_id, digest)
        if replayed is not None:
            return replayed

    if not gmail_enabled():
        return NOT_CONNECTED
    secret = IntegrationSecret.objects.filter(
        workspace=ally.workspace, provider_key=PROVIDER_CALENDAR, revoked_at=None
    ).first()
    if secret is None:
        return NOT_CONNECTED
    decision = check_grant(secret=secret, ally=ally)
    if not decision.allowed or _OPERATION[args.action] not in decision.tool_allowlist:
        return NOT_GRANTED

    try:
        token = refresh_access_token(secret).access_token
        if args.action == "list_events":
            return 200, _list(token, args)
        if args.action == "get_event":
            return 200, _event(
                _calendar(token, f"/events/{quote(args.event_id, safe='')}")
            )
        return _write(message, call_id, digest, args, token)
    except RefreshRevoked:
        return NOT_CONNECTED
    except HTTPError as exc:
        return _http_error(exc)
    except (IntegrationUnavailable, ProviderUnavailable, URLError, OSError, ValueError):
        return 503, {"error": "calendar_unavailable"}


def _http_error(exc: HTTPError) -> tuple[int, dict]:
    if exc.code in {404, 410}:
        return _error(422, "calendar_event_not_found", "List events to find the event.")
    if exc.code == 400:
        return _error(422, "calendar_rejected", "Calendar rejected the request.")
    return 503, {"error": "calendar_unavailable"}


def _replay(message, call_id, digest) -> tuple[int, dict] | None:
    stored = IntegrationToolCall.objects.filter(
        message=message, call_id=call_id
    ).first()
    if stored is None:
        return None
    if stored.request_digest != digest:
        return _error(422, "invalid_calendar_request", "Tool call identity reused.")
    if stored.response.get("status") == "write_pending":
        return _unknown_outcome()
    return 200, stored.response


def _unknown_outcome() -> tuple[int, dict]:
    return _error(
        409,
        "write_outcome_unknown",
        "It is unknown whether the change was made. List events to check before doing anything else; never repeat it blindly.",
    )


def _write(message, call_id, digest, args, token) -> tuple[int, dict]:
    existing = None
    if args.action != "create_event":
        existing = _calendar(token, f"/events/{quote(args.event_id, safe='')}")
    guests = _guests(existing) if existing else []
    notifies = bool(guests or args.attendees)
    consumed_ref = None
    if notifies:
        if not args.confirmation_ref:
            return _prepare(message, call_id, digest, args, existing)
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
                "Call again without a confirmation_ref, show the user what will happen "
                "and who is notified, and get their confirmation in a later message.",
            )
        consumed_ref = args.confirmation_ref
    try:
        with transaction.atomic():
            record = IntegrationToolCall.objects.create(
                message=message,
                call_id=call_id,
                request_digest=digest,
                response={"status": "write_pending"},
                consumed_ref=consumed_ref,
            )
    except IntegrityError:
        twin = _replay(message, call_id, digest)
        if twin is not None:
            return twin
        return _error(
            409,
            "confirmation_used",
            "This confirmation was already used. Do not repeat the change unless the user asks.",
        )
    notify = "all" if notifies else "none"
    try:
        result = _perform(token, args, notify)
    except HTTPError as exc:
        if 400 <= exc.code < 500:
            record.delete()
            return _http_error(exc)
        return _unknown_outcome()
    except (URLError, OSError, ValueError):
        return _unknown_outcome()
    record.response = result
    record.save(update_fields=["response"])
    return 200, result


def _perform(token: str, args: CalendarToolRequest, notify: str) -> dict:
    query = {"sendUpdates": notify}
    if args.add_meet:
        query["conferenceDataVersion"] = 1
    if args.action == "create_event":
        return {
            "status": "created",
            **_event(
                _calendar(
                    token, "/events", query=query, body=_body(args), method="POST"
                )
            ),
        }
    path = f"/events/{quote(args.event_id, safe='')}"
    if args.action == "update_event":
        return {
            "status": "updated",
            **_event(
                _calendar(token, path, query=query, body=_body(args), method="PATCH")
            ),
        }
    try:
        _calendar(token, path, query=query, method="DELETE")
    except HTTPError as exc:
        if exc.code != 410:
            raise
    return {"status": "deleted", "event_id": args.event_id}


def _prepare(message, call_id, digest, args, existing) -> tuple[int, dict]:
    response = {
        "status": "confirmation_required",
        "confirmation_ref": str(uuid4()),
        "payload_sha256": args.payload_digest(),
        "event": _event(existing) if existing else args.model_dump(exclude_unset=True),
        "notifies": sorted(
            {*[g["email"] for g in _guests(existing or {})], *(args.attendees or [])}
        ),
        "instruction": (
            "Show the user the event and everyone who will be notified, and ask them "
            "to confirm. Only after they confirm in a later message, call this action "
            "again with exactly the same fields and this confirmation_ref."
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


def _calendar(token: str, path: str, *, query=None, body=None, method="GET") -> dict:
    url = CALENDAR_API + path + ("?" + urlencode(query, doseq=True) if query else "")
    request = Request(
        url,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urlopen(request, timeout=CALENDAR_TIMEOUT_SECONDS) as response:
        raw = response.read(5_000_001)
    payload = json.loads(raw.decode()) if raw else {}
    if not isinstance(payload, dict):
        raise ProviderUnavailable("calendar response invalid")
    return payload


def _when(value: str, time_zone: str | None) -> dict:
    if len(value) == 10:
        return {"date": value}
    return {"dateTime": value, **({"timeZone": time_zone} if time_zone else {})}


def _body(args: CalendarToolRequest) -> dict:
    body: dict = {}
    for name in ("summary", "description", "location"):
        if name in args.model_fields_set:
            body[name] = getattr(args, name)
    for name in ("start", "end"):
        if name in args.model_fields_set:
            body[name] = _when(getattr(args, name), args.time_zone)
    if "attendees" in args.model_fields_set:
        body["attendees"] = [{"email": address} for address in args.attendees or []]
    if args.color is not None:
        body["colorId"] = COLOR_IDS.get(args.color)
    if args.recurrence is not None:
        body["recurrence"] = args.recurrence
    if args.reminder_minutes is not None:
        body["reminders"] = {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": minutes}
                for minutes in args.reminder_minutes
            ],
        }
    if args.visibility is not None:
        body["visibility"] = args.visibility
    if args.busy is not None:
        body["transparency"] = "transparent" if args.busy == "free" else "opaque"
    for name, key in (
        ("guests_can_modify", "guestsCanModify"),
        ("guests_can_invite", "guestsCanInviteOthers"),
        ("guests_can_see_guests", "guestsCanSeeOtherGuests"),
    ):
        if getattr(args, name) is not None:
            body[key] = getattr(args, name)
    if args.add_meet:
        body["conferenceData"] = {
            "createRequest": {
                "requestId": uuid4().hex,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
    return body


def _guests(event: dict) -> list[dict]:
    return [
        {"email": item.get("email", ""), "response": item.get("responseStatus", "")}
        for item in event.get("attendees", []) or []
        if isinstance(item, dict) and not item.get("self") and item.get("email")
    ]


def _event(event: dict) -> dict:
    description = event.get("description", "") or ""
    return {
        "event_id": event.get("id"),
        "summary": event.get("summary", ""),
        "start": event.get("start", {}),
        "end": event.get("end", {}),
        "location": event.get("location", ""),
        "description": description[:MAX_DESCRIPTION_CHARS],
        "attendees": _guests(event),
        "event_status": event.get("status", ""),
        "link": event.get("htmlLink", ""),
        "color": COLOR_NAMES.get(event.get("colorId"), "default"),
        "recurrence": event.get("recurrence", []),
        "recurring_event_id": event.get("recurringEventId"),
        "meet_link": event.get("hangoutLink", ""),
        "reminder_minutes": _reminders(event),
        "visibility": event.get("visibility", "default"),
        "busy": "free" if event.get("transparency") == "transparent" else "busy",
    }


def _reminders(event: dict):
    reminders = event.get("reminders") or {}
    if reminders.get("useDefault", True):
        return "calendar default"
    return [item.get("minutes") for item in reminders.get("overrides", [])]


def _list(token: str, args: CalendarToolRequest) -> dict:
    query = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": args.max_results or 25,
        "timeMin": _rfc3339(args.time_min) or timezone.now().isoformat(),
    }
    if args.time_max:
        query["timeMax"] = _rfc3339(args.time_max)
    if args.query:
        query["q"] = args.query
    listing = _calendar(token, "/events", query=query)
    return {"events": [_event(item) for item in listing.get("items", [])]}


def _rfc3339(value: str | None) -> str | None:
    if value is None:
        return None
    return f"{value}T00:00:00Z" if len(value) == 10 else value
