from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from runtime.models import (
    Attempt,
    ConversationBinding,
    Execution,
    ExecutionStatus,
    Lease,
    LeaseState,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.services.claims import claim_next_execution
from runtime.services.runtime_auth import (
    authenticate_runtime_token,
    issue_runtime_credential,
)
from runtime.services.validation import digest_payload


@pytest.fixture
def profile_records(db):
    workspace = Workspace.objects.create(
        tenant_ref=f"routine-tenant-{uuid4().hex}",
        fly_app_ref="synthetic-app",
        volume_ref="synthetic-volume",
        machine_ref="synthetic-machine",
        machine_generation=1,
        provisioning_phase=WorkspaceProvisioningPhase.IDLE,
        ready_generation=1,
        ready_start_epoch=0,
        ready_boot_id=uuid4(),
        ready_at=timezone.now(),
        runtime_last_seen_at=timezone.now(),
    )
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="synthetic-ally",
        hermes_profile_key=f"ally-v1-{uuid4().hex}",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=1,
    )
    binding = ConversationBinding.objects.create(
        profile=profile,
        cloud_conversation_ref="synthetic-main-conversation",
        hermes_session_id=None,
    )
    return workspace, profile, binding


def _queued_execution(workspace, profile, sequence: int) -> Execution:
    payload = {
        "kind": "routine_constraint_probe",
        "cloud_conversation_ref": "synthetic-main-conversation",
        "sequence": sequence,
    }
    return Execution.objects.create(
        workspace=workspace,
        profile=profile,
        idempotency_key=f"routine-constraint-{sequence}",
        input_payload=payload,
        payload_digest=digest_payload(payload),
        status=ExecutionStatus.QUEUED,
    )


def test_profile_has_one_conversation_binding(profile_records):
    _workspace, profile, _binding = profile_records

    with pytest.raises(IntegrityError), transaction.atomic():
        ConversationBinding.objects.create(
            profile=profile,
            cloud_conversation_ref="synthetic-routine-conversation",
        )

    assert ConversationBinding.objects.filter(profile=profile).count() == 1


def test_profile_unresolved_lease_is_unique(profile_records):
    workspace, profile, binding = profile_records
    execution = _queued_execution(workspace, profile, 1)
    credential = issue_runtime_credential(workspace.id, "routine-constraint-token")
    context = authenticate_runtime_token(credential.raw_token)
    claim = claim_next_execution(context, uuid4(), 1)
    assert claim is not None

    other_execution = _queued_execution(workspace, profile, 2)
    other_attempt = Attempt.objects.create(
        execution=other_execution,
        number=1,
        machine_generation=workspace.machine_generation,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Lease.objects.create(
            attempt=other_attempt,
            profile=profile,
            token_digest=sha256(b"second-lease").hexdigest(),
            claim_id=uuid4(),
            expires_at=timezone.now() + timedelta(seconds=60),
            machine_generation=workspace.machine_generation,
            state=LeaseState.ACTIVE,
        )

    assert Lease.objects.filter(profile=profile, state=LeaseState.ACTIVE).count() == 1
    assert binding.cloud_conversation_ref == claim.conversation_id
    execution.refresh_from_db()
    assert execution.status == ExecutionStatus.RUNNING


def test_claim_skips_second_execution_when_profile_lease_is_occupied(profile_records):
    workspace, profile, _binding = profile_records
    _queued_execution(workspace, profile, 1)
    second = _queued_execution(workspace, profile, 2)
    credential = issue_runtime_credential(workspace.id, "routine-claim-token")
    context = authenticate_runtime_token(credential.raw_token)

    first_claim = claim_next_execution(context, uuid4(), 2)
    second_claim = claim_next_execution(context, uuid4(), 2)

    assert first_claim is not None
    assert second_claim is None
    second.refresh_from_db()
    assert second.status == ExecutionStatus.QUEUED
