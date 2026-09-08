from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import pytest
from django.core.cache import cache
from django.test import Client, override_settings
from django.utils import timezone
from pydantic import ValidationError

from allies.api.schemas import OnboardingAttemptRequest
from allies.models import (
    Ally,
    AllyBinding,
    BindingStatus,
    OnboardingAttempt,
    ProvisioningOperation,
    ProvisioningStatus,
)
from allies.services.onboarding import begin_onboarding
from auths.config import cookie_name
from auths.exceptions import NativeIdentityUnavailable
from auths.models import SessionClientKind, User
from auths.services.sessions import issue_session
from auths.throttle import ThrottleExceeded, ThrottleUnavailable
from waitlist.exceptions import Throttled
from workspaces.models import Membership, Workspace


@dataclass
class GreetingProvider:
    def generate(self, _request):
        return "Hi, I can help you plan a focused study session. What comes first?"


@pytest.fixture(autouse=True)
def clear_api_cache():
    cache.clear()
    yield
    cache.clear()


def seed():
    return {
        "name": "Mira",
        "job": "Study partner",
        "personality": "Calm, curious, and specific.",
        "appearance": {"catalog_version": "v1", "key": "sunrise"},
    }


def test_seed_schema_normalizes_crlf_before_length_validation():
    payload = seed()
    payload["job"] = "x" * 199 + "\r\n"
    payload["personality"] = " \r\n" + "x" * 3996 + "\r\n "

    parsed = OnboardingAttemptRequest.model_validate(payload)

    assert parsed.job == "x" * 199 + "\n"
    assert parsed.personality == " \n" + "x" * 3996 + "\n "


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("job", "x" * 200 + "\r\n"),
        ("job", "x" * 401),
        ("job", 123),
        ("personality", "x" * 4000 + "\r\n"),
        ("personality", "x" * 8001),
        ("personality", 123),
    ],
)
def test_seed_schema_rejects_canonical_overflow_raw_over_two_x_and_non_string(
    field, value
):
    with pytest.raises(ValidationError):
        OnboardingAttemptRequest.model_validate({**seed(), field: value})


@pytest.mark.parametrize(
    "unsafe",
    [
        "x\ry",
        "x\ty",
        "x\x00y",
        "x\x7fy",
        "x\u0085y",
        "x\u200by",
        "x\u2028y",
        "x\u2029y",
    ],
)
def test_seed_schema_rejects_unsafe_multiline_controls(unsafe):
    with pytest.raises(ValidationError):
        OnboardingAttemptRequest.model_validate({**seed(), "job": unsafe})


