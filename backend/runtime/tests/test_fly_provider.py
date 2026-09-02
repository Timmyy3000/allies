from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from runtime.providers import (
    AppSpec,
    ContainerFileSecret,
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
    ProviderRetryableError,
    ProviderTimeoutError,
    ProviderUnauthorizedError,
    ProviderUnsupportedTopologyError,
    TransportResponse,
    VolumeMount,
    VolumeRecord,
    deterministic_app_name,
    deterministic_machine_name,
    deterministic_volume_name,
    provider_workspace_context,
)

FIXTURES = Path(__file__).parent / "fixtures" / "providers"
WORKSPACE_ID = UUID("01234567-89ab-cdef-0123-456789abcdef")
OPERATION_ID = UUID("11111111-2222-3333-4444-555555555555")
HERMES_FILE_SECRET = "FND008_HERMES_KEY"
OPENAI_FILE_SECRET = "FND008_OPENAI_KEY"


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
                command=("sh", "-c", "exec hermes gateway run --no-supervise"),
                entrypoint=("/bin/sh",),
                user="0",
                environment={
                    "HERMES_ENV": "/run/secrets/hermes.env",
                    "GATEWAY_MULTIPLEX_PROFILES": "true",
                },
                secret_files=(
                    ContainerFileSecret("/run/secrets/hermes.env", "FND008_HERMES_ENV"),
                ),
                healthchecks=(healthcheck("hermes"),),
            ),
            ContainerSpec(
                "allies-runtime",
                "registry.example/runtime@sha256:runtime",
                secret_files=(
                    ContainerFileSecret(
                        "/run/secrets/hermes-api-key", HERMES_FILE_SECRET
                    ),
                    ContainerFileSecret(
                        "/run/secrets/openai-api-key", OPENAI_FILE_SECRET
                    ),
                ),
                healthchecks=(healthcheck("allies-runtime"),),
            ),
        ),
        mount=VolumeMount("vol-01"),
        ownership=ownership(generation),
        runtime_credential_ref=OpaqueReference("vault://runtime/opaque-ref"),
        foundry_origin="https://foundry.example.com",
        foundry_runtime_credential_ref=OpaqueReference(
            "file:///run/secrets/foundry-runtime-token"
        ),
        foundry_runtime_credential_secret_name="FND008_RUNTIME_G1",
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
    volume_name = deterministic_volume_name(WORKSPACE_ID)
    assert len(volume_name) == 30
    assert volume_name.isalnum()
    assert volume_name == volume_name.lower()
    assert volume_name.startswith("avol")


