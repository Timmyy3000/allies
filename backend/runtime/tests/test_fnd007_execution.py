from __future__ import annotations

from uuid import uuid4

import pytest

from runtime.exceptions import RuntimeIdempotencyConflictError, RuntimeValidationError
from runtime.models import (
    Attempt,
    AttemptStatus,
    Execution,
    ExecutionEvent,
    ExecutionStatus,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.services.attempts import complete_attempt, fail_attempt
from runtime.services.claims import claim_next_execution
from runtime.services.events import append_runtime_event
from runtime.services.leases import (
    acknowledge_stopped,
    confirm_machine_stopped_and_fence,
)
from runtime.services.runtime_auth import (
    authenticate_runtime_token,
    issue_runtime_credential,
)


@pytest.fixture
def claimed_execution(db):
    workspace = Workspace.objects.create(
        tenant_ref="fnd007-tenant",
        fly_app_ref="app",
        volume_ref="volume",
        machine_ref="machine-1",
        machine_generation=1,
        provisioning_phase=WorkspaceProvisioningPhase.IDLE,
    )
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="ally",
        hermes_profile_key="ally",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=1,
    )
    execution = Execution.objects.create(
        workspace=workspace,
        profile=profile,
        idempotency_key="turn-1",
        input_payload={"message": "hello", "cloud_conversation_ref": "cloud-1"},
    )
    issued = issue_runtime_credential(workspace.id, "runtime-secret")
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 2)
    return context, execution, claim


def dispatch(context, claim):
    return append_runtime_event(
        context,
        claim.attempt_id,
        claim.lease_token,
        uuid4(),
        claim.stream_id,
        1,
        "execution.dispatched",
        {"status": "dispatched"},
    )


def test_complete_atomically_appends_terminal_event_and_replays(claimed_execution):
    context, execution, claim = claimed_execution
    dispatch(context, claim)
    event_id = uuid4()
    terminal_event = {
        "event_id": event_id,
        "stream_id": claim.stream_id,
        "sequence": 2,
        "payload": {"run_id": "run-1", "status": "completed"},
    }

    first = complete_attempt(
        context,
        claim.attempt_id,
        claim.lease_token,
        {"code": "ok"},
        terminal_event=terminal_event,
    )
    replay = complete_attempt(
        context,
        claim.attempt_id,
        claim.lease_token,
        {"code": "ok"},
        terminal_event=terminal_event,
    )

    assert replay == first
    assert Attempt.objects.get(pk=claim.attempt_id).status == AttemptStatus.SUCCEEDED
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.SUCCEEDED
    assert list(
        ExecutionEvent.objects.filter(attempt_id=claim.attempt_id)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    ) == ["execution.dispatched", "execution.completed"]

    conflicting = {
        **terminal_event,
        "payload": {"run_id": "other", "status": "completed"},
    }
    with pytest.raises(RuntimeIdempotencyConflictError):
        complete_attempt(
            context,
            claim.attempt_id,
            claim.lease_token,
            {"code": "ok"},
            terminal_event=conflicting,
        )


def test_fail_atomically_appends_failure_and_dispatch_prevents_requeue(
    claimed_execution,
):
    context, execution, claim = claimed_execution
    dispatch(context, claim)
    failure = {
        "code": "malformed_response",
        "retryable": False,
        "receipt": {"code": "malformed_response"},
    }
    terminal_event = {
        "event_id": uuid4(),
        "stream_id": claim.stream_id,
        "sequence": 2,
        "payload": {"code": "malformed_response", "retryable": False},
    }

    receipt = fail_attempt(
        context,
        claim.attempt_id,
        claim.lease_token,
        failure,
        terminal_event=terminal_event,
    )

    assert receipt.requeued is False
    assert list(
        ExecutionEvent.objects.filter(attempt_id=claim.attempt_id)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    ) == ["execution.dispatched", "execution.failed"]
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.FAILED


def test_stopped_after_dispatch_is_unknown_safe_and_not_requeued(claimed_execution):
    context, execution, claim = claimed_execution
    dispatch(context, claim)

    receipt = acknowledge_stopped(
        context, claim.attempt_id, claim.lease_token, "lease_lost"
    )

    assert receipt.requeued is False
    assert Attempt.objects.get(pk=claim.attempt_id).status == AttemptStatus.UNKNOWN
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.FAILED


def test_runtime_event_append_rejects_unknown_or_unsafe_payload(claimed_execution):
    context, _execution, claim = claimed_execution

    with pytest.raises(RuntimeValidationError):
        append_runtime_event(
            context,
            claim.attempt_id,
            claim.lease_token,
            uuid4(),
            claim.stream_id,
            1,
            "unknown.event",
            {},
        )
    with pytest.raises(RuntimeValidationError):
        append_runtime_event(
            context,
            claim.attempt_id,
            claim.lease_token,
            uuid4(),
            claim.stream_id,
            1,
            "activity.started",
            {"activity_id": "a", "kind": "tool", "args": {"secret": "x"}},
        )


def test_machine_fence_does_not_requeue_dispatched_work(claimed_execution):
    context, execution, claim = claimed_execution
    dispatch(context, claim)
    workspace = execution.workspace
    workspace.machine_generation = 2
    workspace.machine_ref = None
    workspace.provisioning_phase = WorkspaceProvisioningPhase.OLD_MACHINE_STOPPED
    workspace.provisioning_kind = "replace"
    workspace.provisioning_source_generation = 1
    workspace.provisioning_target_generation = 2
    workspace.provisioning_previous_machine_ref = "machine-1"
    workspace.save(
        update_fields=[
            "machine_generation",
            "machine_ref",
            "provisioning_phase",
            "provisioning_kind",
            "provisioning_source_generation",
            "provisioning_target_generation",
            "provisioning_previous_machine_ref",
            "updated_at",
        ]
    )

    receipt = confirm_machine_stopped_and_fence(workspace.id, 1, 2, "machine-1")

    assert receipt.requeued_count == 0
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.FAILED
