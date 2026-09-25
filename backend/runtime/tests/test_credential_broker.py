from __future__ import annotations

import io
import json
import logging
from urllib.error import HTTPError, URLError
from uuid import uuid4

import pytest
from django.test import Client
from django.utils import timezone

from runtime.models import RuntimeProfile, Workspace, WorkspaceProvisioningPhase
from runtime.services import credential_broker
from runtime.services.profiles import (
    ProfileSeed,
    ensure_runtime_profile,
    install_provider_key,
    set_model_binding,
)
from runtime.services.runtime_auth import issue_runtime_credential

REF = f"allies-key://model-keys/{uuid4()}"
SECRET = "sk-tenant-secret-value-0123456789"


def _workspace(tenant_ref):
    return Workspace.objects.create(
        tenant_ref=tenant_ref,
        fly_app_ref=f"app-{tenant_ref}",
        volume_ref="volume",
        machine_ref="machine-1",
        machine_generation=1,
        provisioning_phase=WorkspaceProvisioningPhase.IDLE,
        ready_generation=1,
        ready_start_epoch=0,
        ready_boot_id=uuid4(),
        runtime_last_seen_at=timezone.now(),
    )


def _profile(workspace, credential_refs=None):
    receipt = ensure_runtime_profile(
        workspace.id,
        uuid4(),
        "ally-a",
        ProfileSeed(
            personality="p",
            provider="openai",
            model="gpt-test",
            first_chat_instruction="i",
            credential_refs=credential_refs
            or {"OPENAI_API_KEY": "file:///run/secrets/openai"},
        ),
    )
    return RuntimeProfile.objects.get(pk=receipt.profile_id)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Opener:
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return _Response(self.outcome)


@pytest.fixture
def cloud(monkeypatch, settings):
    settings.ALLIES_CLOUD_URL = "https://cloud.example"
    settings.ALLIES_CLOUD_CREDENTIAL_TOKEN = "c" * 40
    opener = _Opener(json.dumps({"value": SECRET}).encode())
    monkeypatch.setattr(credential_broker, "build_opener", lambda *_: opener)
    return opener


def _post(workspace, reference=REF):
    token = f"runtime-{uuid4()}"
    issue_runtime_credential(workspace.id, token)
    return Client().post(
        "/api/v1/runtime/credentials/resolve",
        data={"reference": reference},
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_bound_ref_resolves_through_cloud_without_leaking(db, cloud, caplog):
    workspace = _workspace("tenant-a")
    install_provider_key(_profile(workspace).id, "OPENCODE_ZEN_API_KEY", REF)

    with caplog.at_level(logging.DEBUG):
        response = _post(workspace)

    assert response.status_code == 200, response.content
    assert response.json() == {"value": SECRET}
    assert response["Cache-Control"] == "no-store"
    sent = json.loads(cloud.requests[0].data)
    assert sent == {"version": 1, "workspace_id": "tenant-a", "reference": REF}
    assert cloud.requests[0].get_header("Authorization") == f"Bearer {'c' * 40}"
    assert SECRET not in caplog.text


def test_binding_set_with_key_refs_is_resolvable(db, cloud):
    workspace = _workspace("tenant-a")
    set_model_binding(
        _profile(workspace).id,
        {"provider": "opencode-zen", "key_refs": {"OPENCODE_ZEN_API_KEY": REF}},
    )

    assert _post(workspace).status_code == 200


def test_ref_bound_only_in_another_workspace_is_not_asked(db, cloud):
    mine = _workspace("tenant-a")
    _profile(mine)
    other = _workspace("tenant-b")
    install_provider_key(_profile(other).id, "OPENCODE_ZEN_API_KEY", REF)

    response = _post(mine)

    assert response.status_code == 404
    assert cloud.requests == []


@pytest.mark.parametrize(
    "reference",
    ["file:///run/secrets/openai", "allies-key://model-keys/not-a-uuid", "x" * 200],
)
def test_non_broker_refs_are_rejected(db, cloud, reference):
    workspace = _workspace("tenant-a")
    _profile(workspace)

    assert _post(workspace, reference).status_code == 422
    assert cloud.requests == []


def test_invalid_runtime_token_is_rejected(db, cloud):
    response = Client().post(
        "/api/v1/runtime/credentials/resolve",
        data={"reference": REF},
        content_type="application/json",
        headers={"Authorization": "Bearer nope"},
    )

    assert response.status_code == 401
    assert cloud.requests == []


@pytest.mark.parametrize(
    ("outcome", "status"),
    [
        (HTTPError("u", 404, "gone", {}, None), 404),
        (HTTPError("u", 503, "down", {}, None), 409),
        (URLError("unreachable"), 409),
        (b'{"value": ""}', 409),
        (b"x" * 5000, 409),
    ],
)
def test_cloud_failures_map_to_redacted_errors(db, cloud, outcome, status):
    cloud.outcome = outcome
    workspace = _workspace("tenant-a")
    install_provider_key(_profile(workspace).id, "OPENCODE_ZEN_API_KEY", REF)

    response = _post(workspace)

    assert response.status_code == status
    assert SECRET not in response.content.decode()


def test_missing_broker_token_fails_closed(db, cloud, settings):
    settings.ALLIES_CLOUD_CREDENTIAL_TOKEN = None
    workspace = _workspace("tenant-a")
    install_provider_key(_profile(workspace).id, "OPENCODE_ZEN_API_KEY", REF)

    assert _post(workspace).status_code == 409
    assert cloud.requests == []


def test_binding_endpoint_accepts_key_refs_atomically(db, settings):
    settings.ALLIES_CLOUD_SERVICE_TOKEN = "test-service-token"
    profile = _profile(_workspace("tenant-a"))

    response = Client().put(
        f"/api/v1/internal/profiles/{profile.id}/model-binding",
        data={
            "profile_id": str(profile.id),
            "provider": "opencode-zen",
            "model": "gpt-5.2",
            "key_refs": {"OPENCODE_ZEN_API_KEY": REF},
        },
        content_type="application/json",
        headers={"Authorization": "Bearer test-service-token"},
    )

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["generation"] == 1
    assert body["binding"]["key_refs"] == {"OPENCODE_ZEN_API_KEY": REF}


def test_seed_held_broker_ref_resolves(db, cloud):
    workspace = _workspace("tenant-a")
    _profile(workspace, {"OPENCODE_ZEN_API_KEY": REF})

    assert _post(workspace).status_code == 200


def test_uppercase_ref_accepted_by_binding_also_resolves(db, cloud):
    workspace = _workspace("tenant-a")
    upper = REF.replace("allies-key", "ALLIES-KEY").upper()
    install_provider_key(_profile(workspace).id, "OPENCODE_ZEN_API_KEY", upper)

    assert _post(workspace, upper).status_code == 200
