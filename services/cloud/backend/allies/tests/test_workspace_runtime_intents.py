from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from django.core.cache import cache
from django.test import Client, override_settings

from allies.exceptions import FoundryGatewayRetryable, FoundryGatewayUnknownOutcome
from allies.gateways.foundry import RuntimeIntentReceipt
from allies.services.runtime_intents import request_workspace_runtime_intent
from auths.config import cookie_name
from auths.models import SessionClientKind
from auths.providers.base import VerifiedIdentity
from auths.services.accounts import resolve_or_create_user
from auths.services.sessions import issue_session
from auths.throttle import ThrottleExceeded, ThrottleUnavailable
from workspaces.models import Membership, RuntimeIntentMode

KEY = UUID("00000000-0000-4000-8000-000000000012")


def _payload():
    return {
        "version": 1,
        "intent": "ally_creation_started",
        "occurred_at": "2026-09-07T12:00:00Z",
    }


def _browser_client(user):
    issued = issue_session(user)
    client = Client(enforce_csrf_checks=True)
    client.cookies[cookie_name("access")] = issued.access_token
    csrf = client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")["X-CSRFToken"]
    return client, {
        "HTTP_HOST": "testserver",
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_X_CSRFTOKEN": csrf,
        "HTTP_IDEMPOTENCY_KEY": str(uuid4()),
    }


@pytest.fixture(autouse=True)
def clear_runtime_intent_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def account(db):
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject=f"workspace-runtime-{uuid4()}")
    ).user
    workspace = user.owned_workspaces.get()
    Membership.objects.filter(workspace=workspace, user=user).update(
        role="owner", status="active"
    )
    workspace.runtime_intent_mode = RuntimeIntentMode.COMPOSING
    workspace.save(update_fields=("runtime_intent_mode", "updated_at"))
    return user, workspace


@pytest.mark.django_db
@override_settings(ALLIES_RUNTIME_INTENT_ENABLED=True)
def test_workspace_service_derives_workspace_and_dedupes(
    account, monkeypatch, settings
):
    user, workspace = account
    forwarded = []
    rate_checks = []

    def forward(**kwargs):
        forwarded.append(kwargs)
        return RuntimeIntentReceipt(status="waking")

    monkeypatch.setattr(
        "allies.services.runtime_intents.forward_runtime_intent", forward
    )
    monkeypatch.setattr(
        "allies.services.runtime_intents.check_rate_limit",
        lambda **kwargs: rate_checks.append(kwargs),
    )
    occurred_at = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    first = request_workspace_runtime_intent(
        user=user,
        intent="ally_creation_started",
        occurred_at=occurred_at,
        idempotency_key=KEY,
        now=occurred_at,
    )
    duplicate = request_workspace_runtime_intent(
        user=user,
        intent="ally_creation_started",
        occurred_at=occurred_at,
        idempotency_key=KEY,
        now=occurred_at,
    )

    assert first.status == duplicate.status == "waking"
    assert len(forwarded) == 1
    assert forwarded[0] == {
        "workspace_id": workspace.id,
        "intent": "ally_creation_started",
        "received_at": occurred_at,
        "idempotency_key": KEY,
    }
    assert [item["scope"] for item in rate_checks] == [
        "runtime-intent-user",
        "runtime-intent-workspace",
    ]
    assert rate_checks[0]["limit"] == settings.ALLIES_RUNTIME_INTENT_RATE_LIMIT
    assert (
        rate_checks[1]["limit"] == settings.ALLIES_RUNTIME_INTENT_WORKSPACE_RATE_LIMIT
    )


