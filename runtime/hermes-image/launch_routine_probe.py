"""Launch the bounded CLD-012 probe against a local inherited-/init image.

This is test tooling only.  It refuses to invent credentials or a provider,
uses the existing socket resolver protocol, and reports setup separately from
real Hermes capability.  The Class B launcher requires Unix-domain sockets;
run it on a Unix-like host or through WSL rather than native Windows Python.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Collection, Sequence
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any
from uuid import uuid4

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

MODEL = os.environ.get("CLD012_MODEL", "gpt-5.6-luna")
SOURCE_COMMIT = "36cb5ae5530a75def7df3195e49b7a4aa2add482"
MAX_TIMEOUT_SECONDS = 60.0
HERMES_REQUEST_TIMEOUT_SECONDS = 30.0
HERMES_STREAM_TIMEOUT_SECONDS = 30.0
PROBE_STAGE_COUNT = 4
PROBE_REQUEST_BUDGET_COUNT = 12
PROBE_EXECUTION_SLACK_SECONDS = 5.0
IMAGE_DIGEST = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$", re.IGNORECASE)
MAX_REFERENCE_BYTES = 256
MAX_CREDENTIAL_REQUEST_BYTES = MAX_REFERENCE_BYTES + 1
MAX_CREDENTIAL_RESPONSE_BYTES = 4096
CLASS_B_REQUIRED_CHECKS = frozenset(
    {
        "authenticated_readiness",
        "model_preflight",
        "real_session_turns",
        "server_observable_barrier",
        "main_and_routine_overlap",
        "main_completion_while_routine_active",
    }
)
CLASS_B_ASSERTION_CHECKS = frozenset(
    {
        "event_identity_attribution",
        "history_canary_isolation",
        "memory_file_observations",
    }
)
CLASS_B_CAPABILITY_CHECKS = (
    CLASS_B_REQUIRED_CHECKS | CLASS_B_ASSERTION_CHECKS | {"session_creation"}
)
PROBE_CHECK_STATUSES = frozenset({"pass", "fail", "blocked"})
PROBE_EXIT_STATUSES = {
    0: "CAPABILITY_PASSED",
    1: "CAPABILITY_FAILED",
    2: "SETUP_BLOCKED",
}
SENSITIVE_ASSIGNMENT_PREFIXES = (
    "API_SERVER_KEY=",
    "ANTHROPIC_API_KEY=",
    "HERMES_CREDENTIAL_REF=",
    "MODEL_PROVIDER_API_KEY=",
    "OPENAI_API_KEY=",
)
Runner = Callable[..., CompletedProcess[str]]


class LaunchBlocked(RuntimeError):
    """A required external setup prerequisite is unavailable."""


def _safe_reason(error: BaseException) -> str:
    return type(error).__name__.lower().replace("error", "") or "setup_blocked"


def _owned_name(kind: str) -> str:
    return f"cld012-{kind}-{uuid4().hex[:12]}"


def _run(runner: Runner, command: Sequence[str], timeout: float) -> CompletedProcess[str]:
    return runner(
        list(command),
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )


def _probe_execution_timeout(timeout_seconds: float) -> float:
    """Budget the launcher for the probe's sequential service stages.

    The service probe has four bounded stream stages (readiness, preflight,
    concurrent turns, and fresh-session recall) plus twelve bounded request
    calls (including the six history checks).  Keep the outer Docker exec
    timeout above that aggregate so a valid late-stage report is not rewritten
    as a launcher timeout.
    """

    stage_budget = max(timeout_seconds, HERMES_STREAM_TIMEOUT_SECONDS)
    return (
        (PROBE_STAGE_COUNT * stage_budget)
        + (PROBE_REQUEST_BUDGET_COUNT * HERMES_REQUEST_TIMEOUT_SECONDS)
        + PROBE_EXECUTION_SLACK_SECONDS
    )


def _succeeded(result: CompletedProcess[str], marker: str | None = None) -> bool:
    if result.returncode != 0:
        return False
    return marker is None or marker in (result.stdout or "")


def _succeeded_with_exact_output(
    result: CompletedProcess[str], expected: str
) -> bool:
    return result.returncode == 0 and (result.stdout or "").strip() == expected


def redact_command(command: Sequence[str]) -> list[str]:
    """Redact opaque references before a command is shown in test evidence."""

    redacted: list[str] = []
    redact_next = False
    for item in command:
        if redact_next:
            redacted.append("<redacted-reference>")
            redact_next = False
        elif item in {"--credential-ref", "--model-profile-ref"}:
            redacted.append(item)
            redact_next = True
        elif item.startswith(SENSITIVE_ASSIGNMENT_PREFIXES) or item.startswith(
            ("--credential-ref=", "--model-profile-ref=")
        ):
            redacted.append(item.split("=", 1)[0] + "=<redacted-reference>")
        else:
            redacted.append(item)
    return redacted


def _validate_reference(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise LaunchBlocked(f"{field_name} reference is required")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise LaunchBlocked(f"{field_name} reference is invalid") from error
    if len(encoded) > MAX_REFERENCE_BYTES:
        raise LaunchBlocked(f"{field_name} reference is oversized")
    if any(char in value for char in "\x00\r\n"):
        raise LaunchBlocked(f"{field_name} reference is invalid")
    if value.lower().startswith(("test://", "file://")):
        raise LaunchBlocked(f"{field_name} fixture or file reference is not permitted")
    return value


def _reference_request(value: str) -> bytes:
    reference = _validate_reference(value, "credential")
    request = (reference + "\n").encode("utf-8")
    if len(request) > MAX_CREDENTIAL_REQUEST_BYTES:
        raise LaunchBlocked("credential reference request is oversized")
    return request


def validate_inputs(
    *,
    image: str,
    credential_ref: str,
    model_profile_ref: str,
    setup_timeout_seconds: float,
    probe_timeout_seconds: float,
    environment: dict[str, str] | None = None,
) -> tuple[str, str, str, Path]:
    """Validate only bounded, opaque inputs before any Docker resource exists."""

    if not IMAGE_DIGEST.fullmatch(image.strip()):
        raise LaunchBlocked("digest-pinned local image is required")
    credential_ref = _validate_reference(credential_ref, "credential")
    model_profile_ref = _validate_reference(model_profile_ref, "model profile")
    for value in (setup_timeout_seconds, probe_timeout_seconds):
        if not 0 < value <= MAX_TIMEOUT_SECONDS:
            raise LaunchBlocked("timeout must be between 0 and 60 seconds")

    values = os.environ if environment is None else environment
    provider = values.get("CLD012_MODEL_PROVIDER", "")
    if not provider or any(char.isspace() for char in provider):
        raise LaunchBlocked("authorized model provider configuration is required")
    upstream_socket = values.get("CLD012_UPSTREAM_CREDENTIAL_SOCKET", "")
    if not upstream_socket or not Path(upstream_socket).is_absolute():
        raise LaunchBlocked("secure upstream credential socket setup is required")
    upstream_path = Path(upstream_socket)
    if not upstream_path.exists() or not hasattr(socket, "AF_UNIX"):
        raise LaunchBlocked("secure upstream credential socket is unavailable")
    return image.strip(), credential_ref, model_profile_ref, upstream_path


class CredentialSocketProxy:
    """Forward opaque references through an owned socket path without storing keys."""

    def __init__(
        self,
        socket_path: Path,
        upstream_path: Path,
        timeout: float,
        allowed_references: Collection[str],
    ) -> None:
        self.socket_path = socket_path
        self.upstream_path = upstream_path
        self.timeout = timeout
        self._allowed_requests = frozenset(
            _reference_request(reference) for reference in allowed_references
        )
        if not self._allowed_requests:
            raise LaunchBlocked("credential reference allowlist is required")
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if not hasattr(socket, "AF_UNIX"):
            raise LaunchBlocked("Unix credential sockets are unavailable")
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            raise LaunchBlocked("owned credential socket path is not empty")
        try:
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(self.socket_path))
            server.listen(4)
            server.settimeout(0.2)
        except OSError as error:
            raise LaunchBlocked("owned credential socket could not start") from error
        self._server = server
        try:
            self.socket_path.chmod(0o600)
        except OSError as error:
            self.close()
            raise LaunchBlocked("owned credential socket permissions could not be set") from error
        self._thread = threading.Thread(target=self._serve, name="cld012-credential-proxy", daemon=True)
        self._thread.start()

    def _resolve(self, reference: bytes) -> bytes | None:
        if len(reference) > MAX_CREDENTIAL_REQUEST_BYTES or reference not in self._allowed_requests:
            return None
        client: socket.socket | None = None
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(self.timeout)
            client.connect(str(self.upstream_path))
            client.sendall(reference)
            received = bytearray()
            while len(received) <= MAX_CREDENTIAL_RESPONSE_BYTES:
                chunk = client.recv(MAX_CREDENTIAL_RESPONSE_BYTES + 1 - len(received))
                if not chunk:
                    break
                received.extend(chunk)
                newline = received.find(b"\n")
                if newline >= 0:
                    if newline + 1 > MAX_CREDENTIAL_RESPONSE_BYTES:
                        return None
                    return bytes(received[: newline + 1])
        except (OSError, TimeoutError):
            return None
        finally:
            if client is not None:
                client.close()
        return None

    def _serve(self) -> None:
        server = self._server
        if server is None:
            return
        while not self._stop.is_set():
            try:
                client, _ = server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with client:
                client.settimeout(self.timeout)
                request = bytearray()
                try:
                    while len(request) <= MAX_CREDENTIAL_REQUEST_BYTES:
                        chunk = client.recv(MAX_CREDENTIAL_REQUEST_BYTES + 1 - len(request))
                        if not chunk:
                            break
                        request.extend(chunk)
                        newline = request.find(b"\n")
                        if newline >= 0:
                            if (
                                newline != len(request) - 1
                                or len(request) > MAX_CREDENTIAL_REQUEST_BYTES
                            ):
                                request.clear()
                            break
                    request_bytes = bytes(request)
                    if request_bytes and request_bytes in self._allowed_requests:
                        response = self._resolve(request_bytes)
                        if response:
                            client.sendall(response)
                except (OSError, TimeoutError):
                    continue

    def close(self) -> None:
        self._stop.set()
        server, self._server = self._server, None
        if server is not None:
            try:
                server.close()
            except OSError:
                pass
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def build_run_command(
    *,
    image: str,
    container_name: str,
    network_name: str,
    data_root: Path,
    data_volume_name: str | None = None,
    socket_root: Path,
    runtime_root: Path,
    probe_path: Path,
    profile_id: str,
    credential_ref: str,
) -> list[str]:
    data_mount = (
        f"type=volume,source={data_volume_name},destination=/opt/data,volume-nocopy"
        if data_volume_name
        else f"type=bind,source={data_root},destination=/opt/data"
    )
    return [
        "docker",
        "run",
        "--detach",
        "--name",
        container_name,
        "--network",
        network_name,
        "--entrypoint",
        "/init",
        "--mount",
        data_mount,
        "--mount",
        f"type=bind,source={socket_root},destination=/run/allies-runtime,readonly",
        "--mount",
        f"type=bind,source={probe_path},destination=/tmp/smoke_routine_sessions.py,readonly",
        "--mount",
        f"type=bind,source={runtime_root},destination=/tmp/allies-runtime,readonly",
        "--env",
        f"HERMES_CREDENTIAL_REF={credential_ref}",
        "--env",
        "HERMES_CREDENTIAL_SOCKET=/run/allies-runtime/hermes-credential.sock",
        "--env",
        "HERMES_ORIGIN=http://127.0.0.1:8642",
        "--env",
        f"HERMES_REQUEST_TIMEOUT={int(HERMES_REQUEST_TIMEOUT_SECONDS)}",
        "--env",
        f"HERMES_STREAM_TIMEOUT={int(HERMES_STREAM_TIMEOUT_SECONDS)}",
        "--env",
        f"CLD012_MODEL={MODEL}",
        "--env",
        "ALLIES_RICH_APPROVALS_ENABLED=false",
        "--env",
        f"CLD012_HERMES_PROFILE_ID={profile_id}",
        image,
        "/opt/hermes/docker/main-wrapper.sh",
        "--profile",
        profile_id,
        "gateway",
        "run",
        "--no-supervise",
    ]


def build_network_command(network_name: str) -> list[str]:
    return [
        "docker",
        "network",
        "create",
        "--label",
        "cld012.owner=probe",
        network_name,
    ]


def build_data_volume_create_command(volume_name: str) -> list[str]:
    return [
        "docker",
        "volume",
        "create",
        "--label",
        "cld012.owner=probe",
        volume_name,
    ]


def build_data_volume_copy_command(
    *, image: str, data_root: Path, data_volume_name: str
) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--user",
        "0",
        "--mount",
        f"type=bind,source={data_root},destination=/src,readonly",
        "--mount",
        f"type=volume,source={data_volume_name},destination=/dest,volume-nocopy",
        "--entrypoint",
        "/bin/sh",
        image,
        "-ec",
        "cp -a /src/. /dest/ && chown -R 10000:10000 /dest && "
        "for env in /dest/profiles/*/.env; do "
        "[ -f \"$env\" ] && chmod 600 \"$env\"; "
        "done",
    ]


def _readiness_command(container_name: str) -> list[str]:
    code = """import asyncio
