import hashlib
import io
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client, override_settings
from django.test.client import RequestFactory
from PIL import Image

from auths.api.common import (
    _auth_rate_limit_identity,
    _new_auth_throttle_cookie,
    _railway_auth_admission_allowed,
)
from auths.api.controllers import _client_identity, _domain_status, _origin_allowed
from auths.exceptions import AvatarConflict, AvatarStorageUnavailable
from auths.models import ExternalIdentity
from auths.providers.base import VerifiedIdentity
from auths.services.accounts import resolve_or_create_user
from auths.services.sessions import issue_session
from auths.storage.avatars import InMemoryAvatarObjectStore, set_avatar_store
from auths.throttle import ThrottleExceeded, ThrottleUnavailable


def _csrf(client: Client) -> str:
    return client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")["X-CSRFToken"]


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(output, "PNG")
    return output.getvalue()


@override_settings(
    ALLIES_TRUST_FORWARDED_FOR=True, ALLIES_TRUSTED_PROXY_IPS=["10.0.0.8"]
)
def test_client_identity_only_uses_forwarding_from_trusted_proxy():
    factory = RequestFactory()
    spoofed = factory.get(
        "/", REMOTE_ADDR="203.0.113.8", HTTP_X_FORWARDED_FOR="198.51.100.9"
    )
    proxied = factory.get(
        "/",
        REMOTE_ADDR="10.0.0.8",
        HTTP_X_FORWARDED_FOR="198.51.100.9, 10.0.0.7",
    )

    assert _client_identity(spoofed) == "203.0.113.0/24"
    assert _client_identity(proxied) == "10.0.0.0/24"


@override_settings(ALLIES_RAILWAY_PROXY_MODE=True)
def test_railway_auth_throttle_identity_uses_a_server_issued_cookie():
    factory = RequestFactory()
    first = factory.post(
        "/",
        HTTP_COOKIE=f"allies_throttle={_new_auth_throttle_cookie()}",
        REMOTE_ADDR="10.0.0.1",
    )
    second = factory.post("/", HTTP_COOKIE="csrftoken=second", REMOTE_ADDR="10.0.0.1")

    assert _auth_rate_limit_identity(first).startswith("browser:")
    assert _auth_rate_limit_identity(second) == ""


