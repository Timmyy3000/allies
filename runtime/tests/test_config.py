from __future__ import annotations

import pytest

from allies_runtime.config import (
    CredentialReference,
    RuntimeSettings,
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


def test_settings_accept_validated_foundry_runtime_connection():
    settings = load_settings(
        {
            "FOUNDRY_ORIGIN": "https://foundry.example.com/",
            "FOUNDRY_RUNTIME_CREDENTIAL_REF": (
                "file:///run/secrets/foundry-runtime-token"
            ),
        }
    )

    assert settings.foundry_origin == "https://foundry.example.com"
    assert settings.foundry_credential_ref == (
        "file:///run/secrets/foundry-runtime-token"
    )
    assert "foundry-runtime-token" not in repr(settings.foundry_credential_ref)


@pytest.mark.parametrize(
    "env",
    [
        {"HERMES_ORIGIN": "http://localhost:8642"},
        {"HERMES_ORIGIN": "https://127.0.0.1:8642"},
        {"HERMES_CREDENTIAL_REF": "Bearer plaintext"},
        {"PROOF_SLOTS": "1"},
        {"HERMES_REQUEST_TIMEOUT": "181"},
        {"VOLUME_MARKER_PATH": "/tmp/not-hermes"},
        {"HERMES_IMAGE": "hermes:latest"},
        {"HERMES_SOURCE_COMMIT": "not-a-commit"},
        {"FOUNDRY_ORIGIN": "http://foundry.example.com"},
        {"FOUNDRY_ORIGIN": "https://user:secret@foundry.example.com"},
        {"FOUNDRY_ORIGIN": "https://foundry.example.com/api"},
        {"FOUNDRY_RUNTIME_CREDENTIAL_REF": "runtime-secret"},
        {"FOUNDRY_ORIGIN": "https://foundry.example.com:invalid"},
        {"HERMES_ORIGIN": "http://127.0.0.1:invalid"},
        {"VOLUME_MARKER_PATH": "/opt/data/../outside"},
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


@pytest.mark.parametrize("value", ["bad", "0", "6", "nan", "inf"])
def test_activity_wait_setting_rejects_unbounded_values(value):
    with pytest.raises(SettingsError):
        load_settings({"ALLIES_RUNTIME_ACTIVITY_WAIT_SECONDS": value})


def test_activity_wait_defaults_on_with_explicit_rollback():
    assert RuntimeSettings().activity_wait_enabled
    assert load_settings({}).activity_wait_enabled
    assert not load_settings(
        {"ALLIES_RUNTIME_ACTIVITY_WAIT_ENABLED": "false"}
    ).activity_wait_enabled
    settings = load_settings(
        {
            "ALLIES_RUNTIME_ACTIVITY_WAIT_ENABLED": "true",
            "ALLIES_RUNTIME_ACTIVITY_WAIT_SECONDS": "2",
        }
    )
    assert settings.activity_wait_enabled
    assert settings.activity_wait_seconds == 2


def test_marker_can_be_nested_under_custom_volume():
    settings = load_settings(
        {"VOLUME_ROOT": "/mnt/tenant", "VOLUME_MARKER_PATH": "/mnt/tenant/proof"}
    )
    assert settings.marker_path == "/mnt/tenant/proof"


def test_credential_reference_rejects_non_uri():
    with pytest.raises(SettingsError):
        CredentialReference("raw-secret")
