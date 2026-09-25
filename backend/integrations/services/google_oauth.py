"""Allies-owned Google OAuth for Gmail: connect, refresh, revoke.

The driving Cloud owns the full refresh lifecycle. Foundry and Hermes only
ever see short-lived access tokens minted per execution. Refresh secrets at
rest live exclusively in ``IntegrationSecret.ciphertext``.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.db import transaction
from django.utils import timezone

from ..exceptions import (
    IntegrationConflict,
    IntegrationInvalid,
    IntegrationUnavailable,
    ProviderUnavailable,
    RefreshRevoked,
    ScopeInsufficient,
)
from ..models import PROVIDER_GMAIL, GmailConnectSession, IntegrationSecret
from .vault import seal_refresh_token, unseal_refresh_token

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_V1_SCOPES = (GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE)

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
GMAIL_PROFILE_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/profile"

CONNECT_SESSION_TTL_SECONDS = 10 * 60
PROVIDER_TIMEOUT_SECONDS = 10
PROVIDER_MAX_ATTEMPTS = 2


def _setting(name: str, default: str = "") -> str:
    from django.conf import settings

    return str(getattr(settings, name, "") or default)


def gmail_enabled() -> bool:
    from django.conf import settings

    return bool(getattr(settings, "ALLIES_GMAIL_ENABLED", True))


def _client_id() -> str:
    return _setting("ALLIES_GMAIL_CLIENT_ID")


def _client_secret() -> str:
    return _setting("ALLIES_GMAIL_CLIENT_SECRET", "")


def _redirect_uri() -> str:
    return _setting("ALLIES_GMAIL_REDIRECT_URI")


def _post_form(url: str, fields: dict[str, str]) -> dict:
    body = urlencode(fields).encode()
    last_error: Exception | None = None
    for _ in range(PROVIDER_MAX_ATTEMPTS):
        request = Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=PROVIDER_TIMEOUT_SECONDS) as response:
                raw = response.read(1_000_001)
            break
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            time.sleep(0.2)
    else:
        raise ProviderUnavailable("google provider unavailable") from last_error
    try:
        payload = json.loads(raw.decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProviderUnavailable("google provider response invalid") from exc
    if not isinstance(payload, dict):
        raise ProviderUnavailable("google provider response invalid")
    return payload


def _google_error(payload: dict) -> str:
    error = payload.get("error")
    if isinstance(error, str) and len(error) <= 64:
        return error
    return ""


def _handshake_grant_level(sealed_handshake: str) -> str | None:
    from .vault import VAULT_KEY_CURRENT_VERSION, unseal_refresh_token

    try:
        handshake = json.loads(
            unseal_refresh_token(
                sealed_handshake.encode(),
                key_version=VAULT_KEY_CURRENT_VERSION,
            )
        )
    except (ValueError, IntegrationUnavailable):
        return None
    level = handshake.get("grant_level") if isinstance(handshake, dict) else None
    return level if level in {"read", "send"} else None


@dataclass(frozen=True)
class GmailConnectBegin:
    connect_session_id: str
    auth_url: str
    expires_at: object


def begin_gmail_connect(
    *,
    workspace,
    entry_point: str,
    ally=None,
    grant_level: str | None = None,
    idempotency_key: str,
) -> GmailConnectBegin:
    if not gmail_enabled():
        raise IntegrationUnavailable("gmail integration disabled")
    if entry_point not in {"integrations", "in_chat"}:
        raise IntegrationInvalid("unknown connect entry point")
    if entry_point == "in_chat" and ally is None:
        raise IntegrationInvalid("in-chat connect requires an ally")
    if entry_point == "in_chat" and grant_level not in {"read", "send"}:
        raise IntegrationInvalid("in-chat connect requires an explicit grant level")
    if entry_point == "integrations" and grant_level is not None:
        raise IntegrationInvalid("grant level is only valid for in-chat connect")
    if not idempotency_key or len(idempotency_key) > 128:
        raise IntegrationInvalid("idempotency key invalid")
    client_id = _client_id()
    redirect_uri = _redirect_uri()
    if not client_id or not redirect_uri:
        raise IntegrationUnavailable("gmail oauth client incomplete")
    existing = (
        GmailConnectSession.objects.filter(
            workspace=workspace, idempotency_key=idempotency_key, consumed_at=None
        )
        .order_by("-created_at")
        .first()
    )
    now = timezone.now()
    state = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    if existing is not None and existing.expires_at > now:
        existing.state_hash = state_hash
        existing.expires_at = now + timedelta(seconds=CONNECT_SESSION_TTL_SECONDS)
        existing.save(update_fields=["state_hash", "expires_at"])
        return GmailConnectBegin(
            connect_session_id=str(existing.id),
            auth_url=_authorization_url(client_id, redirect_uri, state),
            expires_at=existing.expires_at,
        )
    verifier = secrets.token_urlsafe(64)
    handshake = json.dumps(
        {
            "state": state,
            "pkce_verifier": verifier,
            "workspace_id": str(workspace.id),
            "ally_id": str(ally.id) if ally is not None else None,
            "grant_level": grant_level,
            "entry_point": entry_point,
        }
    )
    ciphertext, _ = seal_refresh_token(handshake)
    session = GmailConnectSession.objects.create(
        workspace=workspace,
        state_hash=state_hash,
        sealed_handshake=ciphertext.decode(),
        entry_point=entry_point,
        ally=ally,
        idempotency_key=idempotency_key,
        expires_at=now + timedelta(seconds=CONNECT_SESSION_TTL_SECONDS),
    )
    return GmailConnectBegin(
        connect_session_id=str(session.id),
        auth_url=_authorization_url(client_id, redirect_uri, state),
        expires_at=session.expires_at,
    )


def _authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    return (
        GOOGLE_AUTHORIZATION_ENDPOINT
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "scope": " ".join(GMAIL_V1_SCOPES),
                "redirect_uri": redirect_uri,
                "state": state,
                "access_type": "offline",
                "prompt": "consent",
            }
        )
    )


@dataclass(frozen=True)
class GmailConnectComplete:
    secret: IntegrationSecret
    auto_grant_ally_id: str | None
    auto_grant_level: str | None
    status: str


@transaction.atomic
def complete_gmail_connect(*, state: str, code: str) -> GmailConnectComplete:
    if not gmail_enabled():
        raise IntegrationUnavailable("gmail integration disabled")
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    try:
        session = GmailConnectSession.objects.select_for_update().get(
            state_hash=state_hash
        )
    except GmailConnectSession.DoesNotExist as exc:
        raise IntegrationInvalid("unknown connect session") from exc
    now = timezone.now()
    if session.consumed_at is not None or session.expires_at <= now:
        raise IntegrationInvalid("connect session expired")
    token = _post_form(
        _setting("ALLIES_GMAIL_TOKEN_ENDPOINT", GOOGLE_TOKEN_ENDPOINT),
        {
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _redirect_uri(),
        },
    )
    if _google_error(token):
        raise IntegrationInvalid("google rejected the connect code")
    granted = token.get("scope", "")
    granted_scopes = set(granted.split()) if isinstance(granted, str) else set()
    if not set(GMAIL_V1_SCOPES) <= granted_scopes:
        raise ScopeInsufficient("gmail needs read and send scopes")
    refresh_token = token.get("refresh_token")
    access_token = token.get("access_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise IntegrationInvalid("google did not return a refresh token")
    if not isinstance(access_token, str) or not access_token:
        raise IntegrationInvalid("google did not return an access token")
    account_sub = _google_account_sub(access_token)
    account_ref_hash = hashlib.sha256(account_sub.encode()).hexdigest()
    account_email = _gmail_profile_email(access_token)
    ciphertext, key_version = seal_refresh_token(refresh_token)
    conflict = (
        IntegrationSecret.objects.filter(
            workspace=session.workspace, provider_key=PROVIDER_GMAIL
        )
        .exclude(account_ref_hash=account_ref_hash)
        .first()
    )
    if conflict is not None:
        raise IntegrationConflict("a different gmail account is connected")
    secret, created = IntegrationSecret.objects.update_or_create(
        workspace=session.workspace,
        provider_key=PROVIDER_GMAIL,
        account_ref_hash=account_ref_hash,
        defaults={
            "ciphertext": bytes(ciphertext),
            "key_version": key_version,
            "scope_set": sorted(granted_scopes),
            "account_email": account_email,
            "revoked_at": None,
        },
    )
    session.consumed_at = now
    session.save(update_fields=["consumed_at"])
    auto_grant_ally_id = str(session.ally_id) if session.ally_id else None
    auto_grant_level = _handshake_grant_level(session.sealed_handshake)
    return GmailConnectComplete(
        secret=secret,
        auto_grant_ally_id=auto_grant_ally_id,
        auto_grant_level=auto_grant_level,
        status="connected" if created else "already_connected",
    )


def _google_account_sub(access_token: str) -> str:
    request = Request(
        GOOGLE_USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"}
    )
    try:
        with urlopen(request, timeout=PROVIDER_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read(100_001).decode())
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise ProviderUnavailable("google account lookup failed") from exc
    sub = payload.get("sub") if isinstance(payload, dict) else None
    if not isinstance(sub, str) or not sub:
        raise ProviderUnavailable("google account lookup failed")
    return sub


def _gmail_profile_email(access_token: str) -> str:
    request = Request(
        GMAIL_PROFILE_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"}
    )
    try:
        with urlopen(request, timeout=PROVIDER_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read(100_001).decode())
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise ProviderUnavailable("gmail profile lookup failed") from exc
    email = payload.get("emailAddress") if isinstance(payload, dict) else None
    if not isinstance(email, str) or not email or len(email) > 254:
        raise ProviderUnavailable("gmail profile lookup failed")
    return email


@dataclass(frozen=True)
class MintedAccess:
    access_token: str
    expires_at: object
    scope_set: list[str]


def refresh_access_token(secret: IntegrationSecret) -> MintedAccess:
    if secret.revoked_at is not None:
        raise RefreshRevoked("gmail connection revoked")
    refresh_token = unseal_refresh_token(
        secret.ciphertext, key_version=secret.key_version
    )
    token = _post_form(
        _setting("ALLIES_GMAIL_TOKEN_ENDPOINT", GOOGLE_TOKEN_ENDPOINT),
        {
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    error = _google_error(token)
    if error in {"invalid_grant", "unauthorized_client"}:
        raise RefreshRevoked("google refresh rejected")
    if error:
        raise ProviderUnavailable("google refresh failed")
    access_token = token.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ProviderUnavailable("google refresh failed")
    expires_in = token.get("expires_in", 3600)
    try:
        ttl = max(60, min(int(expires_in), 3600))
    except (TypeError, ValueError):
        ttl = 3600
    return MintedAccess(
        access_token=access_token,
        expires_at=timezone.now() + timedelta(seconds=ttl),
        scope_set=list(secret.scope_set or []),
    )


def revoke_at_google(refresh_token: str) -> bool:
    try:
        _post_form(
            _setting("ALLIES_GMAIL_REVOKE_ENDPOINT", GOOGLE_REVOKE_ENDPOINT),
            {"token": refresh_token},
        )
    except ProviderUnavailable:
        return False
    return True
