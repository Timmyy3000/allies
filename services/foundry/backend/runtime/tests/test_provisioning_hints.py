from __future__ import annotations

import json
from datetime import timedelta
from urllib.error import URLError
from uuid import UUID, uuid4

import pytest
from django.test import TestCase
from django.utils import timezone

import runtime.services.profiles as profile_service
import runtime.services.provisioning_hints as hint_service
from runtime.exceptions import RuntimeValidationError
from runtime.models import (
    ProvisioningHintDelivery,
    ProvisioningHintDeliveryState,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.services.profiles import (
    ProfileSeed,
    accept_materialization_receipt,
    ensure_runtime_profile,
)
from runtime.services.provisioning_hints import (
    ProvisioningHintClaim,
    claim_provisioning_hint_deliveries,
    mark_provisioning_hint_delivery,
    publish_due_profile_readiness_hints,
)
from runtime.services.runtime_auth import (
    authenticate_runtime_token,
    issue_runtime_credential,
)


@pytest.mark.django_db
@pytest.mark.parametrize("limit", [0, 2, 20, True])
def test_hint_batch_rejects_unsafe_limits(limit):
    with pytest.raises(RuntimeValidationError, match="must be 1"):
        claim_provisioning_hint_deliveries(limit=limit)


@pytest.fixture
def materialization_context(db):
    workspace = Workspace.objects.create(
        tenant_ref=str(uuid4()),
        fly_app_ref="app",
        volume_ref="volume",
        machine_ref="machine-1",
        machine_generation=1,
        provisioning_phase=WorkspaceProvisioningPhase.IDLE,
        ready_generation=1,
        ready_start_epoch=0,
        ready_boot_id=uuid4(),
        runtime_last_seen_at=timezone.now(),
    )
    profile_id = uuid4()
    seed = ProfileSeed(
        personality="Personality",
        provider="openai",
        model="gpt-test",
        first_chat_instruction="Ask one useful question.",
        credential_refs={"provider_api": "vault://providers/ally-a"},
    )
    created = ensure_runtime_profile(workspace.id, profile_id, "ally-a", seed)
    issued = issue_runtime_credential(workspace.id, "runtime-secret")
    context = authenticate_runtime_token(issued.raw_token)
    return workspace, profile_id, created, context


def _accept_receipt(materialization_context, *, operation_id: UUID | None = None):
    workspace, profile_id, created, context = materialization_context
    return accept_materialization_receipt(
        context,
        profile_id,
        operation_id or uuid4(),
        created.lifecycle_epoch,
        workspace.machine_generation,
        created.seed_fingerprint,
        "created",
    )


def _claim() -> ProvisioningHintClaim:
    return ProvisioningHintClaim(
        delivery_id=uuid4(),
        hint_id=uuid4(),
        workspace_id=str(uuid4()),
        ally_ref="ally-a",
        runtime_profile_id=uuid4(),
        generation=1,
        receipt_id=uuid4(),
        occurred_at=timezone.now(),
        attempt=1,
    )


class _Response:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit: int = -1):
        return self._body if limit < 0 else self._body[:limit]


class _LostResponse(_Response):
    def read(self, limit: int = -1):
        raise URLError("202 response lost after remote acceptance")


class _Opener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _configure_hints(settings):
    settings.ALLIES_RUNTIME_READINESS_HINT_ENABLED = True
    settings.ALLIES_CLOUD_URL = "https://cloud.example.test"
    settings.ALLIES_CLOUD_EVENT_SERVICE_TOKEN = "s" * 32


def test_materialization_hint_is_atomic_and_never_posts_under_transaction(
    materialization_context, monkeypatch
):
    workspace, profile_id, _created, _context = materialization_context
    real_ensure = profile_service.ensure_provisioning_hint_delivery

    def ensure_then_fail(*args, **kwargs):
        real_ensure(*args, **kwargs)
        raise RuntimeError("rollback after hint insert")

    posted = []
    monkeypatch.setattr(
        profile_service,
        "ensure_provisioning_hint_delivery",
        ensure_then_fail,
    )
    monkeypatch.setattr(
        hint_service,
        "_post_hint_to_cloud",
        lambda claim: (
            posted.append(claim) or pytest.fail("network under receipt transaction")
        ),
    )

    with pytest.raises(RuntimeError, match="rollback"):
        _accept_receipt(materialization_context)

    profile = RuntimeProfile.objects.get(pk=profile_id)
    assert profile.materialization_operation_id is None
    assert not ProvisioningHintDelivery.objects.filter(
        runtime_profile_id=profile_id
    ).exists()

    monkeypatch.setattr(
        profile_service, "ensure_provisioning_hint_delivery", real_ensure
    )
    receipt = _accept_receipt(materialization_context)
    profile.refresh_from_db()
    delivery = ProvisioningHintDelivery.objects.get(runtime_profile_id=profile_id)
    assert receipt.receipt_id == delivery.receipt_id
    assert delivery.state == ProvisioningHintDeliveryState.PENDING
    assert posted == []
    assert profile.lifecycle_state == RuntimeProfileLifecycleState.ACTIVE
    assert delivery.workspace_id == workspace.id


