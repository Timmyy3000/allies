"""Verify the Cloud and Foundry publication path with isolated test state."""

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen


def python_path(backend):
    relative = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    path = backend / ".venv" / relative
    if not path.is_file():
        raise SystemExit(f"Locked environment is missing: {path}")
    return str(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundry", type=Path, required=True)
    args = parser.parse_args()
    scripts = Path(__file__).resolve().parent
    cloud = scripts.parents[1] / "backend"
    foundry = args.foundry.resolve()
    backend = foundry / "backend"
    with tempfile.TemporaryDirectory(prefix="allies-file-roundtrip-") as root:
        info = Path(root) / "info.json"
        environment = os.environ.copy()
        environment.pop("DATABASE_URL", None)
        environment.update(
            DJANGO_DEBUG="true",
            PYTHONPATH=str(backend),
            FOUNDRY_RUNTIME_ROOT=str(foundry / "runtime"),
            CLOUD_ROUNDTRIP_INFO=str(info),
        )
        with (Path(root) / "cloud.log").open("w+") as log:
            server = subprocess.Popen(
                [
                    python_path(cloud),
                    str(scripts / "cloud_server.py"),
                    str(cloud),
                    str(info),
                    root,
                ],
                cwd=cloud,
                env=environment,
                stdout=log,
                stderr=log,
            )
            try:
                deadline = time.monotonic() + 60
                while not info.exists():
                    if server.poll() is not None or time.monotonic() >= deadline:
                        log.seek(0)
                        raise RuntimeError(
                            "Test Cloud server did not start: " + log.read()
                        )
                    time.sleep(0.1)
                json.loads(info.read_text())
                result = subprocess.run(
                    [
                        python_path(backend),
                        "-m",
                        "pytest",
                        str(scripts / "foundry_scenario.py"),
                        "-q",
                        "-s",
                        "--ds=config.settings",
                        "--tb=short",
                    ],
                    cwd=backend,
                    env=environment,
                    timeout=180,
                    check=False,
                )
                if result.returncode:
                    log.seek(0)
                    print(log.read())
                return result.returncode
            finally:
                if info.exists():
                    try:
                        with urlopen(
                            json.loads(info.read_text())["url"] + "/test/stop",
                            timeout=5,
                        ) as response:
                            response.read()
                    except OSError:
                        server.terminate()
                else:
                    server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
