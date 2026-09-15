from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import close_old_connections, connection
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse

from auths.admin import reset_selected_invites
from auths.exceptions import (
    InviteConsumed,
    InviteRequired,
    InviteUnavailable,
    InviteValidation,
)
from auths.models import (
    BetaInvite,
    ExternalIdentity,
    NativeExchangeCode,
    User,
)
from auths.providers.base import VerifiedIdentity
from auths.services.accounts import resolve_or_create_user
from auths.services.invites import (
    claim_invite,
    issue_invite,
    reset_invite,
    revoke_invite,
)
from auths.throttle import ThrottleExceeded, ThrottleUnavailable
from workspaces.models import Membership, Workspace

TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@pytest.fixture(autouse=True)
def invite_digest_key(settings):
    settings.ALLIES_AUTH_DIGEST_KEY = "invite-test-digest-key"


def _verified_identity(subject: str, email: str = "person@example.com"):
    return VerifiedIdentity(
        provider="google",
        subject=subject,
        email=email,
        email_verified=True,
        email_verification_source="google",
    )


def _csrf(client: Client) -> str:
    return client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")["X-CSRFToken"]


@pytest.mark.django_db
def test_issue_claim_reset_revoke_and_digest_only_storage():
    invite, raw_code = issue_invite()
    assert len(raw_code) <= 128
    assert (
        invite.code_digest
        != __import__("hashlib").sha256(raw_code.encode()).hexdigest()
    )
    assert raw_code not in str(BetaInvite.objects.get(pk=invite.pk).__dict__)

    claim_invite(code=f" {raw_code} ", email=" Person@Example.com ")
    claim_invite(code=raw_code, email="person@example.com")
    invite.refresh_from_db()
    assert invite.claimed_email == "person@example.com"
    assert invite.claimed_at is not None
    with pytest.raises(InviteUnavailable):
        claim_invite(code=raw_code, email="other@example.com")

    replacement = reset_invite(invite.id)
    assert replacement != raw_code
    invite.refresh_from_db()
    assert invite.claimed_email is None
    with pytest.raises(InviteUnavailable):
        claim_invite(code=raw_code, email="person@example.com")
    claim_invite(code=replacement, email="person@example.com")
    revoke_invite(invite.id)
    with pytest.raises(InviteUnavailable):
        claim_invite(code=replacement, email="person@example.com")


@pytest.mark.django_db
@override_settings(ALLIES_BETA_INVITES_REQUIRED=True)
def test_new_identity_requires_matching_claim_and_consumes_it_with_bootstrap():
    before = (User.objects.count(), ExternalIdentity.objects.count())
    with pytest.raises(InviteRequired):
        resolve_or_create_user(_verified_identity("uninvited"))
    assert (User.objects.count(), ExternalIdentity.objects.count()) == before

    invite, code = issue_invite()
    claim_invite(code=code, email="person@example.com")
    bootstrap = resolve_or_create_user(_verified_identity("invited"))
    invite.refresh_from_db()
    assert bootstrap.created is True
    assert invite.consumed_at is not None
    assert bootstrap.workspace.workspace.owner_id == bootstrap.user.id
    assert NativeExchangeCode.objects.count() == 0

    with pytest.raises(InviteConsumed):
        reset_invite(invite.id)


@pytest.mark.django_db
@override_settings(ALLIES_BETA_INVITES_REQUIRED=True)
def test_unverified_or_non_google_new_identities_leave_no_account_graph():
    candidates = (
        VerifiedIdentity(provider="fake", subject="unverified"),
        VerifiedIdentity(provider="google", subject="missing-email"),
    )
    for identity in candidates:
        with pytest.raises(InviteRequired):
            resolve_or_create_user(identity)
    assert User.objects.count() == 0
    assert ExternalIdentity.objects.count() == 0
    assert Workspace.objects.count() == 0
    assert Membership.objects.count() == 0


@pytest.mark.django_db
@override_settings(ALLIES_BETA_INVITES_REQUIRED=True)
def test_signup_rolls_back_invite_consumption_when_bootstrap_fails(monkeypatch):
    invite, code = issue_invite()
    claim_invite(code=code, email="person@example.com")

    def fail_workspace(user):
        raise RuntimeError("workspace unavailable")

    monkeypatch.setattr(
        "auths.services.accounts.ensure_personal_workspace", fail_workspace
    )
    with pytest.raises(RuntimeError, match="workspace unavailable"):
        resolve_or_create_user(_verified_identity("rollback"))
    invite.refresh_from_db()
    assert invite.consumed_at is None
    assert User.objects.count() == 0
    assert ExternalIdentity.objects.count() == 0
    assert Workspace.objects.count() == 0
    assert Membership.objects.count() == 0