def test_duplicate_materialization_receipt_deduplicates_one_hint(
    materialization_context,
):
    operation_id = uuid4()
    first = _accept_receipt(materialization_context, operation_id=operation_id)
    replay = _accept_receipt(materialization_context, operation_id=operation_id)

    assert replay == first
    assert (
        ProvisioningHintDelivery.objects.filter(
            runtime_profile_id=materialization_context[1]
        ).count()
        == 1
    )


def test_lost_hint_response_retries_with_stable_payload(
    materialization_context, settings, monkeypatch
):
    _configure_hints(settings)
    receipt = _accept_receipt(materialization_context)
    first_now = timezone.now()
    opener = _Opener(
        [
            _LostResponse(202, b""),
            _Response(202, b'{"status":"accepted"}'),
        ]
    )
    monkeypatch.setattr(hint_service, "build_opener", lambda _handler: opener)

    first = publish_due_profile_readiness_hints(now=first_now, limit=1)
    delivery = ProvisioningHintDelivery.objects.get(
        runtime_profile_id=materialization_context[1]
    )
    delivery.next_attempt_at = first_now
    delivery.save(update_fields=["next_attempt_at", "updated_at"])
    second = publish_due_profile_readiness_hints(
        now=first_now + timedelta(seconds=1), limit=1
    )

    delivery.refresh_from_db()
    assert receipt.receipt_id == delivery.receipt_id
    assert first.claimed == 1
    assert first.delivered == 0
    assert first.deferred == 1
    assert second.delivered == 1
    assert delivery.state == ProvisioningHintDeliveryState.DELIVERED
    assert len(opener.requests) == 2
    assert opener.requests[0][1] == opener.requests[1][1] == 5
    assert opener.requests[0][0].data == opener.requests[1][0].data
    wire = json.loads(opener.requests[0][0].data)
    assert wire["hint_id"] == str(delivery.id)
    assert wire["receipt_id"] == str(receipt.receipt_id)


def test_stale_hint_attempt_is_fenced_after_lease_reclaim(materialization_context):
    _accept_receipt(materialization_context)
    first_now = timezone.now()
    first = claim_provisioning_hint_deliveries(now=first_now, limit=1)[0]
    delivery = ProvisioningHintDelivery.objects.get(pk=first.delivery_id)
    delivery.lease_expires_at = first_now - timedelta(seconds=1)
    delivery.next_attempt_at = first_now
    delivery.save(update_fields=["lease_expires_at", "next_attempt_at", "updated_at"])

    second = claim_provisioning_hint_deliveries(
        now=first_now + timedelta(seconds=1), limit=1
    )[0]
    assert second.attempt == 2
    assert (
        mark_provisioning_hint_delivery(
            first.delivery_id,
            attempt=first.attempt,
            success=True,
            now=first_now + timedelta(seconds=1),
        )
        is None
    )
    delivery.refresh_from_db()
    assert delivery.state == ProvisioningHintDeliveryState.DELIVERING
    assert delivery.delivery_attempts == second.attempt
    marked = mark_provisioning_hint_delivery(
        second.delivery_id,
        attempt=second.attempt,
        success=True,
        now=first_now + timedelta(seconds=1),
    )
    assert marked is not None
    assert marked.state == ProvisioningHintDeliveryState.DELIVERED


def test_crashed_final_hint_attempt_is_recovered_as_exhausted(materialization_context):
    _accept_receipt(materialization_context)
    observed_at = timezone.now()
    for expected_attempt in range(1, hint_service.MAX_HINT_DELIVERY_ATTEMPTS):
        claim = claim_provisioning_hint_deliveries(now=observed_at, limit=1)[0]
        assert claim.attempt == expected_attempt
        marked = mark_provisioning_hint_delivery(
            claim.delivery_id,
            attempt=claim.attempt,
            success=False,
            safe_error_code="hint_delivery_unavailable",
            now=observed_at,
        )
        assert marked is not None
        marked.next_attempt_at = observed_at
        marked.save(update_fields=["next_attempt_at", "updated_at"])

    final_claim = claim_provisioning_hint_deliveries(now=observed_at, limit=1)[0]
    assert final_claim.attempt == hint_service.MAX_HINT_DELIVERY_ATTEMPTS
    delivery = ProvisioningHintDelivery.objects.get(pk=final_claim.delivery_id)
    delivery.lease_expires_at = observed_at - timedelta(seconds=1)
    delivery.save(update_fields=["lease_expires_at", "updated_at"])

    assert (
        claim_provisioning_hint_deliveries(
            now=observed_at + timedelta(seconds=1), limit=1
        )
        == ()
    )
    delivery.refresh_from_db()
    assert delivery.state == ProvisioningHintDeliveryState.EXHAUSTED
    assert delivery.delivery_attempts == hint_service.MAX_HINT_DELIVERY_ATTEMPTS
    assert delivery.safe_error_code == "hint_lease_expired"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"{}", (503, "hint_delivery_receipt_invalid")),
        (
            b"x" * (hint_service.MAX_RESPONSE_BYTES + 1),
            (503, "hint_delivery_response_too_large"),
        ),
    ],
)
def test_hint_http_receipts_are_bounded(settings, monkeypatch, body, expected):
    _configure_hints(settings)
    opener = _Opener([_Response(202, body)])
    monkeypatch.setattr(hint_service, "build_opener", lambda _handler: opener)

    assert hint_service._post_hint_to_cloud(_claim()) == expected
    assert opener.requests[0][1] == 5


