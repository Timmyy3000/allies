import base64
import hashlib
import json
import logging
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from django.utils import timezone

from auths.api import native as native_api
from auths.exceptions import (
    InvalidFlow,
    InvalidRedirect,
    NativeExchangeInvalid,
    NativeExchangeReplay,
    NativeIdentityUnavailable,
    ProviderRejected,
    ProviderUnavailable,
    SessionInvalid,
)
from auths.models import (
    NativeAuthorizationTransaction,
    NativeCompletionMode,
    NativeExchangeCode,
    NativeTransactionStatus,
    SessionClientKind,
    SessionFamily,
)
from auths.providers.base import ProviderFlow, ProviderKey, VerifiedIdentity
from auths.services import native_authorization, native_sessions
from auths.services.accounts import resolve_or_create_user
from auths.services.native_authorization import (
    NativeCallbackResult,
    begin_native_sign_in,
    complete_native_callback,
)
from auths.services.native_sessions import (
    exchange_native_code,
    logout_native_session,
    refresh_native_session,
)
from auths.services.sessions import authenticate_access, issue_session
from auths.throttle import ThrottleExceeded, ThrottleUnavailable

APP_REDIRECT = "allies://auth/callback"
NATIVE_CALLBACK = "https://cloud.example/api/v1/auths/native/callback/google"


class FixtureGoogleProvider:
    key = ProviderKey.GOOGLE

    def __init__(self):
        self.authorization_flows: list[ProviderFlow] = []
        self.callback_flows: list[ProviderFlow] = []

    def authorization_url(self, flow: ProviderFlow) -> str:
        self.authorization_flows.append(flow)
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(flow.pkce_verifier.encode()).digest()
            )
            .rstrip(b"=")
            .decode()
        )
        return "https://provider.example/authorize?" + urlencode(
            {
                "state": flow.state,
                "redirect_uri": flow.redirect_uri,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )

    def verify_callback(self, code: str, flow: ProviderFlow) -> VerifiedIdentity:
        self.callback_flows.append(flow)
        if code == "provider-failure":
            raise ProviderRejected("provider response rejected")
        return VerifiedIdentity(
            provider="google",
            subject=code.removeprefix("provider:"),
            issuer="https://accounts.google.com",
        )


@pytest.fixture(autouse=True)
def native_test_settings(settings):
    values = {
        "ALLOWED_HOSTS": ["testserver"],
        "ALLIES_AUTH_NATIVE_ENABLED": True,
        "ALLIES_AUTH_GOOGLE_ENABLED": True,
        "ALLIES_AUTH_GOOGLE_CLIENT_ID": "native-client-id",
        "ALLIES_AUTH_GOOGLE_CLIENT_SECRET": "native-client-secret",
        "ALLIES_AUTH_GOOGLE_REDIRECT_URI": "https://cloud.example/api/v1/auths/callback/google",
        "ALLIES_AUTH_GOOGLE_NATIVE_REDIRECT_URI": NATIVE_CALLBACK,
        "ALLIES_AUTH_NATIVE_REDIRECT_URIS": [APP_REDIRECT],
        "ALLIES_AUTH_NATIVE_SIGN_IN_LIMIT": 100,
        "ALLIES_AUTH_NATIVE_EXCHANGE_LIMIT": 100,
        "ALLIES_AUTH_NATIVE_REFRESH_LIMIT": 100,
        "ALLIES_AUTH_NATIVE_LOGOUT_LIMIT": 100,
        "ALLIES_AUTH_NATIVE_GLOBAL_LIMIT": 1000,
        "ALLIES_AUTH_JWT_KEY": "native-test-jwt-key-at-least-thirty-two-bytes",
        "ALLIES_AUTH_DIGEST_KEY": "native-test-digest-key-at-least-thirty-two-bytes",
    }
    for name, value in values.items():
        setattr(settings, name, value)
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def fixture_provider(monkeypatch):
    provider = FixtureGoogleProvider()
    monkeypatch.setattr(native_authorization, "get_provider", lambda _: provider)
    return provider


def _pkce() -> tuple[str, str]:
    verifier = "V" * 43
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def _start_flow(fixture_provider, *, completion_mode=NativeCompletionMode.REDIRECT):
    verifier, challenge = _pkce()
    start = begin_native_sign_in(
        provider=ProviderKey.GOOGLE,
        redirect_uri=APP_REDIRECT,
        code_challenge=challenge,
        state="app-state-123",
        completion_mode=completion_mode,
    )
    provider_state = parse_qs(urlparse(start.authorization_url).query)["state"][0]
    return start, provider_state, verifier, challenge


def _callback_query(location: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(location).query)


@pytest.mark.django_db
def test_native_callback_exchange_refresh_and_logout_bind_one_native_family(
    fixture_provider,
):
    start, provider_state, verifier, _ = _start_flow(fixture_provider)

    callback = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=provider_state,
        provider_code="provider:native-user",
    )
    callback_values = _callback_query(callback.location)
    cloud_code = callback_values["code"][0]
    assert callback_values["state"] == ["app-state-123"]
    assert urlparse(callback.location).scheme == "allies"
    assert "access_token" not in callback.location
    assert "refresh_token" not in callback.location

    transaction_row = NativeAuthorizationTransaction.objects.get(
        state_digest=native_authorization._digest(provider_state)
    )
    assert transaction_row.status == NativeTransactionStatus.COMPLETED
    assert transaction_row.callback_uri == NATIVE_CALLBACK
    assert transaction_row.app_state_sealed != "app-state-123"
    assert provider_state not in transaction_row.state_digest
    assert fixture_provider.authorization_flows[0].redirect_uri == NATIVE_CALLBACK
    assert fixture_provider.callback_flows[0].redirect_uri == NATIVE_CALLBACK
    assert start.expires_at > timezone.now()

    issued = exchange_native_code(
        code=cloud_code,
        code_verifier=verifier,
        redirect_uri=APP_REDIRECT,
    )
    authenticated = authenticate_access(
        issued.access_token, expected_client_kind=SessionClientKind.NATIVE
    )
    assert issued.family.client_kind == SessionClientKind.NATIVE
    import uuid

    assert isinstance(authenticated.user.id, uuid.UUID)

    with pytest.raises(NativeExchangeReplay):
        exchange_native_code(
            code=cloud_code,
            code_verifier=verifier,
            redirect_uri=APP_REDIRECT,
        )

    rotated = refresh_native_session(issued.refresh_token)
    assert rotated.refresh_token != issued.refresh_token
    assert rotated.family.pk == issued.family.pk

    logout_native_session(
        refresh_token=rotated.refresh_token,
        access_token=rotated.access_token,
    )
    family = SessionFamily.objects.get(pk=issued.family.pk)
    assert family.revoked_at is not None
    with pytest.raises(SessionInvalid):
        authenticate_access(rotated.access_token)
    assert logout_native_session(refresh_token="unknown-native-refresh") is None


