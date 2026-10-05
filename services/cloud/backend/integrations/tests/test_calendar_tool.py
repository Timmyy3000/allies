import hashlib
from urllib.error import HTTPError
from uuid import uuid4

import pytest
from django.utils import timezone

from integrations.exceptions import IntegrationInvalid
from integrations.models import (
    PROVIDER_CALENDAR,
    IntegrationSecret,
    IntegrationToolCall,
)
from integrations.services import calendar_tool
from integrations.services.google_oauth import MintedAccess
from integrations.services.grants import check_grant, set_ally_grant
from integrations.services.vault import seal_refresh_token
from integrations.tests.test_gmail_tool import (  # noqa: F401
    _next_message,
    _turn,
    dispatch_records,
    gmail_settings,
)

GUEST_EVENT = {
    "id": "e1",
    "summary": "Standup",
    "start": {"dateTime": "2026-10-01T09:00:00Z"},
    "end": {"dateTime": "2026-10-01T09:15:00Z"},
    "attendees": [
        {"email": "me@gmail.com", "self": True},
        {"email": "bob@example.com", "responseStatus": "accepted"},
    ],
}
SOLO_EVENT = {"id": "e2", "summary": "Focus", "start": {"date": "2026-10-02"}}
LUNCH = {
    "action": "create_event",
    "summary": "Lunch",
    "start": "2026-10-03T12:00:00+01:00",
    "end": "2026-10-03T13:00:00+01:00",
}


@pytest.fixture
def calendar(dispatch_records, gmail_settings, monkeypatch):  # noqa: F811
    workspace, binding, conversation, message = dispatch_records
    conversation.is_default = False
    conversation.save()
    ciphertext, version = seal_refresh_token("refresh.live")
    secret = IntegrationSecret.objects.create(
        workspace=workspace,
        provider_key=PROVIDER_CALENDAR,
        account_ref_hash=hashlib.sha256(b"acct").hexdigest(),
        account_email="me@gmail.com",
        ciphertext=bytes(ciphertext),
        key_version=version,
    )
    set_ally_grant(secret=secret, ally=binding.ally, level="write")
    monkeypatch.setattr(
        calendar_tool,
        "refresh_access_token",
        lambda secret: MintedAccess("ya29.live", timezone.now()),
    )
    calls = []

    def fake_calendar(token, path, *, query=None, body=None, method="GET"):
        calls.append((method, path, query, body))
        if path == "/events" and method == "GET":
            return {"items": [GUEST_EVENT, SOLO_EVENT]}
        if path == "/events":
            return {"id": "new1", **body}
        if path == "/events/e1":
            return GUEST_EVENT if method in {"GET", "PATCH"} else {}
        if path == "/events/e2":
            return SOLO_EVENT if method in {"GET", "PATCH"} else {}
        raise HTTPError("u", 404, "nf", {}, None)

    monkeypatch.setattr(calendar_tool, "_calendar", fake_calendar)
    return {
        "secret": secret,
        "ally": binding.ally,
        "binding": binding,
        "conversation": conversation,
        "turn": _turn(message, binding),
        "calls": calls,
    }


def run(turn, arguments, call_id=None):
    return calendar_tool.execute_calendar_tool(
        **turn, call_id=call_id or uuid4(), arguments=arguments
    )


def _later_turn(calendar):
    message = _next_message(calendar["conversation"], 2)
    return _turn(message, calendar["binding"])


def test_list_events_is_compact_and_hides_the_owner_guest(calendar):
    status, result = run(calendar["turn"], {"action": "list_events"})
    assert status == 200
    assert result["events"][0]["attendees"] == [
        {"email": "bob@example.com", "response": "accepted"}
    ]
    assert calendar["calls"][0][2]["singleEvents"] == "true"
    assert not IntegrationToolCall.objects.exists(), "events are not persisted"


def test_read_grant_cannot_write_and_no_connection_is_denied(calendar):
    set_ally_grant(secret=calendar["secret"], ally=calendar["ally"], level="read")
    assert run(calendar["turn"], {"action": "list_events"})[0] == 200
    status, result = run(calendar["turn"], LUNCH)
    assert (status, result["error"]) == (403, "calendar_not_granted")
    IntegrationSecret.objects.update(revoked_at=timezone.now())
    status, result = run(calendar["turn"], {"action": "list_events"})
    assert (status, result["error"]) == (403, "calendar_not_connected")