@pytest.mark.django_db
@override_settings(
    ALLIES_RUNTIME_INTENT_ENABLED=True,
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
)
def test_workspace_endpoint_uses_browser_csrf_and_excludes_draft(account, monkeypatch):
    user, workspace = account
    issued = issue_session(user)
    client = Client(enforce_csrf_checks=True)
    client.cookies[cookie_name("access")] = issued.access_token
    csrf = client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")["X-CSRFToken"]
    forwarded = []

    def forward(**kwargs):
        forwarded.append(kwargs)
        return RuntimeIntentReceipt(status="waking")

    monkeypatch.setattr(
        "allies.services.runtime_intents.forward_runtime_intent", forward
    )
    headers = {
        "HTTP_HOST": "testserver",
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_X_CSRFTOKEN": csrf,
        "HTTP_IDEMPOTENCY_KEY": str(uuid4()),
    }
    payload = {
        "version": 1,
        "intent": "ally_creation_started",
        "occurred_at": "2026-09-07T12:00:00Z",
    }
    response = client.post(
        "/api/v1/onboarding/runtime-intents",
        json.dumps(payload),
        content_type="application/json",
        **headers,
    )
    extra = client.post(
        "/api/v1/onboarding/runtime-intents",
        json.dumps({**payload, "draft": "private"}),
        content_type="application/json",
        **{**headers, "HTTP_IDEMPOTENCY_KEY": str(uuid4())},
    )

    assert response.status_code == 202
    assert response.json()["data"] == {"status": "waking"}
    assert extra.status_code == 422
    assert forwarded[0]["workspace_id"] == workspace.id
    assert set(forwarded[0]) == {
        "workspace_id",
        "intent",
        "received_at",
        "idempotency_key",
    }