import os
from allies_runtime.__main__ import probe_readiness
from allies_runtime.config import load_settings
from allies_runtime.hermes import HermesClient
from allies_runtime.profile_store import ProfileStore

async def main():
    values = dict(os.environ)
    settings = load_settings(values)
    profile_id = values.get("CLD012_HERMES_PROFILE_ID", "")
    if not profile_id:
        raise RuntimeError("materialized Hermes profile is required")
    store = ProfileStore(settings.volume_root)

    def resolver(_reference):
        return store.read_api_key(profile_id)

    def profile_resolver(key):
        return store.read_api_key(key)

    client = HermesClient(
        settings,
        resolver,
        profile_credential_resolver=profile_resolver,
    )
    print("READY" if await probe_readiness(client) else "NOT_READY")

asyncio.run(main())
"""
    return [
        "docker",
        "exec",
        "--env",
        "PYTHONPATH=/tmp/allies-runtime",
        container_name,
        "/opt/hermes/.venv/bin/python",
        "-c",
        code,
    ]


def _probe_command(container_name: str, timeout: float) -> list[str]:
    return [
        "docker",
        "exec",
        "--env",
        "PYTHONPATH=/tmp/allies-runtime",
        container_name,
        "/opt/hermes/.venv/bin/python",
        "/tmp/smoke_routine_sessions.py",
        "--mode",
        "service",
        "--timeout-seconds",
        str(int(timeout)),
    ]


def _probe_checks(payload: Any) -> dict[str, str] | None:
    if not isinstance(payload, dict) or payload.get("mode") != "service":
        return None
    checks = payload.get("checks")
    if not isinstance(checks, list) or not checks:
        return None
    observed: dict[str, str] = {}
    for check in checks:
        if not isinstance(check, dict):
            return None
        name = check.get("name")
        status = check.get("status")
        if (
            not isinstance(name, str)
            or not name
            or name in observed
            or not isinstance(status, str)
            or status not in PROBE_CHECK_STATUSES
        ):
            return None
        observed[name] = status
    return observed


def _validated_probe_report(payload: Any, returncode: int | None) -> dict[str, str] | None:
    """Validate the service report and its process-status contract together."""

    checks = _probe_checks(payload)
    if checks is None or not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if not isinstance(status, str):
        return None
    expected_status = PROBE_EXIT_STATUSES.get(returncode)
    early_statuses = {"READINESS_FAILED", "MODEL_PREFLIGHT_FAILED"}
    if status in early_statuses:
        if returncode != 1:
            return None
    elif status != expected_status:
        return None

    if status == "READINESS_FAILED":
        if checks != {"authenticated_readiness": "fail"}:
            return None
        return checks
    if status == "MODEL_PREFLIGHT_FAILED":
        if checks != {
            "authenticated_readiness": "pass",
            "model_preflight": "fail",
        }:
            return None
        return checks
    if status == "CAPABILITY_PASSED":
        return (
            checks
            if CLASS_B_REQUIRED_CHECKS <= checks.keys()
            and all(value == "pass" for value in checks.values())
            else None
        )
    if status == "CAPABILITY_FAILED":
        if not checks.keys() <= CLASS_B_CAPABILITY_CHECKS:
            return None
        if not {"authenticated_readiness", "model_preflight"} <= checks.keys():
            return None
        if checks["authenticated_readiness"] != "pass" or checks[
            "model_preflight"
        ] != "pass" or all(value == "pass" for value in checks.values()):
            return None
        return checks
    if status == "SETUP_BLOCKED":
        return checks if any(value != "pass" for value in checks.values()) else None
    return None


def _has_class_b_evidence(payload: Any) -> bool:
    """Retain the focused capability predicate for callers and unit tests."""

    return _validated_probe_report(payload, 0) is not None


def _materialize_profile(
    data_root: Path,
    socket_path: Path,
    model_profile_ref: str,
    *,
    provider: str,
    base_url: str | None,
) -> str:
    try:
        from allies_runtime.hermes import UnixSocketCredentialResolver
        from allies_runtime.profile_store import (
            ProfileProvisionStatus,
            ProfileSeed,
            ProfileStore,
            ProfileStoreError,
        )
    except (ImportError, AttributeError) as error:
        raise LaunchBlocked("profile materialization runtime is unavailable") from error

    credential_name = _model_credential_name(provider)
    profile_id = uuid4()
    seed = ProfileSeed(
        foundry_profile_id=profile_id,
        ally_name="cld012-synthetic-ally",
        personality="Synthetic CLD-012 feasibility profile.",
        provider=provider,
        model=MODEL,
        first_chat_instruction="Use only the authorized tools for this bounded synthetic probe.",
        credential_refs={credential_name: model_profile_ref},
        base_url=base_url,
        memory_mode="narrow_tools",
        memory_tool_allowlist=("mnemosyne_recall", "mnemosyne_remember"),
        memory_profile_isolation=True,
        operation_id="cld012-live-probe",
    )
    store = ProfileStore(
        data_root,
        credential_resolver=UnixSocketCredentialResolver(str(socket_path)),
    )
    try:
        receipt = store.materialize(seed)
    except ProfileStoreError as error:
        raise LaunchBlocked("synthetic profile materialization failed") from error
    if receipt.status not in {ProfileProvisionStatus.CREATED, ProfileProvisionStatus.EXISTING}:
        raise LaunchBlocked("synthetic profile materialization was not accepted")
    return seed.hermes_profile_key or ""


def _wait_for_readiness(runner: Runner, container_name: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = min(5.0, max(0.1, deadline - time.monotonic()))
        try:
            result = _run(runner, _readiness_command(container_name), remaining)
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None and _succeeded_with_exact_output(result, "READY"):
            return True
    return False


def _model_credential_name(provider: str) -> str:
    return (
        "GH_TOKEN"
        if provider.strip().lower() == "copilot"
        else "MODEL_PROVIDER_API_KEY"
    )


def _cleanup_succeeded(result: CompletedProcess[str], resource: str) -> bool:
    if _succeeded(result):
        return True
    output = f"{result.stdout or ''}\n{result.stderr or ''}".casefold()
    absence_markers = {
        "container": ("no such container", "container not found"),
        "network": ("no such network", "network not found"),
        "volume": ("no such volume", "volume not found"),
    }
    return any(marker in output for marker in absence_markers[resource])


def _cleanup(
    runner: Runner,
    container_name: str | None,
    network_name: str | None,
    data_volume_name: str | None,
    timeout: float,
) -> bool:
    outcomes: list[bool] = []
    for resource, command in (
        (
            "container",
            ["docker", "rm", "--force", container_name] if container_name else None,
        ),
        (
            "network",
            ["docker", "network", "rm", network_name] if network_name else None,
        ),
        (
            "volume",
            ["docker", "volume", "rm", data_volume_name]
            if data_volume_name
            else None,
        ),
    ):
        if command is None:
            continue
        try:
            outcomes.append(
                _cleanup_succeeded(_run(runner, command, timeout), resource)
            )
        except (OSError, subprocess.TimeoutExpired):
            outcomes.append(False)
    return all(outcomes)


def run_probe(
    *,
    image: str,
    credential_ref: str,
    model_profile_ref: str,
    setup_timeout_seconds: float = MAX_TIMEOUT_SECONDS,
    probe_timeout_seconds: float = MAX_TIMEOUT_SECONDS,
    runner: Runner = subprocess.run,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run setup/readiness/probe with owned resources and sanitized outcomes."""

    report: dict[str, Any] = {
        "episode": "CLD-012",
        "model": MODEL,
        "source_commit": SOURCE_COMMIT,
        "image": image,
        "setup": "pending",
        "readiness": "pending",
        "model_preflight": "pending",
        "capability": "pending",
        "cleanup": "not_needed",
    }
    container_name: str | None = None
    network_name: str | None = None
    data_volume_name: str | None = None
    proxy: CredentialSocketProxy | None = None
    cleanup_done = False
    try:
        image, credential_ref, model_profile_ref, upstream_socket = validate_inputs(
            image=image,
            credential_ref=credential_ref,
            model_profile_ref=model_profile_ref,
            setup_timeout_seconds=setup_timeout_seconds,
            probe_timeout_seconds=probe_timeout_seconds,
            environment=environment,
        )
        values = os.environ if environment is None else environment
        if shutil.which("docker") is None:
            raise LaunchBlocked("docker is unavailable")
        version = _run(runner, ["docker", "version", "--format", "{{.Server.Version}}"], 5)
        if not _succeeded(version):
            raise LaunchBlocked("docker daemon is unavailable")
        inspect = _run(
            runner,
            [
                "docker",
                "image",
                "inspect",
                "--format",
                "{{index .Config.Labels \"org.opencontainers.image.revision\"}}",
                image,
            ],
            setup_timeout_seconds,
        )
        if not _succeeded_with_exact_output(inspect, SOURCE_COMMIT):
            raise LaunchBlocked("local image source pin is not verified")

        with tempfile.TemporaryDirectory(prefix="cld012-launch-") as temporary:
            root = Path(temporary)
            data_root = root / "data"
            socket_root = root / "socket"
            data_root.mkdir()
            socket_root.mkdir()
            socket_path = socket_root / "hermes-credential.sock"
            proxy = CredentialSocketProxy(
                socket_path,
                upstream_socket,
                min(setup_timeout_seconds, 5.0),
                (credential_ref, model_profile_ref),
            )
            proxy.start()
            profile_id = _materialize_profile(
                data_root,
                socket_path,
                model_profile_ref,
                provider=values.get("CLD012_MODEL_PROVIDER", ""),
                base_url=values.get("CLD012_MODEL_BASE_URL"),
            )
            runtime_root = RUNTIME_ROOT
            probe_path = Path(__file__).with_name("smoke_routine_sessions.py")
            network_name = _owned_name("network")
            network = _run(
                runner,
                build_network_command(network_name),
                setup_timeout_seconds,
            )
            if not _succeeded(network):
                raise LaunchBlocked("owned isolated network could not be created")
            data_volume_name = _owned_name("data")
            volume = _run(
                runner,
                build_data_volume_create_command(data_volume_name),
                setup_timeout_seconds,
            )
            if not _succeeded(volume):
                raise LaunchBlocked("owned data volume could not be created")
            copied = _run(
                runner,
                build_data_volume_copy_command(
                    image=image,
                    data_root=data_root,
                    data_volume_name=data_volume_name,
                ),
                setup_timeout_seconds,
            )
            if not _succeeded(copied):
                raise LaunchBlocked(
                    "materialized profile could not be copied into data volume"
                )
            container_name = _owned_name("hermes")
            run_result = _run(
                runner,
                build_run_command(
                    image=image,
                    container_name=container_name,
                    network_name=network_name,
                    data_root=data_root,
                    data_volume_name=data_volume_name,
                    socket_root=socket_root,
                    runtime_root=runtime_root,
                    probe_path=probe_path,
                    profile_id=profile_id,
                    credential_ref=credential_ref,
                ),
                setup_timeout_seconds,
            )
            if not _succeeded(run_result):
                raise LaunchBlocked("inherited /init container did not start")
            report["setup"] = "passed"
            if not _wait_for_readiness(runner, container_name, setup_timeout_seconds):
                report.update(
                    status="SETUP_BLOCKED",
                    readiness="failed",
                    reason="authenticated_readiness_unavailable",
                )
            else:
                report["readiness"] = "passed"
                try:
                    probe = _run(
                        runner,
                        _probe_command(container_name, probe_timeout_seconds),
                        _probe_execution_timeout(probe_timeout_seconds),
                    )
                except (OSError, subprocess.TimeoutExpired) as error:
                    report.update(
                        status="SETUP_BLOCKED",
                        reason=(
                            "probe_timeout"
                            if isinstance(error, subprocess.TimeoutExpired)
                            else _safe_reason(error)
                        ),
                    )
                else:
                    payload = None
                    for line in reversed((probe.stdout or "").splitlines()):
                        try:
                            candidate = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(candidate, dict):
                            payload = candidate
                            break
                    checks = _validated_probe_report(payload, probe.returncode)
                    if checks is None:
                        report.update(
                            status="SETUP_BLOCKED",
                            reason="class_b_evidence_incomplete",
                        )
                    else:
                        capability_status = payload["status"]
                        if checks.get("authenticated_readiness") == "fail":
                            report["readiness"] = "failed"
                        if "model_preflight" in checks:
                            report["model_preflight"] = (
                                "passed"
                                if checks["model_preflight"] == "pass"
                                else "failed"
                            )
                        if capability_status in {"CAPABILITY_PASSED", "CAPABILITY_FAILED"}:
                            report["capability"] = (
                                "passed"
                                if capability_status == "CAPABILITY_PASSED"
                                else "failed"
                            )
                            report["status"] = capability_status
                        else:
                            report.update(
                                status="SETUP_BLOCKED", reason="probe_setup_blocked"
                            )
            report["cleanup"] = (
                "passed"
                if _cleanup(
                    runner,
                    container_name,
                    network_name,
                    data_volume_name,
                    5.0,
                )
                else "failed"
            )
            cleanup_done = True
            if report["cleanup"] == "failed":
                report["status"] = "CLEANUP_INCOMPLETE"
    except (LaunchBlocked, OSError, subprocess.TimeoutExpired, TypeError, ValueError) as error:
        report.update(status="SETUP_BLOCKED", setup="blocked", reason=_safe_reason(error))
    finally:
        if not cleanup_done and (
            container_name or network_name or data_volume_name
        ):
            report["cleanup"] = (
                "passed"
                if _cleanup(
                    runner,
                    container_name,
                    network_name,
                    data_volume_name,
                    5.0,
                )
                else "failed"
            )
            if report["cleanup"] == "failed":
                report["status"] = "CLEANUP_INCOMPLETE"
        if proxy is not None:
            proxy.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the bounded CLD-012 routine probe")
    parser.add_argument("--image", required=True)
    parser.add_argument("--credential-ref", required=True)
    parser.add_argument("--model-profile-ref", required=True)
    parser.add_argument("--setup-timeout-seconds", type=float, default=MAX_TIMEOUT_SECONDS)
    parser.add_argument("--probe-timeout-seconds", type=float, default=MAX_TIMEOUT_SECONDS)
    args = parser.parse_args()
    report = run_probe(
        image=args.image,
        credential_ref=args.credential_ref,
        model_profile_ref=args.model_profile_ref,
        setup_timeout_seconds=args.setup_timeout_seconds,
        probe_timeout_seconds=args.probe_timeout_seconds,
    )
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report.get("status") == "CAPABILITY_PASSED" else 2 if report.get("status") == "SETUP_BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
