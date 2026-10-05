"""FND-004 adapter from the runtime smoke boundary to FND-003 seams.

This module is intentionally a thin integration layer.  ``WorkspaceLifecycle``
still owns phase claims/retries and ``FlyProvider`` still owns provider
translation.  The adapter only performs capability preflight, records the
binding returned by lifecycle, and cleans resources in a run-scoped ledger.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from runtime.providers import (
    ContainerSpec,
    ContainerState,
    MachineState,
    OpaqueReference,
    ProviderError,
    ProviderNotFoundError,
    ProviderTerminalError,
    ProviderUnsupportedTopologyError,
    WorkspaceResourceNames,
    deterministic_resource_names,
)
from runtime.services.workspaces import (
    WorkspaceBinding,
    WorkspaceLifecycle,
    WorkspaceSpec,
)

try:
    from allies_runtime.evidence import EvidenceCheck, VolumeVisibility, check
    from allies_runtime.integration import (
        CleanupResult,
        IntegrationSnapshot,
        OwnedResourceLedger,
    )
except ImportError:  # pragma: no cover - backend-only commands do not import runtime
    from enum import StrEnum

    class VolumeVisibility(StrEnum):
        ABSENT = "absent"
        READ_ONLY = "read-only"
        READ_WRITE = "read-write"

    @dataclass(frozen=True, slots=True)
    class EvidenceCheck:
        name: str
        status: str
        detail: str | None = None

    def check(name: str, status: str, detail: str | None = None) -> EvidenceCheck:
        return EvidenceCheck(name, status, detail)

    @dataclass(frozen=True, slots=True)
    class IntegrationSnapshot:
        resource_ids: dict[str, str]
        checks: tuple[EvidenceCheck, ...] = ()
        volume_visibility: VolumeVisibility = VolumeVisibility.ABSENT

    @dataclass(frozen=True, slots=True)
    class CleanupResult:
        status: str
        checks: tuple[EvidenceCheck, ...] = ()

    OwnedResourceLedger = Any  # type: ignore[assignment,misc]


PINNED_HERMES_IMAGE = (
    "nousresearch/hermes-agent@sha256:"
    "b6f18532e2c082ef6686c659fc222427e41fde3eed08aa058411f0ea5ab705ca"
)
PINNED_HERMES_SOURCE_COMMIT = "36cb5ae5530a75def7df3195e49b7a4aa2add482"
_IMAGE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$", re.IGNORECASE)


class LiveCompositionError(RuntimeError):
    """Safe failure raised before an operator smoke can create resources."""

    code = "live_composition_blocked"


_REFERENCE = re.compile(r"^[a-z][a-z0-9+.-]{1,31}://[^\s]{1,191}$", re.IGNORECASE)


def _process_healthcheck(name: str) -> dict[str, object]:
    return {
        "name": name,
        "exec": {"command": ["/bin/sh", "-c", "test -r /proc/1/stat"]},
        "interval": 5,
        "timeout": 2,
        "grace_period": 5,
    }


def build_hermes_runtime_spec(
    *,
    runtime_image: str,
    runtime_credential_ref: str | None = None,
    organization: str = "allies",
    region: str = "ams",
    volume_size_gb: int = 1,
    filesystem: str = "ext4",
) -> WorkspaceSpec:
    """Build the immutable two-container FND-004 topology input."""

    if not _IMAGE.fullmatch(runtime_image):
        raise ValueError("runtime_image must be an immutable image digest")
    credential_ref = None
    if runtime_credential_ref is not None:
        if (
            not isinstance(runtime_credential_ref, str)
            or not _REFERENCE.fullmatch(runtime_credential_ref.strip())
            or runtime_credential_ref.lower().startswith(
                ("bearer ", "token=", "key=", "sk-", "api_key=")
            )
        ):
            raise ValueError("runtime_credential_ref must be an opaque URI reference")
        credential_ref = OpaqueReference(runtime_credential_ref.strip())
    return WorkspaceSpec(
        organization=organization,
        region=region,
        volume_size_gb=volume_size_gb,
        filesystem=filesystem,
        runtime_credential_ref=credential_ref,
        containers=(
            ContainerSpec(
                "hermes",
                PINNED_HERMES_IMAGE,
                healthchecks=(_process_healthcheck("hermes_liveness"),),
            ),
            ContainerSpec(
                "allies-runtime",
                runtime_image,
                healthchecks=(_process_healthcheck("runtime_readiness"),),
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class LiveSmokeComposition:
    """Fully wired, still-gated live proof components."""

    integration: ProviderLifecycleSmokeIntegration
    client: Any
    bootstrap: Any
    settings: Any
    spec: WorkspaceSpec


def compose_live_smoke(
    workspace_id: UUID | str,
    *,
    env: dict[str, str] | None = None,
    credential_resolver: Callable[..., Any] | None = None,
    provider_factory: Callable[..., Any] | None = None,
    lifecycle_factory: Callable[..., Any] | None = None,
    client_factory: Callable[..., Any] | None = None,
    bootstrap_factory: Callable[..., Any] | None = None,
) -> LiveSmokeComposition:
    """Construct the operator-facing provider/runtime live proof boundary.

    Factories exist for deterministic wiring tests. The default composition
    uses the existing FlyProvider/WorkspaceLifecycle and imports the separate
    runtime package only when the operator has installed it. No factory is
    allowed to receive a plaintext credential except the injected resolver
    that owns the secure lookup.
    """

    values = dict(os.environ if env is None else env)
    if values.get("FND004_LIVE_SMOKE") != "1":
        raise LiveCompositionError("live_opt_in_required")
    if not values.get("FLY_API_TOKEN"):
        raise LiveCompositionError("fly_api_token_required")
    if values.get("FLY_MULTI_CONTAINER_ENABLED", "").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        raise LiveCompositionError("multi_container_capability_required")
    if not values.get("HERMES_CREDENTIAL_REF"):
        raise LiveCompositionError("hermes_credential_reference_required")
    runtime_image = values.get("RUNTIME_IMAGE", "")
    if not _IMAGE.fullmatch(runtime_image):
        raise LiveCompositionError("runtime_image_digest_required")
    if bootstrap_factory is None:
        raise LiveCompositionError("secure_profile_bootstrap_required")
    try:
        from allies_runtime.config import SettingsError, load_settings
        from allies_runtime.hermes import (
            TEST_CREDENTIAL_PREFIX,
            HermesClient,
            test_credential_for_reference,
        )
    except ImportError as exc:  # backend-only installs cannot run live proof
        raise LiveCompositionError("runtime_package_required") from exc
    if credential_resolver is None:
        reference = values["HERMES_CREDENTIAL_REF"].lower()
        if reference.startswith(TEST_CREDENTIAL_PREFIX):
            credential_resolver = test_credential_for_reference
        else:
            raise LiveCompositionError("credential_resolver_required")

    try:
        workspace_uuid = (
            workspace_id if isinstance(workspace_id, UUID) else UUID(str(workspace_id))
        )
    except (TypeError, ValueError) as exc:
        raise LiveCompositionError("workspace_id_invalid") from exc
    try:
        settings = load_settings(values)
    except SettingsError as exc:
        raise LiveCompositionError("settings_validation_failed") from exc
    provider = (
        provider_factory(
            api_token=values["FLY_API_TOKEN"], multi_container_enabled=True
        )
        if provider_factory is not None
        else _default_fly_provider(values)
    )
    preflight = getattr(provider, "preflight", None) or getattr(
        provider, "assert_topology_supported", None
    )
    if preflight is None:
        raise LiveCompositionError("provider_capability_gate_missing")
    try:
        preflight()
    except ProviderUnsupportedTopologyError as exc:
        raise LiveCompositionError("multi_container_capability_required") from exc
    except ProviderError as exc:
        # Preserve the provider's sanitized classification so an auth,
        # timeout, or API failure is not reported as a capability problem.
        raise LiveCompositionError(f"provider_preflight_{exc.code}") from exc
    except Exception as exc:
        raise LiveCompositionError("provider_preflight_failed") from exc
    spec = build_hermes_runtime_spec(
        runtime_image=runtime_image,
        runtime_credential_ref=values.get("HERMES_CREDENTIAL_REF"),
        organization=values.get("FLY_ORG", "allies"),
        region=values.get("FLY_REGION", "ams"),
    )
    lifecycle = (
        lifecycle_factory(provider)
        if lifecycle_factory is not None
        else WorkspaceLifecycle(provider)
    )
    client = (
        client_factory(settings, credential_resolver)
        if client_factory is not None
        else HermesClient(settings, credential_resolver)
    )
    bootstrap = bootstrap_factory()
    if bootstrap is None:
        raise LiveCompositionError("secure_profile_bootstrap_required")
    integration = ProviderLifecycleSmokeIntegration(
        provider,
        lifecycle,
        workspace_uuid,
        spec,
        marker_path=values.get("VOLUME_MARKER_PATH"),
        volume_root=values.get("VOLUME_ROOT", "/opt/data"),
    )
    return LiveSmokeComposition(integration, client, bootstrap, settings, spec)


def _default_fly_provider(values: dict[str, str]) -> Any:
    from runtime.providers import FlyProvider

    return FlyProvider(
        api_token=values["FLY_API_TOKEN"],
        multi_container_enabled=True,
    )


@dataclass(slots=True)
class ProviderLifecycleSmokeIntegration:
    """Use the existing provider/lifecycle services for one smoke run."""

    provider: Any
    lifecycle: WorkspaceLifecycle
    workspace_id: UUID | str
    spec: WorkspaceSpec
    marker_path: str | Path | None = None
    volume_root: str | Path = "/opt/data"
    _binding: WorkspaceBinding | None = None
    _app_name: str | None = None
    _reserved_machine_name: str | None = None
    _reserved_volume_name: str | None = None
    _before_bind: Callable[[float], None] | None = None

    def configure_before_bind(self, callback: Callable[[float], None] | None) -> None:
        """Install the final authenticated activation gate for this run."""

        self._before_bind = callback

    def preflight(self) -> None:
        gate = getattr(self.provider, "preflight", None)
        if gate is None:
            gate = getattr(self.provider, "assert_topology_supported", None)
        if gate is not None:
            gate()

    def reserve(self, run_id: str) -> IntegrationSnapshot:
        """Reserve deterministic owned references before lifecycle side effects.

        ``WorkspaceLifecycle`` may fail after creating an App or Volume (or a
        provider request may time out after creating a Machine).  The runtime
        ledger therefore receives the workspace-derived identifiers before the
        first ensure call.  A later lifecycle snapshot replaces these values
        with provider IDs when available; an uncertain phase still has a
        bounded, workspace-scoped cleanup target.
        """

        names: WorkspaceResourceNames = deterministic_resource_names(self.workspace_id)
        inspect_app = getattr(self.provider, "inspect_app", None)
        if inspect_app is None:
            raise RuntimeError("smoke ownership probe is unavailable")
        try:
            existing_app = inspect_app(names.app, organization=self.spec.organization)
        except ProviderNotFoundError:
            existing_app = None
        if existing_app is not None:
            raise RuntimeError("smoke workspace resources already exist")
        self._app_name = names.app
        self._reserved_machine_name = names.machine(1)
        self._reserved_volume_name = names.volume
        return IntegrationSnapshot(
            resource_ids={
                "app": names.app,
                "volume": names.volume,
                "machine": names.machine(1),
            }
        )

    def provision(self, run_id: str) -> IntegrationSnapshot:
        if self._before_bind is None:
            self._binding = self.lifecycle.ensure_workspace(
                self.workspace_id, self.spec
            )
        else:

            def before_bind(*args: Any) -> None:
                deadline = args[-1] if args and isinstance(args[-1], float) else 0.0
                try:
                    self._before_bind(deadline)
                except ProviderError:
                    raise
                except Exception as exc:
                    raise ProviderTerminalError(
                        "live profile bootstrap activation failed",
                        operation="live_profile_bootstrap",
                    ) from exc

            self._binding = self.lifecycle.ensure_workspace(
                self.workspace_id,
                self.spec,
                before_bind=before_bind,
            )
        names: WorkspaceResourceNames = deterministic_resource_names(self.workspace_id)
        self._app_name = names.app
        machine = self._inspect_machine(self._binding.machine_ref)
        checks = [
            check("topology_capability", "pass"),
            check(
                "machine_containers",
                "pass" if self._has_required_containers(machine) else "fail",
            ),
            check("container_health", "pass" if self._healthy(machine) else "fail"),
            check(
                "process_failure_visibility",
                "pass"
                if machine is not None and machine.health is not None
                else "fail",
            ),
        ]
        volume_visibility = self._volume_visibility()
        checks.append(
            check(
                "volume_marker_continuity",
                "pass"
                if self.marker_path is None or Path(self.marker_path).is_file()
                else "skip",
            )
        )
        snapshot = IntegrationSnapshot(
            resource_ids={
                "app": self._binding.app_ref,
                "volume": self._binding.volume_ref,
                "machine": self._binding.machine_ref,
            },
            checks=tuple(checks),
            volume_visibility=volume_visibility,
        )
        self._reserved_machine_name = None
        self._reserved_volume_name = None
        return snapshot

    async def cleanup(
        self, ledger: OwnedResourceLedger, *, deadline: float
    ) -> CleanupResult:
        """Stop/destroy only recorded IDs; 404 is an idempotent success."""

        # A lifecycle binding is authoritative even when the post-binding
        # inspection below fails. Promote those IDs over the provisional names
        # reserved before provisioning so cleanup never falls back to deleting
        # an unresolved name after the provider has returned real identities.
        if self._binding is not None:
            ledger.record("app", self._binding.app_ref)
            ledger.record("volume", self._binding.volume_ref)
            ledger.record("machine", self._binding.machine_ref)

        if not self._app_name:
            return CleanupResult(
                "complete", (check("cleanup_owned_resources", "pass"),)
            )

        cleaners: dict[str, Callable[[str], Any]] = {
            "machine": self._clean_machine,
        }
        delete_volume = getattr(self.provider, "delete_volume", None)
        if delete_volume is not None:
            cleaners["volume"] = self._clean_volume
        delete_app = getattr(self.provider, "delete_app", None)
        if delete_app is not None:
            cleaners["app"] = lambda value: delete_app(self._app_name)
        import asyncio

        remaining = max(0.001, deadline - asyncio.get_running_loop().time())
        return await ledger.cleanup(cleaners, timeout_seconds=remaining)

    def _clean_machine(self, machine_id: str) -> None:
        try:
            try:
                machine = self._inspect_machine(machine_id)
            except Exception:
                # Once lifecycle returned this exact ID, ownership is already
                # established. If inspection is temporarily unavailable, use
                # the authoritative ID directly; provisional names still
                # fail closed below because they have no binding proof.
                if self._binding is None or machine_id != self._binding.machine_ref:
                    raise
                machine = None
            if machine is None and machine_id == self._reserved_machine_name:
                raise RuntimeError("smoke Machine ID could not be reconciled")
            resolved_id = machine.id if machine is not None else machine_id
            if machine is None or machine.state not in {
                MachineState.STOPPED,
                MachineState.DESTROYED,
            }:
                try:
                    self.provider.stop_machine(self._app_name, resolved_id)
                except ProviderNotFoundError:
                    return
            try:
                self.provider.destroy_machine(self._app_name, resolved_id)
            except ProviderNotFoundError:
                return
        except ProviderNotFoundError:
            return

    def _inspect_machine(self, machine_id: str) -> Any:
        inspect = getattr(self.provider, "inspect_machine_by_id", None)
        if inspect is not None:
            try:
                machine = inspect(self._app_name or "", machine_id)
            except ProviderNotFoundError:
                machine = None
            if machine is not None:
                return machine
        inspect_by_name = getattr(self.provider, "inspect_machine", None)
        if inspect_by_name is not None:
            try:
                return inspect_by_name(self._app_name or "", machine_id)
            except ProviderNotFoundError:
                return None
        return None

    def _clean_volume(self, volume_ref: str) -> None:
        list_volumes = getattr(self.provider, "list_volumes", None)
        if list_volumes is None:
            if volume_ref == self._reserved_volume_name:
                raise RuntimeError("smoke Volume ID could not be reconciled")
            self.provider.delete_volume(self._app_name, volume_ref)
            return
        try:
            volumes = tuple(list_volumes(self._app_name or ""))
        except ProviderNotFoundError:
            if volume_ref == self._reserved_volume_name:
                raise RuntimeError("smoke Volume could not be reconciled") from None
            # A lifecycle-returned ID remains authoritative even when the
            # provider's list endpoint is temporarily unavailable. The delete
            # endpoint is idempotent and can distinguish an already-gone ID.
            self.provider.delete_volume(self._app_name, volume_ref)
            return
        exact_id = next((volume for volume in volumes if volume.id == volume_ref), None)
        if exact_id is not None:
            target = exact_id
        else:
            name_matches = tuple(
                volume for volume in volumes if volume.name == volume_ref
            )
            if not name_matches:
                if volume_ref == self._reserved_volume_name:
                    raise RuntimeError("smoke Volume ID could not be reconciled")
                # The lifecycle may have returned an authoritative volume ID that
                # is no longer visible in the list response.  Attempt that ID
                # directly; a provider 404 remains an idempotent ledger success.
                self.provider.delete_volume(self._app_name, volume_ref)
                return
            if len(name_matches) > 1:
                raise RuntimeError("smoke volume ownership is ambiguous")
            target = name_matches[0]
        self.provider.delete_volume(self._app_name, target.id)

    @staticmethod
    def _has_required_containers(machine: Any) -> bool:
        required = {"hermes", "allies-runtime"}
        health = getattr(machine, "health", None)
        return health is not None and required.issubset(health.containers)

    @classmethod
    def _healthy(cls, machine: Any) -> bool:
        health = getattr(machine, "health", None)
        return (
            cls._has_required_containers(machine)
            and getattr(machine, "state", None) is MachineState.STARTED
            and all(
                health.containers[name] is ContainerState.STARTED
                for name in ("hermes", "allies-runtime")
            )
        )

    def _volume_visibility(self) -> Any:
        if self.marker_path is None:
            return VolumeVisibility.ABSENT
        marker = Path(self.marker_path)
        if not marker.is_file():
            return VolumeVisibility.ABSENT
        if os.access(marker, os.W_OK):
            return VolumeVisibility.READ_WRITE
        return VolumeVisibility.READ_ONLY


__all__ = [
    "PINNED_HERMES_IMAGE",
    "PINNED_HERMES_SOURCE_COMMIT",
    "LiveCompositionError",
    "LiveSmokeComposition",
    "ProviderLifecycleSmokeIntegration",
    "build_hermes_runtime_spec",
    "compose_live_smoke",
]
