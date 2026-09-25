import base64
import email
import hashlib
import json
from io import BytesIO
from urllib.error import HTTPError, URLError
from uuid import uuid4

import pytest
from django.db import transaction
from django.test import Client, override_settings
from django.utils import timezone

from chat.models import (
    DispatchOutbox,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessageSender,
)
from chat.services.dispatch import _ensure_outbox_locked
from chat.tests.test_dispatch import dispatch_records  # noqa: F401
from integrations.exceptions import IntegrationUnavailable, RefreshRevoked
from integrations.models import PROVIDER_GMAIL, IntegrationSecret, IntegrationToolCall
from integrations.services import gmail_tool
from integrations.services.google_oauth import MintedAccess
from integrations.services.grants import revoke_ally_grant, set_ally_grant
from integrations.services.vault import seal_refresh_token
from integrations.tests.test_grants import gmail_settings  # noqa: F401

DRAFT = {
    "to": ["alice@example.com"],
    "subject": "Lunch",
    "body": "Noon works for me.",
}


def _turn(message, binding):
    with transaction.atomic():
        _ensure_outbox_locked(message)
    outbox = DispatchOutbox.objects.get(message=message)
    return {
        "message_id": message.id,
        "binding_id": binding.id,
        "command_fingerprint": outbox.command_fingerprint,
    }


def _next_message(conversation, sequence):
    return Message.objects.create(
        conversation=conversation,
        sequence=sequence,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content=f"turn {sequence}",
        status=MessageLifecycle.QUEUED,
        send_key_digest=f"{sequence}" * 64,
        content_fingerprint="c" * 64,
    )


@pytest.fixture
def gmail(dispatch_records, gmail_settings, monkeypatch):  # noqa: F811
    workspace, binding, conversation, message = dispatch_records
    conversation.is_default = False
    conversation.save()
    ciphertext, version = seal_refresh_token("refresh.live")
    secret = IntegrationSecret.objects.create(
        workspace=workspace,
        provider_key=PROVIDER_GMAIL,
        account_ref_hash=hashlib.sha256(b"acct").hexdigest(),
        account_email="me@gmail.com",
        ciphertext=bytes(ciphertext),
        key_version=version,
    )
    set_ally_grant(secret=secret, ally=binding.ally, level="send")
    monkeypatch.setattr(
        gmail_tool,
        "refresh_access_token",
        lambda secret: MintedAccess("ya29.live", timezone.now()),
    )
    calls = []

    def fake_gmail(token, path, *, query=None, body=None):
        assert token == "ya29.live"
        calls.append((path, query, body))
        if path == "/messages":
            return {"messages": [{"id": "m1"}]}
        if path == "/messages/m1":
            return {
                "id": "m1",
                "threadId": "t1",
                "snippet": "Hi &amp; hello",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "alice@example.com"},
                        {"name": "Subject", "value": "Hello"},
                    ],
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {
                                "data": base64.urlsafe_b64encode(b"Plain body").decode()
                            },
                        }
                    ],
                },
            }
        if path == "/messages/send":
            return {"id": "sent1", "threadId": "t9"}
        if path == "/threads/t1":
            return {
                "messages": [
                    {
                        "payload": {
                            "headers": [{"name": "Message-ID", "value": "<p@mail>"}]
                        }
                    }
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(gmail_tool, "_gmail", fake_gmail)
    return {
        "secret": secret,
        "ally": binding.ally,
        "binding": binding,
        "conversation": conversation,
        "turn": _turn(message, binding),
        "calls": calls,
    }


def run(turn, arguments, call_id=None):
    return gmail_tool.execute_gmail_tool(
        **turn, call_id=call_id or uuid4(), arguments=arguments
    )


def test_search_and_get_return_compact_messages(gmail):
    status, result = run(gmail["turn"], {"action": "search", "query": "from:alice"})
    assert status == 200
    assert result["messages"][0]["subject"] == "Hello"
    assert result["messages"][0]["snippet"] == "Hi & hello"
    assert gmail["calls"][0][1] == {"q": "from:alice", "maxResults": 10}
    status, result = run(gmail["turn"], {"action": "get", "message_id": "m1"})
    assert status == 200
    assert result["body"] == "Plain body"
    assert not IntegrationToolCall.objects.exists(), "mail content is not persisted"


def test_not_connected_and_not_granted(gmail):
    revoke_ally_grant(secret=gmail["secret"], ally=gmail["ally"])
    status, result = run(gmail["turn"], {"action": "search"})
    assert (status, result["error"]) == (403, "gmail_not_granted")
    IntegrationSecret.objects.update(revoked_at=timezone.now())
    status, result = run(gmail["turn"], {"action": "search"})
    assert (status, result["error"]) == (403, "gmail_not_connected")
    assert gmail["calls"] == []


def test_read_grant_cannot_prepare_or_send(gmail):
    set_ally_grant(secret=gmail["secret"], ally=gmail["ally"], level="read")
    assert run(gmail["turn"], {"action": "search"})[0] == 200
    status, result = run(gmail["turn"], {"action": "prepare_send", **DRAFT})
    assert (status, result["error"]) == (403, "gmail_not_granted")


def test_revoked_google_refresh_reports_not_connected(gmail, monkeypatch):
    def revoked(secret):
        raise RefreshRevoked("gone")

    monkeypatch.setattr(gmail_tool, "refresh_access_token", revoked)
    status, result = run(gmail["turn"], {"action": "search"})
    assert (status, result["error"]) == (403, "gmail_not_connected")


@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "search", "message_id": "m1"},
        {"action": "get"},
        {"action": "prepare_send", **DRAFT, "to": ["not-an-address"]},
        {"action": "prepare_send", **DRAFT, "subject": "a\r\nBcc: x@evil.test"},
        {"action": "send", **DRAFT},
        {"action": "delete"},
    ],
)
def test_invalid_requests_are_rejected(gmail, arguments):
    status, result = run(gmail["turn"], arguments)
    assert (status, result["error"]) == (422, "invalid_gmail_request")
    assert gmail["calls"] == []


