"""Run the repository validation checks from any platform."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def run_check(uv: str, label: str, args: list[str]) -> int:
    command = [uv, *args]
    print(f"\n==> {label}: {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=BACKEND, check=False)
    if completed.returncode:
        print(
            f"Validation stopped after {label} (exit {completed.returncode}).",
            file=sys.stderr,
            flush=True,
        )
    return completed.returncode


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        print("Validation requires uv on PATH.", file=sys.stderr)
        return 127

    checks = [
        ("lockfile", ["lock", "--check"]),
        ("Django configuration", ["run", "--locked", "python", "manage.py", "check"]),
        (
            "missing migrations",
            [
                "run",
                "--locked",
                "python",
                "manage.py",
                "makemigrations",
                "--check",
                "--dry-run",
            ],
        ),
        (
            "tests",
            [
                "run",
                "--locked",
                "pytest",
                "--cov=runtime",
                "--cov=devtools",
                "--cov=config",
                "--cov-report=xml:coverage.xml",
            ],
        ),
    ]

    for label, args in checks:
        result = run_check(uv, label, args)
        if result:
            return result
    print("\nValidation passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
