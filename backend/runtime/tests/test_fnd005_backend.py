from __future__ import annotations

from datetime import timedelta
from threading import Barrier, Thread
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import OperationalError, close_old_connections
from django.test import Client
from django.utils import timezone

from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeDomainError,
    RuntimeFencedError,
    RuntimeIdempotencyConflictError,
    RuntimeLeaseConflictError,
    RuntimeNotReadyError,
    RuntimeValidationError,
)
from runtime.models import (
    Attempt,
    Execution,
    ExecutionEvent,
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
    renew_lease,
)
from runtime.services.runtime_auth import (
    RuntimeContext,
    authenticate_runtime_token,
    issue_runtime_credential,
    issue_runtime_credential_for_generation,
)
from runtime.services.sessions import update_session_binding


@pytest.fixture
def ready_workspace(db):
    return Workspace.objects.create(
        tenant_ref="fnd005-tenant",
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


@pytest.fixture
def runtime_setup(ready_workspace):
    profile = RuntimeProfile.objects.create(
        workspace=ready_workspace,
        ally_ref="ally",
        hermes_profile_key="ally",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=ready_workspace.machine_generation,
    )
    execution = Execution.objects.create(
        workspace=ready_workspace,
        profile=profile,
        idempotency_key="turn-1",
        input_payload={"message": "hello"},
    )
    issued = issue_runtime_credential(ready_workspace.id, "runtime-secret")
    return ready_workspace, profile, execution, issued


def test_claim_replay_and_terminal_receipt(runtime_setup):
    _workspace, _profile, execution, issued = runtime_setup
    context = authenticate_runtime_token(issued.raw_token)
    claim_id = uuid4()
    first = claim_next_execution(context, claim_id, 2)
    replay = claim_next_execution(context, claim_id, 2)
    assert first is not None
    assert replay == first
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.RUNNING
    terminal = complete_attempt(
        context,
        first.attempt_id,
        first.lease_token,
        {"code": "ok", "summary_ref": "local"},
    )
    assert (
        complete_attempt(
            context,
            first.attempt_id,
            first.lease_token,
            {"code": "ok", "summary_ref": "local"},
        )
        == terminal
    )
    with pytest.raises(RuntimeIdempotencyConflictError):
        complete_attempt(
            context,
            first.attempt_id,
            first.lease_token,
            {"code": "different"},
        )


def test_generation_credential_issue_is_exactly_replayable(ready_workspace):
    operation_id = uuid4()
    first = issue_runtime_credential_for_generation(
        ready_workspace.id,
        ready_workspace.machine_generation,
        "generation-secret",
        operation_id,
    )
    replay = issue_runtime_credential_for_generation(
        ready_workspace.id,
        ready_workspace.machine_generation,
        "generation-secret",
        operation_id,
    )

    assert replay.credential.id == first.credential.id == operation_id
    assert replay.raw_token == "generation-secret"
    with pytest.raises(RuntimeIdempotencyConflictError):
        issue_runtime_credential_for_generation(
            ready_workspace.id,
            ready_workspace.machine_generation,
            "different-secret",
            operation_id,
        )


def test_stop_accepts_stopping_and_requeues(runtime_setup):
    _workspace, _profile, execution, issued = runtime_setup
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 1)
    lease = Lease.objects.get(pk=claim.lease_id)
    lease.state = LeaseState.STOPPING
    lease.save(update_fields=["state", "updated_at"])
    receipt = acknowledge_stopped(context, claim.attempt_id, claim.lease_token, "lost")
    assert receipt.requeued is True
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.QUEUED
    assert (
        acknowledge_stopped(context, claim.attempt_id, claim.lease_token, "lost")
        == receipt
    )


def test_fence_rejects_old_context_and_requeues(runtime_setup):
    workspace, _profile, execution, issued = runtime_setup
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 1)
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
    assert receipt.fenced_count == 1
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.QUEUED
    with pytest.raises(RuntimeFencedError):
        renew_lease(context, claim.attempt_id, claim.lease_token)


