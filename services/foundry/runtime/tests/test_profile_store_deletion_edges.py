from __future__ import annotations

import json
import time
from uuid import uuid4

import pytest

from allies_runtime.profile_store import (
    ProfileCleanupStatus,
    ProfileInputError,
    ProfileProvisionStatus,
    ProfileSeed,
    ProfileStore,
)

PROFILE_ID = "12345678-1234-5678-1234-567812345678"


def seed(profile_id: str = PROFILE_ID, *, epoch: int = 4) -> ProfileSeed:
    return ProfileSeed(
        foundry_profile_id=profile_id,
        ally_name="Aster",
        personality="Keep this text.",
        provider="openai",
        model="gpt-test",
        first_chat_instruction="Ask one question.",
        credential_refs={"OPENAI_API_KEY": "vault://tenant/openai"},
        lifecycle_epoch=epoch,
        materialized_generation="machine-1",
        operation_id="provision-1",
    )


def store(tmp_path) -> ProfileStore:
    return ProfileStore(
        tmp_path / "volume",
        api_key_factory=lambda: "profile-local-key-0123456789",
        credential_resolver={"vault://tenant/openai": "secret"},
    )


def deletion_args(profile_seed: ProfileSeed):
    return {
        "profile_key": profile_seed.profile_key,
        "operation_id": str(uuid4()),
        "lifecycle_epoch": profile_seed.lifecycle_epoch,
        "expires_at": time.time() + 30,
        "attempt_id": str(uuid4()),
        "request_digest": "a" * 64,
    }


def test_fence_deletion_replays_and_rejects_competing_attempts(tmp_path):
    profile_seed = seed()
    profile_store = store(tmp_path)
    args = deletion_args(profile_seed)
    first = profile_store.fence_deletion(**args)
    replay = profile_store.fence_deletion(**args)
    competing = profile_store.fence_deletion(
        profile_seed.profile_key,
        args["operation_id"],
        args["lifecycle_epoch"],
        args["expires_at"],
        attempt_id=str(uuid4()),
        request_digest="b" * 64,
    )
    assert first.status is ProfileCleanupStatus.FENCED
    assert replay.status is ProfileCleanupStatus.FENCED
    assert competing.status is ProfileCleanupStatus.FENCED
    assert competing.repair_code == "stale_cleanup_epoch"


def test_fence_deletion_handles_expiry_and_profile_epoch_fences(tmp_path):
    profile_store = store(tmp_path)
    profile_seed = seed()
    expired = deletion_args(profile_seed)
    expired["expires_at"] = 0
    receipt = profile_store.fence_deletion(**expired)
    assert receipt.status is ProfileCleanupStatus.REPAIR_REQUIRED
    assert receipt.repair_code == "cleanup_expired"

    materialized = seed(profile_id="87654321-4321-8765-4321-876543218765", epoch=8)
    assert (
        profile_store.materialize(materialized).status is ProfileProvisionStatus.CREATED
    )
    stale = deletion_args(materialized)
    stale["lifecycle_epoch"] = 7
    stale["expires_at"] = time.time() + 30
    stale_receipt = profile_store.fence_deletion(**stale)
    assert stale_receipt.status is ProfileCleanupStatus.FENCED
    assert stale_receipt.repair_code == "stale_cleanup_epoch"


def test_fence_deletion_rejects_invalid_tombstone_and_bounds_inputs(tmp_path):
    profile_seed = seed()
    profile_store = store(tmp_path)
    args = deletion_args(profile_seed)
    tombstone = profile_store._tombstone_path(profile_seed.profile_key)
    tombstone.parent.mkdir(parents=True, exist_ok=True)
    tombstone.write_text("{broken", encoding="utf-8")
    invalid = profile_store.fence_deletion(**args)
    assert invalid.status is ProfileCleanupStatus.REPAIR_REQUIRED
    assert invalid.repair_code == "invalid_cleanup_tombstone"

    with pytest.raises(ProfileInputError):
        profile_store.fence_deletion(
            **{**args, "expires_at": time.time() + 2 * 24 * 60 * 60}
        )
    with pytest.raises(ProfileInputError):
        profile_store.fence_deletion(**{**args, "attempt_id": "bad-attempt"})
    with pytest.raises(ProfileInputError):
        profile_store.fence_deletion(**{**args, "request_digest": "UPPER" + "a" * 59})


def test_quiescent_cleanup_replays_terminal_marker_and_fences_stale_request(tmp_path):
    profile_seed = seed()
    profile_store = store(tmp_path)
    args = deletion_args(profile_seed)
    fenced = profile_store.fence_deletion(**args)
    deleted = profile_store.cleanup(deletion=True, **args)
    replay = profile_store.cleanup(deletion=True, **args)
    stale = profile_store.cleanup(
        profile_seed.profile_key,
        args["operation_id"],
        args["lifecycle_epoch"],
        args["expires_at"],
        deletion=True,
        attempt_id=str(uuid4()),
        request_digest="c" * 64,
    )
    assert fenced.status is ProfileCleanupStatus.FENCED
    assert deleted.status is ProfileCleanupStatus.DEPROVISIONED
    assert replay.status is ProfileCleanupStatus.DEPROVISIONED
    assert stale.status is ProfileCleanupStatus.DEPROVISIONED
    assert set(
        json.loads(profile_store._tombstone_path(profile_seed.profile_key).read_text())
    ) == {
        "schema",
        "schema_version",
        "profile_key",
        "status",
        "deleted",
    }


def test_quiescent_cleanup_requires_exact_pending_identity(tmp_path):
    profile_seed = seed()
    profile_store = store(tmp_path)
    args = deletion_args(profile_seed)
    profile_store.fence_deletion(**args)
    with pytest.raises(ProfileInputError):
        profile_store.cleanup(
            profile_seed.profile_key,
            args["operation_id"],
            args["lifecycle_epoch"],
            args["expires_at"],
            deletion=True,
            attempt_id=None,
            request_digest=args["request_digest"],
        )
    stale = {**args, "request_digest": "d" * 64}
    fenced = profile_store.cleanup(deletion=True, **stale)
    assert fenced.status is ProfileCleanupStatus.FENCED
    assert fenced.repair_code == "stale_cleanup_epoch"


def test_quiescent_cleanup_expiry_writes_repair_without_removing_profile(tmp_path):
    profile_seed = seed()
    profile_store = store(tmp_path)
    assert (
        profile_store.materialize(profile_seed).status is ProfileProvisionStatus.CREATED
    )
    args = deletion_args(profile_seed)
    args["expires_at"] = 0
    receipt = profile_store.cleanup(deletion=True, **args)
    assert receipt.status is ProfileCleanupStatus.REPAIR_REQUIRED
    assert receipt.repair_code == "cleanup_expired"
    assert (profile_store.volume_root / "profiles" / profile_seed.profile_key).exists()
