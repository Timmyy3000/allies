from urllib.parse import parse_qs, urlparse

import pytest
from django.test import override_settings

from auths.exceptions import FlowReplay, InvalidFlow, InvalidRedirect, ProviderRejected
from auths.models import ExternalIdentity, FlowPurpose
from auths.providers.base import ProviderKey, VerifiedIdentity
from auths.providers.fake import FakeProvider
from auths.services import flows as flow_service
from auths.services.accounts import resolve_or_create_user
from auths.services.flows import (
    _safe_redirect,
    _seal,
    _unseal,
    begin_auth_flow,
    complete_auth_flow,
    flow_redirect_for_state,
)
from auths.services.sessions import issue_session, revoke_family


@pytest.mark.django_db
@override_settings(ALLIES_AUTH_FAKE_PROVIDER_ENABLED=True)
def test_fake_flow_requires_both_bindings_and_consumes_on_provider_failure():
    start = begin_auth_flow(
        provider="fake",
        purpose=FlowPurpose.SIGN_IN,
        redirect_to="/app",
        browser_binding=b"csrf-cookie",
    )
    state = parse_qs(urlparse(start.authorization_url).query)["state"][0]
    with pytest.raises(ProviderRejected):
        complete_auth_flow(
            provider="fake",
            state=state,
            code="not-a-fake-code",
            browser_binding=b"csrf-cookie",
            flow_cookie=start.flow_cookie,
        )
    with pytest.raises(FlowReplay):
        complete_auth_flow(
            provider="fake",
            state=state,
            code="fake:subject",
            browser_binding=b"csrf-cookie",
            flow_cookie=start.flow_cookie,
        )


@pytest.mark.django_db
@override_settings(ALLIES_AUTH_FAKE_PROVIDER_ENABLED=True)
def test_flow_validation_rejects_bad_redirect_bindings_and_link_sessions():
    assert flow_redirect_for_state(None) is None
    assert flow_redirect_for_state("missing") is None
    with pytest.raises(InvalidRedirect):
        _safe_redirect("https://evil.example/")
    for malformed in ("/\\evil.example/path", "\\evil.example/path", "///evil/path"):
        with pytest.raises(InvalidRedirect):
            _safe_redirect(malformed)
    with pytest.raises(InvalidRedirect):
        _safe_redirect("/app\x00")
    with (
        override_settings(ALLIES_AUTH_REDIRECT_PATHS=["/app"]),
        pytest.raises(InvalidRedirect),
    ):
        _safe_redirect("/other")
    with pytest.raises(InvalidFlow):
        begin_auth_flow(
            provider="unknown",
            purpose=FlowPurpose.SIGN_IN,
            redirect_to="/app",
            browser_binding=b"csrf",
        )
    with pytest.raises(InvalidFlow):
        begin_auth_flow(
            provider=ProviderKey.FAKE,
            purpose=FlowPurpose.SIGN_IN,
            redirect_to="/app",
            browser_binding=b"",
        )

    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="flow-link")
    ).user
    issued = issue_session(user)
    with pytest.raises(InvalidFlow):
        begin_auth_flow(
            provider=ProviderKey.FAKE,
            purpose=FlowPurpose.LINK,
            redirect_to="/app",
            browser_binding=b"csrf",
        )
    with pytest.raises(InvalidFlow):
        begin_auth_flow(
            provider=ProviderKey.FAKE,
            purpose=FlowPurpose.SIGN_IN,
            redirect_to="/app",
            browser_binding=b"csrf",
            user=user,
            family=issued.family,
        )

    start = begin_auth_flow(
        provider=ProviderKey.FAKE,
        purpose=FlowPurpose.SIGN_IN,
        redirect_to="/app",
        browser_binding=b"csrf",
    )
    state = parse_qs(urlparse(start.authorization_url).query)["state"][0]
    with pytest.raises(InvalidFlow):
        complete_auth_flow(
            provider="unknown",
            state=state,
            code="fake:x",
            browser_binding=b"csrf",
            flow_cookie=start.flow_cookie,
        )
    with pytest.raises(InvalidFlow):
        complete_auth_flow(
            provider=ProviderKey.FAKE,
            state="",
            code="fake:x",
            browser_binding=b"csrf",
            flow_cookie=start.flow_cookie,
        )
    with pytest.raises(InvalidFlow):
        complete_auth_flow(
            provider=ProviderKey.FAKE,
            state="missing",
            code="fake:x",
            browser_binding=b"csrf",
            flow_cookie=start.flow_cookie,
        )
    with pytest.raises(InvalidFlow):
        complete_auth_flow(
            provider=ProviderKey.GOOGLE,
            state=state,
            code="fake:x",
            browser_binding=b"csrf",
            flow_cookie=start.flow_cookie,
        )
    with pytest.raises(InvalidFlow):
        complete_auth_flow(
            provider=ProviderKey.FAKE,
            state=state,
            code="fake:x",
            browser_binding=b"wrong",
            flow_cookie=start.flow_cookie,
        )
    with pytest.raises(InvalidFlow):
        complete_auth_flow(
            provider=ProviderKey.FAKE,
            state=state,
            code="fake:x",
            browser_binding=b"csrf",
            flow_cookie=None,
        )
    with pytest.raises(InvalidFlow):
        complete_auth_flow(
            provider=ProviderKey.FAKE,
            state=state,
            code="fake:x",
            browser_binding=b"csrf",
            flow_cookie="wrong",
        )


