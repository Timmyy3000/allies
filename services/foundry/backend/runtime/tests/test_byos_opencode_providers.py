from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from runtime.exceptions import RuntimeConflictError, RuntimeValidationError
from runtime.models import RuntimeProfile, Workspace, WorkspaceProvisioningPhase
from runtime.services.profiles import ProfileSeed, ensure_runtime_profile


@pytest.fixture
def ready_workspace(db):
    return Workspace.objects.create(
        tenant_ref="byos-opencode-tenant",
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


def _zen_seed(**overrides):
    values = {
        "personality": "p",
        "provider": "opencode-zen",
        "model": "gpt-5.2",
        "first_chat_instruction": "i",
        "credential_refs": {"OPENCODE_ZEN_API_KEY": "vault://tenant/zen"},
    }
    values.update(overrides)
    return ProfileSeed(**values)


def test_opencode_seed_accepts_tenant_ref_fanout(ready_workspace):
    for ally_ref in ("ally-a", "ally-b"):
        receipt = ensure_runtime_profile(
            ready_workspace.id, uuid4(), ally_ref, _zen_seed()
        )
        assert receipt.seed_fingerprint

    profiles = RuntimeProfile.objects.filter(workspace=ready_workspace).order_by(
        "ally_ref"
    )
    assert [profile.ally_ref for profile in profiles] == ["ally-a", "ally-b"]
    for profile in profiles:
        assert profile.seed_payload["provider"] == "opencode-zen"
        assert profile.seed_payload["credential_refs"] == {
            "OPENCODE_ZEN_API_KEY": "vault://tenant/zen"
        }


def test_opencode_ref_rotation_conflicts_until_reprovision(ready_workspace):
    profile_id = uuid4()
    ensure_runtime_profile(ready_workspace.id, profile_id, "ally-a", _zen_seed())
    with pytest.raises(RuntimeConflictError):
        ensure_runtime_profile(
            ready_workspace.id,
            profile_id,
            "ally-a",
            _zen_seed(
                credential_refs={"OPENCODE_ZEN_API_KEY": "vault://tenant/zen-v2"}
            ),
        )


def test_opencode_seed_rejects_plaintext_key(ready_workspace):
    with pytest.raises(RuntimeValidationError):
        ensure_runtime_profile(
            ready_workspace.id,
            uuid4(),
            "ally-a",
            _zen_seed(credential_refs={"OPENCODE_ZEN_API_KEY": "sk-live-raw-key"}),
        )
