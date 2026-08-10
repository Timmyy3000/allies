import json
import os
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock

import pytest

from allies_runtime.profile_store import (
    HERMES_PROFILE_DIRECTORIES,
    MANIFEST_NAME,
    ProfileCleanupStatus,
    ProfileProvisionStatus,
    ProfileSeed,
    ProfileStore,
    ProfileStoreError,
    derive_profile_key,
    inspect_profile,
    validate_profile_key,
)

PROFILE_ID = "12345678-1234-5678-1234-567812345678"
OTHER_PROFILE_ID = "87654321-4321-8765-4321-876543218765"
PROFILE_SECRET = "fixture-secret-must-not-escape"


def make_seed(
    profile_id: str = PROFILE_ID,
    *,
    operation_id: str = "provision-1",
    generation: str = "machine-1",
    epoch: int = 4,
    first_chat_version: int = 1,
    personality: str = "Keep this text exactly.\nDo not normalize it.\n",
    instruction: str = "Start by greeting the Ally and asking one useful question.",
    credential_refs: dict[str, str] | None = None,
) -> ProfileSeed:
    return ProfileSeed(
        foundry_profile_id=profile_id,
        ally_name="Aster",
        personality=personality,
        provider="openai",
        model="gpt-test",
        first_chat_instruction=instruction,
        credential_refs=credential_refs or {"OPENAI_API_KEY": "vault://tenant/openai"},
        first_chat_version=first_chat_version,
        lifecycle_epoch=epoch,
        materialized_generation=generation,
        operation_id=operation_id,
    )


def make_store(
    tmp_path: Path, *, key_factory=None, resolver=None, **store_kwargs
) -> ProfileStore:
    return ProfileStore(
        tmp_path / "volume",
        api_key_factory=key_factory or (lambda: "profile-local-key-0123456789"),
        credential_resolver=resolver or {"vault://tenant/openai": PROFILE_SECRET},
        **store_kwargs,
    )


def profile_path(store: ProfileStore, seed: ProfileSeed) -> Path:
    return store.volume_root / "profiles" / (seed.hermes_profile_key or "")


def test_key_derivation_is_stable_and_hermes_safe():
    key = derive_profile_key(PROFILE_ID)
    assert key == "ally-v1-12345678123456781234567812345678"
    assert key == derive_profile_key(PROFILE_ID.upper())
    assert len(key) == 40
    assert all(
        character.islower() or character.isdigit() or character in "-_"
        for character in key
    )


