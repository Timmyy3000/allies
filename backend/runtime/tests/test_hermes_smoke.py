from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from runtime.providers import (
    ContainerState,
    MachineHealth,
    MachineRecord,
    MachineState,
    ProviderTimeoutError,
    deterministic_resource_names,
)
from runtime.services.hermes_smoke import (
    PINNED_HERMES_IMAGE,
    LiveCompositionError,
    ProviderLifecycleSmokeIntegration,
    build_hermes_runtime_spec,
    compose_live_smoke,
)
from runtime.services.workspaces import WorkspaceBinding

WORKSPACE_ID = UUID("01234567-89ab-cdef-0123-456789abcdef")
RUNTIME_PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "runtime"
if str(RUNTIME_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_PACKAGE_ROOT))


def owned_ledger():
    from allies_runtime.integration import OwnedResourceLedger

    return OwnedResourceLedger()


class FakeLifecycle:
    def __init__(self, binding):
        self.binding = binding
        self.calls = []

    def ensure_workspace(self, workspace_id, spec, *, before_bind=None):
        self.calls.append((workspace_id, spec, before_bind))
        if before_bind is not None:
            before_bind(workspace_id, spec, None)
        return self.binding


class FakeProvider:
    def __init__(self, machine):
        self.machine = machine
        self.gates = 0
        self.calls = []

    def preflight(self):
        self.gates += 1

    def inspect_app(self, name, organization=None):
        return None

    def inspect_machine_by_id(self, app_name, machine_id):
        if machine_id == self.machine.id:
            return self.machine
        return None

    def inspect_machine(self, app_name, name, ownership=None):
        if name == self.machine.name:
            return self.machine
        return None

    def list_volumes(self, app_name):
        return [
            type(
                "Volume",
                (),
                {"id": self.machine.volume_id, "name": "allies-volume-test"},
            )()
        ]

    def delete_volume(self, app_name, volume_id):
        self.calls.append(("delete-volume", volume_id))

    def delete_app(self, app_name):
        self.calls.append(("delete-app", app_name))

    def stop_machine(self, app_name, machine_id):
        self.calls.append(("stop", machine_id))
        self.machine = MachineRecord(
            self.machine.id,
            self.machine.name,
            self.machine.app_name,
            self.machine.region,
            MachineState.STOPPED,
            self.machine.volume_id,
            self.machine.ownership,
            MachineHealth(MachineState.STOPPED, {}),
        )

    def destroy_machine(self, app_name, machine_id):
        self.calls.append(("destroy", machine_id))


class FakeLedger:
    def __init__(self):
        self.cleaners = None

    async def cleanup(self, cleaners, *, timeout_seconds):
        self.cleaners = cleaners
        for kind in ("machine", "volume", "app"):
            if kind in cleaners:
                cleaners[kind](f"{kind}-id")
        from runtime.services.hermes_smoke import CleanupResult, check

        return CleanupResult("complete", (check("cleanup", "pass"),))


def binding():
    operation = uuid4()
    return WorkspaceBinding(
        WORKSPACE_ID, "app-id", "volume-id", "machine-id", 1, operation
    )


def machine(healthy=True):
    state = MachineState.STARTED if healthy else MachineState.FAILED
    containers = (
        {"hermes": ContainerState.STARTED, "allies-runtime": ContainerState.STARTED}
        if healthy
        else {}
    )
    return MachineRecord(
        "machine-id",
        "allies-machine-test-1",
        "allies-ws-test",
        "ams",
        state,
        "volume-id",
        None,
        MachineHealth(state, containers),
    )


def test_build_spec_pins_hermes_and_requires_runtime_digest():
    spec = build_hermes_runtime_spec(
        runtime_image="registry.example/runtime@sha256:" + "a" * 64,
        runtime_credential_ref="vault://workspace/runtime-key",
    )
    assert [container.name for container in spec.containers] == [
        "hermes",
        "allies-runtime",
    ]
    assert spec.containers[0].image == PINNED_HERMES_IMAGE
    assert spec.containers[0].command == ()
    assert spec.containers[0].healthchecks[0]["name"] == "hermes_liveness"
    assert spec.runtime_credential_ref.reference == "vault://workspace/runtime-key"
    with pytest.raises(ValueError, match="immutable"):
        build_hermes_runtime_spec(runtime_image="registry.example/runtime:latest")
    with pytest.raises(ValueError, match="opaque"):
        build_hermes_runtime_spec(
            runtime_image="registry.example/runtime@sha256:" + "a" * 64,
            runtime_credential_ref="sk-live-secret",
        )


