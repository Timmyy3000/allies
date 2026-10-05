import json
from uuid import uuid4

import pytest
from django.test import Client

from allies.models import Ally, AllyBinding, BindingStatus
from auths.config import cookie_name
from auths.models import SessionClientKind, User
from auths.services.sessions import issue_session, revoke_family
from chat.models import NONTERMINAL_MESSAGE_STATUSES, DispatchOutbox, Message
from chat.services.conversations import (
    ensure_default_conversation,
    reconcile_onboarding_reply,
)
from chat.services.messages import accept_message, complete_turn
from workspaces.models import Membership, Workspace

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def queue_settings(settings):
    settings.ALLOWED_HOSTS = ["testserver"]
    settings.CSRF_TRUSTED_ORIGINS = ["http://localhost:3000"]
    settings.ALLIES_AUTH_DIGEST_KEY = "d" * 32
    settings.ALLIES_AUTH_JWT_KEY = "j" * 32
    settings.ALLIES_CHAT_CURSOR_KEY = "c" * 32
    settings.ALLIES_FOUNDRY_EXECUTION_ENABLED = False


@pytest.fixture
def queue_account():
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Queue workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Planning",
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    AllyBinding.objects.create(
        ally=ally, status=BindingStatus.BOUND, receipt_digest="b" * 64
    )
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Ready"
    )
    reconcile_onboarding_reply(ally=ally)
    complete_turn(
        message_id=conversation.messages.get(sequence=2).id, status="completed"
    )
    messages = [
        accept_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            content=content,
            idempotency_key=f"queue-api-seed-{index:04}",
        ).message
        for index, content in enumerate(["Head", "Private tail"])
    ]
    return user, workspace, ally, conversation, messages


def authenticated_client(user, *, native=False):
    client = Client(enforce_csrf_checks=True)
    issued = issue_session(
        user,
        client_kind=SessionClientKind.NATIVE if native else SessionClientKind.BROWSER,
    )
    if native:
        return client, {"HTTP_AUTHORIZATION": f"Bearer {issued.access_token}"}
    client.cookies[cookie_name("access")] = issued.access_token
    return client, {
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_X_CSRFTOKEN": client.get("/api/v1/auths/csrf")["X-CSRFToken"],
    }


def route(workspace, conversation):
    return f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/messages"


def mutate(client, headers, method, workspace, conversation, messages):
    target = route(workspace, conversation)
    if method == "delete":
        return client.delete(f"{target}/{messages[1].id}", **headers)
    if method == "retry":
        target += f"/{messages[0].id}/retry"
    return client.post(
        target,
        json.dumps({"content": "New tail"}) if method == "send" else "{}",
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="queue-api-mutation-0001",
        **headers,
    )


