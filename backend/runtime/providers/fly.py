"""Fly Machines adapter for the provider-neutral workspace boundary.

Each public operation below performs one Fly API request.  ``ensure_*`` and
``reconcile_*`` helpers only perform deterministic lookup after a timeout;
they do not implement lifecycle retries.  The Workspace service owns phase
claims, deadlines, and backoff.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

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
    ProviderAttachmentConflictError,
    ProviderConflictError,
    ProviderInvalidConfigurationError,
    ProviderNotFoundError,
    ProviderOwnershipError,
    ProviderProtocolError,
    ProviderTimeoutError,
    ProviderUnsupportedTopologyError,
)
from .fly_http import FlyHttpClient, FlyTransport

_WORKSPACE_MARKER = "allies_workspace_id"
_OPERATION_MARKER = "allies_operation_id"
_GENERATION_MARKER = "allies_machine_generation"
_OWNER_MARKER = "allies_owner"
_OWNER_VALUE = "foundry"
_EXPECTED_CONTAINERS = frozenset(("hermes", "allies-runtime"))


@dataclass(frozen=True, slots=True)
class WorkspaceResourceNames:
    """Stable Fly names derived solely from immutable workspace identity."""

    app: str
    volume: str
    workspace_id: str

    def machine(self, generation: int) -> str:
        if type(generation) is not int or generation <= 0:
            raise ValueError("machine generation must be a positive integer")
        return deterministic_machine_name(self.workspace_id, generation)


def _workspace_text(workspace_id: UUID | str) -> str:
    try:
        value = UUID(str(workspace_id)).hex
    except (TypeError, ValueError) as exc:
        raise ValueError("workspace_id must be a UUID") from exc
    return value


def deterministic_app_name(workspace_id: UUID | str) -> str:
    return f"allies-ws-{_workspace_text(workspace_id)}"


def deterministic_volume_name(workspace_id: UUID | str) -> str:
    return f"allies-vol-{_workspace_text(workspace_id)}"


def deterministic_machine_name(workspace_id: UUID | str, generation: int) -> str:
    if type(generation) is not int or generation <= 0:
        raise ValueError("machine generation must be a positive integer")
    return f"allies-machine-{_workspace_text(workspace_id)}-{generation}"


def deterministic_resource_names(workspace_id: UUID | str) -> WorkspaceResourceNames:
    workspace = _workspace_text(workspace_id)
    return WorkspaceResourceNames(
        app=f"allies-ws-{workspace}",
        volume=f"allies-vol-{workspace}",
        workspace_id=workspace,
    )


class FlyProvider:
    """Translate Fly REST resources into provider-neutral records."""

    def __init__(
        self,
        client: FlyHttpClient | None = None,
        *,
        http_client: FlyHttpClient | None = None,
        transport: FlyTransport | None = None,
        api_token: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 10.0,
        multi_container_enabled: bool | None = None,
    ) -> None:
        if client is not None and (http_client is not None or transport is not None):
            raise TypeError("pass only one Fly HTTP client or transport")
        selected = client or http_client
        if selected is None:
            resolved_token = api_token or os.environ.get("FLY_API_TOKEN")
            if not resolved_token:
                raise ProviderInvalidConfigurationError(
                    "FLY_API_TOKEN is required for the Fly provider",
                    operation="provider_config",
                )
            selected = FlyHttpClient(
                api_token=resolved_token,
                base_url=base_url or "https://api.machines.dev/v1",
                timeout_seconds=timeout_seconds,
                transport=transport,
            )
        self.http = selected
        if multi_container_enabled is None:
            multi_container_enabled = _env_flag("FLY_MULTI_CONTAINER_ENABLED")
        self.multi_container_enabled = bool(multi_container_enabled)

    @property
    def topology_supported(self) -> bool:
        return self.multi_container_enabled

    def assert_topology_supported(self) -> None:
        if not self.multi_container_enabled:
            raise ProviderUnsupportedTopologyError(
                "Fly multi-container/Pilot capability is not enabled"
            )

    # Names used by deployment preflight callers; all are the same pure gate.
    preflight = assert_topology_supported
    check_capabilities = assert_topology_supported

    def inspect_app(
        self, name: str, organization: str | None = None
    ) -> AppRecord | None:
        try:
            payload = self.http.get(
                f"/apps/{_path_segment(name)}",
                operation="inspect_app",
            )
        except ProviderNotFoundError:
            return None
        raw = _mapping(payload, "app", operation="inspect_app")
        app = _app_record(raw, fallback_name=name, fallback_org=organization)
        if app.name != name:
            raise ProviderProtocolError(
                "provider App name did not match lookup", operation="inspect_app"
            )
        if organization and app.organization != organization:
            raise ProviderOwnershipError(
                "provider App belongs to a different organization",
                operation="inspect_app",
                details={"resource_type": "app", "resource_id": app.id},
            )
        return app

    def create_app(self, spec: AppSpec) -> AppRecord:
        payload = self.http.post(
            "/apps",
            body={"app_name": spec.name, "org_slug": spec.organization},
            operation="create_app",
        )
        raw = _mapping(payload, "app", operation="create_app")
        app = _app_record(
            raw,
            fallback_name=spec.name,
            fallback_org=spec.organization,
            fallback_status="pending",
        )
        if app.name != spec.name or app.organization != spec.organization:
            raise ProviderOwnershipError(
                "provider App did not match deterministic workspace identity",
                operation="create_app",
                details={"resource_type": "app", "resource_id": app.id},
            )
        return app

    def ensure_app(self, spec: AppSpec) -> AppRecord:
        """Find or create an App, reconciling an uncertain create timeout."""

        existing = self.inspect_app(spec.name, organization=spec.organization)
        if existing is not None:
            return existing
        try:
            return self.create_app(spec)
        except ProviderTimeoutError:
            reconciled = self.inspect_app(spec.name, organization=spec.organization)
            if reconciled is not None:
                return reconciled
            raise

    def list_volumes(self, app_name: str) -> Sequence[VolumeRecord]:
        payload = self.http.get(
            f"/apps/{_path_segment(app_name)}/volumes",
            operation="list_volumes",
        )
        if isinstance(payload, Mapping):
            payload = payload.get("volumes")
        if not isinstance(payload, list):
            raise ProviderProtocolError(
                "provider volume list was not an array", operation="list_volumes"
            )
        return tuple(
            _volume_record(
                _mapping(item, "volume", operation="list_volumes"), app_name=app_name
            )
            for item in payload
        )

    def create_volume(self, spec: VolumeSpec) -> VolumeRecord:
        payload = self.http.post(
            f"/apps/{_path_segment(spec.app_name)}/volumes",
            body={
                "name": spec.name,
                "region": spec.region,
                "size_gb": spec.size_gb,
                "fstype": spec.filesystem,
            },
            operation="create_volume",
        )
        raw = _mapping(payload, "volume", operation="create_volume")
        return _volume_record(
            raw,
            app_name=spec.app_name,
            fallback_name=spec.name,
            fallback_region=spec.region,
            fallback_size=spec.size_gb,
        )

    def ensure_volume(self, spec: VolumeSpec) -> VolumeRecord:
        """Adopt the sole deterministic App Volume or create one."""

        volumes = tuple(self.list_volumes(spec.app_name))
        if len(volumes) > 1:
            raise ProviderConflictError(
                "provider returned multiple candidate workspace Volumes",
                operation="ensure_volume",
                details={"resource_type": "volume"},
            )
        if volumes:
            volume = volumes[0]
            _verify_volume_spec(volume, spec)
            return volume
        try:
            return self.create_volume(spec)
        except ProviderTimeoutError as timeout:
            reconciled = tuple(self.list_volumes(spec.app_name))
            if len(reconciled) == 1:
                _verify_volume_spec(reconciled[0], spec)
                return reconciled[0]
            if len(reconciled) > 1:
                raise ProviderConflictError(
                    "provider returned multiple candidate workspace Volumes",
                    operation="ensure_volume",
                    details={"resource_type": "volume"},
                ) from timeout
            raise

    def inspect_machine(
        self,
        app_name: str,
        name: str,
        ownership: OwnershipMetadata | None = None,
    ) -> MachineRecord | None:
        payload = self.http.get(
            f"/apps/{_path_segment(app_name)}/machines",
            operation="inspect_machine",
        )
        if isinstance(payload, Mapping):
            payload = payload.get("machines")
        if not isinstance(payload, list):
            raise ProviderProtocolError(
                "provider Machine list was not an array", operation="inspect_machine"
            )
        candidates = []
        for item in payload:
            raw = _mapping(item, "machine", operation="inspect_machine")
            candidate = _machine_record(raw, app_name=app_name)
            if candidate.name == name:
                candidates.append(candidate)
        if len(candidates) > 1:
            raise ProviderConflictError(
                "provider returned duplicate deterministic Machines",
                operation="inspect_machine",
                details={"resource_type": "machine"},
            )
        if not candidates:
            return None
        machine = candidates[0]
        if ownership and machine.ownership != ownership:
            raise ProviderOwnershipError(
                "provider Machine ownership marker did not match",
                operation="inspect_machine",
                details={"resource_type": "machine", "resource_id": machine.id},
            )
        return machine

    def inspect_machine_by_id(
        self, app_name: str, machine_id: str
    ) -> MachineRecord | None:
        try:
            payload = self.http.get(
                f"/apps/{_path_segment(app_name)}/machines/{_path_segment(machine_id)}",
                operation="inspect_machine_by_id",
            )
        except ProviderNotFoundError:
            return None
        return _machine_record(
            _mapping(payload, "machine", operation="inspect_machine_by_id"),
            app_name=app_name,
        )

    def create_machine(self, spec: MachineSpec) -> MachineRecord:
        body = self.machine_payload(spec)
        payload = self.http.post(
            f"/apps/{_path_segment(spec.app_name)}/machines",
            body=body,
            operation="create_machine",
        )
        raw = _mapping(payload, "machine", operation="create_machine")
        return _machine_record(
            raw,
            app_name=spec.app_name,
            fallback_name=spec.name,
            fallback_region=spec.region,
            fallback_volume_id=spec.mount.volume_id,
            fallback_ownership=spec.ownership,
        )

    def ensure_machine(self, spec: MachineSpec) -> MachineRecord:
        """Find or create an owned Machine, reconciling create uncertainty."""

        existing = self.inspect_machine(spec.app_name, spec.name)
        if existing is not None:
            _verify_machine_spec(existing, spec)
            return existing
        try:
            return self.create_machine(spec)
        except ProviderTimeoutError:
            reconciled = self.inspect_machine(spec.app_name, spec.name)
            if reconciled is not None:
                _verify_machine_spec(reconciled, spec)
                return reconciled
            raise

    # Explicit alias used by lifecycle reconciliation code after uncertain
    # provider calls.  It intentionally performs no create or delete.
    reconcile_machine = inspect_machine

    def machine_payload(self, spec: MachineSpec) -> dict[str, Any]:
        self.assert_topology_supported()
        if (
            len(spec.containers) != 2
            or {container.name for container in spec.containers} != _EXPECTED_CONTAINERS
        ):
            raise ProviderUnsupportedTopologyError(
                "workspace Machine must contain hermes and allies-runtime containers"
            )
        metadata = {
            _OWNER_MARKER: _OWNER_VALUE,
            _WORKSPACE_MARKER: str(spec.ownership.workspace_id),
            _OPERATION_MARKER: str(spec.ownership.operation_id),
            _GENERATION_MARKER: str(spec.ownership.generation),
        }
        containers: list[dict[str, Any]] = []
        for container in spec.containers:
            if not container.healthchecks:
                raise ProviderInvalidConfigurationError(
                    f"container {container.name} requires a healthcheck",
                    operation="create_machine",
                    details={"resource_type": "machine"},
                )
            item: dict[str, Any] = {
                "name": container.name,
                "image": container.image,
            }
            if container.command:
                item["command"] = list(container.command)
            item["healthchecks"] = [dict(check) for check in container.healthchecks]
            if (
                container.name == "allies-runtime"
                and spec.runtime_credential_ref is not None
            ):
                # Only the reference is sent.  Secret resolution is owned by a
                # later deployment boundary; Fly app secrets are global.
                item["env"] = {
                    "HERMES_CREDENTIAL_REF": spec.runtime_credential_ref.reference
                }
            containers.append(item)
        return {
            "name": spec.name,
            "region": spec.region,
            "skip_launch": True,
            "skip_service_registration": True,
            "config": {
                "containers": containers,
                "mounts": [
                    {
                        "volume": spec.mount.volume_id,
                        # Fly's multi-container Machines contract uses
                        # ``path`` for the guest mount.  Keep this translation
                        # at the provider boundary; lifecycle remains unaware
                        # of the wire spelling.
                        "path": spec.mount.path,
                    }
                ],
                # An explicit empty list makes the no-public-service
                # invariant testable and cannot accidentally inherit routes.
                "services": [],
                "metadata": metadata,
            },
        }

    def wait_machine(
        self,
        app_name: str,
        machine_id: str,
        *,
        timeout_seconds: float,
        state: str = "started",
    ) -> MachineRecord:
        if timeout_seconds <= 0:
            raise ValueError("Machine wait timeout must be positive")
        payload = self.http.get(
            f"/apps/{_path_segment(app_name)}/machines/{_path_segment(machine_id)}/wait",
            operation="wait_machine",
            query={"state": state, "timeout": max(1, int(timeout_seconds))},
        )
        if isinstance(payload, Mapping) and payload.get("ok") is True:
            try:
                requested_state = MachineState(state)
            except ValueError:
                requested_state = MachineState.UNKNOWN
            return _minimal_machine(machine_id, app_name, requested_state)
        return _machine_record(
            _mapping(payload, "machine", operation="wait_machine"),
            app_name=app_name,
            fallback_id=machine_id,
        )

    def start_machine(self, app_name: str, machine_id: str) -> MachineRecord:
        payload = self.http.post(
            f"/apps/{_path_segment(app_name)}/machines/{_path_segment(machine_id)}/start",
            operation="start_machine",
        )
        # Fly's action endpoint returns an acknowledgement object such as
        # ``previous_state``/``migrated`` rather than a full Machine record.
        # Keep the response boundary honest and let the lifecycle health phase
        # inspect the Machine for the authoritative state.
        if _is_machine_action_ack(payload):
            return _minimal_machine(machine_id, app_name, MachineState.STARTED)
        return _machine_record(
            _mapping(payload, "machine", operation="start_machine"),
            app_name=app_name,
            fallback_id=machine_id,
            fallback_state=MachineState.STARTED,
        )

    def stop_machine(self, app_name: str, machine_id: str) -> MachineRecord:
        payload = self.http.post(
            f"/apps/{_path_segment(app_name)}/machines/{_path_segment(machine_id)}/stop",
            operation="stop_machine",
        )
        if _is_machine_action_ack(payload):
            return _minimal_machine(machine_id, app_name, MachineState.STOPPED)
        return _machine_record(
            _mapping(payload, "machine", operation="stop_machine"),
            app_name=app_name,
            fallback_id=machine_id,
            fallback_state=MachineState.STOPPED,
        )

    def destroy_machine(self, app_name: str, machine_id: str) -> None:
        self.http.delete(
            f"/apps/{_path_segment(app_name)}/machines/{_path_segment(machine_id)}",
            operation="destroy_machine",
        )

    def delete_volume(self, app_name: str, volume_id: str) -> None:
        """Delete a smoke-owned Volume; callers classify a 404 as idempotent."""

        self.http.delete(
            f"/apps/{_path_segment(app_name)}/volumes/{_path_segment(volume_id)}",
            operation="delete_volume",
        )

    def delete_app(self, app_name: str) -> None:
        """Delete a smoke-owned App after its Machine and Volume are gone."""

        self.http.delete(
            f"/apps/{_path_segment(app_name)}",
            operation="delete_app",
        )

    def acquire_machine_lease(
        self,
        app_name: str,
        machine_id: str,
        *,
        lease_seconds: int,
    ) -> str | None:
        if type(lease_seconds) is not int or lease_seconds <= 0:
            raise ValueError("Machine lease_seconds must be a positive integer")
        payload = self.http.post(
            f"/apps/{_path_segment(app_name)}/machines/{_path_segment(machine_id)}/lease",
            body={"ttl": lease_seconds, "description": "allies-foundry"},
            operation="acquire_machine_lease",
        )
        raw = _mapping(payload, "lease", operation="acquire_machine_lease")
        data = raw.get("data") if isinstance(raw.get("data"), Mapping) else raw
        nonce = data.get("nonce") if isinstance(data, Mapping) else None
        if not isinstance(nonce, str) or not nonce:
            raise ProviderProtocolError(
                "provider lease response did not include a nonce",
                operation="acquire_machine_lease",
            )
        return nonce

    def release_machine_lease(
        self,
        app_name: str,
        machine_id: str,
        lease_token: str,
    ) -> None:
        if not isinstance(lease_token, str) or not lease_token:
            raise ValueError("Machine lease token must be a non-empty string")
        self.http.delete(
            f"/apps/{_path_segment(app_name)}/machines/{_path_segment(machine_id)}/lease",
            headers={"fly-machine-lease-nonce": lease_token},
            operation="release_machine_lease",
        )

    @staticmethod
    def check_volume_attachment(
        volume: VolumeRecord,
        *,
        expected_machine_id: str | None = None,
    ) -> None:
        attached = volume.attached_machine_id
        if attached and attached != expected_machine_id:
            raise ProviderAttachmentConflictError(
                volume_id=volume.id,
                attached_machine_id=attached,
            )

    assert_volume_available = check_volume_attachment


FlyHttpProvider = FlyProvider
FlyProviderAdapter = FlyProvider


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _path_segment(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(character in value for character in "/\\?#\r\n")
    ):
        raise ValueError("provider path segment must be a simple identifier")
    return value


def _mapping(value: Any, resource: str, *, operation: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProviderProtocolError(
            f"provider {resource} response was not an object", operation=operation
        )
    return value


def _required_string(raw: Mapping[str, Any], key: str, *, operation: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ProviderProtocolError(
            f"provider response omitted {key}", operation=operation
        )
    return value


def _app_record(
    raw: Mapping[str, Any],
    *,
    fallback_name: str | None = None,
    fallback_org: str | None = None,
    fallback_status: str = "unknown",
) -> AppRecord:
    app_id = _required_string(raw, "id", operation="map_app")
    name = raw.get("name") or raw.get("app_name") or fallback_name
    if not isinstance(name, str) or not name:
        raise ProviderProtocolError(
            "provider App response omitted name", operation="map_app"
        )
    organization_raw = raw.get("organization")
    if isinstance(organization_raw, Mapping):
        organization = organization_raw.get("slug") or organization_raw.get("name")
    else:
        organization = raw.get("org_slug")
    organization = organization or fallback_org
    if not isinstance(organization, str) or not organization:
        raise ProviderProtocolError(
            "provider App response omitted organization", operation="map_app"
        )
    status = raw.get("status") or fallback_status
    if not isinstance(status, str) or not status:
        raise ProviderProtocolError(
            "provider App response had invalid status", operation="map_app"
        )
    return AppRecord(app_id, name, organization, status)


def _volume_record(
    raw: Mapping[str, Any],
    *,
    app_name: str,
    fallback_name: str | None = None,
    fallback_region: str | None = None,
    fallback_size: int | None = None,
) -> VolumeRecord:
    volume_id = _required_string(raw, "id", operation="map_volume")
    name = raw.get("name") or fallback_name
    region = raw.get("region") or fallback_region
    size = raw.get("size_gb") or fallback_size
    if not isinstance(name, str) or not name:
        raise ProviderProtocolError(
            "provider Volume response omitted name", operation="map_volume"
        )
    if not isinstance(region, str) or not region:
        raise ProviderProtocolError(
            "provider Volume response omitted region", operation="map_volume"
        )
    if type(size) is not int or size <= 0:
        raise ProviderProtocolError(
            "provider Volume response omitted size", operation="map_volume"
        )
    attached = raw.get("attached_machine_id")
    if attached is not None and (not isinstance(attached, str) or not attached):
        attached = None
    ownership = _ownership(raw.get("metadata"))
    return VolumeRecord(volume_id, name, app_name, region, size, attached, ownership)


def _machine_record(
    raw: Mapping[str, Any],
    *,
    app_name: str,
    fallback_id: str | None = None,
    fallback_name: str | None = None,
    fallback_region: str | None = None,
    fallback_volume_id: str | None = None,
    fallback_ownership: OwnershipMetadata | None = None,
    fallback_state: MachineState = MachineState.UNKNOWN,
) -> MachineRecord:
    machine_id = raw.get("id") or fallback_id
    name = raw.get("name") or fallback_name
    region = raw.get("region") or fallback_region
    if not isinstance(machine_id, str) or not machine_id:
        raise ProviderProtocolError(
            "provider Machine response omitted id", operation="map_machine"
        )
    if not isinstance(name, str) or not name:
        raise ProviderProtocolError(
            "provider Machine response omitted name", operation="map_machine"
        )
    if not isinstance(region, str) or not region:
        raise ProviderProtocolError(
            "provider Machine response omitted region", operation="map_machine"
        )
    state = _machine_state(raw.get("state") or raw.get("status"), fallback_state)
    config = raw.get("config") if isinstance(raw.get("config"), Mapping) else {}
    volume_id = _volume_id_from_config(config) or fallback_volume_id
    ownership = _ownership(raw.get("metadata")) or _ownership(config.get("metadata"))
    ownership = ownership or fallback_ownership
    health = _machine_health(raw, state)
    return MachineRecord(
        machine_id, name, app_name, region, state, volume_id, ownership, health
    )


def _volume_id_from_config(config: Mapping[str, Any]) -> str | None:
    mounts = config.get("mounts")
    if not isinstance(mounts, list):
        return None
    for mount in mounts:
        if isinstance(mount, Mapping):
            value = mount.get("volume") or mount.get("volume_id")
            if isinstance(value, str) and value:
                return value
    return None


def _ownership(raw: Any) -> OwnershipMetadata | None:
    if not isinstance(raw, Mapping):
        return None
    if raw.get(_OWNER_MARKER) != _OWNER_VALUE:
        return None
    workspace = raw.get(_WORKSPACE_MARKER)
    operation = raw.get(_OPERATION_MARKER)
    generation = raw.get(_GENERATION_MARKER)
    if not isinstance(workspace, str) or not workspace:
        return None
    if not isinstance(operation, str) or not operation:
        return None
    try:
        generation = int(generation)
        try:
            normalized_workspace: UUID | str = UUID(workspace)
        except ValueError:
            normalized_workspace = workspace
        try:
            normalized_operation: UUID | str = UUID(operation)
        except ValueError:
            normalized_operation = operation
        return OwnershipMetadata(normalized_workspace, normalized_operation, generation)
    except (TypeError, ValueError):
        return None


def _machine_state(raw: Any, fallback: MachineState) -> MachineState:
    if isinstance(raw, str):
        normalized = raw.lower()
        try:
            return MachineState(normalized)
        except ValueError:
            return MachineState.UNKNOWN
    return fallback


def _container_state(raw: Any) -> ContainerState:
    if isinstance(raw, Mapping):
        raw = raw.get("state") or raw.get("status") or raw.get("health")
    if isinstance(raw, str):
        normalized = raw.lower()
        if normalized in {"passing", "healthy", "running"}:
            return ContainerState.STARTED
        try:
            return ContainerState(normalized)
        except ValueError:
            return ContainerState.UNKNOWN
    return ContainerState.UNKNOWN


def _machine_health(
    raw: Mapping[str, Any], state: MachineState
) -> MachineHealth | None:
    containers: dict[str, ContainerState] = {}
    config = raw.get("config") if isinstance(raw.get("config"), Mapping) else {}
    configured = config.get("containers")
    if isinstance(configured, list):
        for item in configured:
            if isinstance(item, Mapping) and isinstance(item.get("name"), str):
                status = item.get("state") or item.get("status") or item.get("health")
                containers[item["name"]] = _container_state(status)
    checks = raw.get("checks")
    check_entries: list[tuple[str, Any]] = []
    if isinstance(checks, Mapping):
        check_entries.extend(
            (name, check) for name, check in checks.items() if isinstance(name, str)
        )
    elif isinstance(checks, list):
        check_entries.extend(
            (check["name"], check)
            for check in checks
            if isinstance(check, Mapping) and isinstance(check.get("name"), str)
        )
    for name, check in check_entries:
        state = _container_state(check)
        if name not in containers or containers[name] is ContainerState.UNKNOWN:
            containers[name] = state
    if not containers and state is MachineState.UNKNOWN:
        return None
    return MachineHealth(state, containers)


def _minimal_machine(
    machine_id: str, app_name: str, state: MachineState
) -> MachineRecord:
    return MachineRecord(
        machine_id,
        machine_id,
        app_name,
        "unknown",
        state,
        health=MachineHealth(state, {}),
    )


def _is_machine_action_ack(payload: Any) -> bool:
    return isinstance(payload, Mapping) and (
        payload.get("ok") is True
        or "previous_state" in payload
        or "new_host" in payload
        or "migrated" in payload
    )


def _verify_volume_spec(volume: VolumeRecord, spec: VolumeSpec) -> None:
    if volume.app_name != spec.app_name or volume.name != spec.name:
        raise ProviderOwnershipError(
            "provider Volume did not match deterministic workspace identity",
            operation="ensure_volume",
            details={"resource_type": "volume", "resource_id": volume.id},
        )
    if volume.region != spec.region or volume.size_gb != spec.size_gb:
        raise ProviderInvalidConfigurationError(
            "provider Volume does not match requested placement or size",
            operation="ensure_volume",
            details={
                "resource_type": "volume",
                "resource_id": volume.id,
                "region": volume.region,
            },
        )


def _verify_machine_spec(machine: MachineRecord, spec: MachineSpec) -> None:
    if machine.app_name != spec.app_name or machine.name != spec.name:
        raise ProviderOwnershipError(
            "provider Machine did not match deterministic workspace identity",
            operation="ensure_machine",
            details={"resource_type": "machine", "resource_id": machine.id},
        )
    if machine.ownership != spec.ownership:
        raise ProviderOwnershipError(
            "provider Machine ownership marker did not match",
            operation="ensure_machine",
            details={"resource_type": "machine", "resource_id": machine.id},
        )
    if machine.volume_id and machine.volume_id != spec.mount.volume_id:
        raise ProviderConflictError(
            "provider Machine is mounted to a different Volume",
            operation="ensure_machine",
            details={"resource_type": "machine", "resource_id": machine.id},
        )


__all__ = [
    "FlyHttpProvider",
    "FlyProvider",
    "FlyProviderAdapter",
    "WorkspaceResourceNames",
    "deterministic_app_name",
    "deterministic_machine_name",
    "deterministic_resource_names",
    "deterministic_volume_name",
]