def test_volume_name_preserves_full_workspace_identity():
    first = UUID("01234567-89ab-cdef-0123-456789abcdef")
    last_bit_changed = UUID("01234567-89ab-cdef-0123-456789abcdee")

    assert deterministic_volume_name(first) != deterministic_volume_name(
        last_bit_changed
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


def test_provider_observes_direct_operations_once_and_aliases(monkeypatch):
    events = []
    monkeypatch.setenv("ALLIES_OBSERVABILITY_DIGEST_KEY", "test-digest")
    monkeypatch.setattr(
        "runtime.providers.fly.emit_event",
        lambda event: events.append(event),
    )
    fake = FakeFlyTransport(
        [
            TransportResponse(404, {}),
            TransportResponse(200, fixture("app.json")),
        ]
    )
    result = provider(fake).ensure_app(
        AppSpec(deterministic_app_name(WORKSPACE_ID), "allies-pilot", "ams")
    )

    assert result.id == "app-01"
    operations = [event["operation"] for event in events]
    assert operations == ["inspect_app", "inspect_app", "create_app", "create_app"]
    assert "ensure_app" not in operations
    assert all(event["workspace_id"].startswith("id_") for event in events)

    machine_fake = FakeFlyTransport(
        [TransportResponse(200, fixture("machines.json"))]
    )
    machine_provider = provider(machine_fake)
    assert machine_provider.reconcile_machine(
        deterministic_app_name(WORKSPACE_ID), deterministic_machine_name(WORKSPACE_ID, 1)
    ) is not None
    assert events[-2]["operation"] == "inspect_machine"
    assert events[-1]["operation"] == "inspect_machine"
    assert all(event["workspace_id"].startswith("id_") for event in events)


def test_wait_machine_only_emits_nested_inspection_pair(monkeypatch):
    events = []
    monkeypatch.setenv("ALLIES_OBSERVABILITY_DIGEST_KEY", "test-digest")
    monkeypatch.setattr(
        "runtime.providers.fly.emit_event",
        lambda event: events.append(event),
    )
    fake = FakeFlyTransport(
        [
            TransportResponse(200, {"ok": True}),
            TransportResponse(200, fixture("machines.json")[0]),
        ]
    )

    provider(fake).wait_machine(
        deterministic_app_name(WORKSPACE_ID), "machine-01", timeout_seconds=10
    )

    assert [event["operation"] for event in events] == [
        "inspect_machine_by_id",
        "inspect_machine_by_id",
    ]
    assert all(event["workspace_id"].startswith("id_") for event in events)


def test_provider_context_correlates_non_deterministic_call_shapes(monkeypatch):
    events = []
    monkeypatch.setenv("ALLIES_OBSERVABILITY_DIGEST_KEY", "test-digest")
    monkeypatch.setattr(
        "runtime.providers.fly.emit_event",
        lambda event: events.append(event),
    )
    app_payload = fixture("app.json")
    app_payload["name"] = "app-01"
    fake = FakeFlyTransport([TransportResponse(200, app_payload)])

    with provider_workspace_context(WORKSPACE_ID):
        provider(fake).inspect_app("app-01")

    assert len(events) == 2
    assert all(event["workspace_id"].startswith("id_") for event in events)


def test_machine_payload_has_two_containers_private_mount_and_opaque_ref_only():
    fake = FakeFlyTransport([TransportResponse(200, fixture("machines.json")[0])])
    result = provider(fake).create_machine(machine_spec())
    payload = fake.calls[0].json_body
    config = payload["config"]
    assert result.id == "machine-01"
    assert payload["skip_launch"] is True
    assert [item["name"] for item in config["containers"]] == [
        "hermes",
        "allies-runtime",
    ]
    assert config["mounts"] == [{"volume": "vol-01", "path": "/opt/data"}]
    assert config["services"] == []
    assert config["guest"] == {
        "cpu_kind": "shared",
        "cpus": 1,
        "memory_mb": 1024,
    }
    assert config["containers"][0]["healthchecks"][0]["name"] == "hermes"
    assert config["containers"][1]["healthchecks"][0]["name"] == "allies-runtime"
    assert config["containers"][0]["cmd"] == [
        "sh",
        "-c",
        "exec hermes gateway run --no-supervise",
    ]
    assert config["containers"][0]["entrypoint"] == ["/bin/sh"]
    assert config["containers"][0]["user"] == "0"
    assert "command" not in config["containers"][0]
    assert config["containers"][0]["env"] == {
        "HERMES_ENV": "/run/secrets/hermes.env",
        "GATEWAY_MULTIPLEX_PROFILES": "true",
    }
    assert config["containers"][0]["files"] == [
        {
            "guest_path": "/run/secrets/hermes.env",
            "secret_name": "FND008_HERMES_ENV",
        }
    ]
    assert config["metadata"]["allies_machine_generation"] == "1"
    assert config["metadata"]["fly_platform_version"] == "v2"
    assert config["metadata"]["fly_process_group"] == "app"
    assert config["containers"][1]["env"] == {
        "HERMES_CREDENTIAL_REF": "vault://runtime/opaque-ref",
        "FOUNDRY_ORIGIN": "https://foundry.example.com",
        "FOUNDRY_RUNTIME_CREDENTIAL_REF": ("file:///run/secrets/foundry-runtime-token"),
    }
    assert config["containers"][1]["files"] == [
        {
            "guest_path": "/run/secrets/hermes-api-key",
            "secret_name": "FND008_HERMES_KEY",
        },
        {
            "guest_path": "/run/secrets/openai-api-key",
            "secret_name": "FND008_OPENAI_KEY",
        },
        {
            "guest_path": "/run/secrets/foundry-runtime-token",
            "secret_name": "FND008_RUNTIME_G1",
        },
    ]
    assert config["containers"][0]["secrets"] == [
        {"env_var": "FND008_HERMES_ENV", "name": "FND008_HERMES_ENV"}
    ]
    assert config["containers"][1]["secrets"] == [
        {"env_var": "FND008_HERMES_KEY", "name": "FND008_HERMES_KEY"},
        {"env_var": "FND008_OPENAI_KEY", "name": "FND008_OPENAI_KEY"},
        {"env_var": "FND008_RUNTIME_G1", "name": "FND008_RUNTIME_G1"},
    ]
    assert result.health is not None
    assert result.health.containers == {
        "hermes": ContainerState.STARTED,
        "allies-runtime": ContainerState.STARTED,
    }
    serialized = json.dumps(payload)
    assert "fly-token-must-not-be-retained" not in serialized
    assert "plain-secret" not in serialized
    assert "foundry-secret" not in serialized
    assert fake.calls[0].headers["Authorization"] == "<redacted>"
    assert fake.calls[0].timeout == 10.0


def test_machine_payload_includes_current_release_metadata():
    fly = provider(FakeFlyTransport([]))
    fly.set_release_metadata("rel_release123", "2")

    metadata = fly.machine_payload(machine_spec())["config"]["metadata"]

    assert metadata["fly_release_id"] == "rel_release123"
    assert metadata["fly_release_version"] == "2"


def test_container_file_secret_rejects_paths_outside_runtime_secret_root():
    with pytest.raises(ValueError, match="/run/secrets"):
        ContainerFileSecret("/opt/data/private", "FND008_SECRET")


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


def test_machine_health_uses_top_level_runtime_container_states():
    machine = fixture("machines.json")[0]
    machine.pop("checks")
    machine["containers"] = [
        {"name": "hermes", "state": "healthy"},
        {"name": "allies-runtime", "state": "healthy"},
    ]
    fake = FakeFlyTransport([TransportResponse(200, machine)])

    result = provider(fake).inspect_machine_by_id("workspace-app", "machine-01")

    assert result is not None
    assert result.health is not None
    assert result.health.containers == {
        "hermes": ContainerState.STARTED,
        "allies-runtime": ContainerState.STARTED,
    }


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
        [
            TransportResponse(200, {"ok": True}),
            TransportResponse(200, fixture("machines.json")[0]),
            TransportResponse(200, {"ok": True}),
        ]
    )
    adapter = provider(fake)
    waited = adapter.wait_machine("app", "machine", timeout_seconds=10)
    started = adapter.start_machine("app", "machine")
    assert waited.state.value == "started"
    assert started.state.value == "started"
    assert fake.calls[0].url.endswith("/machines/machine/wait?state=started&timeout=10")
    assert fake.calls[1].url.endswith("/machines/machine")


