"""Browser-bound, one-time authentication flows."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

from auths.audit import emit_auth_event
from auths.config import digest_key, flow_ttl_seconds, setting
from auths.exceptions import (
    FlowReplay,
    InvalidFlow,
    InvalidRedirect,
    ProviderRejected,
)
from auths.models import AuthFlow, FlowPurpose, SessionFamily, User
from auths.origins import origin_allowed
from auths.providers.base import (
    ProviderFlow,
    ProviderKey,
    VerifiedIdentity,
    get_provider,
)
from auths.services.accounts import UserBootstrap, resolve_or_create_user
from auths.services.identities import link_identity
from auths.services.sessions import IssuedSession, issue_session
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

logger = logging.getLogger("allies.auth")


@dataclass(frozen=True)
class AuthorizationStart:
    provider: ProviderKey
    redirect_to: str
    authorization_url: str
    flow_cookie: str
    expires_at: object


@dataclass(frozen=True)
class AuthCompletion:
    user: User
    identity: VerifiedIdentity
    session: IssuedSession | None
    bootstrap: UserBootstrap | None = None
    redirect_to: str = "/"


def flow_redirect_for_state(state: str) -> str | None:
    """Return a still-safe redirect target for privacy-safe callback errors."""

    if not isinstance(state, str) or not state:
        return None
    return (
        AuthFlow.objects.filter(
            state_digest=_digest(state), expires_at__gt=timezone.now()
        )
        .values_list("redirect_to", flat=True)
        .first()
    )


def _digest(raw: bytes | str) -> str:
    value = raw.encode() if isinstance(raw, str) else raw
    return hmac.new(digest_key(), value, hashlib.sha256).hexdigest()


def _seal(value: str) -> str:
    try:
        from cryptography.fernet import Fernet

        key = base64.urlsafe_b64encode(hashlib.sha256(digest_key()).digest())
        return Fernet(key).encrypt(value.encode()).decode()
    except Exception as exc:
        raise InvalidFlow("flow protection unavailable") from exc


def _unseal(value: str, *, max_age: int) -> str:
    try:
        from cryptography.fernet import Fernet

        key = base64.urlsafe_b64encode(hashlib.sha256(digest_key()).digest())
        # Fernet embeds an authenticated timestamp; max_age bounds replay of a
        # stolen database value even if the flow row has not yet been cleaned.
        return Fernet(key).decrypt(value.encode(), ttl=max_age).decode()
    except Exception as exc:
        raise InvalidFlow("flow verifier invalid") from exc


def _safe_redirect(value: str, trusted_origin: str | None) -> str:
    if (
        not isinstance(trusted_origin, str)
        or not origin_allowed(
            trusted_origin, getattr(settings, "CSRF_TRUSTED_ORIGINS", ())
        )
        or not isinstance(value, str)
        or len(trusted_origin) > 500
        or any(ord(char) < 32 or ord(char) == 127 for char in trusted_origin)
        or "\\" in trusted_origin
    ):
        raise InvalidRedirect("redirect is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value) or "\\" in value:
        raise InvalidRedirect("redirect is invalid")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise InvalidRedirect("redirect is invalid") from exc
    if (
        parsed.scheme
        or parsed.netloc
        or not value.startswith("/")
        or value.startswith("//")
        or not url_has_allowed_host_and_scheme(
            value, allowed_hosts=set(), require_https=True
        )
    ):
        raise InvalidRedirect("redirect is invalid")
    target = f"{trusted_origin.rstrip('/')}{value}"
    if len(target) > 500:
        raise InvalidRedirect("redirect is invalid")
    return target


def _browser_callback_uri(provider: ProviderKey) -> str:
    route = f"/api/v1/auths/callback/{provider.value}"
    if provider is ProviderKey.GOOGLE:
        return str(setting("ALLIES_AUTH_GOOGLE_REDIRECT_URI", "")) or route
    return route


def begin_auth_flow(
    *,
    provider: ProviderKey | str,
    purpose: FlowPurpose,
    redirect_to: str,
    trusted_origin: str | None,
    browser_binding: bytes,
    user: User | None = None,
    family: SessionFamily | None = None,
) -> AuthorizationStart:
    try:
        provider_key = ProviderKey(str(provider))
    except ValueError as exc:
        raise InvalidFlow("provider is invalid") from exc
    redirect = _safe_redirect(redirect_to, trusted_origin)
    if not browser_binding:
        raise InvalidFlow("browser binding is required")
    if purpose == FlowPurpose.LINK:
        if (
            user is None
            or family is None
            or family.user_id != user.pk
            or not family.is_active()
        ):
            raise InvalidFlow("link requires an active user session")
    elif user is not None or family is not None:
        raise InvalidFlow("sign-in flow cannot be user bound")
    provider_adapter = get_provider(provider_key)
    state = secrets.token_urlsafe(32)
    flow_cookie = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(24)
    pkce_verifier = secrets.token_urlsafe(32)
    now = timezone.now()
    expires_at = now + timedelta(seconds=flow_ttl_seconds())
    callback = _browser_callback_uri(provider_key)
    flow = AuthFlow.objects.create(
        state_digest=_digest(state),
        flow_cookie_digest=_digest(flow_cookie),
        browser_binding_digest=_digest(browser_binding),
        provider=provider_key.value,
        purpose=purpose,
        redirect_to=redirect,
        callback_uri=callback,
        user=user if purpose == FlowPurpose.LINK else None,
        session_family=family if purpose == FlowPurpose.LINK else None,
        nonce_digest=_digest(nonce),
        nonce_sealed=_seal(nonce),
        pkce_verifier_sealed=_seal(pkce_verifier),
        expires_at=expires_at,
    )
    del flow
    url = provider_adapter.authorization_url(
        ProviderFlow(
            provider=provider_key,
            state=state,
            nonce=nonce,
            redirect_uri=callback,
            pkce_verifier=pkce_verifier,
        )
    )
    emit_auth_event(
        "auth.flow.started", outcome="accepted", provider=provider_key.value
    )
    return AuthorizationStart(provider_key, redirect, url, flow_cookie, expires_at)


def complete_auth_flow(
    *,
    provider: ProviderKey | str,
    state: str,
    code: str,
    browser_binding: bytes,
    flow_cookie: str | bytes | None = None,
) -> AuthCompletion:
    try:
        provider_key = ProviderKey(str(provider))
    except ValueError as exc:
        raise InvalidFlow("provider is invalid") from exc
    if not state or len(state) > 512 or not browser_binding:
        raise InvalidFlow("flow state invalid")
    try:
        flow = AuthFlow.objects.select_related("user", "session_family").get(
            state_digest=_digest(state)
        )
    except AuthFlow.DoesNotExist as exc:
        raise InvalidFlow("flow state invalid") from exc
    now = timezone.now()
    if flow.provider != provider_key.value:
        raise InvalidFlow("provider mismatch")
    if flow.consumed_at is not None:
        raise FlowReplay("flow already consumed")
    if flow.expires_at <= now:
        raise InvalidFlow("flow expired")
    browser_digest = _digest(browser_binding)
    if not hmac.compare_digest(flow.browser_binding_digest, browser_digest):
        raise InvalidFlow("browser binding mismatch")
    if flow_cookie is None:
        raise InvalidFlow("flow cookie required")
    raw_cookie = flow_cookie.encode() if isinstance(flow_cookie, str) else flow_cookie
    if not hmac.compare_digest(flow.flow_cookie_digest, _digest(raw_cookie)):
        raise InvalidFlow("flow cookie mismatch")
    if flow.purpose == FlowPurpose.LINK and (
        flow.user_id is None
        or flow.session_family_id is None
        or not flow.session_family.is_active(now)
    ):
        raise InvalidFlow("link session is no longer active")
    pkce_verifier = _unseal(flow.pkce_verifier_sealed, max_age=flow_ttl_seconds() + 60)
    nonce = _unseal(flow.nonce_sealed, max_age=flow_ttl_seconds() + 60)
    adapter = get_provider(provider_key)
    # Claim the one-time state before provider I/O.  A malformed/outage
    # callback therefore cannot be retried with the same state.
    with transaction.atomic():
        locked = AuthFlow.objects.select_for_update().get(pk=flow.pk)
        if locked.consumed_at is not None:
            raise FlowReplay("flow already consumed")
        locked.consumed_at = now
        locked.save(update_fields=("consumed_at",))
    try:
        identity = adapter.verify_callback(
            code,
            ProviderFlow(
                provider=provider_key,
                state=state,
                nonce=nonce,
                redirect_uri=flow.callback_uri,
                pkce_verifier=pkce_verifier,
            ),
        )
    except ProviderRejected as exc:
        if settings.DEBUG:
            logger.warning(
                "auth provider callback rejected in debug mode: provider=%s reason=%s",
                provider_key.value,
                str(exc),
            )
        emit_auth_event(
            "auth.flow.rejected",
            outcome="rejected",
            reason_code=getattr(exc, "code", "provider_rejected"),
            provider=provider_key.value,
        )
        raise
    if identity.provider != provider_key.value:
        raise ProviderRejected("provider response mismatch")
    # Fake/provider adapters return a normalized identity; nonce validation is
    # provider-owned.  The persisted digest remains available for adapters that
    # expose a verified nonce in their result.
    if flow.purpose == FlowPurpose.LINK:
        with transaction.atomic():
            family = (
                SessionFamily.objects.select_for_update()
                .select_related("user")
                .get(pk=flow.session_family_id)
            )
            if family.user_id != flow.user_id or not family.is_active():
                raise InvalidFlow("link session is no longer active")
            link_identity(user=family.user, identity=identity)
        emit_auth_event(
            "auth.identity.linked",
            outcome="accepted",
            provider=provider_key.value,
            user_ref=str(family.user.id),
        )
        return AuthCompletion(
            user=family.user,
            identity=identity,
            session=None,
            redirect_to=flow.redirect_to,
        )
    bootstrap = resolve_or_create_user(identity)
    session = issue_session(bootstrap.user)
    emit_auth_event(
        "auth.flow.completed",
        outcome="accepted",
        provider=provider_key.value,
        user_ref=str(bootstrap.user.id),
    )
    return AuthCompletion(
        user=bootstrap.user,
        identity=identity,
        session=session,
        bootstrap=bootstrap,
        redirect_to=flow.redirect_to,
    )