def test_fence_requires_exact_replacement_cas(runtime_setup):
    workspace, _profile, _execution, _issued = runtime_setup
    workspace.machine_generation = 2
    workspace.provisioning_kind = "replace"
    workspace.provisioning_source_generation = 1
    workspace.provisioning_target_generation = 2
    workspace.provisioning_previous_machine_ref = "machine-1"
    workspace.provisioning_phase = WorkspaceProvisioningPhase.MACHINE_STARTED
    workspace.save(
        update_fields=[
            "machine_generation",
            "provisioning_kind",
            "provisioning_source_generation",
            "provisioning_target_generation",
            "provisioning_previous_machine_ref",
            "provisioning_phase",
            "updated_at",
        ]
    )
    with pytest.raises(RuntimeConflictError):
        confirm_machine_stopped_and_fence(workspace.id, 1, 2, "machine-1")
    workspace.provisioning_phase = WorkspaceProvisioningPhase.OLD_MACHINE_STOPPED
    workspace.save(update_fields=["provisioning_phase", "updated_at"])
    with pytest.raises(RuntimeConflictError):
        confirm_machine_stopped_and_fence(workspace.id, 1, 2, "wrong-machine")


def test_claim_requires_ready_workspace(runtime_setup):
    workspace, _profile, _execution, issued = runtime_setup
    workspace.provisioning_phase = WorkspaceProvisioningPhase.MACHINE_STARTED
    workspace.save(update_fields=["provisioning_phase", "updated_at"])
    context = authenticate_runtime_token(issued.raw_token)
    with pytest.raises(RuntimeNotReadyError):
        claim_next_execution(context, uuid4(), 1)


def test_session_binding_replays_after_terminal_release(runtime_setup):
    _workspace, _profile, _execution, issued = runtime_setup
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 1)
    first = update_session_binding(
        context,
        claim.attempt_id,
        claim.lease_token,
        "cloud-conversation",
        None,
        "hermes-session-1",
    )
    complete_attempt(context, claim.attempt_id, claim.lease_token, {"code": "ok"})
    assert (
        update_session_binding(
            context,
            claim.attempt_id,
            claim.lease_token,
            "cloud-conversation",
            None,
            "hermes-session-1",
        )
        == first
    )
    with pytest.raises(RuntimeIdempotencyConflictError):
        update_session_binding(
            context,
            claim.attempt_id,
            claim.lease_token,
            "cloud-conversation",
            None,
            "hermes-session-2",
        )


def test_old_session_replay_returns_attempt_value_after_later_rotation(runtime_setup):
    _workspace, profile, execution, issued = runtime_setup
    _second_execution = Execution.objects.create(
        workspace=execution.workspace,
        profile=profile,
        idempotency_key="turn-2",
        input_payload={"message": "second"},
    )
    context = authenticate_runtime_token(issued.raw_token)
    first_claim = claim_next_execution(context, uuid4(), 1)
    first_binding = update_session_binding(
        context,
        first_claim.attempt_id,
        first_claim.lease_token,
        "cloud-conversation",
        None,
        "hermes-session-1",
    )
    complete_attempt(
        context, first_claim.attempt_id, first_claim.lease_token, {"code": "ok"}
    )
    second_claim = claim_next_execution(context, uuid4(), 1)
    update_session_binding(
        context,
        second_claim.attempt_id,
        second_claim.lease_token,
        "cloud-conversation",
        "hermes-session-1",
        "hermes-session-2",
    )
    complete_attempt(
        context,
        second_claim.attempt_id,
        second_claim.lease_token,
        {"code": "ok"},
    )
    replay = update_session_binding(
        context,
        first_claim.attempt_id,
        first_claim.lease_token,
        "cloud-conversation",
        None,
        "hermes-session-1",
    )
    assert first_binding.hermes_session_id == "hermes-session-1"
    assert replay.hermes_session_id == "hermes-session-1"


def test_claim_replay_cannot_return_a_retired_generation(runtime_setup):
    workspace, _profile, _execution, issued = runtime_setup
    context = authenticate_runtime_token(issued.raw_token)
    claim_id = uuid4()
    claim = claim_next_execution(context, claim_id, 1)
    workspace.machine_generation = 2
    workspace.machine_ref = "machine-2"
    workspace.provisioning_phase = WorkspaceProvisioningPhase.IDLE
    workspace.ready_generation = 2
    workspace.ready_start_epoch = workspace.runtime_start_epoch
    workspace.runtime_last_seen_at = timezone.now()
    workspace.save(
        update_fields=[
            "machine_generation",
            "machine_ref",
            "provisioning_phase",
            "ready_generation",
            "ready_start_epoch",
            "runtime_last_seen_at",
            "updated_at",
        ]
    )
    new_context = RuntimeContext(workspace.id, 2, issued.credential.id)
    with pytest.raises(RuntimeIdempotencyConflictError):
        claim_next_execution(new_context, claim_id, 1)
    assert claim is not None