@pytest.mark.django_db
def test_native_logout_rejects_unknown_refresh_with_valid_bearer(fixture_provider):
    _, provider_state, verifier, _ = _start_flow(fixture_provider)
    callback = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=provider_state,
        provider_code="provider:logout-proof",
    )
    issued = exchange_native_code(
        code=_callback_query(callback.location)["code"][0],
        code_verifier=verifier,
        redirect_uri=APP_REDIRECT,
    )

    with pytest.raises(SessionInvalid):
        logout_native_session(
            refresh_token="unknown-native-refresh",
            access_token=issued.access_token,
        )

    authenticate_access(
        issued.access_token,
        expected_client_kind=SessionClientKind.NATIVE,
    )


@pytest.mark.django_db
def test_native_refresh_reuse_revokes_family(fixture_provider):
    _, provider_state, verifier, _ = _start_flow(fixture_provider)
    callback = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=provider_state,
        provider_code="provider:refresh-reuse",
    )
    cloud_code = _callback_query(callback.location)["code"][0]
    issued = exchange_native_code(
        code=cloud_code,
        code_verifier=verifier,
        redirect_uri=APP_REDIRECT,
    )
    refresh_native_session(issued.refresh_token)

    with pytest.raises(SessionInvalid):
        refresh_native_session(issued.refresh_token)
    family = SessionFamily.objects.get(pk=issued.family.pk)
    assert family.revoke_reason == "refresh_reuse"
    with pytest.raises(SessionInvalid):
        authenticate_access(issued.access_token)


@pytest.mark.django_db
def test_native_callback_replay_is_safe_and_provider_is_called_once(fixture_provider):
    _, provider_state, verifier, _ = _start_flow(fixture_provider)
    first = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=provider_state,
        provider_code="provider:replay-user",
    )
    second = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=provider_state,
        provider_code="provider:replay-user",
    )
    assert second.location == first.location
    assert len(fixture_provider.callback_flows) == 1

    cloud_code = _callback_query(first.location)["code"][0]
    exchange_native_code(
        code=cloud_code,
        code_verifier=verifier,
        redirect_uri=APP_REDIRECT,
    )
    terminal = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=provider_state,
        provider_code="provider:replay-user",
    )
    terminal_values = _callback_query(terminal.location)
    assert terminal_values["error"] == ["exchange_invalid"]
    assert "code" not in terminal_values


@pytest.mark.django_db
def test_manual_callback_retries_reuse_code_and_original_expiry(fixture_provider):
    _, provider_state, _, _ = _start_flow(
        fixture_provider, completion_mode=NativeCompletionMode.MANUAL_CODE
    )
    first = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=provider_state,
        provider_code="provider:manual-retry",
    )
    assert first.completion_mode is NativeCompletionMode.MANUAL_CODE
    assert first.location is None
    assert first.code
    assert first.expires_at is not None
    exchange = NativeExchangeCode.objects.get()
    assert first.expires_at == exchange.expires_at

    second = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=provider_state,
        provider_code="provider:manual-retry",
    )
    assert second.completion_mode is NativeCompletionMode.MANUAL_CODE
    assert second.code == first.code
    assert second.expires_at == first.expires_at
    assert NativeExchangeCode.objects.count() == 1


