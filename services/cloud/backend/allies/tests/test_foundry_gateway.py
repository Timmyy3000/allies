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
    FoundryGatewayRejected,
    FoundryGatewayRetryable,
    FoundryGatewayUnknownOutcome,
    ProvisioningRejected,
    ProvisioningRetryable,
)
from allies.gateways.contracts import (
    ExecutionCommand,
    RoutineApprovalReceipt,
    RoutineCancelWaitReceipt,
    RoutineDispatchReceipt,
    canonical_fingerprint,
    canonical_json_bytes,
)
from allies.gateways.foundry import (
    ProfileProvisioningRequest,
    RuntimeIntentReceipt,
    accept_routine_dispatch,
    activate_workspace,
    cancel_routine_wait,
    decide_routine_approval,
    provision_profile,
    reconcile_execution_intent,
    request_runtime_intent,
)

MULTILINE_JOB = (
    "I want you to teach my German \n"
    "I am currently at the A1 level and just started at A2"
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


ROUTINE_SCOPE = {
    "kind": "workspace",
    "workspace_id": "00000000-0000-4000-8000-000000000001",
    "owner_user_id": "00000000-0000-4000-8000-000000000002",
    "ally_id": "00000000-0000-4000-8000-000000000003",
    "cloud_binding_id": "00000000-0000-4000-8000-000000000009",
}


def _routine_command(kind: str, **fields):
    value = {
        "schema_version": "v1",
        "kind": kind,
        "producer": "cloud",
        "service_identity": "cloud-service",
        "scope": ROUTINE_SCOPE,
        "issued_at": "2026-09-11T08:00:00Z",
        "deadline_at": "2026-09-11T08:01:00Z",
        "fingerprint": "",
        **fields,
    }
    value["fingerprint"] = canonical_fingerprint(value)
    return value


def routine_dispatch_command():
    return _routine_command(
        "routine.dispatch",
        command_id="00000000-0000-4000-8000-00000000001e",
        idempotency_key="00000000-0000-4000-8000-00000000001f",
        routine_id="00000000-0000-4000-8000-000000000004",
        routine_revision=3,
        schedule_generation=2,
        occurrence_id="00000000-0000-4000-8000-000000000005",
        run_id="00000000-0000-4000-8000-000000000006",
        scheduled_at="2026-09-11T08:02:00Z",
        delayed=False,
        occurrence_disposition="admitted",
        main_conversation_id="00000000-0000-4000-8000-000000000007",
        run_conversation_id="00000000-0000-4000-8000-000000000008",
        cloud_binding_id=ROUTINE_SCOPE["cloud_binding_id"],
        execution_prompt="Check the saved routine condition.",
        title_snapshot="Morning check",
    )


def routine_approval_command():
    return _routine_command(
        "routine.approval_decision",
        command_id="00000000-0000-4000-8000-000000000020",
        idempotency_key="00000000-0000-4000-8000-000000000021",
        approval_request_id="00000000-0000-4000-8000-00000000000c",
        action_attempt_id="00000000-0000-4000-8000-00000000000d",
        run_id="00000000-0000-4000-8000-000000000006",
        attempt_id="00000000-0000-4000-8000-00000000000b",
        generation=7,
        decision="approve",
        decided_at="2026-09-11T08:04:30Z",
    )


def routine_cancel_command():
    return _routine_command(
        "routine.cancel_wait",
        command_id="00000000-0000-4000-8000-000000000022",
        idempotency_key="00000000-0000-4000-8000-000000000023",
        approval_request_id="00000000-0000-4000-8000-00000000000c",
        run_id="00000000-0000-4000-8000-000000000006",
        attempt_id="00000000-0000-4000-8000-00000000000b",
        generation=7,
        reason="replacement",
        replacing_occurrence_id="00000000-0000-4000-8000-00000000001e",
    )


def routine_dispatch_receipt(command, *, outcome="accepted", **overrides):
    value = {
        "schema_version": "v1",
        "kind": "routine.dispatch_receipt",
        "producer": "foundry",
        "service_identity": "foundry-service",
        "command_id": command["command_id"],
        "idempotency_key": command["idempotency_key"],
        "outcome": outcome,
        "occurrence_id": command["occurrence_id"],
        "run_id": command["run_id"],
        "execution_id": "00000000-0000-4000-8000-00000000000a",
        "attempt_id": "00000000-0000-4000-8000-00000000000b",
        "generation": 7,
        "acceptance_is_completion": False,
        "scope": command["scope"],
        "issued_at": "2026-09-11T08:00:02Z",
        "deadline_at": "2026-09-11T08:01:02Z",
        "fingerprint": "",
        **overrides,
    }
    value["fingerprint"] = canonical_fingerprint(value)
    return value


def routine_approval_receipt(command, **overrides):
    value = {
        "schema_version": "v1",
        "kind": "routine.approval_receipt",
        "producer": "foundry",
        "service_identity": "foundry-service",
        "command_id": command["command_id"],
        "idempotency_key": command["idempotency_key"],
        "result_code": "APPROVAL_AUTHORIZED",
        "request_status": "authorizing",
        "run_status": "working",
        "permission_consumed": True,
        "action_attempt_state": "pre_dispatch",
        "scope": command["scope"],
        "issued_at": "2026-09-11T08:04:31Z",
        "deadline_at": "2026-09-11T08:05:31Z",
        "fingerprint": "",
        **overrides,
    }
    value["fingerprint"] = canonical_fingerprint(value)
    return value


def routine_cancel_receipt(**overrides):
    return {
        "code": "WAIT_CANCELLED",
        "routine_execution_id": "00000000-0000-4000-8000-00000000000a",
        "fence": 4,
        "status": "cancelled",
        "replayed": False,
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


def test_gateway_serializes_authorized_multiline_job_exactly(monkeypatch, settings):
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"
    captured = {}

    class Opener:
        def open(self, request, *, timeout):
            captured["body"] = json.loads(request.data)
            return Response(receipt())

    monkeypatch.setattr(
        "allies.gateways.foundry.build_opener", lambda *_handlers: Opener()
    )

    provision_profile(request_payload().model_copy(update={"job": MULTILINE_JOB}))

    assert captured["body"]["job"] == MULTILINE_JOB


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("job", "x\ry"),
        ("job", "x\ty"),
        ("personality", "x\x00y"),
        ("personality", "x\u2028y"),
    ],
)
def test_profile_request_rejects_unsafe_multiline_controls(field, value):
    with pytest.raises(ValueError):
        ProfileProvisioningRequest(**{**request_payload().model_dump(), field: value})


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


