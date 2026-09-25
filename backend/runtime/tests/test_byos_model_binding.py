from __future__ import annotations

from uuid import uuid4

import pytest
from django.test import Client
from django.utils import timezone

from runtime.exceptions import RuntimeValidationError
from runtime.models import (
    ConversationBinding,
    Execution,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.services.claims import claim_next_execution
from runtime.services.profiles import (
    ProfileSeed,
    clear_model_binding,
    effective_model_selection,
    ensure_runtime_profile,
    install_provider_key,
    normalize_model_binding,
    remove_provider_key,
    set_model_binding,
)
from runtime.services.runtime_auth import (
    authenticate_runtime_token,
    issue_runtime_credential,
)


@pytest.fixture
def ready_workspace(db):
    return Workspace.objects.create(
        tenant_ref="byos-binding-tenant",
        fly_app_ref="app",
        volume_ref="volume",
        machine_ref="machine-1",
        machine_generation=1,
        provisioning_phase=WorkspaceProvisioningPhase.IDLE,
        ready_generation=1,
        ready_start_epoch=0,
        ready_boot_id=uuid4(),
        runtime_last_seen_at=timezone.now(),
    )


def _seed():
    return ProfileSeed(
        personality="p",
        provider="openai",
        model="gpt-test",
        first_chat_instruction="i",
        credential_refs={"OPENAI_API_KEY": "vault://tenant/openai"},
    )


def _profile(ready_workspace, ally_ref="ally-a"):
    receipt = ensure_runtime_profile(ready_workspace.id, uuid4(), ally_ref, _seed())
    return RuntimeProfile.objects.get(pk=receipt.profile_id)


def test_binding_set_clear_bumps_generation_and_resolves_selection(
    ready_workspace,
):
    profile = _profile(ready_workspace)
    assert effective_model_selection(profile) == {
        "provider": "openai",
        "model": "gpt-test",
        "options": {},
        "key_refs": {"OPENAI_API_KEY": "vault://tenant/openai"},
    }

    first = set_model_binding(
        profile.id,
        {"provider": "opencode-zen", "model": "gpt-5.2", "reasoning": "high"},
    )
    assert first.generation == 1
    profile.refresh_from_db()
    assert effective_model_selection(profile) == {
        "provider": "opencode-zen",
        "model": "gpt-5.2",
        "options": {"reasoning": "high"},
        "key_refs": {"OPENAI_API_KEY": "vault://tenant/openai"},
    }

    partial = set_model_binding(profile.id, {"model": "glm-5"})
    assert partial.generation == 2
    profile.refresh_from_db()
    assert effective_model_selection(profile)["model"] == "glm-5"
    assert effective_model_selection(profile)["provider"] == "openai"

    cleared = clear_model_binding(profile.id)
    assert cleared.generation == 3
    profile.refresh_from_db()
    assert effective_model_selection(profile) == {
        "provider": "openai",
        "model": "gpt-test",
        "options": {},
        "key_refs": {"OPENAI_API_KEY": "vault://tenant/openai"},
    }


def test_disconnect_restores_seed_keys_without_reprovision(ready_workspace):
    profile = _profile(ready_workspace)
    install_provider_key(profile.id, "OPENCODE_ZEN_API_KEY", "vault://tenant/zen")
    set_model_binding(profile.id, {"provider": "opencode-zen", "model": "gpt-5.2"})
    profile.refresh_from_db()
    assert effective_model_selection(profile)["key_refs"] == {
        "OPENAI_API_KEY": "vault://tenant/openai",
        "OPENCODE_ZEN_API_KEY": "vault://tenant/zen",
    }

    cleared = clear_model_binding(profile.id)
    assert cleared.generation == 3
    profile.refresh_from_db()
    selection = effective_model_selection(profile)
    assert selection["provider"] == "openai"
    assert selection["model"] == "gpt-test"
    assert selection["key_refs"] == {"OPENAI_API_KEY": "vault://tenant/openai"}


def test_binding_key_install_remove_merges_refs(ready_workspace):
    profile = _profile(ready_workspace)
    first = install_provider_key(
        profile.id, "OPENCODE_ZEN_API_KEY", "vault://tenant/zen"
    )
    assert first.generation == 1
    assert first.binding["key_refs"] == {"OPENCODE_ZEN_API_KEY": "vault://tenant/zen"}

    second = install_provider_key(
        profile.id, "opencode-go-api-key", "vault://tenant/go"
    )
    assert second.generation == 2
    assert second.binding["key_refs"] == {
        "OPENCODE_ZEN_API_KEY": "vault://tenant/zen",
        "OPENCODE_GO_API_KEY": "vault://tenant/go",
    }

    removed = remove_provider_key(profile.id, "OPENCODE_ZEN_API_KEY")
    assert removed.generation == 3
    assert removed.binding["key_refs"] == {"OPENCODE_GO_API_KEY": "vault://tenant/go"}


def test_binding_rejects_values_and_unknown_fields(ready_workspace):
    profile = _profile(ready_workspace)
    with pytest.raises(RuntimeValidationError):
        set_model_binding(profile.id, {"provider": "x" * 81})
    with pytest.raises(RuntimeValidationError):
        set_model_binding(profile.id, {"model": "m", "reasoning": "medium"})
    with pytest.raises(RuntimeValidationError):
        set_model_binding(profile.id, {"model": "m", "unknown": 1})
    with pytest.raises(RuntimeValidationError):
        install_provider_key(profile.id, "OPENCODE_ZEN_API_KEY", "sk-live-raw")
    with pytest.raises(RuntimeValidationError):
        install_provider_key(profile.id, "API_SERVER_KEY", "vault://tenant/x")
    with pytest.raises(RuntimeValidationError):
        normalize_model_binding("not-a-binding")
    with pytest.raises(RuntimeValidationError):
        set_model_binding(uuid4(), {"model": "m"})


def test_install_rejects_key_refs_beyond_bound_with_seed(ready_workspace):
    seed_refs = {f"SEED_KEY_{i:02d}": f"vault://tenant/seed-{i}" for i in range(32)}
    receipt = ensure_runtime_profile(
        ready_workspace.id,
        uuid4(),
        "ally-full",
        ProfileSeed(
            personality="p",
            provider="openai",
            model="gpt-test",
            first_chat_instruction="i",
            credential_refs=seed_refs,
        ),
    )
    profile = RuntimeProfile.objects.get(pk=receipt.profile_id)
    with pytest.raises(RuntimeValidationError):
        install_provider_key(profile.id, "OPENCODE_ZEN_API_KEY", "vault://tenant/zen")
    profile.refresh_from_db()
    assert (profile.model_override or {}).get("generation", 0) == 0


def test_claim_carries_effective_selection(ready_workspace):
    profile = RuntimeProfile.objects.create(
        workspace=ready_workspace,
        ally_ref="ally-a",
        hermes_profile_key="ally-a",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=1,
        seed_payload={"model": "gpt-test", "provider": "openai"},
    )
    set_model_binding(profile.id, {"provider": "opencode-zen", "model": "gpt-5.2"})
    execution = Execution.objects.create(  # noqa: F841 - fixture row for the claim
        workspace=ready_workspace,
        profile=profile,
        idempotency_key="turn-1",
        input_payload={"message": "hello", "cloud_conversation_ref": "cloud-1"},
    )
    ConversationBinding.objects.create(
        profile=profile,
        cloud_conversation_ref="cloud-1",
        hermes_session_id=None,
    )
    issued = issue_runtime_credential(ready_workspace.id, "runtime-secret")
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 2)
    assert claim.model == "gpt-5.2"
    assert claim.provider == "opencode-zen"
    assert claim.model_options == {}
    assert claim.binding_generation == 1
    assert claim.binding_key_refs == {}


