from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

import pytest
from django.test import Client

from runtime.models import (
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.services.profiles import accept_materialization_receipt
from runtime.services.runtime_auth import (
    authenticate_runtime_token,
    issue_runtime_credential,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "contracts"
    / "foundry-profile-provisioning-v1.json"
)


@pytest.fixture
def contract():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def service_token(settings):
    settings.ALLIES_CLOUD_SERVICE_TOKEN = "test-service-token"
    return settings.ALLIES_CLOUD_SERVICE_TOKEN


@pytest.fixture
def workspace(db, contract):
    request = contract["request"]
    return Workspace.objects.create(
        tenant_ref=request["workspace_id"],
        fly_app_ref="app",
        volume_ref="volume",
        machine_ref="machine",
        machine_generation=1,
        provisioning_phase=WorkspaceProvisioningPhase.IDLE,
    )


def post_profile(payload, *, token="test-service-token"):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return Client().post(
        "/api/v1/internal/profile-provisioning",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers,
    )


def test_fixture_request_creates_pending_profile_without_private_receipt_fields(
    workspace, contract, service_token
):
    response = post_profile(contract["request"])

    assert response.status_code == 200, response.content
    receipt = response.json()
    assert set(receipt) == {
        "version",
        "binding_id",
        "operation_id",
        "request_fingerprint",
        "status",
        "evidence_digest",
    }
    assert receipt["version"] == contract["receipt"]["version"]
    assert receipt["binding_id"] == contract["request"]["binding_id"]
    assert receipt["operation_id"] == contract["request"]["operation_id"]
    assert receipt["request_fingerprint"] == contract["request"]["request_fingerprint"]
    assert receipt["status"] == "pending"
    assert receipt["evidence_digest"] == contract["receipt"]["evidence_digest"]
    assert re.fullmatch(r"[0-9a-f]{64}", receipt["evidence_digest"])
    assert "profile_id" not in receipt
    assert "hermes_profile_key" not in receipt
    assert "seed_payload" not in receipt
    assert "credentials" not in receipt

    profile = RuntimeProfile.objects.get(ally_ref=contract["request"]["ally_ref"])
    assert profile.lifecycle_state == RuntimeProfileLifecycleState.PENDING
    assert profile.seed_payload["personality"] == contract["request"]["personality"]
    assert contract["request"]["job"] in profile.seed_payload["first_chat_instruction"]


def test_provisioning_seed_uses_deployment_settings(
    workspace, contract, service_token, settings
):
    settings.PROFILE_PROVISIONING_PROVIDER = "test-provider"
    settings.PROFILE_PROVISIONING_MODEL = "test-model"
    settings.PROFILE_PROVISIONING_BASE_URL = "https://provider.example/v1"
    settings.PROFILE_PROVISIONING_CREDENTIAL_REFS = {
        "PROVIDER_TOKEN": "file:///run/secrets/provider-token"
    }

    response = post_profile(contract["request"])

    assert response.status_code == 200
    profile = RuntimeProfile.objects.get(workspace=workspace)
    assert profile.seed_payload["provider"] == "test-provider"
    assert profile.seed_payload["model"] == "test-model"
    assert profile.seed_payload["base_url"] == "https://provider.example/v1"
    assert profile.seed_payload["credential_refs"] == {
        "PROVIDER_TOKEN": "file:///run/secrets/provider-token"
    }


def test_exact_replay_is_idempotent_and_changed_seed_does_not_mutate(
    workspace, contract, service_token
):
    first = post_profile(contract["request"])
    replay = post_profile(contract["request"])

    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert RuntimeProfile.objects.filter(workspace=workspace).count() == 1

    changed = dict(contract["request"])
    changed["personality"] += " Changed."
    conflict = post_profile(changed)

    assert conflict.status_code == 409
    assert conflict.json()["code"] == "CONFLICT"
    assert changed["personality"] not in conflict.content.decode()
    assert RuntimeProfile.objects.filter(workspace=workspace).count() == 1
    profile = RuntimeProfile.objects.get(workspace=workspace)
    assert profile.seed_payload["personality"] == contract["request"]["personality"]


def test_active_profile_state_is_returned_truthfully(
    workspace, contract, service_token
):
    pending = post_profile(contract["request"])
    assert pending.status_code == 200
    profile = RuntimeProfile.objects.get(workspace=workspace)
    issued = issue_runtime_credential(workspace.id, "runtime-test-token")
    context = authenticate_runtime_token(issued.raw_token)
    accept_materialization_receipt(
        context,
        profile.id,
        uuid4(),
        profile.lifecycle_epoch,
        workspace.machine_generation,
        profile.seed_fingerprint,
        "created",
    )

    active = post_profile(contract["request"])

    assert active.status_code == 200
    assert active.json()["status"] == "active"
    assert active.json()["evidence_digest"] == pending.json()["evidence_digest"]


@pytest.mark.parametrize("token", [None, "wrong-service-token", "ÿ"])
def test_missing_or_invalid_service_bearer_is_the_same_401(
    workspace, contract, service_token, token
):
    response = post_profile(contract["request"], token=token)

    assert response.status_code == 401
    assert response.json() == {
        "code": "INVALID_CREDENTIAL",
        "message": "request is not authorized",
    }
    assert service_token not in response.content.decode()


def test_missing_workspace_fails_closed_without_echoing_identity(
    db, contract, service_token
):
    response = post_profile(contract["request"])

    assert response.status_code == 422
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "request is invalid",
    }
    assert contract["request"]["workspace_id"] not in response.content.decode()


@pytest.mark.parametrize("version", [0, 2])
def test_unknown_contract_version_is_rejected_without_mutation(
    workspace, contract, service_token, version
):
    payload = dict(contract["request"])
    payload["version"] = version

    response = post_profile(payload)

    assert response.status_code == 422
    assert RuntimeProfile.objects.count() == 0


def test_malformed_extra_fields_are_rejected(db, contract, service_token):
    payload = dict(contract["request"])
    payload["appearance"] = {"key": "sunrise"}

    response = post_profile(payload)

    assert response.status_code == 422
    assert RuntimeProfile.objects.count() == 0


def test_fixture_uses_public_opaque_ids_only(contract):
    assert set(contract) == {"request", "receipt"}
    for key in ("workspace_id", "binding_id", "ally_ref", "operation_id"):
        value = contract["request"][key]
        assert isinstance(value, str)
        assert value and not any(character.isspace() for character in value)