@pytest.mark.django_db
def test_manual_code_wrong_verifier_does_not_consume_code(fixture_provider):
    _, provider_state, verifier, _ = _start_flow(
        fixture_provider, completion_mode=NativeCompletionMode.MANUAL_CODE
    )
    callback = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=provider_state,
        provider_code="provider:manual-pkce",
    )
    assert callback.code is not None

    with pytest.raises(NativeExchangeInvalid):
        exchange_native_code(
            code=callback.code,
            code_verifier="W" * 43,
            redirect_uri=APP_REDIRECT,
        )
    exchange = NativeExchangeCode.objects.get()
    assert exchange.consumed_at is None

    exchange_native_code(
        code=callback.code,
        code_verifier=verifier,
        redirect_uri=APP_REDIRECT,
    )


@pytest.mark.django_db
def test_manual_callback_hides_consumed_and_expired_codes(fixture_provider):
    _, consumed_state, verifier, _ = _start_flow(
        fixture_provider, completion_mode=NativeCompletionMode.MANUAL_CODE
    )
    consumed = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=consumed_state,
        provider_code="provider:manual-consumed",
    )
    exchange_native_code(
        code=consumed.code,
        code_verifier=verifier,
        redirect_uri=APP_REDIRECT,
    )
    consumed_retry = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=consumed_state,
        provider_code="provider:manual-consumed",
    )
    assert consumed_retry.code is None
    assert consumed_retry.expires_at is None
    assert consumed_retry.error_code == "exchange_invalid"

    _, expired_state, _, _ = _start_flow(
        fixture_provider, completion_mode=NativeCompletionMode.MANUAL_CODE
    )
    complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=expired_state,
        provider_code="provider:manual-expired",
    )
    NativeExchangeCode.objects.filter(
        transaction__state_digest=native_authorization._digest(expired_state)
    ).update(expires_at=timezone.now())
    expired_retry = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=expired_state,
        provider_code="provider:manual-expired",
    )
    assert expired_retry.code is None
    assert expired_retry.error_code == "exchange_invalid"