def test_solo_writes_need_no_confirmation_and_notify_nobody(calendar):
    status, result = run(calendar["turn"], LUNCH)
    assert (status, result["status"]) == (200, "created")
    method, _, query, body = calendar["calls"][-1]
    assert (method, query) == ("POST", {"sendUpdates": "none"})
    assert body["start"] == {"dateTime": "2026-10-03T12:00:00+01:00"}
    status, result = run(calendar["turn"], {"action": "delete_event", "event_id": "e2"})
    assert (status, result["status"]) == (200, "deleted")
    assert calendar["calls"][-1][:3] == (
        "DELETE",
        "/events/e2",
        {"sendUpdates": "none"},
    )


def test_all_day_and_naive_times(calendar):
    status, _ = run(
        calendar["turn"], {**LUNCH, "start": "2026-10-03", "end": "2026-10-04"}
    )
    assert status == 200
    assert calendar["calls"][-1][3]["start"] == {"date": "2026-10-03"}
    status, result = run(calendar["turn"], {**LUNCH, "start": "2026-10-03T12:00:00"})
    assert (status, result["error"]) == (422, "invalid_calendar_request")


def test_guests_need_a_confirmation_from_an_earlier_turn_and_it_works_once(calendar):
    invite = {**LUNCH, "attendees": ["bob@example.com"]}
    status, prepared = run(calendar["turn"], invite)
    assert (status, prepared["status"]) == (200, "confirmation_required")
    assert prepared["notifies"] == ["bob@example.com"]
    assert calendar["calls"] == []
    ref = prepared["confirmation_ref"]

    status, result = run(calendar["turn"], {**invite, "confirmation_ref": ref})
    assert (status, result["error"]) == (422, "confirmation_required")

    later = _later_turn(calendar)
    changed = {**invite, "attendees": ["eve@example.com"], "confirmation_ref": ref}
    assert run(later, changed)[1]["error"] == "confirmation_required"
    assert calendar["calls"] == []

    status, result = run(later, {**invite, "confirmation_ref": ref})
    assert (status, result["status"]) == (200, "created")
    assert calendar["calls"][-1][2] == {"sendUpdates": "all"}
    status, result = run(later, {**invite, "confirmation_ref": ref})
    assert (status, result["error"]) == (409, "confirmation_used")
    assert len(calendar["calls"]) == 1


def test_deleting_or_updating_an_event_with_guests_is_gated(calendar):
    args = {"action": "delete_event", "event_id": "e1"}
    _, prepared = run(calendar["turn"], args)
    assert prepared["status"] == "confirmation_required"
    assert prepared["notifies"] == ["bob@example.com"]
    assert prepared["event"]["summary"] == "Standup"
    assert all(call[0] == "GET" for call in calendar["calls"])
    _, result = run(
        calendar["turn"], {"action": "update_event", "event_id": "e1", "summary": "x"}
    )
    assert result["status"] == "confirmation_required"
    later = _later_turn(calendar)
    status, result = run(
        later, {**args, "confirmation_ref": prepared["confirmation_ref"]}
    )
    assert (status, result["status"]) == (200, "deleted")
    assert calendar["calls"][-1][:3] == ("DELETE", "/events/e1", {"sendUpdates": "all"})


def test_retry_with_the_same_call_id_replays_instead_of_writing_twice(calendar):
    call_id = uuid4()
    first = run(calendar["turn"], LUNCH, call_id)
    again = run(calendar["turn"], LUNCH, call_id)
    assert first == again
    assert [call[0] for call in calendar["calls"]] == ["POST"]


def test_lost_write_response_is_reported_unknown_never_replayed(calendar, monkeypatch):
    def boom(*args, **kwargs):
        raise HTTPError("u", 502, "bad gateway", {}, None)

    monkeypatch.setattr(calendar_tool, "_calendar", boom)
    call_id = uuid4()
    status, result = run(calendar["turn"], LUNCH, call_id)
    assert (status, result["error"]) == (409, "write_outcome_unknown")
    assert run(calendar["turn"], LUNCH, call_id)[1]["error"] == "write_outcome_unknown"


def test_calendar_grants_use_read_and_write_only(calendar):
    decision = check_grant(secret=calendar["secret"], ally=calendar["ally"])
    assert "calendar write" in decision.tool_allowlist
    assert not any(op.startswith("gmail") for op in decision.tool_allowlist)
    with pytest.raises(IntegrationInvalid):
        set_ally_grant(secret=calendar["secret"], ally=calendar["ally"], level="send")


@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "get_event"},
        {"action": "list_events", "event_id": "e1"},
        {"action": "update_event", "event_id": "e1"},
        {"action": "create_event", "summary": "x", "start": "2026-10-03"},
        {**LUNCH, "attendees": ["not-an-address"]},
        {"action": "delete_event", "event_id": "e1", "summary": "x"},
    ],
)
def test_malformed_requests_are_rejected_before_any_call(calendar, arguments):
    status, result = run(calendar["turn"], arguments)
    assert (status, result["error"]) == (422, "invalid_calendar_request")
    assert calendar["calls"] == []


