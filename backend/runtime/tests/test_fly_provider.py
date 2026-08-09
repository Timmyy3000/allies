from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from runtime.providers import (
    AppSpec,
    ContainerSpec,
    ContainerState,
    FakeFlyTransport,
    FlyHttpClient,
    FlyProvider,
    MachineSpec,
    MachineState,
    OpaqueReference,
    OwnershipMetadata,
    ProviderAttachmentConflictError,
    ProviderInvalidConfigurationError,
    ProviderOwnershipError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnauthorizedError,
    ProviderUnsupportedTopologyError,
    TransportResponse,
    VolumeMount,
    VolumeRecord,
    deterministic_app_name,
    deterministic_machine_name,
    deterministic_volume_name,
)

FIXTURES = Path(__file__).parent / "fixtures" / "providers"
WORKSPACE_ID = UUID("01234567-89ab-cdef-0123-456789abcdef")
OPERATION_ID = UUID("11111111-2222-3333-4444-555555555555")


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def provider(fake: FakeFlyTransport, **kwargs) -> FlyProvider:
    kwargs.setdefault("multi_container_enabled", True)
    return FlyProvider(
        http_client=FlyHttpClient(
            api_token="fly-token-must-not-be-retained",
            transport=fake,
        ),
        **kwargs,
    )


def ownership(generation: int = 1) -> OwnershipMetadata:
    return OwnershipMetadata(WORKSPACE_ID, OPERATION_ID, generation)


def healthcheck(name: str) -> dict[str, object]:
    return {
        "name": name,
        "exec": {"command": ["/bin/sh", "-c", "test -r /proc/1/stat"]},
        "interval": 5,
        "timeout": 2,
        "grace_period": 5,
    }


def machine_spec(generation: int = 1) -> MachineSpec:
    return MachineSpec(
        app_name=deterministic_app_name(WORKSPACE_ID),
        name=deterministic_machine_name(WORKSPACE_ID, generation),
        region="ams",
        containers=(
            ContainerSpec(
                "hermes",
                "registry.example/hermes@sha256:hermes",
                healthchecks=(healthcheck("hermes"),),
            ),
            ContainerSpec(
                "allies-runtime",
                "registry.example/runtime@sha256:runtime",
                healthchecks=(healthcheck("allies-runtime"),),
            ),
        ),
        mount=VolumeMount("vol-01"),
        ownership=ownership(generation),
        runtime_credential_ref=OpaqueReference("vault://runtime/opaque-ref"),
    )


def test_names_are_stable_and_generation_scoped():
    assert deterministic_app_name(WORKSPACE_ID) == deterministic_app_name(
        str(WORKSPACE_ID)
    )
    assert deterministic_volume_name(WORKSPACE_ID) != deterministic_app_name(
        WORKSPACE_ID
    )
    assert deterministic_machine_name(WORKSPACE_ID, 1) != deterministic_machine_name(
        WORKSPACE_ID, 2
    )


def test_app_create_timeout_reconciles_by_deterministic_name():
    fake = FakeFlyTransport(
        [
            TransportResponse(404, {}),
            TimeoutError("request timed out"),
            TransportResponse(200, fixture("app.json")),
        ]
    )
    result = provider(fake).ensure_app(
        AppSpec(deterministic_app_name(WORKSPACE_ID), "allies-pilot", "ams")
    )
    assert result.id == "app-01"
    assert [call.method for call in fake.calls] == ["GET", "POST", "GET"]
    assert fake.calls[1].json_body == {
        "app_name": deterministic_app_name(WORKSPACE_ID),
        "org_slug": "allies-pilot",
    }


def test_machine_payload_has_two_containers_private_mount_and_opaque_ref_only():
    fake = FakeFlyTransport([TransportResponse(200, fixture("machines.json")[0])])
    result = provider(fake).create_machine(machine_spec())
    payload = fake.calls[0].json_body
    config = payload["config"]
    assert result.id == "machine-01"
    assert [item["name"] for item in config["containers"]] == [
        "hermes",
        "allies-runtime",
    ]
    assert config["mounts"] == [{"volume": "vol-01", "guest_path": "/opt/data"}]
    assert config["services"] == []
    assert config["containers"][0]["healthchecks"][0]["name"] == "hermes"
    assert config["containers"][1]["healthchecks"][0]["name"] == "allies-runtime"
    assert config["metadata"]["allies_machine_generation"] == "1"
    assert config["containers"][1]["env"] == {
        "ALLIES_RUNTIME_CREDENTIAL_REF": "vault://runtime/opaque-ref"
    }
    assert result.health is not None
    assert result.health.containers == {
        "hermes": ContainerState.STARTED,
        "allies-runtime": ContainerState.STARTED,
    }
    serialized = json.dumps(payload)
    assert "fly-token-must-not-be-retained" not in serialized
    assert "plain-secret" not in serialized
    assert fake.calls[0].headers["Authorization"] == "<redacted>"
    assert fake.calls[0].timeout == 10.0


