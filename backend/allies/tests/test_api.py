from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import pytest
from auths.config import cookie_name
from auths.models import User
from auths.services.sessions import issue_session
from django.test import Client, override_settings
from django.utils import timezone
from workspaces.models import Membership, Workspace

from allies.models import (
    Ally,
    AllyBinding,
    BindingStatus,
    ProvisioningOperation,
    ProvisioningStatus,
)
from allies.services.onboarding import begin_onboarding


@dataclass
class GreetingProvider:
    def generate(self, _request):
        return "Hi, I can help you plan a focused study session. What comes first?"


def seed():
    return {
        "name": "Mira",
        "job": "Study partner",
        "personality": "Calm, curious, and specific.",
        "appearance": {"catalog_version": "v1", "key": "sunrise"},
    }


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
