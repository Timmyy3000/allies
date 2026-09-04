from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from runtime.exceptions import (
    RuntimeIdempotencyConflictError,
    RuntimeLeaseConflictError,
    RuntimeValidationError,
)
from runtime.models import (
    Attempt,
    AttemptStatus,
    ConversationBinding,
    Execution,
    ExecutionEvent,
    ExecutionEventDelivery,
    ExecutionStatus,
    Lease,
    LeaseState,
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
    RuntimeContext,
    authenticate_runtime_token,
    issue_runtime_credential,
)
from runtime.services.sessions import update_session_binding


@pytest.fixture
def claimed_execution(db):
    workspace = Workspace.objects.create(
        tenant_ref="fnd007-tenant",
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
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="ally",
        hermes_profile_key="ally",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=1,
        seed_payload={"model": "gpt-5.6-luna"},
    )
    execution = Execution.objects.create(
        workspace=workspace,
        profile=profile,
        idempotency_key="turn-1",
        input_payload={"message": "hello", "cloud_conversation_ref": "cloud-1"},
    )
    ConversationBinding.objects.create(
        profile=profile,
        cloud_conversation_ref="cloud-1",
        hermes_session_id=None,
    )
    issued = issue_runtime_credential(workspace.id, "runtime-secret")
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 2)
    return context, execution, claim


def test_claim_exposes_reserved_conversation_before_hermes_session(
    claimed_execution,
):
    _context, _execution, claim = claimed_execution

    assert claim.conversation_id == "cloud-1"
    assert claim.session_id is None


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


def bind_effective_session(context, claim):
    return update_session_binding(
        context,
        claim.attempt_id,
        claim.lease_token,
        "cloud-1",
        None,
        "session-1",
    )


def test_complete_atomically_appends_terminal_event_and_replays(claimed_execution):
    context, execution, claim = claimed_execution
    dispatch(context, claim)
    bind_effective_session(context, claim)
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