def test_provider_lifecycle_adapter_preflights_and_records_health(tmp_path):
    provider = FakeProvider(machine())
    lifecycle = FakeLifecycle(binding())
    marker = tmp_path / "marker"
    marker.write_text("hermes", encoding="utf-8")
    adapter = ProviderLifecycleSmokeIntegration(
        provider,
        lifecycle,
        WORKSPACE_ID,
        build_hermes_runtime_spec(
            runtime_image="registry.example/runtime@sha256:" + "b" * 64
        ),
        marker_path=marker,
        volume_root=tmp_path,
    )
    adapter.preflight()
    snapshot = adapter.provision("run-1")
    assert provider.gates == 1
    assert snapshot.resource_ids == {
        "app": "app-id",
        "volume": "volume-id",
        "machine": "machine-id",
    }
    assert {item.name for item in snapshot.checks} >= {
        "machine_containers",
        "container_health",
    }
    assert lifecycle.calls


def test_provider_lifecycle_adapter_reserves_workspace_refs_before_ensure():
    adapter = ProviderLifecycleSmokeIntegration(
        FakeProvider(machine()),
        FakeLifecycle(binding()),
        WORKSPACE_ID,
        build_hermes_runtime_spec(
            runtime_image="registry.example/runtime@sha256:" + "e" * 64
        ),
    )
    snapshot = adapter.reserve("phase-failure")
    names = deterministic_resource_names(WORKSPACE_ID)
    assert snapshot.resource_ids == {
        "app": names.app,
        "volume": names.volume,
        "machine": names.machine(1),
    }
    assert adapter._app_name == names.app


def test_provider_lifecycle_adapter_retains_reserved_names_on_post_binding_failure():
    class BrokenInspectProvider(FakeProvider):
        def inspect_machine_by_id(self, app_name, machine_id):
            raise RuntimeError("machine inspection failed")

    adapter = ProviderLifecycleSmokeIntegration(
        BrokenInspectProvider(machine()),
        FakeLifecycle(binding()),
        WORKSPACE_ID,
        build_hermes_runtime_spec(
            runtime_image="registry.example/runtime@sha256:" + "9" * 64
        ),
    )
    reserved = adapter.reserve("post-binding-failure")
    with pytest.raises(RuntimeError, match="inspection"):
        adapter.provision("post-binding-failure")
    names = deterministic_resource_names(WORKSPACE_ID)
    assert reserved.resource_ids["machine"] == names.machine(1)
    assert adapter._reserved_machine_name == names.machine(1)
    assert adapter._reserved_volume_name == names.volume


def test_provider_lifecycle_cleanup_promotes_binding_ids_after_inspection_failure():
    class BrokenInspectProvider(FakeProvider):
        def inspect_machine_by_id(self, app_name, machine_id):
            raise RuntimeError("machine inspection unavailable")

    provider = BrokenInspectProvider(machine())
    adapter = ProviderLifecycleSmokeIntegration(
        provider,
        FakeLifecycle(binding()),
        WORKSPACE_ID,
        build_hermes_runtime_spec(
            runtime_image="registry.example/runtime@sha256:" + "a" * 64
        ),
    )
    reserved = adapter.reserve("promote-binding-ids")
    with pytest.raises(RuntimeError, match="inspection unavailable"):
        adapter.provision("promote-binding-ids")

    ledger = owned_ledger()
    ledger.record_snapshot(reserved)
    result = asyncio.run(adapter.cleanup(ledger, deadline=9999999999))

    assert result.status == "complete"
    assert ledger.resources == {
        "app": "app-id",
        "volume": "volume-id",
        "machine": "machine-id",
    }
    assert ("stop", "machine-id") in provider.calls
    assert ("destroy", "machine-id") in provider.calls


def test_provider_lifecycle_adapter_rejects_existing_smoke_namespace():
    class ExistingAppProvider(FakeProvider):
        def inspect_app(self, name, organization=None):
            return object()

    adapter = ProviderLifecycleSmokeIntegration(
        ExistingAppProvider(machine()),
        FakeLifecycle(binding()),
        WORKSPACE_ID,
        build_hermes_runtime_spec(
            runtime_image="registry.example/runtime@sha256:" + "1" * 64
        ),
    )
    with pytest.raises(RuntimeError, match="already exist"):
        adapter.reserve("reused-workspace")


