from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.test import Client
from django.utils import timezone

from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeFencedError,
    RuntimeIdempotencyConflictError,
    RuntimeLeaseConflictError,
    RuntimeNotReadyError,
)
from runtime.models import (
    Execution,
    ExecutionStatus,
    Lease,
    LeaseState,
    RuntimeProfile,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.services.attempts import complete_attempt, fail_attempt
from runtime.services.claims import claim_next_execution
from runtime.services.leases import (
    acknowledge_stopped,
    confirm_machine_stopped_and_fence,
    renew_lease,
)
from runtime.services.runtime_auth import (
    RuntimeContext,
    authenticate_runtime_token,
    issue_runtime_credential,
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
    )


@pytest.fixture
def runtime_setup(ready_workspace):
    profile = RuntimeProfile.objects.create(
        workspace=ready_workspace,
        ally_ref="ally",
        hermes_profile_key="ally",
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
    assert complete_attempt(
        context,
        first.attempt_id,
        first.lease_token,
        {"code": "ok", "summary_ref": "local"},
    ) == terminal
    with pytest.raises(RuntimeIdempotencyConflictError):
        complete_attempt(
            context,
            first.attempt_id,
            first.lease_token,
            {"code": "different"},
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
    assert acknowledge_stopped(context, claim.attempt_id, claim.lease_token, "lost") == receipt


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
    assert update_session_binding(
        context,
        claim.attempt_id,
        claim.lease_token,
        "cloud-conversation",
        None,
        "hermes-session-1",
    ) == first
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
    complete_attempt(context, first_claim.attempt_id, first_claim.lease_token, {"code": "ok"})
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
    workspace.save(
        update_fields=[
            "machine_generation",
            "machine_ref",
            "provisioning_phase",
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
        "type": "delta",
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
    complete = client.post(
        f"/api/v1/runtime/attempts/{claim['attempt_id']}/complete",
        data={"receipt": {"code": "ok"}},
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