def test_complete_requires_effective_session_before_terminal_event(
    claimed_execution,
):
    context, execution, claim = claimed_execution
    dispatch(context, claim)
    terminal_event = {
        "event_id": uuid4(),
        "stream_id": claim.stream_id,
        "sequence": 2,
        "payload": {"run_id": "run-1", "status": "completed"},
    }

    with pytest.raises(RuntimeLeaseConflictError, match="effective session"):
        complete_attempt(
            context,
            claim.attempt_id,
            claim.lease_token,
            {"code": "ok"},
            terminal_event=terminal_event,
        )

    assert Attempt.objects.get(pk=claim.attempt_id).status == AttemptStatus.RUNNING
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.RUNNING
    assert not ExecutionEvent.objects.filter(
        attempt_id=claim.attempt_id, event_type="execution.completed"
    ).exists()

    bind_effective_session(context, claim)
    complete_attempt(
        context,
        claim.attempt_id,
        claim.lease_token,
        {"code": "ok"},
        terminal_event=terminal_event,
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


def test_projection_event_budget_reserves_sequence_513_for_terminal_truth(
    claimed_execution,
):
    context, _execution, claim = claimed_execution

    with pytest.raises(RuntimeValidationError, match="1 to 513"):
        complete_attempt(
            context,
            claim.attempt_id,
            claim.lease_token,
            {"code": "ok"},
            terminal_event={
                "event_id": uuid4(),
                "stream_id": claim.stream_id,
                "sequence": 514,
                "payload": {"run_id": "run-1", "status": "completed"},
            },
        )

    dispatch(context, claim)
    bind_effective_session(context, claim)
    receipt = complete_attempt(
        context,
        claim.attempt_id,
        claim.lease_token,
        {"code": "ok"},
        terminal_event={
            "event_id": uuid4(),
            "stream_id": claim.stream_id,
            "sequence": 513,
            "payload": {"run_id": "run-1", "status": "completed"},
        },
    )

    assert receipt.status == AttemptStatus.SUCCEEDED
    assert (
        ExecutionEvent.objects.get(attempt_id=claim.attempt_id, sequence=513).event_type
        == "execution.completed"
    )


def make_cloud_visible(execution):
    execution.command_id = uuid4()
    execution.cloud_workspace_id = uuid4()
    execution.cloud_ally_id = uuid4()
    execution.cloud_conversation_id = uuid4()
    execution.cloud_message_id = uuid4()
    execution.cloud_binding_id = uuid4()
    execution.conversation_turn_ordinal = 1
    execution.source_kind = "conversation_message"
    execution.command_fingerprint = "canonical-json-sha256:v1:" + "0" * 64
    execution.save(
        update_fields=[
            "command_id",
            "cloud_workspace_id",
            "cloud_ally_id",
            "cloud_conversation_id",
            "cloud_message_id",
            "cloud_binding_id",
            "conversation_turn_ordinal",
            "source_kind",
            "command_fingerprint",
            "updated_at",
        ]
    )


def test_expired_lease_uses_next_sequence_for_synthetic_failure(claimed_execution):
    context, execution, claim = claimed_execution
    dispatch(context, claim)
    for sequence in range(2, 513):
        append_runtime_event(
            context,
            claim.attempt_id,
            claim.lease_token,
            uuid4(),
            claim.stream_id,
            sequence,
            "message.delta",
            {"text": "x"},
        )
    Lease.objects.filter(pk=claim.lease_id).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    assert claim_next_execution(context, uuid4(), 1) is None

    failure = ExecutionEvent.objects.get(
        attempt_id=claim.attempt_id,
        event_type="execution.failed",
    )
    assert failure.sequence == 513
    assert failure.stream_id == claim.stream_id
    assert failure.payload == {"code": "lease_expired", "retryable": False}
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.FAILED


@pytest.mark.parametrize("prior_sequence", [513, 100000])
def test_expired_lease_recovers_after_high_nonterminal_sequence(
    claimed_execution, prior_sequence
):
    context, execution, claim = claimed_execution
    dispatch(context, claim)
    append_runtime_event(
        context,
        claim.attempt_id,
        claim.lease_token,
        uuid4(),
        claim.stream_id,
        prior_sequence,
        "message.delta",
        {"text": "last durable delta"},
    )
    Lease.objects.filter(pk=claim.lease_id).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    assert claim_next_execution(context, uuid4(), 1) is None

    failure = ExecutionEvent.objects.get(
        attempt_id=claim.attempt_id,
        event_type="execution.failed",
    )
    assert failure.sequence == prior_sequence + 1
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.FAILED


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("session_request_digest", "a" * 64),
        ("session_receipt", {"session_id": "session-1"}),
    ],
)
def test_expired_session_only_ambiguity_fails_without_replay(
    claimed_execution, field, value
):
    context, execution, claim = claimed_execution
    make_cloud_visible(execution)
    Attempt.objects.filter(pk=claim.attempt_id).update(**{field: value})
    Lease.objects.filter(pk=claim.lease_id).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    assert claim_next_execution(context, uuid4(), 1) is None
    assert claim_next_execution(context, uuid4(), 1) is None

    assert Attempt.objects.filter(execution_id=execution.id).count() == 1
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.FAILED
    failure = ExecutionEvent.objects.get(
        attempt_id=claim.attempt_id,
        event_type="execution.failed",
    )
    assert failure.payload == {"code": "lease_expired", "retryable": False}
    assert ExecutionEventDelivery.objects.filter(event=failure).count() == 1


def test_expired_retired_generation_is_failed_and_fenced(claimed_execution):
    _context, execution, claim = claimed_execution
    workspace = execution.workspace
    workspace.machine_generation = 2
    workspace.machine_ref = "machine-2"
    workspace.ready_generation = 2
    workspace.ready_start_epoch = workspace.runtime_start_epoch
    workspace.runtime_last_seen_at = timezone.now()
    workspace.save(
        update_fields=[
            "machine_generation",
            "machine_ref",
            "ready_generation",
            "ready_start_epoch",
            "runtime_last_seen_at",
            "updated_at",
        ]
    )
    Lease.objects.filter(pk=claim.lease_id).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    current_context = RuntimeContext(workspace.id, 2, uuid4())
    assert claim_next_execution(current_context, uuid4(), 1) is None

    assert Lease.objects.get(pk=claim.lease_id).state == LeaseState.FENCED
    assert Attempt.objects.get(pk=claim.attempt_id).status == AttemptStatus.UNKNOWN
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.FAILED
    failure = ExecutionEvent.objects.get(
        attempt_id=claim.attempt_id,
        event_type="execution.failed",
    )
    assert failure.payload == {"code": "lease_expired", "retryable": False}


def test_expired_failure_persists_one_cloud_outbox_row(claimed_execution):
    context, execution, claim = claimed_execution
    make_cloud_visible(execution)
    dispatch(context, claim)
    Lease.objects.filter(pk=claim.lease_id).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    assert claim_next_execution(context, uuid4(), 1) is None

    failure = ExecutionEvent.objects.get(
        attempt_id=claim.attempt_id,
        event_type="execution.failed",
    )
    delivery = ExecutionEventDelivery.objects.get(event=failure)
    assert delivery.state == "pending"
    assert delivery.byte_length > 0


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
