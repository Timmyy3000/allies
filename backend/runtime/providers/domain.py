"""Provider-neutral resource and request records.

These records deliberately contain identities and health state, not Fly
response objects or credentials.  Provider adapters are responsible for
validating and translating external responses into these shapes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID


def _identifier(value: str, name: str, *, max_length: int = 255) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ValueError(
            f"{name} must be a non-empty string of at most {max_length} characters"
        )
    if any(character in value for character in "\r\n"):
        raise ValueError(f"{name} must not contain newlines")
    return value


def _labels(value: Mapping[str, str], name: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        normalized[_identifier(key, f"{name} key")] = _identifier(
            item,
            f"{name} value",
        )
    return MappingProxyType(normalized)


class MachineState(StrEnum):
    CREATED = "created"
    STARTED = "started"
    STOPPED = "stopped"
    DESTROYED = "destroyed"
    UNKNOWN = "unknown"


class ContainerState(StrEnum):
    CREATED = "created"
    STARTED = "started"
    STOPPED = "stopped"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class OpaqueReference:
    """A non-secret reference accepted at the provider boundary.

    The value is an identifier for a separately managed secret.  It is never
    serialized into a provider response or persisted as the secret itself.
    """

    reference: str

    def __post_init__(self) -> None:
        _identifier(self.reference, "opaque reference")

    def __str__(self) -> str:
        return self.reference


@dataclass(frozen=True, slots=True)
class OwnershipMetadata:
    workspace_id: UUID | str
    operation_id: UUID | str
    generation: int

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_id, (UUID, str)):
            raise TypeError("workspace_id must be a UUID or string")
        if not isinstance(self.operation_id, (UUID, str)):
            raise TypeError("operation_id must be a UUID or string")
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("generation must be a positive integer")


@dataclass(frozen=True, slots=True)
class AppSpec:
    name: str
    organization: str
    region: str

    def __post_init__(self) -> None:
        _identifier(self.name, "app name")
        _identifier(self.organization, "organization")
        _identifier(self.region, "region")


@dataclass(frozen=True, slots=True)
class AppRecord:
    id: str
    name: str
    organization: str
    status: str = "running"

    def __post_init__(self) -> None:
        _identifier(self.id, "app id")
        _identifier(self.name, "app name")
        _identifier(self.organization, "organization")
        _identifier(self.status, "app status")


@dataclass(frozen=True, slots=True)
class VolumeSpec:
    app_name: str
    name: str
    region: str
    size_gb: int = 1
    filesystem: str = "ext4"

    def __post_init__(self) -> None:
        _identifier(self.app_name, "volume app name")
        _identifier(self.name, "volume name")
        _identifier(self.region, "volume region")
        if type(self.size_gb) is not int or self.size_gb <= 0:
            raise ValueError("volume size_gb must be a positive integer")
        _identifier(self.filesystem, "volume filesystem", max_length=32)


@dataclass(frozen=True, slots=True)
class VolumeRecord:
    id: str
    name: str
    app_name: str
    region: str
    size_gb: int
    attached_machine_id: str | None = None
    ownership: OwnershipMetadata | None = None

    def __post_init__(self) -> None:
        _identifier(self.id, "volume id")
        _identifier(self.name, "volume name")
        _identifier(self.app_name, "volume app name")
        _identifier(self.region, "volume region")
        if type(self.size_gb) is not int or self.size_gb <= 0:
            raise ValueError("volume size_gb must be a positive integer")
        if self.attached_machine_id is not None:
            _identifier(self.attached_machine_id, "attached machine id")


@dataclass(frozen=True, slots=True)
class VolumeMount:
    volume_id: str
    path: str = "/opt/data"
    read_only: bool = False

    def __post_init__(self) -> None:
        _identifier(self.volume_id, "mount volume id")
        _identifier(self.path, "mount path", max_length=255)
        if not self.path.startswith("/"):
            raise ValueError("mount path must be absolute")
        if type(self.read_only) is not bool:
            raise ValueError("mount read_only must be a boolean")


@dataclass(frozen=True, slots=True)
class ContainerSpec:
    name: str
    image: str
    command: tuple[str, ...] = ()
    healthchecks: tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.name, "container name", max_length=64)
        _identifier(self.image, "container image")
        if not isinstance(self.command, tuple):
            object.__setattr__(self, "command", tuple(self.command))
        for item in self.command:
            _identifier(item, "container command")
        if not isinstance(self.healthchecks, tuple):
            object.__setattr__(self, "healthchecks", tuple(self.healthchecks))
        normalized_checks: list[Mapping[str, object]] = []
        for check in self.healthchecks:
            if not isinstance(check, Mapping):
                raise TypeError("container healthchecks must be mappings")
            check_name = check.get("name")
            if not isinstance(check_name, str):
                raise TypeError("container healthcheck name is required")
            _identifier(check_name, "container healthcheck name", max_length=64)
            normalized_checks.append(MappingProxyType(dict(check)))
        object.__setattr__(self, "healthchecks", tuple(normalized_checks))


@dataclass(frozen=True, slots=True)
class MachineSpec:
    app_name: str
    name: str
    region: str
    containers: tuple[ContainerSpec, ...]
    mount: VolumeMount
    ownership: OwnershipMetadata
    runtime_credential_ref: OpaqueReference | str | None = None
    public_services: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.app_name, "machine app name")
        _identifier(self.name, "machine name")
        _identifier(self.region, "machine region")
        if not isinstance(self.containers, tuple):
            object.__setattr__(self, "containers", tuple(self.containers))
        if not self.containers:
            raise ValueError("machine spec requires at least one container")
        container_names = [container.name for container in self.containers]
        if len(container_names) != len(set(container_names)):
            raise ValueError("machine container names must be unique")
        if not isinstance(self.mount, VolumeMount):
            raise TypeError("machine mount must be a VolumeMount")
        if not isinstance(self.ownership, OwnershipMetadata):
            raise TypeError("machine ownership metadata is required")
        if isinstance(self.runtime_credential_ref, str):
            object.__setattr__(
                self,
                "runtime_credential_ref",
                OpaqueReference(self.runtime_credential_ref),
            )
        elif self.runtime_credential_ref is not None and not isinstance(
            self.runtime_credential_ref,
            OpaqueReference,
        ):
            raise ValueError("runtime credential must be an opaque reference")
        if not isinstance(self.public_services, tuple):
            object.__setattr__(self, "public_services", tuple(self.public_services))
        if self.public_services:
            raise ValueError("workspace Machines must not expose public services")


@dataclass(frozen=True, slots=True)
class MachineHealth:
    state: MachineState
    containers: Mapping[str, ContainerState]

    def __post_init__(self) -> None:
        state = self.state
        if not isinstance(state, MachineState):
            try:
                state = MachineState(state)
            except ValueError as exc:
                raise ValueError("invalid machine state") from exc
            object.__setattr__(self, "state", state)
        normalized = {}
        for name, container_state in self.containers.items():
            _identifier(name, "health container name", max_length=64)
            if not isinstance(container_state, ContainerState):
                try:
                    container_state = ContainerState(container_state)
                except ValueError as exc:
                    raise ValueError("invalid container state") from exc
            normalized[name] = container_state
        object.__setattr__(self, "containers", MappingProxyType(normalized))


@dataclass(frozen=True, slots=True)
class MachineRecord:
    id: str
    name: str
    app_name: str
    region: str
    state: MachineState
    volume_id: str | None = None
    ownership: OwnershipMetadata | None = None
    health: MachineHealth | None = None

    def __post_init__(self) -> None:
        _identifier(self.id, "machine id")
        _identifier(self.name, "machine name")
        _identifier(self.app_name, "machine app name")
        _identifier(self.region, "machine region")
        if not isinstance(self.state, MachineState):
            try:
                object.__setattr__(self, "state", MachineState(self.state))
            except ValueError as exc:
                raise ValueError("invalid machine state") from exc
        if self.volume_id is not None:
            _identifier(self.volume_id, "machine volume id")


# Short names keep lifecycle code provider-neutral while the explicit Record
# names make serialization and type-checking at the adapter boundary clear.
App = AppRecord
Volume = VolumeRecord
Machine = MachineRecord


__all__ = [
    "App",
    "AppRecord",
    "AppSpec",
    "ContainerSpec",
    "ContainerState",
    "Machine",
    "MachineHealth",
    "MachineRecord",
    "MachineSpec",
    "MachineState",
    "OpaqueReference",
    "OwnershipMetadata",
    "Volume",
    "VolumeMount",
    "VolumeRecord",
    "VolumeSpec",
]