def test_every_event_detail_reaches_google_in_its_own_shape(calendar):
    status, result = run(
        calendar["turn"],
        {
            **LUNCH,
            "color": "graphite",
            "visibility": "private",
            "busy": "free",
            "reminder_minutes": [10, 60],
            "guests_can_modify": False,
            "guests_can_invite": False,
            "guests_can_see_guests": True,
            "add_meet": True,
        },
    )
    assert (status, result["status"]) == (200, "created")
    _, _, query, body = calendar["calls"][-1]
    assert query == {"sendUpdates": "none", "conferenceDataVersion": 1}
    assert body["colorId"] == "8"
    assert (body["visibility"], body["transparency"]) == ("private", "transparent")
    assert body["reminders"] == {
        "useDefault": False,
        "overrides": [
            {"method": "popup", "minutes": 10},
            {"method": "popup", "minutes": 60},
        ],
    }
    assert (
        body["guestsCanModify"],
        body["guestsCanInviteOthers"],
        body["guestsCanSeeOtherGuests"],
    ) == (False, False, True)
    assert body["conferenceData"]["createRequest"]["conferenceSolutionKey"] == {
        "type": "hangoutsMeet"
    }


def test_colour_names_map_both_ways_and_default_clears_it(calendar):
    assert (
        run(
            calendar["turn"],
            {"action": "update_event", "event_id": "e2", "color": "tomato"},
        )[0]
        == 200
    )
    assert calendar["calls"][-1][3] == {"colorId": "11"}
    assert (
        run(
            calendar["turn"],
            {"action": "update_event", "event_id": "e2", "color": "default"},
        )[0]
        == 200
    )
    assert calendar["calls"][-1][3] == {"colorId": None}
    assert calendar_tool._event({"id": "x", "colorId": "9"})["color"] == "blueberry"
    assert calendar_tool._event({"id": "x"})["color"] == "default"


def test_recurring_events_and_event_output_details(calendar):
    status, _ = run(
        calendar["turn"],
        {
            **LUNCH,
            "time_zone": "Europe/London",
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO"],
        },
    )
    assert status == 200
    assert calendar["calls"][-1][3]["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO"]
    event = calendar_tool._event(
        {
            "id": "e9",
            "recurrence": ["RRULE:FREQ=DAILY"],
            "recurringEventId": "series",
            "hangoutLink": "https://meet.google.com/abc",
            "reminders": {"useDefault": False, "overrides": [{"minutes": 30}]},
            "transparency": "transparent",
            "visibility": "private",
        }
    )
    assert event["meet_link"] == "https://meet.google.com/abc"
    assert event["recurring_event_id"] == "series"
    assert event["reminder_minutes"] == [30]
    assert (event["busy"], event["visibility"]) == ("free", "private")
    assert calendar_tool._event({"id": "e"})["reminder_minutes"] == "calendar default"


def test_details_on_an_event_with_guests_still_need_confirmation(calendar):
    args = {"action": "update_event", "event_id": "e1", "color": "sage"}
    _, prepared = run(calendar["turn"], args)
    assert prepared["status"] == "confirmation_required"
    assert all(call[0] == "GET" for call in calendar["calls"])
    later = _later_turn(calendar)
    status, result = run(
        later, {**args, "confirmation_ref": prepared["confirmation_ref"]}
    )
    assert (status, result["status"]) == (200, "updated")
    assert calendar["calls"][-1][2] == {"sendUpdates": "all"}


@pytest.mark.parametrize(
    "arguments",
    [
        {**LUNCH, "color": "pink"},
        {**LUNCH, "recurrence": ["FREQ=WEEKLY"]},
        {**LUNCH, "start": "2026-10-03T12:00:00", "time_zone": None},
        {**LUNCH, "recurrence": ["RRULE:FREQ=DAILY"], "start": "2026-10-03T12:00:00Z"},
        {**LUNCH, "reminder_minutes": [99999]},
        {**LUNCH, "visibility": "secret"},
        {"action": "list_events", "color": "sage"},
        {"action": "delete_event", "event_id": "e1", "add_meet": True},
    ],
)
def test_bad_event_details_are_rejected_before_any_call(calendar, arguments):
    status, result = run(calendar["turn"], arguments)
    assert (status, result["error"]) == (422, "invalid_calendar_request")
    assert calendar["calls"] == []
