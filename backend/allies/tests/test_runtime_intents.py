from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from django.test import Client, override_settings

from allies.gateways.foundry import RuntimeIntentReceipt
from allies.models import Ally
from allies.services.runtime_intents import request_runtime_intent
from auths.config import cookie_name
from auths.exceptions import WorkspaceAccessDenied
from auths.models import User
from auths.providers.base import VerifiedIdentity
from auths.services.accounts import resolve_or_create_user
from auths.services.sessions import issue_session
from auths.throttle import ThrottleExceeded
from workspaces.models import Membership, RuntimeIntentMode, Workspace

ALLY_ID = UUID("00000000-0000-4000-8000-000000000001")
KEY = UUID("00000000-0000-4000-8000-000000000002")


def _ally(*, workspace: Workspace, ally_id: UUID = ALLY_ID) -> Ally:
    return Ally.objects.create(
        id=ally_id,
        workspace=workspace,
        name="Mira",
        job="Study partner",
        personality="Calm and specific.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )


@pytest.fixture
def account(db):
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject=f"runtime-{uuid4()}")
    ).user
    workspace = user.owned_workspaces.get()
    Membership.objects.filter(workspace=workspace, user=user).update(
        role="owner", status="active"
    )
    return user, workspace, _ally(workspace=workspace)


@pytest.mark.django_db
@override_settings(ALLIES_RUNTIME_INTENT_ENABLED=True)
def test_service_forwards_only_workspace_intent_receipt_and_key(
    account, monkeypatch, settings
):
    user, workspace, ally = account
    workspace.runtime_intent_mode = RuntimeIntentMode.COMPOSING
    workspace.save(update_fields=("runtime_intent_mode", "updated_at"))
    captured = {}

    def forward(**kwargs):
        captured.update(kwargs)
        return RuntimeIntentReceipt(status="waking")

    monkeypatch.setattr(
        "allies.services.runtime_intents.forward_runtime_intent", forward
    )
    monkeypatch.setattr(
        "allies.services.runtime_intents.check_rate_limit",
        lambda **kwargs: captured.update(rate=kwargs),
    )

    result = request_runtime_intent(
        user=user,
        ally_id=ally.id,
        intent="composing_started",
        occurred_at=datetime.now(UTC),
        idempotency_key=KEY,
    )

    assert result.status == "waking"
    assert captured["workspace_id"] == workspace.id
    assert captured["intent"] == "composing_started"
    assert captured["idempotency_key"] == KEY
    assert captured["received_at"].tzinfo is not None
    assert captured["rate"] == {
        "scope": "runtime-intent-user",
        "identity": str(user.id),
        "limit": settings.ALLIES_RUNTIME_INTENT_RATE_LIMIT,
        "period": settings.ALLIES_RUNTIME_INTENT_RATE_PERIOD_SECONDS,
    }
    assert set(captured) == {
        "workspace_id",
        "intent",
        "received_at",
        "idempotency_key",
        "rate",
    }


@pytest.mark.django_db
@override_settings(ALLIES_RUNTIME_INTENT_ENABLED=True)
def test_service_policy_off_suppresses_rate_limit_and_gateway(account, monkeypatch):
    user, workspace, ally = account
    monkeypatch.setattr(
        "allies.services.runtime_intents.check_rate_limit",
        lambda **_kwargs: pytest.fail("disabled intent was rate limited"),
    )
    monkeypatch.setattr(
        "allies.services.runtime_intents.forward_runtime_intent",
        lambda **_kwargs: pytest.fail("disabled intent reached Foundry"),
    )

    result = request_runtime_intent(
        user=user,
        ally_id=ally.id,
        intent="composing_started",
        occurred_at=datetime.now(UTC),
        idempotency_key=KEY,
    )

    assert result.status == "disabled"
    assert workspace.runtime_intent_mode == RuntimeIntentMode.OFF


@pytest.mark.django_db
def test_service_rejects_foreign_or_inactive_membership(account):
    user, workspace, ally = account
    foreign = User.objects.create_user()

    with pytest.raises(WorkspaceAccessDenied):
        request_runtime_intent(
            user=foreign,
            ally_id=ally.id,
            intent="composing_started",
            occurred_at=datetime.now(UTC),
            idempotency_key=KEY,
        )

    Membership.objects.filter(workspace=workspace, user=user).update(status="inactive")
    with pytest.raises(WorkspaceAccessDenied):
        request_runtime_intent(
            user=user,
            ally_id=ally.id,
            intent="composing_started",
            occurred_at=datetime.now(UTC),
            idempotency_key=KEY,
        )


