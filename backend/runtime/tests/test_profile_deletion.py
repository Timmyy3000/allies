from datetime import timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from django.test import Client
from django.utils import timezone

from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeFencedError,
    RuntimeIdempotencyConflictError,
)
from runtime.models import (
    Attempt,
    ConversationBinding,
    DeletedProfile,
    Execution,
    ExecutionEvent,
    Lease,
    LeaseState,
    PublicationIntent,
    RoutineApprovalAction,
    RoutineCommandReceipt,
    RoutineExecution,
    RuntimeProfile,
    Workspace,
)
from runtime.services.executions import create_execution
from runtime.services.profile_deletion import coordinate_profile_deletion
from runtime.services.profiles import (
    ProfileSeed,
    accept_cleanup_receipt,
    ensure_runtime_profile,
)
from runtime.services.runtime_auth import (
    authenticate_runtime_token,
    issue_runtime_credential,
)


@pytest.fixture
def target(db):
    external_id, ally_id, binding_id = uuid4(), uuid4(), uuid4()
    workspace = Workspace.objects.create(
        tenant_ref=str(external_id),
        machine_generation=1,
        fly_app_ref="app",
        volume_ref="volume",
        machine_ref="machine",
        ready_generation=1,
        ready_start_epoch=0,
        ready_boot_id=uuid4(),
        ready_at=timezone.now(),
        runtime_last_seen_at=timezone.now(),
    )
    seed = ProfileSeed(
        personality="Patient",
        provider="test",
        model="test",
        first_chat_instruction="Hello",
        credential_refs={},
    )
    profile_id = uuid5(
        uuid5(NAMESPACE_URL, "allies-foundry-profile-v1"), str(binding_id)
    )
    ensure_runtime_profile(workspace.id, profile_id, str(ally_id), seed)
    profile = RuntimeProfile.objects.get(pk=profile_id)
    context = authenticate_runtime_token(
        issue_runtime_credential(workspace.id).raw_token
    )
    command = {
        "workspace_id": external_id,
        "ally_id": ally_id,
        "binding_id": binding_id,
        "operation_id": uuid4(),
    }
    return workspace, profile, seed, context, command


def close_profile(target, **changes):
    workspace, profile, _, context, _ = target
    profile.refresh_from_db()
    proof = {
        "result_code": "deprovisioned",
        "deleted": True,
        "active_lease_count": 0,
        "attempt_id": profile.cleanup_attempt_id,
        "machine_generation": workspace.machine_generation,
        "runtime_start_epoch": workspace.runtime_start_epoch,
        "runtime_boot_id": workspace.ready_boot_id,
        "hermes_instance_id": uuid4(),
        "quiescence": {
            "state": "quiesced",
            "safe_error_code": "",
            "active_runs": 0,
            "active_profile_io": 0,
            "open_profile_stores": 0,
            "owned_children": 0,
        },
    }
    proof.update(changes)
    return accept_cleanup_receipt(
        context,
        profile.id,
        profile.cleanup_operation_id,
        profile.lifecycle_epoch,
        profile.cleanup_request_digest,
        **proof,
    )


def test_deletion_fences_admission_and_replays_without_changing_attempt(target):
    workspace, profile, seed, _, command = target
    first = coordinate_profile_deletion(**command)
    profile.refresh_from_db()
    expiry, digest = profile.cleanup_expires_at, profile.cleanup_request_digest
    assert first == coordinate_profile_deletion(**command)
    profile.refresh_from_db()
    assert (expiry, digest) == (
        profile.cleanup_expires_at,
        profile.cleanup_request_digest,
    )
    with pytest.raises(RuntimeFencedError):
        ensure_runtime_profile(workspace.id, profile.id, profile.ally_ref, seed)
    with pytest.raises(RuntimeConflictError):
        create_execution(workspace.id, profile.id, "late", {"message": "late"})
    with pytest.raises(RuntimeIdempotencyConflictError):
        coordinate_profile_deletion(**{**command, "operation_id": uuid4()})


@pytest.mark.parametrize(
    "changes",
    [
        {"attempt_id": uuid4()},
        {"runtime_boot_id": uuid4()},
        {"machine_generation": 2},
        {"runtime_start_epoch": 1},
        {"hermes_instance_id": None},
        {"quiescence": None},
        {
            "quiescence": {
                "state": "quiesced",
                "safe_error_code": "",
                "active_runs": 0,
                "active_profile_io": 1,
                "open_profile_stores": 0,
                "owned_children": 0,
            }
        },
    ],
)
def test_stale_or_incomplete_closure_cannot_complete(target, changes):
    coordinate_profile_deletion(**target[-1])
    with pytest.raises((RuntimeConflictError, RuntimeFencedError)):
        close_profile(target, **changes)
    assert not DeletedProfile.objects.exists()
    assert coordinate_profile_deletion(**target[-1])["state"] == "pending"


def test_expired_attempt_requires_explicit_resume_and_rejects_old_receipt(target):
    _, profile, _, _, command = target
    first = coordinate_profile_deletion(**command)
    RuntimeProfile.objects.filter(pk=profile.id).update(
        cleanup_expires_at=timezone.now() - timedelta(seconds=1)
    )
    with pytest.raises(RuntimeFencedError):
        close_profile(target)
    assert coordinate_profile_deletion(**command)["state"] == "repair_required"
    resumed = coordinate_profile_deletion(
        **command, expected_attempt_id=UUID(first["attempt_id"])
    )
    assert resumed["attempt_id"] != first["attempt_id"]
    assert resumed == coordinate_profile_deletion(
        **command, expected_attempt_id=UUID(first["attempt_id"])
    )
    with pytest.raises(RuntimeFencedError):
        close_profile(target, attempt_id=UUID(first["attempt_id"]))


