from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import connection, connections, transaction
from django.utils import timezone

from runtime.contracts import (
    FINGERPRINT_PREFIX,
    ApprovalDecisionCommand,
    canonical_fingerprint,
)
from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeFencedError,
    RuntimeLeaseConflictError,
)
from runtime.models import (
    ApprovalRequest,
    ApprovalRequestStatus,
    ConversationBinding,
    Execution,
    Lease,
    LeaseState,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.services.approvals import (
    apply_approval_resolution,
    record_approval_decision,
    record_approval_request_from_event,
)
from runtime.services.attempts import fail_attempt
from runtime.services.claims import claim_next_execution
from runtime.services.leases import acknowledge_stopped
from runtime.services.profiles import _fence_profile_leases
from runtime.services.runtime_auth import (
    authenticate_runtime_token,
    issue_runtime_credential,
)


@pytest.fixture
def approval_setup(db):
    cloud_workspace_id = uuid4()
    cloud_ally_id = uuid4()
    cloud_conversation_id = uuid4()
    cloud_message_id = uuid4()
    cloud_binding_id = uuid4()
    workspace = Workspace.objects.create(
        tenant_ref=str(cloud_workspace_id),
        fly_app_ref="app",
        volume_ref="volume",
        machine_ref="machine",
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
    ConversationBinding.objects.create(
        profile=profile,
        cloud_conversation_ref=str(cloud_conversation_id),
    )
    execution = Execution.objects.create(
        workspace=workspace,
        profile=profile,
        idempotency_key=str(uuid4()),
        input_payload={
            "message": "connect",
            "cloud_conversation_ref": str(cloud_conversation_id),
        },
        command_id=uuid4(),
        command_fingerprint=FINGERPRINT_PREFIX + "0" * 64,
        cloud_workspace_id=cloud_workspace_id,
        cloud_ally_id=cloud_ally_id,
        cloud_conversation_id=cloud_conversation_id,
        cloud_message_id=cloud_message_id,
        cloud_binding_id=cloud_binding_id,
        conversation_turn_ordinal=1,
        source_kind="conversation_message",
    )
    issued = issue_runtime_credential(workspace.id, "approval-runtime-token")
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 1)
    assert claim is not None

    def new_request():
        attempt = Execution.objects.get(pk=execution.id).attempts.get()
        attempt = (
            type(attempt)
            .objects.select_related("execution__workspace", "execution__profile")
            .get(pk=attempt.id)
        )
        request_id = uuid4()
        expires_at = timezone.now() + timedelta(seconds=120)
        with transaction.atomic():
            request = record_approval_request_from_event(
                attempt,
                {
                    "approval_request_id": str(request_id),
                    "action_kind": "plugin_tool",
                    "action_label": "Connect Nabu",
                    "action_preview": "Connect to the selected Nabu space",
                    "expires_at": expires_at.isoformat(),
                },
            )
        return request

    def command(request, *, decision="approve", cloud_ally=None):
        now = timezone.now()
        command_data = {
            "schema_version": "v1",
            "kind": "approval.decision",
            "producer": "cloud",
            "service_identity": "cloud-service",
            "command_id": uuid4(),
            "idempotency_key": uuid4(),
            "scope": {
                "kind": "workspace",
                "cloud_workspace_id": cloud_workspace_id,
            },
            "cloud": {
                "ally_id": cloud_ally or cloud_ally_id,
                "conversation_id": cloud_conversation_id,
                "message_id": cloud_message_id,
                "cloud_binding_id": cloud_binding_id,
            },
            "foundry": {
                "execution_id": execution.id,
                "attempt_id": request.attempt_id,
                "generation": 1,
            },
            "approval_request_id": request.id,
            "decision": decision,
            "decided_at": now,
            "acknowledgement_deadline_at": now + timedelta(seconds=30),
            "issued_at": now,
            "deadline_at": now + timedelta(seconds=10),
            "fingerprint": FINGERPRINT_PREFIX + "0" * 64,
        }
        draft = ApprovalDecisionCommand.model_validate(command_data)
        return draft.model_copy(
            update={
                "fingerprint": canonical_fingerprint(
                    draft.model_dump(
                        mode="json",
                        exclude={"issued_at", "deadline_at", "fingerprint"},
                    )
                )
            }
        )

    return SimpleNamespace(
        workspace=workspace,
        execution=execution,
        claim=claim,
        context=context,
        new_request=new_request,
        command=command,
    )


def test_first_decision_is_idempotent_and_full_cloud_binding_is_required(
    approval_setup,
):
    request = approval_setup.new_request()
    command = approval_setup.command(request)

    accepted = record_approval_decision(command)
    duplicate = record_approval_decision(command)
    assert accepted.status == "accepted"
    assert duplicate.status == "duplicate"

    conflicting = approval_setup.command(request, decision="reject")
    with pytest.raises(RuntimeConflictError):
        record_approval_decision(conflicting)

    foreign = approval_setup.command(request, cloud_ally=uuid4())
    with pytest.raises(RuntimeConflictError):
        record_approval_decision(foreign)


def test_stale_or_released_approval_lease_cannot_record_a_new_decision(approval_setup):
    stale_request = approval_setup.new_request()
    approval_setup.workspace.machine_generation = 2
    approval_setup.workspace.save(update_fields=["machine_generation", "updated_at"])
    with pytest.raises((RuntimeFencedError, RuntimeLeaseConflictError)):
        record_approval_decision(approval_setup.command(stale_request))

    approval_setup.workspace.machine_generation = 1
    approval_setup.workspace.save(update_fields=["machine_generation", "updated_at"])
    lease = Lease.objects.get(attempt_id=stale_request.attempt_id)
    lease.state = LeaseState.RELEASED
    lease.save(update_fields=["state", "updated_at"])
    released_request = approval_setup.new_request()
    with pytest.raises(RuntimeLeaseConflictError):
        record_approval_decision(approval_setup.command(released_request))


def test_late_matching_resolution_preserves_outcome_unknown(approval_setup):
    request = approval_setup.new_request()
    command = approval_setup.command(request)
    record_approval_decision(command)
    ApprovalRequest.objects.filter(pk=request.id).update(
        acknowledgement_deadline_at=timezone.now() - timedelta(seconds=1)
    )

    resolved = apply_approval_resolution(request.attempt_id, request.id, "approved")

    assert resolved.status == ApprovalRequestStatus.OUTCOME_UNKNOWN
    assert resolved.outcome is None


def test_expired_decision_command_cannot_record_a_choice(approval_setup):
    request = approval_setup.new_request()
    now = timezone.now()
    command = approval_setup.command(request)
    command = command.model_copy(
        update={
            "issued_at": now - timedelta(seconds=60),
            "decided_at": now - timedelta(seconds=31),
            "acknowledgement_deadline_at": now - timedelta(seconds=1),
            "deadline_at": now - timedelta(seconds=2),
        }
    )
    command = command.model_copy(
        update={
            "fingerprint": canonical_fingerprint(
                command.model_dump(
                    mode="json",
                    exclude={"issued_at", "deadline_at", "fingerprint"},
                )
            )
        }
    )

    with pytest.raises(RuntimeConflictError, match="window has expired"):
        record_approval_decision(command)


def test_future_dated_decision_cannot_record_a_choice(approval_setup):
    request = approval_setup.new_request()
    now = timezone.now()
    command = approval_setup.command(request)
    command = command.model_copy(
        update={
            "issued_at": now,
            "decided_at": now + timedelta(seconds=60),
            "acknowledgement_deadline_at": now + timedelta(seconds=90),
            "deadline_at": now + timedelta(seconds=10),
        }
    )
    command = command.model_copy(
        update={
            "fingerprint": canonical_fingerprint(
                command.model_dump(
                    mode="json",
                    exclude={"issued_at", "deadline_at", "fingerprint"},
                )
            )
        }
    )

    with pytest.raises(RuntimeConflictError, match="dated in the future"):
        record_approval_decision(command)


def test_decision_deadline_may_extend_acknowledgement_past_consent_expiry(
    approval_setup,
):
    request = approval_setup.new_request()
    now = timezone.now()
    request.expires_at = now + timedelta(seconds=10)
    request.save(update_fields=["expires_at", "updated_at"])
    command = approval_setup.command(request)
    command = command.model_copy(
        update={
            "issued_at": now,
            "decided_at": now,
            "deadline_at": request.expires_at - timedelta(seconds=1),
            "acknowledgement_deadline_at": now + timedelta(seconds=30),
        }
    )
    command = command.model_copy(
        update={
            "fingerprint": canonical_fingerprint(
                command.model_dump(
                    mode="json",
                    exclude={"issued_at", "deadline_at", "fingerprint"},
                )
            )
        }
    )

    assert record_approval_decision(command).status == "accepted"


def test_terminal_failure_cancels_live_approval_and_rejects_late_decision(
    approval_setup,
):
    request = approval_setup.new_request()

    fail_attempt(
        approval_setup.context,
        request.attempt_id,
        approval_setup.claim.lease_token,
        {"code": "worker_failed"},
    )

    request.refresh_from_db()
    assert request.status == ApprovalRequestStatus.CANCELLED
    assert request.outcome == "cancelled"
    with pytest.raises(RuntimeConflictError, match="already been resolved"):
        record_approval_decision(approval_setup.command(request))


def test_stopped_attempt_cancels_live_approval(approval_setup):
    request = approval_setup.new_request()

    acknowledge_stopped(
        approval_setup.context,
        request.attempt_id,
        approval_setup.claim.lease_token,
        "operator_stop",
    )

    request.refresh_from_db()
    assert request.status == ApprovalRequestStatus.CANCELLED
    assert request.outcome == "cancelled"


def test_fenced_attempt_cancels_live_approval(approval_setup):
    request = approval_setup.new_request()

    with transaction.atomic():
        _fence_profile_leases(approval_setup.workspace.profiles.get().id)

    request.refresh_from_db()
    assert request.status == ApprovalRequestStatus.CANCELLED
    assert request.outcome == "cancelled"


def test_cancellation_preserves_acknowledgement_outcome_unknown(approval_setup):
    request = approval_setup.new_request()
    record_approval_decision(approval_setup.command(request))
    ApprovalRequest.objects.filter(pk=request.id).update(
        acknowledgement_deadline_at=timezone.now() - timedelta(seconds=1)
    )

    fail_attempt(
        approval_setup.context,
        request.attempt_id,
        approval_setup.claim.lease_token,
        {"code": "worker_failed"},
    )

    request.refresh_from_db()
    assert request.status == ApprovalRequestStatus.OUTCOME_UNKNOWN
    assert request.outcome is None


@pytest.mark.parametrize("transition", ["fail", "stop", "fence"])
def test_recorded_approval_is_unknown_when_attempt_leaves_before_ack(
    approval_setup, transition
):
    request = approval_setup.new_request()
    record_approval_decision(approval_setup.command(request))

    if transition == "fail":
        fail_attempt(
            approval_setup.context,
            request.attempt_id,
            approval_setup.claim.lease_token,
            {"code": "worker_failed"},
        )
    elif transition == "stop":
        acknowledge_stopped(
            approval_setup.context,
            request.attempt_id,
            approval_setup.claim.lease_token,
            "operator_stop",
        )
    else:
        with transaction.atomic():
            _fence_profile_leases(approval_setup.workspace.profiles.get().id)

    request.refresh_from_db()
    assert request.status == ApprovalRequestStatus.OUTCOME_UNKNOWN
    assert request.decision == "approve"
    assert request.outcome is None


@pytest.mark.django_db(transaction=True)
def test_concurrent_first_decision_wins_on_postgresql(approval_setup):
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row-lock semantics")
    request = approval_setup.new_request()
    approve = approval_setup.command(request, decision="approve")
    reject = approval_setup.command(request, decision="reject")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda command: _decision_result(command),
                (approve, reject),
            )
        )

    assert sorted(results) == ["accepted", "conflict"]


def _decision_result(command):
    try:
        return record_approval_decision(command).status
    except RuntimeConflictError:
        return "conflict"
    finally:
        connections.close_all()
