import json
from datetime import timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from django.test import override_settings
from django.utils import timezone

from runtime.exceptions import RuntimeAuthorizationError
from runtime.models import Attempt, Lease
from runtime.services.routine_tools import call_routine_tool, routine_tool_token
from runtime.tests.test_fnd007_execution import claimed_execution  # noqa: F401


@pytest.fixture
def tool_claim(claimed_execution):  # noqa: F811
    _, execution, claim = claimed_execution
    execution.cloud_message_id = uuid4()
    execution.cloud_binding_id = uuid4()
    execution.command_fingerprint = "canonical-json-sha256:v1:" + "a" * 64
    execution.save()
    return execution, claim


@override_settings(
    ALLIES_CLOUD_URL="https://cloud.example.test",
    ALLIES_CLOUD_EVENT_SERVICE_TOKEN="service-secret",
)
def test_proxy_derives_message_identity_and_hides_service_secret(
    tool_claim, monkeypatch
):
    execution, claim = tool_claim
    captured = []

    class Response(BytesIO):
        status = 200

    class Opener:
        def open(self, request, timeout):
            captured.append(request)
            return Response(b'{"status":"saved","routine_id":"example"}')

    monkeypatch.setattr(
        "runtime.services.routine_tools.build_opener", lambda *a: Opener()
    )
    result = call_routine_tool(
        routine_tool_token(claim), call_id=uuid4(), arguments={"action": "list"}
    )
    assert result[0] == 200
    body = json.loads(captured[0].data)
    assert body["message_id"] == str(execution.cloud_message_id)
    assert body["binding_id"] == str(execution.cloud_binding_id)
    assert body["command_fingerprint"] == execution.command_fingerprint
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("fence", ["expired", "generation", "terminal", "tampered"])
def test_capability_rejects_stale_attempt_before_network(
    tool_claim, monkeypatch, fence
):
    execution, claim = tool_claim
    token = routine_tool_token(claim)
    if fence == "expired":
        Lease.objects.filter(pk=claim.lease_id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
    elif fence == "generation":
        execution.workspace.machine_generation += 1
        execution.workspace.save()
    elif fence == "terminal":
        Attempt.objects.filter(pk=claim.attempt_id).update(status="succeeded")
    else:
        token += "x"

    def unexpected(*args):
        pytest.fail("unauthorized request reached network")

    monkeypatch.setattr("runtime.services.routine_tools.build_opener", unexpected)
    with pytest.raises(RuntimeAuthorizationError):
        call_routine_tool(token, call_id=uuid4(), arguments={"action": "list"})
