from __future__ import annotations

import pytest

from allies_runtime.config import (
    CredentialReference,
    SettingsError,
    load_settings,
    validate_image_reference,
)


def test_settings_use_loopback_and_opaque_reference():
    settings = load_settings({"HERMES_CREDENTIAL_REF": "vault://tenant/hermes"})
    assert settings.hermes_origin == "http://127.0.0.1:8642"
    assert settings.credential_ref == "vault://tenant/hermes"
    assert "vault://" not in repr(settings.credential_ref)
    assert settings.proof_slots >= 2


@pytest.mark.parametrize(
    "env",
    [
        {"HERMES_ORIGIN": "http://localhost:8642"},
        {"HERMES_ORIGIN": "https://127.0.0.1:8642"},
        {"HERMES_CREDENTIAL_REF": "Bearer plaintext"},
        {"PROOF_SLOTS": "1"},
        {"HERMES_REQUEST_TIMEOUT": "61"},
        {"VOLUME_MARKER_PATH": "/tmp/not-hermes"},
        {"HERMES_IMAGE": "hermes:latest"},
        {"HERMES_SOURCE_COMMIT": "not-a-commit"},
    ],
)
def test_settings_reject_unsafe_values(env):
    with pytest.raises(SettingsError):
        load_settings(env)


def test_image_reference_is_immutable():
    digest = "registry.example/runtime@sha256:" + "a" * 64
    assert validate_image_reference(digest) == digest
    with pytest.raises(SettingsError):
        validate_image_reference("registry.example/runtime:latest")


def test_marker_can_be_nested_under_custom_volume():
    settings = load_settings(
        {"VOLUME_ROOT": "/mnt/tenant", "VOLUME_MARKER_PATH": "/mnt/tenant/proof"}
    )
    assert settings.marker_path == "/mnt/tenant/proof"


def test_credential_reference_rejects_non_uri():
    with pytest.raises(SettingsError):
        CredentialReference("raw-secret")
