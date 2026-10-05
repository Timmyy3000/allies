import json
from pathlib import Path

from allies.gateways.foundry import (
    ProfileDeletionReceipt,
    ProfileDeletionRequest,
    ProfileProvisioningReceipt,
    ProfileProvisioningRequest,
)


def test_checked_foundry_fixture_matches_typed_contract():
    path = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "contracts"
        / "foundry-profile-provisioning-v1.json"
    )
    contract = json.loads(path.read_text(encoding="utf-8"))

    assert ProfileProvisioningRequest.model_validate(contract["request"])
    assert ProfileProvisioningReceipt.model_validate(contract["receipt"])


def test_profile_deletion_fixture_covers_all_receipt_states():
    path = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "contracts"
        / "foundry-profile-deletion-v1.json"
    )
    contract = json.loads(path.read_text(encoding="utf-8"))

    assert ProfileDeletionRequest.model_validate(contract["request"])
    for state in ("pending", "complete", "repair_required"):
        receipt = ProfileDeletionReceipt.model_validate(contract[state])
        assert receipt.state == state