def test_first_publish_exact_layout_manifest_and_secret_permissions(tmp_path):
    store = make_store(tmp_path)
    seed = make_seed()

    receipt = store.materialize(seed)

    assert receipt.status is ProfileProvisionStatus.CREATED
    profile = profile_path(store, seed)
    assert {item.name for item in profile.iterdir()} == {
        MANIFEST_NAME,
        "config.yaml",
        ".env",
        "SOUL.md",
        *HERMES_PROFILE_DIRECTORIES,
    }
    assert (
        (profile / "SOUL.md").read_text(encoding="utf-8").startswith(seed.personality)
    )
    soul = (profile / "SOUL.md").read_text(encoding="utf-8")
    assert soul.count("allies-first-chat:v1") == 1
    assert (profile / "config.yaml").read_text(encoding="utf-8") == (
        'model:\n  provider: "openai"\n  default: "gpt-test"\n'
    )
    assert PROFILE_SECRET in (profile / ".env").read_text(encoding="utf-8")
    if os.name != "nt":
        assert (os.stat(profile / ".env", follow_symlinks=False).st_mode & 0o077) == 0

    manifest = json.loads((profile / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["foundry_profile_id"] == PROFILE_ID
    assert manifest["hermes_profile_key"] == seed.hermes_profile_key
    assert manifest["seed_fingerprint"] == seed.fingerprint
    assert manifest["completion_state"] == "complete"
    assert PROFILE_SECRET not in json.dumps(manifest)
    assert PROFILE_SECRET not in json.dumps(receipt.to_dict())


def test_repeat_and_machine_replacement_are_existing_and_stable(tmp_path):
    calls = 0
    calls_lock = Lock()

    def key_factory():
        nonlocal calls
        with calls_lock:
            calls += 1
        return "profile-local-key-0123456789"

    store = make_store(tmp_path, key_factory=key_factory)
    seed = make_seed()
    first = store.materialize(seed)
    repeat = store.materialize(seed)
    replacement = store.materialize(
        make_seed(operation_id="reconcile-after-replacement", generation="machine-2")
    )

    assert first.status is ProfileProvisionStatus.CREATED
    assert repeat.status is ProfileProvisionStatus.EXISTING
    assert repeat.receipt_id == first.receipt_id
    assert repeat.seed_fingerprint == first.seed_fingerprint
    assert repeat.profile_key == first.profile_key
    assert replacement.status is ProfileProvisionStatus.EXISTING
    assert replacement.materialized_generation == "machine-2"
    assert calls == 1


def test_two_profiles_are_isolated(tmp_path):
    resolved = {
        "vault://tenant/openai": "secret-one",
        "vault://tenant/other": "secret-two",
    }
    store = make_store(tmp_path, resolver=resolved)
    first = make_seed()
    second = make_seed(
        OTHER_PROFILE_ID,
        personality="The second personality is distinct.",
        credential_refs={"OPENAI_API_KEY": "vault://tenant/other"},
        operation_id="provision-2",
    )

    assert store.materialize(first).status is ProfileProvisionStatus.CREATED
    assert store.materialize(second).status is ProfileProvisionStatus.CREATED
    first_env = (profile_path(store, first) / ".env").read_text(encoding="utf-8")
    second_env = (profile_path(store, second) / ".env").read_text(encoding="utf-8")
    assert "secret-one" in first_env and "secret-two" not in first_env
    assert "secret-two" in second_env and "secret-one" not in second_env
    assert (profile_path(store, first) / "SOUL.md").read_text(encoding="utf-8") != (
        profile_path(store, second) / "SOUL.md"
    ).read_text(encoding="utf-8")


def test_same_profile_concurrency_publishes_once(tmp_path):
    calls = 0
    calls_lock = Lock()

    def key_factory():
        nonlocal calls
        with calls_lock:
            calls += 1
        return f"profile-local-key-{calls:010d}"

    store = make_store(tmp_path, key_factory=key_factory)
    seed = make_seed()
    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(store.materialize, (seed, seed)))

    assert sorted(receipt.status.value for receipt in receipts) == [
        "CREATED",
        "EXISTING",
    ]
    assert len(list((store.volume_root / "profiles").glob("ally-v1-*"))) == 1
    assert calls == 1


def test_partial_and_incompatible_state_fail_closed(tmp_path):
    store = make_store(tmp_path)
    seed = make_seed()
    profile = profile_path(store, seed)
    profile.mkdir(parents=True)
    (profile / MANIFEST_NAME).write_text(
        '{"completion_state":"writing"}', encoding="utf-8"
    )
    partial = store.materialize(seed)
    assert partial.status is ProfileProvisionStatus.REPAIR_REQUIRED
    assert partial.repair_code == "unsupported_manifest"

    shutil.rmtree(profile)
    assert store.materialize(seed).status is ProfileProvisionStatus.CREATED
    conflict = make_seed(personality="Changed immutable personality")
    assert store.materialize(conflict).status is ProfileProvisionStatus.CONFLICT
    assert profile.exists()


def test_unknown_temp_state_is_repairable_and_does_not_publish(tmp_path):
    store = make_store(tmp_path)
    seed = make_seed()
    profiles = store.volume_root / "profiles"
    profiles.mkdir(parents=True)
    (profiles / f".{seed.hermes_profile_key}.tmp-unknown").mkdir()

    receipt = store.materialize(seed)

    assert receipt.status is ProfileProvisionStatus.REPAIR_REQUIRED
    assert receipt.repair_code == "unknown_temporary_state"
    assert not profile_path(store, seed).exists()


def test_symlinked_profile_is_never_followed(tmp_path):
    store = make_store(tmp_path)
    seed = make_seed()
    profile = profile_path(store, seed)
    outside = tmp_path / "outside"
    outside.mkdir()
    profile.parent.mkdir(parents=True)
    try:
        os.symlink(outside, profile, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")

    receipt = store.materialize(seed)

    assert receipt.status is ProfileProvisionStatus.REPAIR_REQUIRED
    assert receipt.repair_code == "symlinked_profile"
    assert not any(outside.iterdir())


def test_cleanup_is_bounded_idempotent_and_fences_late_provision(tmp_path):
    store = make_store(tmp_path)
    seed = make_seed()
    store.materialize(seed)

    first = store.cleanup(
        seed.hermes_profile_key or "",
        "cleanup-1",
        seed.lifecycle_epoch,
        time.time() + 30,
    )
    repeat = store.cleanup(
        seed.hermes_profile_key or "",
        "cleanup-1",
        seed.lifecycle_epoch,
        time.time() + 30,
    )
    late = store.materialize(seed)
    stale_cleanup = store.cleanup(
        seed.hermes_profile_key or "",
        "cleanup-old",
        seed.lifecycle_epoch,
        time.time() + 30,
    )

    assert first.status is ProfileCleanupStatus.DEPROVISIONED
    assert repeat.to_dict() == first.to_dict()
    assert not profile_path(store, seed).exists()
    assert late.status is ProfileProvisionStatus.FENCED
    assert stale_cleanup.status is ProfileCleanupStatus.FENCED
    assert (
        store.volume_root
        / "profiles"
        / ".allies-profile-tombstones"
        / f"{seed.hermes_profile_key}.json"
    ).exists()


def test_cleanup_rejects_epoch_older_than_materialized_profile(tmp_path):
    store = make_store(tmp_path)
    seed = make_seed(epoch=7)
    store.materialize(seed)

    stale = store.cleanup(
        seed.hermes_profile_key or "", "cleanup-stale", 6, time.time() + 30
    )

    assert stale.status is ProfileCleanupStatus.FENCED
    assert stale.repair_code == "stale_cleanup_epoch"
    assert profile_path(store, seed).exists()


def test_expired_cleanup_preserves_profile_but_fences_stale_request(tmp_path):
    store = make_store(tmp_path)
    seed = make_seed()
    store.materialize(seed)

    cleanup = store.cleanup(
        seed.hermes_profile_key or "", "cleanup-expired", seed.lifecycle_epoch, 0
    )
    late = store.materialize(seed)

    assert cleanup.status is ProfileCleanupStatus.REPAIR_REQUIRED
    assert cleanup.repair_code == "cleanup_expired"
    assert profile_path(store, seed).exists()
    assert late.status is ProfileProvisionStatus.FENCED


def test_interrupted_cleanup_resumes_same_operation(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    seed = make_seed()
    store.materialize(seed)
    original_remove = store._remove_owned_path

    def interrupted(*args, **kwargs):
        raise ProfileStoreError("simulated interruption")

    monkeypatch.setattr(store, "_remove_owned_path", interrupted)
    interrupted_receipt = store.cleanup(
        seed.hermes_profile_key or "",
        "cleanup-interrupted",
        seed.lifecycle_epoch,
        time.time() + 30,
    )
    monkeypatch.setattr(store, "_remove_owned_path", original_remove)
    resumed_receipt = store.cleanup(
        seed.hermes_profile_key or "",
        "cleanup-interrupted",
        seed.lifecycle_epoch,
        time.time() + 30,
    )

    assert interrupted_receipt.status is ProfileCleanupStatus.REPAIR_REQUIRED
    assert resumed_receipt.status is ProfileCleanupStatus.DEPROVISIONED
    assert not profile_path(store, seed).exists()


def test_secret_resolver_failure_is_sanitized(tmp_path, capsys):
    def resolver(_reference: str) -> str:
        raise RuntimeError(PROFILE_SECRET)

    store = make_store(tmp_path, resolver=resolver)
    receipt = store.materialize(make_seed())

    captured = capsys.readouterr()
    assert receipt.status is ProfileProvisionStatus.REPAIR_REQUIRED
    assert PROFILE_SECRET not in repr(receipt.to_dict())
    assert PROFILE_SECRET not in captured.out
    assert PROFILE_SECRET not in captured.err


def test_profile_seed_validation_rejects_unsafe_inputs():
    with pytest.raises(ProfileStoreError):
        derive_profile_key("not-a-uuid")
    with pytest.raises(ProfileStoreError):
        validate_profile_key("bad.key")
    with pytest.raises(ProfileStoreError):
        validate_profile_key("default")
    with pytest.raises(ProfileStoreError):
        ProfileSeed("not-a-uuid")
    with pytest.raises(ProfileStoreError):
        ProfileSeed(
            foundry_profile_id=PROFILE_ID,
            ally_name="",
            personality="personality",
            provider="openai",
            model="gpt-test",
            first_chat_instruction="instruction",
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"provider": "one", "model_provider": "two"},
        {"model": "one", "model_default": "two"},
        {"first_chat_instruction": "one", "system_instruction": "two"},
        {"seed_version": 2, "version": 1},
        {"first_chat_version": 2, "first_chat_instruction_version": 1},
        {"seed_version": 0},
        {"first_chat_version": 0},
        {"lifecycle_epoch": -1},
        {"materialized_generation": True},
        {"materialized_generation": object()},
        {"operation_id": "bad/id"},
        {"base_url": "bad\x00url"},
        {"base_url": "bad\nurl"},
        {"ally_id": "bad\x00id"},
        {"credential_refs": {"API_SERVER_KEY": "vault://tenant/key"}},
        {"credential_refs": {1: "vault://tenant/key"}},
        {"credential_refs": {"Bad Name": "vault://tenant/key"}},
        {
            "credential_refs": {
                "provider-api": "vault://tenant/key",
                "PROVIDER_API": "vault://tenant/other",
            }
        },
        {"credential_refs": {"provider": "sk-secret"}},
        {"credential_refs": {"provider": "vault://tenant/\nkey"}},
        {"identity": {"Bad Name": "value"}},
        {"hermes_profile_key": "ally-v1-" + "0" * 32},
    ],
)
def test_profile_seed_rejects_invalid_variants(changes):
    values = {
        "foundry_profile_id": PROFILE_ID,
        "ally_name": "Aster",
        "personality": "personality",
        "provider": "openai",
        "model": "gpt-test",
        "first_chat_instruction": "instruction",
        "credential_refs": {"provider": "vault://tenant/key"},
    }
    values.update(changes)
    with pytest.raises(ProfileStoreError):
        ProfileSeed(**values)


def test_profile_seed_aliases_and_optional_layout_are_supported(tmp_path):
    seed = ProfileSeed(
        foundry_profile_id=PROFILE_ID,
        ally_name="Aster",
        personality="personality",
        model_provider="openai",
        model_default="gpt-test",
        system_instruction="instruction",
        credential_refs={"provider-api": "vault://tenant/openai"},
        base_url="https://model.example.test/v1",
        identity={"role": "assistant"},
        ally_id="ally-a",
        version=1,
        first_chat_instruction_version=1,
        materialized_generation=2,
        operation_id=uuid.uuid4(),
    )
    assert seed.provider == "openai"
    assert seed.model == "gpt-test"
    assert seed.first_chat_instruction == "instruction"
    assert dict(seed.credential_refs) == {"PROVIDER_API": "vault://tenant/openai"}
    store = make_store(tmp_path)
    receipt = store.materialize(seed)
    assert receipt.status is ProfileProvisionStatus.CREATED
    assert 'base_url: "https://model.example.test/v1"' in (
        (profile_path(store, seed) / "config.yaml").read_text(encoding="utf-8")
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"volume_root": "relative"},
        {"lock_timeout_seconds": 0},
        {"stale_lock_seconds": 0},
        {"cleanup_timeout_seconds": 0},
        {"max_cleanup_entries": 0},
    ],
)
def test_profile_store_configuration_is_bounded(tmp_path, kwargs):
    with pytest.raises(ProfileStoreError):
        if "volume_root" in kwargs:
            ProfileStore(**kwargs)
        else:
            ProfileStore(tmp_path / "volume", **kwargs)


