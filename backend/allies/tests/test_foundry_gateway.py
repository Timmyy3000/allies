from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from allies.exceptions import ProvisioningRejected, ProvisioningRetryable
from allies.gateways.foundry import ProfileProvisioningRequest, provision_profile


def request_payload() -> ProfileProvisioningRequest:
    return ProfileProvisioningRequest(
        workspace_id="00000000-0000-4000-8000-000000000001",
        binding_id="00000000-0000-4000-8000-000000000002",
        ally_ref="00000000-0000-4000-8000-000000000003",
        operation_id="00000000-0000-4000-8000-000000000004",
        request_fingerprint="a" * 64,
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
