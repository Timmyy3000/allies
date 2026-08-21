import json
from pathlib import Path

from allies.gateways.foundry import (
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