@pytest.mark.django_db
@override_settings(ALLIES_RUNTIME_INTENT_ENABLED=True, ALLIES_AUTH_NATIVE_ENABLED=True)
def test_workspace_endpoint_accepts_native_bearer_without_browser_signals(
    account, monkeypatch
):
    user, _workspace = account
    issued = issue_session(user, client_kind=SessionClientKind.NATIVE)
    monkeypatch.setattr(
        "allies.services.runtime_intents.forward_runtime_intent",
        lambda **_kwargs: RuntimeIntentReceipt(status="waking"),
    )
    response = Client().post(
        "/api/v1/onboarding/runtime-intents",
        json.dumps(
            {
                "version": 1,
                "intent": "ally_creation_started",
                "occurred_at": "2026-09-07T12:00:00Z",
            }
        ),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {issued.access_token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 202
    assert response.json()["data"] == {"status": "waking"}


@pytest.mark.django_db
@override_settings(
    ALLIES_RUNTIME_INTENT_ENABLED=True,
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
)
def test_workspace_endpoint_requires_an_authenticated_browser_session(account):
    _user, _workspace = account
    client = Client(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")["X-CSRFToken"]
    response = client.post(
        "/api/v1/onboarding/runtime-intents",
        json.dumps(_payload()),
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 401
    assert response.json()["data"] == {"code": "session_invalid"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("origin", "csrf", "code"),
    [
        ("http://evil.example", "present", "origin_rejected"),
        ("http://localhost:3000", "missing", "csrf_rejected"),
    ],
)
@override_settings(
    ALLIES_RUNTIME_INTENT_ENABLED=True,
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
)
def test_workspace_endpoint_rejects_wrong_origin_or_missing_csrf(
    account, origin, csrf, code
):
    user, _workspace = account
    client, headers = _browser_client(user)
    headers["HTTP_ORIGIN"] = origin
    if csrf == "missing":
        headers.pop("HTTP_X_CSRFTOKEN")
    response = client.post(
        "/api/v1/onboarding/runtime-intents",
        json.dumps(_payload()),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 403
    assert response.json()["data"] == {"code": code}


@pytest.mark.django_db
@override_settings(ALLIES_RUNTIME_INTENT_ENABLED=True, ALLIES_AUTH_NATIVE_ENABLED=False)
def test_workspace_endpoint_rejects_native_bearer_when_native_flag_is_off(
    account, monkeypatch
):
    user, _workspace = account
    issued = issue_session(user, client_kind=SessionClientKind.NATIVE)
    monkeypatch.setattr(
        "allies.services.runtime_intents.forward_runtime_intent",
        lambda **_kwargs: pytest.fail("native-disabled request reached Foundry"),
    )
    response = Client().post(
        "/api/v1/onboarding/runtime-intents",
        json.dumps(_payload()),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {issued.access_token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 401
    assert response.json()["data"] == {"code": "session_invalid"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("enabled", "mode"),
    [
        (False, RuntimeIntentMode.COMPOSING),
        (True, RuntimeIntentMode.OFF),
    ],
)
def test_workspace_service_global_or_mode_gate_suppresses_forwarding(
    account, monkeypatch, settings, enabled, mode
):
    user, workspace = account
    settings.ALLIES_RUNTIME_INTENT_ENABLED = enabled
    workspace.runtime_intent_mode = mode
    workspace.save(update_fields=("runtime_intent_mode", "updated_at"))
    monkeypatch.setattr(
        "allies.services.runtime_intents.check_rate_limit",
        lambda **_kwargs: pytest.fail("disabled intent was rate limited"),
    )
    monkeypatch.setattr(
        "allies.services.runtime_intents.forward_runtime_intent",
        lambda **_kwargs: pytest.fail("disabled intent reached Foundry"),
    )

    result = request_workspace_runtime_intent(
        user=user,
        intent="ally_creation_started",
        occurred_at=datetime.now(UTC),
        idempotency_key=uuid4(),
    )

    assert result.status == "disabled"


@pytest.mark.django_db
@override_settings(
    ALLIES_RUNTIME_INTENT_ENABLED=True,
    ALLIES_RUNTIME_INTENT_RATE_LIMIT=1,
    ALLIES_RUNTIME_INTENT_WORKSPACE_RATE_LIMIT=10,
)
def test_workspace_service_enforces_actual_user_rate_limit(account, monkeypatch):
    user, _workspace = account
    monkeypatch.setattr(
        "allies.services.runtime_intents.forward_runtime_intent",
        lambda **_kwargs: RuntimeIntentReceipt(status="waking"),
    )
    request = {
        "user": user,
        "intent": "ally_creation_started",
        "occurred_at": datetime.now(UTC),
    }

    assert (
        request_workspace_runtime_intent(**request, idempotency_key=uuid4()).status
        == "waking"
    )
    with pytest.raises(ThrottleExceeded):
        request_workspace_runtime_intent(**request, idempotency_key=uuid4())


@pytest.mark.django_db
@override_settings(
    ALLIES_RUNTIME_INTENT_ENABLED=True,
    ALLIES_RUNTIME_INTENT_RATE_LIMIT=10,
    ALLIES_RUNTIME_INTENT_WORKSPACE_RATE_LIMIT=1,
)
def test_workspace_service_enforces_actual_workspace_rate_limit(account, monkeypatch):
    user, _workspace = account
    monkeypatch.setattr(
        "allies.services.runtime_intents.forward_runtime_intent",
        lambda **_kwargs: RuntimeIntentReceipt(status="waking"),
    )
    request = {
        "user": user,
        "intent": "ally_creation_started",
        "occurred_at": datetime.now(UTC),
    }

    assert (
        request_workspace_runtime_intent(**request, idempotency_key=uuid4()).status
        == "waking"
    )
    with pytest.raises(ThrottleExceeded):
        request_workspace_runtime_intent(**request, idempotency_key=uuid4())


@pytest.mark.django_db
@override_settings(ALLIES_RUNTIME_INTENT_ENABLED=True)
def test_workspace_service_dedupe_expires_and_allows_a_new_attempt(
    account, monkeypatch
):
    user, _workspace = account
    forwarded = []

    class ExpiringCache:
        def __init__(self):
            self.clock = 0
            self.values = {}

        def add(self, key, value, timeout):
            current = self.values.get(key)
            if current is not None and current[1] > self.clock:
                return False
            self.values[key] = (value, self.clock + timeout)
            return True

        def get(self, key):
            current = self.values.get(key)
            if current is None or current[1] <= self.clock:
                self.values.pop(key, None)
                return None
            return current[0]

        def set(self, key, value, timeout):
            self.values[key] = (value, self.clock + timeout)

    expiring_cache = ExpiringCache()
    monkeypatch.setattr("allies.services.runtime_intents.cache", expiring_cache)
    monkeypatch.setattr(
        "allies.services.runtime_intents.check_rate_limit", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        "allies.services.runtime_intents.forward_runtime_intent",
        lambda **kwargs: (
            forwarded.append(kwargs) or RuntimeIntentReceipt(status="waking")
        ),
    )
    request = {
        "user": user,
        "intent": "ally_creation_started",
        "occurred_at": datetime.now(UTC),
        "idempotency_key": KEY,
    }

    assert request_workspace_runtime_intent(**request).status == "waking"
    assert request_workspace_runtime_intent(**request).status == "waking"
    expiring_cache.clock = 601
    assert request_workspace_runtime_intent(**request).status == "waking"
    assert len(forwarded) == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    "gateway_error", [FoundryGatewayRetryable, FoundryGatewayUnknownOutcome]
)
@override_settings(
    ALLIES_RUNTIME_INTENT_ENABLED=True,
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
)
def test_workspace_endpoint_maps_foundry_retryable_outcomes_to_503(
    account, monkeypatch, gateway_error
):
    user, _workspace = account
    client, headers = _browser_client(user)
    monkeypatch.setattr(
        "allies.services.runtime_intents.forward_runtime_intent",
        lambda **_kwargs: (_ for _ in ()).throw(gateway_error("unavailable")),
    )
    response = client.post(
        "/api/v1/onboarding/runtime-intents",
        json.dumps(_payload()),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 503
    assert response.json()["data"] == {"code": "runtime_intent_unavailable"}


@pytest.mark.django_db
@override_settings(ALLIES_RUNTIME_INTENT_ENABLED=True)
def test_failed_workspace_intent_can_retry_same_foundry_key(account, monkeypatch):
    user, _workspace = account
    forwarded = []

    def forward(**kwargs):
        forwarded.append(kwargs["idempotency_key"])
        if len(forwarded) == 1:
            raise FoundryGatewayRetryable("response unavailable")
        return RuntimeIntentReceipt(status="already_ready")

    monkeypatch.setattr(
        "allies.services.runtime_intents.forward_runtime_intent", forward
    )
    request = {
        "user": user,
        "intent": "ally_creation_started",
        "occurred_at": datetime.now(UTC),
        "idempotency_key": KEY,
    }
    with pytest.raises(FoundryGatewayRetryable):
        request_workspace_runtime_intent(**request)
    assert request_workspace_runtime_intent(**request).status == "already_ready"
    assert forwarded == [KEY, KEY]


@pytest.mark.django_db
@override_settings(ALLIES_RUNTIME_INTENT_ENABLED=True)
def test_pending_duplicate_does_not_report_unconfirmed_wake(account, monkeypatch):
    user, _workspace = account
    request = {
        "user": user,
        "intent": "ally_creation_started",
        "occurred_at": datetime.now(UTC),
        "idempotency_key": KEY,
    }

    def forward(**kwargs):
        with pytest.raises(FoundryGatewayRetryable):
            request_workspace_runtime_intent(**request)
        return RuntimeIntentReceipt(status="ready")

    monkeypatch.setattr(
        "allies.services.runtime_intents.forward_runtime_intent", forward
    )
    assert request_workspace_runtime_intent(**request).status == "ready"
    assert request_workspace_runtime_intent(**request).status == "ready"


@pytest.mark.django_db
@override_settings(ALLIES_RUNTIME_INTENT_ENABLED=True)
def test_final_cache_failure_allows_same_key_retry(account, monkeypatch):
    user, _workspace = account
    forwarded = []
    original_set = cache.set

    def forward(**kwargs):
        forwarded.append(kwargs["idempotency_key"])
        return RuntimeIntentReceipt(status="already_ready")

    def fail_set(*args, **kwargs):
        raise ConnectionError("cache unavailable")

    monkeypatch.setattr(
        "allies.services.runtime_intents.forward_runtime_intent", forward
    )
    monkeypatch.setattr(
        "allies.services.runtime_intents.check_rate_limit", lambda **_: None
    )
    monkeypatch.setattr(cache, "set", fail_set)
    request = {
        "user": user,
        "intent": "ally_creation_started",
        "occurred_at": datetime.now(UTC),
        "idempotency_key": KEY,
    }
    with pytest.raises(ThrottleUnavailable):
        request_workspace_runtime_intent(**request)
    monkeypatch.setattr(cache, "set", original_set)
    assert request_workspace_runtime_intent(**request).status == "already_ready"
    assert forwarded == [KEY, KEY]
