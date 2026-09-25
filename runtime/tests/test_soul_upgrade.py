import json
from pathlib import Path
from string import Template

from test_profile_store import make_seed, make_store, profile_path

from allies_runtime.profile_store import MANIFEST_NAME, ProfileProvisionStatus
from allies_runtime.soul_upgrade import (
    LEGACY_SOUL_TEMPLATE,
    PLATFORM_LAYER_SOUL_TEMPLATE,
    legacy_soul_for,
)

VALUES = {
    "ALLY_NAME": "Mira",
    "ALLY_JOB": "Keep ${ALLY_NAME} organised\nacross two lines",
    "ALLY_PERSONALITY": "Warm > direct",
}
NEW_SOUL = Template(PLATFORM_LAYER_SOUL_TEMPLATE).substitute(VALUES)
OLD_SOUL = Template(LEGACY_SOUL_TEMPLATE).substitute(VALUES)


def test_platform_layer_template_matches_backend_default():
    backend = (
        Path(__file__).resolve().parents[2] / "backend/runtime/default_allies_soul.md"
    )
    assert backend.read_text(encoding="utf-8") == PLATFORM_LAYER_SOUL_TEMPLATE


def test_legacy_soul_is_derived_only_from_exact_managed_renderings():
    assert legacy_soul_for(NEW_SOUL) == OLD_SOUL
    assert legacy_soul_for(NEW_SOUL + "edited") is None
    assert legacy_soul_for(OLD_SOUL) is None
    assert legacy_soul_for("custom soul") is None
    assert make_seed(personality="custom soul").legacy_soul_fingerprint is None


def test_legacy_soul_profile_upgrades_to_platform_layer_soul(tmp_path):
    store = make_store(tmp_path)
    legacy_seed = make_seed(personality=OLD_SOUL)
    assert store.materialize(legacy_seed).status is ProfileProvisionStatus.CREATED
    profile = profile_path(store, legacy_seed)
    (profile / "SOUL.md").write_text("hand-edited soul", encoding="utf-8")
    marker = profile / "sessions" / "preserved"
    marker.write_text("keep", encoding="utf-8")

    seed = make_seed(personality=NEW_SOUL)
    receipt = store.materialize(seed)

    assert receipt.status is ProfileProvisionStatus.EXISTING
    assert (profile / "SOUL.md").read_text(encoding="utf-8") == NEW_SOUL
    assert marker.read_text(encoding="utf-8") == "keep"
    manifest = json.loads((profile / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["seed_fingerprint"] == seed.fingerprint
    assert store.materialize(seed).status is ProfileProvisionStatus.EXISTING


def test_unrelated_personality_change_still_conflicts(tmp_path):
    store = make_store(tmp_path)
    assert store.materialize(make_seed(personality=OLD_SOUL)).status is (
        ProfileProvisionStatus.CREATED
    )
    other = Template(PLATFORM_LAYER_SOUL_TEMPLATE).substitute(
        VALUES | {"ALLY_NAME": "Nova"}
    )
    receipt = store.materialize(make_seed(personality=other))
    assert receipt.status is ProfileProvisionStatus.CONFLICT


def test_missing_manifest_fingerprint_is_not_a_soul_upgrade(tmp_path):
    store = make_store(tmp_path)
    seed = make_seed(personality="custom soul")
    assert store.materialize(seed).status is ProfileProvisionStatus.CREATED
    profile = profile_path(store, seed)
    manifest_path = profile / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["seed_fingerprint"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    receipt = store.materialize(make_seed(personality="another custom soul"))

    assert receipt.status is ProfileProvisionStatus.CONFLICT
    assert (profile / "SOUL.md").read_text(encoding="utf-8") == "custom soul"
