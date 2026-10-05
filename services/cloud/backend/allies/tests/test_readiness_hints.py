from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.db import transaction
from django.test import Client, override_settings
from django.utils import timezone

from allies.gateways.foundry import ProfileReadinessHint
from allies.models import Ally, AllyBinding, ProvisioningOperation, ProvisioningStatus
from allies.services.provisioning import (
    _defer,
    accept_profile_readiness_hint,
)
from auths.models import User
from workspaces.models import Workspace


@pytest.fixture
def operation(db):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Hints")
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study partner",
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    binding = AllyBinding.objects.create(ally=ally)
    return ProvisioningOperation.objects.create(
        binding=binding,
        workspace=workspace,
        user=user,
        api_idempotency_key_digest="a" * 64,
        content_fingerprint="b" * 64,
        expires_at=timezone.now() + timedelta(hours=1),
    )


def _hint(operation, *, occurred_at: datetime) -> ProfileReadinessHint:
    return ProfileReadinessHint(
        version=1,
        hint_id=uuid4(),
        workspace_id=operation.workspace_id,
        ally_ref=operation.binding.ally_id,
        runtime_profile_id=uuid4(),
        generation=4,
        receipt_id=uuid4(),
        occurred_at=occurred_at,
    )


@pytest.mark.django_db
def test_hint_timing_maps_delivery_to_operation_after_commit(
    operation, monkeypatch, django_capture_on_commit_callbacks
):
    events = []
    monkeypatch.setattr(
        "allies.services.provisioning.emit_event",
        lambda kind, **fields: events.append(fields),
    )
    monkeypatch.setattr(
        "allies.services.provisioning._enqueue_due_dispatch", lambda: None
    )
    payload = _hint(operation, occurred_at=timezone.now())
    with django_capture_on_commit_callbacks(execute=True):
        assert accept_profile_readiness_hint(payload).status == "accepted"
        assert events == []
    assert len(events) == 1
    assert events[0]["request_id"] == str(payload.hint_id)
    assert events[0]["correlation_id"] == str(operation.pk)


@pytest.mark.django_db
def test_pending_hint_marks_operation_due_and_wakes_dispatch(operation, monkeypatch):
    receive_at = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    scheduled = []
    monkeypatch.setattr(
        "allies.services.provisioning._enqueue_due_dispatch",
        lambda: scheduled.append(True),
    )
    monkeypatch.setattr(
        "allies.services.provisioning.transaction.on_commit",
        lambda callback: callback(),
    )

    result = accept_profile_readiness_hint(
        _hint(operation, occurred_at=receive_at), now=receive_at
    )

    operation.refresh_from_db()
    assert result.status == "accepted"
    assert operation.readiness_hint_received_at == receive_at
    assert operation.next_attempt_at <= receive_at
    assert scheduled == [True]


@pytest.mark.django_db
def test_terminal_hint_is_idempotent_noop(operation, monkeypatch):
    operation.status = ProvisioningStatus.SUCCEEDED
    operation.save(update_fields=("status", "updated_at"))
    monkeypatch.setattr(
        "allies.services.provisioning._enqueue_due_dispatch",
        lambda: pytest.fail("terminal hint scheduled work"),
    )

    result = accept_profile_readiness_hint(
        _hint(operation, occurred_at=datetime.now(UTC)), now=datetime.now(UTC)
    )

    operation.refresh_from_db()
    assert result.status == "ignored"
    assert operation.readiness_hint_received_at is None


@pytest.mark.django_db
def test_hint_during_late_live_attempt_wakes_after_defer(operation, monkeypatch):
    attempt_started = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    operation.status = ProvisioningStatus.IN_PROGRESS
    operation.attempt_count = 4
    operation.last_attempt_at = attempt_started
    operation.lease_expires_at = attempt_started + timedelta(minutes=1)
    operation.next_attempt_at = attempt_started + timedelta(minutes=1)
    operation.save(
        update_fields=(
            "status",
            "attempt_count",
            "last_attempt_at",
            "lease_expires_at",
            "next_attempt_at",
            "updated_at",
        )
    )
    receive_at = attempt_started + timedelta(seconds=2)
    scheduled = []
    monkeypatch.setattr(
        "allies.services.provisioning._enqueue_due_dispatch",
        lambda: scheduled.append(True),
    )
    monkeypatch.setattr(
        "allies.services.provisioning.transaction.on_commit",
        lambda callback: callback(),
    )
    accept_profile_readiness_hint(
        _hint(operation, occurred_at=receive_at), now=receive_at
    )

    assert _defer(
        operation.id,
        4,
        "materialization_pending",
        now=receive_at + timedelta(seconds=1),
    )
    operation.refresh_from_db()
    assert operation.status == ProvisioningStatus.RETRYABLE
    assert operation.next_attempt_at == receive_at + timedelta(seconds=1)
    assert scheduled == [True]


@pytest.mark.django_db
def test_hint_scope_mismatch_is_unavailable(operation):
    payload = _hint(operation, occurred_at=datetime.now(UTC)).model_copy(
        update={"ally_ref": uuid4()}
    )

    with pytest.raises(ValueError):
        accept_profile_readiness_hint(payload)


@pytest.mark.django_db
@override_settings(ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN="hint-token")
def test_foundry_hint_endpoint_requires_service_auth_and_returns_plain_202(operation):
    client = Client()
    payload = _hint(operation, occurred_at=datetime.now(UTC)).model_dump(mode="json")
    response = client.post(
        "/api/v1/internal/foundry/profile-readiness-hints",
        json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer hint-token",
    )

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}


@pytest.mark.django_db
@pytest.mark.parametrize("authorization", ["", "Bearer wrong", "Basic hint-token"])
@override_settings(ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN="hint-token")
def test_hint_rejects_untrusted_sender_without_mutation(operation, authorization):
    response = Client().post(
        "/api/v1/internal/foundry/profile-readiness-hints",
        _hint(operation, occurred_at=datetime.now(UTC)).model_dump_json(),
        content_type="application/json",
        HTTP_AUTHORIZATION=authorization,
    )
    assert response.status_code == 401
    operation.refresh_from_db()
    assert operation.readiness_hint_received_at is None


@pytest.mark.django_db(transaction=True)
def test_hint_dispatch_follows_commit_and_broker_failure_preserves_due_work(
    operation, monkeypatch
):
    observed = []
    events = []
    monkeypatch.setattr(
        "allies.services.provisioning.emit_event",
        lambda event, **fields: events.append({"event": event, **fields}),
    )

    def unavailable_broker():
        observed.append(transaction.get_connection().in_atomic_block)
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr(
        "allies.tasks.dispatch_due_provisioning_task.apply_async", unavailable_broker
    )
    now = timezone.now()
    with transaction.atomic():
        accept_profile_readiness_hint(_hint(operation, occurred_at=now), now=now)
        assert observed == []
    assert observed == [False]
    failure = next(
        event for event in events if event.get("operation") == "readiness.hint_dispatch"
    )
    assert failure == {
        "event": "runtime.operation.failed",
        "operation": "readiness.hint_dispatch",
        "error_code": "broker_unavailable",
        "error_type": "ConnectionError",
    }
    from observability.events import build_event

    serialized = build_event(
        failure["event"],
        **{key: value for key, value in failure.items() if key != "event"},
    )
    assert serialized["outcome"] == "error"
    assert serialized["error_code"] == "broker_unavailable"
    operation.refresh_from_db()
    assert operation.next_attempt_at == now
    assert operation.readiness_hint_received_at == now
    assert operation.status == ProvisioningStatus.PENDING