@pytest.mark.django_db
@override_settings(
    ALLIES_RUNTIME_INTENT_ENABLED=True,
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
)
def test_controller_requires_csrf_and_strict_content_free_schema(account, monkeypatch):
    user, workspace, ally = account
    workspace.runtime_intent_mode = RuntimeIntentMode.COMPOSING
    workspace.save(update_fields=("runtime_intent_mode", "updated_at"))
    issued = issue_session(user)
    client = Client(enforce_csrf_checks=True)
    client.cookies[cookie_name("access")] = issued.access_token
    csrf = client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")["X-CSRFToken"]
    monkeypatch.setattr(
        "allies.services.runtime_intents.forward_runtime_intent",
        lambda **_kwargs: RuntimeIntentReceipt(status="waking"),
    )
    headers = {
        "HTTP_HOST": "testserver",
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_X_CSRFTOKEN": csrf,
        "HTTP_IDEMPOTENCY_KEY": str(KEY),
    }
    payload = {
        "intent": "composing_started",
        "occurred_at": "2026-09-04T12:00:00.000Z",
    }

    missing_csrf = client.post(
        f"/api/v1/allies/{ally.id}/runtime-intents",
        json.dumps(payload),
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_IDEMPOTENCY_KEY=str(KEY),
    )
    response = client.post(
        f"/api/v1/allies/{ally.id}/runtime-intents",
        json.dumps(payload),
        content_type="application/json",
        **headers,
    )
    extra = client.post(
        f"/api/v1/allies/{ally.id}/runtime-intents",
        json.dumps({**payload, "draft": "must not cross the boundary"}),
        content_type="application/json",
        **headers,
    )

    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["data"] == {"code": "csrf_rejected"}
    assert response.status_code == 202
    assert response.json()["data"] == {"status": "waking"}
    assert extra.status_code == 422
    assert extra.json()["data"]["code"] == "validation_error"


@pytest.mark.django_db
@override_settings(
    ALLIES_RUNTIME_INTENT_ENABLED=True,
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
)
def test_controller_maps_user_limit_and_hides_foreign_ally(account, monkeypatch):
    user, workspace, ally = account
    workspace.runtime_intent_mode = RuntimeIntentMode.COMPOSING
    workspace.save(update_fields=("runtime_intent_mode", "updated_at"))
    issued = issue_session(user)
    client = Client(enforce_csrf_checks=True)
    client.cookies[cookie_name("access")] = issued.access_token
    csrf = client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")["X-CSRFToken"]
    headers = {
        "HTTP_HOST": "testserver",
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_X_CSRFTOKEN": csrf,
        "HTTP_IDEMPOTENCY_KEY": str(KEY),
    }
    payload = {
        "intent": "composing_started",
        "occurred_at": "2026-09-04T12:00:00.000Z",
    }
    monkeypatch.setattr(
        "allies.services.runtime_intents.check_rate_limit",
        lambda **_kwargs: (_ for _ in ()).throw(ThrottleExceeded()),
    )
    limited = client.post(
        f"/api/v1/allies/{ally.id}/runtime-intents",
        json.dumps(payload),
        content_type="application/json",
        **headers,
    )
    foreign = client.post(
        "/api/v1/allies/00000000-0000-4000-8000-000000000099/runtime-intents",
        json.dumps(payload),
        content_type="application/json",
        **headers,
    )
    bad_key = client.post(
        f"/api/v1/allies/{ally.id}/runtime-intents",
        json.dumps(payload),
        content_type="application/json",
        **{**headers, "HTTP_IDEMPOTENCY_KEY": "x" * 36},
    )

    assert limited.status_code == 429
    assert limited.json()["data"] == {"code": "rate_limited"}
    assert foreign.status_code == 404
    assert foreign.json()["data"] == {"code": "ally_unavailable"}
    assert bad_key.status_code == 422
    assert bad_key.json()["data"] == {"code": "validation_error"}
