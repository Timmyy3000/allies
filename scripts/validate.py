"""Run the repository validation checks from any platform."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
RUNTIME = ROOT / "runtime"


def run_check(
    uv: str,
    label: str,
    args: list[str],
    *,
    cwd: Path = ROOT,
) -> int:
    command = [uv, *args]
    print(f"\n==> {label}: {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=cwd, check=False)
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
        ("backend lockfile", ["lock", "--check"], BACKEND),
        ("runtime lockfile", ["lock", "--check"], RUNTIME),
        (
            "Django configuration",
            ["run", "--locked", "python", "manage.py", "check"],
            BACKEND,
        ),
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
            BACKEND,
        ),
        (
            "backend tests",
            [
                "run",
                "--locked",
                "pytest",
                "--cov=runtime",
                "--cov=devtools",
                "--cov=config",
                "--cov-report=xml:coverage.xml",
            ],
            BACKEND,
        ),
        (
            "runtime tests",
            [
                "run",
                "--locked",
                "pytest",
                "--cov=allies_runtime",
                "--cov-report=xml:coverage.xml",
            ],
            RUNTIME,
        ),
    ]

    for label, args, cwd in checks:
        result = run_check(uv, label, args, cwd=cwd)
        if result:
            return result
    print("\nValidation passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
