import json
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.test import Client, override_settings
from django.utils import timezone

from waitlist.capabilities import capability_digest
from waitlist.models import DraftLifecycle, OperationKind, WaitlistDraft


@pytest.fixture
def waitlist_client(settings):
    settings.ALLIES_WAITLIST_ENABLED = True
    settings.ALLIES_WAITLIST_CAPABILITY_KEY = "k" * 32
    cache.clear()
    client = Client(enforce_csrf_checks=True)
    session = client.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    assert session.status_code == 204
    csrf = client.cookies["csrftoken"].value
    return client, {
        "HTTP_HOST": "testserver",
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_X_CSRFTOKEN": csrf,
    }


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_ENABLED=True,
    ALLIES_WAITLIST_PROVIDER_ENABLED=True,
    ALLIES_WAITLIST_PROVIDER="fake",
    ALLIES_WAITLIST_CONSENT_VERSION="consent-v1",
    ALLIES_WAITLIST_JOINED_RETENTION_SECONDS=30 * 24 * 60 * 60,
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
)
def test_browser_flow_is_cookie_bound_and_refresh_safe(waitlist_client):
    client, headers = waitlist_client
    headers["HTTP_IDEMPOTENCY_KEY"] = "create-1"
    created = client.post(
        "/api/v1/waitlist/draft", data="{}", content_type="application/json", **headers
    )
    assert created.status_code == 200
    assert created.json()["data"]["result_revision"] == 1
    # The acknowledgement is immutable on replay.
    assert (
        client.post(
            "/api/v1/waitlist/draft",
            data="{}",
            content_type="application/json",
            **headers,
        ).json()
        == created.json()
    )
    restored = client.get(
        "/api/v1/waitlist/draft",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    assert restored.json()["data"]["lifecycle"] == "configuring"
    revision = restored.json()["data"]["revision"]
    headers["HTTP_IDEMPOTENCY_KEY"] = "config-1"
    configured = client.patch(
        "/api/v1/waitlist/draft/configuration",
        data=json.dumps(
            {
                "revision": revision,
                "name": "Ari",
                "appearance_catalog_version": "v1",
                "appearance_key": "calm",
                "job": "Planning",
                "personality": "Warm",
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert configured.json()["data"]["result_lifecycle"] == "ready_for_greeting"
    configured_acknowledgement = configured.json()
    # A later mutation must not change an earlier retry acknowledgement.
    revision += 1
    headers["HTTP_IDEMPOTENCY_KEY"] = "generate-1"
    generated = client.post(
        "/api/v1/waitlist/draft/greeting",
        data=json.dumps({"revision": revision}),
        content_type="application/json",
        **headers,
    )
    assert generated.json()["data"]["result_lifecycle"] == "greeting_ready"
    replayed_configuration = client.patch(
        "/api/v1/waitlist/draft/configuration",
        data=json.dumps(
            {
                "revision": 1,
                "name": "Ari",
                "appearance_catalog_version": "v1",
                "appearance_key": "calm",
                "job": "Planning",
                "personality": "Warm",
            }
        ),
        content_type="application/json",
        **dict(headers, HTTP_IDEMPOTENCY_KEY="config-1"),
    )
    assert replayed_configuration.json() == configured_acknowledgement
    revision += 1
    headers["HTTP_IDEMPOTENCY_KEY"] = "reply-1"
    replied = client.post(
        "/api/v1/waitlist/draft/reply",
        data=json.dumps({"revision": revision, "text": "  exact attempted reply  "}),
        content_type="application/json",
        **headers,
    )
    assert replied.json()["data"]["result_lifecycle"] == "reply_pending"
    revision += 1
    headers["HTTP_IDEMPOTENCY_KEY"] = "join-1"
    joined = client.post(
        "/api/v1/waitlist/draft/join",
        data=json.dumps(
            {
                "revision": revision,
                "email": "Person@Example.com",
                "consent_version": "consent-v1",
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert joined.json()["data"]["email"] == "p****n@example.com"
    with override_settings(ALLIES_WAITLIST_CONSENT_VERSION="consent-v2"):
        replayed_join = client.post(
            "/api/v1/waitlist/draft/join",
            data=json.dumps(
                {
                    "revision": revision,
                    "email": "Person@Example.com",
                    "consent_version": "consent-v1",
                }
            ),
            content_type="application/json",
            **headers,
        )
    assert replayed_join.json() == joined.json()
    snapshot = client.get(
        "/api/v1/waitlist/draft",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    ).json()
    assert snapshot["data"]["reply"]["text"] == "  exact attempted reply  "
    assert "Person@Example.com" not in json.dumps(snapshot)


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_ENABLED=True, ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32
)
def test_public_mutations_require_origin_csrf_and_idempotency(waitlist_client):
    client, headers = waitlist_client
    no_key = client.post(
        "/api/v1/waitlist/draft",
        data="{}",
        content_type="application/json",
        **headers,
    )
    assert no_key.status_code == 422
    assert no_key.json()["data"]["details"] == {
        "errors": [{"field": "request", "code": "value_error"}]
    }
    bad_origin = dict(headers, HTTP_ORIGIN="http://evil.example")
    bad_origin["HTTP_IDEMPOTENCY_KEY"] = "create"
    response = client.post(
        "/api/v1/waitlist/draft",
        data="{}",
        content_type="application/json",
        **bad_origin,
    )
    assert response.status_code == 403
    response = client.get(
        "/api/v1/waitlist/draft",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://evil.example",
    )
    assert response.status_code == 403
    response = client.get(
        "/api/v1/waitlist/draft",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_ENABLED=True, ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32
)
def test_restore_without_capability_does_not_admit_empty_digest(
    waitlist_client, monkeypatch
):
    client, _ = waitlist_client
    client.cookies.pop("allies_waitlist_capability", None)
    admitted = []
    monkeypatch.setattr("waitlist.api.controllers.admit_capability", admitted.append)

    response = client.get(
        "/api/v1/waitlist/draft",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )

    assert response.status_code == 404
    assert admitted == []


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_ENABLED=True, ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32
)
def test_empty_configuration_patch_rejects_without_mutation(waitlist_client):
    client, headers = waitlist_client
    created = client.post(
        "/api/v1/waitlist/draft",
        data="{}",
        content_type="application/json",
        **dict(headers, HTTP_IDEMPOTENCY_KEY="create-empty-config"),
    )
    assert created.status_code == 200

    response = client.patch(
        "/api/v1/waitlist/draft/configuration",
        data=json.dumps({"revision": 1}),
        content_type="application/json",
        **dict(headers, HTTP_IDEMPOTENCY_KEY="empty-config"),
    )
    assert response.status_code == 422
    draft = WaitlistDraft.objects.get()
    assert draft.revision == 1
    assert not draft.operations.filter(kind=OperationKind.CONFIGURE).exists()


@pytest.mark.django_db
@override_settings(ALLIES_WAITLIST_ENABLED=False)
def test_disabled_feature_is_neutral():
    client = Client()
    response = client.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    assert response.status_code == 503
    assert response.json()["message"] == "waitlist unavailable"
    assert response.json()["data"]["code"] == "waitlist_unavailable"


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_ENABLED=True, ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32
)
def test_session_refreshes_valid_cookie_and_rotates_expired_draft():
    cache.clear()
    client = Client()
    client.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    raw = client.cookies["allies_waitlist_capability"].value
    digest = capability_digest(raw)
    from waitlist.services.drafts import create_or_resume_draft

    create_or_resume_draft(capability_digest=digest, raw_key="create")
    draft = WaitlistDraft.objects.get(capability_digest=digest)

    refreshed = client.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    refreshed_raw = refreshed.cookies["allies_waitlist_capability"].value
    assert capability_digest(refreshed_raw) == digest

    draft.expires_at = timezone.now() - timedelta(seconds=1)
    draft.save(update_fields=("expires_at",))
    rotated = client.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    assert rotated.cookies["allies_waitlist_capability"].value != raw
    draft.refresh_from_db()
    assert draft.lifecycle == DraftLifecycle.EXPIRED
    assert draft.capability_digest is None


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_ENABLED=True,
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_CAPABILITY_TTL_SECONDS=2,
)
def test_session_revokes_draft_bound_to_expired_capability(monkeypatch):
    cache.clear()
    monkeypatch.setattr("waitlist.capabilities.time.time", lambda: 100)
    client = Client()
    initial = client.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    assert initial.status_code == 204
    raw = client.cookies["allies_waitlist_capability"].value
    digest = capability_digest(raw)

    from waitlist.services.drafts import create_or_resume_draft

    create_or_resume_draft(capability_digest=digest, raw_key="expired-cookie-create")
    draft = WaitlistDraft.objects.get(capability_digest=digest)

    monkeypatch.setattr("waitlist.capabilities.time.time", lambda: 103)
    rotated = client.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    assert rotated.status_code == 204
    replacement = rotated.cookies["allies_waitlist_capability"].value
    assert replacement != raw
    assert capability_digest(replacement) != digest

    draft.refresh_from_db()
    assert draft.lifecycle == DraftLifecycle.EXPIRED
    assert draft.capability_digest is None


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_ENABLED=True, ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32
)
def test_cross_site_session_cannot_rotate_or_revoke_capability():
    cache.clear()
    client = Client(enforce_csrf_checks=True)
    initial = client.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    assert initial.status_code == 204
    raw = client.cookies["allies_waitlist_capability"].value
    digest = capability_digest(raw)

    from waitlist.services.drafts import create_or_resume_draft

    create_or_resume_draft(capability_digest=digest, raw_key="cross-site-create")
    draft = WaitlistDraft.objects.get(capability_digest=digest)
    draft.expires_at = timezone.now() - timedelta(seconds=1)
    draft.save(update_fields=("expires_at",))

    missing_provenance = client.get("/api/v1/waitlist/session", HTTP_HOST="testserver")
    assert missing_provenance.status_code == 403
    assert missing_provenance.json()["data"]["code"] == "origin_rejected"
    assert "allies_waitlist_capability" not in missing_provenance.cookies

    blocked = client.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://evil.example",
    )
    assert blocked.status_code == 403
    assert blocked.json()["data"]["code"] == "origin_rejected"
    assert "allies_waitlist_capability" not in blocked.cookies
    referer_blocked = client.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_REFERER="https://evil.example/preview",
    )
    assert referer_blocked.status_code == 403
    assert "allies_waitlist_capability" not in referer_blocked.cookies

    draft.refresh_from_db()
    assert draft.capability_digest == digest
    assert draft.lifecycle == DraftLifecycle.CONFIGURING


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_ENABLED=True,
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_CAPABILITY_TTL_SECONDS=2,
)
def test_successful_mutation_extends_capability_without_orphaning_draft(monkeypatch):
    cache.clear()
    monkeypatch.setattr("waitlist.capabilities.time.time", lambda: 100)
    client = Client(enforce_csrf_checks=True)
    client.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    raw = client.cookies["allies_waitlist_capability"].value
    digest = capability_digest(raw)
    csrf = client.cookies["csrftoken"].value
    created = client.post(
        "/api/v1/waitlist/draft",
        data="{}",
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="create-sliding",
    )
    assert created.status_code == 200

    monkeypatch.setattr("waitlist.capabilities.time.time", lambda: 101)
    configured = client.patch(
        "/api/v1/waitlist/draft/configuration",
        data=json.dumps({"revision": 1, "name": "Still active"}),
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="config-sliding",
    )
    assert configured.status_code == 200
    refreshed_raw = configured.cookies["allies_waitlist_capability"].value
    assert refreshed_raw != raw
    assert capability_digest(refreshed_raw) == digest

    monkeypatch.setattr("waitlist.capabilities.time.time", lambda: 102.5)
    restored = client.get(
        "/api/v1/waitlist/draft",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    assert restored.status_code == 200
    assert restored.json()["data"]["revision"] == 2


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_ENABLED=True, ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32
)
def test_forged_capability_cannot_create_draft(waitlist_client):
    client, headers = waitlist_client
    client.cookies["allies_waitlist_capability"] = "attacker-chosen"
    response = client.post(
        "/api/v1/waitlist/draft",
        data="{}",
        content_type="application/json",
        **dict(headers, HTTP_IDEMPOTENCY_KEY="forged-create"),
    )

    assert response.status_code == 404
    assert response.json()["data"]["code"] == "waitlist_draft_unavailable"
    assert WaitlistDraft.objects.count() == 0


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_ENABLED=True,
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_CONSENT_VERSION="consent-v1",
)
def test_valid_second_browser_cannot_access_first_browser_draft():
    cache.clear()
    first = Client(enforce_csrf_checks=True)
    first.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    first_headers = {
        "HTTP_HOST": "testserver",
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_X_CSRFTOKEN": first.cookies["csrftoken"].value,
        "HTTP_IDEMPOTENCY_KEY": "first-create",
    }
    assert (
        first.post(
            "/api/v1/waitlist/draft",
            data="{}",
            content_type="application/json",
            **first_headers,
        ).status_code
        == 200
    )

    second = Client(enforce_csrf_checks=True)
    second.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    second_headers = {
        "HTTP_HOST": "testserver",
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_X_CSRFTOKEN": second.cookies["csrftoken"].value,
    }
    responses = [
        second.get(
            "/api/v1/waitlist/draft",
            HTTP_HOST="testserver",
            HTTP_ORIGIN="http://localhost:3000",
        ),
        second.patch(
            "/api/v1/waitlist/draft/configuration",
            data=json.dumps({"revision": 1, "name": "Other"}),
            content_type="application/json",
            **dict(second_headers, HTTP_IDEMPOTENCY_KEY="second-config"),
        ),
        second.post(
            "/api/v1/waitlist/draft/greeting",
            data=json.dumps({"revision": 1}),
            content_type="application/json",
            **dict(second_headers, HTTP_IDEMPOTENCY_KEY="second-greeting"),
        ),
        second.post(
            "/api/v1/waitlist/draft/reply",
            data=json.dumps({"revision": 1, "text": "No access"}),
            content_type="application/json",
            **dict(second_headers, HTTP_IDEMPOTENCY_KEY="second-reply"),
        ),
        second.post(
            "/api/v1/waitlist/draft/join",
            data=json.dumps(
                {
                    "revision": 1,
                    "email": "other@example.com",
                    "consent_version": "consent-v1",
                }
            ),
            content_type="application/json",
            **dict(second_headers, HTTP_IDEMPOTENCY_KEY="second-join"),
        ),
    ]

    for response in responses:
        assert response.status_code == 404
        assert response.json() == {
            "status": "error",
            "message": "waitlist request failed",
            "data": {"code": "waitlist_draft_unavailable"},
        }


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_ENABLED=True,
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_RAILWAY_PROXY_MODE=True,
)
def test_railway_bootstrap_uses_server_issued_browser_identity(monkeypatch):
    cache.clear()
    identities = []
    monkeypatch.setattr("waitlist.api.controllers.admit_bootstrap", identities.append)

    first = Client()
    second = Client()
    assert (
        first.get(
            "/api/v1/waitlist/session",
            HTTP_HOST="testserver",
            HTTP_ORIGIN="http://localhost:3000",
        ).status_code
        == 204
    )
    assert (
        second.get(
            "/api/v1/waitlist/session",
            HTTP_HOST="testserver",
            HTTP_ORIGIN="http://localhost:3000",
        ).status_code
        == 204
    )
    assert "allies_throttle" in first.cookies
    assert "allies_throttle" in second.cookies

    assert (
        first.get(
            "/api/v1/waitlist/session",
            HTTP_HOST="testserver",
            HTTP_ORIGIN="http://localhost:3000",
        ).status_code
        == 204
    )
    assert (
        second.get(
            "/api/v1/waitlist/session",
            HTTP_HOST="testserver",
            HTTP_ORIGIN="http://localhost:3000",
        ).status_code
        == 204
    )
    # Cookie-less issuance uses a bounded network identity; once each browser
    # has a signed throttle cookie, refreshes use separate per-browser keys.
    assert len(identities) == 4
    assert identities[0].startswith("unbound:")
    assert identities[1].startswith("unbound:")
    assert identities[0] == identities[1]
    assert identities[2].startswith("browser:")
    assert identities[3].startswith("browser:")
    assert identities[2] != identities[3]


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_ENABLED=True,
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_RAILWAY_PROXY_MODE=True,
    ALLIES_WAITLIST_BOOTSTRAP_CAPACITY=1,
    ALLIES_WAITLIST_BOOTSTRAP_REFILL_SECONDS=60.0,
)
def test_railway_cookie_less_session_issuance_uses_bootstrap_admission():
    cache.clear()
    client = Client()
    first = client.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    assert first.status_code == 204

    client.cookies.pop("allies_waitlist_capability", None)
    client.cookies.pop("allies_throttle", None)
    blocked = client.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )

    assert blocked.status_code == 429
    assert blocked.json()["data"]["code"] == "throttled"


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_ENABLED=True,
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_RAILWAY_PROXY_MODE=True,
    ALLIES_WAITLIST_CREATION_CAPACITY=2,
    ALLIES_WAITLIST_CREATION_REFILL_SECONDS=60.0,
)
def test_railway_cookie_clearing_hits_distributed_unbound_creation_bucket():
    cache.clear()
    client = Client(enforce_csrf_checks=True)
    successful_creates = 0
    blocked = None

    for index in range(4):
        # Clearing both browser bindings must not mint an unlimited sequence of
        # new capabilities/drafts.  The unbound sentinel is distributed in
        # Redis (or Django's shared test cache) rather than process-local.
        client.cookies.pop("allies_waitlist_capability", None)
        client.cookies.pop("allies_throttle", None)
        session = client.get(
            "/api/v1/waitlist/session",
            HTTP_HOST="testserver",
            HTTP_ORIGIN="http://localhost:3000",
        )
        if session.status_code != 204:
            blocked = session
            break
        # Retain the fresh capability for this draft attempt but clear the
        # server-issued browser identity to model a cookie-clearing attacker.
        client.cookies.pop("allies_throttle", None)
        csrf = client.cookies["csrftoken"].value
        created = client.post(
            "/api/v1/waitlist/draft",
            data="{}",
            content_type="application/json",
            HTTP_HOST="testserver",
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_IDEMPOTENCY_KEY=f"unbound-create-{index}",
        )
        if created.status_code != 200:
            blocked = created
            break
        successful_creates += 1

    assert blocked is not None
    assert blocked.status_code == 429
    assert blocked.json()["data"]["code"] == "throttled"
    assert successful_creates == 2
    assert WaitlistDraft.objects.count() == 2


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_ENABLED=True,
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_RAILWAY_PROXY_MODE=True,
    ALLIES_WAITLIST_CREATION_CAPACITY=1,
    ALLIES_WAITLIST_CREATION_REFILL_SECONDS=60.0,
)
def test_railway_unbound_creation_budget_does_not_block_other_browser():
    cache.clear()
    attacker = Client(enforce_csrf_checks=True)
    session = attacker.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    assert session.status_code == 204
    csrf = attacker.cookies["csrftoken"].value

    # Clearing the issued bindings makes this request consume only the
    # unbound creation budget; it must not affect a browser retaining its
    # server-issued per-browser throttle identity.
    attacker.cookies.pop("allies_waitlist_capability", None)
    attacker.cookies.pop("allies_throttle", None)
    session = attacker.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    assert session.status_code == 204
    csrf = attacker.cookies["csrftoken"].value
    attacker.cookies.pop("allies_throttle", None)
    first = attacker.post(
        "/api/v1/waitlist/draft",
        data="{}",
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="unbound-first",
    )
    assert first.status_code == 200

    legitimate = Client(enforce_csrf_checks=True)
    session = legitimate.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    assert session.status_code == 204
    csrf = legitimate.cookies["csrftoken"].value
    second = legitimate.post(
        "/api/v1/waitlist/draft",
        data="{}",
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="legitimate-create",
    )
    assert second.status_code == 200

    # Session/cookie issuance remains harmless even after the unbound budget
    # is exhausted; only the storage-changing creation is throttled.
    another_session = attacker.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    assert another_session.status_code == 204
