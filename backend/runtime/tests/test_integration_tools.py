import json
from io import BytesIO
from urllib.error import URLError
from uuid import uuid4

import pytest
from django.test import Client, override_settings

from runtime.exceptions import RuntimeAuthorizationError
from runtime.models import Attempt
from runtime.services.routine_tools import call_integration_tool, routine_tool_token
from runtime.tests.test_fnd007_execution import claimed_execution  # noqa: F401
from runtime.tests.test_routine_tools import tool_claim  # noqa: F401

CLOUD = {
    "ALLIES_CLOUD_URL": "https://cloud.example.test",
    "ALLIES_CLOUD_EVENT_SERVICE_TOKEN": "service-secret",
}


def _opener(monkeypatch, status, body, captured):
    class Response(BytesIO):
        pass

    class Opener:
        def open(self, request, timeout):
            captured.append(request)
            response = Response(body)
            response.status = status
            return response

    monkeypatch.setattr(
        "runtime.services.routine_tools.build_opener", lambda *a: Opener()
    )


@override_settings(**CLOUD)
def test_relays_opaque_integration_with_dispatch_identity(
    tool_claim,  # noqa: F811
    monkeypatch,
):
    execution, claim = tool_claim
    captured = []
    _opener(monkeypatch, 200, b'{"messages":[]}', captured)
    status, result = call_integration_tool(
        routine_tool_token(claim),
        call_id=uuid4(),
        integration="gmail",
        arguments={"action": "search", "query": "from:a"},
    )
    assert (status, result) == (200, {"messages": []})
    request = captured[0]
    assert request.full_url == (
        "https://cloud.example.test/api/v1/internal/foundry/integrations/tool"
    )
    body = json.loads(request.data)
    assert body["message_id"] == str(execution.cloud_message_id)
    assert body["binding_id"] == str(execution.cloud_binding_id)
    assert body["command_fingerprint"] == execution.command_fingerprint
    assert body["integration"] == "gmail"
    assert body["arguments"] == {"action": "search", "query": "from:a"}


@override_settings(**CLOUD)
@pytest.mark.parametrize("status", [403, 422])
def test_passes_cloud_denials_through(tool_claim, monkeypatch, status):  # noqa: F811
    _, claim = tool_claim
    _opener(monkeypatch, status, b'{"error":"integration_unavailable"}', [])
    assert call_integration_tool(
        routine_tool_token(claim), call_id=uuid4(), integration="gmail", arguments={}
    ) == (status, {"error": "integration_unavailable"})


@override_settings(**CLOUD)
def test_unexpected_cloud_status_is_unavailable(tool_claim, monkeypatch):  # noqa: F811
    _, claim = tool_claim
    _opener(monkeypatch, 500, b'{"secret":"leak"}', [])
    assert call_integration_tool(
        routine_tool_token(claim), call_id=uuid4(), integration="gmail", arguments={}
    ) == (503, {"error": "integration_service_unavailable"})


@override_settings(**CLOUD)
def test_network_failure_is_unconfirmed(tool_claim, monkeypatch):  # noqa: F811
    _, claim = tool_claim

    class Opener:
        def open(self, request, timeout):
            raise URLError("down")

    monkeypatch.setattr(
        "runtime.services.routine_tools.build_opener", lambda *a: Opener()
    )
    status, result = call_integration_tool(
        routine_tool_token(claim), call_id=uuid4(), integration="gmail", arguments={}
    )
    assert status == 503
    assert result["error"] == "integration_service_unavailable"
    assert "unconfirmed" in result["instruction"]


def test_inactive_attempt_never_reaches_cloud(tool_claim, monkeypatch):  # noqa: F811
    _, claim = tool_claim
    Attempt.objects.filter(pk=claim.attempt_id).update(status="succeeded")
    monkeypatch.setattr(
        "runtime.services.routine_tools.build_opener",
        lambda *a: pytest.fail("unauthorized request reached network"),
    )
    with pytest.raises(RuntimeAuthorizationError):
        call_integration_tool(
            routine_tool_token(claim),
            call_id=uuid4(),
            integration="gmail",
            arguments={},
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        {"call_id": "not-a-uuid", "integration": "gmail", "arguments": {}},
        {"call_id": 123, "integration": "gmail", "arguments": {}},
        {"call_id": str(uuid4()), "integration": "Gmail!", "arguments": {}},
        {"call_id": str(uuid4()), "integration": "gmail", "arguments": []},
        {"call_id": str(uuid4()), "arguments": {}},
        {"call_id": str(uuid4()), "integration": "gmail", "arguments": {}, "x": 1},
    ],
)
def test_endpoint_rejects_malformed_requests(body):
    response = Client().post(
        "/api/v1/runtime/integrations/tool",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer token",
    )
    assert response.status_code == 422


@pytest.mark.django_db
def test_endpoint_rejects_bad_capability():
    response = Client().post(
        "/api/v1/runtime/integrations/tool",
        data=json.dumps(
            {"call_id": str(uuid4()), "integration": "gmail", "arguments": {}}
        ),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer forged",
    )
    assert response.status_code in {401, 403}


@pytest.mark.django_db
def test_routine_endpoint_rejects_non_string_call_id():
    response = Client().post(
        "/api/v1/runtime/routines/tool",
        data=json.dumps({"call_id": 123, "arguments": {}}),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer token",
    )
    assert response.status_code == 422
