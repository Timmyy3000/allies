"""Small provider protocol consumed by workspace lifecycle services."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .domain import (
    AppRecord,
    AppSpec,
    MachineRecord,
    MachineSpec,
    VolumeRecord,
    VolumeSpec,
)


class WorkspaceProvider(Protocol):
    """Provider operations needed by ensure and explicit replacement.

    Every method represents one bounded provider operation. Implementations
    should perform no lifecycle retries here; callers reconcile and retry at
    the durable operation phase boundary.
    """

    def inspect_app(self, name: str) -> AppRecord | None: ...

    def create_app(self, spec: AppSpec) -> AppRecord: ...

    def list_volumes(self, app_name: str) -> Sequence[VolumeRecord]: ...

    def create_volume(self, spec: VolumeSpec) -> VolumeRecord: ...

    def inspect_machine(self, app_name: str, name: str) -> MachineRecord | None: ...

    def create_machine(self, spec: MachineSpec) -> MachineRecord: ...

    def wait_machine(
        self,
        app_name: str,
        machine_id: str,
        *,
        timeout_seconds: float,
    ) -> MachineRecord: ...

    def start_machine(self, app_name: str, machine_id: str) -> MachineRecord: ...

    def stop_machine(self, app_name: str, machine_id: str) -> MachineRecord: ...

    def destroy_machine(self, app_name: str, machine_id: str) -> None: ...

    def acquire_machine_lease(
        self,
        app_name: str,
        machine_id: str,
        *,
        lease_seconds: int,
    ) -> str | None: ...

    def release_machine_lease(
        self,
        app_name: str,
        machine_id: str,
        lease_token: str,
    ) -> None: ...


# Names used by the accepted plan and by future adapter implementations.
FlyProvider = WorkspaceProvider
FlyProviderProtocol = WorkspaceProvider
Provider = WorkspaceProvider


__all__ = ["FlyProvider", "FlyProviderProtocol", "Provider", "WorkspaceProvider"]
