"""Single-host workspace provider backed by the local Docker Engine API.

Self-hosted deployments run each workspace "Machine" as two containers on the
same host: ``<machine>`` (Hermes) and ``<machine>-runtime`` (allies-runtime),
with the runtime sharing Hermes's network namespace exactly like the Fly
multi-container Machine. The workspace Volume is a Docker named volume.

Secrets never touch Docker objects at rest beyond container env: the
``DockerSecretStore`` keeps decoded values in a root-only host directory and
the provider hands each container the base64 value as the env var named by
its secret, which the container commands decode into ``/run/secrets``.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import re
import shutil
import socket
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from uuid import uuid4

from .domain import (
    AppRecord,
    AppSpec,
    ContainerState,
    MachineHealth,
    MachineRecord,
    MachineSpec,
    MachineState,
    OwnershipMetadata,
    VolumeRecord,
    VolumeSpec,
)
from .errors import (
    ProviderConflictError,
    ProviderInvalidConfigurationError,
    ProviderNotFoundError,
    ProviderProtocolError,
    ProviderRetryableError,
    ProviderTimeoutError,
)

_OWNER = "allies.owner"
_APP = "allies.app"
_MACHINE = "allies.machine"
_ROLE = "allies.role"
_WORKSPACE = "allies.workspace_id"
_OPERATION = "allies.operation_id"
_GENERATION = "allies.generation"
_REGION = "allies.region"
_SIZE = "allies.size_gb"
_OWNER_VALUE = "foundry"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SAFE_SECRET = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_RUNTIME_SUFFIX = "-runtime"
_STOP_SECONDS = 20
# bwrap inside Hermes needs nested namespaces and mounts; Fly provides a VM.
_HERMES_SECURITY = ["seccomp=unconfined", "apparmor=unconfined", "systempaths=unconfined"]


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


class DockerEngine:
    """Minimal Docker Engine API client over the local Unix socket."""

    def __init__(self, socket_path: str = "/var/run/docker.sock", timeout: float = 30):
        self.socket_path = socket_path
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        operation: str,
    ) -> tuple[int, Any]:
        if query:
            path = f"{path}?{urlencode(query)}"
        payload = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"} if payload else {}
        connection = _UnixHTTPConnection(self.socket_path, self.timeout)
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read()
        except TimeoutError as exc:
            raise ProviderTimeoutError("Docker request timed out", operation=operation) from exc
        except OSError as exc:
            raise ProviderRetryableError("Docker is unavailable", operation=operation) from exc
        finally:
            connection.close()
        try:
            data = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            data = None
        if response.status >= 500:
            raise ProviderRetryableError(
                "Docker request failed", operation=operation, status_code=response.status
            )
        return response.status, data


class DockerSecretStore:
    """``ProofSecretStore`` that keeps per-app secrets in a host directory."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)

    def app_dir(self, app_ref: str) -> Path:
        _check_name(app_ref, "app")
        return self.root / app_ref

    def stage(self, app_ref: str, secret_name: str, encoded_value: str) -> None:
        _check_secret(secret_name)
        value = base64.b64decode(encoded_value, validate=True)
        directory = self.app_dir(app_ref)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / secret_name
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(value)
        temporary.chmod(0o600)
        temporary.replace(path)

    def remove(self, app_ref: str, secret_name: str) -> None:
        self.remove_many(app_ref, (secret_name,))

    def remove_many(self, app_ref: str, secret_names: tuple[str, ...]) -> None:
        for name in secret_names:
            _check_secret(name)
            (self.app_dir(app_ref) / name).unlink(missing_ok=True)

    def encoded(self, app_ref: str, secret_name: str) -> str:
        _check_secret(secret_name)
        path = self.app_dir(app_ref) / secret_name
        try:
            return base64.b64encode(path.read_bytes()).decode()
        except FileNotFoundError as exc:
            raise ProviderNotFoundError(
                f"secret {secret_name} is not staged", operation="create_machine"
            ) from exc

    # Fly needs a release to activate staged secrets; files are live at once.
    def bootstrap_release(self, app_ref: str, image: str, region: str) -> tuple[str, str]:
        return ("local", "1")

    def deploy(self, app_ref: str) -> tuple[str, str]:
        return ("local", "1")


