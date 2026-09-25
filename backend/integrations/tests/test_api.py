import json
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from django.test import Client, override_settings

from allies.models import Ally, AllyBinding
from auths.config import cookie_name
from auths.models import User
from auths.services.sessions import issue_session
from integrations.models import IntegrationSecret
from integrations.services import google_oauth
from workspaces.models import Membership, Workspace

FULL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly "
    "https://www.googleapis.com/auth/gmail.send"
)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self, limit=-1):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_urlopen(token):
    def _fake(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "oauth2.googleapis.com/token" in url:
            return FakeResponse(token)
        if "userinfo" in url:
            return FakeResponse({"sub": "google-sub-1"})
        if "gmail.googleapis.com" in url:
            return FakeResponse({"emailAddress": "user@gmail.com"})
        if "oauth2.googleapis.com/revoke" in url:
            return FakeResponse({})
        raise AssertionError(f"unexpected provider call: {url}")

    return _fake


@pytest.fixture
def api_account(db):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="API workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Inbox helper",
        personality="Calm and specific.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    AllyBinding.objects.create(ally=ally)
    return user, workspace, ally


def _client(user):
    client = Client(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")["X-CSRFToken"]
    client.cookies[cookie_name("access")] = issue_session(user).access_token
    return client, csrf


def _headers(csrf, **extra):
    headers = {
        "HTTP_HOST": "testserver",
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_X_CSRFTOKEN": csrf,
    }
    headers.update(extra)
    return headers


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
    ALLIES_GMAIL_ENABLED=True,
    ALLIES_GMAIL_CLIENT_ID="test-client-id",
    ALLIES_GMAIL_CLIENT_SECRET="test-client-secret",
    ALLIES_GMAIL_REDIRECT_URI="https://app.example/callback",
    ALLIES_INTEGRATIONS_VAULT_KEY=Fernet.generate_key().decode(),
)
def test_status_begin_grant_disconnect_flow(api_account, monkeypatch):
    user, workspace, ally = api_account
    client, csrf = _client(user)
    base = f"/api/v1/workspaces/{workspace.id}/integrations/gmail"

    empty = client.get(base, **_headers(csrf))
    assert empty.status_code == 200
    assert empty.json()["data"] is None

    begun = client.post(
        f"{base}/connect",
        json.dumps(
            {
                "entry_point": "in_chat",
                "ally_id": str(ally.id),
                "grant_level": "send",
            }
        ),
        content_type="application/json",
        **_headers(csrf, HTTP_IDEMPOTENCY_KEY="api-connect-key-0001"),
    )
    assert begun.status_code == 202
    auth_url = begun.json()["data"]["auth_url"]
    state = parse_qs(urlparse(auth_url).query)["state"][0]

    token = {
        "access_token": "ya29.test",
        "refresh_token": "refresh.test",
        "scope": FULL_SCOPES,
        "expires_in": 3600,
    }
    monkeypatch.setattr(google_oauth, "urlopen", fake_urlopen(token))
    callback = client.get(
        f"/api/v1/integrations/gmail/callback?code=auth-code-9&state={state}",
        **_headers(csrf),
    )
    assert callback.status_code == 200
    data = callback.json()["data"]
    assert data["account_email"] == "user@gmail.com"
    assert len(data["ally_grants"]) == 1
    assert data["ally_grants"][0]["level"] == "send"

    removed = client.post(
        f"{base}/grants",
        json.dumps({"ally_id": str(ally.id), "level": "none"}),
        content_type="application/json",
        **_headers(csrf),
    )
    assert removed.status_code == 200
    assert removed.json()["data"]["level"] == "none"

    denied = client.post(
        f"{base}/grants",
        json.dumps({"ally_id": str(ally.id), "level": "send"}),
        content_type="application/json",
        **_headers(csrf),
    )
    assert denied.status_code == 200

    gone = client.delete(
        base,
        json.dumps({"confirm": True}),
        content_type="application/json",
        **_headers(csrf),
    )
    assert gone.status_code == 202
    assert gone.json()["data"]["status"] == "deprovisioned"
    secret = IntegrationSecret.objects.get()
    assert secret.revoked_at is not None


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
    ALLIES_GMAIL_ENABLED=True,
    ALLIES_GMAIL_CLIENT_ID="test-client-id",
    ALLIES_GMAIL_CLIENT_SECRET="test-client-secret",
    ALLIES_GMAIL_REDIRECT_URI="https://app.example/callback",
    ALLIES_INTEGRATIONS_VAULT_KEY=Fernet.generate_key().decode(),
)
def test_callback_scope_shortfall_returns_422(api_account, monkeypatch):
    user, workspace, _ = api_account
    client, csrf = _client(user)
    base = f"/api/v1/workspaces/{workspace.id}/integrations/gmail"
    begun = client.post(
        f"{base}/connect",
        json.dumps({"entry_point": "integrations"}),
        content_type="application/json",
        **_headers(csrf, HTTP_IDEMPOTENCY_KEY="k" * 16),
    )
    assert begun.status_code == 202
    state = parse_qs(urlparse(begun.json()["data"]["auth_url"]).query)["state"][0]
    token = {
        "access_token": "ya29.test",
        "refresh_token": "refresh.test",
        "scope": "https://www.googleapis.com/auth/gmail.readonly",
        "expires_in": 3600,
    }
    monkeypatch.setattr(google_oauth, "urlopen", fake_urlopen(token))
    callback = client.get(
        f"/api/v1/integrations/gmail/callback?code=auth-code-8&state={state}",
        **_headers(csrf),
    )
    assert callback.status_code == 422
    assert callback.json()["data"]["code"] == "scope_insufficient"


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
    ALLIES_GMAIL_ENABLED=True,
    ALLIES_GMAIL_CLIENT_ID="test-client-id",
    ALLIES_GMAIL_CLIENT_SECRET="test-client-secret",
    ALLIES_GMAIL_REDIRECT_URI="https://app.example/callback",
    ALLIES_INTEGRATIONS_VAULT_KEY=Fernet.generate_key().decode(),
)
def test_outsider_gets_nothing_and_creates_nothing(api_account, monkeypatch):
    from integrations.models import AllyIntegrationGrant, IntegrationSecret

    _, workspace, ally = api_account
    outsider = User.objects.create_user()
    client, csrf = _client(outsider)
    base = f"/api/v1/workspaces/{workspace.id}/integrations/gmail"

    assert client.get(base, **_headers(csrf)).status_code == 404
    begun = client.post(
        f"{base}/connect",
        json.dumps({"entry_point": "integrations"}),
        content_type="application/json",
        **_headers(csrf, HTTP_IDEMPOTENCY_KEY="o" * 16),
    )
    assert begun.status_code == 404
    denied_grant = client.post(
        f"{base}/grants",
        json.dumps({"ally_id": str(ally.id), "level": "read"}),
        content_type="application/json",
        **_headers(csrf),
    )
    assert denied_grant.status_code == 404
    denied_delete = client.delete(
        base,
        json.dumps({"confirm": True}),
        content_type="application/json",
        **_headers(csrf),
    )
    assert denied_delete.status_code == 404
    assert IntegrationSecret.objects.count() == 0
    assert AllyIntegrationGrant.objects.count() == 0
    from integrations.models import GmailConnectSession

    assert GmailConnectSession.objects.count() == 0


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
    ALLIES_GMAIL_ENABLED=True,
    ALLIES_GMAIL_CLIENT_ID="test-client-id",
    ALLIES_GMAIL_CLIENT_SECRET="test-client-secret",
    ALLIES_GMAIL_REDIRECT_URI="https://app.example/callback",
    ALLIES_INTEGRATIONS_VAULT_KEY=Fernet.generate_key().decode(),
)
def test_callback_checks_capability_before_mutating(api_account, monkeypatch):
    from integrations.models import GmailConnectSession, IntegrationSecret

    user, workspace, _ = api_account
    owner_client, owner_csrf = _client(user)
    base = f"/api/v1/workspaces/{workspace.id}/integrations/gmail"
    begun = owner_client.post(
        f"{base}/connect",
        json.dumps({"entry_point": "integrations"}),
        content_type="application/json",
        **_headers(owner_csrf, HTTP_IDEMPOTENCY_KEY="c" * 16),
    )
    assert begun.status_code == 202
    state = parse_qs(urlparse(begun.json()["data"]["auth_url"]).query)["state"][0]

    token = {
        "access_token": "ya29.test",
        "refresh_token": "refresh.test",
        "scope": FULL_SCOPES,
        "expires_in": 3600,
    }
    monkeypatch.setattr(google_oauth, "urlopen", fake_urlopen(token))
    outsider = User.objects.create_user()
    outsider_client, outsider_csrf = _client(outsider)
    denied = outsider_client.get(
        f"/api/v1/integrations/gmail/callback?code=auth-code-7&state={state}",
        **_headers(outsider_csrf),
    )
    assert denied.status_code == 404
    assert IntegrationSecret.objects.count() == 0
    session = GmailConnectSession.objects.get()
    assert session.consumed_at is None
