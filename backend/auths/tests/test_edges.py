from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.test import RequestFactory, override_settings
from django.utils import timezone

from auths.authentication import SessionCookieAuthentication, authenticate_request
from auths.exceptions import (
    IdentityConflict,
    InvalidFlow,
    InvalidRedirect,
    ProviderUnavailable,
    SessionInvalid,
    ValidationError,
)
from auths.models import AuthFlow, ExternalIdentity, FlowPurpose
from auths.providers.base import ProviderKey, VerifiedIdentity, get_provider
from auths.services.accounts import resolve_or_create_user
from auths.services.flows import begin_auth_flow, complete_auth_flow
from auths.services.identities import link_identity
from auths.services.profiles import update_display_name
from auths.services.sessions import (
    authenticate_access,
    issue_session,
    logout_session,
)


@pytest.mark.django_db
def test_authenticated_link_is_idempotent_and_collision_safe():
    first = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="edge-a")
    ).user
    second = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="edge-b")
    ).user
    identity = VerifiedIdentity(provider="fake", subject="linked")
    linked = link_identity(user=first, identity=identity)
    assert link_identity(user=first, identity=identity).pk == linked.pk
    with pytest.raises(IdentityConflict):
        link_identity(user=second, identity=identity)


@pytest.mark.django_db
def test_identity_link_unrelated_integrity_error_is_preserved(monkeypatch):
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="edge-race")
    ).user

    def collide(*args, **kwargs):
        raise IntegrityError("unique provider/subject race")

    monkeypatch.setattr(ExternalIdentity.objects, "create", collide)
    with pytest.raises(IntegrityError):
        link_identity(
            user=user,
            identity=VerifiedIdentity(provider="fake", subject="race-subject"),
        )


@pytest.mark.django_db
def test_access_claims_logout_and_unknown_tokens_fail_closed():
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="edge-session")
    ).user
    issued = issue_session(user)
    request = RequestFactory().get("/")
    request.COOKIES = {"allies_access": issued.access_token}
    assert authenticate_request(request).user.id == user.id
    assert SessionCookieAuthentication()(request).user.id == user.id
    logout_session(access=authenticate_access(issued.access_token))
    with pytest.raises(SessionInvalid):
        authenticate_access(issued.access_token)
    request.COOKIES = {}
    assert SessionCookieAuthentication()(request) is None
    with pytest.raises(SessionInvalid):
        authenticate_request(request)


@pytest.mark.django_db
@override_settings(ALLIES_AUTH_FAKE_PROVIDER_ENABLED=True)
def test_flow_binding_redirect_and_expiry_fail_closed():
    with pytest.raises(InvalidRedirect):
        begin_auth_flow(
            provider=ProviderKey.FAKE,
            purpose=FlowPurpose.SIGN_IN,
            redirect_to="https://evil.example/",
            browser_binding=b"csrf",
        )
    start = begin_auth_flow(
        provider=ProviderKey.FAKE,
        purpose=FlowPurpose.SIGN_IN,
        redirect_to="/app?next=1",
        browser_binding=b"csrf",
    )
    flow = AuthFlow.objects.get(state_digest__isnull=False)
    flow.expires_at = timezone.now() - timedelta(seconds=1)
    flow.save(update_fields=("expires_at",))
    from urllib.parse import parse_qs, urlparse

    state = parse_qs(urlparse(start.authorization_url).query)["state"][0]
    with pytest.raises(InvalidFlow):
        complete_auth_flow(
            provider=ProviderKey.FAKE,
            state=state,
            code="fake:expired",
            browser_binding=b"csrf",
            flow_cookie=start.flow_cookie,
        )


@pytest.mark.django_db
def test_profile_name_validation_and_provider_catalogue():
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="edge-profile")
    ).user
    with pytest.raises(ValidationError):
        update_display_name(user, "\u0000")
    with pytest.raises(ValidationError):
        update_display_name(user, "")
    with pytest.raises(ProviderUnavailable):
        get_provider("unknown")