def _confirmed(gmail):
    status, prepared = run(gmail["turn"], {"action": "prepare_send", **DRAFT})
    assert status == 200 and prepared["status"] == "confirmation_required"
    later = _next_message(gmail["conversation"], 2)
    return prepared["confirmation_ref"], _turn(later, gmail["binding"])


def test_send_needs_confirmation_from_an_earlier_turn(gmail):
    status, prepared = run(gmail["turn"], {"action": "prepare_send", **DRAFT})
    ref = prepared["confirmation_ref"]
    status, result = run(
        gmail["turn"], {"action": "send", **DRAFT, "confirmation_ref": ref}
    )
    assert (status, result["error"]) == (422, "confirmation_required")
    later = _turn(_next_message(gmail["conversation"], 2), gmail["binding"])
    status, result = run(later, {"action": "send", **DRAFT, "confirmation_ref": ref})
    assert (status, result["status"]) == (200, "sent")
    raw = next(body for path, _, body in gmail["calls"] if path == "/messages/send")
    sent = email.message_from_bytes(base64.urlsafe_b64decode(raw["raw"]))
    assert sent["To"] == "alice@example.com"
    assert sent["Subject"] == "Lunch"


def test_send_rejects_changed_message(gmail):
    ref, later = _confirmed(gmail)
    status, result = run(
        later,
        {"action": "send", **DRAFT, "body": "Changed", "confirmation_ref": ref},
    )
    assert (status, result["error"]) == (422, "confirmation_required")
    assert not any(path == "/messages/send" for path, _, _ in gmail["calls"])


def test_confirmation_sends_once_and_call_replays(gmail):
    ref, later = _confirmed(gmail)
    call_id = uuid4()
    arguments = {"action": "send", **DRAFT, "confirmation_ref": ref}
    first = run(later, arguments, call_id)
    assert run(later, arguments, call_id) == first
    status, result = run(later, arguments)
    assert (status, result["error"]) == (409, "confirmation_used")
    assert sum(path == "/messages/send" for path, _, _ in gmail["calls"]) == 1


def test_unknown_send_outcome_is_never_replayed(gmail, monkeypatch):
    ref, later = _confirmed(gmail)
    real = gmail_tool._gmail

    def dropped(token, path, **kwargs):
        if path == "/messages/send":
            raise URLError("lost response")
        return real(token, path, **kwargs)

    monkeypatch.setattr(gmail_tool, "_gmail", dropped)
    call_id = uuid4()
    arguments = {"action": "send", **DRAFT, "confirmation_ref": ref}
    for _ in range(2):
        status, result = run(later, arguments, call_id)
        assert (status, result["error"]) == (409, "send_outcome_unknown")