def test_existing_profile_classifies_epoch_manifest_and_layout_conflicts(tmp_path):
    store = make_store(tmp_path)
    seed = make_seed(personality="personality without a trailing newline")
    assert store.materialize(seed).status is ProfileProvisionStatus.CREATED
    profile = profile_path(store, seed)
    manifest_path = profile / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest["foundry_profile_id"] = OTHER_PROFILE_ID
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert store.materialize(seed).repair_code == "identity_collision"
    manifest["foundry_profile_id"] = PROFILE_ID
    manifest["lifecycle_epoch"] = seed.lifecycle_epoch + 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert store.materialize(seed).status is ProfileProvisionStatus.FENCED
    manifest["lifecycle_epoch"] = seed.lifecycle_epoch - 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert store.materialize(seed).repair_code == "lifecycle_epoch_mismatch"
    manifest["lifecycle_epoch"] = seed.lifecycle_epoch
    manifest["completion_state"] = "writing"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert store.materialize(seed).repair_code == "incomplete_profile"
    manifest["completion_state"] = "complete"
    (profile / ".env").unlink()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert store.materialize(seed).repair_code == "incomplete_profile"
    (profile / ".env").write_text("API_SERVER_KEY=key\n", encoding="utf-8")
    (profile / HERMES_PROFILE_DIRECTORIES[0]).rmdir()
    assert store.materialize(seed).repair_code == "incomplete_layout"


