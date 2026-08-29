from __future__ import annotations

import json
from datetime import timedelta
from io import StringIO
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from runtime.contracts import (
    ExecutionCommand,
    FoundryEventEnvelope,
    build_event_envelope,
    command_fingerprint,
    event_fingerprint,
)
from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeNotFoundError,
    RuntimeValidationError,
)
from runtime.models import (
    ConversationBinding,
    Execution,
    ExecutionEvent,
    ExecutionEventDelivery,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.services import event_delivery
from runtime.services.claims import claim_next_execution
from runtime.services.event_delivery import (
    claim_event_deliveries,
    mark_event_delivery,
    publish_pending_event_deliveries,
)
from runtime.services.events import append_runtime_event
from runtime.services.executions import create_execution_intent
from runtime.services.runtime_auth import (
    authenticate_runtime_token,
    issue_runtime_credential,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "contracts"
    / "foundry-execution-v1.json"
)
PROFILE_NAMESPACE = uuid5(NAMESPACE_URL, "allies-foundry-profile-v1")


@pytest.fixture
def contract():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def configured(settings):
    settings.ALLIES_CLOUD_SERVICE_TOKEN = "test-cloud-service-token"
    return settings.ALLIES_CLOUD_SERVICE_TOKEN


@pytest.fixture
def binding(db, contract):
    command = contract["command"]
    workspace = Workspace.objects.create(
        tenant_ref=command["scope"]["cloud_workspace_id"],
        fly_app_ref="app",
        volume_ref="volume",
        machine_ref="machine",
        machine_generation=1,
        provisioning_phase=WorkspaceProvisioningPhase.IDLE,
    )
    binding_id = UUID(command["cloud"]["cloud_binding_id"])
    profile = RuntimeProfile.objects.create(
        id=uuid5(PROFILE_NAMESPACE, str(binding_id)),
        workspace=workspace,
        ally_ref=command["cloud"]["ally_id"],
        hermes_profile_key="contract_ally",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=workspace.machine_generation,
    )
    ConversationBinding.objects.create(
        profile=profile,
        cloud_conversation_ref=command["cloud"]["conversation_id"],
        hermes_session_id="session-1",
    )
    return workspace, profile


@pytest.fixture
def delivery(binding, contract):
    workspace, _profile = binding
    create_execution_intent(ExecutionCommand.model_validate(contract["command"]))
    issued = issue_runtime_credential(workspace.id, "runtime-contract-token")
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 1)
    assert claim is not None
    event = append_runtime_event(
        context,
        claim.attempt_id,
        claim.lease_token,
        uuid4(),
        claim.stream_id,
        1,
        "execution.dispatched",
        {"status": "dispatched"},
    )
    return ExecutionEventDelivery.objects.get(event=event)


def test_fixture_is_strict_and_fingerprints_are_reproducible(contract):
    command = ExecutionCommand.model_validate(contract["command"])
    event = FoundryEventEnvelope.model_validate(contract["event"])

    assert command_fingerprint(command) == command.fingerprint
    assert event_fingerprint(event) == event.fingerprint
    assert command.payload.text == "normalized user text"


def test_cloud_projection_budget_allows_only_terminal_sequence_513(delivery):
    event = delivery.event
    event.sequence = 513
    event.event_type = "message.delta"
    event.payload = {"text": "beyond the non-terminal budget"}
    with pytest.raises(RuntimeValidationError, match="projection budget"):
        build_event_envelope(event.attempt.execution, event.attempt, event)

    event.event_type = "execution.completed"
    event.payload = {"run_id": "run-1", "status": "completed"}
    envelope = build_event_envelope(event.attempt.execution, event.attempt, event)
    assert envelope is not None
    assert envelope.foundry.attempt_sequence == 513

    event.sequence = 514
    with pytest.raises(RuntimeValidationError, match="projection budget"):
        build_event_envelope(event.attempt.execution, event.attempt, event)


def test_command_exact_replay_and_conflict_do_not_duplicate(binding, contract):
    command = ExecutionCommand.model_validate(contract["command"])

    first = create_execution_intent(command)
    replay = create_execution_intent(command)

    assert first.status == "accepted"
    assert replay.status == "duplicate"
    assert replay.model_copy(update={"status": first.status}) == first
    assert Execution.objects.count() == 1

    changed = ExecutionCommand.model_validate(
        command.model_dump(mode="json")
        | {
            "command_id": str(uuid4()),
            "payload": {"kind": "execution_input", "text": "different"},
        }
    )
    changed = changed.model_copy(update={"fingerprint": command_fingerprint(changed)})
    with pytest.raises(RuntimeConflictError) as error:
        create_execution_intent(changed)
    assert "different execution" in str(error.value)
    assert Execution.objects.count() == 1


