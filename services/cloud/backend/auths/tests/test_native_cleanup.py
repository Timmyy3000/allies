import hashlib
import uuid
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from auths.models import (
    NativeAuthorizationTransaction,
    NativeExchangeCode,
    NativeTransactionStatus,
    User,
)
from auths.services import native_authorization
from auths.services.cleanup import cleanup_auth_artifacts


@pytest.fixture(autouse=True)
def native_cleanup_settings(settings):
    settings.ALLIES_AUTH_NATIVE_ENABLED = True
    settings.ALLIES_AUTH_GOOGLE_NATIVE_REDIRECT_URI = (
        "https://cloud.example/api/v1/auths/native/callback/google"
    )
    settings.ALLIES_AUTH_GOOGLE_REDIRECT_URI = (
        "https://cloud.example/api/v1/auths/callback/google"
    )
    settings.ALLIES_AUTH_NATIVE_REDIRECT_URIS = ["allies://auth/callback"]
    settings.ALLIES_AUTH_DIGEST_KEY = (
        "native-cleanup-digest-key-at-least-thirty-two-bytes"
    )
    cache.clear()
    yield
    cache.clear()


def _transaction(*, status, now, expires_at, terminal_at=None, claim_expires_at=None):
    claimed_at = now - timedelta(seconds=10) if claim_expires_at else None
    return NativeAuthorizationTransaction.objects.create(
        state_digest=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        provider="google",
        callback_uri="https://cloud.example/api/v1/auths/native/callback/google",
        redirect_uri="allies://auth/callback",
        app_state_sealed=native_authorization._seal("app-state"),
        code_challenge="A" * 43,
        nonce_digest="N" * 64,
        nonce_sealed=native_authorization._seal("nonce"),
        pkce_verifier_sealed=native_authorization._seal("V" * 43),
        status=status,
        claim_digest="C" * 64 if claim_expires_at else "",
        claimed_at=claimed_at,
        claim_expires_at=claim_expires_at,
        terminal_at=terminal_at,
        expires_at=expires_at,
    )


@pytest.mark.django_db
def test_cleanup_marks_stale_claim_failed_but_keeps_active_claim():
    now = timezone.now()
    stale = _transaction(
        status=NativeTransactionStatus.CLAIMED,
        now=now,
        expires_at=now - timedelta(minutes=1),
        claim_expires_at=now - timedelta(seconds=1),
    )
    active = _transaction(
        status=NativeTransactionStatus.CLAIMED,
        now=now,
        expires_at=now - timedelta(minutes=1),
        claim_expires_at=now + timedelta(seconds=10),
    )

    result = cleanup_auth_artifacts(batch_size=100)

    stale.refresh_from_db()
    active.refresh_from_db()
    assert stale.status == NativeTransactionStatus.FAILED
    assert stale.error_code == "provider_unavailable"
    assert stale.terminal_at is not None
    assert active.status == NativeTransactionStatus.CLAIMED
    assert result.flows == 0


@pytest.mark.django_db
def test_cleanup_deletes_expired_pending_and_protects_live_terminal_exchange():
    now = timezone.now()
    pending = _transaction(
        status=NativeTransactionStatus.PENDING,
        now=now,
        expires_at=now - timedelta(seconds=1),
    )
    user = User.objects.create_user()
    terminal_at = now - timedelta(days=2)
    completed = _transaction(
        status=NativeTransactionStatus.COMPLETED,
        now=now,
        expires_at=now - timedelta(days=2),
        terminal_at=terminal_at,
    )
    code = NativeExchangeCode.objects.create(
        transaction=completed,
        code_digest=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        code_sealed=native_authorization._seal("cloud-code"),
        user=user,
        redirect_uri="allies://auth/callback",
        code_challenge="A" * 43,
        expires_at=now + timedelta(seconds=30),
    )

    first = cleanup_auth_artifacts(batch_size=100)
    assert first.flows == 1
    assert not NativeAuthorizationTransaction.objects.filter(pk=pending.pk).exists()
    assert NativeAuthorizationTransaction.objects.filter(pk=completed.pk).exists()
    assert NativeExchangeCode.objects.filter(pk=code.pk).exists()

    NativeExchangeCode.objects.filter(pk=code.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    second = cleanup_auth_artifacts(batch_size=100)
    assert second.flows == 1
    assert not NativeExchangeCode.objects.filter(pk=code.pk).exists()
    assert not NativeAuthorizationTransaction.objects.filter(pk=completed.pk).exists()
