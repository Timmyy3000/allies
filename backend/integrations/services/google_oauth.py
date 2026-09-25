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

GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_V1_SCOPES = (GMAIL_MODIFY_SCOPE, GMAIL_SEND_SCOPE)

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
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
        except HTTPError as exc:
            try:
                raw = exc.read(1_000_001)
                payload = json.loads(raw.decode())
            except (ValueError, UnicodeDecodeError):
                payload = None
            if (
                isinstance(payload, dict)
                and exc.code is not None
                and 400 <= exc.code < 500
            ):
                return payload
            last_error = exc
            time.sleep(0.2)
        except (URLError, TimeoutError, OSError) as exc:
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


def _handshake_field(sealed_handshake: str, name: str) -> str | None:
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
    value = handshake.get(name) if isinstance(handshake, dict) else None
    return value if isinstance(value, str) and value else None


def _handshake_grant_level(sealed_handshake: str) -> str | None:
    level = _handshake_field(sealed_handshake, "grant_level")
    return level if level in {"read", "send"} else None


def _code_challenge(verifier: str) -> str:
    import base64

    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )


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
    verifier = secrets.token_urlsafe(64)
    challenge = _code_challenge(verifier)
    if existing is not None and existing.expires_at > now:
        if str(existing.ally_id or "") != str(ally.id if ally is not None else ""):
            raise IntegrationInvalid("connect replay targets a different ally")
        if existing.entry_point != entry_point:
            raise IntegrationInvalid("connect replay targets a different entry point")
        if _handshake_grant_level(existing.sealed_handshake) != grant_level:
            raise IntegrationInvalid("connect replay targets a different grant level")
        replay_handshake = json.dumps(
            {
                "state": state,
                "pkce_verifier": verifier,
                "workspace_id": str(existing.workspace_id),
                "ally_id": str(existing.ally_id) if existing.ally_id else None,
                "grant_level": _handshake_grant_level(existing.sealed_handshake),
                "entry_point": existing.entry_point,
            }
        )
        replay_sealed, _ = seal_refresh_token(replay_handshake)
        existing.state_hash = state_hash
        existing.sealed_handshake = replay_sealed.decode()
        existing.expires_at = now + timedelta(seconds=CONNECT_SESSION_TTL_SECONDS)
        existing.save(update_fields=["state_hash", "sealed_handshake", "expires_at"])
        return GmailConnectBegin(
            connect_session_id=str(existing.id),
            auth_url=_authorization_url(client_id, redirect_uri, state, challenge),
            expires_at=existing.expires_at,
        )
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
        auth_url=_authorization_url(client_id, redirect_uri, state, challenge),
        expires_at=session.expires_at,
    )


def _authorization_url(
    client_id: str, redirect_uri: str, state: str, challenge: str
) -> str:
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
                "code_challenge": challenge,
                "code_challenge_method": "S256",
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


def peek_connect_workspace_id(*, state: str):
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    try:
        session = GmailConnectSession.objects.get(state_hash=state_hash)
    except GmailConnectSession.DoesNotExist as exc:
        raise IntegrationInvalid("unknown connect session") from exc
    now = timezone.now()
    if session.consumed_at is not None or session.expires_at <= now:
        raise IntegrationInvalid("connect session expired")
    return session.workspace_id


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
    verifier = _handshake_field(session.sealed_handshake, "pkce_verifier")
    if verifier is None:
        raise IntegrationInvalid("connect session handshake invalid")
    token = _post_form(
        _setting("ALLIES_GMAIL_TOKEN_ENDPOINT", GOOGLE_TOKEN_ENDPOINT),
        {
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "code": code,
            "code_verifier": verifier,
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
    account_email = _gmail_profile_email(access_token)
    account_ref_hash = hashlib.sha256(account_email.lower().encode()).hexdigest()
    ciphertext, key_version = seal_refresh_token(refresh_token)
    conflict = (
        IntegrationSecret.objects.filter(
            workspace=session.workspace,
            provider_key=PROVIDER_GMAIL,
            revoked_at=None,
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