def test_hint_http_disables_redirects_before_sending_bearer(settings, monkeypatch):
    _configure_hints(settings)
    opener = _Opener([_Response(302, b"")])
    handlers = []
    monkeypatch.setattr(
        hint_service,
        "build_opener",
        lambda handler: handlers.append(handler) or opener,
    )

    status, _code = hint_service._post_hint_to_cloud(_claim())

    assert status == 302
    assert handlers == [hint_service._NoRedirect]
    assert (
        hint_service._NoRedirect().redirect_request(
            None, None, 302, "", {}, "https://evil.test"
        )
        is None
    )
    assert opener.requests[0][0].headers["Authorization"] == "Bearer " + "s" * 32


def test_hint_timing_uses_receipt_bridge_and_marks_http_failure(settings, monkeypatch):
    _configure_hints(settings)
    captured = []
    monkeypatch.setattr(
        hint_service,
        "emit_event",
        lambda event, **_kwargs: captured.append(event),
    )
    opener = _Opener([_Response(503, b'{"code":"temporary"}')])
    monkeypatch.setattr(hint_service, "build_opener", lambda _handler: opener)
    claim = _claim()

    assert hint_service._post_hint_to_cloud(claim) == (503, "temporary")
    assert captured[0]["event"] == "runtime.operation.started"
    assert captured[0]["request_id"] == str(claim.hint_id)
    assert captured[0]["correlation_id"] == str(claim.receipt_id)
    assert captured[-1]["event"] == "runtime.operation.failed"
    assert captured[-1]["operation"] == "readiness.hint_send"
    assert captured[-1]["status_code"] == 503
    assert captured[-1]["outcome"] == "error"


def test_materialization_timing_pairs_profile_and_operation_ids(
    materialization_context, monkeypatch
):
    monkeypatch.setenv("ALLIES_OBSERVABILITY_DIGEST_KEY", "test-digest")
    captured = []
    monkeypatch.setattr(
        profile_service,
        "emit_event",
        lambda event, **_kwargs: captured.append(event),
    )
    operation_id = uuid4()

    with TestCase.captureOnCommitCallbacks(execute=True):
        _accept_receipt(materialization_context, operation_id=operation_id)

    started = [
        event
        for event in captured
        if event["event"] == "runtime.operation.started"
        and event["operation"] == "runtime.profile_materialization_receipt"
    ][-1]
    terminal = [
        event
        for event in captured
        if event["event"] == "runtime.operation.succeeded"
        and event["operation"] == "runtime.profile_materialization_receipt"
    ][-1]
    assert started["profile_id"] == terminal["profile_id"]
    assert started["profile_id"].startswith("id_")
    assert started["correlation_id"] == str(operation_id)
    assert terminal["correlation_id"] == str(operation_id)


def test_feature_off_does_not_claim_or_post_hints(
    materialization_context, settings, monkeypatch
):
    _accept_receipt(materialization_context)
    settings.ALLIES_RUNTIME_READINESS_HINT_ENABLED = False
    posted = []
    monkeypatch.setattr(
        hint_service,
        "_post_hint_to_cloud",
        lambda claim: posted.append(claim) or pytest.fail("disabled hint posted"),
    )

    report = publish_due_profile_readiness_hints(limit=1)
    delivery = ProvisioningHintDelivery.objects.get(
        runtime_profile_id=materialization_context[1]
    )
    assert report == hint_service.PublishResult()
    assert delivery.state == ProvisioningHintDeliveryState.PENDING
    assert delivery.delivery_attempts == 0
    assert posted == []


def test_delivery_timestamp_records_acknowledgement_after_http(
    materialization_context, settings, monkeypatch
):
    _configure_hints(settings)
    _accept_receipt(materialization_context)
    started = timezone.now()
    acknowledged = started + timedelta(seconds=2)
    clock = [started]
    monkeypatch.setattr(hint_service.timezone, "now", lambda: clock[0])

    def post(_claim):
        clock[0] = acknowledged
        return 202, ""

    monkeypatch.setattr(hint_service, "_post_hint_to_cloud", post)
    report = publish_due_profile_readiness_hints(limit=1)
    delivery = ProvisioningHintDelivery.objects.get(
        runtime_profile_id=materialization_context[1]
    )
    assert report.delivered == 1
    assert delivery.delivered_at == acknowledged
