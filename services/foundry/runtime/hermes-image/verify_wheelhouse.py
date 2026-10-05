"""Verify every locked wheel before the minimal offline image install."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ENTRY = re.compile(
    r"(?m)^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+) \\\r?\n"
    r"\s+--hash=sha256:([0-9a-f]{64})$"
)


def normalized(value: str) -> str:
    return re.sub(r"[-_.]+", "_", value).lower()


def verify(lock_path: Path, wheelhouse: Path) -> None:
    lock_text = lock_path.read_text(encoding="utf-8")
    entries = ENTRY.findall(lock_text)
    if not entries or ENTRY.sub("", lock_text).strip():
        raise ValueError("requirements lock has an unsupported shape")
    wheels = tuple(wheelhouse.glob("*.whl"))
    if len(wheels) != len(entries):
        raise ValueError("wheelhouse does not exactly match the lock")
    used: set[Path] = set()
    for name, version, expected in entries:
        prefix = f"{normalized(name)}_{normalized(version)}"
        matches = [
            wheel for wheel in wheels if normalized(wheel.name).startswith(prefix + "_")
        ]
        if len(matches) != 1 or matches[0] in used:
            raise ValueError(f"locked wheel is missing or ambiguous: {name}")
        wheel = matches[0]
        actual = hashlib.sha256(wheel.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"locked wheel hash mismatch: {name}")
        used.add(wheel)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_wheelhouse.py LOCK WHEELHOUSE")
    verify(Path(sys.argv[1]), Path(sys.argv[2]))