def test_existing_profile_classifies_invalid_metadata_and_updates_generation(
    tmp_path, monkeypatch
):
    store = make_store(tmp_path)
    seed = make_seed()
    assert store.materialize(seed).status is ProfileProvisionStatus.CREATED
    profile = profile_path(store, seed)
    manifest_path = profile / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["operation_id"] = "bad/id"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert store.materialize(seed).repair_code == "invalid_manifest_metadata"
    manifest["operation_id"] = seed.operation_id
    manifest["receipt_id"] = "invalid"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert store.materialize(seed).repair_code == "invalid_manifest_metadata"

    manifest["receipt_id"] = "pr-" + "a" * 32
    manifest["materialized_generation"] = "old-generation"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    updated = store.materialize(make_seed(generation="new-generation"))
    assert updated.status is ProfileProvisionStatus.EXISTING
    assert updated.materialized_generation == "new-generation"

    original = store._write_json_atomic
    monkeypatch.setattr(
        store,
        "_write_json_atomic",
        lambda *args, **kwargs: (_ for _ in ()).throw(ProfileStoreError("write")),
    )
    manifest["materialized_generation"] = "old-again"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert (
        store.materialize(make_seed(generation="newer")).repair_code
        == "manifest_update_failed"
    )
    monkeypatch.setattr(store, "_write_json_atomic", original)