def test_machine_payload_requires_named_healthchecks():
    fake = FakeFlyTransport([])
    containers = (
        ContainerSpec("hermes", "registry.example/hermes@sha256:hermes"),
        ContainerSpec(
            "allies-runtime",
            "registry.example/runtime@sha256:runtime",
            healthchecks=(healthcheck("allies-runtime"),),
        ),
    )
    unready_spec = MachineSpec(
        app_name=deterministic_app_name(WORKSPACE_ID),
        name=deterministic_machine_name(WORKSPACE_ID, 1),
        region="ams",
        containers=containers,
        mount=VolumeMount("vol-01"),
        ownership=ownership(),
    )

    with pytest.raises(ProviderInvalidConfigurationError, match="healthcheck"):
        provider(fake).machine_payload(unready_spec)
    assert fake.calls == []


def test_start_action_ack_is_not_parsed_as_a_machine_record():
    fake = FakeFlyTransport(
        [
            TransportResponse(
                200,
                {"previous_state": "stopped", "migrated": False, "new_host": ""},
            )
        ]
    )

    started = provider(fake).start_machine("workspace-app", "machine-01")

    assert started.id == "machine-01"
    assert started.state is MachineState.STARTED


def test_default_provider_reads_fly_api_token_from_environment(monkeypatch):
    monkeypatch.setenv("FLY_API_TOKEN", "environment-token")
    fake = FakeFlyTransport([TransportResponse(200, fixture("app.json"))])

    provider_from_env = FlyProvider(transport=fake, multi_container_enabled=True)
    provider_from_env.inspect_app(deterministic_app_name(WORKSPACE_ID))

    assert fake.calls[0].headers["Authorization"] == "<redacted>"


def test_default_provider_requires_fly_api_token(monkeypatch):
    monkeypatch.delenv("FLY_API_TOKEN", raising=False)
    with pytest.raises(ProviderInvalidConfigurationError, match="FLY_API_TOKEN"):
        FlyProvider(transport=FakeFlyTransport(), multi_container_enabled=True)


def test_machine_reconciliation_rejects_unknown_ownership():
    machine = fixture("machines.json")[0]
    machine["config"]["metadata"]["allies_operation_id"] = str(UUID(int=3))
    fake = FakeFlyTransport([TransportResponse(200, [machine])])
    with pytest.raises(ProviderOwnershipError) as caught:
        provider(fake).ensure_machine(machine_spec())
    assert caught.value.code == "provider_ownership"


def test_machine_reconciliation_normalizes_uuid_metadata():
    fake = FakeFlyTransport([TransportResponse(200, fixture("machines.json"))])
    result = provider(fake).ensure_machine(machine_spec())
    assert result.id == "machine-01"
    assert result.ownership == ownership()


def test_attachment_conflict_is_typed_and_does_not_start_machine():
    fake = FakeFlyTransport([])
    volume = VolumeRecord("vol-01", "workspace", "app", "ams", 1, "other-machine")
    with pytest.raises(ProviderAttachmentConflictError) as caught:
        FlyProvider.check_volume_attachment(volume)
    assert caught.value.volume_id == "vol-01"
    assert not fake.calls


def test_wait_and_start_ok_responses_map_to_machine_records():
    fake = FakeFlyTransport(
        [TransportResponse(200, {"ok": True}), TransportResponse(200, {"ok": True})]
    )
    adapter = provider(fake)
    waited = adapter.wait_machine("app", "machine", timeout_seconds=10)
    started = adapter.start_machine("app", "machine")
    assert waited.state.value == "started"
    assert started.state.value == "started"
    assert fake.calls[0].url.endswith("/machines/machine/wait?state=started&timeout=10")


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, ProviderUnauthorizedError),
        (403, ProviderUnauthorizedError),
        (400, ProviderInvalidConfigurationError),
        (422, ProviderInvalidConfigurationError),
        (408, ProviderTimeoutError),
        (429, ProviderRateLimitError),
    ],
)
def test_status_mapping_is_typed_and_does_not_retain_response_body(status, error):
    fake = FakeFlyTransport([TransportResponse(status, {"message": "secret response"})])
    with pytest.raises(error) as caught:
        provider(fake).inspect_app("missing")
    assert not hasattr(caught.value, "response_body")
    assert "secret response" not in str(caught.value)


def test_unsupported_topology_gate_runs_before_machine_request():
    fake = FakeFlyTransport([])
    blocked = provider(fake, multi_container_enabled=False)
    with pytest.raises(ProviderUnsupportedTopologyError):
        blocked.create_machine(machine_spec())
    assert fake.calls == []