def _cloud_client(monkeypatch):
    from django.conf import settings

    settings.ALLIES_CLOUD_SERVICE_TOKEN = "test-service-token"
    return Client()


def test_binding_endpoints_roundtrip(monkeypatch, ready_workspace):
    client = _cloud_client(monkeypatch)
    profile = _profile(ready_workspace)
    headers = {"Authorization": "Bearer test-service-token"}

    response = client.put(
        f"/api/v1/internal/profiles/{profile.id}/model-binding",
        data={
            "profile_id": str(profile.id),
            "provider": "opencode-go",
            "model": "glm-5",
        },
        content_type="application/json",
        headers=headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["generation"] == 1

    response = client.put(
        f"/api/v1/internal/profiles/{profile.id}/provider-keys",
        data={
            "profile_id": str(profile.id),
            "env_name": "OPENCODE_GO_API_KEY",
            "reference": "vault://tenant/go",
        },
        content_type="application/json",
        headers=headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["binding"]["key_refs"] == {
        "OPENCODE_GO_API_KEY": "vault://tenant/go"
    }

    response = client.delete(
        f"/api/v1/internal/profiles/{profile.id}/provider-keys/OPENCODE_GO_API_KEY",
        headers=headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["binding"]["key_refs"] == {}

    response = client.delete(
        f"/api/v1/internal/profiles/{profile.id}/model-binding",
        headers=headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["generation"] == 4

    denied = client.put(
        f"/api/v1/internal/profiles/{profile.id}/model-binding",
        data={"profile_id": str(profile.id), "model": "m"},
        content_type="application/json",
        headers={"Authorization": "Bearer wrong"},
    )
    assert denied.status_code == 401

    mismatch = client.put(
        f"/api/v1/internal/profiles/{profile.id}/model-binding",
        data={"profile_id": str(uuid4()), "model": "m"},
        content_type="application/json",
        headers=headers,
    )
    assert mismatch.status_code == 422
