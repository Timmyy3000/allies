"""Native authorization transaction and provider callback workflows."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode, urlparse, urlsplit, urlunsplit

from django.db import DatabaseError, transaction
from django.utils import timezone

from auths.audit import emit_auth_event
from auths.config import (
    digest_key,
    native_app_redirect_uris,
    native_claim_lease_seconds,
    native_enabled,
    native_exchange_ttl_seconds,
    native_google_redirect_uri,
    native_provider_timeout_seconds,
    native_terminal_retention_seconds,
    native_transaction_ttl_seconds,
    setting,
)
from auths.exceptions import (
    AuthDomainError,
    InvalidFlow,
    InvalidRedirect,
    NativeCallbackInProgress,
    NativeConfigurationInvalid,
    NativeUnavailable,
    ProviderRejected,
    ProviderUnavailable,
)
from auths.models import (
    NativeAuthorizationTransaction,
    NativeExchangeCode,
    NativeTransactionStatus,
)
from auths.providers.base import ProviderFlow, ProviderKey, get_provider
from auths.services.accounts import resolve_or_create_user

_PKCE_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_STATE_RE = re.compile(r"^[\x21-\x7e]{1,512}$")
_NATIVE_CALLBACK_PATH = "/api/v1/auths/native/callback/google"


@dataclass(frozen=True)
class NativeAuthorizationStart:
    provider: ProviderKey
    authorization_url: str
    expires_at: object


@dataclass(frozen=True)
class NativeAppRedirect:
    location: str


def _digest(raw: str | bytes) -> str:
    value = raw.encode() if isinstance(raw, str) else raw
    return hmac.new(digest_key(), value, hashlib.sha256).hexdigest()


def _seal(value: str) -> str:
    try:
        from cryptography.fernet import Fernet

        key = base64.urlsafe_b64encode(hashlib.sha256(digest_key()).digest())
        return Fernet(key).encrypt(value.encode()).decode()
    except Exception as exc:
        raise NativeConfigurationInvalid("native flow protection unavailable") from exc


def _unseal(value: str, *, max_age: int) -> str:
    try:
        from cryptography.fernet import Fernet

        key = base64.urlsafe_b64encode(hashlib.sha256(digest_key()).digest())
        return Fernet(key).decrypt(value.encode(), ttl=max_age).decode()
    except Exception as exc:
        raise NativeConfigurationInvalid("native flow protection unavailable") from exc


def _provider_key(provider: ProviderKey | str) -> ProviderKey:
    try:
        key = ProviderKey(str(provider))
    except ValueError as exc:
        raise ProviderUnavailable("native provider is unavailable") from exc
    if key is not ProviderKey.GOOGLE:
        raise ProviderUnavailable("native provider is unavailable")
    return key


def _validate_state(state: str) -> str:
    if not isinstance(state, str) or not _STATE_RE.fullmatch(state):
        raise InvalidFlow("native state is invalid")
    return state


def _validate_code_challenge(code_challenge: str) -> str:
    if not isinstance(code_challenge, str) or not _PKCE_CHALLENGE_RE.fullmatch(
        code_challenge
    ):
        raise InvalidFlow("pkce challenge is invalid")
    return code_challenge


def _validate_app_redirect(redirect_uri: str) -> str:
    if (
        not isinstance(redirect_uri, str)
        or len(redirect_uri) > 500
        or any(ord(char) < 32 for char in redirect_uri)
        or "\\" in redirect_uri
    ):
        raise InvalidRedirect("redirect is invalid")
    parsed = urlparse(redirect_uri)
    if (
        not parsed.scheme
        or parsed.username
        or parsed.password
        or parsed.params
        or parsed.query
        or parsed.fragment
        or "*" in redirect_uri
        or parsed.scheme.lower() in {"about", "data", "file", "http", "javascript"}
    ):
        raise InvalidRedirect("redirect is invalid")
    if parsed.scheme == "https" and not parsed.netloc:
        raise InvalidRedirect("redirect is invalid")
    if not any(
        hmac.compare_digest(redirect_uri, configured)
        for configured in native_app_redirect_uris()
    ):
        raise InvalidRedirect("redirect is not registered")
    return redirect_uri


def _native_callback_uri() -> str:
    value = native_google_redirect_uri()
    parsed = urlparse(value)
    if (
        not value
        or parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.path != _NATIVE_CALLBACK_PATH
    ):
        raise NativeConfigurationInvalid("native Google callback is unavailable")
    browser_uri = str(setting("ALLIES_AUTH_GOOGLE_REDIRECT_URI", ""))
    if value == browser_uri:
        raise NativeConfigurationInvalid("native and browser callbacks must differ")
    return value


def _append_query(base: str, values: dict[str, str]) -> str:
    parsed = urlsplit(base)
    if parsed.query or parsed.fragment:
        raise InvalidRedirect("redirect is invalid")
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(values), "")
    )


def _app_state(transaction_row: NativeAuthorizationTransaction) -> str:
    return _unseal(
        transaction_row.app_state_sealed,
        max_age=native_transaction_ttl_seconds() + native_terminal_retention_seconds(),
    )


def _failure_redirect(
    transaction_row: NativeAuthorizationTransaction, error_code: str
) -> NativeAppRedirect:
    return NativeAppRedirect(
        _append_query(
            transaction_row.redirect_uri,
            {"error": error_code, "state": _app_state(transaction_row)},
        )
    )


def _success_redirect(
    transaction_row: NativeAuthorizationTransaction, code: str
) -> NativeAppRedirect:
    return NativeAppRedirect(
        _append_query(
            transaction_row.redirect_uri,
            {"code": code, "state": _app_state(transaction_row)},
        )
    )


def _terminal_redirect(
    transaction_row: NativeAuthorizationTransaction,
) -> NativeAppRedirect:
    if transaction_row.status == NativeTransactionStatus.COMPLETED:
        exchange = NativeExchangeCode.objects.filter(
            transaction=transaction_row
        ).first()
        now = timezone.now()
        if exchange and exchange.consumed_at is None and exchange.expires_at > now:
            return _success_redirect(
                transaction_row,
                _unseal(
                    exchange.code_sealed,
                    max_age=native_exchange_ttl_seconds() + 60,
                ),
            )
        return _failure_redirect(transaction_row, "exchange_invalid")
    if transaction_row.status == NativeTransactionStatus.DENIED:
        return _failure_redirect(transaction_row, "access_denied")
    return _failure_redirect(
        transaction_row, transaction_row.error_code or "flow_failed"
    )


def _mark_failed(
    transaction_id: int,
    *,
    claim_digest: str | None,
    error_code: str = "provider_unavailable",
) -> NativeAppRedirect | None:
    with transaction.atomic():
        locked = NativeAuthorizationTransaction.objects.select_for_update().get(
            pk=transaction_id
        )
        if locked.status != NativeTransactionStatus.CLAIMED:
            return _terminal_redirect(locked)
        if claim_digest and not hmac.compare_digest(locked.claim_digest, claim_digest):
            return _terminal_redirect(locked)
        now = timezone.now()
        locked.status = NativeTransactionStatus.FAILED
        locked.error_code = error_code[:64]
        locked.terminal_at = now
        locked.save(update_fields=("status", "error_code", "terminal_at"))
        return _failure_redirect(locked, error_code)


def begin_native_sign_in(
    *, provider: ProviderKey | str, redirect_uri: str, code_challenge: str, state: str
) -> NativeAuthorizationStart:
    if not native_enabled():
        raise NativeUnavailable("native authentication is disabled")
    provider_key = _provider_key(provider)
    redirect = _validate_app_redirect(redirect_uri)
    challenge = _validate_code_challenge(code_challenge)
    app_state = _validate_state(state)
    callback_uri = _native_callback_uri()
    adapter = get_provider(provider_key)
    provider_state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(24)
    provider_verifier = secrets.token_urlsafe(32)
    authorization_url = adapter.authorization_url(
        ProviderFlow(
            provider=provider_key,
            state=provider_state,
            nonce=nonce,
            redirect_uri=callback_uri,
            pkce_verifier=provider_verifier,
        )
    )
    now = timezone.now()
    expires_at = now + timedelta(seconds=native_transaction_ttl_seconds())
    NativeAuthorizationTransaction.objects.create(
        state_digest=_digest(provider_state),
        provider=provider_key.value,
        callback_uri=callback_uri,
        redirect_uri=redirect,
        app_state_sealed=_seal(app_state),
        code_challenge=challenge,
        nonce_digest=_digest(nonce),
        nonce_sealed=_seal(nonce),
        pkce_verifier_sealed=_seal(provider_verifier),
        status=NativeTransactionStatus.PENDING,
        expires_at=expires_at,
    )
    emit_auth_event(
        "auth.native.flow.started", outcome="accepted", provider=provider_key.value
    )
    return NativeAuthorizationStart(provider_key, authorization_url, expires_at)


def _claim_transaction(
    provider_key: ProviderKey, provider_state: str
) -> tuple[NativeAuthorizationTransaction, str | None, NativeAppRedirect | None]:
    try:
        transaction_row = NativeAuthorizationTransaction.objects.get(
            state_digest=_digest(provider_state)
        )
    except NativeAuthorizationTransaction.DoesNotExist as exc:
        raise InvalidFlow("native state is invalid") from exc
    now = timezone.now()
    with transaction.atomic():
        try:
            locked = NativeAuthorizationTransaction.objects.select_for_update().get(
                pk=transaction_row.pk
            )
        except NativeAuthorizationTransaction.DoesNotExist as exc:
            raise InvalidFlow("native state is invalid") from exc
        if locked.provider != provider_key.value:
            raise InvalidFlow("provider mismatch")
        if locked.status == NativeTransactionStatus.PENDING:
            if locked.expires_at <= now:
                locked.status = NativeTransactionStatus.FAILED
                locked.error_code = "flow_expired"
                locked.terminal_at = now
                locked.save(update_fields=("status", "error_code", "terminal_at"))
                return locked, None, _failure_redirect(locked, "flow_expired")
            claim = secrets.token_urlsafe(32)
            locked.status = NativeTransactionStatus.CLAIMED
            locked.claim_digest = _digest(claim)
            locked.claimed_at = now
            locked.claim_expires_at = now + timedelta(
                seconds=native_claim_lease_seconds()
            )
            locked.save(
                update_fields=(
                    "status",
                    "claim_digest",
                    "claimed_at",
                    "claim_expires_at",
                )
            )
            return locked, claim, None
        if locked.status == NativeTransactionStatus.CLAIMED:
            if locked.claim_expires_at and locked.claim_expires_at > now:
                raise NativeCallbackInProgress("native callback is in progress")
            locked.status = NativeTransactionStatus.FAILED
            locked.error_code = "provider_unavailable"
            locked.terminal_at = now
            locked.save(update_fields=("status", "error_code", "terminal_at"))
        return locked, None, _terminal_redirect(locked)


def _finalize_provider_result(
    transaction_id: int,
    *,
    claim_digest: str,
    identity,
) -> NativeAppRedirect:
    with transaction.atomic():
        locked = NativeAuthorizationTransaction.objects.select_for_update().get(
            pk=transaction_id
        )
        if locked.status != NativeTransactionStatus.CLAIMED or not hmac.compare_digest(
            locked.claim_digest, claim_digest
        ):
            return _terminal_redirect(locked)
        now = timezone.now()
        if locked.claim_expires_at is None or locked.claim_expires_at <= now:
            locked.status = NativeTransactionStatus.FAILED
            locked.error_code = "provider_unavailable"
            locked.terminal_at = now
            locked.save(update_fields=("status", "error_code", "terminal_at"))
            return _failure_redirect(locked, "provider_unavailable")
        bootstrap = resolve_or_create_user(identity)
        raw_code = secrets.token_urlsafe(32)
        NativeExchangeCode.objects.create(
            transaction=locked,
            code_digest=_digest(raw_code),
            code_sealed=_seal(raw_code),
            user=bootstrap.user,
            redirect_uri=locked.redirect_uri,
            code_challenge=locked.code_challenge,
            expires_at=now + timedelta(seconds=native_exchange_ttl_seconds()),
        )
        locked.status = NativeTransactionStatus.COMPLETED
        locked.terminal_at = now
        locked.error_code = ""
        locked.save(update_fields=("status", "terminal_at", "error_code"))
        emit_auth_event(
            "auth.native.flow.completed",
            outcome="accepted",
            provider=locked.provider,
            user_ref=bootstrap.user.public_id,
        )
        return _success_redirect(locked, raw_code)


def complete_native_callback(
    *,
    provider: ProviderKey | str,
    provider_state: str,
    provider_code: str | None = None,
    provider_error: str | None = None,
) -> NativeAppRedirect:
    if not native_enabled():
        raise NativeUnavailable("native authentication is disabled")
    provider_key = _provider_key(provider)
    state = _validate_state(provider_state)
    transaction_row, claim, terminal = _claim_transaction(provider_key, state)
    if terminal is not None:
        return terminal
    if claim is None:
        return _terminal_redirect(transaction_row)
    if provider_error:
        error_code = (
            "access_denied"
            if provider_error in {"access_denied", "cancelled", "user_cancelled"}
            else "provider_unavailable"
        )
        with transaction.atomic():
            locked = NativeAuthorizationTransaction.objects.select_for_update().get(
                pk=transaction_row.pk
            )
            if (
                locked.status != NativeTransactionStatus.CLAIMED
                or not hmac.compare_digest(locked.claim_digest, _digest(claim))
            ):
                return _terminal_redirect(locked)
            locked.status = (
                NativeTransactionStatus.DENIED
                if error_code == "access_denied"
                else NativeTransactionStatus.FAILED
            )
            locked.error_code = "" if error_code == "access_denied" else error_code
            locked.terminal_at = timezone.now()
            locked.save(update_fields=("status", "error_code", "terminal_at"))
            emit_auth_event(
                "auth.native.flow.rejected",
                outcome="denied" if error_code == "access_denied" else "rejected",
                reason_code=error_code,
                provider=provider_key.value,
            )
            return _failure_redirect(locked, error_code)
    if (
        not isinstance(provider_code, str)
        or not provider_code
        or len(provider_code) > 4096
    ):
        failed = _mark_failed(
            transaction_row.pk,
            claim_digest=_digest(claim),
            error_code="flow_failed",
        )
        if failed is not None:
            return failed
        raise ProviderRejected("provider code malformed")
    try:
        nonce = _unseal(
            transaction_row.nonce_sealed,
            max_age=native_transaction_ttl_seconds() + native_claim_lease_seconds(),
        )
        provider_verifier = _unseal(
            transaction_row.pkce_verifier_sealed,
            max_age=native_transaction_ttl_seconds() + native_claim_lease_seconds(),
        )
        adapter = get_provider(provider_key)
        deadline = time.monotonic() + native_provider_timeout_seconds()
        identity = adapter.verify_callback(
            provider_code,
            ProviderFlow(
                provider=provider_key,
                state=state,
                nonce=nonce,
                redirect_uri=transaction_row.callback_uri,
                pkce_verifier=provider_verifier,
                deadline_monotonic=deadline,
            ),
        )
        if time.monotonic() >= deadline:
            raise ProviderRejected("provider attempt timed out")
        if identity.provider != provider_key.value:
            raise ProviderRejected("provider response mismatch")
    except (AuthDomainError, AttributeError, TypeError, ValueError):
        failed = _mark_failed(
            transaction_row.pk,
            claim_digest=_digest(claim),
            error_code="provider_unavailable",
        )
        if failed is not None:
            emit_auth_event(
                "auth.native.flow.rejected",
                outcome="rejected",
                reason_code="provider_unavailable",
                provider=provider_key.value,
            )
            return failed
        raise NativeUnavailable("native provider unavailable") from None
    try:
        return _finalize_provider_result(
            transaction_row.pk, claim_digest=_digest(claim), identity=identity
        )
    except (AuthDomainError, DatabaseError, ValueError):
        failed = _mark_failed(
            transaction_row.pk,
            claim_digest=_digest(claim),
            error_code="flow_failed",
        )
        if failed is not None:
            return failed
        raise NativeUnavailable("native flow failed") from None