@pytest.mark.django_db
def test_manual_callback_http_page_is_private_and_escapes_code(fixture_provider):
    client = Client()
    _, challenge = _pkce()
    start_response = client.post(
        "/api/v1/auths/native/sign-in/google",
        {
            "redirect_uri": APP_REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "manual-http-state",
            "completion_mode": "manual_code",
        },
        content_type="application/json",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )
    provider_state = parse_qs(
        urlparse(start_response.json()["data"]["authorization_url"]).query
    )["state"][0]
    assert (
        NativeAuthorizationTransaction.objects.get(
            state_digest=native_authorization._digest(provider_state)
        ).completion_mode
        == NativeCompletionMode.MANUAL_CODE
    )
    callback_response = client.get(
        "/api/v1/auths/native/callback/google",
        {"state": provider_state, "code": "provider:manual-http"},
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )
    body = callback_response.content.decode()
    assert callback_response.status_code == 200
    assert callback_response["Content-Type"] == "text/html; charset=utf-8"
    assert "Location" not in callback_response
    assert callback_response["Cache-Control"] == "no-store"
    assert callback_response["Pragma"] == "no-cache"
    assert callback_response["Referrer-Policy"] == "no-referrer"
    assert callback_response["X-Content-Type-Options"] == "nosniff"
    csp = callback_response["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    assert "script-src 'nonce-" in csp
    assert "Copy sign-in code" in body
    assert '<code id="sign-in-code"' in body
    assert "<input" not in body
    exchange = NativeExchangeCode.objects.get()
    raw_code = native_authorization._unseal(
        exchange.code_sealed,
        max_age=native_authorization.native_exchange_ttl_seconds() + 60,
    )
    assert raw_code in body
    assert "Expires in" in body

    escaped_expires_at = timezone.now() + timedelta(seconds=30)
    escaped = native_api._manual_callback_response(
        NativeCallbackResult(
            completion_mode=NativeCompletionMode.MANUAL_CODE,
            code='</textarea><script>alert("x")</script>',
            expires_at=escaped_expires_at,
        )
    )
    escaped_body = escaped.content.decode()
    assert '</textarea><script>alert("x")</script>' not in escaped_body
    assert "&lt;/textarea&gt;&lt;script&gt;" in escaped_body
    assert "const deadline = Date.now() + " in escaped_body
    assert "window.setInterval" in escaped_body
    assert 'code.textContent = "";' in escaped_body
    assert "navigator.clipboard.writeText(code.textContent)" in escaped_body
    assert "range.selectNodeContents(code)" in escaped_body
    assert "if (selection) {" in escaped_body
    assert "button.disabled = true;" in escaped_body

    expired_page = native_api._manual_callback_response(
        NativeCallbackResult(
            completion_mode=NativeCompletionMode.MANUAL_CODE,
            code="expired-code",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
    )
    expired_body = expired_page.content.decode()
    assert 'id="sign-in-code"' not in expired_body
    assert "expired-code" not in expired_body
    assert "expired or was already used" in expired_body

    failure = native_api._manual_callback_response(
        NativeCallbackResult(
            completion_mode=NativeCompletionMode.MANUAL_CODE,
            error_code="exchange_invalid",
        )
    )
    failure_body = failure.content.decode()
    assert failure.status_code == 200
    assert 'id="sign-in-code"' not in failure_body
    assert "expired or was already used" in failure_body
    assert "Location" not in failure


@pytest.mark.django_db
def test_native_start_rejects_unknown_completion_mode(fixture_provider):
    client = Client()
    _, challenge = _pkce()
    response = client.post(
        "/api/v1/auths/native/sign-in/google",
        {
            "redirect_uri": APP_REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "invalid-mode-state",
            "completion_mode": "unknown",
        },
        content_type="application/json",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )
    assert response.status_code == 422
    assert response.json()["data"]["code"] == "validation_error"
    assert NativeAuthorizationTransaction.objects.count() == 0


@pytest.mark.django_db
def test_legacy_0001_insert_uses_database_completion_mode_default():
    historical_apps = (
        MigrationExecutor(connection)
        .loader.project_state([("auths", "0001_initial")])
        .apps
    )
    historical_transaction = historical_apps.get_model(
        "auths", "NativeAuthorizationTransaction"
    )
    now = timezone.now()
    legacy_row = historical_transaction(
        state_digest=native_authorization._digest("legacy-provider-state"),
        provider="google",
        callback_uri=NATIVE_CALLBACK,
        redirect_uri=APP_REDIRECT,
        app_state_sealed="legacy-app-state",
        code_challenge="A" * 43,
        nonce_digest="N" * 64,
        nonce_sealed="legacy-nonce",
        pkce_verifier_sealed="legacy-verifier",
        status=NativeTransactionStatus.PENDING,
        claim_digest="",
        error_code="",
        expires_at=now + timedelta(minutes=1),
    )
    legacy_row.save(force_insert=True)

    current_row = NativeAuthorizationTransaction.objects.get(pk=legacy_row.pk)
    assert current_row.completion_mode == NativeCompletionMode.REDIRECT


@pytest.mark.django_db
def test_native_callback_deleted_after_state_read_is_invalid(
    fixture_provider, monkeypatch
):
    _, provider_state, _, _ = _start_flow(fixture_provider)
    original_get = NativeAuthorizationTransaction.objects.get

    def delete_after_initial_read(*args, **kwargs):
        row = original_get(*args, **kwargs)
        NativeAuthorizationTransaction.objects.filter(pk=row.pk).delete()
        return row

    monkeypatch.setattr(
        NativeAuthorizationTransaction.objects,
        "get",
        delete_after_initial_read,
    )

    with pytest.raises(InvalidFlow, match="native state is invalid"):
        complete_native_callback(
            provider=ProviderKey.GOOGLE,
            provider_state=provider_state,
            provider_code="provider:deleted-after-read",
        )


@pytest.mark.django_db
def test_native_exchange_rejection_emits_safe_audit_event(monkeypatch):
    events = []
    monkeypatch.setattr(
        native_sessions,
        "emit_auth_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )

    with pytest.raises(NativeExchangeInvalid):
        exchange_native_code(
            code="unknown-code",
            code_verifier="V" * 43,
            redirect_uri=APP_REDIRECT,
        )

    assert events == [
        (
            ("auth.native.exchange.rejected",),
            {
                "outcome": "rejected",
                "reason_code": "code_invalid",
                "provider": "",
            },
        )
    ]


@pytest.mark.django_db
def test_native_denial_failure_and_expiry_have_safe_terminal_results(fixture_provider):
    _, denied_state, _, _ = _start_flow(fixture_provider)
    denied = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=denied_state,
        provider_error="access_denied",
    )
    denied_values = _callback_query(denied.location)
    assert denied_values == {"error": ["access_denied"], "state": ["app-state-123"]}
    assert not NativeExchangeCode.objects.exists()
    assert not fixture_provider.callback_flows

    denied_replay = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=denied_state,
        provider_error="access_denied",
    )
    assert denied_replay.location == denied.location

    _, failed_state, _, _ = _start_flow(fixture_provider)
    failed = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=failed_state,
        provider_code="provider-failure",
    )
    failed_values = _callback_query(failed.location)
    assert failed_values["error"] == ["provider_unavailable"]
    assert "provider response rejected" not in failed.location

    _, expired_state, _, _ = _start_flow(fixture_provider)
    NativeAuthorizationTransaction.objects.filter(
        state_digest=native_authorization._digest(expired_state)
    ).update(expires_at=timezone.now())
    expired = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=expired_state,
        provider_code="provider:expired",
    )
    assert _callback_query(expired.location)["error"] == ["flow_expired"]


