from dataclasses import replace
from uuid import uuid4

import pytest

from runtime.providers import (
    FakeFlyTransport,
    ProviderInvalidConfigurationError,
    TransportResponse,
    VolumeSpec,
)
from runtime.services.workspaces import WorkspaceSpec
from runtime.tests.test_fly_provider import fixture, machine_spec, provider


def test_workspace_sizing_reaches_machine_payload_and_provider_observation():
    workspace = WorkspaceSpec(
        hermes_image="registry.example/hermes@sha256:hermes",
        runtime_image="registry.example/runtime@sha256:runtime",
        cpus=2,
        memory_mb=2048,
        volume_size_gb=10,
    )
    spec = workspace.machine_spec(uuid4(), "vol-01", 1, uuid4())
    assert (spec.cpu_kind, spec.cpus, spec.memory_mb) == ("shared", 2, 2048)
    assert workspace.volume_spec(uuid4()).size_gb == 10
    raw = fixture("machines.json")[0]
    raw["config"]["guest"] = {"cpu_kind": "shared", "cpus": 2, "memory_mb": 2048}
    fake = FakeFlyTransport([TransportResponse(200, raw)])
    observed = provider(fake).create_machine(
        replace(machine_spec(), cpus=2, memory_mb=2048)
    )
    assert fake.calls[0].json_body["config"]["guest"] == raw["config"]["guest"]
    assert (observed.cpu_kind, observed.cpus, observed.memory_mb) == ("shared", 2, 2048)


@pytest.mark.parametrize("size", [10, 20])
def test_adopt_volume_preserves_at_least_requested_capacity(size):
    raw = fixture("volumes.json")[0]
    raw.update(size_gb=size, name="workspacevolume")
    fake = FakeFlyTransport([TransportResponse(200, [raw])])
    volume = provider(fake).ensure_volume(
        VolumeSpec("workspaceapp", "workspacevolume", "ams", 10)
    )
    assert volume.id == "vol-01"
    assert volume.size_gb == size
    assert len(fake.calls) == 1
    assert fake.calls[0].method == "GET"


def test_adopt_undersized_volume_refuses_without_replacement():
    raw = fixture("volumes.json")[0]
    raw.update(size_gb=1, name="workspacevolume")
    fake = FakeFlyTransport([TransportResponse(200, [raw])])
    with pytest.raises(ProviderInvalidConfigurationError):
        provider(fake).ensure_volume(
            VolumeSpec("workspaceapp", "workspacevolume", "ams", 10)
        )
    assert len(fake.calls) == 1


@pytest.mark.parametrize(
    "fields", [{"cpus": True}, {"cpus": 0}, {"memory_mb": -1}, {"cpu_kind": "unknown"}]
)
def test_invalid_sizing_rejected_before_provider_work(fields):
    with pytest.raises(ValueError):
        WorkspaceSpec(**fields)
    with pytest.raises(ValueError):
        replace(machine_spec(), **fields)


@pytest.mark.parametrize(
    "guest", [{}, {"cpu_kind": [], "cpus": True, "memory_mb": "2048"}]
)
def test_missing_or_malformed_observed_size_is_not_invented(guest):
    raw = fixture("machines.json")[0]
    raw["config"]["guest"] = guest
    fake = FakeFlyTransport([TransportResponse(200, raw)])
    observed = provider(fake).inspect_machine_by_id(machine_spec().app_name, raw["id"])
    assert (observed.cpu_kind, observed.cpus, observed.memory_mb) == (None, None, None)


@pytest.mark.parametrize("mode", ["create", "adopt", "timeout"])
@pytest.mark.parametrize(
    "guest", [{}, {"cpu_kind": "shared", "cpus": 1, "memory_mb": 1024}]
)
def test_machine_size_mismatch_fails_closed(mode, guest):
    raw = fixture("machines.json")[0]
    raw["config"]["guest"] = guest
    responses = [TransportResponse(200, raw)]
    if mode == "adopt":
        responses = [TransportResponse(200, [raw])]
    elif mode == "timeout":
        responses = [
            TransportResponse(200, []),
            TimeoutError("uncertain"),
            TransportResponse(200, [raw]),
        ]
    fake = FakeFlyTransport(responses)
    adapter = provider(fake)
    operation = adapter.create_machine if mode == "create" else adapter.ensure_machine
    with pytest.raises(ProviderInvalidConfigurationError):
        operation(replace(machine_spec(), cpus=2, memory_mb=2048))


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("size", [1, 10, 20])
def test_replacement_checks_volume_capacity_before_stopping_old_machine(size):
    from runtime.models import Workspace
    from runtime.services.workspaces import WorkspaceLifecycle
    from runtime.tests.test_workspace_lifecycle import FakeProvider, spec

    adapter = FakeProvider()
    lifecycle = WorkspaceLifecycle(adapter, sleep=lambda _: None, jitter=False)
    workspace = Workspace.objects.create(tenant_ref="sizing-replacement")
    binding = lifecycle.ensure_workspace(workspace.id, spec())
    adapter.volume = replace(adapter.volume, size_gb=size)
    adapter.calls.clear()
    desired = replace(spec(), cpus=2, memory_mb=2048, volume_size_gb=10)
    if size < 10:
        with pytest.raises(ProviderInvalidConfigurationError):
            lifecycle.replace_machine(workspace.id, desired, 1)
        assert "stop_machine" not in adapter.calls
        assert "destroy_machine" not in adapter.calls
        assert binding.machine_ref in adapter.machines
    else:
        replacement = lifecycle.replace_machine(workspace.id, desired, 1)
        assert replacement.volume_ref == binding.volume_ref
    assert adapter.volume.id == binding.volume_ref
    assert adapter.volume.size_gb == size
