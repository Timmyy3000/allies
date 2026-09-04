from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from urllib.error import HTTPError, URLError
from uuid import UUID

import pytest

from allies.exceptions import (
    FoundryGatewayConflict,
    FoundryGatewayInvalid,
    FoundryGatewayNotFound,
    ProvisioningRejected,
    ProvisioningRetryable,
)
from allies.gateways.contracts import ExecutionCommand
from allies.gateways.foundry import (
    ProfileProvisioningRequest,
    RuntimeIntentReceipt,
    activate_workspace,
    provision_profile,
    reconcile_execution_intent,
    request_runtime_intent,
)


def request_payload() -> ProfileProvisioningRequest:
    return ProfileProvisioningRequest(
        workspace_id="00000000-0000-4000-8000-000000000001",
        binding_id="00000000-0000-4000-8000-000000000002",
        ally_ref="00000000-0000-4000-8000-000000000003",
        operation_id="00000000-0000-4000-8000-000000000004",
        request_fingerprint="a" * 64,
        name="Mira",
        job="Study partner",
        personality="Calm and specific",
    )


class Response:
    def __init__(self, body: dict):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int) -> bytes:
        return self.body


def receipt(**overrides):
    return {
        "version": 1,
        "binding_id": "00000000-0000-4000-8000-000000000002",
        "operation_id": "00000000-0000-4000-8000-000000000004",
        "request_fingerprint": "a" * 64,
        "status": "pending",
        "evidence_digest": "b" * 64,
        **overrides,
    }


