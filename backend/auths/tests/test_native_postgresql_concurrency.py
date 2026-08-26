import base64
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from django.db import close_old_connections, connection
from django.test import override_settings
from django.utils import timezone

from auths.exceptions import InvalidFlow, NativeCallbackInProgress, NativeExchangeReplay
from auths.models import (
    NativeAuthorizationTransaction,
    NativeExchangeCode,
    NativeTransactionStatus,
    User,
)
from auths.providers.base import ProviderFlow, ProviderKey, VerifiedIdentity
from auths.services import native_authorization
from auths.services.cleanup import cleanup_auth_artifacts
from auths.services.native_authorization import (
    begin_native_sign_in,
    complete_native_callback,
)
from auths.services.native_sessions import exchange_native_code

APP_REDIRECT = "allies://auth/callback"
NATIVE_CALLBACK = "https://cloud.example/api/v1/auths/native/callback/google"


def _challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
@override_settings(
    ALLIES_AUTH_NATIVE_ENABLED=True,
    ALLIES_AUTH_GOOGLE_ENABLED=True,
    ALLIES_AUTH_GOOGLE_NATIVE_REDIRECT_URI=NATIVE_CALLBACK,
    ALLIES_AUTH_GOOGLE_REDIRECT_URI="https://cloud.example/api/v1/auths/callback/google",
    ALLIES_AUTH_NATIVE_REDIRECT_URIS=[APP_REDIRECT],
    ALLIES_AUTH_JWT_KEY="native-postgres-jwt-key-at-least-thirty-two-bytes",
    ALLIES_AUTH_DIGEST_KEY="native-postgres-digest-key-at-least-thirty-two-bytes",
)
def test_native_exchange_has_one_postgresql_winner():
    if connection.vendor != "postgresql":
        pytest.skip("native exchange race requires PostgreSQL")

    now = timezone.now()
    user = User.objects.create_user()
    transaction_row = NativeAuthorizationTransaction.objects.create(
        state_digest=hashlib.sha256(b"native-pg-exchange-state").hexdigest(),
        provider="google",
        callback_uri=NATIVE_CALLBACK,
        redirect_uri=APP_REDIRECT,
        app_state_sealed=native_authorization._seal("state"),
        code_challenge=_challenge("V" * 43),
        nonce_digest="N" * 64,
        nonce_sealed=native_authorization._seal("nonce"),
        pkce_verifier_sealed=native_authorization._seal("V" * 43),
        status=NativeTransactionStatus.COMPLETED,
        terminal_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    raw_code = "native-postgres-exchange-code"
    NativeExchangeCode.objects.create(
        transaction=transaction_row,
        code_digest=native_authorization._digest(raw_code),
        code_sealed=native_authorization._seal(raw_code),
        user=user,
        redirect_uri=APP_REDIRECT,
        code_challenge=_challenge("V" * 43),
        expires_at=now + timedelta(minutes=1),
    )
    barrier = threading.Barrier(2)

    def exchange_once():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                issued = exchange_native_code(
                    code=raw_code,
                    code_verifier="V" * 43,
                    redirect_uri=APP_REDIRECT,
                )
            except NativeExchangeReplay:
                return "replayed", None
            return "issued", issued.family.pk
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=15)
            for future in [
                pool.submit(exchange_once),
                pool.submit(exchange_once),
            ]
        ]

    assert sorted(result[0] for result in results) == ["issued", "replayed"]
    assert (
        NativeExchangeCode.objects.filter(
            transaction=transaction_row, consumed_at__isnull=False
        ).count()
        == 1
    )
    assert user.native_exchange_codes.count() == 1


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
@override_settings(
    ALLIES_AUTH_NATIVE_ENABLED=True,
    ALLIES_AUTH_GOOGLE_ENABLED=True,
    ALLIES_AUTH_GOOGLE_NATIVE_REDIRECT_URI=NATIVE_CALLBACK,
    ALLIES_AUTH_GOOGLE_REDIRECT_URI="https://cloud.example/api/v1/auths/callback/google",
    ALLIES_AUTH_NATIVE_REDIRECT_URIS=[APP_REDIRECT],
    ALLIES_AUTH_JWT_KEY="native-postgres-callback-jwt-at-least-thirty-two-bytes",
    ALLIES_AUTH_DIGEST_KEY="native-postgres-callback-digest-at-least-thirty-two-bytes",
)
def test_native_callback_claim_allows_one_provider_attempt(monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("native callback race requires PostgreSQL")

    started = threading.Event()
    release = threading.Event()

    class BlockingProvider:
        key = ProviderKey.GOOGLE
        callback_calls = 0

        def authorization_url(self, flow: ProviderFlow) -> str:
            return "https://provider.example/authorize?" + urlencode(
                {"state": flow.state}
            )

        def verify_callback(self, code: str, flow: ProviderFlow):
            self.callback_calls += 1
            started.set()
            assert release.wait(timeout=10)
            return VerifiedIdentity(
                provider="google",
                subject="native-pg-callback",
                issuer="https://accounts.google.com",
            )

    provider = BlockingProvider()
    monkeypatch.setattr(native_authorization, "get_provider", lambda _: provider)
    start = begin_native_sign_in(
        provider=ProviderKey.GOOGLE,
        redirect_uri=APP_REDIRECT,
        code_challenge=_challenge("V" * 43),
        state="callback-state",
    )
    provider_state = parse_qs(urlparse(start.authorization_url).query)["state"][0]

    def callback_once():
        close_old_connections()
        try:
            try:
                result = complete_native_callback(
                    provider=ProviderKey.GOOGLE,
                    provider_state=provider_state,
                    provider_code="provider-code",
                )
            except NativeCallbackInProgress:
                return "in_progress", None
            return "completed", result.location
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(callback_once)
        assert started.wait(timeout=10)
        second = pool.submit(callback_once)
        second_result = second.result(timeout=10)
        release.set()
        first_result = first.result(timeout=15)

    assert second_result[0] == "in_progress"
    assert first_result[0] == "completed"
    assert provider.callback_calls == 1
    assert (
        NativeAuthorizationTransaction.objects.filter(
            status=NativeTransactionStatus.COMPLETED
        ).count()
        == 1
    )
    assert NativeExchangeCode.objects.count() == 1


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
@override_settings(
    ALLIES_AUTH_NATIVE_ENABLED=True,
    ALLIES_AUTH_GOOGLE_ENABLED=True,
    ALLIES_AUTH_GOOGLE_NATIVE_REDIRECT_URI=NATIVE_CALLBACK,
    ALLIES_AUTH_GOOGLE_REDIRECT_URI="https://cloud.example/api/v1/auths/callback/google",
    ALLIES_AUTH_NATIVE_REDIRECT_URIS=[APP_REDIRECT],
    ALLIES_AUTH_JWT_KEY="native-postgres-cleanup-jwt-key-at-least-thirty-two-bytes",
    ALLIES_AUTH_DIGEST_KEY="native-postgres-cleanup-digest-at-least-thirty-two-bytes",
)
def test_native_callback_claim_vs_cleanup_delete_is_safe(monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("native callback cleanup race requires PostgreSQL")

    now = timezone.now()
    provider_state = "native-cleanup-race-state"
    transaction_row = NativeAuthorizationTransaction.objects.create(
        state_digest=native_authorization._digest(provider_state),
        provider="google",
        callback_uri=NATIVE_CALLBACK,
        redirect_uri=APP_REDIRECT,
        app_state_sealed=native_authorization._seal("state"),
        code_challenge=_challenge("V" * 43),
        nonce_digest="N" * 64,
        nonce_sealed=native_authorization._seal("nonce"),
        pkce_verifier_sealed=native_authorization._seal("V" * 43),
        status=NativeTransactionStatus.PENDING,
        expires_at=now - timedelta(seconds=1),
    )
    initial_read = threading.Event()
    release_callback = threading.Event()
    original_get = NativeAuthorizationTransaction.objects.get

    def pause_after_initial_read(*args, **kwargs):
        row = original_get(*args, **kwargs)
        if not initial_read.is_set():
            initial_read.set()
            assert release_callback.wait(timeout=10)
        return row

    monkeypatch.setattr(
        NativeAuthorizationTransaction.objects,
        "get",
        pause_after_initial_read,
    )

    def callback_once():
        close_old_connections()
        try:
            with pytest.raises(InvalidFlow, match="native state is invalid"):
                complete_native_callback(
                    provider=ProviderKey.GOOGLE,
                    provider_state=provider_state,
                    provider_code="provider-code",
                )
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        callback_future = pool.submit(callback_once)
        assert initial_read.wait(timeout=10)
        cleanup_result = pool.submit(cleanup_auth_artifacts).result(timeout=10)
        release_callback.set()
        callback_future.result(timeout=15)

    assert cleanup_result.flows == 1
    assert not NativeAuthorizationTransaction.objects.filter(
        pk=transaction_row.pk
    ).exists()
