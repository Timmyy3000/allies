"""PKCE exchange and native bearer-session workflows."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re

from django.db import transaction
from django.utils import timezone

from auths.audit import emit_auth_event
from auths.config import digest_key
from auths.exceptions import (
    InvalidRedirect,
    NativeExchangeInvalid,
    NativeExchangeReplay,
    SessionInvalid,
)
from auths.models import (
    NativeExchangeCode,
    RefreshToken,
    SessionClientKind,
    SessionFamily,
)
from auths.services.native_authorization import _validate_app_redirect
from auths.services.sessions import (
    AuthenticatedSession,
    IssuedSession,
    authenticate_access,
    issue_session,
    rotate_refresh,
)

_PKCE_VERIFIER_RE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")


def _digest(raw: str | bytes) -> str:
    value = raw.encode() if isinstance(raw, str) else raw
    return hmac.new(digest_key(), value, hashlib.sha256).hexdigest()


def _pkce_challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode("ascii")
    )


def _validate_code(code: str) -> str:
    if not isinstance(code, str) or not code or len(code) > 512:
        raise NativeExchangeInvalid("exchange code invalid")
    return code


def _validate_verifier(verifier: str) -> str:
    if not isinstance(verifier, str) or not _PKCE_VERIFIER_RE.fullmatch(verifier):
        raise NativeExchangeInvalid("code verifier invalid")
    return verifier


def _reject_exchange(
    reason_code: str,
    *,
    replay: bool = False,
    provider: str = "",
) -> None:
    emit_auth_event(
        "auth.native.exchange.rejected",
        outcome="rejected",
        reason_code=reason_code,
        provider=provider,
    )
    if replay:
        raise NativeExchangeReplay("exchange code already used")
    raise NativeExchangeInvalid(reason_code)


@transaction.atomic
def exchange_native_code(
    *, code: str, code_verifier: str, redirect_uri: str
) -> IssuedSession:
    try:
        raw_code = _validate_code(code)
    except NativeExchangeInvalid:
        _reject_exchange("code_invalid")
    try:
        verifier = _validate_verifier(code_verifier)
    except NativeExchangeInvalid:
        _reject_exchange("verifier_invalid")
    try:
        redirect = _validate_app_redirect(redirect_uri)
    except InvalidRedirect as exc:
        emit_auth_event(
            "auth.native.exchange.rejected",
            outcome="rejected",
            reason_code="redirect_invalid",
        )
        raise NativeExchangeInvalid("exchange redirect invalid") from exc
    try:
        exchange = (
            NativeExchangeCode.objects.select_for_update()
            .select_related("transaction", "user")
            .get(code_digest=_digest(raw_code))
        )
    except NativeExchangeCode.DoesNotExist:
        _reject_exchange("code_invalid")
    if exchange.consumed_at is not None:
        _reject_exchange(
            "code_replayed", replay=True, provider=str(exchange.transaction.provider)
        )
    now = timezone.now()
    if exchange.expires_at <= now:
        _reject_exchange("code_expired", provider=str(exchange.transaction.provider))
    if exchange.transaction.status != "completed":
        _reject_exchange(
            "transaction_invalid", provider=str(exchange.transaction.provider)
        )
    if not hmac.compare_digest(exchange.redirect_uri, redirect):
        _reject_exchange(
            "redirect_mismatch", provider=str(exchange.transaction.provider)
        )
    if not hmac.compare_digest(exchange.code_challenge, _pkce_challenge(verifier)):
        _reject_exchange(
            "verifier_mismatch", provider=str(exchange.transaction.provider)
        )
    exchange.consumed_at = now
    exchange.save(update_fields=("consumed_at",))
    issued = issue_session(
        exchange.user,
        client_kind=SessionClientKind.NATIVE,
    )
    emit_auth_event(
        "auth.native.exchange.completed",
        outcome="accepted",
        provider=exchange.transaction.provider,
        user_ref=str(exchange.user.id),
        family_ref=str(issued.family.id),
    )
    return issued


def refresh_native_session(raw_token: str) -> IssuedSession:
    issued = rotate_refresh(
        raw_token,
        expected_client_kind=SessionClientKind.NATIVE,
    )
    emit_auth_event(
        "auth.native.refresh.rotated",
        outcome="accepted",
        family_ref=str(issued.family.id),
    )
    return issued


@transaction.atomic
def logout_native_session(
    *, refresh_token: str, access_token: str | None = None
) -> AuthenticatedSession | None:
    if (
        not isinstance(refresh_token, str)
        or not refresh_token
        or len(refresh_token) > 512
    ):
        raise SessionInvalid("session invalid")
    access_session = None
    if access_token:
        try:
            access_session = authenticate_access(
                access_token, expected_client_kind=SessionClientKind.NATIVE
            )
        except SessionInvalid:
            # Logout remains usable after the short-lived access JWT expires.
            access_session = None
    try:
        refresh = RefreshToken.objects.select_related("family").get(
            token_digest=_digest(refresh_token)
        )
    except RefreshToken.DoesNotExist:
        if access_session is not None:
            raise SessionInvalid("session invalid")
        return None
    family = refresh.family
    if family.client_kind != SessionClientKind.NATIVE:
        raise SessionInvalid("session transport mismatch")
    if access_session is not None and access_session.family.pk != family.pk:
        raise SessionInvalid("session family mismatch")
    locked = SessionFamily.objects.select_for_update().get(pk=family.pk)
    if locked.revoked_at is None:
        locked.revoked_at = timezone.now()
        locked.revoke_reason = "logout"
        locked.save(update_fields=("revoked_at", "revoke_reason"))
    emit_auth_event(
        "auth.native.session.revoked",
        outcome="accepted",
        family_ref=str(locked.id),
    )
    return access_session