@pytest.mark.django_db
def test_native_exchange_binds_redirect_pkce_and_one_time_code(fixture_provider):
    _, provider_state, verifier, _ = _start_flow(fixture_provider)
    callback = complete_native_callback(
        provider=ProviderKey.GOOGLE,
        provider_state=provider_state,
        provider_code="provider:exchange-boundary",
    )
    cloud_code = _callback_query(callback.location)["code"][0]

    with pytest.raises(NativeExchangeInvalid):
        exchange_native_code(
            code=cloud_code,
            code_verifier=verifier,
            redirect_uri="allies://auth/other",
        )
    with pytest.raises(NativeExchangeInvalid):
        exchange_native_code(
            code=cloud_code,
            code_verifier="W" * 43,
            redirect_uri=APP_REDIRECT,
        )
    assert NativeExchangeCode.objects.get().consumed_at is None

    issued = exchange_native_code(
        code=cloud_code,
        code_verifier=verifier,
        redirect_uri=APP_REDIRECT,
    )
    assert issued.family.client_kind == SessionClientKind.NATIVE

    with pytest.raises(InvalidRedirect):
        begin_native_sign_in(
            provider=ProviderKey.GOOGLE,
            redirect_uri="javascript:alert(1)",
            code_challenge="A" * 43,
            state="state",
        )
    with pytest.raises(ProviderUnavailable):
        begin_native_sign_in(
            provider="fake",
            redirect_uri=APP_REDIRECT,
            code_challenge="A" * 43,
            state="state",
        )