@override_settings(ALLIES_RAILWAY_PROXY_MODE=True)
def test_railway_auth_admission_cannot_be_reset_by_rotating_csrf_cookie(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("auths.api.common.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("auths.api.common._railway_auth_bootstrap_tokens", 1.0)
    monkeypatch.setattr("auths.api.common._railway_auth_bootstrap_last_at", 100.0)

    factory = RequestFactory()
    first = factory.post("/", HTTP_COOKIE="csrftoken=first")
    second = factory.post("/", HTTP_COOKIE="csrftoken=second")

    assert _railway_auth_admission_allowed(first)
    assert not _railway_auth_admission_allowed(second)
    clock[0] += 1.0
    assert _railway_auth_admission_allowed(second)


@override_settings(ALLIES_RAILWAY_PROXY_MODE=True)
def test_valid_railway_throttle_cookie_does_not_share_bootstrap_gate(monkeypatch):
    monkeypatch.setattr("auths.api.common._railway_auth_bootstrap_tokens", 0.0)
    monkeypatch.setattr("auths.api.common._railway_auth_bootstrap_last_at", 100.0)
    request = RequestFactory().post(
        "/",
        HTTP_COOKIE=f"allies_throttle={_new_auth_throttle_cookie()}",
    )

    assert _railway_auth_admission_allowed(request)


@pytest.mark.django_db
@override_settings(
    ALLIES_AUTH_FAKE_PROVIDER_ENABLED=True,
    ALLIES_RAILWAY_PROXY_MODE=True,
    ALLOWED_HOSTS=["testserver"],
)
def test_railway_sign_in_gate_survives_throttle_cookie_rotation(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("auths.api.common.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("auths.api.common._railway_auth_bootstrap_tokens", 1.0)
    monkeypatch.setattr("auths.api.common._railway_auth_bootstrap_last_at", 100.0)

    client = Client(enforce_csrf_checks=True)
    csrf = _csrf(client)
    first = client.post(
        "/api/v1/auths/sign-in/fake",
        {"redirect_to": "/"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    assert first.status_code == 200

    del client.cookies["allies_throttle"]
    del client.cookies["csrftoken"]
    second = client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")
    assert second.status_code == 429


@pytest.mark.django_db
@override_settings(ALLOWED_HOSTS=["testserver"])
def test_refresh_throttle_uses_stable_family_across_rotation(monkeypatch):
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="refresh-throttle")
    ).user
    issued = issue_session(user)
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "auths.api.sessions.check_rate_limit",
        lambda **kwargs: captured.append((kwargs["scope"], kwargs["identity"])),
    )
    client = Client(enforce_csrf_checks=True)
    client.cookies["allies_refresh"] = issued.refresh_token
    csrf = _csrf(client)

    for _ in range(2):
        response = client.post(
            "/api/v1/auths/refresh",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_HOST="testserver",
        )
        assert response.status_code == 204

    family_identities = [
        identity for scope, identity in captured if scope == "refresh-family"
    ]
    assert family_identities == [issued.family.public_id, issued.family.public_id]


@pytest.mark.django_db
@override_settings(ALLIES_AUTH_FAKE_PROVIDER_ENABLED=True, ALLOWED_HOSTS=["testserver"])
def test_profile_refresh_logout_and_link_error_paths():
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="api-edge")
    ).user
    issued = issue_session(user)
    client = Client(enforce_csrf_checks=True)
    client.cookies["allies_access"] = issued.access_token
    client.cookies["allies_refresh"] = issued.refresh_token
    csrf = _csrf(client)
    profile = client.patch(
        "/api/v1/auths/me/profile",
        {"display_name": "Updated Name"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    assert profile.status_code == 200
    invalid = client.patch(
        "/api/v1/auths/me/profile",
        {"display_name": "\u0000"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    assert invalid.status_code == 422
    link = client.post(
        "/api/v1/auths/identities/fake/link",
        {"redirect_to": "/app"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    assert link.status_code == 200
    state = parse_qs(urlparse(link.json()["data"]["redirect_url"]).query)["state"][0]
    callback = client.get(
        "/api/v1/auths/callback/fake",
        {"state": state, "code": "fake:linked"},
        HTTP_HOST="testserver",
    )
    assert callback.status_code == 303
    assert ExternalIdentity.objects.filter(user=user, subject="linked").exists()
    refreshed = client.post(
        "/api/v1/auths/refresh",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    assert refreshed.status_code == 204
    logged_out = client.post(
        "/api/v1/auths/logout",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    assert logged_out.status_code == 204


@pytest.mark.django_db
@override_settings(ALLOWED_HOSTS=["testserver"])
def test_avatar_and_workspace_controller_boundaries():
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="api-avatar")
    ).user
    issued = issue_session(user)
    client = Client(enforce_csrf_checks=True)
    client.cookies["allies_access"] = issued.access_token
    csrf = _csrf(client)
    data = _png()
    set_avatar_store(InMemoryAvatarObjectStore())
    prepare = client.post(
        "/api/v1/auths/me/avatar/uploads",
        {
            "content_type": "image/png",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    assert prepare.status_code == 201
    from auths.models import AvatarAsset

    asset = AvatarAsset.objects.get(public_id=prepare.json()["data"]["asset_id"])
    store = InMemoryAvatarObjectStore()
    set_avatar_store(store)
    store.put(asset.object_key, data, "image/png")
    complete = client.post(
        f"/api/v1/auths/me/avatar/{asset.public_id}/complete",
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    assert complete.status_code == 200
    read = client.get("/api/v1/auths/me/avatar/read", HTTP_HOST="testserver")
    assert read.status_code == 200 and read.json()["data"]["url"].startswith(
        "memory://"
    )
    deleted = client.delete(
        "/api/v1/auths/me/avatar",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    assert deleted.status_code == 204
    workspace = user.owned_workspaces.first()
    context = client.get(
        f"/api/v1/workspaces/{workspace.public_id}", HTTP_HOST="testserver"
    )
    assert context.status_code == 200
    assert (
        client.get("/api/v1/workspaces/wsp_missing", HTTP_HOST="testserver").status_code
        == 404
    )


@pytest.mark.django_db
@override_settings(ALLOWED_HOSTS=["testserver"])
def test_avatar_controller_normalizes_storage_and_pointer_failures(monkeypatch):
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="api-avatar-outage")
    ).user
    issued = issue_session(user)
    client = Client(enforce_csrf_checks=True)
    client.cookies["allies_access"] = issued.access_token
    csrf = _csrf(client)
    request_headers = {
        "HTTP_X_CSRFTOKEN": csrf,
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_HOST": "testserver",
    }
    unavailable = lambda *args, **kwargs: (_ for _ in ()).throw(
        AvatarStorageUnavailable("R2 unavailable")
    )

    monkeypatch.setattr("auths.api.avatar.prepare_avatar_upload", unavailable)
    prepared = client.post(
        "/api/v1/auths/me/avatar/uploads",
        {"content_type": "image/png", "size": 10, "sha256": "0" * 64},
        content_type="application/json",
        **request_headers,
    )
    assert prepared.status_code == 503

    monkeypatch.setattr("auths.api.avatar.complete_avatar_upload", unavailable)
    completed = client.post(
        "/api/v1/auths/me/avatar/avt_missing/complete",
        content_type="application/json",
        **request_headers,
    )
    assert completed.status_code == 503

    monkeypatch.setattr("auths.api.avatar.signed_avatar_read", unavailable)
    assert (
        client.get("/api/v1/auths/me/avatar/read", HTTP_HOST="testserver").status_code
        == 503
    )

    monkeypatch.setattr(
        "auths.api.avatar.delete_current_avatar",
        lambda user: (_ for _ in ()).throw(AvatarConflict("invalid pointer")),
    )
    deleted = client.delete("/api/v1/auths/me/avatar", **request_headers)
    assert deleted.status_code == 409


@pytest.mark.django_db
@override_settings(ALLIES_AUTH_FAKE_PROVIDER_ENABLED=True, ALLOWED_HOSTS=["testserver"])
def test_controller_origin_provider_callback_and_throttle_failures(monkeypatch):
    client = Client(enforce_csrf_checks=True)
    csrf = _csrf(client)
    rejected = client.post(
        "/api/v1/auths/sign-in/fake",
        {"redirect_to": "/"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="https://evil.example",
        HTTP_HOST="testserver",
    )
    assert rejected.status_code == 403
    monkeypatch.setattr(
        "auths.api.authentication.check_rate_limit",
        lambda **kwargs: (_ for _ in ()).throw(ThrottleExceeded()),
    )
    throttled = client.post(
        "/api/v1/auths/sign-in/fake",
        {"redirect_to": "/"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    assert throttled.status_code == 429
    monkeypatch.setattr(
        "auths.api.authentication.check_rate_limit",
        lambda **kwargs: (_ for _ in ()).throw(ThrottleUnavailable()),
    )
    unavailable = client.post(
        "/api/v1/auths/sign-in/fake",
        {"redirect_to": "/"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    assert unavailable.status_code == 503


@pytest.mark.django_db
@override_settings(ALLIES_AUTH_FAKE_PROVIDER_ENABLED=True, ALLOWED_HOSTS=["testserver"])
def test_all_mutating_routes_reject_missing_origin_and_referer():
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="missing-origin")
    ).user
    issued = issue_session(user)
    client = Client(enforce_csrf_checks=True)
    client.cookies["allies_access"] = issued.access_token
    client.cookies["allies_refresh"] = issued.refresh_token
    csrf = _csrf(client)
    headers = {"HTTP_X_CSRFTOKEN": csrf, "HTTP_HOST": "testserver"}
    requests = (
        lambda: client.post(
            "/api/v1/auths/sign-in/fake",
            {"redirect_to": "/"},
            content_type="application/json",
            **headers,
        ),
        lambda: client.post("/api/v1/auths/refresh", **headers),
        lambda: client.post("/api/v1/auths/logout", **headers),
        lambda: client.patch(
            "/api/v1/auths/me/profile",
            {"display_name": "Name"},
            content_type="application/json",
            **headers,
        ),
        lambda: client.post(
            "/api/v1/auths/identities/fake/link",
            {"redirect_to": "/"},
            content_type="application/json",
            **headers,
        ),
        lambda: client.post(
            "/api/v1/auths/me/avatar/uploads",
            {"content_type": "image/png", "size": 1, "sha256": "0" * 64},
            content_type="application/json",
            **headers,
        ),
        lambda: client.post(
            "/api/v1/auths/me/avatar/avt_missing/complete",
            content_type="application/json",
            **headers,
        ),
        lambda: client.delete("/api/v1/auths/me/avatar", **headers),
    )

    assert [request().status_code for request in requests] == [403] * len(requests)


@pytest.mark.django_db
@override_settings(ALLIES_AUTH_FAKE_PROVIDER_ENABLED=True, ALLOWED_HOSTS=["testserver"])
def test_callback_provider_failure_redirects_without_reusing_state():
    client = Client(enforce_csrf_checks=True)
    csrf = _csrf(client)
    start = client.post(
        "/api/v1/auths/sign-in/fake",
        {"redirect_to": "/app?from=login"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    state = parse_qs(urlparse(start.json()["data"]["redirect_url"]).query)["state"][0]
    failed = client.get(
        "/api/v1/auths/callback/fake",
        {"state": state, "code": "bad-code"},
        HTTP_HOST="testserver",
    )
    assert failed.status_code == 303
    assert failed["Location"].startswith("/app?from=login&auth_error=")


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"], ALLIES_AUTH_FAKE_PROVIDER_ENABLED=False
)
def test_controller_unauthenticated_and_unknown_provider_statuses():
    client = Client(enforce_csrf_checks=True)
    csrf = _csrf(client)
    assert client.get("/api/v1/auths/me", HTTP_HOST="testserver").status_code == 401
    assert (
        client.get("/api/v1/auths/me/avatar/read", HTTP_HOST="testserver").status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auths/refresh",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_HOST="testserver",
        ).status_code
        == 401
    )
    client.cookies["allies_refresh"] = "invalid"
    assert (
        client.post(
            "/api/v1/auths/refresh",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_HOST="testserver",
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auths/identities/fake/link",
            {"redirect_to": "/"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_HOST="testserver",
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auths/sign-in/unknown",
            {"redirect_to": "/"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_HOST="testserver",
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/v1/auths/callback/unknown",
            {"state": "bad", "code": "bad"},
            HTTP_HOST="testserver",
        ).status_code
        == 400
    )
    assert (
        client.delete(
            "/api/v1/auths/me/avatar",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_HOST="testserver",
        ).status_code
        == 401
    )


@override_settings(CSRF_TRUSTED_ORIGINS=["http://localhost:3000"])
def test_origin_and_status_helpers_are_explicit():
    request = RequestFactory().post("/", HTTP_REFERER="http://localhost:3000/app")
    assert _origin_allowed(request)
    assert not _origin_allowed(RequestFactory().post("/"))
    assert _domain_status("provider_unavailable") == 404
    assert _domain_status("unknown", 418) == 418