def test_profile_store_classifies_tombstones_and_lock_recovery(tmp_path):
    store = make_store(tmp_path, stale_lock_seconds=0.01)
    seed = make_seed()
    profiles = store._profiles_root()
    lock = store._locks_root() / f"{seed.hermes_profile_key}.lock"
    lock.write_text("stale", encoding="ascii")
    old = time.time() - 10
    os.utime(lock, (old, old))
    assert store.materialize(seed).status is ProfileProvisionStatus.CREATED

    tombstone = store._tombstone_path(seed.hermes_profile_key or "")
    shutil.rmtree(profile_path(store, seed))
    tombstone.write_text("not-json", encoding="utf-8")
    assert store.materialize(seed).repair_code == "invalid_cleanup_tombstone"
    tombstone.write_text(json.dumps({"status": "unknown"}), encoding="utf-8")
    assert (
        store.cleanup(
            seed.hermes_profile_key or "",
            "cleanup",
            seed.lifecycle_epoch,
            time.time() + 30,
        ).repair_code
        == "invalid_cleanup_tombstone"
    )
    tombstone.unlink()
    temporary = profiles / f".{seed.hermes_profile_key}.tmp-other"
    temporary.mkdir()
    cleanup = store.cleanup(
        seed.hermes_profile_key or "",
        "cleanup",
        seed.lifecycle_epoch,
        time.time() + 30,
    )
    assert cleanup.status is ProfileCleanupStatus.DEPROVISIONED
    assert not temporary.exists()


def test_profile_store_rejects_tombstone_for_another_profile(tmp_path):
    store = make_store(tmp_path)
    seed = make_seed()
    cleanup = store.cleanup(seed.profile_key, "cleanup-mismatch", seed.lifecycle_epoch)
    tombstone = store._tombstone_path(seed.profile_key)
    payload = json.loads(tombstone.read_text(encoding="utf-8"))
    payload["profile_key"] = derive_profile_key(OTHER_PROFILE_ID)
    tombstone.write_text(json.dumps(payload), encoding="utf-8")

    cleanup_replay = store.cleanup(
        seed.profile_key, "cleanup-mismatch", seed.lifecycle_epoch
    )
    materialization = store.materialize(seed)

    assert cleanup.status is ProfileCleanupStatus.DEPROVISIONED
    assert cleanup_replay.repair_code == "invalid_cleanup_tombstone"
    assert materialization.repair_code == "invalid_cleanup_tombstone"


def test_profile_cleanup_classifies_bounded_and_non_directory_state(tmp_path):
    store = make_store(tmp_path, max_cleanup_entries=1)
    seed = make_seed()
    assert store.materialize(seed).status is ProfileProvisionStatus.CREATED
    bounded = store.cleanup(
        seed.hermes_profile_key or "",
        "cleanup-bound",
        seed.lifecycle_epoch,
        time.time() + 30,
    )
    assert bounded.status is ProfileCleanupStatus.REPAIR_REQUIRED
    assert bounded.repair_code == "cleanup_bound_exceeded"

    shutil.rmtree(profile_path(store, seed), ignore_errors=True)
    store._tombstone_path(seed.hermes_profile_key or "").unlink()
    profile = profile_path(store, seed)
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("not-a-directory", encoding="utf-8")
    result = store.cleanup(
        seed.hermes_profile_key or "",
        "cleanup-file",
        seed.lifecycle_epoch,
        time.time() + 30,
    )
    assert result.repair_code == "profile_is_not_directory"


@pytest.mark.parametrize("factory_kind", ["short", "newline", "non_text", "raises"])
def test_profile_store_sanitizes_api_key_factory_failures(tmp_path, factory_kind):
    if factory_kind == "short":
        key_factory = lambda: "short"
    elif factory_kind == "newline":
        key_factory = lambda: "profile-local-key\n"
    elif factory_kind == "non_text":
        key_factory = lambda: 17
    else:

        def key_factory():
            raise RuntimeError(PROFILE_SECRET)

    store = make_store(tmp_path, key_factory=key_factory)
    receipt = store.materialize(make_seed())

    assert receipt.status is ProfileProvisionStatus.REPAIR_REQUIRED
    assert receipt.repair_code == "materialization_failed"
    assert PROFILE_SECRET not in repr(receipt.to_dict())