def test_complete_purges_target_graph_keeps_sibling_and_rejects_recreation(target):
    workspace, profile, seed, _, command = target
    sibling_id = uuid4()
    ensure_runtime_profile(workspace.id, sibling_id, str(uuid4()), seed)
    sibling = RuntimeProfile.objects.get(pk=sibling_id)
    execution = Execution.objects.create(
        workspace=workspace,
        profile=profile,
        idempotency_key="target",
        input_payload={"message": "erase"},
    )
    attempt = Attempt.objects.create(
        execution=execution, number=1, machine_generation=1
    )
    Lease.objects.create(
        profile=profile,
        attempt=attempt,
        state=LeaseState.RELEASED,
        token_digest="a" * 64,
        machine_generation=1,
        expires_at=timezone.now(),
    )
    ConversationBinding.objects.create(
        profile=profile,
        cloud_conversation_ref=str(uuid4()),
        hermes_session_id="session",
    )
    ExecutionEvent.objects.create(
        attempt=attempt,
        event_id=uuid4(),
        sequence=1,
        event_type="text",
        payload={"text": "erase"},
    )
    PublicationIntent.objects.create(
        workspace=workspace,
        profile=profile,
        execution=execution,
        source_attempt=attempt,
        cloud_binding_id=command["binding_id"],
        cloud_message_id=uuid4(),
        tool_call_digest="b" * 64,
        request_digest="c" * 64,
    )
    RoutineCommandReceipt.objects.create(
        workspace=workspace,
        command_id=uuid4(),
        idempotency_key=uuid4(),
        kind="routine.dispatch.receipt",
        fingerprint="x",
        response={"scope": {"ally_id": profile.ally_ref}, "text": "erase"},
    )
    routine = RoutineExecution.objects.create(
        workspace=workspace,
        profile=profile,
        execution=execution,
        current_attempt=attempt,
        routine_id=uuid4(),
        routine_revision=1,
        schedule_generation=1,
        occurrence_id=uuid4(),
        run_id=uuid4(),
        scheduled_at=timezone.now(),
        main_conversation_id=uuid4(),
        run_conversation_id=uuid4(),
        cloud_binding_id=command["binding_id"],
        owner_user_id=uuid4(),
        ally_id=command["ally_id"],
        title_snapshot="erase",
        execution_prompt="erase",
    )
    RoutineApprovalAction.objects.create(
        routine_execution=routine,
        attempt=attempt,
        approval_request_id=uuid4(),
        action_attempt_id=uuid4(),
        generation=1,
        action_digest="d" * 64,
        provider_idempotency_key="erase",
        created_at=timezone.now(),
        expires_at=timezone.now(),
    )
    RoutineCommandReceipt.objects.create(
        workspace=workspace,
        command_id=uuid4(),
        idempotency_key=uuid4(),
        kind="routine.cancel.receipt",
        fingerprint="x",
        response={"routine_execution_id": str(routine.id), "text": "erase"},
    )
    sibling_execution = Execution.objects.create(
        workspace=workspace,
        profile=sibling,
        idempotency_key="sibling",
        input_payload={"message": "keep"},
    )
    coordinate_profile_deletion(**command)
    close_profile(target)
    complete = coordinate_profile_deletion(**command)
    assert complete["state"] == "complete" and complete["receipt_id"]
    assert complete == coordinate_profile_deletion(**command)
    assert not RuntimeProfile.objects.filter(pk=profile.id).exists()
    assert not Execution.objects.filter(pk=execution.id).exists()
    assert not RoutineCommandReceipt.objects.exists()
    assert Execution.objects.get(pk=sibling_execution.id).input_payload == {
        "message": "keep"
    }
    assert set(DeletedProfile.objects.values().get()) == {"profile_id", "workspace_id"}
    with pytest.raises(RuntimeFencedError):
        ensure_runtime_profile(workspace.id, profile.id, profile.ally_ref, seed)
    workspace.refresh_from_db()
    assert workspace.machine_ref == "machine" and workspace.volume_ref == "volume"


def test_absent_profile_still_requires_runtime_absence_proof(target):
    _, profile, _, _, command = target
    profile.delete()
    result = coordinate_profile_deletion(**command)
    assert result["state"] == "pending"
    assert not DeletedProfile.objects.exists()


def test_identity_mismatch_does_not_fence_a_sibling(target):
    _, profile, _, _, command = target
    with pytest.raises(RuntimeConflictError):
        coordinate_profile_deletion(**{**command, "ally_id": uuid4()})
    profile.refresh_from_db()
    assert not profile.cleanup_requires_quiescence


def test_internal_api_requires_service_auth_and_strict_body(target, settings):
    settings.ALLIES_CLOUD_SERVICE_TOKEN = "test-service-token"
    payload = {"version": 1, **{key: str(value) for key, value in target[-1].items()}}
    url = "/api/v1/internal/profile-deletion"
    client = Client()
    assert (
        client.post(url, data=payload, content_type="application/json").status_code
        == 401
    )
    headers = {"Authorization": "Bearer test-service-token"}
    assert (
        client.post(
            url,
            data={**payload, "unknown": True},
            content_type="application/json",
            headers=headers,
        ).status_code
        == 422
    )
    response = client.post(
        url, data=payload, content_type="application/json", headers=headers
    )
    assert response.status_code == 200
    assert response.json()["state"] == "pending"
