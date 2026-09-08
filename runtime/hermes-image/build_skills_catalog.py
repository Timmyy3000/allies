"""Build the immutable Allies skill catalog from the pinned Hermes image."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import yaml

RESTRICTED_SKILLS = frozenset({"docx", "xlsx", "pdf", "powerpoint"})
INHERITED_MIT_SKILLS = frozenset(
    {
        "autonomous-ai-agents/computer-use",
        "creative/ascii-video",
        "creative/manim-video",
        "creative/p5js",
        "creative/songwriting-and-ai-music",
        "media/youtube-content",
        "note-taking/obsidian",
        "research/polymarket",
        "software-development/dogfood",
    }
)


def _frontmatter_license(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")[:65_536]
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    metadata = yaml.safe_load(text[3:end]) or {}
    value = metadata.get("license") if isinstance(metadata, dict) else None
    return value if isinstance(value, str) else None


def _validate_skill(source: Path, skill_file: Path) -> tuple[str, str]:
    key = skill_file.parent.relative_to(source).as_posix()
    license_name = _frontmatter_license(skill_file)
    if license_name is None and key in INHERITED_MIT_SKILLS:
        return key, "MIT (repository inheritance)"
    if license_name != "MIT":
        raise ValueError(f"skill has incompatible or unknown license: {key}")
    return key, license_name


def _reject_symlinks(root: Path) -> None:
    if root.is_symlink():
        raise ValueError(f"symlink is not allowed in skill tree: {root}")
    for directory, subdirectories, files in os.walk(root, followlinks=False):
        for name in [*subdirectories, *files]:
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError(f"symlink is not allowed in skill tree: {path}")


def _seal(root: Path) -> None:
    """Make catalog paths root-owned and unwritable by runtime UID 10000."""
    for directory, subdirectories, files in os.walk(root):
        for name in subdirectories:
            path = Path(directory) / name
            if hasattr(os, "chown"):
                os.chown(path, 0, 0)
            path.chmod(0o555)
        for name in files:
            path = Path(directory) / name
            if hasattr(os, "chown"):
                os.chown(path, 0, 0)
            executable = bool(path.stat().st_mode & stat.S_IXUSR)
            path.chmod(0o555 if executable else 0o444)
    if hasattr(os, "chown"):
        os.chown(root, 0, 0)
    root.chmod(0o555)


def build_catalog(
    source: Path,
    destination: Path,
    repository_license: Path,
    allies_skill: Path,
) -> list[tuple[str, str]]:
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_dir() or not repository_license.is_file():
        raise ValueError("catalog source and repository license must exist")
    if destination == source or destination.is_relative_to(source):
        raise ValueError("catalog destination must be outside the source tree")
    if destination.exists():
        raise ValueError(f"catalog destination already exists: {destination}")
    if not allies_skill.is_dir() or not (allies_skill / "SKILL.md").is_file():
        raise ValueError("Allies discovery skill is missing")
    if _frontmatter_license(allies_skill / "SKILL.md") != "MIT":
        raise ValueError("Allies discovery skill must carry an MIT license")
    _reject_symlinks(allies_skill)

    eligible = []
    for skill_file in sorted(source.rglob("SKILL.md")):
        if skill_file.parent.name in RESTRICTED_SKILLS and (
            skill_file.parent.parent.name == "productivity"
        ):
            continue
        entry = _validate_skill(source, skill_file)
        _reject_symlinks(skill_file.parent)
        eligible.append((skill_file, entry))

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    categories = {skill_file.parent.parent for skill_file, _ in eligible}
    for skill_file, _ in eligible:
        key = skill_file.parent.relative_to(source)
        target = destination / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_file.parent, target)
    for category in categories:
        description = category / "DESCRIPTION.md"
        if description.is_file():
            if description.is_symlink():
                raise ValueError(f"symlink is not allowed in category: {description}")
            target = destination / category.relative_to(source)
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(description, target / description.name)
    shutil.copy2(repository_license, destination / "LICENSE")
    shutil.copytree(allies_skill, destination / allies_skill.name)
    _seal(destination)
    return [entry for _, entry in eligible]


if __name__ == "__main__":
    found = build_catalog(
        Path("/opt/hermes/skills"),
        Path("/opt/allies/skills"),
        Path("/opt/hermes/LICENSE"),
        Path("/tmp/allies-skill-discovery"),
    )
    print(f"Built {len(found)} eligible Hermes skills at /opt/allies/skills")