@pytest.mark.parametrize("outcome", ["accepted", "duplicate"])
def test_routine_dispatch_sends_persisted_canonical_body_and_validates_receipt(
    monkeypatch, settings, outcome
):
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"
    command = routine_dispatch_command()
    body = canonical_json_bytes(command)
    captured = {}

    class Opener:
        def open(self, request, *, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            captured["body"] = request.data
            captured["timeout"] = timeout
            return Response(routine_dispatch_receipt(command, outcome=outcome))

    monkeypatch.setattr(
        "allies.gateways.foundry.build_opener", lambda *_handlers: Opener()
    )

    result = accept_routine_dispatch(raw_body=body)

    assert isinstance(result, RoutineDispatchReceipt)
    assert result.outcome == outcome
    assert captured == {
        "url": "https://foundry.example.test/api/v1/internal/routines/dispatch",
        "authorization": "Bearer service-secret",
        "body": body,
        "timeout": settings.ALLIES_FOUNDRY_TIMEOUT_SECONDS,
    }


def test_routine_transport_rejects_noncanonical_persisted_body_before_network(
    monkeypatch, settings
):
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"
    monkeypatch.setattr(
        "allies.gateways.foundry._request",
        lambda **_kwargs: pytest.fail("noncanonical routine body reached the network"),
    )

    with pytest.raises(FoundryGatewayInvalid):
        accept_routine_dispatch(
            raw_body=canonical_json_bytes(routine_dispatch_command()) + b"\n"
        )


def test_routine_approval_and_cancel_wait_use_confirmed_routes(monkeypatch, settings):
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"
    approval = routine_approval_command()
    cancel = routine_cancel_command()
    captured = []

    class Opener:
        def open(self, request, *, timeout):
            captured.append(
                {
                    "url": request.full_url,
                    "authorization": request.get_header("Authorization"),
                    "body": request.data,
                    "timeout": timeout,
                }
            )
            if request.full_url.endswith("approval-decision"):
                return Response(routine_approval_receipt(approval))
            return Response(routine_cancel_receipt())

    monkeypatch.setattr(
        "allies.gateways.foundry.build_opener", lambda *_handlers: Opener()
    )

    approval_result = decide_routine_approval(raw_body=canonical_json_bytes(approval))
    cancel_result = cancel_routine_wait(raw_body=canonical_json_bytes(cancel))

    assert isinstance(approval_result, RoutineApprovalReceipt)
    assert approval_result.result_code == "APPROVAL_AUTHORIZED"
    assert isinstance(cancel_result, RoutineCancelWaitReceipt)
    assert cancel_result.code == "WAIT_CANCELLED"
    assert [entry["url"] for entry in captured] == [
        "https://foundry.example.test/api/v1/internal/routines/approval-decision",
        "https://foundry.example.test/api/v1/internal/routines/cancel-wait",
    ]
    assert [entry["authorization"] for entry in captured] == [
        "Bearer service-secret",
        "Bearer service-secret",
    ]
    assert [entry["body"] for entry in captured] == [
        canonical_json_bytes(approval),
        canonical_json_bytes(cancel),
    ]


@pytest.mark.parametrize(
    ("operation", "response"),
    [
        (
            "dispatch",
            lambda: routine_dispatch_receipt(
                routine_dispatch_command(), unexpected="field"
            ),
        ),
        (
            "approval",
            lambda: {
                **routine_approval_receipt(routine_approval_command()),
                "fingerprint": "canonical-json-sha256:v1:" + "0" * 64,
            },
        ),
        (
            "cancel",
            lambda: routine_cancel_receipt(status="succeeded"),
        ),
    ],
)
def test_routine_transport_rejects_invalid_receipts(
    monkeypatch, settings, operation, response
):
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response(response())

    monkeypatch.setattr(
        "allies.gateways.foundry.build_opener", lambda *_handlers: Opener()
    )

    with pytest.raises(FoundryGatewayInvalid):
        if operation == "dispatch":
            accept_routine_dispatch(
                raw_body=canonical_json_bytes(routine_dispatch_command())
            )
        elif operation == "approval":
            decide_routine_approval(
                raw_body=canonical_json_bytes(routine_approval_command())
            )
        else:
            cancel_routine_wait(raw_body=canonical_json_bytes(routine_cancel_command()))


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, FoundryGatewayRejected),
        (404, FoundryGatewayNotFound),
        (409, FoundryGatewayConflict),
        (422, FoundryGatewayInvalid),
        (503, FoundryGatewayRetryable),
    ],
)
def test_routine_transport_maps_http_errors(monkeypatch, settings, status, error):
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"

    class Opener:
        def open(self, *_args, **_kwargs):
            raise HTTPError(
                "https://foundry.example.test/api/v1/internal/routines/dispatch",
                status,
                "failure",
                {},
                BytesIO(),
            )

    monkeypatch.setattr(
        "allies.gateways.foundry.build_opener", lambda *_handlers: Opener()
    )

    with pytest.raises(error):
        accept_routine_dispatch(
            raw_body=canonical_json_bytes(routine_dispatch_command())
        )