@pytest.mark.django_db
@override_settings(ALLIES_BETA_INVITES_REQUIRED=True)
def test_existing_provider_identity_bypasses_invite_gate():
    invite, code = issue_invite()
    claim_invite(code=code, email="person@example.com")
    first = resolve_or_create_user(_verified_identity("returning"))
    invite.refresh_from_db()
    assert invite.consumed_at is not None

    repeat = resolve_or_create_user(
        _verified_identity("returning", "changed@example.com")
    )
    assert repeat.user.id == first.user.id


@pytest.mark.django_db
def test_claim_api_requires_origin_csrf_and_returns_no_store_success():
    invite, code = issue_invite()
    client = Client(enforce_csrf_checks=True)
    csrf = _csrf(client)
    headers = {
        "HTTP_X_CSRFTOKEN": csrf,
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_HOST": "testserver",
    }
    missing_origin = client.post(
        "/api/v1/auths/invites/claim",
        {"code": code, "email": "person@example.com"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_HOST="testserver",
    )
    assert missing_origin.status_code == 403
    response = client.post(
        "/api/v1/auths/invites/claim",
        {"code": code, "email": "person@example.com"},
        content_type="application/json",
        **headers,
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "message": "Invite claimed",
        "data": {"claimed": True},
    }
    assert response["Cache-Control"].startswith("no-store")
    assert response["Pragma"] == "no-cache"
    invite.refresh_from_db()
    assert invite.claimed_email == "person@example.com"


@pytest.mark.django_db
def test_claim_api_rejects_extra_fields_and_unavailable_codes():
    client = Client(enforce_csrf_checks=True)
    csrf = _csrf(client)
    headers = {
        "HTTP_X_CSRFTOKEN": csrf,
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_HOST": "testserver",
    }
    extra = client.post(
        "/api/v1/auths/invites/claim",
        {"code": "MISSINGX", "email": "person@example.com", "status": "claimed"},
        content_type="application/json",
        **headers,
    )
    assert extra.status_code == 422
    unavailable = client.post(
        "/api/v1/auths/invites/claim",
        {"code": "MISSINGX", "email": "person@example.com"},
        content_type="application/json",
        **headers,
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["data"]["code"] == "invite_unavailable"


@pytest.mark.django_db
def test_claim_api_checks_identity_before_global_limit(monkeypatch):
    client = Client(enforce_csrf_checks=True)
    csrf = _csrf(client)
    calls = []

    def reject_identity(**kwargs):
        calls.append(kwargs)
        raise ThrottleExceeded

    monkeypatch.setattr("auths.api.invites.check_rate_limit", reject_identity)
    response = client.post(
        "/api/v1/auths/invites/claim",
        {"code": "ABCDEFGH", "email": "person@example.com"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    assert response.status_code == 429
    assert response["Retry-After"] == "60"
    assert len(calls) == 1
    assert calls[0]["scope"] == "invite-claim-identity"


@pytest.mark.django_db
def test_claim_api_fails_closed_when_throttle_cache_is_unavailable(monkeypatch):
    client = Client(enforce_csrf_checks=True)
    csrf = _csrf(client)
    monkeypatch.setattr(
        "auths.api.invites.check_rate_limit",
        lambda **kwargs: (_ for _ in ()).throw(ThrottleUnavailable()),
    )
    response = client.post(
        "/api/v1/auths/invites/claim",
        {"code": "ABCDEFGH", "email": "person@example.com"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    assert response.status_code == 503
    assert response.json()["data"]["code"] == "throttle_unavailable"


@pytest.mark.django_db
@override_settings(
    ALLIES_AUTH_INVITE_CLAIM_LIMIT=1,
    ALLIES_AUTH_INVITE_CLAIM_GLOBAL_LIMIT=2,
    ALLIES_AUTH_INVITE_CLAIM_RATE_LIMIT_PERIOD_SECONDS=60,
)
def test_claim_rate_limits_identity_before_global_and_blocks_mutation():
    cache.clear()
    invites = [issue_invite() for _ in range(4)]

    def claim(client, code, email, remote_addr):
        csrf = _csrf(client)
        return client.post(
            "/api/v1/auths/invites/claim",
            {"code": code, "email": email},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_HOST="testserver",
            REMOTE_ADDR=remote_addr,
        )

    first_client = Client(enforce_csrf_checks=True)
    second_client = Client(enforce_csrf_checks=True)
    third_client = Client(enforce_csrf_checks=True)
    first = claim(first_client, invites[0][1], "one@example.com", "10.0.0.1")
    repeated_identity = claim(
        first_client, invites[1][1], "two@example.com", "10.0.0.1"
    )
    other_identity = claim(second_client, invites[1][1], "two@example.com", "10.0.1.1")
    global_saturated = claim(
        third_client, invites[2][1], "three@example.com", "10.0.2.1"
    )

    assert first.status_code == 200
    assert repeated_identity.status_code == 429
    assert other_identity.status_code == 200
    assert global_saturated.status_code == 429
    invites[2][0].refresh_from_db()
    assert invites[2][0].claimed_email is None
    cache.clear()


@pytest.mark.django_db
@override_settings(STORAGES=TEST_STORAGES)
def test_beta_invite_admin_requires_add_change_permissions_and_shows_code_once():
    content_type = ContentType.objects.get_for_model(BetaInvite)
    add_permission = Permission.objects.get(
        content_type=content_type, codename="add_betainvite"
    )
    view_permission = Permission.objects.get(
        content_type=content_type, codename="view_betainvite"
    )
    view_only = User.objects.create(is_staff=True, is_active=True)
    view_only.set_unusable_password()
    view_only.save(update_fields=("password",))
    view_only.user_permissions.add(view_permission)
    client = Client()
    client.force_login(view_only)
    add_url = reverse("admin:auths_betainvite_add")
    assert client.get(add_url).status_code == 403
    assert client.post(add_url, {}).status_code == 403
    assert not BetaInvite.objects.exists()
    request = RequestFactory().get("/")
    request.user = view_only
    assert "revoke_selected_invites" not in admin.site.get_model_admin(
        BetaInvite
    ).get_actions(request)

    issuer = User.objects.create(is_staff=True, is_active=True)
    issuer.set_unusable_password()
    issuer.save(update_fields=("password",))
    issuer.user_permissions.add(add_permission)
    client.force_login(issuer)
    assert client.get(add_url).status_code == 200
    response = client.post(add_url, {})
    assert response.status_code == 200
    assert response["Cache-Control"].startswith("no-store")
    assert BetaInvite.objects.count() == 1
    assert "code=" not in response.content.decode()
    assert "Copy these codes now" in response.content.decode()


@pytest.mark.django_db(transaction=True)
def test_beta_invite_admin_reset_batch_rolls_back_before_codes_are_returned(
    monkeypatch,
):
    first, _ = issue_invite()
    second, _ = issue_invite()
    original_digests = {
        first.id: first.code_digest,
        second.id: second.code_digest,
    }
    operator = User.objects.create(is_staff=True, is_active=True)
    request = RequestFactory().post("/")
    request.user = operator
    modeladmin = admin.site.get_model_admin(BetaInvite)

    def fail_log(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("auths.admin.LogEntry.objects.log_actions", fail_log)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        reset_selected_invites(modeladmin, request, BetaInvite.objects.all())

    for invite_id, digest in original_digests.items():
        assert BetaInvite.objects.get(id=invite_id).code_digest == digest


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
def test_same_code_claim_has_one_postgresql_winner():
    if connection.vendor != "postgresql":
        pytest.skip("invite claim race requires PostgreSQL")
    _, code = issue_invite()
    barrier = Barrier(2)

    def claim_once(email):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            claim_invite(code=code, email=email)
            return "claimed"
        except InviteUnavailable:
            return "rejected"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(claim_once, ("first@example.com", "second@example.com"))
        )
    assert sorted(results) == ["claimed", "rejected"]


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
def test_distinct_codes_for_one_email_have_one_postgresql_winner():
    if connection.vendor != "postgresql":
        pytest.skip("invite claim race requires PostgreSQL")
    _, first_code = issue_invite()
    _, second_code = issue_invite()
    barrier = Barrier(2)

    def claim_once(code):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            claim_invite(code=code, email="same@example.com")
            return "claimed"
        except InviteUnavailable:
            return "rejected"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim_once, (first_code, second_code)))
    assert sorted(results) == ["claimed", "rejected"]


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
@override_settings(ALLIES_BETA_INVITES_REQUIRED=True)
def test_same_subject_signup_converges_after_grant_lock():
    if connection.vendor != "postgresql":
        pytest.skip("invite signup race requires PostgreSQL")
    invite, code = issue_invite()
    claim_invite(code=code, email="person@example.com")
    barrier = Barrier(2)

    def resolve_once():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return resolve_or_create_user(_verified_identity("same-subject"))
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=15)
            for future in [pool.submit(resolve_once) for _ in range(2)]
        ]
    assert results[0].user.pk == results[1].user.pk
    assert User.objects.filter(pk=results[0].user.pk).count() == 1
    invite.refresh_from_db()
    assert invite.consumed_at is not None


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
@override_settings(ALLIES_BETA_INVITES_REQUIRED=True)
def test_one_grant_admits_one_of_two_subjects():
    if connection.vendor != "postgresql":
        pytest.skip("invite signup race requires PostgreSQL")
    invite, code = issue_invite()
    claim_invite(code=code, email="person@example.com")
    barrier = Barrier(2)

    def resolve_once(subject):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                resolve_or_create_user(_verified_identity(subject))
            except InviteRequired:
                return "rejected"
            return "created"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(resolve_once, ("first-subject", "second-subject")))
    assert sorted(results) == ["created", "rejected"]
    invite.refresh_from_db()
    assert invite.consumed_at is not None
    assert ExternalIdentity.objects.count() == 1


@pytest.mark.django_db
@override_settings(
    ALLIES_BETA_INVITES_REQUIRED=True,
    ALLIES_AUTH_FAKE_PROVIDER_ENABLED=True,
    ALLOWED_HOSTS=["testserver"],
)
def test_browser_callback_redirects_invite_required_without_account_graph():
    client = Client(enforce_csrf_checks=True)
    csrf = _csrf(client)
    start = client.post(
        "/api/v1/auths/sign-in/fake",
        {"redirect_to": "/home"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    state = parse_qs(urlparse(start.json()["data"]["redirect_url"]).query)["state"][0]
    callback = client.get(
        "/api/v1/auths/callback/fake",
        {"state": state, "code": "fake:denied-new"},
        HTTP_HOST="testserver",
    )
    assert callback.status_code == 303
    assert callback["Location"] == (
        "http://localhost:3000/home?auth_error=invite_required"
    )
    assert User.objects.count() == 0
    assert ExternalIdentity.objects.count() == 0
    assert Workspace.objects.count() == 0
    assert Membership.objects.count() == 0


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("operation", [revoke_invite, reset_invite])
@override_settings(ALLIES_BETA_INVITES_REQUIRED=True)
def test_operator_change_and_signup_serialize_on_the_same_grant(operation):
    if connection.vendor != "postgresql":
        pytest.skip("invite lifecycle race requires PostgreSQL")
    invite, code = issue_invite()
    claim_invite(code=code, email="person@example.com")
    barrier = Barrier(2)

    def signup():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                resolve_or_create_user(_verified_identity("operator-race"))
                return "created"
            except InviteRequired:
                return "denied"
        finally:
            connection.close()

    def change_grant():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                operation(invite.id)
                return "changed"
            except InviteConsumed:
                return "consumed"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        signup_future = pool.submit(signup)
        operator_future = pool.submit(change_grant)
        signup_result = signup_future.result(timeout=15)
        operator_result = operator_future.result(timeout=15)

    invite.refresh_from_db()
    created = signup_result == "created"
    assert ExternalIdentity.objects.count() == int(created)
    assert (invite.consumed_at is not None) == created
    if operation is reset_invite:
        assert operator_result == ("consumed" if created else "changed")
        if not created:
            assert invite.claimed_email is None
    else:
        assert operator_result == "changed"
        assert invite.revoked_at is not None


@pytest.mark.django_db
def test_fixed_length_invite_codes_allow_lowercase():
    invite, code = issue_invite()
    assert len(code) == 8
    assert set(code) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    claim_invite(code=code.lower(), email="short@example.com")
    invite.refresh_from_db()
    assert invite.claimed_email == "short@example.com"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "code",
    [
        "",
        "ABCDEFG",
        "ABCDEFGHI",
        "ABCD1234",
        "old-token-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    ],
)
def test_rejects_invalid_invite_code_format(code):
    with pytest.raises(InviteValidation):
        claim_invite(code=code, email="person@example.com")


@pytest.mark.django_db
def test_claim_api_strips_whitespace_before_fixed_length_validation():
    invite, code = issue_invite()
    client = Client(enforce_csrf_checks=True)
    csrf = _csrf(client)
    response = client.post(
        "/api/v1/auths/invites/claim",
        {"code": f" {code.lower()} ", "email": "person@example.com"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    assert response.status_code == 200
    invite.refresh_from_db()
    assert invite.claimed_email == "person@example.com"


@pytest.mark.django_db
def test_invite_digest_depends_on_server_key():
    invite, code = issue_invite()
    with (
        override_settings(ALLIES_AUTH_DIGEST_KEY="different-test-key"),
        pytest.raises(InviteUnavailable),
    ):
        claim_invite(code=code, email="person@example.com")
    claim_invite(code=code, email="person@example.com")
    invite.refresh_from_db()
    assert invite.claimed_email == "person@example.com"
