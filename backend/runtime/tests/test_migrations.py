from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

MIGRATION_PROBE = r"""
from __future__ import annotations

import os
import sys
import uuid

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from django.db import connections
from django.db.migrations.executor import MigrationExecutor

MIGRATION_FROM = ("runtime", "0006_lease_runtime_lease_state_valid")
MIGRATION_TO = ("runtime", "0007_workspace_provisioning_state")
database_path, mode = sys.argv[1:]
connections.databases["default"]["NAME"] = database_path
connections["default"].settings_dict["NAME"] = database_path
connection = connections["default"]


def migrate(target):
    MigrationExecutor(connection).migrate([target])


def model_at(target):
    return MigrationExecutor(connection).loader.project_state([target]).apps.get_model(
        "runtime", "Workspace"
    )


migrate(MIGRATION_FROM)
old_workspace = model_at(MIGRATION_FROM)

if mode == "valid":
    empty_id = uuid.uuid4()
    complete_id = uuid.uuid4()
    old_workspace.objects.bulk_create(
        [
            old_workspace(
                id=empty_id,
                tenant_ref="legacy-empty",
                fly_app_ref="",
                volume_ref="",
                machine_ref="",
                machine_generation=7,
            ),
            old_workspace(
                id=complete_id,
                tenant_ref="legacy-complete",
                fly_app_ref="app-legacy",
                volume_ref="volume-legacy",
                machine_ref="machine-legacy",
                machine_generation=0,
            ),
        ]
    )
    migrate(MIGRATION_TO)
    new_workspace = model_at(MIGRATION_TO)
    empty = new_workspace.objects.get(id=empty_id)
    assert empty.machine_generation == 0
    assert empty.fly_app_ref is None
    assert empty.volume_ref is None
    assert empty.machine_ref is None
    complete = new_workspace.objects.get(id=complete_id)
    assert complete.machine_generation == 1
    assert complete.fly_app_ref == "app-legacy"
    assert complete.volume_ref == "volume-legacy"
    assert complete.machine_ref == "machine-legacy"
elif mode == "partial":
    old_workspace.objects.create(
        id=uuid.uuid4(),
        tenant_ref="legacy-partial",
        fly_app_ref="app-legacy",
        volume_ref="",
        machine_ref="",
        machine_generation=0,
    )
    try:
        migrate(MIGRATION_TO)
    except RuntimeError as exc:
        assert "partial Fly bindings" in str(exc)
    else:
        raise AssertionError("partial legacy bindings were accepted")
else:
    raise AssertionError(f"unknown migration probe mode: {mode}")
"""

MEMORY_MIGRATION_PROBE = r"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from django.db import connections
from django.db.migrations.executor import MigrationExecutor

MIGRATION_FROM = ("runtime", "0013_workspace_activation_claim")
MIGRATION_TO = ("runtime", "0014_profile_memory_seed_v2")
database_path = sys.argv[1]
connections.databases["default"]["NAME"] = database_path
connections["default"].settings_dict["NAME"] = database_path
connection = connections["default"]


def migrate(target):
    MigrationExecutor(connection).migrate([target])


def models_at(target):
    apps = MigrationExecutor(connection).loader.project_state([target]).apps
    return apps.get_model("runtime", "Workspace"), apps.get_model("runtime", "RuntimeProfile")


migrate(MIGRATION_FROM)
workspace_model, profile_model = models_at(MIGRATION_FROM)
workspace = workspace_model.objects.create(
    id=uuid.uuid4(),
    tenant_ref="memory-migration",
    fly_app_ref="app-memory",
    volume_ref="volume-memory",
    machine_ref="machine-memory",
    machine_generation=2,
)
profile_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
key = "ally-v1-00000000000000000000000000000001"
seed = {
    "version": 1,
    "personality": "p",
    "provider": "openai",
    "model": "gpt-test",
    "base_url": None,
    "first_chat_instruction": "i",
    "first_chat_instruction_version": 1,
    "credential_refs": {"PROVIDER_API": "vault://p"},
}
canonical = {
    "schema_version": 1,
    "foundry_profile_id": str(profile_id),
    "hermes_profile_key": key,
    "identity": {"ally_name": "ally-a"},
    "personality": "p",
    "first_chat_version": 1,
    "first_chat_instruction": "i",
    "model": {"provider": "openai", "default": "gpt-test", "base_url": None},
    "credential_refs": {"PROVIDER_API": "vault://p"},
}
encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
legacy = hashlib.sha256(b"allies-profile-seed-v1\0" + encoded).hexdigest()
profile_model.objects.create(
    id=profile_id,
    workspace=workspace,
    ally_ref="ally-a",
    hermes_profile_key=key,
    lifecycle_state="active",
    seed_payload=seed,
    seed_fingerprint=legacy,
    materialized_generation=2,
    materialization_operation_id=uuid.uuid4(),
    materialization_request_digest="a" * 64,
    materialization_receipt_id=uuid.uuid4(),
    materialization_result_code="created",
)

migrate(MIGRATION_TO)
_, upgraded_model = models_at(MIGRATION_TO)
profile = upgraded_model.objects.get(pk=profile_id)
assert profile.seed_payload["memory_provider"] == "allies_mnemosyne"
assert profile.seed_payload["memory_policy_version"] == "allies-mnemosyne-v1"
assert profile.seed_fingerprint == "cd995ea7543b218b8380d61d6b051548da09af3a13a9bfcc529b33fca9a95db9"
assert profile.materialized_generation == 0
assert profile.materialization_operation_id is None
assert profile.materialization_request_digest == ""
assert profile.materialization_receipt_id is None
assert profile.materialization_result_code == ""
assert profile.lifecycle_state == "active"

migrate(MIGRATION_FROM)
_, rolled_back_model = models_at(MIGRATION_FROM)
profile = rolled_back_model.objects.get(pk=profile_id)
assert profile.seed_payload == seed
assert profile.seed_fingerprint == legacy
assert profile.materialized_generation == 0
assert profile.materialization_operation_id is None
assert profile.materialization_request_digest == ""
assert profile.materialization_receipt_id is None
assert profile.materialization_result_code == ""
assert profile.lifecycle_state == "active"
"""


def run_migration_probe(tmp_path: Path, mode: str) -> None:
    database_path = tmp_path / f"{mode}.sqlite3"
    result = subprocess.run(
        [sys.executable, "-c", MIGRATION_PROBE, str(database_path), mode],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("mode", ["valid", "partial"])
def test_workspace_migration_handles_legacy_binding_shapes(tmp_path, mode):
    run_migration_probe(tmp_path, mode)


def test_profile_memory_seed_migration_requeues_materialization(tmp_path):
    database_path = tmp_path / "memory.sqlite3"
    result = subprocess.run(
        [sys.executable, "-c", MEMORY_MIGRATION_PROBE, str(database_path)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
