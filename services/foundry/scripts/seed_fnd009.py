"""Seed one isolated Foundry database for the FND-009 proof."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
repository_backend = Path(__file__).resolve().parents[1] / "backend"
container_backend = Path("/app")
sys.path.insert(
    0,
    str(container_backend if (container_backend / "manage.py").exists() else repository_backend),
)

import django  # noqa: E402

django.setup()

from django.utils import timezone  # noqa: E402

from fnd009_common import (  # noqa: E402
    ALLY_A_ID,
    ALLY_B_ID,
    APP_NAME,
    BINDING_A_ID,
    BINDING_B_ID,
    CONVERSATION_A_ID,
    CONVERSATION_B_ID,
    MACHINE_ID,
    MACHINE_NAME,
    PROVISIONING_ID,
    RUNTIME_CREDENTIAL_ID,
    RUNTIME_TOKEN,
    VOLUME_ID,
    WORKSPACE_ID,
    profile_id_for_binding,
    stable_id,
)
from runtime.models import (  # noqa: E402
    ConversationBinding,
    RuntimeCredential,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    RuntimeOperationState,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.profile_keys import derive_hermes_profile_key  # noqa: E402


def _digest(value: object) -> str:
    if isinstance(value, bytes):
        raw = value
    else:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    keep_warm = int(os.environ.get("FND009_KEEP_WARM_SECONDS", "8"))
    now = timezone.now()
    Workspace.objects.filter(pk=WORKSPACE_ID).delete()
    workspace = Workspace.objects.create(
        id=WORKSPACE_ID,
        tenant_ref=str(WORKSPACE_ID),
        fly_app_ref=APP_NAME,
        volume_ref=VOLUME_ID,
        machine_ref=MACHINE_ID,
        machine_generation=1,
        provisioning_id=PROVISIONING_ID,
        provisioning_phase=WorkspaceProvisioningPhase.IDLE,
        runtime_operation_state=RuntimeOperationState.IDLE,
        runtime_start_epoch=0,
        speculative_keep_warm_until=now + timedelta(seconds=keep_warm),
    )
    RuntimeCredential.objects.create(
        id=RUNTIME_CREDENTIAL_ID,
        workspace=workspace,
        token_digest=hashlib.sha256(RUNTIME_TOKEN.encode()).hexdigest(),
        machine_generation=1,
    )
    profiles = (
        (BINDING_A_ID, ALLY_A_ID, CONVERSATION_A_ID, "a"),
        (BINDING_B_ID, ALLY_B_ID, CONVERSATION_B_ID, "b"),
    )
    for binding_id, ally_id, conversation_label, suffix in profiles:
        profile_id = profile_id_for_binding(binding_id)
        payload = {
            "version": 1,
            "personality": f"FND-009 deterministic proof Ally {suffix}",
            "provider": "fake",
            "model": "fnd009-proof",
            "first_chat_instruction": "Respond with the fixed proof response.",
            "credential_refs": {},
        }
        profile = RuntimeProfile.objects.create(
            id=profile_id,
            workspace=workspace,
            ally_ref=str(ally_id),
            hermes_profile_key=derive_hermes_profile_key(profile_id),
            hermes_profile_key_version=1,
            lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
            lifecycle_epoch=0,
            seed_version=1,
            seed_payload=payload,
            seed_fingerprint=_digest(payload),
            materialized_generation=1,
            materialization_operation_id=stable_id(f"fnd009-materialization-{suffix}"),
            materialization_request_digest=_digest(f"fnd009-materialization-{suffix}"),
            materialization_receipt_id=stable_id(f"fnd009-materialization-receipt-{suffix}"),
            materialization_result_code="created",
        )
        ConversationBinding.objects.create(
            profile=profile,
            cloud_conversation_ref=str(conversation_label),
        )
    print(json.dumps({
        "status": "seeded",
        "workspace_id": str(WORKSPACE_ID),
        "machine_id": MACHINE_ID,
        "machine_name": MACHINE_NAME,
        "generation": workspace.machine_generation,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