def test_gmail_rejection_frees_the_confirmation(gmail, monkeypatch):
    ref, later = _confirmed(gmail)
    real = gmail_tool._gmail

    def rejected(token, path, **kwargs):
        if path == "/messages/send":
            raise HTTPError(path, 400, "bad", {}, BytesIO(b"{}"))
        return real(token, path, **kwargs)

    monkeypatch.setattr(gmail_tool, "_gmail", rejected)
    arguments = {"action": "send", **DRAFT, "confirmation_ref": ref}
    status, result = run(later, arguments)
    assert (status, result["error"]) == (422, "gmail_rejected")
    monkeypatch.setattr(gmail_tool, "_gmail", real)
    assert run(later, arguments)[0] == 200


def test_reply_threads_under_the_last_message(gmail):
    draft = {**DRAFT, "thread_id": "t1"}
    _, prepared = run(gmail["turn"], {"action": "prepare_send", **draft})
    later = _turn(_next_message(gmail["conversation"], 2), gmail["binding"])
    arguments = {
        "action": "send",
        **draft,
        "confirmation_ref": prepared["confirmation_ref"],
    }
    assert run(later, arguments)[0] == 200
    body = next(body for path, _, body in gmail["calls"] if path == "/messages/send")
    assert body["threadId"] == "t1"
    sent = email.message_from_bytes(base64.urlsafe_b64decode(body["raw"]))
    assert sent["In-Reply-To"] == "<p@mail>"


def test_foreign_binding_or_fingerprint_is_unavailable(gmail):
    with pytest.raises(PermissionError):
        run({**gmail["turn"], "binding_id": uuid4()}, {"action": "search"})
    with pytest.raises(PermissionError):
        run({**gmail["turn"], "command_fingerprint": "x"}, {"action": "search"})


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN="test-service-token",
)
def test_internal_endpoint_auth_and_routing(gmail):
    client = Client()
    body = {
        **{key: str(value) for key, value in gmail["turn"].items()},
        "call_id": str(uuid4()),
        "integration": "gmail",
        "arguments": {"action": "search"},
    }
    url = "/api/v1/internal/foundry/integrations/tool"

    def post(payload, **headers):
        return client.post(
            url, json.dumps(payload), content_type="application/json", **headers
        )

    auth = {"HTTP_AUTHORIZATION": "Bearer test-service-token"}
    assert post(body).status_code == 401
    response = post(body, **auth)
    assert response.status_code == 200, response.content
    assert response.json()["messages"][0]["message_id"] == "m1"
    assert post({**body, "integration": "calendar"}, **auth).status_code == 422
    foreign = post({**body, "binding_id": str(uuid4())}, **auth)
    assert foreign.status_code == 403
    assert foreign.json() == {"error": "integration_unavailable"}


def test_concurrent_twin_calls_replay_instead_of_failing(gmail):
    message = Message.objects.get(pk=gmail["turn"]["message_id"])
    call_id = uuid4()
    arguments = {"action": "prepare_send", **DRAFT}
    first = run(gmail["turn"], arguments, call_id)
    args = gmail_tool.GmailToolRequest.model_validate(arguments)
    digest = IntegrationToolCall.objects.get(call_id=call_id).request_digest
    # The twin lost the race: its pre-check saw nothing, then its insert collides.
    assert gmail_tool._prepare_send(message, call_id, digest, args) == first

    ref, later = _confirmed(gmail)
    later_message = Message.objects.get(pk=later["message_id"])
    send_args = {"action": "send", **DRAFT, "confirmation_ref": ref}
    send_id = uuid4()
    sent = run(later, send_args, send_id)
    record = IntegrationToolCall.objects.get(call_id=send_id)
    twin = gmail_tool._send(
        later_message,
        send_id,
        record.request_digest,
        gmail_tool.GmailToolRequest.model_validate(send_args),
        gmail["secret"],
    )
    assert twin == sent
    assert sum(path == "/messages/send" for path, _, _ in gmail["calls"]) == 1


def test_unreadable_vault_is_retryable_and_frees_the_send(gmail, monkeypatch):
    ref, later = _confirmed(gmail)
    real = gmail_tool.refresh_access_token

    def unreadable(secret):
        raise IntegrationUnavailable("integration credential unreadable")

    monkeypatch.setattr(gmail_tool, "refresh_access_token", unreadable)
    assert run(gmail["turn"], {"action": "search"}) == (
        503,
        {"error": "gmail_unavailable"},
    )
    arguments = {"action": "send", **DRAFT, "confirmation_ref": ref}
    assert run(later, arguments)[0] == 503
    monkeypatch.setattr(gmail_tool, "refresh_access_token", real)
    assert run(later, arguments)[0] == 200