def seed_ally(*, workspace, user, ally_id: str, name: str) -> Ally:
    ally = Ally.objects.create(
        id=UUID(ally_id),
        workspace=workspace,
        name=name,
        job="Study partner",
        personality="Calm, curious, and specific.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    binding = AllyBinding.objects.create(ally=ally)
    digest = ally_id.replace("-", "")
    ProvisioningOperation.objects.create(
        binding=binding,
        workspace=workspace,
        user=user,
        api_idempotency_key_digest=(digest * 2)[:64],
        content_fingerprint=(digest[::-1] * 2)[:64],
    )
    return ally


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
)
def test_create_retrieve_and_replay_use_workspace_scoped_contract(monkeypatch):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Personal Workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    other_user = User.objects.create_user()
    other_workspace = Workspace.objects.create(owner=other_user, name="Other Workspace")
    Membership.objects.create(
        workspace=other_workspace, user=other_user, role="owner", status="active"
    )

    client = Client(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")["X-CSRFToken"]
    issued = issue_session(user)
    client.cookies[cookie_name("access")] = issued.access_token
    start = begin_onboarding(
        name="Mira",
        job="Study partner",
        personality="Calm, curious, and specific.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
        browser_binding=client.cookies["csrftoken"].value.encode(),
        generation_identity="test:api",
        provider=GreetingProvider(),
    )
    monkeypatch.setattr("allies.services.creation._enqueue_dispatch", lambda: None)
    payload = {
        **seed(),
        "onboarding_attempt": start.attempt_token,
        "reply": "Help me plan tomorrow.",
    }
    headers = {
        "HTTP_HOST": "testserver",
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_X_CSRFTOKEN": csrf,
        "HTTP_IDEMPOTENCY_KEY": "stable-create-key-1",
    }

    created = client.post(
        f"/api/v1/workspaces/{workspace.id}/allies",
        json.dumps(payload),
        content_type="application/json",
        **headers,
    )
    replay = client.post(
        f"/api/v1/workspaces/{workspace.id}/allies",
        json.dumps(payload),
        content_type="application/json",
        **headers,
    )

    assert created.status_code == 202
    assert replay.status_code == 202
    assert replay.json()["data"]["id"] == created.json()["data"]["id"]
    ally_id = created.json()["data"]["id"]
    loaded = client.get(
        f"/api/v1/workspaces/{workspace.id}/allies/{ally_id}",
        HTTP_HOST="testserver",
    )
    foreign = client.get(
        f"/api/v1/workspaces/{other_workspace.id}/allies/{ally_id}",
        HTTP_HOST="testserver",
    )

    assert loaded.status_code == 200
    assert loaded.json()["data"]["name"] == "Mira"
    assert foreign.status_code == 404
    assert foreign.json()["data"] == {"code": "ally_unavailable"}


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
)
def test_repair_required_state_is_visible_for_bound_ally():
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Personal Workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    ally = seed_ally(
        workspace=workspace,
        user=user,
        ally_id="00000000-0000-4000-8000-000000000004",
        name="Repairable",
    )
    binding = AllyBinding.objects.get(ally=ally)
    binding.status = BindingStatus.BOUND
    binding.receipt_digest = "a" * 64
    binding.save(update_fields=("status", "receipt_digest", "updated_at"))
    operation = ProvisioningOperation.objects.get(binding=binding)
    operation.status = ProvisioningStatus.REPAIR_REQUIRED
    operation.safe_error_code = "onboarding_handoff_repair_required"
    operation.save(update_fields=("status", "safe_error_code", "updated_at"))

    client = Client()
    issued = issue_session(user)
    client.cookies[cookie_name("access")] = issued.access_token
    response = client.get(
        f"/api/v1/workspaces/{workspace.id}/allies/{ally.id}",
        HTTP_HOST="testserver",
    )

    assert response.status_code == 200
    assert response.json()["data"]["provisioning_state"] == "repair_required"
    assert response.json()["data"]["retryable"] is False


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
)
def test_onboarding_attempt_route_requires_trusted_csrf_bound_origin():
    client = Client(enforce_csrf_checks=True)
    response = client.post(
        "/api/v1/onboarding/attempts",
        json.dumps(seed()),
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="https://evil.example",
    )

    assert response.status_code == 403
    assert response.json()["data"] == {"code": "origin_rejected"}


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
    ALLIES_AUTH_NATIVE_ENABLED=True,
    ALLIES_AUTH_NATIVE_ONBOARDING_LIMIT=100,
    ALLIES_AUTH_NATIVE_GLOBAL_LIMIT=1000,
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
)
@pytest.mark.parametrize(
    "browser_signal",
    [
        ({"HTTP_ORIGIN": "http://localhost:3000"}, "csrf_rejected"),
        (
            {"HTTP_REFERER": "http://localhost:3000/onboarding"},
            "csrf_rejected",
        ),
        ({"HTTP_X_CSRFTOKEN": "csrf-token"}, "origin_rejected"),
        ({"HTTP_COOKIE": "unrelated=1"}, "origin_rejected"),
        ({"HTTP_AUTHORIZATION": "Bearer native-token"}, "origin_rejected"),
    ],
)
def test_native_onboarding_does_not_fallback_for_browser_signals(
    monkeypatch, browser_signal
):
    monkeypatch.setattr(
        "allies.services.onboarding.get_provider",
        lambda: pytest.fail("browser-marked requests must not use native"),
    )
    headers, code = browser_signal
    response = Client().post(
        "/api/v1/onboarding/attempts",
        json.dumps(seed()),
        content_type="application/json",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.73",
        **headers,
    )

    assert response.status_code == 403
    assert response.json()["data"] == {"code": code}
    assert OnboardingAttempt.objects.count() == 0


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
    ALLIES_AUTH_NATIVE_ENABLED=True,
    ALLIES_AUTH_NATIVE_ONBOARDING_LIMIT=100,
    ALLIES_AUTH_NATIVE_GLOBAL_LIMIT=1000,
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
)
def test_browser_onboarding_keeps_trusted_origin_and_csrf_contract(monkeypatch):
    monkeypatch.setattr("allies.services.onboarding.get_provider", GreetingProvider)
    client = Client(enforce_csrf_checks=True)
    csrf_response = client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")
    csrf = csrf_response["X-CSRFToken"]

    response = client.post(
        "/api/v1/onboarding/attempts",
        json.dumps(seed()),
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_X_CSRFTOKEN=csrf,
    )

    assert response.status_code == 200
    assert set(response.json()["data"]) == {"attempt_token", "greeting"}
    assert response["Cache-Control"] == "no-store"


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_AUTH_NATIVE_ENABLED=True,
    ALLIES_AUTH_NATIVE_ONBOARDING_LIMIT=100,
    ALLIES_AUTH_NATIVE_GLOBAL_LIMIT=1000,
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
)
def test_native_onboarding_attempt_requires_no_browser_state_and_is_not_cached(
    monkeypatch,
):
    monkeypatch.setattr("allies.services.onboarding.get_provider", GreetingProvider)
    client = Client()

    response = client.post(
        "/api/v1/onboarding/attempts",
        json.dumps(seed()),
        content_type="application/json",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.73",
    )

    assert response.status_code == 200
    assert set(response.json()["data"]) == {"attempt_token", "greeting"}
    assert response["Cache-Control"] == "no-store"
    assert response["Pragma"] == "no-cache"
    assert response.cookies == {}


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_AUTH_NATIVE_ENABLED=True,
    ALLIES_AUTH_NATIVE_ONBOARDING_LIMIT=100,
    ALLIES_AUTH_NATIVE_GLOBAL_LIMIT=1000,
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
)
def test_native_onboarding_can_continue_to_native_workspace_create(
    monkeypatch,
):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Personal Workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    monkeypatch.setattr("allies.services.onboarding.get_provider", GreetingProvider)
    monkeypatch.setattr("allies.services.creation._enqueue_dispatch", lambda: None)
    client = Client()
    preview = client.post(
        "/api/v1/onboarding/attempts",
        json.dumps(seed()),
        content_type="application/json",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.73",
    )
    issued = issue_session(user, client_kind=SessionClientKind.NATIVE)
    payload = {
        **seed(),
        "onboarding_attempt": preview.json()["data"]["attempt_token"],
        "reply": "Help me plan tomorrow.",
    }
    headers = {
        "HTTP_HOST": "testserver",
        "HTTP_AUTHORIZATION": f"Bearer {issued.access_token}",
        "HTTP_IDEMPOTENCY_KEY": "native-create-key-1",
        "REMOTE_ADDR": "198.51.100.73",
    }

    created = client.post(
        f"/api/v1/workspaces/{workspace.id}/allies",
        json.dumps(payload),
        content_type="application/json",
        **headers,
    )
    replay = client.post(
        f"/api/v1/workspaces/{workspace.id}/allies",
        json.dumps(payload),
        content_type="application/json",
        **headers,
    )

    assert preview.status_code == 200
    assert created.status_code == 202
    assert replay.status_code == 202
    assert replay.json()["data"]["id"] == created.json()["data"]["id"]
    assert OnboardingAttempt.objects.get().consumed_at is not None


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_AUTH_NATIVE_ENABLED=True,
    ALLIES_AUTH_NATIVE_ONBOARDING_LIMIT=100,
    ALLIES_AUTH_NATIVE_GLOBAL_LIMIT=1000,
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
)
@pytest.mark.parametrize(
    "hybrid_header",
    [
        {"HTTP_ORIGIN": "http://localhost:3000"},
        {"HTTP_REFERER": "http://localhost:3000/onboarding"},
        {"HTTP_X_CSRFTOKEN": "csrf-token"},
        {"HTTP_COOKIE": "unrelated=1"},
    ],
)
def test_native_create_rejects_browser_hybrid_signals(monkeypatch, hybrid_header):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Personal Workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    monkeypatch.setattr("allies.services.onboarding.get_provider", GreetingProvider)
    client = Client()
    preview = client.post(
        "/api/v1/onboarding/attempts",
        json.dumps(seed()),
        content_type="application/json",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.73",
    )
    issued = issue_session(user, client_kind=SessionClientKind.NATIVE)
    response = client.post(
        f"/api/v1/workspaces/{workspace.id}/allies",
        json.dumps(
            {
                **seed(),
                "onboarding_attempt": preview.json()["data"]["attempt_token"],
                "reply": "Help me plan tomorrow.",
            }
        ),
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_AUTHORIZATION=f"Bearer {issued.access_token}",
        HTTP_IDEMPOTENCY_KEY="native-hybrid-key-1",
        REMOTE_ADDR="198.51.100.73",
        **hybrid_header,
    )

    assert response.status_code == 403
    assert response.json()["data"] == {"code": "csrf_rejected"}
    assert Ally.objects.count() == 0


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_AUTH_NATIVE_ENABLED=True,
    ALLIES_AUTH_NATIVE_ONBOARDING_LIMIT=100,
    ALLIES_AUTH_NATIVE_GLOBAL_LIMIT=1000,
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
)
@pytest.mark.parametrize("token_kind", ["browser", "invalid"])
def test_native_create_rejects_non_native_bearers(monkeypatch, token_kind):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Personal Workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    monkeypatch.setattr("allies.services.onboarding.get_provider", GreetingProvider)
    client = Client()
    preview = client.post(
        "/api/v1/onboarding/attempts",
        json.dumps(seed()),
        content_type="application/json",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.73",
    )
    bearer = (
        issue_session(user).access_token
        if token_kind == "browser"
        else "invalid-native-access"
    )
    response = client.post(
        f"/api/v1/workspaces/{workspace.id}/allies",
        json.dumps(
            {
                **seed(),
                "onboarding_attempt": preview.json()["data"]["attempt_token"],
                "reply": "Help me plan tomorrow.",
            }
        ),
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_AUTHORIZATION=f"Bearer {bearer}",
        HTTP_IDEMPOTENCY_KEY="native-invalid-key-1",
        REMOTE_ADDR="198.51.100.73",
    )

    assert response.status_code == 401
    assert response.json()["data"] == {"code": "session_invalid"}
    assert Ally.objects.count() == 0


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_AUTH_NATIVE_ENABLED=True,
    ALLIES_AUTH_NATIVE_ONBOARDING_LIMIT=100,
    ALLIES_AUTH_NATIVE_GLOBAL_LIMIT=1000,
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
)
def test_native_onboarding_requester_throttle_maps_to_429_without_generation(
    monkeypatch,
):
    monkeypatch.setattr(
        "allies.api.controllers.check_native_rate_limit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ThrottleExceeded()),
    )
    monkeypatch.setattr(
        "allies.services.onboarding.get_provider",
        lambda: pytest.fail("provider must not run after requester throttling"),
    )
    response = Client().post(
        "/api/v1/onboarding/attempts",
        json.dumps(seed()),
        content_type="application/json",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.73",
    )

    assert response.status_code == 429
    assert response.json()["data"] == {"code": "throttled"}
    assert OnboardingAttempt.objects.count() == 0


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_AUTH_NATIVE_ENABLED=True,
    ALLIES_AUTH_NATIVE_ONBOARDING_LIMIT=100,
    ALLIES_AUTH_NATIVE_GLOBAL_LIMIT=1000,
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
)
@pytest.mark.parametrize(
    "failure",
    [ThrottleUnavailable(), NativeIdentityUnavailable()],
)
def test_native_onboarding_admission_failures_map_to_503(monkeypatch, failure):
    monkeypatch.setattr(
        "allies.api.controllers.check_native_rate_limit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )
    response = Client().post(
        "/api/v1/onboarding/attempts",
        json.dumps(seed()),
        content_type="application/json",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.73",
    )

    assert response.status_code == 503
    assert response.json()["data"] == {"code": "onboarding_unavailable"}
    assert OnboardingAttempt.objects.count() == 0


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_AUTH_NATIVE_ENABLED=True,
    ALLIES_AUTH_NATIVE_ONBOARDING_LIMIT=100,
    ALLIES_AUTH_NATIVE_GLOBAL_LIMIT=1000,
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
)
def test_generation_throttle_maps_to_429(monkeypatch):
    monkeypatch.setattr(
        "allies.api.controllers.check_native_rate_limit",
        lambda *_args, **_kwargs: "198.51.100.0/24",
    )
    monkeypatch.setattr(
        "allies.api.controllers.begin_onboarding",
        lambda **_kwargs: (_ for _ in ()).throw(Throttled()),
    )
    response = Client().post(
        "/api/v1/onboarding/attempts",
        json.dumps(seed()),
        content_type="application/json",
        HTTP_HOST="testserver",
        REMOTE_ADDR="198.51.100.73",
    )

    assert response.status_code == 429
    assert response.json()["data"] == {"code": "throttled"}


