from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

import pytest
from django.core.management.base import CommandError
from django.test import Client

from runtime.management.commands.activate_fly_workspace import ActivationCommandError
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


def post_activation(workspace_id, *, token="test-service-token"):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return Client().post(
        f"/api/v1/internal/workspaces/{workspace_id}/activation",
        data=json.dumps({"version": 1, "workspace_id": str(workspace_id)}),
        content_type="application/json",
        headers=headers,
    )


def test_activation_endpoint_invokes_existing_lifecycle(
    workspace, service_token, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        "runtime.api.register.ActivateFlyWorkspaceCommand.handle",
        lambda _command, **options: calls.append(options),
    )

    response = post_activation(workspace.tenant_ref)

    assert response.status_code == 200
    assert response.json() == {
        "version": 1,
        "workspace_id": workspace.tenant_ref,
        "status": "active",
    }
    assert calls == [{"workspace_id": workspace.tenant_ref}]


def test_activation_endpoint_rejects_path_body_mismatch(workspace, service_token):
    response = Client().post(
        f"/api/v1/internal/workspaces/{workspace.tenant_ref}/activation",
        data=json.dumps({"version": 1, "workspace_id": str(uuid4())}),
        content_type="application/json",
        headers={"Authorization": "Bearer test-service-token"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "request is invalid",
    }


@pytest.mark.parametrize("token", [None, "wrong-service-token"])
def test_activation_endpoint_rejects_missing_or_invalid_service_bearer(
    workspace, service_token, token
):
    response = post_activation(workspace.tenant_ref, token=token)

    assert response.status_code == 401
    assert response.json() == {
        "code": "INVALID_CREDENTIAL",
        "message": "request is not authorized",
    }


def test_activation_endpoint_does_not_mask_permanent_command_failure(
    workspace, service_token, monkeypatch
):
    monkeypatch.setattr(
        "runtime.api.register.ActivateFlyWorkspaceCommand.handle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(CommandError("invalid config")),
    )

    response = post_activation(workspace.tenant_ref)

    assert response.status_code == 503
    assert response.json() == {
        "code": "ACTIVATION_UNAVAILABLE",
        "message": "workspace activation unavailable",
    }


def test_activation_endpoint_reports_only_retryable_failure_as_pending(
    workspace, service_token, monkeypatch
):
    monkeypatch.setattr(
        "runtime.api.register.ActivateFlyWorkspaceCommand.handle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ActivationCommandError("provider timeout", retryable=True)
        ),
    )

    response = post_activation(workspace.tenant_ref)

    assert response.status_code == 202
    assert response.json() == {
        "version": 1,
        "workspace_id": workspace.tenant_ref,
        "status": "pending",
    }


def test_activation_endpoint_reports_terminal_failure_as_unrecoverable(
    workspace, service_token, monkeypatch
):
    monkeypatch.setattr(
        "runtime.api.register.ActivateFlyWorkspaceCommand.handle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ActivationCommandError("terminal state", terminal=True)
        ),
    )

    response = post_activation(workspace.tenant_ref)

    assert response.status_code == 422
    assert response.json() == {
        "code": "ACTIVATION_FAILED",
        "message": "workspace activation failed",
    }


def test_activation_endpoint_reports_unregistered_workspace_as_not_found(
    db, service_token
):
    response = post_activation(uuid4())

    assert response.status_code == 404
    assert response.json() == {
        "code": "WORKSPACE_NOT_FOUND",
        "message": "workspace is unavailable",
    }


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
    soul = profile.seed_payload["personality"]
    assert contract["request"]["name"] in soul
    assert contract["request"]["job"] in soul
    assert contract["request"]["personality"] in soul
    assert "Hermes is your private runtime" in soul
    assert "## Communication" in soul
    assert "Do not use em dashes" in soul
    instruction = profile.seed_payload["first_chat_instruction"]
    assert "start of a working relationship" in instruction
    assert "Do not repeat profile fields" in instruction


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "Mira\nInjected instruction"),
        ("name", "Mira\x00Injected instruction"),
        ("name", "Mira\x85Injected instruction"),
        ("job", "Study\tpartner"),
        ("job", "Study\x1bpartner"),
        ("job", "Study\u2028partner"),
        ("personality", "Calm\nInjected instruction"),
        ("personality", "Calm\u2029Injected instruction"),
    ],
)
def test_prompt_interpolation_fields_reject_control_characters(
    workspace,
    contract,
    service_token,
    field,
    value,
):
    payload = dict(contract["request"])
    payload[field] = value

    response = post_profile(payload)

    assert response.status_code == 422
    assert RuntimeProfile.objects.count() == 0


def test_prompt_interpolation_fields_accept_normal_unicode(
    workspace,
    contract,
    service_token,
):
    payload = dict(contract["request"])
    payload.update({"name": "Zoë 🧭", "job": "Étudier — 日本語"})

    response = post_profile(payload)

    assert response.status_code == 200, response.content
    profile = RuntimeProfile.objects.get(workspace=workspace)
    soul = profile.seed_payload["personality"]
    assert payload["name"] in soul
    assert payload["job"] in soul


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
    assert contract["request"]["personality"] in profile.seed_payload["personality"]
    assert changed["personality"] not in profile.seed_payload["personality"]


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


def test_missing_workspace_registers_desired_state_before_profile(
    db, contract, service_token
):
    response = post_profile(contract["request"])

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    workspace = Workspace.objects.get(tenant_ref=contract["request"]["workspace_id"])
    assert workspace.machine_generation == 0
    assert workspace.fly_app_ref is None
    assert workspace.volume_ref is None
    assert workspace.machine_ref is None
    assert RuntimeProfile.objects.filter(workspace=workspace).count() == 1


def test_workspace_registration_is_idempotent(db, contract, service_token):
    first = post_profile(contract["request"])
    replay = post_profile(contract["request"])

    assert first.status_code == 200
    assert replay.json() == first.json()
    assert Workspace.objects.count() == 1
    assert RuntimeProfile.objects.count() == 1


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