def test_gateway_sends_one_bearer_authenticated_command(monkeypatch, settings):
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"
    captured = {}

    class Opener:
        def open(self, request, *, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            captured["timeout"] = timeout
            return Response(receipt())

    monkeypatch.setattr(
        "allies.gateways.foundry.build_opener", lambda *_handlers: Opener()
    )

    result = provision_profile(request_payload())

    assert result.status == "pending"
    assert captured == {
        "url": "https://foundry.example.test/api/v1/internal/profile-provisioning",
        "authorization": "Bearer service-secret",
        "timeout": settings.ALLIES_FOUNDRY_TIMEOUT_SECONDS,
    }


def test_gateway_starts_workspace_activation(monkeypatch, settings):
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"
    captured = {}

    class Opener:
        def open(self, request, *, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            captured["body"] = json.loads(request.data)
            return Response(
                {
                    "version": 1,
                    "workspace_id": request_payload().workspace_id,
                    "status": "active",
                }
            )

    monkeypatch.setattr(
        "allies.gateways.foundry.build_opener", lambda *_handlers: Opener()
    )

    result = activate_workspace(request_payload().workspace_id)

    assert result.status == "active"
    assert captured == {
        "url": "https://foundry.example.test/api/v1/internal/workspaces/00000000-0000-4000-8000-000000000001/activation",
        "authorization": "Bearer service-secret",
        "body": {"version": 1, "workspace_id": request_payload().workspace_id},
    }


def test_gateway_forwards_content_free_runtime_intent_with_same_key(
    monkeypatch, settings
):
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"
    captured = {}
    workspace_id = UUID("00000000-0000-4000-8000-000000000001")
    key = UUID("00000000-0000-4000-8000-000000000002")

    class Opener:
        def open(self, request, *, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            captured["idempotency_key"] = request.get_header("Idempotency-key")
            captured["body"] = json.loads(request.data)
            captured["timeout"] = timeout
            return Response({"status": "waking"})

    monkeypatch.setattr(
        "allies.gateways.foundry.build_opener", lambda *_handlers: Opener()
    )

    result = request_runtime_intent(
        workspace_id=workspace_id,
        intent="composing_started",
        received_at=datetime(2026, 9, 4, 12, tzinfo=UTC),
        idempotency_key=key,
    )

    assert isinstance(result, RuntimeIntentReceipt)
    assert result.status == "waking"
    assert captured["url"] == (
        "https://foundry.example.test/api/v1/control/workspaces/"
        "00000000-0000-4000-8000-000000000001/runtime-intents"
    )
    assert captured["authorization"] == "Bearer service-secret"
    assert captured["idempotency_key"] == str(key)
    assert captured["body"] == {
        "intent": "composing_started",
        "received_at": "2026-09-04T12:00:00Z",
    }
    assert captured["timeout"] == settings.ALLIES_FOUNDRY_TIMEOUT_SECONDS


def test_gateway_does_not_allow_authorization_override(monkeypatch, settings):
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"

    monkeypatch.setattr(
        "allies.gateways.foundry._foundry_origin",
        lambda: ("https://foundry.example.test", "service-secret"),
    )

    with pytest.raises(FoundryGatewayInvalid):
        from allies.gateways.foundry import _request

        _request(
            method="POST",
            path="api/v1/control/workspaces/test",
            extra_headers={"Authorization": "attacker-token"},
        )


@pytest.mark.parametrize(
    "gateway_error", [FoundryGatewayNotFound, FoundryGatewayConflict]
)
def test_activation_maps_rollout_skew_and_conflict_to_retryable(
    monkeypatch, settings, gateway_error
):
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"
    monkeypatch.setattr(
        "allies.gateways.foundry._foundry_origin",
        lambda: (_ for _ in ()).throw(gateway_error("failure")),
    )

    with pytest.raises(ProvisioningRetryable):
        activate_workspace(request_payload().workspace_id)


def test_gateway_allows_debug_docker_host_origin(monkeypatch, settings):
    settings.DEBUG = True
    settings.ALLIES_FOUNDRY_URL = "http://host.docker.internal:8100"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"
    captured = {}

    class Opener:
        def open(self, request, *, timeout):
            captured["url"] = request.full_url
            return Response(receipt())

    monkeypatch.setattr(
        "allies.gateways.foundry.build_opener", lambda *_handlers: Opener()
    )

    provision_profile(request_payload())

    assert captured["url"] == (
        "http://host.docker.internal:8100/api/v1/internal/profile-provisioning"
    )


def test_gateway_rejects_plain_http_outside_debug(settings):
    settings.DEBUG = False
    settings.ALLIES_FOUNDRY_URL = "http://host.docker.internal:8100"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"

    with pytest.raises(ProvisioningRetryable):
        provision_profile(request_payload())


@pytest.mark.parametrize(
    "error",
    [
        URLError("timeout"),
        HTTPError("https://foundry.example.test", 503, "", {}, BytesIO()),
        HTTPError("https://foundry.example.test", 429, "", {}, BytesIO()),
    ],
)
def test_gateway_maps_unknown_outcomes_to_retryable(monkeypatch, settings, error):
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"

    class Opener:
        def open(self, *_args, **_kwargs):
            raise error

    monkeypatch.setattr(
        "allies.gateways.foundry.build_opener", lambda *_handlers: Opener()
    )

    with pytest.raises(ProvisioningRetryable):
        provision_profile(request_payload())


@pytest.mark.parametrize(
    "body",
    [
        {"message": "not a receipt"},
        receipt(version=2),
    ],
)
def test_gateway_rejects_malformed_or_incompatible_receipts(
    monkeypatch, settings, body
):
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response(body)

    monkeypatch.setattr(
        "allies.gateways.foundry.build_opener", lambda *_handlers: Opener()
    )

    with pytest.raises(ProvisioningRejected):
        provision_profile(request_payload())


@pytest.mark.parametrize(
    ("key", "fingerprint"),
    [
        ("0" * 36, "canonical-json-sha256:v1:" + "a" * 64),
        (
            "00000000-0000-4000-8000-000000000001",
            "canonical-json-sha256:v1:" + "a" * 63,
        ),
    ],
)
def test_reconcile_validates_uuid_and_complete_fingerprint_before_network(
    monkeypatch, settings, key, fingerprint
):
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"
    monkeypatch.setattr(
        "allies.gateways.foundry._request",
        lambda **_kwargs: pytest.fail("invalid reconcile input reached the network"),
    )

    with pytest.raises(FoundryGatewayInvalid):
        reconcile_execution_intent(key, fingerprint)


def test_execution_command_fixture_round_trips_through_gateway_dto():
    command = ExecutionCommand.model_validate(
        {
            "schema_version": "v1",
            "kind": "execution.command",
            "producer": "cloud",
            "service_identity": "cloud-service",
            "command_id": "550e8400-e29b-41d4-a716-446655440000",
            "idempotency_key": "650e8400-e29b-41d4-a716-446655440000",
            "scope": {
                "kind": "workspace",
                "cloud_workspace_id": "750e8400-e29b-41d4-a716-446655440000",
            },
            "conversation_turn_ordinal": 12,
            "cloud": {
                "ally_id": "850e8400-e29b-41d4-a716-446655440000",
                "conversation_id": "950e8400-e29b-41d4-a716-446655440000",
                "message_id": "a50e8400-e29b-41d4-a716-446655440000",
                "cloud_binding_id": "c50e8400-e29b-41d4-a716-446655440000",
            },
            "source_kind": "conversation_message",
            "payload": {"kind": "execution_input", "text": "normalized user text"},
            "issued_at": "2026-08-25T12:00:00Z",
            "deadline_at": "2026-08-25T12:00:05Z",
            "fingerprint": "canonical-json-sha256:v1:b4e253ef34e4710692d1eaba026071ccbe9468d7be6baf8115242624d676b663",
        }
    )
    assert command.fingerprint.endswith(
        "b4e253ef34e4710692d1eaba026071ccbe9468d7be6baf8115242624d676b663"
    )
