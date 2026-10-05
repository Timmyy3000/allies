from __future__ import annotations

from uuid import uuid4

import pytest

from runtime.providers import (
    AppRecord,
    AppSpec,
    ContainerSpec,
    MachineSpec,
    OpaqueReference,
    OwnershipMetadata,
    ProviderAttachmentConflictError,
    ProviderTimeoutError,
    VolumeMount,
    VolumeRecord,
    VolumeSpec,
)


def ownership(generation=1):
    return OwnershipMetadata(uuid4(), uuid4(), generation)


def test_domain_records_validate_provider_identity_without_transport_shapes():
    app_spec = AppSpec("workspace-app", "pilot", "ams")
    app = AppRecord("app-id", app_spec.name, app_spec.organization)
    volume_spec = VolumeSpec(app.name, "workspace-volume", app_spec.region)
    volume = VolumeRecord(
        "volume-id",
        volume_spec.name,
        volume_spec.app_name,
        volume_spec.region,
        volume_spec.size_gb,
    )

    assert app.name == volume.app_name
    assert volume.attached_machine_id is None


def test_machine_spec_carries_only_opaque_credential_reference_and_private_mount():
    spec = MachineSpec(
        app_name="workspace-app",
        name="workspace-machine-1",
        region="ams",
        containers=(
            ContainerSpec("hermes", "hermes@sha256:digest"),
            ContainerSpec("allies-runtime", "runtime@sha256:digest"),
        ),
        mount=VolumeMount("volume-id"),
        ownership=ownership(),
        runtime_credential_ref="vault://workspace/runtime-token",
    )

    assert spec.mount.path == "/opt/data"
    assert isinstance(spec.runtime_credential_ref, OpaqueReference)
    assert spec.runtime_credential_ref.reference.startswith("vault://")
    assert spec.public_services == ()

    with pytest.raises(ValueError, match="public services"):
        MachineSpec(
            app_name="workspace-app",
            name="workspace-machine-2",
            region="ams",
            containers=(ContainerSpec("hermes", "hermes@sha256:digest"),),
            mount=VolumeMount("volume-id"),
            ownership=ownership(),
            public_services=("http",),
        )


def test_provider_errors_expose_retry_and_uncertainty_without_response_bodies():
    timeout = ProviderTimeoutError(
        "provider request timed out", operation="create_machine"
    )
    assert timeout.retryable is True
    assert timeout.uncertain is True
    assert timeout.code == "provider_timeout"
    assert not hasattr(timeout, "response_body")

    conflict = ProviderAttachmentConflictError(
        volume_id="volume-id",
        attached_machine_id="other-machine",
    )
    assert conflict.retryable is False
    assert conflict.code == "volume_attachment_conflict"