def test_first_execution_can_create_the_runtime_session(binding, contract):
    _workspace, profile = binding
    ConversationBinding.objects.filter(profile=profile).delete()

    receipt = create_execution_intent(
        ExecutionCommand.model_validate(contract["command"])
    )

    assert receipt.status == "accepted"
    execution = Execution.objects.get()
    assert execution.profile == profile
    assert execution.input_payload["cloud_conversation_ref"] == str(
        contract["command"]["cloud"]["conversation_id"]
    )
    reserved = ConversationBinding.objects.get(profile=profile)
    assert reserved.cloud_conversation_ref == str(
        contract["command"]["cloud"]["conversation_id"]
    )
    assert reserved.hermes_session_id is None


def test_existing_profile_conversation_must_match_cloud_command(binding, contract):
    _workspace, profile = binding
    ConversationBinding.objects.filter(profile=profile).update(
        cloud_conversation_ref="another-conversation"
    )

    with pytest.raises(RuntimeNotFoundError, match="binding is unavailable"):
        create_execution_intent(ExecutionCommand.model_validate(contract["command"]))

    assert not Execution.objects.exists()


def test_command_api_is_authenticated_and_reconciles(binding, contract, configured):
    client = Client()
    payload = json.dumps(contract["command"])
    headers = {"Authorization": f"Bearer {configured}"}

    response = client.post(
        "/api/v1/internal/executions",
        data=payload,
        content_type="application/json",
        headers=headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "accepted"
    assert "execution_id" not in response.json()
    assert "profile_id" not in response.json()

    replay = client.post(
        "/api/v1/internal/executions",
        data=payload,
        content_type="application/json",
        headers=headers,
    )
    assert replay.status_code == 200
    assert replay.json()["status"] == "duplicate"

    query = {
        "idempotency_key": contract["command"]["idempotency_key"],
        "fingerprint": contract["command"]["fingerprint"],
    }
    reconciled = client.get(
        "/api/v1/internal/executions/reconcile",
        query,
        headers=headers,
    )
    assert reconciled.status_code == 200
    assert reconciled.json()["status"] == "accepted"
    assert "execution_id" not in reconciled.json()

    missing = client.get(
        "/api/v1/internal/executions/reconcile",
        {
            "idempotency_key": str(uuid4()),
            "fingerprint": contract["command"]["fingerprint"],
        },
        headers=headers,
    )
    assert missing.status_code == 200
    assert missing.json()["status"] == "not_found"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.update({"schema_version": "v2"}),
        lambda payload: payload.update({"unknown": True}),
        lambda payload: payload.update(
            {"fingerprint": "canonical-json-sha256:v1:" + "0" * 64}
        ),
    ],
)
def test_command_api_rejects_unknown_or_conflicting_shapes(
    binding, contract, configured, mutator
):
    payload = dict(contract["command"])
    mutator(payload)
    response = Client().post(
        "/api/v1/internal/executions",
        data=json.dumps(payload),
        content_type="application/json",
        headers={"Authorization": f"Bearer {configured}"},
    )
    assert response.status_code == 422
    assert Execution.objects.count() == 0


def test_dispatched_runtime_event_is_published_as_accepted(binding, contract):
    workspace, profile = binding
    execution = create_execution_intent(
        ExecutionCommand.model_validate(contract["command"])
    )
    record = Execution.objects.get(command_id=execution.command_id)
    issued = issue_runtime_credential(workspace.id, "runtime-contract-token")
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 1)
    assert claim is not None

    event = append_runtime_event(
        context,
        claim.attempt_id,
        claim.lease_token,
        uuid4(),
        claim.stream_id,
        1,
        "execution.dispatched",
        {"status": "dispatched"},
    )
    delivery = ExecutionEventDelivery.objects.get(event=event)
    wire = json.loads(bytes(delivery.envelope_bytes))

    assert record.profile_id == profile.id
    assert event.event_type == "execution.dispatched"
    assert wire["event_type"] == "execution.accepted"
    assert wire["payload"] == {"status": "accepted"}
    assert (
        wire["conversation_turn_ordinal"]
        == contract["command"]["conversation_turn_ordinal"]
    )
    assert wire["foundry"]["execution_id"] not in {
        str(record.profile_id),
        contract["command"]["command_id"],
    }
    assert ExecutionEvent.objects.filter(attempt=claim.attempt_id).count() == 1