class DockerProvider:
    """``WorkspaceProvider`` for one Docker host."""

    def __init__(
        self,
        *,
        network: str,
        secrets: DockerSecretStore,
        engine: DockerEngine | None = None,
        organization: str = "local",
    ) -> None:
        if not network:
            raise ProviderInvalidConfigurationError(
                "ALLIES_DOCKER_NETWORK is required", operation="docker_config"
            )
        self.network = network
        self.secrets = secrets
        self.engine = engine or DockerEngine()
        self.organization = organization

    @classmethod
    def from_environment(cls) -> DockerProvider:
        return cls(
            network=os.environ.get("ALLIES_DOCKER_NETWORK", "").strip(),
            secrets=DockerSecretStore(
                os.environ.get("ALLIES_DOCKER_SECRETS_DIR", "/var/lib/allies/secrets")
            ),
            engine=DockerEngine(
                os.environ.get("ALLIES_DOCKER_SOCKET", "/var/run/docker.sock")
            ),
        )

    # Fly-only hooks used by activation; nothing to do on one host.
    def set_release_metadata(self, release_id: str, version: str) -> None:
        return None

    def assert_proof_capabilities(self) -> None:
        return None

    # Apps: Docker has no app object, so an app is its secret directory.
    def inspect_app(self, name: str) -> AppRecord | None:
        if not self.secrets.app_dir(name).is_dir():
            return None
        return AppRecord(name, name, self.organization)

    def create_app(self, spec: AppSpec) -> AppRecord:
        self.secrets.app_dir(spec.name).mkdir(mode=0o700, parents=True, exist_ok=True)
        return AppRecord(spec.name, spec.name, self.organization)

    def ensure_app(self, spec: AppSpec) -> AppRecord:
        return self.inspect_app(spec.name) or self.create_app(spec)

    def delete_app(self, app_name: str) -> None:
        shutil.rmtree(self.secrets.app_dir(app_name), ignore_errors=True)

    # Volumes
    def list_volumes(self, app_name: str) -> Sequence[VolumeRecord]:
        _, data = self.engine.request(
            "GET",
            "/volumes",
            query={"filters": json.dumps({"label": [f"{_APP}={app_name}"]})},
            operation="list_volumes",
        )
        volumes = (data or {}).get("Volumes") or []
        return tuple(self._volume_record(raw) for raw in volumes)

    def create_volume(self, spec: VolumeSpec) -> VolumeRecord:
        _check_name(spec.name, "volume")
        status, data = self.engine.request(
            "POST",
            "/volumes/create",
            body={
                "Name": spec.name,
                "Labels": {
                    _OWNER: _OWNER_VALUE,
                    _APP: spec.app_name,
                    _REGION: spec.region,
                    _SIZE: str(spec.size_gb),
                },
            },
            operation="create_volume",
        )
        _expect(status, (200, 201), "create_volume")
        return self._volume_record(data)

    def delete_volume(self, app_name: str, volume_id: str) -> None:
        status, _ = self.engine.request(
            "DELETE", f"/volumes/{quote(volume_id)}", operation="delete_volume"
        )
        if status == 409:
            raise ProviderConflictError("volume is in use", operation="delete_volume")
        _expect(status, (204, 404), "delete_volume")

    # Machines
    def inspect_machine(self, app_name: str, name: str) -> MachineRecord | None:
        hermes = self._container(name, "inspect_machine")
        if hermes is None:
            return None
        labels = hermes["Config"].get("Labels") or {}
        if labels.get(_APP) != app_name:
            return None
        runtime = self._container(name + _RUNTIME_SUFFIX, "inspect_machine")
        return self._machine_record(hermes, runtime)

    def create_machine(self, spec: MachineSpec) -> MachineRecord:
        if self._container(spec.name, "create_machine") is not None:
            raise ProviderConflictError("machine already exists", operation="create_machine")
        labels = {
            _OWNER: _OWNER_VALUE,
            _APP: spec.app_name,
            _MACHINE: spec.name,
            _REGION: spec.region,
            _WORKSPACE: str(spec.ownership.workspace_id),
            _OPERATION: str(spec.ownership.operation_id),
            _GENERATION: str(spec.ownership.generation),
            "allies.volume": spec.mount.volume_id,
        }
        mount = {
            "Type": "volume",
            "Source": spec.mount.volume_id,
            "Target": spec.mount.path,
            "ReadOnly": spec.mount.read_only,
        }
        by_name = {container.name: container for container in spec.containers}
        if set(by_name) != {"hermes", "allies-runtime"}:
            raise ProviderInvalidConfigurationError(
                "workspace Machine must contain hermes and allies-runtime containers",
                operation="create_machine",
            )
        hermes_id = self._create_container(
            spec.name,
            spec,
            by_name["hermes"],
            labels={**labels, _ROLE: "hermes"},
            host={
                "Mounts": [mount],
                "NetworkMode": self.network,
                "Memory": spec.memory_mb * 1024 * 1024,
                "NanoCpus": spec.cpus * 1_000_000_000,
                "SecurityOpt": _HERMES_SECURITY,
                "RestartPolicy": {"Name": "unless-stopped"},
            },
        )
        self._create_container(
            spec.name + _RUNTIME_SUFFIX,
            spec,
            by_name["allies-runtime"],
            labels={**labels, _ROLE: "allies-runtime"},
            host={
                "Mounts": [mount],
                "NetworkMode": f"container:{hermes_id}",
                "RestartPolicy": {"Name": "unless-stopped"},
            },
        )
        machine = self.inspect_machine(spec.app_name, spec.name)
        if machine is None:
            raise ProviderProtocolError("created machine vanished", operation="create_machine")
        return machine

    def wait_machine(
        self,
        app_name: str,
        machine_id: str,
        *,
        timeout_seconds: float,
        state: str = "started",
    ) -> MachineRecord:
        deadline = time.monotonic() + timeout_seconds
        while True:
            machine = self.inspect_machine(app_name, machine_id)
            if machine is None:
                raise ProviderNotFoundError("machine not found", operation="wait_machine")
            if machine.state.value == state:
                return machine
            if time.monotonic() >= deadline:
                raise ProviderTimeoutError(
                    f"machine did not reach {state}", operation="wait_machine"
                )
            time.sleep(0.5)

    def start_machine(self, app_name: str, machine_id: str) -> MachineRecord:
        for name in (machine_id, machine_id + _RUNTIME_SUFFIX):
            status, _ = self.engine.request(
                "POST", f"/containers/{quote(name)}/start", operation="start_machine"
            )
            _expect(status, (204, 304), "start_machine")
        return self._require(app_name, machine_id, "start_machine")

    def stop_machine(self, app_name: str, machine_id: str) -> MachineRecord:
        for name in (machine_id + _RUNTIME_SUFFIX, machine_id):
            status, _ = self.engine.request(
                "POST",
                f"/containers/{quote(name)}/stop",
                query={"t": _STOP_SECONDS},
                operation="stop_machine",
            )
            _expect(status, (204, 304, 404), "stop_machine")
        return self._require(app_name, machine_id, "stop_machine")

    def destroy_machine(self, app_name: str, machine_id: str) -> None:
        for name in (machine_id + _RUNTIME_SUFFIX, machine_id):
            status, _ = self.engine.request(
                "DELETE",
                f"/containers/{quote(name)}",
                query={"force": "true"},
                operation="destroy_machine",
            )
            _expect(status, (204, 404), "destroy_machine")

    # ponytail: leases are advisory on one host where Foundry is the only
    # writer; add a DB-backed lease if several Foundry workers ever race.
    def acquire_machine_lease(
        self, app_name: str, machine_id: str, *, lease_seconds: int
    ) -> str | None:
        return uuid4().hex

    def release_machine_lease(self, app_name: str, machine_id: str, lease_token: str) -> None:
        return None

    # Internals
    def _create_container(
        self,
        name: str,
        spec: MachineSpec,
        container: Any,
        *,
        labels: Mapping[str, str],
        host: Mapping[str, Any],
    ) -> str:
        env = dict(container.environment)
        for secret in container.secret_files:
            env[secret.secret_name] = self.secrets.encoded(spec.app_name, secret.secret_name)
        if container.name == "allies-runtime":
            if spec.runtime_credential_ref is not None:
                env["HERMES_CREDENTIAL_REF"] = spec.runtime_credential_ref.reference
            if spec.foundry_runtime_credential_ref is not None:
                env["FOUNDRY_ORIGIN"] = spec.foundry_origin
                env["FOUNDRY_RUNTIME_CREDENTIAL_REF"] = (
                    spec.foundry_runtime_credential_ref.reference
                )
                secret_name = spec.foundry_runtime_credential_secret_name
                env[secret_name] = self.secrets.encoded(spec.app_name, secret_name)
        body: dict[str, Any] = {
            "Image": container.image,
            "Labels": dict(labels),
            "Env": [f"{key}={value}" for key, value in env.items()],
            "HostConfig": dict(host),
        }
        if container.command:
            body["Cmd"] = list(container.command)
        if container.entrypoint:
            body["Entrypoint"] = list(container.entrypoint)
        if container.user is not None:
            body["User"] = container.user
        status, data = self._create(name, body)
        if status == 404:
            self._pull(container.image)
            status, data = self._create(name, body)
        _expect(status, (201,), "create_machine")
        return data["Id"]

    def _create(self, name: str, body: Mapping[str, Any]) -> tuple[int, Any]:
        return self.engine.request(
            "POST",
            "/containers/create",
            query={"name": name},
            body=body,
            operation="create_machine",
        )

    def _pull(self, image: str) -> None:
        status, _ = self.engine.request(
            "POST", "/images/create", query={"fromImage": image}, operation="pull_image"
        )
        _expect(status, (200,), "pull_image")

    def _container(self, name: str, operation: str) -> Mapping[str, Any] | None:
        status, data = self.engine.request(
            "GET", f"/containers/{quote(name)}/json", operation=operation
        )
        if status == 404:
            return None
        _expect(status, (200,), operation)
        return data

    def _require(self, app_name: str, machine_id: str, operation: str) -> MachineRecord:
        machine = self.inspect_machine(app_name, machine_id)
        if machine is None:
            raise ProviderNotFoundError("machine not found", operation=operation)
        return machine

    def _machine_record(
        self, hermes: Mapping[str, Any], runtime: Mapping[str, Any] | None
    ) -> MachineRecord:
        labels = hermes["Config"].get("Labels") or {}
        containers = {"hermes": _container_state(hermes)}
        if runtime is not None:
            containers["allies-runtime"] = _container_state(runtime)
        states = set(containers.values())
        if runtime is None or ContainerState.FAILED in states:
            state = MachineState.STOPPED
        elif states == {ContainerState.STARTED}:
            state = MachineState.STARTED
        elif states == {ContainerState.CREATED}:
            state = MachineState.CREATED
        elif ContainerState.STARTED in states:
            state = MachineState.UNKNOWN
        else:
            state = MachineState.STOPPED
        images = {"hermes": hermes["Config"]["Image"]}
        if runtime is not None:
            images["allies-runtime"] = runtime["Config"]["Image"]
        memory = (hermes.get("HostConfig") or {}).get("Memory") or 0
        return MachineRecord(
            id=labels[_MACHINE],
            name=labels[_MACHINE],
            app_name=labels[_APP],
            region=labels.get(_REGION, "local"),
            state=state,
            volume_id=labels.get("allies.volume"),
            ownership=_ownership(labels),
            health=MachineHealth(state, containers),
            images=images,
            cpu_kind="shared",
            cpus=max(1, ((hermes.get("HostConfig") or {}).get("NanoCpus") or 0) // 1_000_000_000),
            memory_mb=memory // (1024 * 1024) or None,
        )

    def _volume_record(self, raw: Mapping[str, Any]) -> VolumeRecord:
        labels = raw.get("Labels") or {}
        name = raw.get("Name")
        if not name or _APP not in labels:
            raise ProviderProtocolError("volume is not Foundry-owned", operation="map_volume")
        _, data = self.engine.request(
            "GET",
            "/containers/json",
            query={
                "all": "true",
                "filters": json.dumps(
                    {"label": [f"allies.volume={name}", f"{_ROLE}=hermes"]}
                ),
            },
            operation="list_volumes",
        )
        attached = None
        for container in data or []:
            attached = (container.get("Labels") or {}).get(_MACHINE) or attached
        return VolumeRecord(
            id=name,
            name=name,
            app_name=labels[_APP],
            region=labels.get(_REGION, "local"),
            size_gb=int(labels.get(_SIZE, "1")),
            attached_machine_id=attached,
        )


def _container_state(raw: Mapping[str, Any]) -> ContainerState:
    status = (raw.get("State") or {}).get("Status")
    if status in ("running", "restarting"):
        return ContainerState.STARTED
    if status == "created":
        return ContainerState.CREATED
    if status == "dead":
        return ContainerState.FAILED
    if status in ("exited", "paused", "removing"):
        return ContainerState.STOPPED
    return ContainerState.UNKNOWN


def _ownership(labels: Mapping[str, str]) -> OwnershipMetadata | None:
    if labels.get(_OWNER) != _OWNER_VALUE:
        return None
    try:
        from uuid import UUID

        return OwnershipMetadata(
            UUID(labels[_WORKSPACE]), UUID(labels[_OPERATION]), int(labels[_GENERATION])
        )
    except (KeyError, ValueError):
        return None


def _expect(status: int, allowed: tuple[int, ...], operation: str) -> None:
    if status == 404 and 404 not in allowed:
        raise ProviderNotFoundError("Docker resource not found", operation=operation)
    if status == 409 and 409 not in allowed:
        raise ProviderConflictError("Docker resource conflict", operation=operation)
    if status not in allowed:
        raise ProviderProtocolError(
            "unexpected Docker response", operation=operation, status_code=status
        )


def _check_name(value: str, kind: str) -> None:
    if not isinstance(value, str) or not _SAFE_NAME.fullmatch(value):
        raise ProviderInvalidConfigurationError(f"invalid {kind} name", operation="docker")


def _check_secret(value: str) -> None:
    if not isinstance(value, str) or not _SAFE_SECRET.fullmatch(value):
        raise ValueError("secret name is invalid")


__all__ = ["DockerEngine", "DockerProvider", "DockerSecretStore"]