@pytest.mark.django_db
def test_retrieve_requires_a_valid_session():
    client = Client()
    response = client.get(
        "/api/v1/workspaces/00000000-0000-4000-8000-000000000001/allies/00000000-0000-4000-8000-000000000002",
        HTTP_HOST="testserver",
    )

    assert response.status_code == 401
    assert response.json()["data"] == {"code": "session_invalid"}


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
)
def test_list_returns_empty_for_an_authorized_workspace():
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Personal Workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    client = Client()
    issued = issue_session(user)
    client.cookies[cookie_name("access")] = issued.access_token

    response = client.get(
        f"/api/v1/workspaces/{workspace.id}/allies",
        HTTP_HOST="testserver",
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"allies": []}


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
)
def test_list_orders_newest_then_uuid_and_hides_foreign_or_inactive_scope():
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Personal Workspace")
    membership = Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    foreign_user = User.objects.create_user()
    foreign_workspace = Workspace.objects.create(owner=foreign_user, name="Other")
    Membership.objects.create(
        workspace=foreign_workspace,
        user=foreign_user,
        role="owner",
        status="active",
    )
    older = seed_ally(
        workspace=workspace,
        user=user,
        ally_id="00000000-0000-4000-8000-000000000001",
        name="Older",
    )
    tie_low = seed_ally(
        workspace=workspace,
        user=user,
        ally_id="00000000-0000-4000-8000-000000000002",
        name="Tie low",
    )
    tie_high = seed_ally(
        workspace=workspace,
        user=user,
        ally_id="00000000-0000-4000-8000-000000000003",
        name="Tie high",
    )
    stamp = timezone.now()
    Ally.objects.filter(pk=older.pk).update(created_at=stamp - timedelta(seconds=1))
    Ally.objects.filter(pk__in=[tie_low.pk, tie_high.pk]).update(created_at=stamp)

    client = Client()
    issued = issue_session(user)
    client.cookies[cookie_name("access")] = issued.access_token
    path = f"/api/v1/workspaces/{workspace.id}/allies"

    response = client.get(path, HTTP_HOST="testserver")
    foreign = client.get(
        f"/api/v1/workspaces/{foreign_workspace.id}/allies",
        HTTP_HOST="testserver",
    )
    membership.status = "inactive"
    membership.save(update_fields=("status", "updated_at"))
    inactive = client.get(path, HTTP_HOST="testserver")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]["allies"]] == [
        str(tie_high.pk),
        str(tie_low.pk),
        str(older.pk),
    ]
    assert response.json()["data"]["allies"][0]["name"] == "Tie high"
    assert foreign.status_code == 404
    assert foreign.json()["data"] == {"code": "ally_unavailable"}
    assert inactive.status_code == 404
    assert inactive.json()["data"] == {"code": "ally_unavailable"}


@pytest.mark.django_db
def test_list_requires_a_valid_session():
    client = Client()
    response = client.get(
        "/api/v1/workspaces/00000000-0000-4000-8000-000000000001/allies",
        HTTP_HOST="testserver",
    )

    assert response.status_code == 401
    assert response.json()["data"] == {"code": "session_invalid"}