@pytest.mark.parametrize("native", [False, True])
def test_queue_contract_deletion_replay_and_head_protection(queue_account, native):
    user, workspace, ally, conversation, messages = queue_account
    head, tail = messages
    send_count = Message.objects.filter(
        conversation=conversation, origin="send"
    ).count()
    client, headers = authenticated_client(user, native=native)
    target = route(workspace, conversation)
    read_headers = {
        key: value for key, value in headers.items() if key == "HTTP_AUTHORIZATION"
    }
    loaded = client.get(
        f"/api/v1/workspaces/{workspace.id}/allies/{ally.id}/conversation?limit=1",
        **read_headers,
    )
    assert loaded.status_code == 200
    assert len(loaded.json()["data"]["messages"]) == 1
    assert [row["id"] for row in loaded.json()["data"]["queue"]] == [
        str(head.id),
        str(tail.id),
    ]
    assert [row["queue_state"] for row in loaded.json()["data"]["queue"]] == [
        "claimed",
        "unclaimed",
    ]
    active = client.get(
        f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/activities",
        **read_headers,
    )
    assert active.status_code == 200
    assert active.json()["data"]["active_message_id"] == str(head.id)
    denied = client.delete(f"{target}/{head.id}", **headers)
    assert denied.status_code == 409
    assert denied.json()["data"]["code"] == "message_not_deletable"

    deleted = client.delete(f"{target}/{tail.id}", **headers)
    repeated = client.delete(f"{target}/{tail.id}", **headers)
    assert deleted.status_code == repeated.status_code == 200
    assert deleted.json() == repeated.json()
    tombstone = deleted.json()["data"]
    assert tombstone["content"] == ""
    assert tombstone["deleted_at"] and tombstone["queue_state"] is None
    assert tombstone["status"] == "stopped"
    replay = client.post(
        target,
        json.dumps({"content": "Private tail"}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="queue-api-seed-0001",
        **headers,
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["message"] == tombstone
    conflict = client.post(
        target,
        json.dumps({"content": "Different content"}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="queue-api-seed-0001",
        **headers,
    )
    assert conflict.status_code == 409
    outbox = DispatchOutbox.objects.get(message=tail)
    assert not outbox.command_bytes and outbox.command_byte_length == 0
    assert (
        Message.objects.filter(conversation=conversation, origin="send").count()
        == send_count
    )


@pytest.mark.parametrize("method", ["send", "retry", "delete"])
def test_native_mutations_accept_live_native_bearer(queue_account, method):
    user, workspace, _ally, conversation, messages = queue_account
    Message.objects.filter(pk=messages[0].pk).update(
        status="failed", retry_allowed=True
    )
    client, headers = authenticated_client(user, native=True)
    response = mutate(client, headers, method, workspace, conversation, messages)
    assert response.status_code == (200 if method == "delete" else 201)


@pytest.mark.parametrize("method", ["send", "retry", "delete"])
@pytest.mark.parametrize(
    "credential", ["invalid", "revoked", "browser", "mixed", "missing"]
)
def test_mutations_reject_invalid_native_transports(queue_account, method, credential):
    user, workspace, _ally, conversation, messages = queue_account
    client = Client(enforce_csrf_checks=True)
    issued = issue_session(
        user,
        client_kind=SessionClientKind.BROWSER
        if credential == "browser"
        else SessionClientKind.NATIVE,
    )
    if credential == "revoked":
        revoke_family(issued.family)
    headers = {}
    if credential != "missing":
        headers["HTTP_AUTHORIZATION"] = (
            f"Bearer {'invalid' if credential == 'invalid' else issued.access_token}"
        )
    if credential == "mixed":
        client.cookies[cookie_name("access")] = issue_session(user).access_token
        headers["HTTP_X_CSRFTOKEN"] = client.get("/api/v1/auths/csrf")["X-CSRFToken"]
        headers["HTTP_ORIGIN"] = "http://localhost:3000"
    before = list(Message.objects.values("id", "status", "content", "deleted_at"))
    response = mutate(client, headers, method, workspace, conversation, messages)
    assert response.status_code == (403 if credential == "missing" else 401)
    assert (
        list(Message.objects.values("id", "status", "content", "deleted_at")) == before
    )


@pytest.mark.parametrize("method", ["send", "retry", "delete"])
@pytest.mark.parametrize(
    "failure", ["missing_csrf", "missing_origin", "foreign_origin"]
)
def test_browser_mutations_keep_origin_and_csrf_checks(queue_account, method, failure):
    user, workspace, _ally, conversation, messages = queue_account
    client, headers = authenticated_client(user)
    if failure == "missing_csrf":
        headers.pop("HTTP_X_CSRFTOKEN")
    elif failure == "missing_origin":
        headers.pop("HTTP_ORIGIN")
    else:
        headers["HTTP_ORIGIN"] = "https://foreign.invalid"
    before = list(Message.objects.values("id", "status", "content", "deleted_at"))
    response = mutate(client, headers, method, workspace, conversation, messages)
    assert response.status_code == 403
    assert (
        list(Message.objects.values("id", "status", "content", "deleted_at")) == before
    )


@pytest.mark.parametrize("native", [False, True])
def test_delete_hides_foreign_scope_and_missing_message(queue_account, native):
    user, workspace, _ally, conversation, messages = queue_account
    outsider = User.objects.create_user()
    client, headers = authenticated_client(outsider, native=native)
    foreign = client.delete(
        f"{route(workspace, conversation)}/{messages[1].id}", **headers
    )
    own_client, own_headers = authenticated_client(user, native=native)
    missing = own_client.delete(
        f"{route(workspace, conversation)}/{uuid4()}", **own_headers
    )
    wrong_conversation = own_client.delete(
        f"/api/v1/workspaces/{workspace.id}/conversations/{uuid4()}/messages/{messages[1].id}",
        **own_headers,
    )
    assert (
        foreign.status_code
        == missing.status_code
        == wrong_conversation.status_code
        == 404
    )
    assert foreign.json() == missing.json() == wrong_conversation.json()
    messages[1].refresh_from_db()
    assert messages[1].content == "Private tail" and messages[1].deleted_at is None


def test_paused_admission_keeps_replay_delete_and_drain_working(
    queue_account, settings
):
    user, workspace, _ally, conversation, messages = queue_account
    settings.ALLIES_CHAT_QUEUE_ADMISSION_ENABLED = False
    client, headers = authenticated_client(user, native=True)
    rejected = mutate(client, headers, "send", workspace, conversation, messages)
    assert rejected.status_code == 429
    replay = client.post(
        route(workspace, conversation),
        json.dumps({"content": "Head"}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="queue-api-seed-0000",
        **headers,
    )
    assert replay.status_code == 200 and replay.json()["data"]["replayed"]
    deleted = mutate(client, headers, "delete", workspace, conversation, messages)
    assert deleted.status_code == 200
    live = Message.objects.filter(
        conversation=conversation,
        sender="user",
        origin="send",
        status__in=NONTERMINAL_MESSAGE_STATUSES,
        deleted_at__isnull=True,
    )
    assert live.filter(execution_claimed_at__isnull=True).count() == 0
    assert live.filter(execution_claimed_at__isnull=False).count() == 1
    complete_turn(message_id=messages[0].id, status="completed")
    assert live.count() == 0
    first = mutate(client, headers, "send", workspace, conversation, messages)
    assert first.status_code == 201
    assert first.json()["data"]["message"]["queue_state"] == "claimed"


def test_lowered_admission_limit_does_not_truncate_existing_queue(
    queue_account, settings
):
    user, workspace, ally, conversation, messages = queue_account
    client, headers = authenticated_client(user, native=True)
    assert (
        mutate(client, headers, "send", workspace, conversation, messages).status_code
        == 201
    )
    settings.ALLIES_CHAT_MAX_PENDING_MESSAGES = 1
    loaded = client.get(
        f"/api/v1/workspaces/{workspace.id}/allies/{ally.id}/conversation?limit=1",
        **headers,
    )
    assert loaded.status_code == 200
    assert len(loaded.json()["data"]["queue"]) == 3
