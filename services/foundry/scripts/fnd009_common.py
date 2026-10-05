"""Deterministic identities shared by the local FND-009 proof helpers."""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

FND009_NAMESPACE = uuid5(NAMESPACE_URL, "allies-fnd009:proof:v1")


def stable_id(label: str) -> UUID:
    return uuid5(FND009_NAMESPACE, label)


WORKSPACE_ID = stable_id("fnd009-workspace")
USER_ID = stable_id("fnd009-user")
ALLY_A_ID = stable_id("fnd009-ally-a")
ALLY_B_ID = stable_id("fnd009-ally-b")
CONVERSATION_A_ID = stable_id("fnd009-conversation-a")
CONVERSATION_B_ID = stable_id("fnd009-conversation-b")
RUNTIME_CREDENTIAL_ID = stable_id("fnd009-runtime-credential")
BINDING_A_ID = stable_id("fnd009-binding-a")
BINDING_B_ID = stable_id("fnd009-binding-b")
PROVISIONING_ID = stable_id("fnd009-provisioning")

APP_NAME = f"allies-ws-{WORKSPACE_ID.hex}"
MACHINE_ID = "machine-fnd009"
MACHINE_NAME = "machine-fnd009"
VOLUME_ID = "vol-fnd009"
REGION = "local"

# These values are proof-only fixtures, not deployment credentials.
CLOUD_SERVICE_TOKEN = "fnd009-cloud-service-token-local-only-32-bytes"
EVENT_SERVICE_TOKEN = "fnd009-event-service-token-local-only-32-bytes"
RUNTIME_TOKEN = "fnd009-runtime-token-local-only-32-bytes"
FLY_TOKEN = "fnd009-fly-token-local-only-32-bytes"
PROOF_TOKEN = "fnd009-proof-snapshot-token"
FAKE_SUBJECT = "fnd009-user"


def profile_id_for_binding(binding_id: UUID) -> UUID:
    return uuid5(uuid5(NAMESPACE_URL, "allies-foundry-profile-v1"), str(binding_id))


__all__ = [
    "ALLY_A_ID",
    "ALLY_B_ID",
    "APP_NAME",
    "BINDING_A_ID",
    "BINDING_B_ID",
    "CLOUD_SERVICE_TOKEN",
    "CONVERSATION_A_ID",
    "CONVERSATION_B_ID",
    "EVENT_SERVICE_TOKEN",
    "FAKE_SUBJECT",
    "FLY_TOKEN",
    "MACHINE_ID",
    "MACHINE_NAME",
    "PROOF_TOKEN",
    "PROVISIONING_ID",
    "REGION",
    "RUNTIME_CREDENTIAL_ID",
    "RUNTIME_TOKEN",
    "USER_ID",
    "VOLUME_ID",
    "WORKSPACE_ID",
    "profile_id_for_binding",
    "stable_id",
]
