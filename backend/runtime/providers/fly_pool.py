"""Small Fly adapter used by the bounded ready-pool maintainer."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from uuid import UUID

from runtime.models import ReadyWorkspaceBundle, RuntimeCredential, Workspace
from runtime.providers.domain import MachineRecord, MachineState, VolumeRecord
from runtime.providers.errors import (
    ProviderInvalidConfigurationError,
    ProviderNotFoundError,
    ProviderOwnershipError,
    ProviderRetryableError,
)
from runtime.providers.fly import deterministic_resource_names
from runtime.providers.protocol import WorkspaceProvider, provider_workspace_context
from runtime.services.runtime_auth import revoke_runtime_credential


class FlyPoolAdapter:
    """Translate one recorded Fly binding into the pool service evidence."""

    def __init__(
        self,
        provider: WorkspaceProvider,
        activator: Callable[[UUID], Any],
        *,
        organization: str | None = None,
        blank_probe: Callable[[Workspace], bool] | None = None,
    ) -> None:
        self.provider = provider
        self.activator = activator
        self.organization = organization or os.environ.get("FLY_ORG", "").strip()
        if not self.organization:
            raise ProviderInvalidConfigurationError(
                "FLY_ORG is required for pool ownership checks",
                operation="pool_config",
            )
        self.blank_probe = blank_probe
        self._fresh_volume_workspaces: set[UUID] = set()

    @classmethod
    def from_environment(cls) -> FlyPoolAdapter:
        """Build the default adapter without importing Fly at module load."""

        from runtime.management.commands.activate_fly_workspace import Command
        from runtime.services.runtime_provider import runtime_power_provider

        return cls(
            runtime_power_provider(),
            Command().activate_registered_workspace,
        )

    def activate(self, workspace_id: UUID) -> Any:
        workspace = Workspace.objects.get(pk=workspace_id)
        names = deterministic_resource_names(workspace_id)
        if (
            not workspace.fly_app_ref
            and not workspace.volume_ref
            and not workspace.machine_ref
        ):
            with provider_workspace_context(workspace_id):
                app = self.provider.inspect_app(names.app)
            if app is None:
                self._fresh_volume_workspaces.add(workspace_id)
        with provider_workspace_context(workspace_id):
            return self.activator(workspace_id)

    def record_fresh_volume(self, workspace: Workspace) -> str | None:
        """Return the exact Volume created by this adapter's fresh activation."""

        if workspace.id not in self._fresh_volume_workspaces:
            return None
        names = deterministic_resource_names(workspace.id)
        if (
            not workspace.fly_app_ref
            or not workspace.volume_ref
            or not workspace.machine_ref
            or workspace.fly_app_ref != names.app
        ):
            return None
        with provider_workspace_context(workspace.id):
            app = self.provider.inspect_app(workspace.fly_app_ref)
            if app is None:
                raise ProviderNotFoundError(
                    "fresh pool App is missing", operation="pool.fresh_volume"
                )
            self._check_app(app.name, app.organization, workspace.fly_app_ref)
            volumes = tuple(self.provider.list_volumes(workspace.fly_app_ref))
            if len(volumes) != 1 or volumes[0].id != workspace.volume_ref:
                raise ProviderOwnershipError(
                    "fresh pool Volume identity is ambiguous",
                    operation="pool.fresh_volume",
                )
            volume = volumes[0]
            self._check_volume(volume, workspace, names.volume)
            if volume.attached_machine_id != workspace.machine_ref:
                raise ProviderRetryableError(
                    "fresh pool Volume is not attached to its Machine",
                    operation="pool.fresh_volume",
                )
        if self.blank_probe is not None:
            blank = self.blank_probe(workspace)
            if type(blank) is not bool:
                raise ProviderRetryableError(
                    "pool blank-volume probe did not return a boolean",
                    operation="pool.fresh_volume",
                )
            if not blank:
                raise ProviderOwnershipError(
                    "fresh pool Volume is not blank",
                    operation="pool.fresh_volume",
                )
        self._fresh_volume_workspaces.discard(workspace.id)
        return workspace.volume_ref

    def inspect(self, workspace: Workspace):
        from runtime.services.ready_pool_maintenance import (
            PoolProviderSnapshot,
            pool_config_fingerprint,
        )

        if (
            not workspace.fly_app_ref
            or not workspace.volume_ref
            or not workspace.machine_ref
        ):
            raise ProviderNotFoundError(
                "pool workspace binding is incomplete", operation="pool.inspect"
            )
        names = deterministic_resource_names(workspace.id)
        if workspace.fly_app_ref != names.app:
            raise ProviderOwnershipError(
                "pool App reference is not deterministic", operation="pool.app"
            )
        with provider_workspace_context(workspace.id):
            app = self.provider.inspect_app(workspace.fly_app_ref)
            if app is None:
                raise ProviderNotFoundError(
                    "recorded pool App is missing", operation="pool.inspect"
                )
            self._check_app(app.name, app.organization, workspace.fly_app_ref)

            volume = self._volume(workspace.fly_app_ref, workspace.volume_ref)
            if volume is None:
                raise ProviderNotFoundError(
                    "recorded pool Volume is missing", operation="pool.inspect"
                )
            self._check_volume(volume, workspace, names.volume)
            machine = self._machine(workspace.fly_app_ref, workspace.machine_ref)
            if machine is None:
                raise ProviderNotFoundError(
                    "recorded pool Machine is missing", operation="pool.inspect"
                )
            self._check_machine(
                machine, workspace, names.machine(workspace.machine_generation)
            )

        health = (
            {}
            if machine.health is None
            else {
                name: str(state.value)
                for name, state in machine.health.containers.items()
            }
        )
        images = dict(machine.images)
        fingerprint = pool_config_fingerprint(
            region=machine.region,
            images=images,
            containers=tuple(images),
        )
        durable_blank = ReadyWorkspaceBundle.objects.filter(
            workspace_id=workspace.id,
            blank_volume_ref=workspace.volume_ref,
        ).exists()
        fresh_activation = workspace.id in self._fresh_volume_workspaces
        self._fresh_volume_workspaces.discard(workspace.id)
        blank = (
            self.blank_probe(workspace)
            if self.blank_probe is not None
            else durable_blank or fresh_activation
        )
        if type(blank) is not bool:
            raise ProviderRetryableError(
                "pool blank-volume probe did not return a boolean",
                operation="pool.inspect",
            )
        ownership = machine.ownership
        return PoolProviderSnapshot(
            app_ref=workspace.fly_app_ref,
            volume_ref=volume.id,
            machine_ref=machine.id,
            region=machine.region,
            machine_state=str(machine.state.value),
            health_containers=health,
            ownership_workspace_id=ownership.workspace_id if ownership else "",
            ownership_operation_id=ownership.operation_id if ownership else None,
            ownership_generation=ownership.generation if ownership else 0,
            volume_attached_machine_ref=volume.attached_machine_id,
            images=images,
            config_fingerprint=fingerprint,
            blank=blank,
        )

    def cleanup(self, workspace: Workspace) -> bool:
        """Delete only exact, independently rechecked owned resources."""

        app_ref = workspace.fly_app_ref
        expected_app = deterministic_resource_names(workspace.id).app
        if app_ref and app_ref != expected_app:
            raise ProviderOwnershipError(
                "pool cleanup App reference is not deterministic",
                operation="pool.cleanup",
            )
        if not app_ref:
            if workspace.volume_ref or workspace.machine_ref:
                raise ProviderOwnershipError(
                    "pool cleanup has provider refs but no recorded App",
                    operation="pool.cleanup",
                )
            self._revoke_credentials(workspace.id)
            return True

        with provider_workspace_context(workspace.id):
            app = self.provider.inspect_app(app_ref)
            if app is None:
                self._revoke_credentials(workspace.id)
                return True
            self._check_app(app.name, app.organization, app_ref)
            self._revoke_credentials(workspace.id)
            if workspace.machine_ref:
                machine = self._machine(app_ref, workspace.machine_ref)
                if machine is not None:
                    self._check_machine(
                        machine,
                        workspace,
                        deterministic_resource_names(workspace.id).machine(
                            workspace.machine_generation
                        ),
                    )
                    self._destroy_machine(app_ref, workspace.machine_ref)
            if workspace.volume_ref:
                volume = self._volume(app_ref, workspace.volume_ref)
                if volume is not None:
                    self._check_volume(
                        volume,
                        workspace,
                        deterministic_resource_names(workspace.id).volume,
                    )
                    if volume.attached_machine_id:
                        raise ProviderRetryableError(
                            "pool Volume is still attached",
                            operation="pool.cleanup",
                            details={
                                "resource_type": "volume",
                                "resource_id": volume.id,
                            },
                        )
                    try:
                        self.provider.delete_volume(app_ref, volume.id)
                    except ProviderNotFoundError:
                        pass
            try:
                self.provider.delete_app(app_ref)
            except ProviderNotFoundError:
                pass
        return True

    def _machine(self, app_ref: str, machine_ref: str) -> MachineRecord | None:
        inspect = getattr(self.provider, "inspect_machine_by_id", None)
        if callable(inspect):
            return inspect(app_ref, machine_ref)
        return self.provider.inspect_machine(app_ref, machine_ref)

    def _volume(self, app_ref: str, volume_ref: str) -> VolumeRecord | None:
        matches = [
            volume
            for volume in self.provider.list_volumes(app_ref)
            if volume.id == volume_ref
        ]
        if len(matches) > 1:
            raise ProviderOwnershipError(
                "pool Volume identity is ambiguous", operation="pool.volume"
            )
        return matches[0] if matches else None

    def _check_app(self, name: str, organization: str, expected: str) -> None:
        if name != expected or (
            self.organization and organization != self.organization
        ):
            raise ProviderOwnershipError(
                "pool App ownership does not match", operation="pool.app"
            )

    @staticmethod
    def _check_volume(
        volume: VolumeRecord, workspace: Workspace, expected_name: str
    ) -> None:
        expected_region = (
            ReadyWorkspaceBundle.objects.filter(workspace_id=workspace.id)
            .values_list("region", flat=True)
            .first()
        )
        if (
            volume.name != expected_name
            or volume.app_name != workspace.fly_app_ref
            or expected_region is not None
            and volume.region != expected_region
        ):
            raise ProviderOwnershipError(
                "pool Volume identity does not match", operation="pool.volume"
            )
        ownership = volume.ownership
        if ownership is not None and (
            str(ownership.workspace_id) != str(workspace.id)
            or ownership.generation != workspace.machine_generation
        ):
            raise ProviderOwnershipError(
                "pool Volume ownership does not match", operation="pool.volume"
            )

    @staticmethod
    def _check_machine(
        machine: MachineRecord, workspace: Workspace, expected_name: str
    ) -> None:
        ownership = machine.ownership
        if (
            machine.id != workspace.machine_ref
            or machine.name != expected_name
            or machine.app_name != workspace.fly_app_ref
            or machine.volume_id != workspace.volume_ref
            or ownership is None
            or str(ownership.workspace_id) != str(workspace.id)
            or ownership.generation != workspace.machine_generation
            or workspace.provisioning_id is not None
            and str(ownership.operation_id) != str(workspace.provisioning_id)
        ):
            raise ProviderOwnershipError(
                "pool Machine ownership does not match", operation="pool.machine"
            )

    def _destroy_machine(self, app_ref: str, machine_ref: str) -> None:
        machine = self._machine(app_ref, machine_ref)
        if machine is None or machine.state is MachineState.DESTROYED:
            return
        if machine.state is not MachineState.STOPPED:
            try:
                self.provider.stop_machine(app_ref, machine_ref)
            except ProviderNotFoundError:
                return
            machine = self._machine(app_ref, machine_ref)
            if machine is None:
                return
        if machine.state is not MachineState.STOPPED:
            raise ProviderRetryableError(
                "pool Machine did not stop", operation="pool.cleanup"
            )
        try:
            self.provider.destroy_machine(app_ref, machine_ref)
        except ProviderNotFoundError:
            return
        machine = self._machine(app_ref, machine_ref)
        if machine is not None and machine.state is not MachineState.DESTROYED:
            raise ProviderRetryableError(
                "pool Machine destruction is pending", operation="pool.cleanup"
            )

    @staticmethod
    def _revoke_credentials(workspace_id: UUID) -> None:
        for credential_id in RuntimeCredential.objects.filter(
            workspace_id=workspace_id,
            revoked_at__isnull=True,
        ).values_list("id", flat=True):
            revoke_runtime_credential(credential_id)


__all__ = ["FlyPoolAdapter"]
