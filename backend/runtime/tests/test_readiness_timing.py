from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from observability import events as observability_events
from runtime.exceptions import RuntimeFencedError, RuntimeValidationError
from runtime.models import (
    RuntimeOperationState,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.services import runtime_readiness
from runtime.services import timing as runtime_timing
from runtime.services.runtime_auth import RuntimeContext
from runtime.services.runtime_readiness import accept_runtime_readiness


@pytest.fixture
def readiness_workspace(transactional_db):
    requested_at = timezone.now()
    workspace = Workspace.objects.create(
        tenant_ref=f"readiness-timing-{uuid4()}",
        fly_app_ref="app",
        volume_ref="volume",
        machine_ref="machine",
        machine_generation=7,
        runtime_start_epoch=3,
        runtime_operation_id=uuid4(),
        runtime_operation_state=RuntimeOperationState.AWAITING_READINESS,
        runtime_operation_requested_at=requested_at,
        provisioning_phase=WorkspaceProvisioningPhase.IDLE,
    )
    return workspace


@pytest.fixture
def serialized_events(monkeypatch):
    captured = []

    def capture(envelope: bytes, **_kwargs):
        captured.append(json.loads(envelope))
        return SimpleNamespace(accepted=True, dropped=False)

    monkeypatch.setattr(observability_events, "_offer_stdout", capture)
    monkeypatch.setattr(
        observability_events,
        "_error_rate_limiter",
        observability_events._ErrorRateLimiter(),
    )
    return captured


def _operation_events(events, operation):
    return [event for event in events if event.get("operation") == operation]


def _readiness_context(workspace):
    return RuntimeContext(workspace.id, workspace.machine_generation, uuid4())


@pytest.mark.django_db(transaction=True)
def test_readiness_success_event_waits_for_outer_commit(
    readiness_workspace, serialized_events, monkeypatch
):
    monkeypatch.setenv("ALLIES_OBSERVABILITY_DIGEST_KEY", "test-digest")
    context = _readiness_context(readiness_workspace)
    boot_id = uuid4()
    operation_id = readiness_workspace.runtime_operation_id

    with transaction.atomic():
        receipt = accept_runtime_readiness(
            context,
            boot_id,
            readiness_workspace.machine_generation,
            readiness_workspace.runtime_start_epoch,
            now=readiness_workspace.runtime_operation_requested_at,
        )

        assert receipt.status == "ready"
        assert [
            event["event"]
            for event in _operation_events(
                serialized_events, "runtime.readiness_receipt"
            )
        ] == ["runtime.operation.started"]

    receipt_events = _operation_events(serialized_events, "runtime.readiness_receipt")
    assert [event["event"] for event in receipt_events] == [
        "runtime.operation.started",
        "runtime.operation.succeeded",
    ]
    succeeded = receipt_events[1]
    assert succeeded["request_id"] == str(boot_id)
    assert succeeded["correlation_id"] == str(operation_id)
    assert succeeded["generation"] == readiness_workspace.machine_generation
    assert succeeded["runtime_start_epoch"] == readiness_workspace.runtime_start_epoch
    assert succeeded["workspace_id"].startswith("id_")

    wall_events = _operation_events(
        serialized_events, "runtime.readiness.scheduled_to_commit_wall"
    )
    assert len(wall_events) == 1
    assert wall_events[0]["request_id"] == str(boot_id)
    assert wall_events[0]["correlation_id"] == str(operation_id)
    assert wall_events[0]["generation"] == readiness_workspace.machine_generation
    assert (
        wall_events[0]["runtime_start_epoch"] == readiness_workspace.runtime_start_epoch
    )


@pytest.mark.django_db(transaction=True)
def test_readiness_rollback_discards_success_event(
    readiness_workspace, serialized_events
):
    context = _readiness_context(readiness_workspace)
    boot_id = uuid4()

    with pytest.raises(RuntimeError, match="rollback readiness"), transaction.atomic():
        accept_runtime_readiness(
            context,
            boot_id,
            readiness_workspace.machine_generation,
            readiness_workspace.runtime_start_epoch,
            now=readiness_workspace.runtime_operation_requested_at,
        )
        assert not any(
            event["event"] == "runtime.operation.succeeded"
            for event in serialized_events
        )
        raise RuntimeError("rollback readiness")

    assert not any(
        event["event"] == "runtime.operation.succeeded" for event in serialized_events
    )
    readiness_workspace.refresh_from_db()
    assert readiness_workspace.runtime_operation_state == (
        RuntimeOperationState.AWAITING_READINESS
    )


@pytest.mark.django_db(transaction=True)
def test_scheduled_to_commit_duration_uses_commit_callback_time(
    readiness_workspace, serialized_events, monkeypatch
):
    requested_at = readiness_workspace.runtime_operation_requested_at
    accepted_at = requested_at + timedelta(milliseconds=250)
    committed_at = requested_at + timedelta(milliseconds=1750)
    monkeypatch.setattr(runtime_readiness.timezone, "now", lambda: committed_at)

    with transaction.atomic():
        receipt = accept_runtime_readiness(
            _readiness_context(readiness_workspace),
            uuid4(),
            readiness_workspace.machine_generation,
            readiness_workspace.runtime_start_epoch,
            now=accepted_at,
        )

    assert receipt.accepted_at == accepted_at
    wall_events = _operation_events(
        serialized_events, "runtime.readiness.scheduled_to_commit_wall"
    )
    assert len(wall_events) == 1
    assert wall_events[0]["duration_ms"] == pytest.approx(1750.0)
    assert wall_events[0]["duration_ms"] != pytest.approx(1500.0)


def test_invalid_readiness_emits_started_and_failed_pair(
    readiness_workspace, serialized_events
):
    with pytest.raises(RuntimeValidationError):
        accept_runtime_readiness(
            _readiness_context(readiness_workspace),
            "invalid-boot-id",
            readiness_workspace.machine_generation,
            readiness_workspace.runtime_start_epoch,
            now=readiness_workspace.runtime_operation_requested_at,
        )

    events = _operation_events(serialized_events, "runtime.readiness_receipt")
    assert [event["event"] for event in events] == [
        "runtime.operation.started",
        "runtime.operation.failed",
    ]
    assert events[1]["outcome"] == "error"
    assert events[1]["error_type"] == "RuntimeValidationError"
    assert events[1]["duration_ms"] >= 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("stale_field", ["generation", "start_epoch"])
def test_fenced_readiness_emits_started_and_failed_pair(
    readiness_workspace, serialized_events, stale_field
):
    boot_id = uuid4()
    generation = readiness_workspace.machine_generation
    start_epoch = readiness_workspace.runtime_start_epoch
    if stale_field == "generation":
        generation -= 1
    else:
        start_epoch -= 1
    with pytest.raises(RuntimeFencedError):
        accept_runtime_readiness(
            _readiness_context(readiness_workspace),
            boot_id,
            generation,
            start_epoch,
            now=readiness_workspace.runtime_operation_requested_at,
        )

    events = _operation_events(serialized_events, "runtime.readiness_receipt")
    assert [event["event"] for event in events] == [
        "runtime.operation.started",
        "runtime.operation.failed",
    ]
    assert events[1]["request_id"] == str(boot_id)
    assert "correlation_id" not in events[1]
    assert events[1]["error_type"] == "RuntimeFencedError"
    assert events[1]["outcome"] == "error"


def test_broken_timing_event_builder_does_not_change_readiness_result(
    readiness_workspace, monkeypatch
):
    def broken_builder(*_args, **_kwargs):
        raise RuntimeError("event builder unavailable")

    monkeypatch.setattr(observability_events, "build_event", broken_builder)
    monkeypatch.setattr(runtime_readiness, "build_event", broken_builder, raising=False)
    monkeypatch.setattr(runtime_timing, "build_event", broken_builder)

    context = _readiness_context(readiness_workspace)
    boot_id = uuid4()
    receipt = accept_runtime_readiness(
        context,
        boot_id,
        readiness_workspace.machine_generation,
        readiness_workspace.runtime_start_epoch,
        now=readiness_workspace.runtime_operation_requested_at,
    )

    assert receipt.status == "ready"
    readiness_workspace.refresh_from_db()
    assert readiness_workspace.ready_boot_id == boot_id
    assert (
        readiness_workspace.ready_generation == readiness_workspace.machine_generation
    )
    assert readiness_workspace.runtime_operation_state == RuntimeOperationState.IDLE