def test_wait_acknowledgement_preserves_authoritative_created_state():
    machine = dict(fixture("machines.json")[0])
    machine["state"] = "created"
    fake = FakeFlyTransport(
        [TransportResponse(200, {"ok": True}), TransportResponse(200, machine)]
    )

    waited = provider(fake).wait_machine("app", "machine-01", timeout_seconds=10)

    assert waited.state is MachineState.CREATED


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


def test_start_precondition_is_retryable_without_retaining_response_body():
    fake = FakeFlyTransport(
        [TransportResponse(412, {"message": "sensitive provider detail"})]
    )

    with pytest.raises(ProviderRetryableError) as caught:
        provider(fake).start_machine("workspace-app", "machine-01")

    assert caught.value.operation == "start_machine"
    assert caught.value.status_code == 412
    assert "sensitive provider detail" not in str(caught.value)


def test_unsupported_topology_gate_runs_before_machine_request():
    fake = FakeFlyTransport([])
    blocked = provider(fake, multi_container_enabled=False)
    with pytest.raises(ProviderUnsupportedTopologyError):
        blocked.create_machine(machine_spec())
    assert fake.calls == []


def test_proof_capability_gate_requires_explicit_file_secret_support():
    fake = FakeFlyTransport([])
    provider(fake).assert_proof_capabilities()

    with pytest.raises(ProviderUnsupportedTopologyError, match="file secrets"):
        provider(fake, file_secrets_enabled=False).assert_proof_capabilities()
