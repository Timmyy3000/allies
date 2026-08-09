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