@pytest.mark.parametrize(
    "resolver_kind", ["missing", "none", "empty", "newline", "raises"]
)
def test_profile_store_sanitizes_credential_resolver_failures(tmp_path, resolver_kind):
    if resolver_kind == "missing":
        resolver = {}
    elif resolver_kind == "none":
        resolver = None
    elif resolver_kind == "empty":
        resolver = lambda _reference: ""
    elif resolver_kind == "newline":
        resolver = lambda _reference: "secret\nvalue"
    else:

        def resolver(_reference):
            raise RuntimeError(PROFILE_SECRET)

    store = ProfileStore(
        tmp_path / "volume",
        api_key_factory=lambda: "profile-local-key-0123456789",
        credential_resolver=resolver,
    )
    receipt = store.materialize(make_seed())

    assert receipt.status is ProfileProvisionStatus.REPAIR_REQUIRED
    assert receipt.repair_code == "materialization_failed"
    assert PROFILE_SECRET not in repr(receipt.to_dict())


def test_profile_seed_rejects_credential_and_identity_limits():
    with pytest.raises(ProfileStoreError):
        ProfileSeed(
            foundry_profile_id=PROFILE_ID,
            ally_name="Aster",
            personality="personality",
            provider="openai",
            model="gpt-test",
            first_chat_instruction="instruction",
            credential_refs={str(index): "vault://tenant/key" for index in range(33)},
        )
    with pytest.raises(ProfileStoreError):
        ProfileSeed(
            foundry_profile_id=PROFILE_ID,
            ally_name="Aster",
            personality="personality",
            provider="openai",
            model="gpt-test",
            first_chat_instruction="instruction",
            identity={str(index): "value" for index in range(17)},
        )


@pytest.mark.parametrize(
    "namespace",
    ["profiles", "locks", "tombstones"],
)
def test_profile_store_rejects_namespace_files(tmp_path, namespace):
    volume = tmp_path / "volume"
    volume.mkdir()
    profiles = volume / "profiles"
    profiles.mkdir()
    if namespace == "profiles":
        profiles.rmdir()
        profiles.write_text("not-a-directory", encoding="utf-8")
    elif namespace == "locks":
        (profiles / ".allies-profile-locks").write_text(
            "not-a-directory", encoding="utf-8"
        )
    else:
        (profiles / ".allies-profile-tombstones").write_text(
            "not-a-directory", encoding="utf-8"
        )

    store = make_store(tmp_path)
    receipt = store.materialize(make_seed())

    assert receipt.status is ProfileProvisionStatus.REPAIR_REQUIRED
    assert receipt.repair_code == "profile_store_unavailable"


@pytest.mark.parametrize("symlinked_component", [False, True])
def test_profile_store_rejects_symlinked_volume_root_and_components(
    tmp_path, symlinked_component
):
    outside = tmp_path / "outside"
    outside.mkdir()
    if symlinked_component:
        volume = tmp_path / "volume-link" / "volume"
        link = volume.parent
    else:
        volume = tmp_path / "volume-link"
        link = volume
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")

    store = ProfileStore(
        volume,
        api_key_factory=lambda: "profile-local-key-0123456789",
        credential_resolver={"vault://tenant/openai": PROFILE_SECRET},
    )
    receipt = store.materialize(make_seed())

    assert receipt.status is ProfileProvisionStatus.REPAIR_REQUIRED
    assert receipt.repair_code == "profile_store_unavailable"
    assert store.volume_root == volume
    assert not (outside / "profiles").exists()


def test_profile_store_does_not_steal_live_lock_after_stale_threshold(tmp_path):
    started = Event()
    release = Event()

    def slow_key_factory():
        started.set()
        assert release.wait(2)
        return "profile-local-key-0123456789"

    first_store = make_store(
        tmp_path,
        key_factory=slow_key_factory,
        lock_timeout_seconds=0.5,
        stale_lock_seconds=0.01,
    )
    second_store = make_store(
        tmp_path,
        lock_timeout_seconds=0.1,
        stale_lock_seconds=0.01,
    )
    seed = make_seed()

    with ThreadPoolExecutor(max_workers=1) as executor:
        first_operation = executor.submit(first_store.materialize, seed)
        assert started.wait(1)
        lock = first_store._locks_root() / f"{seed.hermes_profile_key}.lock"
        metadata = json.loads(lock.read_text(encoding="ascii"))
        assert metadata["pid"] == os.getpid()
        assert isinstance(metadata["nonce"], str)

        try:
            time.sleep(0.05)
            second_receipt = second_store.materialize(seed)
        finally:
            release.set()
        first_receipt = first_operation.result(timeout=2)

    assert second_receipt.status is ProfileProvisionStatus.REPAIR_REQUIRED
    assert second_receipt.repair_code == "lock_timeout"
    assert first_receipt.status is ProfileProvisionStatus.CREATED


