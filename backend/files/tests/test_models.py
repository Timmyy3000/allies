import json
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError

from allies.gateways.contracts import (
    ExecutionCommand,
    ExecutionInput,
    canonical_fingerprint,
)
from allies.models import Ally
from auths.models import User
from files.models import FileDirection, FileVersion
from workspaces.models import Workspace


@pytest.mark.django_db
def test_file_version_keeps_private_scope_and_immutable_identity():
    owner = User.objects.create_user()
    workspace = Workspace.objects.create(owner=owner, name="Personal")
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study partner",
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    file = FileVersion(
        workspace=workspace,
        ally=ally,
        owner=owner,
        direction=FileDirection.INBOUND,
        original_name="report.pdf",
        media_type="application/pdf",
        expected_size=1200,
        sha256="a" * 64,
    )

    file.full_clean()
    file.save()

    assert file.id
    assert file.write_fence
    assert file.generation == 1
    file.expected_size = 25_000_001
    with pytest.raises(ValidationError):
        file.full_clean()


def _file_input(size: int, suffix: str) -> dict:
    return {
        "file_id": f"550e8400-e29b-41d4-a716-4466554400{suffix}",
        "name": f"report-{suffix}.pdf",
        "media_type": "application/pdf",
        "size": size,
        "sha256": "a" * 64,
    }


def test_file_input_enforces_manifest_presence_and_aggregate_limit():
    omitted = ExecutionInput.model_validate(
        {"kind": "execution_input", "text": "normalized user text"}
    )
    assert "files" not in omitted.model_fields_set
    with pytest.raises(ValueError, match="files must be omitted"):
        ExecutionInput.model_validate(
            {"kind": "execution_input", "text": "normalized user text", "files": None}
        )
    with pytest.raises(ValueError):
        ExecutionInput.model_validate(
            {"kind": "execution_input", "text": "normalized user text", "files": []}
        )

    accepted = ExecutionInput.model_validate(
        {
            "kind": "execution_input",
            "text": "",
            "files": [_file_input(25_000_000, "01"), _file_input(25_000_000, "02")],
        }
    )
    assert sum(file.size for file in accepted.files or []) == 50_000_000
    with pytest.raises(ValueError, match="aggregate size"):
        ExecutionInput.model_validate(
            {
                "kind": "execution_input",
                "text": "",
                "files": [
                    _file_input(25_000_000, "01"),
                    _file_input(25_000_000, "02"),
                    _file_input(1, "03"),
                ],
            }
        )


def test_omitted_files_keep_legacy_execution_fingerprints():
    fixture = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "contracts"
        / "foundry-execution-v1.json"
    )
    contract = json.loads(fixture.read_text(encoding="utf-8"))
    for name in ("command", "bootstrap_command"):
        command = ExecutionCommand.model_validate(contract[name])
        assert "files" not in command.payload.model_fields_set
        assert command.fingerprint == contract[name]["fingerprint"]


def test_file_input_commands_match_golden_fingerprints():
    fixture = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "contracts"
        / "foundry-execution-file-input-v1.json"
    )
    contract = json.loads(fixture.read_text(encoding="utf-8"))
    for command_data in contract["commands"].values():
        command = ExecutionCommand.model_validate(command_data)
        assert canonical_fingerprint(command) == command_data["fingerprint"]
