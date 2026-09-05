import json
import logging

import pytest
from django.test import Client, override_settings

from allies.models import Ally
from auths.config import cookie_name
from auths.models import User
from auths.services.sessions import issue_session
from auths.throttle import ThrottleUnavailable
from chat.models import Message, MessageLifecycle
from chat.services.conversations import ensure_default_conversation
from workspaces.models import Membership, Workspace


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
    ALLIES_CHAT_CURSOR_KEY="c" * 32,
)
def test_conversation_read_send_and_replay_contract():
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Personal Workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study partner",
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Ready"
    )
    client = Client(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")["X-CSRFToken"]
    client.cookies[cookie_name("access")] = issue_session(user).access_token
    loaded = client.get(
        f"/api/v1/workspaces/{workspace.id}/allies/{ally.id}/conversation",
        HTTP_HOST="testserver",
    )
    assert loaded.status_code == 200
    assert loaded.json()["data"]["id"] == str(conversation.id)
    headers = {
        "HTTP_HOST": "testserver",
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_X_CSRFTOKEN": csrf,
        "HTTP_IDEMPOTENCY_KEY": "chat-api-send-key-1",
    }
    body = json.dumps({"content": "Plan my day"})
    created = client.post(
        f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/messages",
        body,
        content_type="application/json",
        **headers,
    )
    replay = client.post(
        f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/messages",
        body,
        content_type="application/json",
        **headers,
    )
    assert created.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["data"]["replayed"] is True
    assert (
        replay.json()["data"]["message"]["id"]
        == created.json()["data"]["message"]["id"]
    )
    created_message_id = created.json()["data"]["message"]["id"]
    Message.objects.filter(pk=created_message_id).update(
        status=MessageLifecycle.FAILED, retry_allowed=True
    )
    retried = client.post(
        f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/messages/"
        f"{created_message_id}/retry",
        "{}",
        content_type="application/json",
        **{**headers, "HTTP_IDEMPOTENCY_KEY": "chat-api-retry-key-0001"},
    )
    assert retried.status_code == 201

    foreign_user = User.objects.create_user()
    foreign_workspace = Workspace.objects.create(
        owner=foreign_user,
        name="Foreign Workspace",
    )
    Membership.objects.create(
        workspace=foreign_workspace,
        user=foreign_user,
        role="owner",
        status="active",
    )
    foreign_ally = Ally.objects.create(
        workspace=foreign_workspace,
        name="Nova",
        job="Other",
        personality="Private",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    foreign_conversation = ensure_default_conversation(
        ally=foreign_ally,
        greeting="Private hello",
        reply="Private reply",
    )
    denied_get = client.get(
        f"/api/v1/workspaces/{foreign_workspace.id}/conversations/"
        f"{foreign_conversation.id}",
        HTTP_HOST="testserver",
    )
    denied_post = client.post(
        f"/api/v1/workspaces/{foreign_workspace.id}/conversations/"
        f"{foreign_conversation.id}/messages",
        json.dumps({"content": "Probe"}),
        content_type="application/json",
        **{**headers, "HTTP_IDEMPOTENCY_KEY": "chat-foreign-key-0001"},
    )
    foreign_message = foreign_conversation.messages.order_by("sequence").first()
    denied_retry = client.post(
        f"/api/v1/workspaces/{foreign_workspace.id}/conversations/"
        f"{foreign_conversation.id}/messages/{foreign_message.id}/retry",
        "{}",
        content_type="application/json",
        **{**headers, "HTTP_IDEMPOTENCY_KEY": "chat-foreign-retry-0001"},
    )
    assert denied_get.status_code == 404
    assert denied_post.status_code == 404
    assert denied_retry.status_code == 404
    assert denied_get.json() == denied_post.json() == denied_retry.json()


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
    ALLIES_CHAT_CURSOR_KEY="c" * 32,
    ALLIES_CHAT_SEND_RATE_LIMIT=1,
    ALLIES_CHAT_SEND_RATE_PERIOD_SECONDS=60,
)
def test_rate_limit_is_generic_and_aggregate_only(caplog, monkeypatch):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Personal Workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study partner",
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    conversation = ensure_default_conversation(
        ally=ally, greeting="Hello", reply="Ready"
    )
    client = Client(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")["X-CSRFToken"]
    client.cookies[cookie_name("access")] = issue_session(user).access_token
    route = (
        f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/messages"
    )
    headers = {
        "HTTP_HOST": "testserver",
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_X_CSRFTOKEN": csrf,
    }
    client.post(
        route,
        json.dumps({"content": "First"}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="chat-rate-key-0001",
        **headers,
    )
    other_owner = User.objects.create_user()
    other_workspace = Workspace.objects.create(
        owner=other_owner,
        name="Other Workspace",
    )
    Membership.objects.create(
        workspace=other_workspace,
        user=user,
        role="owner",
        status="active",
    )
    other_ally = Ally.objects.create(
        workspace=other_workspace,
        name="Nova",
        job="Writing partner",
        personality="Direct",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    other_conversation = ensure_default_conversation(
        ally=other_ally,
        greeting="Hello",
        reply="Ready",
    )
    other_created = client.post(
        f"/api/v1/workspaces/{other_workspace.id}/conversations/"
        f"{other_conversation.id}/messages",
        json.dumps({"content": "Independent"}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="chat-rate-other-0001",
        **headers,
    )
    assert other_created.status_code == 201
    wide_logs = []
    monkeypatch.setattr("observability.events.logger.info", wide_logs.append)
    with caplog.at_level(logging.INFO, logger="allies.observability"):
        limited = client.post(
            route,
            json.dumps({"content": "Second"}),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="chat-rate-key-0002",
            **headers,
        )
    assert limited.status_code == 429
    assert limited.json() == {
        "status": "error",
        "message": "Request temporarily unavailable",
        "data": {"code": "rate_limited"},
    }
    assert "X-Request-ID" not in limited
    event = json.loads(wide_logs[-1])
    assert set(event) == {
        "event",
        "method",
        "reason",
        "route",
        "schema_version",
        "status_code",
    }
    assert event["schema_version"] == 1
    assert "chat-rate-key-0002" not in wide_logs[-1]
    assert str(workspace.id) not in wide_logs[-1]

    def unavailable_rate_limit(**_kwargs):
        raise ThrottleUnavailable("forced cache outage")

    monkeypatch.setattr(
        "chat.services.messages.check_rate_limit", unavailable_rate_limit
    )
    unavailable = client.post(
        route,
        json.dumps({"content": "Third"}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="chat-rate-key-0003",
        **headers,
    )
    assert unavailable.status_code == 500
    assert unavailable.json() == {
        "status": "error",
        "message": "internal server error",
        "data": {"code": "internal_error"},
    }