def test_profile_store_reports_lock_timeout(tmp_path):
    store = make_store(tmp_path, lock_timeout_seconds=0.01, stale_lock_seconds=60)
    seed = make_seed()
    lock = store._locks_root() / f"{seed.hermes_profile_key}.lock"
    lock.write_text("active", encoding="ascii")

    receipt = store.materialize(seed)

    assert receipt.status is ProfileProvisionStatus.REPAIR_REQUIRED
    assert receipt.repair_code == "lock_timeout"


def test_profile_store_existing_state_reports_missing_and_unsupported_metadata(
    tmp_path,
):
    store = make_store(tmp_path)
    seed = make_seed()
    profile = profile_path(store, seed)
    profile.mkdir(parents=True)
    assert store.materialize(seed).repair_code == "incomplete_manifest"

    shutil.rmtree(profile)
    profile.write_text("not-a-directory", encoding="utf-8")
    assert store.materialize(seed).repair_code == "profile_is_not_directory"

    profile.unlink()
    profile.mkdir(parents=True)
    (profile / MANIFEST_NAME).write_text("{}", encoding="utf-8")
    assert store.materialize(seed).repair_code == "unsupported_manifest"


def test_profile_store_distinguishes_first_chat_version_conflict(tmp_path):
    store = make_store(tmp_path)
    first = make_seed()
    assert store.materialize(first).status is ProfileProvisionStatus.CREATED

    changed = make_seed(first_chat_version=2)
    receipt = store.materialize(changed)

    assert receipt.status is ProfileProvisionStatus.CONFLICT
    assert receipt.repair_code == "instruction_version_conflict"


def test_profile_store_bounds_temporary_state_and_handles_publish_races(
    tmp_path, monkeypatch
):
    store = make_store(tmp_path, max_cleanup_entries=1)
    seed = make_seed()
    profiles = store._profiles_root()
    (profiles / f".{seed.hermes_profile_key}.tmp-one").mkdir()
    (profiles / f".{seed.hermes_profile_key}.tmp-two").mkdir()
    bounded = store.materialize(seed)
    assert bounded.repair_code == "temporary_state_unreadable"

    race_store = make_store(tmp_path / "race")
    race_seed = make_seed(OTHER_PROFILE_ID)

    def build_and_appear(current_seed, temporary):
        temporary.mkdir(parents=True)
        profile_path(race_store, current_seed).mkdir(parents=True)
        return "profile-local-key-0123456789", "pr-" + "a" * 32

    monkeypatch.setattr(race_store, "_build_profile", build_and_appear)
    appeared = race_store.materialize(race_seed)
    assert appeared.repair_code == "profile_appeared_during_publish"


