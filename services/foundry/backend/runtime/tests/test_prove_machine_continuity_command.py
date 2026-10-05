from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from runtime.services.continuity_proof import ContinuityProofResult, ProofCheck


def command_args(output):
    digest = "registry.example/image@sha256:" + "a" * 64
    provider_key = output.parent / "openai-api-key"
    provider_key.write_text("provider-key-must-not-escape", encoding="utf-8")
    return (
        "--runtime-image",
        digest,
        "--hermes-image",
        digest,
        "--foundry-origin",
        "https://foundry.example.com",
        "--output",
        str(output),
        "--provider-api-key-file",
        str(provider_key),
        "--model",
        "gpt-test",
        "--run-id",
        "fnd008-command",
    )


@pytest.mark.django_db
def test_command_requires_explicit_live_and_writes_skipped_evidence(tmp_path):
    output = tmp_path / "skipped.json"

    with pytest.raises(CommandError) as caught:
        call_command("prove_machine_continuity", *command_args(output))

    assert caught.value.returncode == 2
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "skipped"
    assert payload["checks"][0]["detail_code"] == "live_flag_required"


@pytest.mark.django_db
def test_live_command_writes_only_the_service_evidence(monkeypatch, tmp_path):
    from runtime.management.commands import prove_machine_continuity as command

    output = tmp_path / "passed.json"
    expected = ContinuityProofResult(
        run_id="fnd008-command",
        status="pass",
        checks=(ProofCheck("continuity_recovery", "pass", "history_complete"),),
        workspace={
            "workspace_id": "00000000-0000-0000-0000-000000000008",
            "old_generation": 1,
            "new_generation": 2,
        },
        resources={"app": "allies-proof-app"},
        executions=(),
        sessions=(),
        cleanup="complete",
    )
    monkeypatch.setattr(command, "FlyProvider", lambda **_kwargs: object())
    monkeypatch.setattr(
        command.Command,
        "_check_foundry_reachable",
        staticmethod(lambda _origin: None),
    )
    monkeypatch.setattr(
        command,
        "FlyCliSecretStore",
        lambda: SimpleNamespace(
            executable="fly",
            deploy=lambda _app_ref: None,
            bootstrap_release=lambda _app_ref, _image, _region: None,
        ),
    )
    monkeypatch.setattr(
        command.Command, "_fly_api_token", staticmethod(lambda _: "fly-token")
    )
    captured = {}

    def dependency_bootstrap(store, *, provider_api_key):
        captured["provider_api_key"] = provider_api_key
        return object()

    monkeypatch.setattr(command, "ProofCredentialBootstrap", lambda _store: object())
    monkeypatch.setattr(
        command, "ProofDependencyCredentialBootstrap", dependency_bootstrap
    )
    monkeypatch.setattr(
        command,
        "run_machine_replacement_proof",
        lambda config, **_kwargs: captured.update(config=config) or expected,
    )

    call_command("prove_machine_continuity", "--live", *command_args(output))

    assert json.loads(output.read_text(encoding="utf-8")) == expected.to_dict()
    assert captured["provider_api_key"] == "provider-key-must-not-escape"
    assert captured["config"].timeout_seconds == 600.0
    assert {profile.seed.provider for profile in captured["config"].profiles} == {
        "custom"
    }
    assert {profile.seed.base_url for profile in captured["config"].profiles} == {
        "https://api.openai.com/v1"
    }
    assert all(
        profile.recognizable_fact.casefold()
        not in profile.seed.personality.casefold()
        for profile in captured["config"].profiles
    )
    assert "provider-key-must-not-escape" not in output.read_text(encoding="utf-8")


def test_provider_api_key_file_must_be_absolute(tmp_path):
    from runtime.management.commands.prove_machine_continuity import Command

    with pytest.raises(ValueError, match="unavailable"):
        Command._secret_file("openai-api-key")


@pytest.mark.django_db
def test_command_preflight_rejects_mutable_image_before_provider(monkeypatch, tmp_path):
    from runtime.management.commands import prove_machine_continuity as command

    output = tmp_path / "invalid.json"
    args = list(command_args(output))
    args[1] = "registry.example/runtime:latest"
    provider_calls = []
    monkeypatch.setattr(command, "FlyProvider", lambda: provider_calls.append(True))

    with pytest.raises(CommandError) as caught:
        call_command("prove_machine_continuity", "--live", *args)

    assert caught.value.returncode == 2
    assert provider_calls == []
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "skipped"


def test_fly_api_token_reports_bounded_timeout(monkeypatch):
    from runtime.management.commands import prove_machine_continuity as command

    monkeypatch.delenv("FLY_API_TOKEN", raising=False)
    monkeypatch.setattr(
        command.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("fly", 15)
        ),
    )

    with pytest.raises(ValueError, match="timed out"):
        command.Command._fly_api_token("fly")