@pytest.mark.parametrize(
    "network_error", [URLError("timeout"), TimeoutError("timeout")]
)
def test_routine_transport_maps_unknown_network_outcomes(
    monkeypatch, settings, network_error
):
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"

    class Opener:
        def open(self, *_args, **_kwargs):
            raise network_error

    monkeypatch.setattr(
        "allies.gateways.foundry.build_opener", lambda *_handlers: Opener()
    )

    with pytest.raises(FoundryGatewayUnknownOutcome):
        accept_routine_dispatch(
            raw_body=canonical_json_bytes(routine_dispatch_command())
        )


def test_routine_transport_enforces_bounded_command_and_response_bodies(
    monkeypatch, settings
):
    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "service-secret"
    monkeypatch.setattr(
        "allies.gateways.foundry._request",
        lambda **_kwargs: pytest.fail("oversized routine command reached the network"),
    )

    with pytest.raises(FoundryGatewayInvalid):
        accept_routine_dispatch(raw_body=b"{" + b" " * (64 * 1024))
    monkeypatch.undo()

    class OversizedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b"x" * (64 * 1024 + 1)

    class Opener:
        def open(self, *_args, **_kwargs):
            return OversizedResponse()

    monkeypatch.setattr(
        "allies.gateways.foundry.build_opener", lambda *_handlers: Opener()
    )
    with pytest.raises(FoundryGatewayInvalid):
        accept_routine_dispatch(
            raw_body=canonical_json_bytes(routine_dispatch_command())
        )


def test_stop_gateway_carries_selected_workspace_and_message(monkeypatch, settings):
    from allies.gateways.foundry import stop_conversation

    settings.ALLIES_FOUNDRY_URL = "https://foundry.example.test"
    settings.ALLIES_FOUNDRY_SERVICE_TOKEN = "test-token"
    requests = []

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            return Response({"stopped": 0})

    monkeypatch.setattr("allies.gateways.foundry.build_opener", lambda *_args: Opener())
    workspace_id = UUID("00000000-0000-4000-8000-000000000001")
    conversation_id = UUID("00000000-0000-4000-8000-000000000002")
    message_id = UUID("00000000-0000-4000-8000-000000000003")
    assert (
        stop_conversation(
            conversation_id, workspace_id=workspace_id, message_id=message_id
        )
        == 0
    )
    assert (
        requests[0].full_url
        == f"https://foundry.example.test/api/v1/internal/conversations/{conversation_id}/stop"
    )
    assert json.loads(requests[0].data) == {
        "workspace_id": str(workspace_id),
        "message_id": str(message_id),
    }


@pytest.mark.parametrize(
    "receipt", [{"stopped": True}, {"stopped": -1}, {}, {"stopped": "0"}]
)
def test_stop_gateway_rejects_invalid_confirmation(monkeypatch, receipt):
    from allies.gateways.foundry import stop_conversation

    monkeypatch.setattr(
        "allies.gateways.foundry._request",
        lambda **kwargs: json.dumps(receipt).encode(),
    )
    with pytest.raises(FoundryGatewayInvalid):
        stop_conversation(UUID(int=1), workspace_id=UUID(int=2), message_id=UUID(int=3))