def test_profile_store_classifies_publish_oserror(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    original_rename = os.rename

    def fail_rename(*_args, **_kwargs):
        raise OSError("publish failed")

    monkeypatch.setattr(os, "rename", fail_rename)
    try:
        receipt = store.materialize(make_seed())
    finally:
        monkeypatch.setattr(os, "rename", original_rename)

    assert receipt.status is ProfileProvisionStatus.REPAIR_REQUIRED
    assert receipt.repair_code == "profile_publish_failed"


def test_profile_store_sanitizes_existing_cleanup_repair_code(tmp_path):
    store = make_store(tmp_path)
    seed = make_seed()
    first = store.cleanup(
        seed.profile_key,
        "cleanup-repair-code",
        seed.lifecycle_epoch,
        time.time() + 30,
    )
    tombstone = store._tombstone_path(seed.profile_key)
    payload = json.loads(tombstone.read_text(encoding="utf-8"))
    payload["repair_code"] = "not-safe-to-echo"
    tombstone.write_text(json.dumps(payload), encoding="utf-8")

    replay = store.cleanup(
        seed.profile_key,
        "cleanup-repair-code",
        seed.lifecycle_epoch,
        time.time() + 30,
    )

    assert first.status is ProfileCleanupStatus.DEPROVISIONED
    assert replay.repair_code == "invalid_repair_code"


def test_profile_store_classifies_pending_tombstone_conflicts(tmp_path):
    store = make_store(tmp_path)
    seed = make_seed()
    tombstone = store._tombstone_path(seed.profile_key)
    tombstone.write_text(
        json.dumps(
            {
                "status": "CLEANUP_PENDING",
                "profile_key": "ally-v1-" + "0" * 32,
                "operation_id": "old-operation",
                "lifecycle_epoch": 5,
            }
        ),
        encoding="utf-8",
    )

    invalid = store.cleanup(seed.profile_key, "new-operation", 5, time.time() + 30)
    assert invalid.repair_code == "invalid_cleanup_tombstone"

    tombstone.write_text(
        json.dumps(
            {
                "status": "CLEANUP_PENDING",
                "profile_key": seed.profile_key,
                "operation_id": "old-operation",
                "lifecycle_epoch": 5,
            }
        ),
        encoding="utf-8",
    )
    stale = store.cleanup(seed.profile_key, "new-operation", 4, time.time() + 30)

    assert stale.repair_code == "stale_cleanup_epoch"


def test_profile_store_expiry_inputs_are_bounded_and_parseable(tmp_path):
    store = make_store(tmp_path)
    first = make_seed()
    second = make_seed(OTHER_PROFILE_ID)
    future = datetime.now(UTC) + timedelta(seconds=60)

    datetime_receipt = store.cleanup(first.profile_key, "cleanup-datetime", 1, future)
    string_receipt = store.cleanup(
        second.profile_key,
        "cleanup-string",
        1,
        (future + timedelta(seconds=1)).isoformat(),
    )

    assert datetime_receipt.status is ProfileCleanupStatus.DEPROVISIONED
    assert string_receipt.status is ProfileCleanupStatus.DEPROVISIONED


@pytest.mark.parametrize("expiry", [True, float("nan"), "not-a-date", object()])
def test_profile_store_rejects_invalid_expiry_inputs(tmp_path, expiry):
    store = make_store(tmp_path)
    with pytest.raises(ProfileStoreError):
        store.cleanup(make_seed().profile_key, "cleanup-invalid", 1, expiry)


def test_profile_store_file_guards_are_fail_closed(tmp_path):
    store = make_store(tmp_path)
    parent = tmp_path / "parent"
    parent.mkdir()
    existing = parent / "existing"
    existing.write_text("existing", encoding="utf-8")
    with pytest.raises(ProfileStoreError):
        store._write_bytes(existing, b"new", mode=0o600)
    with pytest.raises(ProfileStoreError):
        store._write_json_atomic(tmp_path / "missing" / "metadata.json", {}, mode=0o644)

    directory = parent / "directory"
    directory.mkdir()
    with pytest.raises(ProfileStoreError):
        store._remove_owned_path(directory, parent=parent, allow_directory=False)
    with pytest.raises(ProfileStoreError):
        store._remove_owned_path(existing, parent=tmp_path)


def test_profile_store_accessors_default_factory_overrides_and_inspection(
    tmp_path, monkeypatch
):
    seed = make_seed()
    assert seed.model_provider_name == seed.provider
    assert seed.model_default_name == seed.model
    assert seed.seed_fingerprint == seed.fingerprint

    store = ProfileStore(
        tmp_path / "volume",
        credential_resolver={"vault://tenant/openai": PROFILE_SECRET},
    )
    receipt = inspect_profile(store, seed)
    assert receipt.status is ProfileProvisionStatus.CREATED
    assert receipt.result_code == "created"
    assert receipt.state == "CREATED"
    assert receipt.to_dict()["status"] == "CREATED"

    cleanup = store.cleanup(seed.profile_key, "cleanup-accessors", seed.lifecycle_epoch)
    assert cleanup.result_code == "deprovisioned"
    assert cleanup.state == "DEPROVISIONED"
    assert cleanup.to_dict()["status"] == "DEPROVISIONED"

    replacement = make_store(tmp_path / "replacement")
    overridden = replacement.materialize(
        make_seed(OTHER_PROFILE_ID),
        operation_id="override-operation",
        lifecycle_epoch=9,
        materialized_generation=11,
    )
    assert overridden.operation_id == "override-operation"
    assert overridden.lifecycle_epoch == 9
    assert overridden.materialized_generation == "11"

    generic_failure = make_store(tmp_path / "generic-failure")

    def fail_write(*_args, **_kwargs):
        raise RuntimeError("unexpected write failure")

    monkeypatch.setattr(generic_failure, "_write_bytes", fail_write)
    failed = generic_failure.materialize(make_seed(OTHER_PROFILE_ID))
    assert failed.repair_code == "materialization_failed"

    naive_expiry = datetime.now(UTC).astimezone().replace(tzinfo=None) + timedelta(
        seconds=60
    )
    naive = make_store(tmp_path / "naive-expiry")
    naive_receipt = naive.cleanup(
        make_seed(OTHER_PROFILE_ID).profile_key,
        "cleanup-naive",
        1,
        naive_expiry,
    )
    assert naive_receipt.status is ProfileCleanupStatus.DEPROVISIONED
