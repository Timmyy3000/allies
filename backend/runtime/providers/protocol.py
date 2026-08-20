"""Small provider protocol consumed by workspace lifecycle services."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Protocol
from uuid import UUID

from .domain import (
    AppRecord,
    AppSpec,
    MachineRecord,
    MachineSpec,
    VolumeRecord,
    VolumeSpec,
)

_provider_workspace_id: ContextVar[UUID | str | None] = ContextVar(
    "foundry_provider_workspace_id", default=None
)


@contextmanager
def provider_workspace_context(workspace_id: UUID | str):
    """Carry the lifecycle workspace identity across provider calls safely."""

    token = _provider_workspace_id.set(workspace_id)
    try:
        yield
    finally:
        _provider_workspace_id.reset(token)


def current_provider_workspace_id() -> UUID | str | None:
    return _provider_workspace_id.get()


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
        state: str = "started",
    ) -> MachineRecord: ...

    def start_machine(self, app_name: str, machine_id: str) -> MachineRecord: ...

    def stop_machine(self, app_name: str, machine_id: str) -> MachineRecord: ...

    def destroy_machine(self, app_name: str, machine_id: str) -> None: ...

    def delete_volume(self, app_name: str, volume_id: str) -> None: ...

    def delete_app(self, app_name: str) -> None: ...

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


__all__ = [
    "FlyProvider",
    "FlyProviderProtocol",
    "Provider",
    "WorkspaceProvider",
    "current_provider_workspace_id",
    "provider_workspace_context",
]