def test_provider_lifecycle_adapter_cleanup_stops_then_destroys_machine():
    provider = FakeProvider(machine())
    adapter = ProviderLifecycleSmokeIntegration(
        provider,
        FakeLifecycle(binding()),
        WORKSPACE_ID,
        build_hermes_runtime_spec(
            runtime_image="registry.example/runtime@sha256:" + "c" * 64
        ),
    )
    adapter._app_name = "allies-ws-test"
    ledger = owned_ledger()
    ledger.record_snapshot(
        type(
            "Snapshot",
            (),
            {
                "resource_ids": {
                    "app": "allies-ws-test",
                    "volume": "volume-id",
                    "machine": "machine-id",
                }
            },
        )()
    )
    result = asyncio.run(adapter.cleanup(ledger, deadline=9999999999))
    assert result.status == "complete"
    assert provider.calls == [
        ("stop", "machine-id"),
        ("destroy", "machine-id"),
        ("delete-volume", "volume-id"),
        ("delete-app", "allies-ws-test"),
    ]


def test_provider_lifecycle_adapter_reconciles_reserved_names_to_provider_ids():
    provider = FakeProvider(machine())
    adapter = ProviderLifecycleSmokeIntegration(
        provider,
        FakeLifecycle(binding()),
        WORKSPACE_ID,
        build_hermes_runtime_spec(
            runtime_image="registry.example/runtime@sha256:" + "f" * 64
        ),
    )
    adapter._app_name = "allies-ws-test"
    ledger = owned_ledger()
    ledger.record("app", "allies-ws-test")
    ledger.record("volume", "allies-volume-test")
    ledger.record("machine", "allies-machine-test-1")
    result = asyncio.run(adapter.cleanup(ledger, deadline=9999999999))
    assert result.status == "complete"
    assert ("destroy", "machine-id") in provider.calls
    assert ("delete-volume", "volume-id") in provider.calls


def test_provider_lifecycle_adapter_deletes_unlisted_authoritative_volume_id():
    class UnlistedVolumeProvider(FakeProvider):
        def list_volumes(self, app_name):
            return []

    provider = UnlistedVolumeProvider(machine())
    adapter = ProviderLifecycleSmokeIntegration(
        provider,
        FakeLifecycle(binding()),
        WORKSPACE_ID,
        build_hermes_runtime_spec(
            runtime_image="registry.example/runtime@sha256:" + "a" * 64
        ),
    )
    adapter._app_name = "allies-ws-test"
    ledger = owned_ledger()
    ledger.record("volume", "authoritative-volume-id")
    result = asyncio.run(adapter.cleanup(ledger, deadline=9999999999))
    assert result.status == "complete"
    assert ("delete-volume", "authoritative-volume-id") in provider.calls


def test_provider_lifecycle_adapter_marks_unresolved_reserved_resources_incomplete():
    class MissingResourceProvider(FakeProvider):
        def inspect_machine(self, app_name, name, ownership=None):
            return None

        def list_volumes(self, app_name):
            return []

    provider = MissingResourceProvider(machine())
    adapter = ProviderLifecycleSmokeIntegration(
        provider,
        FakeLifecycle(binding()),
        WORKSPACE_ID,
        build_hermes_runtime_spec(
            runtime_image="registry.example/runtime@sha256:" + "2" * 64
        ),
    )
    adapter._app_name = "allies-ws-test"
    adapter._reserved_machine_name = "allies-machine-test-1"
    adapter._reserved_volume_name = "allies-volume-test"
    ledger = owned_ledger()
    ledger.record("app", "allies-ws-test")
    ledger.record("volume", "allies-volume-test")
    ledger.record("machine", "allies-machine-test-1")
    result = asyncio.run(adapter.cleanup(ledger, deadline=9999999999))
    assert result.status == "incomplete"


def test_provider_lifecycle_cleanup_prefers_exact_volume_id_over_name_collision():
    class CollidingVolumeProvider(FakeProvider):
        def list_volumes(self, app_name):
            return [
                type(
                    "Volume",
                    (),
                    {"id": "volume-id", "name": "other-volume"},
                )(),
                type(
                    "Volume",
                    (),
                    {"id": "other-id", "name": "volume-id"},
                )(),
            ]

    provider = CollidingVolumeProvider(machine())
    adapter = ProviderLifecycleSmokeIntegration(
        provider,
        FakeLifecycle(binding()),
        WORKSPACE_ID,
        build_hermes_runtime_spec(
            runtime_image="registry.example/runtime@sha256:" + "2" * 64
        ),
    )
    adapter._app_name = "allies-ws-test"
    adapter._clean_volume("volume-id")
    assert ("delete-volume", "volume-id") in provider.calls
    assert ("delete-volume", "other-id") not in provider.calls


