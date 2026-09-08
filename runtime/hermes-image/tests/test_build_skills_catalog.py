import importlib.util
import os
import stat
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "build_skills_catalog.py"
SPEC = importlib.util.spec_from_file_location("build_skills_catalog", MODULE_PATH)
catalog = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(catalog)


def _skill(root: Path, key: str, license_name: str | None) -> None:
    path = root / key
    path.mkdir(parents=True)
    license_line = f"license: {license_name}\n" if license_name else ""
    (path / "SKILL.md").write_text(
        f"---\nname: {path.name}\ndescription: fixture\n{license_line}---\n\nBody\n",
        encoding="utf-8",
    )
    (path / "references").mkdir()
    (path / "references" / "guide.md").write_text("support", encoding="utf-8")


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    source = tmp_path / "hermes" / "skills"
    source.mkdir(parents=True)
    _skill(source, "research/allowed", "MIT")
    _skill(source, "software-development/dogfood", None)
    _skill(source, "productivity/docx", "Proprietary")
    (source / "research" / "DESCRIPTION.md").write_text("Research", encoding="utf-8")
    (source / "index-cache").mkdir()
    (source / "index-cache" / "untrusted.json").write_text("office4", encoding="utf-8")
    (tmp_path / "hermes" / "LICENSE").write_text("repository license", encoding="utf-8")
    allies = tmp_path / "allies-skill-discovery"
    allies.mkdir()
    (allies / "SKILL.md").write_text(
        "---\nname: allies-skill-discovery\ndescription: fixture\nlicense: MIT\n---\n",
        encoding="utf-8",
    )
    return source, tmp_path / "catalog", tmp_path / "hermes" / "LICENSE", allies


def test_build_copies_eligible_tree_and_seals_it(tmp_path, monkeypatch):
    source, destination, license_path, allies = _inputs(tmp_path)
    if hasattr(catalog.os, "chown"):
        monkeypatch.setattr(catalog.os, "chown", lambda *_: None)

    inventory = catalog.build_catalog(source, destination, license_path, allies)

    assert {key for key, _ in inventory} == {
        "research/allowed",
        "software-development/dogfood",
    }
    assert (
        destination / "research/allowed/references/guide.md"
    ).read_text() == "support"
    assert (destination / "software-development/dogfood/SKILL.md").exists()
    assert not (destination / "productivity/docx").exists()
    assert (destination / "LICENSE").read_text() == "repository license"
    assert (destination / "allies-skill-discovery/SKILL.md").exists()
    assert (destination / "research/DESCRIPTION.md").read_text() == "Research"
    assert not (destination / "index-cache").exists()
    assert stat.S_IMODE((destination / "research").stat().st_mode) == 0o555
    assert (
        stat.S_IMODE((destination / "research/allowed/SKILL.md").stat().st_mode)
        == 0o444
    )


def test_unknown_provenance_fails_before_install(tmp_path):
    source, destination, license_path, allies = _inputs(tmp_path)
    _skill(source, "unknown/source", "Custom-License")

    with pytest.raises(ValueError, match="unknown license"):
        catalog.build_catalog(source, destination, license_path, allies)

    assert not destination.exists()


def test_unlicensed_skill_outside_pinned_fallback_fails_closed(tmp_path):
    source, destination, license_path, allies = _inputs(tmp_path)
    _skill(source, "research/unlisted", None)

    with pytest.raises(ValueError, match="unknown license"):
        catalog.build_catalog(source, destination, license_path, allies)


def test_symlink_in_eligible_skill_fails_before_install(tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks are unavailable")
    source, destination, license_path, allies = _inputs(tmp_path)
    target = source / "research" / "target.txt"
    target.write_text("target", encoding="utf-8")
    link = source / "research" / "allowed" / "linked.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable")

    with pytest.raises(ValueError, match="symlink"):
        catalog.build_catalog(source, destination, license_path, allies)

    assert not destination.exists()
