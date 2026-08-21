"""Short-lived access JWTs and database-authoritative refresh sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from auths.audit import emit_auth_event
from auths.config import (
    access_ttl_seconds,
    digest_key,
    jwt_audience,
    jwt_issuer,
    jwt_key,
    refresh_absolute_seconds,
    refresh_idle_seconds,
)
from auths.exceptions import SessionInvalid
from auths.models import (
    RefreshToken,
    SessionClientKind,
    SessionFamily,
    User,
)
from common.identifiers import new_public_id


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _digest(raw: str | bytes) -> str:
    value = raw.encode() if isinstance(raw, str) else raw
    return hmac.new(digest_key(), value, hashlib.sha256).hexdigest()


def _encode_jwt(claims: dict[str, Any]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    encoded_header = _b64(
        json.dumps(header, separators=(",", ":"), sort_keys=True).encode()
    )
    encoded_claims = _b64(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
    )
    signing_input = f"{encoded_header}.{encoded_claims}".encode()
    signature = hmac.new(jwt_key(), signing_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_claims}.{_b64(signature)}"


def _decode_jwt(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw) > 4096:
        raise SessionInvalid("access token malformed")
    parts = raw.split(".")
    if len(parts) != 3:
        raise SessionInvalid("access token malformed")
    try:
        header = json.loads(_unb64(parts[0]))
        claims = json.loads(_unb64(parts[1]))
        signature = _unb64(parts[2])
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise SessionInvalid("access token malformed") from exc
    if header != {"alg": "HS256", "typ": "JWT"} or not isinstance(claims, dict):
        raise SessionInvalid("access token claims invalid")
    expected = hmac.new(
        jwt_key(), f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(signature, expected):
        raise SessionInvalid("access token signature invalid")
    allowed = {"iss", "aud", "sub", "sid", "jti", "iat", "exp"}
    if set(claims) != allowed:
        raise SessionInvalid("access token claims invalid")
    if claims.get("iss") != jwt_issuer() or claims.get("aud") != jwt_audience():
        raise SessionInvalid("access token audience invalid")
    now = int(timezone.now().timestamp())
    try:
        if int(claims["exp"]) <= now or int(claims["iat"]) > now + 60:
            raise SessionInvalid("access token expired")
    except (KeyError, TypeError, ValueError) as exc:
        raise SessionInvalid("access token timing invalid") from exc
    if not all(
        isinstance(claims.get(key), str) and claims[key]
        for key in ("sub", "sid", "jti")
    ):
        raise SessionInvalid("access token subject invalid")
    return claims


@dataclass(frozen=True)
class SessionContext:
    user_agent: str = ""
    ip_prefix: str = ""


@dataclass(frozen=True)
class IssuedSession:
    family: SessionFamily
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


@dataclass(frozen=True)
class AuthenticatedSession:
    user: User
    family: SessionFamily
    claims: dict[str, Any]


class _RefreshReuse(Exception):
    def __init__(self, family_id: int):
        self.family_id = family_id


def _access_token(
    family: SessionFamily, user: User, now: datetime
) -> tuple[str, datetime]:
    expires = now + timedelta(seconds=access_ttl_seconds())
    claims = {
        "iss": jwt_issuer(),
        "aud": jwt_audience(),
        "sub": user.public_id,
        "sid": family.public_id,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return _encode_jwt(claims), expires


def _new_refresh() -> tuple[str, str]:
    raw = _b64(secrets.token_bytes(32))
    return raw, _digest(raw)


@transaction.atomic
def issue_session(
    user: User,
    *,
    context: SessionContext | None = None,
    client_kind: SessionClientKind | str = SessionClientKind.BROWSER,
) -> IssuedSession:
    if not user.is_active:
        raise SessionInvalid("user inactive")
    try:
        resolved_client_kind = SessionClientKind(str(client_kind))
    except ValueError as exc:
        raise SessionInvalid("session client kind invalid") from exc
    now = timezone.now()
    idle = now + timedelta(seconds=refresh_idle_seconds())
    absolute = now + timedelta(seconds=refresh_absolute_seconds())
    family = SessionFamily.objects.create(
        user=user,
        public_id=new_public_id("ses"),
        last_used_at=now,
        idle_expires_at=idle,
        absolute_expires_at=absolute,
        client_kind=resolved_client_kind,
    )
    raw_refresh, digest = _new_refresh()
    RefreshToken.objects.create(family=family, token_digest=digest, expires_at=idle)
    del context
    access, access_expires = _access_token(family, user, now)
    return IssuedSession(family, access, raw_refresh, access_expires, idle)


def authenticate_access(
    raw_jwt: str, *, expected_client_kind: SessionClientKind | str | None = None
) -> AuthenticatedSession:
    claims = _decode_jwt(raw_jwt)
    try:
        family = SessionFamily.objects.select_related("user").get(
            public_id=claims["sid"], user__public_id=claims["sub"]
        )
    except SessionFamily.DoesNotExist as exc:
        raise SessionInvalid("session not found") from exc
    if expected_client_kind is not None:
        try:
            resolved_client_kind = SessionClientKind(str(expected_client_kind))
        except ValueError as exc:
            raise SessionInvalid("session client kind invalid") from exc
        if family.client_kind != resolved_client_kind:
            raise SessionInvalid("session transport mismatch")
    if not family.is_active() or family.user.public_id != claims["sub"]:
        raise SessionInvalid("session inactive")
    return AuthenticatedSession(user=family.user, family=family, claims=claims)


def refresh_family_public_id(raw_token: str) -> str:
    """Resolve a rotating refresh token to its stable, non-secret family id."""

    if not isinstance(raw_token, str) or len(raw_token) > 512:
        raise SessionInvalid("refresh token invalid")
    try:
        return (
            RefreshToken.objects.select_related("family")
            .get(token_digest=_digest(raw_token))
            .family.public_id
        )
    except RefreshToken.DoesNotExist as exc:
        raise SessionInvalid("refresh token invalid") from exc


@transaction.atomic
def _rotate_refresh(
    raw_token: str,
    *,
    request_context: SessionContext | None = None,
    expected_client_kind: SessionClientKind | str | None = None,
) -> IssuedSession:
    if not isinstance(raw_token, str) or len(raw_token) > 512:
        raise SessionInvalid("refresh token invalid")
    try:
        token = (
            RefreshToken.objects.select_for_update()
            .select_related("family__user")
            .get(token_digest=_digest(raw_token))
        )
    except RefreshToken.DoesNotExist as exc:
        raise SessionInvalid("refresh token invalid") from exc
    family = (
        SessionFamily.objects.select_for_update()
        .select_related("user")
        .get(pk=token.family_id)
    )
    if expected_client_kind is not None:
        try:
            resolved_client_kind = SessionClientKind(str(expected_client_kind))
        except ValueError as exc:
            raise SessionInvalid("session client kind invalid") from exc
        if family.client_kind != resolved_client_kind:
            raise SessionInvalid("session transport mismatch")
    now = timezone.now()
    if token.used_at is not None:
        family.revoked_at = now
        family.revoke_reason = "refresh_reuse"
        family.save(update_fields=("revoked_at", "revoke_reason"))
        raise _RefreshReuse(family.pk)
    if not family.is_active(now) or token.expires_at <= now:
        raise SessionInvalid("refresh session expired")
    token.used_at = now
    token.save(update_fields=("used_at",))
    raw_successor, successor_digest = _new_refresh()
    successor_expires = min(
        now + timedelta(seconds=refresh_idle_seconds()), family.absolute_expires_at
    )
    RefreshToken.objects.create(
        family=family, token_digest=successor_digest, expires_at=successor_expires
    )
    family.last_used_at = now
    family.idle_expires_at = successor_expires
    family.save(update_fields=("last_used_at", "idle_expires_at"))
    access, access_expires = _access_token(family, family.user, now)
    del request_context
    return IssuedSession(
        family, access, raw_successor, access_expires, successor_expires
    )


def rotate_refresh(
    raw_token: str,
    *,
    request_context: SessionContext | None = None,
    expected_client_kind: SessionClientKind | str | None = None,
) -> IssuedSession:
    try:
        return _rotate_refresh(
            raw_token,
            request_context=request_context,
            expected_client_kind=expected_client_kind,
        )
    except _RefreshReuse as reuse:
        # The rotation transaction deliberately rolls back on the sentinel;
        # revocation is committed in its own transaction before returning 401.
        with transaction.atomic():
            family = SessionFamily.objects.select_for_update().get(pk=reuse.family_id)
            if family.revoked_at is None:
                family.revoked_at = timezone.now()
                family.revoke_reason = "refresh_reuse"
                family.save(update_fields=("revoked_at", "revoke_reason"))
        emit_auth_event(
            "auth.refresh.reuse_detected",
            outcome="revoked",
            reason_code="refresh_reuse",
            family_ref=str(reuse.family_id),
        )
        raise SessionInvalid("refresh token reused") from None


@transaction.atomic
def logout_session(
    *,
    access: AuthenticatedSession | None = None,
    refresh: str | None = None,
    expected_client_kind: SessionClientKind | str | None = None,
) -> None:
    family: SessionFamily | None = access.family if access else None
    if family is None and refresh:
        try:
            token = RefreshToken.objects.select_related("family").get(
                token_digest=_digest(refresh)
            )
            family = token.family
        except RefreshToken.DoesNotExist:
            return
    if family is None:
        return
    if expected_client_kind is not None:
        try:
            resolved_client_kind = SessionClientKind(str(expected_client_kind))
        except ValueError as exc:
            raise SessionInvalid("session client kind invalid") from exc
        if family.client_kind != resolved_client_kind:
            return
    locked = SessionFamily.objects.select_for_update().filter(pk=family.pk).first()
    if locked and locked.revoked_at is None:
        locked.revoked_at = timezone.now()
        locked.revoke_reason = "logout"
        locked.save(update_fields=("revoked_at", "revoke_reason"))


def revoke_family(family: SessionFamily, *, reason: str = "operator") -> bool:
    with transaction.atomic():
        locked = SessionFamily.objects.select_for_update().get(pk=family.pk)
        if locked.revoked_at is not None:
            return False
        locked.revoked_at = timezone.now()
        locked.revoke_reason = reason[:64]
        locked.save(update_fields=("revoked_at", "revoke_reason"))
        return True
