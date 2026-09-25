import base64
import hashlib
import json
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

import pytest

from allies.models import Ally, AllyBinding
from auths.models import User
from integrations.exceptions import (
    IntegrationConflict,
    IntegrationInvalid,
    IntegrationUnavailable,
    ProviderUnavailable,
    RefreshRevoked,
    ScopeInsufficient,
)
from integrations.models import GmailConnectSession, IntegrationSecret
from integrations.services import google_oauth
from integrations.services.google_oauth import (
    GMAIL_SEND_SCOPE,
    complete_gmail_connect,
)
from integrations.services.vault import seal_refresh_token
from workspaces.models import Membership, Workspace

VAULT_KEY_B64 = base64.urlsafe_b64encode(b"v" * 32).decode()
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


def fake_urlopen_factory(*, token=None, sub="google-sub-1", email="user@gmail.com"):
    def _fake(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "oauth2.googleapis.com/token" in url:
            return FakeResponse(token)
        if "userinfo" in url:
            return FakeResponse({"sub": sub})
        if "gmail.googleapis.com" in url:
            return FakeResponse({"emailAddress": email})
        if "oauth2.googleapis.com/revoke" in url:
            return FakeResponse({})
        raise AssertionError(f"unexpected provider call: {url}")

    return _fake


@pytest.fixture
def gmail_settings(settings):
    settings.ALLIES_GMAIL_ENABLED = True
    settings.ALLIES_GMAIL_CLIENT_ID = "test-client-id"
    settings.ALLIES_GMAIL_CLIENT_SECRET = "test-client-secret"
    settings.ALLIES_GMAIL_REDIRECT_URI = "https://app.example/callback"
    settings.ALLIES_INTEGRATIONS_VAULT_KEY = VAULT_KEY_B64
    return settings


@pytest.fixture
def account(db):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Gmail workspace")
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


def _state_from_auth_url(auth_url):
    return parse_qs(urlparse(auth_url).query)["state"][0]


@pytest.mark.django_db
def test_begin_and_complete_connect(account, gmail_settings, monkeypatch):
    _, workspace, ally = account
    begun = google_oauth.begin_gmail_connect(
        workspace=workspace,
        entry_point="in_chat",
        ally=ally,
        grant_level="read",
        idempotency_key="connect-key-0000000001",
    )
    assert begun.auth_url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    scope_param = parse_qs(urlparse(begun.auth_url).query)["scope"][0]
    assert GMAIL_SEND_SCOPE in scope_param
    token = {
        "access_token": "ya29.test",
        "refresh_token": "refresh.test",
        "scope": FULL_SCOPES,
        "expires_in": 3600,
    }
    monkeypatch.setattr(google_oauth, "urlopen", fake_urlopen_factory(token=token))
    completed = complete_gmail_connect(
        state=_state_from_auth_url(begun.auth_url), code="auth-code-1"
    )
    assert completed.status == "connected"
    assert completed.auto_grant_ally_id == str(ally.id)
    assert completed.auto_grant_level == "read"
    secret = IntegrationSecret.objects.get(pk=completed.secret.pk)
    assert secret.account_email == "user@gmail.com"
    assert set(secret.scope_set) == set(FULL_SCOPES.split())
    assert b"refresh.test" not in bytes(secret.ciphertext)
    assert GmailConnectSession.objects.get().consumed_at is not None


@pytest.mark.django_db
def test_begin_replay_returns_live_session(account, gmail_settings):
    _, workspace, ally = account
    first = google_oauth.begin_gmail_connect(
        workspace=workspace,
        entry_point="in_chat",
        ally=ally,
        grant_level="send",
        idempotency_key="connect-key-0000000002",
    )
    second = google_oauth.begin_gmail_connect(
        workspace=workspace,
        entry_point="in_chat",
        ally=ally,
        grant_level="send",
        idempotency_key="connect-key-0000000002",
    )
    assert str(first.connect_session_id) == str(second.connect_session_id)
    assert GmailConnectSession.objects.count() == 1


@pytest.mark.django_db
def test_begin_rejects_bad_entry_and_flag_off(account, gmail_settings):
    _, workspace, ally = account
    with pytest.raises(IntegrationInvalid):
        google_oauth.begin_gmail_connect(
            workspace=workspace,
            entry_point="in_chat",
            ally=ally,
            grant_level=None,
            idempotency_key="connect-key-0000000003",
        )
    gmail_settings.ALLIES_GMAIL_ENABLED = False
    with pytest.raises(IntegrationUnavailable):
        google_oauth.begin_gmail_connect(
            workspace=workspace,
            entry_point="integrations",
            idempotency_key="connect-key-0000000004",
        )


@pytest.mark.django_db
def test_complete_rejects_scope_shortfall_and_stores_nothing(
    account, gmail_settings, monkeypatch
):
    _, workspace, _ally = account
    begun = google_oauth.begin_gmail_connect(
        workspace=workspace,
        entry_point="integrations",
        idempotency_key="connect-key-0000000006",
    )
    token = {
        "access_token": "ya29.test",
        "refresh_token": "refresh.test",
        "scope": "https://www.googleapis.com/auth/gmail.readonly",
        "expires_in": 3600,
    }
    monkeypatch.setattr(google_oauth, "urlopen", fake_urlopen_factory(token=token))
    with pytest.raises(ScopeInsufficient):
        complete_gmail_connect(
            state=_state_from_auth_url(begun.auth_url), code="auth-code-2"
        )
    assert IntegrationSecret.objects.count() == 0


@pytest.mark.django_db
def test_complete_rejects_second_account(account, gmail_settings, monkeypatch):
    _, workspace, _ = account
    for index, sub in enumerate(("google-sub-a", "google-sub-b")):
        begun = google_oauth.begin_gmail_connect(
            workspace=workspace,
            entry_point="integrations",
            idempotency_key=f"connect-key-dupe-{index:010d}",
        )
        token = {
            "access_token": "ya29.test",
            "refresh_token": f"refresh.{sub}",
            "scope": FULL_SCOPES,
            "expires_in": 3600,
        }
        monkeypatch.setattr(
            google_oauth, "urlopen", fake_urlopen_factory(token=token, sub=sub)
        )
        if index == 0:
            complete_gmail_connect(
                state=_state_from_auth_url(begun.auth_url), code="auth-code-3"
            )
        else:
            with pytest.raises(IntegrationConflict):
                complete_gmail_connect(
                    state=_state_from_auth_url(begun.auth_url), code="auth-code-4"
                )


@pytest.mark.django_db
def test_complete_rejects_unknown_and_expired_state(
    account, gmail_settings, monkeypatch
):
    _, workspace, _ = account
    with pytest.raises(IntegrationInvalid):
        complete_gmail_connect(state="no-such-state", code="auth-code-5")
    begun = google_oauth.begin_gmail_connect(
        workspace=workspace,
        entry_point="integrations",
        idempotency_key="connect-key-0000000006",
    )
    session = GmailConnectSession.objects.get(pk=begun.connect_session_id)
    state_hash = session.state_hash
    from django.utils import timezone

    GmailConnectSession.objects.filter(pk=session.pk).update(
        expires_at=timezone.now() - timezone.timedelta(seconds=1)
    )
    with pytest.raises(IntegrationInvalid):
        complete_gmail_connect(
            state=_state_from_auth_url(begun.auth_url), code="auth-code-6"
        )
    assert state_hash == session.state_hash


@pytest.mark.django_db
def test_refresh_happy_path_and_revoked(account, gmail_settings, monkeypatch):
    _, workspace, _ = account
    ciphertext, version = seal_refresh_token("refresh.live")
    secret = IntegrationSecret.objects.create(
        workspace=workspace,
        provider_key="gmail",
        account_ref_hash=hashlib.sha256(b"google-sub-1").hexdigest(),
        account_email="user@gmail.com",
        ciphertext=bytes(ciphertext),
        key_version=version,
        scope_set=FULL_SCOPES.split(),
    )
    monkeypatch.setattr(
        google_oauth,
        "urlopen",
        fake_urlopen_factory(token={"access_token": "ya29.fresh", "expires_in": 3600}),
    )
    minted = google_oauth.refresh_access_token(secret)
    assert minted.access_token == "ya29.fresh"

    def _revoked(request, timeout=None):
        return FakeResponse({"error": "invalid_grant"})

    monkeypatch.setattr(google_oauth, "urlopen", _revoked)
    with pytest.raises(RefreshRevoked):
        google_oauth.refresh_access_token(secret)


@pytest.mark.django_db
def test_refresh_provider_outage_is_retryable(account, gmail_settings, monkeypatch):
    _, workspace, _ = account
    ciphertext, version = seal_refresh_token("refresh.live")
    secret = IntegrationSecret.objects.create(
        workspace=workspace,
        provider_key="gmail",
        account_ref_hash=hashlib.sha256(b"google-sub-1").hexdigest(),
        account_email="user@gmail.com",
        ciphertext=bytes(ciphertext),
        key_version=version,
        scope_set=FULL_SCOPES.split(),
    )

    def _down(request, timeout=None):
        raise URLError("connection refused")

    monkeypatch.setattr(google_oauth, "urlopen", _down)
    with pytest.raises(ProviderUnavailable):
        google_oauth.refresh_access_token(secret)


@pytest.mark.django_db
def test_revoke_reports_success_and_failure(gmail_settings, monkeypatch):
    monkeypatch.setattr(google_oauth, "urlopen", fake_urlopen_factory(token={}))
    assert google_oauth.revoke_at_google("refresh.x") is True

    def _down(request, timeout=None):
        raise URLError("connection refused")

    monkeypatch.setattr(google_oauth, "urlopen", _down)
    assert google_oauth.revoke_at_google("refresh.x") is False