@pytest.mark.django_db
def test_native_http_contract_has_no_cookie_dependency_and_rejects_cross_transport(
    fixture_provider,
):
    client = Client(enforce_csrf_checks=True)
    verifier, challenge = _pkce()
    payload = {
        "redirect_uri": APP_REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "http-state",
    }
    start_response = client.post(
        "/api/v1/auths/native/sign-in/google",
        payload,
        content_type="application/json",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )
    assert start_response.status_code == 200
    assert start_response["Cache-Control"] == "no-store"
    assert not start_response.cookies

    provider_state = parse_qs(
        urlparse(start_response.json()["data"]["authorization_url"]).query
    )["state"][0]
    assert (
        NativeAuthorizationTransaction.objects.get(
            state_digest=native_authorization._digest(provider_state)
        ).completion_mode
        == NativeCompletionMode.REDIRECT
    )
    callback_response = client.get(
        "/api/v1/auths/native/callback/google",
        {"state": provider_state, "code": "provider:http-user"},
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )
    assert callback_response.status_code == 303
    assert callback_response["Location"].startswith(APP_REDIRECT + "?")
    code = _callback_query(callback_response["Location"])["code"][0]

    token_response = client.post(
        "/api/v1/auths/native/token",
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": APP_REDIRECT,
        },
        content_type="application/json",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )
    assert token_response.status_code == 200
    assert token_response["Cache-Control"] == "no-store"
    assert token_response["Pragma"] == "no-cache"
    assert not token_response.cookies
    token_data = token_response.json()["data"]
    assert token_data["token_type"] == "Bearer"
    assert token_data["expires_in"] <= 600
    assert token_data["refresh_expires_in"] <= 14 * 24 * 60 * 60

    access = token_data["access_token"]
    me_response = client.get(
        "/api/v1/auths/me",
        HTTP_AUTHORIZATION=f"Bearer {access}",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )
    assert me_response.status_code == 200

    profile_response = client.patch(
        "/api/v1/auths/me/profile",
        {"display_name": "Native User"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )
    assert profile_response.status_code == 200

    browser_user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="browser-boundary")
    ).user
    browser_session = issue_session(browser_user)
    browser_bearer = client.get(
        "/api/v1/auths/me",
        HTTP_AUTHORIZATION=f"Bearer {browser_session.access_token}",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )
    assert browser_bearer.status_code == 401
    native_cookie = client.get(
        "/api/v1/auths/me",
        HTTP_COOKIE=f"allies_access={access}",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )
    assert native_cookie.status_code == 401
    mixed = client.get(
        "/api/v1/auths/me",
        HTTP_COOKIE=f"allies_access={browser_session.access_token}",
        HTTP_AUTHORIZATION=f"Bearer {access}",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )
    assert mixed.status_code == 401

    public_bearer = client.post(
        "/api/v1/auths/native/token",
        {
            "grant_type": "authorization_code",
            "code": "x",
            "code_verifier": verifier,
            "redirect_uri": APP_REDIRECT,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )
    assert public_bearer.status_code == 400
    assert public_bearer.json()["data"]["code"] == "exchange_invalid"

    unknown_refresh = client.post(
        "/api/v1/auths/native/logout",
        {"refresh_token": "unknown-refresh"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )
    assert unknown_refresh.status_code == 401
    assert unknown_refresh.json()["data"]["code"] == "session_invalid"
    assert (
        client.get(
            "/api/v1/auths/me",
            HTTP_AUTHORIZATION=f"Bearer {access}",
            HTTP_HOST="testserver",
            REMOTE_ADDR="198.51.100.8",
        ).status_code
        == 200
    )

    logout_response = client.post(
        "/api/v1/auths/native/logout",
        {"refresh_token": token_data["refresh_token"]},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )
    assert logout_response.status_code == 204
    assert logout_response["Cache-Control"] == "no-store"
    assert not logout_response.cookies
    assert (
        client.get(
            "/api/v1/auths/me",
            HTTP_AUTHORIZATION=f"Bearer {access}",
            HTTP_HOST="testserver",
            REMOTE_ADDR="198.51.100.8",
        ).status_code
        == 401
    )


@pytest.mark.django_db
def test_native_global_limit_precedes_sign_in_persistence_when_ip_rotates(
    fixture_provider, settings
):
    settings.ALLIES_RAILWAY_PROXY_MODE = True
    settings.ALLIES_TRUSTED_PROXY_IPS = []
    settings.ALLIES_AUTH_NATIVE_GLOBAL_LIMIT = 1
    client = Client()
    _, challenge = _pkce()
    payload = {
        "redirect_uri": APP_REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "first-state",
    }

    first = client.post(
        "/api/v1/auths/native/sign-in/google",
        payload,
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_X_REAL_IP="198.51.100.8",
    )
    second = client.post(
        "/api/v1/auths/native/sign-in/google",
        {**payload, "state": "second-state"},
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_X_REAL_IP="203.0.113.8",
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert NativeAuthorizationTransaction.objects.count() == 1


@pytest.mark.django_db
def test_native_global_limit_precedes_callback_processing_when_ip_rotates(
    monkeypatch, settings
):
    settings.ALLIES_RAILWAY_PROXY_MODE = True
    settings.ALLIES_TRUSTED_PROXY_IPS = []
    settings.ALLIES_AUTH_NATIVE_GLOBAL_LIMIT = 1
    calls = []

    def reject_callback(**kwargs):
        calls.append(kwargs)
        raise InvalidFlow("invalid callback")

    monkeypatch.setattr(native_api, "complete_native_callback", reject_callback)
    client = Client()

    first = client.get(
        "/api/v1/auths/native/callback/google",
        {"state": "first-state", "code": "first-code"},
        HTTP_HOST="testserver",
        HTTP_X_REAL_IP="198.51.100.8",
    )
    second = client.get(
        "/api/v1/auths/native/callback/google",
        {"state": "second-state", "code": "second-code"},
        HTTP_HOST="testserver",
        HTTP_X_REAL_IP="203.0.113.8",
    )

    assert first.status_code == 400
    assert second.status_code == 429
    assert len(calls) == 1


@pytest.mark.django_db
def test_native_public_routes_are_disabled_and_reject_plain_pkce(
    fixture_provider, settings
):
    settings.ALLIES_AUTH_NATIVE_ENABLED = False
    client = Client()
    disabled = client.post(
        "/api/v1/auths/native/sign-in/google",
        {
            "redirect_uri": APP_REDIRECT,
            "code_challenge": "A" * 43,
            "code_challenge_method": "S256",
            "state": "state",
        },
        content_type="application/json",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )
    assert disabled.status_code == 404

    settings.ALLIES_AUTH_NATIVE_ENABLED = True
    plain = client.post(
        "/api/v1/auths/native/sign-in/google",
        {
            "redirect_uri": APP_REDIRECT,
            "code_challenge": "A" * 43,
            "code_challenge_method": "plain",
            "state": "state",
        },
        content_type="application/json",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )
    assert plain.status_code == 400
    assert plain.json()["data"]["code"] == "pkce_required"


@pytest.mark.django_db
def test_native_http_error_mapping_and_public_bearer_exclusions(
    fixture_provider, monkeypatch
):
    client = Client()
    verifier, challenge = _pkce()
    sign_in_payload = {
        "redirect_uri": APP_REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "error-state",
    }
    request_headers = {
        "HTTP_HOST": "testserver",
        "REMOTE_ADDR": "198.51.100.8",
    }
    native_user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="identity-unavailable-state")
    ).user
    native_issued = issue_session(native_user, client_kind=SessionClientKind.NATIVE)

    sign_in_bearer = client.post(
        "/api/v1/auths/native/sign-in/google",
        sign_in_payload,
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer native-access",
        **request_headers,
    )
    assert sign_in_bearer.status_code == 503
    assert sign_in_bearer.json()["data"]["code"] == "auth_unavailable"

    callback_bearer = client.get(
        "/api/v1/auths/native/callback/google",
        {"state": "callback-state", "code": "provider:user"},
        HTTP_AUTHORIZATION="Bearer native-access",
        **request_headers,
    )
    assert callback_bearer.status_code == 503
    assert callback_bearer.json()["data"]["code"] == "auth_unavailable"

    token_bearer = client.post(
        "/api/v1/auths/native/token",
        {
            "grant_type": "authorization_code",
            "code": "cloud-code",
            "code_verifier": verifier,
            "redirect_uri": APP_REDIRECT,
        },
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer native-access",
        **request_headers,
    )
    assert token_bearer.status_code == 400
    assert token_bearer.json()["data"]["code"] == "exchange_invalid"

    refresh_bearer = client.post(
        "/api/v1/auths/native/token/refresh",
        {"grant_type": "refresh_token", "refresh_token": "refresh"},
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer native-access",
        **request_headers,
    )
    assert refresh_bearer.status_code == 401
    assert refresh_bearer.json()["data"]["code"] == "session_invalid"

    invalid_grant = client.post(
        "/api/v1/auths/native/token",
        {
            "grant_type": "refresh_token",
            "code": "cloud-code",
            "code_verifier": verifier,
            "redirect_uri": APP_REDIRECT,
        },
        content_type="application/json",
        **request_headers,
    )
    assert invalid_grant.status_code == 400
    assert invalid_grant.json()["data"]["code"] == "exchange_invalid"

    invalid_refresh_grant = client.post(
        "/api/v1/auths/native/token/refresh",
        {"grant_type": "authorization_code", "refresh_token": "refresh"},
        content_type="application/json",
        **request_headers,
    )
    assert invalid_refresh_grant.status_code == 401
    assert invalid_refresh_grant.json()["data"]["code"] == "session_invalid"

    invalid_code = client.post(
        "/api/v1/auths/native/token",
        {
            "grant_type": "authorization_code",
            "code": "unknown-code",
            "code_verifier": verifier,
            "redirect_uri": APP_REDIRECT,
        },
        content_type="application/json",
        **request_headers,
    )
    assert invalid_code.status_code == 400
    assert invalid_code.json()["data"]["code"] == "exchange_invalid"

    invalid_refresh = client.post(
        "/api/v1/auths/native/token/refresh",
        {"grant_type": "refresh_token", "refresh_token": "unknown-refresh"},
        content_type="application/json",
        **request_headers,
    )
    assert invalid_refresh.status_code == 401
    assert invalid_refresh.json()["data"]["code"] == "session_invalid"

    invalid_logout = client.post(
        "/api/v1/auths/native/logout",
        {"refresh_token": ""},
        content_type="application/json",
        **request_headers,
    )
    assert invalid_logout.status_code == 401
    assert invalid_logout.json()["data"]["code"] == "session_invalid"

    callback_invalid_state = client.get(
        "/api/v1/auths/native/callback/google",
        {"state": "", "code": "provider:user"},
        **request_headers,
    )
    assert callback_invalid_state.status_code == 400
    assert callback_invalid_state.json()["data"]["code"] == "flow_invalid"

    unsupported_provider = client.post(
        "/api/v1/auths/native/sign-in/unknown",
        sign_in_payload,
        content_type="application/json",
        **request_headers,
    )
    assert unsupported_provider.status_code == 404
    assert unsupported_provider.json()["data"]["code"] == "provider_unavailable"

    def throttled(*args, **kwargs):
        raise ThrottleExceeded("test throttle")

    monkeypatch.setattr(native_api, "check_native_rate_limit", throttled)
    throttled_sign_in = client.post(
        "/api/v1/auths/native/sign-in/google",
        sign_in_payload,
        content_type="application/json",
        **request_headers,
    )
    assert throttled_sign_in.status_code == 429
    assert throttled_sign_in.json()["data"]["code"] == "throttled"

    throttled_callback = client.get(
        "/api/v1/auths/native/callback/google",
        {"state": "callback-state", "code": "provider-code"},
        **request_headers,
    )
    assert throttled_callback.status_code == 429
    assert throttled_callback.json()["data"]["code"] == "throttled"

    def unavailable(*args, **kwargs):
        raise ThrottleUnavailable("test cache")

    monkeypatch.setattr(native_api, "check_native_rate_limit", unavailable)
    unavailable_token = client.post(
        "/api/v1/auths/native/token",
        {
            "grant_type": "authorization_code",
            "code": "cloud-code",
            "code_verifier": verifier,
            "redirect_uri": APP_REDIRECT,
        },
        content_type="application/json",
        **request_headers,
    )
    assert unavailable_token.status_code == 503
    assert unavailable_token.json()["data"]["code"] == "auth_unavailable"

    def identity_unavailable(*args, **kwargs):
        raise NativeIdentityUnavailable("test identity")

    monkeypatch.setattr(native_api, "check_native_rate_limit", identity_unavailable)
    unavailable_refresh = client.post(
        "/api/v1/auths/native/token/refresh",
        {
            "grant_type": "refresh_token",
            "refresh_token": native_issued.refresh_token,
        },
        content_type="application/json",
        **request_headers,
    )
    assert unavailable_refresh.status_code == 503
    assert unavailable_refresh.json()["data"]["code"] == "auth_unavailable"

    unavailable_logout = client.post(
        "/api/v1/auths/native/logout",
        {"refresh_token": native_issued.refresh_token},
        content_type="application/json",
        **request_headers,
    )
    assert unavailable_logout.status_code == 503
    assert unavailable_logout.json()["data"]["code"] == "auth_unavailable"

    rotated = refresh_native_session(native_issued.refresh_token)
    assert rotated.family.pk == native_issued.family.pk
    native_issued.family.refresh_from_db()
    assert native_issued.family.revoked_at is None


@pytest.mark.django_db
def test_native_logout_uses_refresh_proof_when_bearer_header_is_malformed():
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="malformed-logout-bearer")
    ).user
    issued = issue_session(user, client_kind=SessionClientKind.NATIVE)
    client = Client()

    response = client.post(
        "/api/v1/auths/native/logout",
        {"refresh_token": issued.refresh_token},
        content_type="application/json",
        HTTP_AUTHORIZATION="Basic malformed-bearer",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.8",
    )

    assert response.status_code == 204
    issued.family.refresh_from_db()
    assert issued.family.revoke_reason == "logout"