def test_invalid_service_bearer_is_privacy_safe(binding, contract, configured):
    response = Client().post(
        "/api/v1/internal/executions",
        data=json.dumps(contract["command"]),
        content_type="application/json",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401
    assert configured not in response.content.decode()


def test_command_auth_precedes_request_validation(configured):
    responses = [
        Client().post(
            "/api/v1/internal/executions",
            data="{malformed",
            content_type="application/json",
            headers=headers,
        )
        for headers in ({}, {"Authorization": "Bearer wrong-token"})
    ]

    assert [response.status_code for response in responses] == [401, 401]
    assert responses[0].content == responses[1].content
    assert configured not in responses[0].content.decode()


class _DeliveryResponse:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit: int = -1):
        return self._body if limit < 0 else self._body[:limit]


class _DeliveryOpener:
    def __init__(self, response):
        self.response = response
        self.request = None

    def open(self, request, *, timeout):
        self.request = request
        return self.response


def _configure_delivery(settings):
    settings.ALLIES_CLOUD_EVENT_DELIVERY_ENABLED = True
    settings.ALLIES_CLOUD_URL = "https://cloud.example.test"
    settings.ALLIES_CLOUD_EVENT_SERVICE_TOKEN = "s" * 32


def test_disabled_delivery_does_not_consume_attempts(delivery, settings, monkeypatch):
    settings.ALLIES_CLOUD_EVENT_DELIVERY_ENABLED = False
    calls = []
    monkeypatch.setattr(
        event_delivery,
        "_post_to_cloud",
        lambda _body: calls.append(True) or (503, "delivery_disabled"),
    )

    for _ in range(event_delivery.MAX_DELIVERY_ATTEMPTS + 1):
        assert publish_pending_event_deliveries() == event_delivery.DeliveryReport()

    delivery.refresh_from_db()
    assert delivery.state == "pending"
    assert delivery.delivery_attempts == 0
    assert delivery.envelope_bytes
    assert calls == []


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b'{"event_id":"00000000-0000-4000-8000-000000000000","status":"applied","extra":true}',
        b'{"event_id":"00000000-0000-4000-8000-000000000000","status":"held"}',
        b"not-json",
    ],
)
def test_event_delivery_requires_bounded_strict_cloud_receipt(
    delivery, settings, monkeypatch, body
):
    _configure_delivery(settings)
    opener = _DeliveryOpener(_DeliveryResponse(202, body))
    monkeypatch.setattr(event_delivery, "build_opener", lambda *_: opener)

    status, code = event_delivery._post_to_cloud(bytes(delivery.envelope_bytes))

    assert (status, code) == (503, "delivery_receipt_invalid")


def test_event_delivery_rejects_mismatched_cloud_receipt(
    delivery, settings, monkeypatch
):
    _configure_delivery(settings)
    body = b'{"event_id":"00000000-0000-4000-8000-000000000000","status":"applied"}'
    opener = _DeliveryOpener(_DeliveryResponse(202, body))
    monkeypatch.setattr(event_delivery, "build_opener", lambda *_: opener)

    status, code = event_delivery._post_to_cloud(bytes(delivery.envelope_bytes))

    assert (status, code) == (503, "delivery_receipt_mismatch")


def test_event_delivery_rejects_oversized_cloud_receipt(
    delivery, settings, monkeypatch
):
    _configure_delivery(settings)
    opener = _DeliveryOpener(
        _DeliveryResponse(202, b"x" * (event_delivery.MAX_RESPONSE_BYTES + 1))
    )
    monkeypatch.setattr(event_delivery, "build_opener", lambda *_: opener)

    status, code = event_delivery._post_to_cloud(bytes(delivery.envelope_bytes))

    assert (status, code) == (503, "delivery_response_too_large")


