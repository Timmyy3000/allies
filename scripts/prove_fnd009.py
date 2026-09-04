"""Run the repeatable Docker + local Interface FND-009 proof.

The runner owns one uniquely named Compose project per backend, starts only
the service commands already used by local/Railway Compose, and removes those
exact projects, volumes, and networks in a finally block.  It never calls a
real provider or a deployment API.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from fnd009_common import (
    ALLY_A_ID,
    ALLY_B_ID,
    CLOUD_SERVICE_TOKEN,
    CONVERSATION_B_ID,
    EVENT_SERVICE_TOKEN,
    PROOF_TOKEN,
    RUNTIME_TOKEN,
    USER_ID,
    WORKSPACE_ID,
)


class ProofFailure(RuntimeError):
    pass


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _repository_root(worktree: Path, repository: str, *, web: bool = False) -> Path:
    current = worktree.resolve()
    source_repo = next(
        (candidate for candidate in (current, *current.parents) if candidate.name == "allies-foundry"),
        None,
    )
    if source_repo is not None:
        base = source_repo.parent
        suffix = [".forest", "worktrees"]
        suffix.extend(["web", "ft"] if web else ["ft"])
        suffix.append(current.name)
        return base / repository / Path(*suffix)
    raise ProofFailure(f"could not derive {repository} worktree from {worktree}")


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    check: bool = True,
    quiet: bool = False,
) -> subprocess.CompletedProcess[str]:
    if not quiet:
        print("+", " ".join(command), flush=True)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr).strip()
        raise ProofFailure(
            f"command failed ({result.returncode}): {' '.join(command)}\n{detail[-6000:]}"
        )
    if not quiet and result.stdout.strip():
        print(result.stdout.rstrip(), flush=True)
    if not quiet and result.stderr.strip():
        print(result.stderr.rstrip(), file=sys.stderr, flush=True)
    return result


def _compose(
    root: Path,
    project: str,
    env: dict[str, str],
    *arguments: str,
    check: bool = True,
    quiet: bool = False,
) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "docker",
            "compose",
            "-p",
            project,
            "-f",
            "compose.yaml",
            "-f",
            "compose.fnd009.yaml",
            *arguments,
        ],
        cwd=root,
        env=env,
        check=check,
        quiet=quiet,
    )


def _http_ready(url: str, timeout: float = 3.0) -> bool:
    try:
        with urlopen(url, timeout=timeout) as response:
            return 200 <= int(response.status) < 300
    except (OSError, URLError):
        return False


def _wait_http(url: str, *, seconds: int = 90) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _http_ready(url):
            return
        time.sleep(1)
    raise ProofFailure(f"service did not become ready: {url}")


def _seed(root: Path, project: str, env: dict[str, str], command: list[str]) -> None:
    _compose(
        root,
        project,
        env,
        "run",
        "--rm",
        "--no-deps",
        "--entrypoint",
        "uv",
        *command,
    )


def _compose_cleanup(
    root: Path,
    project: str,
    network: str,
    env: dict[str, str],
) -> None:
    _compose(
        root,
        project,
        env,
        "down",
        "--volumes",
        "--remove-orphans",
        check=False,
        quiet=True,
    )
    _run(
        ["docker", "network", "rm", network],
        cwd=root,
        env=env,
        check=False,
        quiet=True,
    )
    leftovers = _run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ],
        cwd=root,
        env=env,
        check=False,
        quiet=True,
    ).stdout.strip()
    if leftovers:
        raise ProofFailure(f"exact Compose cleanup left containers for {project}")
    networks = _run(
        ["docker", "network", "ls", "-q", "--filter", f"name=^{network}$"],
        cwd=root,
        env=env,
        check=False,
        quiet=True,
    ).stdout.strip()
    if networks:
        raise ProofFailure(f"exact Compose cleanup left network {network}")


def _start_interface(
    root: Path,
    port: int,
    cloud_url: str,
    env: dict[str, str],
) -> tuple[subprocess.Popen[bytes], Path]:
    log_handle = tempfile.NamedTemporaryFile(
        mode="wb", prefix="fnd009-interface-", suffix=".log", delete=False
    )
    log_path = Path(log_handle.name)
    process_env = dict(env)
    process_env.update(
        {
            "NEXT_PUBLIC_CLOUD_API_URL": cloud_url,
            "NEXT_PUBLIC_ACTIVITY_SSE_ENABLED": "true",
            "NEXT_PUBLIC_WAITLIST_ENABLED": "false",
            "NEXT_PUBLIC_SITE_URL": f"http://127.0.0.1:{port}",
        }
    )
    process = subprocess.Popen(
        [
            "bun",
            "--filter",
            "web",
            "dev",
            "--hostname",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=root,
        env=process_env,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    log_handle.close()
    return process, log_path


def _playwright(
    root: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "bunx",
            "playwright",
            "test",
            "-c",
            "apps/web/playwright.fnd009.config.ts",
        ],
        cwd=root,
        env=env,
    )


def _last_json_line(output: str) -> dict[str, object]:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise ProofFailure("proof inspection did not return a JSON object")


def _inspect_backend(
    root: Path,
    project: str,
    env: dict[str, str],
    service: str,
    uv_arguments: list[str],
) -> dict[str, object]:
    result = _compose(
        root,
        project,
        env,
        "exec",
        "-T",
        service,
        "uv",
        *uv_arguments,
        quiet=True,
    )
    return _last_json_line(result.stdout)


def _simulator_snapshot(port: int) -> dict[str, object]:
    request = Request(
        f"http://127.0.0.1:{port}/snapshot",
        headers={"Authorization": f"Bearer {PROOF_TOKEN}"},
    )
    with urlopen(request, timeout=3) as response:
        value = json.loads(response.read())
    if not isinstance(value, dict):
        raise ProofFailure("simulator snapshot was not a JSON object")
    return value


def _collect_evidence(
    foundry_root: Path,
    cloud_root: Path,
    foundry_project: str,
    cloud_project: str,
    simulator_port: int,
    env: dict[str, str],
    *,
    validate: bool = True,
) -> dict[str, object]:
    foundry = _inspect_backend(
        foundry_root,
        foundry_project,
        env,
        "foundry",
        ["run", "--no-sync", "python", "/proof/inspect_fnd009.py"],
    )
    cloud = _inspect_backend(
        cloud_root,
        cloud_project,
        env,
        "backend",
        ["run", "python", "/proof/inspect_fnd009.py"],
    )
    simulator = _simulator_snapshot(simulator_port)
    if validate and not (
        simulator.get("machine_state") == "stopped"
        and simulator.get("starts") == 3
        and simulator.get("stops") == 3
        and simulator.get("claims") == 3
        and simulator.get("completed") == 3
        and simulator.get("errors") == 0
        and foundry.get("execution_count") == 3
        and foundry.get("attempt_count") == 3
        and foundry.get("lease_count") == 3
        and foundry.get("event_count") == foundry.get("delivery_count")
        and cloud.get("activity_count", 0) > 0
        and "completed" in cloud.get("message_statuses", [])
    ):
        raise ProofFailure("final proof state did not satisfy FND-009 invariants")
    return {"foundry": foundry, "cloud": cloud, "provider": simulator}


def _stop_interface(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundry-root", type=Path, default=Path.cwd())
    parser.add_argument("--cloud-root", type=Path)
    parser.add_argument("--interface-root", type=Path)
    parser.add_argument("--keep-warm-seconds", type=int, default=8)
    parser.add_argument("--skip-playwright", action="store_true")
    parser.add_argument("--no-cleanup", action="store_true")
    args = parser.parse_args()

    foundry_root = args.foundry_root.resolve()
    cloud_root = (args.cloud_root or _repository_root(foundry_root, "allies-cloud")).resolve()
    interface_root = (
        args.interface_root
        or _repository_root(foundry_root, "allies-interface", web=True)
    ).resolve()
    if args.keep_warm_seconds < 2:
        raise ProofFailure("--keep-warm-seconds must be at least 2")
    for root, required in (
        (foundry_root, "compose.yaml"),
        (cloud_root, "compose.yaml"),
        (interface_root, "apps/web/package.json"),
    ):
        if not (root / required).exists():
            raise ProofFailure(f"missing {required} under {root.name}")
    if shutil.which("docker") is None or shutil.which("bunx") is None:
        raise ProofFailure("docker and bunx are required for the proof")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = f"{os.getpid():x}"
    foundry_project = f"fnd009-foundry-{stamp}-{suffix}"[:63]
    cloud_project = f"fnd009-cloud-{stamp}-{suffix}"[:63]
    foundry_network = f"{foundry_project}-net"[:63]
    cloud_network = f"{cloud_project}-net"[:63]
    foundry_port = _free_port()
    cloud_port = _free_port()
    simulator_port = _free_port()
    interface_port = _free_port()

    common_env = dict(os.environ)
    common_env.update(
        {
            "FND009_KEEP_WARM_SECONDS": str(args.keep_warm_seconds),
            "FND009_FOUNDRY_PORT": str(foundry_port),
            "FND009_CLOUD_PORT": str(cloud_port),
            "FND009_SIMULATOR_PORT": str(simulator_port),
            "FND009_INTERFACE_PORT": str(interface_port),
            "FND009_FOUNDRY_NETWORK": foundry_network,
            "FND009_CLOUD_NETWORK": cloud_network,
        }
    )
    playwright_env = dict(common_env)
    playwright_env.update(
        {
            "PW_BASE_URL": f"http://127.0.0.1:{interface_port}",
            "FND009_CLOUD_URL": f"http://127.0.0.1:{cloud_port}",
            "FND009_SIMULATOR_URL": f"http://127.0.0.1:{simulator_port}",
            "FND009_PROOF_TOKEN": PROOF_TOKEN,
            "FND009_WORKSPACE_ID": str(WORKSPACE_ID),
            "FND009_ALLY_A_ID": str(ALLY_A_ID),
            "FND009_ALLY_B_ID": str(ALLY_B_ID),
            "FND009_CONVERSATION_B_ID": str(CONVERSATION_B_ID),
        }
    )

    interface_process: subprocess.Popen[bytes] | None = None
    interface_log: Path | None = None
    foundry_clean = cloud_clean = False
    started = time.monotonic()
    result: dict[str, object] = {"status": "failed"}
    exit_code = 1
    try:
        _compose(foundry_root, foundry_project, common_env, "config", "--quiet")
        _compose(cloud_root, cloud_project, common_env, "config", "--quiet")
        _compose(foundry_root, foundry_project, common_env, "build")
        _compose(cloud_root, cloud_project, common_env, "build")

        _compose(
            foundry_root,
            foundry_project,
            common_env,
            "up",
            "-d",
            "--wait",
            "postgres",
        )
        _compose(
            cloud_root,
            cloud_project,
            common_env,
            "up",
            "-d",
            "--wait",
            "postgres",
            "redis",
        )
        _seed(
            foundry_root,
            foundry_project,
            common_env,
            ["migrate", "run", "--no-sync", "python", "manage.py", "migrate", "--noinput"],
        )
        _seed(
            cloud_root,
            cloud_project,
            common_env,
            ["migrate", "run", "python", "manage.py", "migrate", "--noinput"],
        )
        _seed(
            foundry_root,
            foundry_project,
            common_env,
            ["migrate", "run", "--no-sync", "python", "/proof/seed_fnd009.py"],
        )
        _seed(
            cloud_root,
            cloud_project,
            common_env,
            ["migrate", "run", "python", "/proof/seed_fnd009.py"],
        )
        _compose(cloud_root, cloud_project, common_env, "up", "-d", "backend", "worker", "beat")
        _wait_http(f"http://127.0.0.1:{cloud_port}/api/v1/health")
        _compose(
            foundry_root,
            foundry_project,
            common_env,
            "up",
            "-d",
            "foundry",
            "fly-simulator",
        )
        _wait_http(f"http://127.0.0.1:{foundry_port}/healthz")
        _wait_http(f"http://127.0.0.1:{simulator_port}/healthz")
        _compose(
            foundry_root,
            foundry_project,
            common_env,
            "up",
            "-d",
            "event-publisher",
        )

        if args.skip_playwright:
            result["status"] = "preflight-ready"
        else:
            interface_process, interface_log = _start_interface(
                interface_root,
                interface_port,
                f"http://127.0.0.1:{cloud_port}",
                common_env,
            )
            _wait_http(f"http://127.0.0.1:{interface_port}")
            _playwright(interface_root, playwright_env)
            result["evidence"] = _collect_evidence(
                foundry_root,
                cloud_root,
                foundry_project,
                cloud_project,
                simulator_port,
                common_env,
            )
            result["status"] = "passed"
        result["elapsed_seconds"] = round(time.monotonic() - started, 1)
        exit_code = 0
    except (ProofFailure, OSError, subprocess.SubprocessError) as exc:
        result["error"] = str(exc)
        result["debug"] = {
            "foundry_project": foundry_project,
            "cloud_project": cloud_project,
            "ports": {
                "foundry": foundry_port,
                "cloud": cloud_port,
                "simulator": simulator_port,
                "interface": interface_port,
            },
        }
        try:
            result["diagnostics"] = _collect_evidence(
                foundry_root,
                cloud_root,
                foundry_project,
                cloud_project,
                simulator_port,
                common_env,
                validate=False,
            )
        except (ProofFailure, OSError, subprocess.SubprocessError, URLError):
            pass
        if interface_log is not None and interface_log.exists():
            result["interface_log_tail"] = interface_log.read_text(errors="replace")[-4000:]
    finally:
        if interface_process is not None:
            _stop_interface(interface_process)
        if not args.no_cleanup:
            cleanup_errors = []
            for name, root, project, network in (
                ("foundry", foundry_root, foundry_project, foundry_network),
                ("cloud", cloud_root, cloud_project, cloud_network),
            ):
                try:
                    _compose_cleanup(root, project, network, common_env)
                    if name == "foundry":
                        foundry_clean = True
                    else:
                        cloud_clean = True
                except ProofFailure as exc:
                    cleanup_errors.append(str(exc))
            result["cleanup"] = {
                "foundry": foundry_clean,
                "cloud": cloud_clean,
            }
            if cleanup_errors:
                result["status"] = "failed"
                result["cleanup_errors"] = cleanup_errors
                exit_code = 1
        if interface_log is not None:
            interface_log.unlink(missing_ok=True)
    print(
        json.dumps(result, sort_keys=True),
        file=sys.stdout if exit_code == 0 else sys.stderr,
        flush=True,
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