@pytest.mark.django_db
def test_native_flow_logs_redact_request_secrets(fixture_provider, monkeypatch, caplog):
    client = Client(raise_request_exception=False)
    verifier, challenge = _pkce()
    sign_in_payload = {
        "redirect_uri": APP_REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "app-state-secret-value",
    }
    request_headers = {
        "HTTP_HOST": "testserver",
        "REMOTE_ADDR": "198.51.100.8",
    }
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="native-log-redaction")
    ).user
    issued = issue_session(user, client_kind=SessionClientKind.NATIVE)
    audit_events = []
    audit_logger = logging.getLogger("allies.auth")
    original_audit_info = audit_logger.info

    def capture_audit_event(message, *args, **kwargs):
        event = kwargs.get("extra", {}).get("auth_event")
        if event is not None:
            audit_events.append(event)
        return original_audit_info(message, *args, **kwargs)

    monkeypatch.setattr(audit_logger, "info", capture_audit_event)

    with caplog.at_level(logging.INFO):
        started = client.post(
            "/api/v1/auths/native/sign-in/google",
            sign_in_payload,
            content_type="application/json",
            **request_headers,
        )
        assert started.status_code == 200
        provider_state = parse_qs(
            urlparse(started.json()["data"]["authorization_url"]).query
        )["state"][0]

        denied = client.get(
            "/api/v1/auths/native/callback/google",
            {"state": provider_state, "error": "access_denied"},
            **request_headers,
        )
        assert denied.status_code == 303

        failed_start = client.post(
            "/api/v1/auths/native/sign-in/google",
            {**sign_in_payload, "state": "provider-failure-state"},
            content_type="application/json",
            **request_headers,
        )
        failed_state = parse_qs(
            urlparse(failed_start.json()["data"]["authorization_url"]).query
        )["state"][0]

        def reject_provider(*args, **kwargs):
            raise ProviderRejected("provider rejection")

        monkeypatch.setattr(fixture_provider, "verify_callback", reject_provider)
        provider_failed = client.get(
            "/api/v1/auths/native/callback/google",
            {"state": failed_state, "code": "provider-code-secret"},
            **request_headers,
        )
        assert provider_failed.status_code == 303

        refreshed = client.post(
            "/api/v1/auths/native/token/refresh",
            {"grant_type": "refresh_token", "refresh_token": issued.refresh_token},
            content_type="application/json",
            **request_headers,
        )
        assert refreshed.status_code == 200
        rotated_refresh = refreshed.json()["data"]["refresh_token"]

        def throttled(*args, **kwargs):
            raise ThrottleExceeded("test throttle")

        monkeypatch.setattr(native_api, "check_native_rate_limit", throttled)
        throttled_response = client.post(
            "/api/v1/auths/native/sign-in/google",
            {**sign_in_payload, "state": "throttle-state-secret"},
            content_type="application/json",
            **request_headers,
        )
        assert throttled_response.status_code == 429

        monkeypatch.setattr(native_api, "check_native_rate_limit", lambda *a, **k: None)

        def fail_unhandled(*args, **kwargs):
            raise RuntimeError("private failure detail")

        monkeypatch.setattr(native_api, "begin_native_sign_in", fail_unhandled)
        unhandled = client.post(
            "/api/v1/auths/native/sign-in/google",
            {**sign_in_payload, "state": "unhandled-state-secret"},
            content_type="application/json",
            **request_headers,
        )
        assert unhandled.status_code == 500

        logout = client.post(
            "/api/v1/auths/native/logout",
            {"refresh_token": rotated_refresh},
            content_type="application/json",
            **request_headers,
        )
        assert logout.status_code == 204

    raw_values = (
        APP_REDIRECT,
        challenge,
        verifier,
        sign_in_payload["state"],
        "provider-failure-state",
        provider_state,
        failed_state,
        "provider-code-secret",
        issued.refresh_token,
        rotated_refresh,
        "throttle-state-secret",
        "unhandled-state-secret",
    )
    for value in raw_values:
        assert value not in caplog.text
    event_names = {event["event_name"] for event in audit_events}
    assert {
        "auth.native.flow.started",
        "auth.native.flow.rejected",
        "auth.native.refresh.rotated",
        "auth.native.session.revoked",
    } <= event_names
    assert any(
        event["event_name"] == "auth.native.flow.rejected"
        and event["outcome"] == "denied"
        and event["reason_code"] == "access_denied"
        for event in audit_events
    )
    assert any(
        event["event_name"] == "auth.native.flow.rejected"
        and event["outcome"] == "rejected"
        and event["reason_code"] == "provider_unavailable"
        for event in audit_events
    )
    for event in audit_events:
        serialized_event = json.dumps(event, sort_keys=True)
        for value in raw_values:
            assert value not in serialized_event
    assert "unhandled API exception" in caplog.text