def live_env():
    return {
        "FND004_LIVE_SMOKE": "1",
        "FLY_API_TOKEN": "opaque-fly-token",
        "FLY_MULTI_CONTAINER_ENABLED": "1",
        "HERMES_CREDENTIAL_REF": "vault://hermes/proof",
        "RUNTIME_IMAGE": "registry.example/runtime@sha256:" + "d" * 64,
    }


def test_live_composition_fails_closed_before_factories_without_capability():
    called = []

    def provider_factory(**kwargs):
        called.append(kwargs)
        return FakeProvider(machine())

    with pytest.raises(LiveCompositionError, match="multi_container"):
        compose_live_smoke(
            WORKSPACE_ID,
            env={**live_env(), "FLY_MULTI_CONTAINER_ENABLED": "0"},
            provider_factory=provider_factory,
            bootstrap_factory=lambda: object(),
            credential_resolver=lambda _: "test-only-key",
        )
    assert called == []


def test_live_composition_wires_provider_lifecycle_client_and_bootstrap():
    provider = FakeProvider(machine())
    lifecycle = FakeLifecycle(binding())
    client = object()
    bootstrap = object()
    composition = compose_live_smoke(
        WORKSPACE_ID,
        env=live_env(),
        provider_factory=lambda **kwargs: provider,
        lifecycle_factory=lambda selected: lifecycle,
        client_factory=lambda settings, resolver: client,
        bootstrap_factory=lambda: bootstrap,
        credential_resolver=lambda reference: "test-only-key",
    )
    assert composition.integration.provider is provider
    assert composition.integration.lifecycle is lifecycle
    assert composition.client is client
    assert composition.bootstrap is bootstrap
    assert composition.spec.containers[0].image == PINNED_HERMES_IMAGE
    assert provider.gates == 1


def test_live_composition_selects_the_proof_only_test_resolver():
    provider = FakeProvider(machine())
    captured = []
    compose_live_smoke(
        WORKSPACE_ID,
        env={**live_env(), "HERMES_CREDENTIAL_REF": "test://fnd004/proof"},
        provider_factory=lambda **kwargs: provider,
        lifecycle_factory=lambda selected: FakeLifecycle(binding()),
        client_factory=lambda settings, resolver: captured.append(resolver) or object(),
        bootstrap_factory=lambda: object(),
    )
    assert len(captured) == 1


def test_live_composition_requires_opaque_reference_and_runtime_image():
    with pytest.raises(LiveCompositionError, match="hermes_credential"):
        compose_live_smoke(
            WORKSPACE_ID,
            env={
                key: value
                for key, value in live_env().items()
                if key != "HERMES_CREDENTIAL_REF"
            },
            bootstrap_factory=lambda: object(),
            credential_resolver=lambda _: "test-only-key",
            provider_factory=lambda **kwargs: FakeProvider(machine()),
        )
    with pytest.raises(LiveCompositionError, match="runtime_image"):
        compose_live_smoke(
            WORKSPACE_ID,
            env={**live_env(), "RUNTIME_IMAGE": "registry.example/runtime:latest"},
            bootstrap_factory=lambda: object(),
            credential_resolver=lambda _: "test-only-key",
            provider_factory=lambda **kwargs: FakeProvider(machine()),
        )


def test_live_composition_classifies_provider_preflight_failures():
    class FailingProvider(FakeProvider):
        def preflight(self):
            raise ProviderTimeoutError("Fly preflight timed out")

    with pytest.raises(
        LiveCompositionError, match="provider_preflight_provider_timeout"
    ):
        compose_live_smoke(
            WORKSPACE_ID,
            env=live_env(),
            provider_factory=lambda **kwargs: FailingProvider(machine()),
            bootstrap_factory=lambda: object(),
            credential_resolver=lambda _: "test-only-key",
        )


def test_live_composition_classifies_settings_validation_failures():
    with pytest.raises(LiveCompositionError, match="settings_validation_failed"):
        compose_live_smoke(
            WORKSPACE_ID,
            env={**live_env(), "HERMES_REQUEST_TIMEOUT": "61"},
            provider_factory=lambda **kwargs: FakeProvider(machine()),
            bootstrap_factory=lambda: object(),
            credential_resolver=lambda _: "test-only-key",
        )