def test_expired_claim_replay_returns_no_stale_lease(runtime_setup):
    _workspace, _profile, _execution, issued = runtime_setup
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 1)
    Lease.objects.filter(pk=claim.lease_id).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert claim_next_execution(context, claim.claim_id, 1) is None


@pytest.mark.parametrize("lease_state", [LeaseState.ACTIVE, LeaseState.STOPPING])
def test_expired_pre_dispatch_lease_requeues_before_next_claim(
    runtime_setup, lease_state
):
    _workspace, _profile, execution, issued = runtime_setup
    context = authenticate_runtime_token(issued.raw_token)
    first = claim_next_execution(context, uuid4(), 1)
    Lease.objects.filter(pk=first.lease_id).update(
        expires_at=timezone.now() - timedelta(seconds=1),
        state=lease_state,
    )

    replacement = claim_next_execution(context, uuid4(), 1)

    assert replacement is not None
    assert replacement.attempt_id != first.attempt_id
    assert replacement.execution_id == execution.id
    assert Attempt.objects.get(pk=first.attempt_id).status == "unknown"
    assert Lease.objects.get(pk=first.lease_id).state == LeaseState.RELEASED
    assert Attempt.objects.filter(execution_id=execution.id).count() == 2


def test_expired_cleanup_lease_is_fenced_without_requeue(runtime_setup):
    _workspace, profile, execution, issued = runtime_setup
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 1)
    profile.lifecycle_state = RuntimeProfileLifecycleState.CLEANUP_PENDING
    profile.save(update_fields=["lifecycle_state", "updated_at"])
    Lease.objects.filter(pk=claim.lease_id).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    assert claim_next_execution(context, uuid4(), 1) is None

    assert Attempt.objects.get(pk=claim.attempt_id).status == "unknown"
    assert Lease.objects.get(pk=claim.lease_id).state == LeaseState.FENCED
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.FAILED
    assert not ExecutionEvent.objects.filter(attempt_id=claim.attempt_id).exists()


def test_expired_dispatched_lease_fails_once_without_successor(runtime_setup):
    _workspace, _profile, execution, issued = runtime_setup
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 1)
    append_runtime_event(
        context,
        claim.attempt_id,
        claim.lease_token,
        uuid4(),
        claim.stream_id,
        1,
        "execution.dispatched",
        {"status": "dispatched"},
    )
    Lease.objects.filter(pk=claim.lease_id).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    assert claim_next_execution(context, uuid4(), 1) is None
    assert claim_next_execution(context, uuid4(), 1) is None

    assert Attempt.objects.get(pk=claim.attempt_id).status == "unknown"
    assert Lease.objects.get(pk=claim.lease_id).state == LeaseState.RELEASED
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.FAILED
    events = ExecutionEvent.objects.filter(attempt_id=claim.attempt_id).order_by(
        "sequence"
    )
    assert list(events.values_list("event_type", flat=True)) == [
        "execution.dispatched",
        "execution.failed",
    ]
    failure = events.get(event_type="execution.failed")
    assert failure.payload == {"code": "lease_expired", "retryable": False}