@pytest.mark.django_db
@override_settings(ALLIES_AUTH_FAKE_PROVIDER_ENABLED=True)
def test_flow_protection_and_link_state_and_provider_identity_mismatch(monkeypatch):
    monkeypatch.setattr(
        flow_service,
        "digest_key",
        lambda: (_ for _ in ()).throw(RuntimeError("key unavailable")),
    )
    with pytest.raises(InvalidFlow):
        _seal("secret")
    with pytest.raises(InvalidFlow):
        _unseal("sealed", max_age=60)
    monkeypatch.undo()

    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="flow-link-state")
    ).user
    issued = issue_session(user)
    start = begin_auth_flow(
        provider=ProviderKey.FAKE,
        purpose=FlowPurpose.LINK,
        redirect_to="/app",
        browser_binding=b"csrf",
        user=user,
        family=issued.family,
    )
    state = parse_qs(urlparse(start.authorization_url).query)["state"][0]
    revoke_family(issued.family, reason="test")
    with pytest.raises(InvalidFlow):
        complete_auth_flow(
            provider=ProviderKey.FAKE,
            state=state,
            code="fake:x",
            browser_binding=b"csrf",
            flow_cookie=start.flow_cookie,
        )


@pytest.mark.django_db
@override_settings(ALLIES_AUTH_FAKE_PROVIDER_ENABLED=True)
def test_link_rechecks_session_after_provider_io(monkeypatch):
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="link-race-owner")
    ).user
    issued = issue_session(user)
    start = begin_auth_flow(
        provider=ProviderKey.FAKE,
        purpose=FlowPurpose.LINK,
        redirect_to="/app",
        browser_binding=b"csrf",
        user=user,
        family=issued.family,
    )
    state = parse_qs(urlparse(start.authorization_url).query)["state"][0]

    class RevokingProvider(FakeProvider):
        def verify_callback(self, code, flow):
            revoke_family(issued.family, reason="during-provider-io")
            return VerifiedIdentity(provider="fake", subject="must-not-link")

    monkeypatch.setattr(
        flow_service, "get_provider", lambda provider: RevokingProvider()
    )

    with pytest.raises(InvalidFlow, match="no longer active"):
        complete_auth_flow(
            provider=ProviderKey.FAKE,
            state=state,
            code="fake:must-not-link",
            browser_binding=b"csrf",
            flow_cookie=start.flow_cookie,
        )
    assert not ExternalIdentity.objects.filter(subject="must-not-link").exists()

    start = begin_auth_flow(
        provider=ProviderKey.FAKE,
        purpose=FlowPurpose.SIGN_IN,
        redirect_to="/app",
        browser_binding=b"csrf",
    )
    state = parse_qs(urlparse(start.authorization_url).query)["state"][0]

    class MismatchingProvider(FakeProvider):
        def verify_callback(self, code, flow):
            return VerifiedIdentity(provider="google", subject="mismatch")

    monkeypatch.setattr(
        flow_service, "get_provider", lambda provider: MismatchingProvider()
    )
    with pytest.raises(ProviderRejected):
        complete_auth_flow(
            provider=ProviderKey.FAKE,
            state=state,
            code="fake:x",
            browser_binding=b"csrf",
            flow_cookie=start.flow_cookie,
        )