@pytest.mark.parametrize(
    "base_url",
    [
        "http://cloud.example.test",
        "https://user:password@cloud.example.test",
        "https://cloud.example.test/events?token=secret",
    ],
)
def test_event_delivery_requires_credential_free_https_base_url(
    delivery, settings, monkeypatch, base_url
):
    _configure_delivery(settings)
    settings.ALLIES_CLOUD_URL = base_url
    called = []
    monkeypatch.setattr(
        event_delivery,
        "build_opener",
        lambda *_: called.append(True),
    )

    status, code = event_delivery._post_to_cloud(bytes(delivery.envelope_bytes))

    assert (status, code) == (503, "delivery_not_configured")
    assert called == []


def test_event_delivery_disables_redirects_before_sending_bearer(
    delivery, settings, monkeypatch
):
    _configure_delivery(settings)
    opener = _DeliveryOpener(_DeliveryResponse(302, b""))
    handlers = []
    monkeypatch.setattr(
        event_delivery,
        "build_opener",
        lambda handler: handlers.append(handler) or opener,
    )

    status, _code = event_delivery._post_to_cloud(bytes(delivery.envelope_bytes))

    assert status == 302
    assert len(handlers) == 1
    assert handlers[0] is event_delivery._NoRedirect
    assert (
        event_delivery._NoRedirect().redirect_request(
            None, None, 302, "", {}, "https://evil.test"
        )
        is None
    )


def test_event_delivery_fences_a_late_lease_result(delivery):
    first_now = timezone.now()
    first = claim_event_deliveries(now=first_now)[0]
    delivery.lease_expires_at = first_now - timedelta(seconds=1)
    delivery.next_attempt_at = first_now
    delivery.save(update_fields=["lease_expires_at", "next_attempt_at", "updated_at"])
    second = claim_event_deliveries(now=first_now + timedelta(seconds=1))[0]

    assert (
        mark_event_delivery(
            delivery.id,
            attempt=first.attempt,
            success=True,
            now=first_now + timedelta(seconds=1),
        )
        is None
    )
    delivery.refresh_from_db()
    assert delivery.state == "delivering"
    assert delivery.delivery_attempts == second.attempt

    marked = mark_event_delivery(
        delivery.id,
        attempt=second.attempt,
        success=True,
        now=first_now + timedelta(seconds=1),
    )
    assert marked is not None
    assert marked.state == "delivered"
    assert marked.envelope_bytes == b""
    assert marked.byte_length == 0


@pytest.mark.parametrize("cloud_status", ["sequence_gap", "conflict"])
def test_event_delivery_maps_cloud_409_statuses(
    delivery, settings, monkeypatch, cloud_status
):
    settings.ALLIES_CLOUD_EVENT_DELIVERY_ENABLED = True
    monkeypatch.setattr(
        event_delivery,
        "_post_to_cloud",
        lambda _body: (409, cloud_status),
    )

    report = publish_pending_event_deliveries()

    delivery.refresh_from_db()
    assert report.claimed == 1
    if cloud_status == "sequence_gap":
        assert report.deferred == 1
        assert delivery.state == "pending"
    else:
        assert report.exhausted == 1
        assert delivery.state == "exhausted"
        assert delivery.envelope_bytes == b""
        assert delivery.byte_length == 0


def test_event_delivery_backoff_has_bounded_jitter(monkeypatch):
    monkeypatch.setattr(event_delivery.random, "random", lambda: 0.0)
    assert event_delivery._backoff_seconds(1) == 1
    monkeypatch.setattr(event_delivery.random, "random", lambda: 0.999999)
    assert 1 < event_delivery._backoff_seconds(1) < 1.25
    assert event_delivery._backoff_seconds(20) < 375


def test_event_delivery_management_command_uses_bounded_watch(monkeypatch):
    calls = []
    sleeps = []
    monkeypatch.setattr(
        "runtime.management.commands.publish_event_deliveries.publish_pending_event_deliveries",
        lambda: calls.append("run") or event_delivery.DeliveryReport(delivered=1),
    )
    monkeypatch.setattr(
        "runtime.management.commands.publish_event_deliveries.sleep", sleeps.append
    )

    output = StringIO()
    call_command(
        "publish_event_deliveries",
        "--watch",
        "--interval",
        "7",
        "--max-runs",
        "3",
        stdout=output,
    )

    assert calls == ["run", "run", "run"]
    assert sleeps == [7, 7]
    assert output.getvalue().count("Delivered 1 event(s)") == 3