def test_expired_failure_event_persistence_rolls_back_reconciliation(runtime_setup):
    _workspace, _profile, execution, issued = runtime_setup
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 1)
    append_runtime_event(
        context,
        claim.attempt_id,
        claim.lease_token,
        uuid4(),
        claim.stream_id,
        1,
        "execution.dispatched",
        {"status": "dispatched"},
    )
    Lease.objects.filter(pk=claim.lease_id).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    with (
        patch(
            "runtime.services.events._enqueue_event_delivery",
            side_effect=RuntimeValidationError("synthetic outbox failure"),
        ),
        pytest.raises(RuntimeValidationError, match="synthetic outbox failure"),
    ):
        claim_next_execution(context, uuid4(), 1)

    assert Lease.objects.get(pk=claim.lease_id).state == LeaseState.ACTIVE
    assert Attempt.objects.get(pk=claim.attempt_id).status == "running"
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.RUNNING
    assert not ExecutionEvent.objects.filter(
        attempt_id=claim.attempt_id, event_type="execution.failed"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_claimers_create_one_replacement_after_expiry(runtime_setup):
    _workspace, _profile, execution, issued = runtime_setup
    context = authenticate_runtime_token(issued.raw_token)
    stale = claim_next_execution(context, uuid4(), 1)
    Lease.objects.filter(pk=stale.lease_id).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    barrier = Barrier(2)
    outcomes = [None, None]
    errors = [None, None]

    def claim(index):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            outcomes[index] = claim_next_execution(context, uuid4(), 1)
        except (OperationalError, RuntimeDomainError, TimeoutError) as exc:
            errors[index] = exc
        finally:
            close_old_connections()

    threads = [Thread(target=claim, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == [None, None], errors
    assert sum(outcome is not None for outcome in outcomes) == 1
    assert Attempt.objects.filter(execution_id=execution.id).count() == 2
    assert (
        Lease.objects.filter(
            profile_id=execution.profile_id,
            state__in=(LeaseState.ACTIVE, LeaseState.STOPPING),
        ).count()
        == 1
    )


def test_non_retryable_failure_is_failed_not_succeeded(runtime_setup):
    _workspace, _profile, execution, issued = runtime_setup
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 1)
    receipt = fail_attempt(
        context,
        claim.attempt_id,
        claim.lease_token,
        {"code": "bad_input", "retryable": False, "receipt": {"code": "bad_input"}},
    )
    assert receipt.status == "failed"
    assert Execution.objects.get(pk=execution.id).status == ExecutionStatus.FAILED


def test_expired_active_lease_cannot_complete_or_bind(runtime_setup):
    _workspace, _profile, _execution, issued = runtime_setup
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 1)
    lease = Lease.objects.get(pk=claim.lease_id)
    lease.expires_at = timezone.now() - timedelta(seconds=1)
    lease.save(update_fields=["expires_at", "updated_at"])
    with pytest.raises(RuntimeLeaseConflictError):
        complete_attempt(
            context,
            claim.attempt_id,
            claim.lease_token,
            {"code": "late"},
        )
    with pytest.raises(RuntimeLeaseConflictError):
        update_session_binding(
            context,
            claim.attempt_id,
            claim.lease_token,
            "cloud-conversation",
            None,
            "hermes-session",
        )


def test_internal_api_claim_and_event(runtime_setup):
    _workspace, _profile, _execution, issued = runtime_setup
    client = Client()
    claim_id = str(uuid4())
    response = client.post(
        "/api/v1/runtime/claims",
        data={"claim_id": claim_id, "available_slots": 2},
        content_type="application/json",
        headers={"Authorization": f"Bearer {issued.raw_token}"},
    )
    assert response.status_code == 200, response.content
    claim = response.json()
    event_payload = {
        "event_id": str(uuid4()),
        "stream_id": claim["stream_id"],
        "sequence": 1,
        "type": "message.delta",
        "payload": {"text": "hello"},
    }
    event = client.post(
        f"/api/v1/runtime/attempts/{claim['attempt_id']}/events",
        data=event_payload,
        content_type="application/json",
        headers={
            "Authorization": f"Bearer {issued.raw_token}",
            "X-Foundry-Lease-Token": claim["lease_token"],
        },
    )
    assert event.status_code == 202, event.content
    session = client.put(
        f"/api/v1/runtime/attempts/{claim['attempt_id']}/session-binding",
        data={
            "cloud_conversation_ref": "cloud-conversation",
            "expected_session_id": None,
            "effective_session_id": "hermes-session",
        },
        content_type="application/json",
        headers={
            "Authorization": f"Bearer {issued.raw_token}",
            "X-Foundry-Lease-Token": claim["lease_token"],
        },
    )
    assert session.status_code == 200, session.content
    complete = client.post(
        f"/api/v1/runtime/attempts/{claim['attempt_id']}/complete",
        data={
            "event_id": str(uuid4()),
            "stream_id": claim["stream_id"],
            "sequence": 2,
            "payload": {"run_id": "run-1", "status": "completed"},
            "receipt": {"code": "ok"},
        },
        content_type="application/json",
        headers={
            "Authorization": f"Bearer {issued.raw_token}",
            "X-Foundry-Lease-Token": claim["lease_token"],
        },
    )
    assert complete.status_code == 200, complete.content
    replay = client.post(
        f"/api/v1/runtime/attempts/{claim['attempt_id']}/events",
        data=event_payload,
        content_type="application/json",
        headers={
            "Authorization": f"Bearer {issued.raw_token}",
            "X-Foundry-Lease-Token": claim["lease_token"],
        },
    )
    assert replay.status_code == 202, replay.content


def test_internal_api_validation_error_is_stable(runtime_setup):
    _workspace, _profile, _execution, issued = runtime_setup
    response = Client().post(
        "/api/v1/runtime/claims",
        data={"available_slots": 2},
        content_type="application/json",
        headers={"Authorization": f"Bearer {issued.raw_token}"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"
