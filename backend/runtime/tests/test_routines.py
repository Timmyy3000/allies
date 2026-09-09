from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, local
from time import monotonic
from uuid import UUID, uuid4, uuid5

import pytest
from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.db.models.query import QuerySet
from django.test import Client
from django.utils import timezone as django_timezone

from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeFencedError,
    RuntimeLeaseConflictError,
    RuntimeNotReadyError,
)
from runtime.models import (
    Attempt,
    AttemptStatus,
    ConversationBinding,
    EventDeliveryState,
    Execution,
    ExecutionEvent,
    ExecutionEventDelivery,
    ExecutionStatus,
    Lease,
    LeaseState,
    RoutineApprovalAction,
    RoutineApprovalStatus,
    RoutineExecution,
    RoutineLeaseAcquisition,
    RoutineRunStatus,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.routine_contracts import (
    MAX_ROUTINE_EVENT_BYTES,
    RoutineApprovalDecision,
    RoutineApprovalRequested,
    RoutineDispatch,
    RoutineResult,
    parse_routine_message,
    routine_fingerprint,
)
from runtime.services.attempts import fail_attempt
from runtime.services.claims import claim_next_execution
from runtime.services.leases import acknowledge_stopped
from runtime.services.profiles import _fence_profile_leases
from runtime.services.routines import (
    PROFILE_ID_NAMESPACE,
    accept_routine_dispatch,
    append_runtime_routine_result,
    decide_routine_approval,
    disable_routine_admission,
    enable_routine_admission,
    expire_routine_approvals,
    request_routine_approval,
)
from runtime.services.runtime_auth import (
    authenticate_runtime_token,
    issue_runtime_credential,
)
from runtime.services.runtime_releases import current_runtime_release_digest
from runtime.services.sessions import bind_routine_session


@pytest.fixture
def routine_context(db, monkeypatch):
    applied_images = {
        "allies-runtime": "runtime@sha256:" + "a" * 64,
        "hermes": "hermes@sha256:" + "b" * 64,
    }
    workspace = Workspace.objects.create(
        tenant_ref="routine-tenant",
        fly_app_ref="routine-app",
        volume_ref="routine-volume",
        machine_ref="routine-machine",
        machine_generation=7,
        applied_images=applied_images,
        provisioning_phase=WorkspaceProvisioningPhase.IDLE,
        ready_generation=7,
        ready_start_epoch=0,
        ready_boot_id=uuid4(),
        runtime_last_seen_at=django_timezone.now(),
    )
    owner_id = uuid4()
    ally_id = uuid4()
    cloud_binding_id = uuid4()
    profile_id = uuid5(PROFILE_ID_NAMESPACE, str(cloud_binding_id))
    profile = RuntimeProfile.objects.create(
        id=profile_id,
        workspace=workspace,
        ally_ref=str(ally_id),
        hermes_profile_key="routine_ally",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=workspace.machine_generation,
        seed_payload={"model": "gpt-5.6-luna"},
    )
    main_conversation_id = uuid4()
    ConversationBinding.objects.create(
        profile=profile,
        cloud_conversation_ref=str(main_conversation_id),
    )
    release_digest = current_runtime_release_digest(workspace)
    assert release_digest is not None
    monkeypatch.setattr(
        settings,
        "ALLIES_RUNTIME_ROUTINE_RELEASE_DIGEST",
        release_digest,
        raising=False,
    )
    enable_routine_admission(
        workspace.id,
        release_digest=release_digest,
        machine_generation=workspace.machine_generation,
        runtime_start_epoch=workspace.runtime_start_epoch,
    )
    issued = issue_runtime_credential(workspace.id, "routine-runtime-secret")
    context = authenticate_runtime_token(issued.raw_token)
    return {
        "workspace": workspace,
        "profile": profile,
        "owner_id": owner_id,
        "ally_id": ally_id,
        "cloud_binding_id": cloud_binding_id,
        "main_conversation_id": main_conversation_id,
        "context": context,
        "release_digest": release_digest,
        "base": datetime(2026, 9, 9, 8, 0, tzinfo=UTC),
    }


def dispatch_payload(
    state, *, ordinal: int = 1, routine_id: UUID | None = None
) -> dict:
    base = state["base"] + timedelta(minutes=ordinal)
    routine_id = routine_id or uuid4()
    occurrence_id = uuid4()
    run_id = uuid4()
    run_conversation_id = uuid4()
    value = {
        "schema_version": "v1",
        "kind": "routine.dispatch",
        "producer": "cloud",
        "service_identity": "cloud-service",
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "routine_id": str(routine_id),
        "routine_revision": 4,
        "schedule_generation": 1,
        "occurrence_id": str(occurrence_id),
        "run_id": str(run_id),
        "schedule": {
            "kind": "recurring",
            "frequency": "daily",
            "local_time": "09:00:00",
            "timezone": "Europe/Berlin",
        },
        "scheduled_at": base.isoformat().replace("+00:00", "Z"),
        "delayed": False,
        "occurrence_disposition": "admitted",
        "main_conversation_id": str(state["main_conversation_id"]),
        "run_conversation_id": str(run_conversation_id),
        "cloud_binding_id": str(state["cloud_binding_id"]),
        "execution_prompt": f"Run routine {ordinal}.",
        "title_snapshot": f"Routine {ordinal}",
        "scope": {
            "kind": "workspace",
            "workspace_id": str(state["workspace"].id),
            "owner_user_id": str(state["owner_id"]),
            "ally_id": str(state["ally_id"]),
            "cloud_binding_id": str(state["cloud_binding_id"]),
        },
        "issued_at": base.isoformat().replace("+00:00", "Z"),
        "deadline_at": (base + timedelta(seconds=60)).isoformat().replace(
            "+00:00", "Z"
        ),
        "fingerprint": "",
    }
    value["fingerprint"] = routine_fingerprint(value)
    return value


def dispatch(
    state, *, ordinal: int = 1, routine_id: UUID | None = None
) -> tuple[RoutineDispatch, RoutineExecution]:
    command = RoutineDispatch.model_validate(
        dispatch_payload(state, ordinal=ordinal, routine_id=routine_id)
    )
    receipt = accept_routine_dispatch(command)
    return command, RoutineExecution.objects.get(execution_id=receipt.execution_id)


def test_routine_admission_requires_the_approved_current_release(routine_context):
    state = routine_context

    with pytest.raises(RuntimeNotReadyError):
        enable_routine_admission(
            state["workspace"].id,
            release_digest="sha256:" + "f" * 64,
            machine_generation=state["workspace"].machine_generation,
            runtime_start_epoch=state["workspace"].runtime_start_epoch,
        )


def test_disabling_admission_leaves_routines_queued_but_does_not_block_main(
    routine_context,
):
    state = routine_context
    _command, routine = dispatch(state)
    disable_routine_admission(state["workspace"].id)

    with pytest.raises(RuntimeNotReadyError):
        claim_next_execution(state["context"], uuid4(), 3)

    routine.refresh_from_db()
    assert routine.status == RoutineRunStatus.QUEUED
    main_execution = Execution.objects.create(
        workspace=state["workspace"],
        profile=state["profile"],
        idempotency_key="main-after-admission-disable",
        input_payload={"message": "main turn"},
    )
    main_claim = claim_next_execution(state["context"], uuid4(), 3)
    assert main_claim is not None
    assert main_claim.execution_id == main_execution.id
    assert main_claim.routine_id is None


def test_routine_claim_replay_rechecks_admission_gate(routine_context):
    state = routine_context
    _command, _routine = dispatch(state)
    claim = claim_next_execution(state["context"], uuid4(), 2)
    assert claim is not None and claim.routine_id is not None
    disable_routine_admission(state["workspace"].id)

    with pytest.raises(RuntimeNotReadyError):
        claim_next_execution(state["context"], claim.claim_id, 2)


def test_stale_admission_release_fences_routine_claims(routine_context):
    state = routine_context
    _command, _routine = dispatch(state)
    workspace = Workspace.objects.get(pk=state["workspace"].id)
    target = dict(workspace.release_target)
    target["routine_admission"] = {
        **target["routine_admission"],
        "release_digest": "sha256:" + "0" * 64,
    }
    workspace.release_target = target
    workspace.save(update_fields=["release_target", "updated_at"])

    with pytest.raises(RuntimeFencedError):
        claim_next_execution(state["context"], uuid4(), 2)


def test_generic_attempt_failure_is_projected_as_a_routine_result(routine_context):
    state = routine_context
    _command, routine = dispatch(state)
    claim = claim_next_execution(state["context"], uuid4(), 2)
    assert claim is not None

    receipt = fail_attempt(
        state["context"],
        claim.attempt_id,
        claim.lease_token,
        {"code": "worker_error", "retryable": False},
        terminal_event={
            "event_id": uuid4(),
            "stream_id": claim.stream_id,
            "sequence": 2,
            "payload": {"code": "worker_error", "retryable": False},
        },
    )

    assert receipt.status == "failed"
    routine.refresh_from_db()
    assert routine.status == RoutineRunStatus.FAILED


def test_routine_result_locking_supports_postgres_normal_and_failed_replays(
    routine_context,
):
    state = routine_context

    _normal_command, normal_routine = dispatch(state, ordinal=1)
    normal_claim = claim_next_execution(state["context"], uuid4(), 2)
    assert normal_claim is not None
    normal_event_id = uuid4()
    normal = append_runtime_routine_result(
        state["context"],
        normal_claim.attempt_id,
        normal_claim.lease_token,
        event_id=normal_event_id,
        sequence=1,
        outcome="unchanged",
        text="No changes were needed.",
        references=[],
        delayed=False,
    )
    assert normal["status"] == "succeeded"
    assert (
        append_runtime_routine_result(
            state["context"],
            normal_claim.attempt_id,
            normal_claim.lease_token,
            event_id=normal_event_id,
            sequence=1,
            outcome="unchanged",
            text="No changes were needed.",
            references=[],
            delayed=False,
        )
        == normal
    )
    normal_routine.refresh_from_db()
    assert normal_routine.status == RoutineRunStatus.SUCCEEDED

    _failed_command, failed_routine = dispatch(state, ordinal=2)
    failed_claim = claim_next_execution(state["context"], uuid4(), 2)
    assert failed_claim is not None
    failed_event_id = uuid4()
    failed = append_runtime_routine_result(
        state["context"],
        failed_claim.attempt_id,
        failed_claim.lease_token,
        event_id=failed_event_id,
        sequence=1,
        outcome="failed",
        text="The routine failed before completion.",
        references=[],
        delayed=False,
    )
    assert failed["status"] == "failed"
    assert (
        append_runtime_routine_result(
            state["context"],
            failed_claim.attempt_id,
            failed_claim.lease_token,
            event_id=failed_event_id,
            sequence=1,
            outcome="failed",
            text="The routine failed before completion.",
            references=[],
            delayed=False,
        )
        == failed
    )
    failed_routine.refresh_from_db()
    assert failed_routine.status == RoutineRunStatus.FAILED


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("operation", ["result", "session-bind"])
def test_postgres_result_and_expiry_race_has_one_terminal_outcome(
    routine_context, monkeypatch, transactional_db, operation
):
    if connection.vendor != "postgresql":
        pytest.skip("requires PostgreSQL row-lock semantics")

    state = routine_context
    _command, routine = dispatch(state)
    claim = claim_next_execution(state["context"], uuid4(), 2)
    assert claim is not None
    request_routine_approval(
        routine.id,
        action_attempt_id=uuid4(),
        approval_request_id=uuid4(),
        action_digest="a" * 64,
        provider_idempotency_key="provider-action-race",
        expires_at=state["base"] + timedelta(minutes=1),
        now=state["base"],
    )
    role = local()
    worker_pids = {}
    expiry_routine_query = Event()
    result_routine_query = Event()
    original_first = QuerySet.first

    def coordinated_first(queryset, *args, **kwargs):
        if queryset.model is RoutineExecution:
            if getattr(role, "name", None) == "expiry":
                expiry_routine_query.set()
            elif getattr(role, "name", None) == "result":
                result_routine_query.set()
        return original_first(queryset, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "first", coordinated_first)

    def set_lock_timeout(role_name: str) -> None:
        close_old_connections()
        role.name = role_name
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '10s'")
            cursor.execute("SELECT pg_backend_pid()")
            worker_pids[role_name] = cursor.fetchone()[0]

    def wait_for_controller_block(controller_pid: int, worker_pid: int) -> None:
        deadline = monotonic() + 5
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_blocking_pids(%s)", [worker_pid],
                )
                blockers = cursor.fetchone()[0]
                if controller_pid in blockers or worker_pids.get("expiry") in blockers:
                    return
        raise AssertionError("worker did not queue on the held routine lock")

    def append_result():
        try:
            set_lock_timeout("result")
            if operation == "session-bind":
                bind_routine_session(
                    state["context"], claim.attempt_id, claim.lease_token,
                    None, "late-routine-session",
                )
                return "bound"
            append_runtime_routine_result(
                state["context"],
                claim.attempt_id,
                claim.lease_token,
                event_id=uuid4(),
                sequence=1,
                outcome="unchanged",
                text="The result races approval expiry.",
                references=[],
                delayed=False,
                now=state["base"] + timedelta(minutes=1),
            )
        except RuntimeLeaseConflictError:
            return "stale"
        finally:
            connection.close()
        return "result"

    def expire_approval():
        try:
            set_lock_timeout("expiry")
            return expire_routine_approvals(
                now=state["base"] + timedelta(minutes=1),
            )
        finally:
            connection.close()

    controller = transaction.atomic()
    controller.__enter__()
    executor = ThreadPoolExecutor(max_workers=2)
    try:
        RoutineExecution.objects.select_for_update().get(pk=routine.id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            controller_pid = cursor.fetchone()[0]
        expiry_future = executor.submit(expire_approval)
        assert expiry_routine_query.wait(timeout=5)
        wait_for_controller_block(controller_pid, worker_pids["expiry"])
        result_future = executor.submit(append_result)
        assert result_routine_query.wait(timeout=5)
        wait_for_controller_block(controller_pid, worker_pids["result"])
        Attempt.objects.select_for_update(nowait=True).get(pk=claim.attempt_id)
        controller.__exit__(None, None, None)
        controller = None
        result_outcome = result_future.result(timeout=10)
        expiry_outcome = expiry_future.result(timeout=10)
    finally:
        if controller is not None:
            controller.__exit__(None, None, None)
        executor.shutdown(wait=True, cancel_futures=True)

    assert result_outcome == "stale"
    assert expiry_outcome == 1
    routine.refresh_from_db()
    assert routine.status == RoutineRunStatus.EXPIRED
    assert routine.current_attempt.status == AttemptStatus.FAILED


def test_stopped_routine_is_terminalized_with_a_failed_result(routine_context):
    state = routine_context
    command, routine = dispatch(state)
    claim = claim_next_execution(state["context"], uuid4(), 2)
    assert claim is not None

    receipt = acknowledge_stopped(
        state["context"], claim.attempt_id, claim.lease_token, "response_lost"
    )

    assert receipt.requeued is False
    routine.refresh_from_db()
    assert routine.status == RoutineRunStatus.FAILED
    attempt = routine.current_attempt
    attempt.refresh_from_db()
    assert attempt.status == AttemptStatus.FAILED
    assert Execution.objects.get(pk=routine.execution_id).status == ExecutionStatus.FAILED
    event = ExecutionEvent.objects.get(attempt_id=attempt.id, event_type="routine.result")
    assert event.payload["outcome"] == "failed"
    assert Lease.objects.get(attempt_id=attempt.id).state == LeaseState.RELEASED

    assert (
        acknowledge_stopped(
            state["context"], claim.attempt_id, claim.lease_token, "response_lost"
        )
        == receipt
    )
    _replacement_command, replacement = dispatch(
        state, ordinal=2, routine_id=command.routine_id
    )
    assert replacement.routine_id == command.routine_id


def approval_decision_payload(state, routine, action, *, decision: str = "approve") -> dict:
    base = state["base"] + timedelta(minutes=10)
    value = {
        "schema_version": "v1",
        "kind": "routine.approval_decision",
        "producer": "cloud",
        "service_identity": "cloud-service",
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "approval_request_id": str(action.approval_request_id),
        "action_attempt_id": str(action.action_attempt_id),
        "run_id": str(routine.run_id),
        "attempt_id": str(routine.current_attempt_id),
        "generation": routine.generation,
        "decision": decision,
        "decided_at": base.isoformat().replace("+00:00", "Z"),
        "scope": {
            "kind": "workspace",
            "workspace_id": str(state["workspace"].id),
            "owner_user_id": str(state["owner_id"]),
            "ally_id": str(state["ally_id"]),
            "cloud_binding_id": str(state["cloud_binding_id"]),
        },
        "issued_at": base.isoformat().replace("+00:00", "Z"),
        "deadline_at": (base + timedelta(seconds=60)).isoformat().replace(
            "+00:00", "Z"
        ),
        "fingerprint": "",
    }
    value["fingerprint"] = routine_fingerprint(value)
    return value


def cancel_wait_payload(state, routine, action) -> dict:
    base = state["base"] + timedelta(minutes=11)
    value = {
        "schema_version": "v1",
        "kind": "routine.cancel_wait",
        "producer": "cloud",
        "service_identity": "cloud-service",
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "approval_request_id": str(action.approval_request_id),
        "run_id": str(routine.run_id),
        "attempt_id": str(routine.current_attempt_id),
        "generation": routine.generation,
        "reason": "replacement",
        "replacing_occurrence_id": str(uuid4()),
        "scope": {
            "kind": "workspace",
            "workspace_id": str(state["workspace"].id),
            "owner_user_id": str(state["owner_id"]),
            "ally_id": str(state["ally_id"]),
            "cloud_binding_id": str(state["cloud_binding_id"]),
        },
        "issued_at": base.isoformat().replace("+00:00", "Z"),
        "deadline_at": (base + timedelta(seconds=60)).isoformat().replace(
            "+00:00", "Z"
        ),
        "fingerprint": "",
    }
    value["fingerprint"] = routine_fingerprint(value)
    return value


def post_internal_routine(path, payload, *, token="test-cloud-service-token"):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return Client().post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers,
    )


@pytest.mark.parametrize("token", [None, "wrong-cloud-service-token"])
def test_routine_dispatch_endpoint_requires_cloud_service_auth(
    routine_context, settings, token
):
    settings.ALLIES_CLOUD_SERVICE_TOKEN = "test-cloud-service-token"
    response = post_internal_routine(
        "/api/v1/internal/routines/dispatch",
        dispatch_payload(routine_context),
        token=token,
    )

    assert response.status_code in (401, 403)
    assert not Execution.objects.filter(source_kind="routine_dispatch").exists()


def test_routine_dispatch_endpoint_replays_the_stored_rev9_receipt(
    routine_context, settings
):
    settings.ALLIES_CLOUD_SERVICE_TOKEN = "test-cloud-service-token"
    payload = dispatch_payload(routine_context)

    first = post_internal_routine("/api/v1/internal/routines/dispatch", payload)
    replay = post_internal_routine("/api/v1/internal/routines/dispatch", payload)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json() == replay.json()
    assert first.json()["kind"] == "routine.dispatch_receipt"
    assert first.json()["acceptance_is_completion"] is False
    assert set(first.json()) >= {
        "execution_id",
        "attempt_id",
        "generation",
    }
    assert (
        Execution.objects.filter(source_kind="routine_dispatch").count() == 1
    )


def test_routine_dispatch_endpoint_rejects_a_different_routine_kind(
    routine_context, settings
):
    settings.ALLIES_CLOUD_SERVICE_TOKEN = "test-cloud-service-token"
    payload = dispatch_payload(routine_context)
    payload["kind"] = "routine.approval_decision"

    response = post_internal_routine("/api/v1/internal/routines/dispatch", payload)

    assert response.status_code == 422
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "request is invalid",
    }


def test_routine_dispatch_endpoint_rejects_an_oversized_schedule(
    routine_context, settings
):
    settings.ALLIES_CLOUD_SERVICE_TOKEN = "test-cloud-service-token"
    payload = dispatch_payload(routine_context)
    payload["schedule"]["metadata"] = "x" * MAX_ROUTINE_EVENT_BYTES
    payload["fingerprint"] = routine_fingerprint(payload)

    response = post_internal_routine("/api/v1/internal/routines/dispatch", payload)

    assert response.status_code == 422
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "request is invalid",
    }
    assert not Execution.objects.filter(source_kind="routine_dispatch").exists()


def test_routine_approval_endpoint_replays_and_fences_changed_idempotency(
    routine_context, settings
):
    settings.ALLIES_CLOUD_SERVICE_TOKEN = "test-cloud-service-token"
    state = routine_context
    _command, routine = dispatch(state)
    claim = claim_next_execution(state["context"], uuid4(), 2)
    assert claim is not None
    request_routine_approval(
        routine.id,
        action_attempt_id=uuid4(),
        approval_request_id=uuid4(),
        action_digest="a" * 64,
        provider_idempotency_key="provider-api-approval",
        continuation={"tool": "example"},
        event_sequence=1,
        now=state["base"],
    )
    action = RoutineApprovalAction.objects.get(routine_execution=routine)
    payload = approval_decision_payload(state, routine, action)

    first = post_internal_routine(
        "/api/v1/internal/routines/approval-decision", payload
    )
    replay = post_internal_routine(
        "/api/v1/internal/routines/approval-decision", payload
    )
    command_collision = dict(payload)
    command_collision["idempotency_key"] = str(uuid4())
    command_collision["fingerprint"] = routine_fingerprint(command_collision)
    collision = post_internal_routine(
        "/api/v1/internal/routines/approval-decision", command_collision
    )
    changed = dict(payload)
    changed["decision"] = "reject"
    changed["fingerprint"] = routine_fingerprint(changed)
    conflict = post_internal_routine(
        "/api/v1/internal/routines/approval-decision", changed
    )

    assert first.status_code == 200
    assert first.json()["result_code"] == "APPROVAL_AUTHORIZED"
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert collision.status_code == 409
    assert collision.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_rejected_routine_emits_a_failed_result_before_terminalizing(
    routine_context,
):
    state = routine_context
    _command, routine = dispatch(state)
    claim = claim_next_execution(state["context"], uuid4(), 2)
    assert claim is not None
    request_routine_approval(
        routine.id,
        action_attempt_id=uuid4(),
        approval_request_id=uuid4(),
        action_digest="c" * 64,
        provider_idempotency_key="provider-action-reject",
        continuation={"tool": "example"},
        event_sequence=1,
        now=state["base"],
    )
    action = RoutineApprovalAction.objects.get(routine_execution=routine)
    decision = RoutineApprovalDecision.model_validate(
        approval_decision_payload(state, routine, action, decision="reject")
    )

    receipt = decide_routine_approval(
        decision,
        now=state["base"] + timedelta(minutes=1),
    )

    assert receipt.result_code == "APPROVAL_REJECTED"
    routine.refresh_from_db()
    assert routine.status == RoutineRunStatus.CANCELLED
    assert routine.current_attempt.status == AttemptStatus.CANCELLED
    event = ExecutionEvent.objects.get(
        attempt_id=routine.current_attempt_id,
        event_type="routine.result",
    )
    assert event.payload["outcome"] == "failed"
    assert event.payload["text"] == "Routine approval was rejected before execution."
    assert routine.terminal_receipt["result_event_id"] == str(event.event_id)


def test_routine_cancel_wait_endpoint_returns_the_existing_fence_receipt(
    routine_context, settings
):
    settings.ALLIES_CLOUD_SERVICE_TOKEN = "test-cloud-service-token"
    state = routine_context
    _command, routine = dispatch(state)
    claim = claim_next_execution(state["context"], uuid4(), 2)
    assert claim is not None
    request_routine_approval(
        routine.id,
        action_attempt_id=uuid4(),
        approval_request_id=uuid4(),
        action_digest="b" * 64,
        provider_idempotency_key="provider-api-cancel",
        continuation={"tool": "example"},
        event_sequence=1,
        now=state["base"],
    )
    action = RoutineApprovalAction.objects.get(routine_execution=routine)

    payload = cancel_wait_payload(state, routine, action)
    response = post_internal_routine(
        "/api/v1/internal/routines/cancel-wait",
        payload,
    )
    replay = post_internal_routine(
        "/api/v1/internal/routines/cancel-wait",
        payload,
    )
    changed = dict(payload)
    changed["reason"] = "replacement-again"
    changed["fingerprint"] = routine_fingerprint(changed)
    conflict = post_internal_routine(
        "/api/v1/internal/routines/cancel-wait",
        changed,
    )

    assert response.status_code == 200
    assert response.json()["code"] == "WAIT_CANCELLED"
    assert response.json()["status"] == "cancelled"
    assert replay.status_code == 200
    assert replay.json() == response.json()
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    routine.refresh_from_db()
    assert routine.status == RoutineRunStatus.CANCELLED
    event = ExecutionEvent.objects.get(
        attempt_id=routine.current_attempt_id,
        event_type="routine.result",
    )
    assert event.payload["outcome"] == "failed"
    assert event.payload["text"] == "Routine wait was cancelled before execution."


def test_routine_session_binding_endpoint_accepts_runtime_payload_without_cloud_ref(
    routine_context,
):
    state = routine_context
    _command, _routine = dispatch(state)
    claim = claim_next_execution(state["context"], uuid4(), 2)
    assert claim is not None
    issued = issue_runtime_credential(state["workspace"].id, "routine-api-secret")

    response = Client().put(
        f"/api/v1/runtime/attempts/{claim.attempt_id}/routine-session-binding",
        data=json.dumps(
            {"expected_session_id": None, "effective_session_id": "routine-api"}
        ),
        content_type="application/json",
        headers={
            "Authorization": f"Bearer {issued.raw_token}",
            "X-Foundry-Lease-Token": claim.lease_token,
        },
    )

    assert response.status_code == 200, response.content
    assert response.json() == {"session_id": "routine-api"}


@pytest.mark.parametrize("main_session", [None, "existing-main-session"])
def test_routine_lease_cannot_bind_the_main_session(routine_context, main_session):
    state = routine_context
    _command, routine = dispatch(state)
    claim = claim_next_execution(state["context"], uuid4(), 2)
    binding = ConversationBinding.objects.get(profile=state["profile"])
    binding.hermes_session_id = main_session
    binding.save(update_fields=["hermes_session_id"])
    issued = issue_runtime_credential(state["workspace"].id, "routine-api-secret")

    response = Client().put(
        f"/api/v1/runtime/attempts/{claim.attempt_id}/session-binding",
        data=json.dumps(
            {
                "cloud_conversation_ref": str(state["main_conversation_id"]),
                "expected_session_id": main_session,
                "effective_session_id": "routine-must-not-be-main",
            }
        ),
        content_type="application/json",
        headers={
            "Authorization": f"Bearer {issued.raw_token}",
            "X-Foundry-Lease-Token": claim.lease_token,
        },
    )

    assert response.status_code == 409, response.content
    binding.refresh_from_db()
    routine.refresh_from_db()
    assert binding.hermes_session_id == main_session
    assert routine.hermes_session_id is None
    assert routine.current_attempt.session_receipt is None
    assert Lease.objects.get(attempt_id=claim.attempt_id).state == LeaseState.ACTIVE


def test_routine_lease_cannot_complete_through_main_endpoint(routine_context):
    state = routine_context
    _command, routine = dispatch(state)
    claim = claim_next_execution(state["context"], uuid4(), 2)
    lease = Lease.objects.get(attempt_id=claim.attempt_id)
    attempt = routine.current_attempt
    # Exercise the guard even if an older main-binding endpoint stored a receipt.
    attempt.session_receipt = {"session_id": "legacy-routine-session"}
    attempt.session_lease_digest = lease.token_digest
    attempt.save(update_fields=["session_receipt", "session_lease_digest"])
    issued = issue_runtime_credential(state["workspace"].id, "routine-api-secret")
    response = Client().post(
        f"/api/v1/runtime/attempts/{claim.attempt_id}/complete",
        data=json.dumps(
            {
                "receipt": {"code": "completed"},
                "event_id": str(uuid4()),
                "stream_id": "routine-stream",
                "sequence": 1,
                "payload": {"run_id": "routine-run", "status": "completed"},
            }
        ),
        content_type="application/json",
        headers={
            "Authorization": f"Bearer {issued.raw_token}",
            "X-Foundry-Lease-Token": claim.lease_token,
        },
    )
    assert response.status_code == 409, response.content
    routine.refresh_from_db()
    attempt.refresh_from_db()
    lease.refresh_from_db()
    assert routine.status == RoutineRunStatus.WORKING
    assert attempt.terminal_receipt is None
    assert lease.state == LeaseState.ACTIVE
    assert not ExecutionEvent.objects.filter(attempt_id=attempt.id).exists()
    result = append_runtime_routine_result(
        state["context"],
        claim.attempt_id,
        claim.lease_token,
        event_id=uuid4(),
        sequence=1,
        outcome="unchanged",
        text="Completed through the routine result endpoint.",
        references=[],
        delayed=False,
    )
    assert result["status"] == "succeeded"
    assert (
        ExecutionEvent.objects.filter(
            attempt_id=attempt.id, event_type="routine.result"
        ).count()
        == 1
    )


def test_same_profile_routines_have_distinct_leases_and_sessions(routine_context):
    state = routine_context
    first_command, first = dispatch(state, ordinal=1)
    second_command, second = dispatch(state, ordinal=2)

    first_claim = claim_next_execution(state["context"], uuid4(), 3)
    second_claim = claim_next_execution(state["context"], uuid4(), 3)

    assert first_claim is not None
    assert second_claim is not None
    assert {first_claim.routine_id, second_claim.routine_id} == {
        first.routine_id,
        second.routine_id,
    }
    assert first_claim.lease_id != second_claim.lease_id
    assert first_claim.conversation_id != second_claim.conversation_id
    main_execution = Execution.objects.create(
        workspace=state["workspace"],
        profile=state["profile"],
        idempotency_key="main-turn-after-routines",
        input_payload={
            "message": "main turn",
            "cloud_conversation_ref": str(state["main_conversation_id"]),
        },
    )
    main_claim = claim_next_execution(state["context"], uuid4(), 3)
    assert main_claim is not None
    assert main_claim.execution_id == main_execution.id
    assert main_claim.routine_id is None

    first_claim = first_claim if first_claim.routine_id == first.routine_id else second_claim
    first_session = bind_routine_session(
        state["context"],
        first_claim.attempt_id,
        first_claim.lease_token,
        None,
        "routine-session-1",
    )
    assert first_session.session_id == "routine-session-1"
    binding = ConversationBinding.objects.get(profile=state["profile"])
    assert binding.cloud_conversation_ref == str(state["main_conversation_id"])
    assert binding.hermes_session_id is None

    result = append_runtime_routine_result(
        state["context"],
        first_claim.attempt_id,
        first_claim.lease_token,
        event_id=uuid4(),
        sequence=1,
        outcome="unchanged",
        text="No changes were needed.",
        references=[],
        delayed=False,
    )
    assert result["status"] == "succeeded"
    event_delivery = ExecutionEventDelivery.objects.get(
        event__event_id=UUID(result["receipt"]["event_id"])
    )
    assert event_delivery.state == EventDeliveryState.PENDING
    event = parse_routine_message(json.loads(event_delivery.envelope_bytes))
    assert isinstance(event, RoutineResult)
    assert event.outcome == "unchanged"
    assert event.routine_revision == first.routine_revision
    assert event.title_snapshot == first.title_snapshot
    replay = append_runtime_routine_result(
        state["context"],
        first_claim.attempt_id,
        first_claim.lease_token,
        event_id=UUID(result["receipt"]["event_id"]),
        sequence=1,
        outcome="unchanged",
        text="No changes were needed.",
        references=[],
        delayed=False,
    )
    assert replay == result

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == RoutineRunStatus.SUCCEEDED
    assert second.status == RoutineRunStatus.WORKING
    assert first_command.run_conversation_id != second_command.run_conversation_id


def test_approval_wait_retires_and_reacquires_one_lease(routine_context):
    state = routine_context
    _command, routine = dispatch(state)
    claim = claim_next_execution(state["context"], uuid4(), 2)
    assert claim is not None
    old_lease_id = claim.lease_id
    old_acquisition = RoutineLeaseAcquisition.objects.get(claim_id=claim.claim_id)
    action_attempt_id = uuid4()
    approval_request_id = uuid4()

    event = request_routine_approval(
        routine.id,
        action_attempt_id=action_attempt_id,
        approval_request_id=approval_request_id,
        action_digest="a" * 64,
        provider_idempotency_key="provider-action-1",
        continuation={"tool": "example", "arguments": {"value": 1}},
        event_sequence=1,
        now=state["base"],
    )
    routine.refresh_from_db()
    old_acquisition.refresh_from_db()
    old_lease = Lease.objects.get(pk=old_lease_id)
    assert routine.status == RoutineRunStatus.APPROVAL_WAITING
    assert routine.current_attempt.status == AttemptStatus.APPROVAL_WAITING
    assert old_lease.state == LeaseState.RELEASED
    assert old_acquisition.current is False
    assert isinstance(
        parse_routine_message(
            json.loads(ExecutionEventDelivery.objects.get(event=event).envelope_bytes)
        ),
        RoutineApprovalRequested,
    )

    action = RoutineApprovalAction.objects.get(approval_request_id=approval_request_id)
    decision = RoutineApprovalDecision.model_validate(
        approval_decision_payload(state, routine, action)
    )
    receipt = decide_routine_approval(decision, now=state["base"] + timedelta(minutes=1))

    assert receipt.result_code == "APPROVAL_AUTHORIZED"
    assert receipt.request_status == RoutineApprovalStatus.AUTHORIZING
    assert receipt.run_status == RoutineRunStatus.WORKING
    action.refresh_from_db()
    routine.refresh_from_db()
    paused_lease = Lease.objects.get(pk=old_lease_id)
    acquisitions = list(
        RoutineLeaseAcquisition.objects.filter(lease_id=old_lease_id).order_by("ordinal")
    )
    assert len(acquisitions) == 1
    assert acquisitions[0].current is False
    assert paused_lease.state == LeaseState.RELEASED
    assert action.status == RoutineApprovalStatus.AUTHORIZING
    assert routine.status == RoutineRunStatus.WORKING
    assert routine.current_attempt.status == AttemptStatus.QUEUED

    disable_routine_admission(state["workspace"].id)
    with pytest.raises(RuntimeNotReadyError):
        claim_next_execution(state["context"], uuid4(), 2)
    enable_routine_admission(
        state["workspace"].id,
        release_digest=state["release_digest"],
        machine_generation=state["workspace"].machine_generation,
        runtime_start_epoch=state["workspace"].runtime_start_epoch,
    )
    resumed_claim = claim_next_execution(state["context"], uuid4(), 2)
    assert resumed_claim is not None
    assert resumed_claim.lease_id == old_lease_id
    assert resumed_claim.payload["routine_approval"]["continuation"] == {
        "tool": "example",
        "arguments": {"value": 1},
    }
    new_lease = Lease.objects.get(pk=old_lease_id)
    acquisitions = list(
        RoutineLeaseAcquisition.objects.filter(lease_id=old_lease_id).order_by("ordinal")
    )
    assert len(acquisitions) == 2
    assert acquisitions[0].current is False
    assert acquisitions[1].current is True
    assert new_lease.state == LeaseState.ACTIVE
    assert new_lease.current_acquisition_id == acquisitions[1].id

    replay = decide_routine_approval(decision, now=state["base"] + timedelta(minutes=2))
    assert replay.model_dump(mode="json") == receipt.model_dump(mode="json")

    append_runtime_routine_result(
        state["context"],
        resumed_claim.attempt_id,
        resumed_claim.lease_token,
        event_id=uuid4(),
        sequence=100001,
        outcome="failed",
        text="Approved action continuation is unavailable; no action was executed.",
        references=[],
        delayed=False,
    )
    action.refresh_from_db()
    assert action.status == RoutineApprovalStatus.CANCELLED
    assert action.action_state == "manual_reconciliation"

    with pytest.raises(RuntimeConflictError):
        request_routine_approval(
            routine.id,
            action_attempt_id=action_attempt_id,
            approval_request_id=approval_request_id,
            action_digest="b" * 64,
            provider_idempotency_key="provider-action-1",
            continuation={"tool": "example"},
            now=state["base"],
        )


def test_expiry_fences_waiting_routine_without_a_decision_receipt(routine_context):
    state = routine_context
    _command, routine = dispatch(state)
    claim = claim_next_execution(state["context"], uuid4(), 2)
    assert claim is not None
    request_routine_approval(
        routine.id,
        action_attempt_id=uuid4(),
        action_digest="a" * 64,
        provider_idempotency_key="provider-action-expiry",
        expires_at=state["base"] + timedelta(minutes=1),
        now=state["base"],
    )

    assert (
        expire_routine_approvals(
            now=state["base"] + timedelta(minutes=1),
        )
        == 1
    )
    routine.refresh_from_db()
    action = RoutineApprovalAction.objects.get(routine_execution=routine)
    assert routine.status == RoutineRunStatus.EXPIRED
    assert action.status == RoutineApprovalStatus.EXPIRED
    assert routine.current_attempt.status == AttemptStatus.FAILED
    event = ExecutionEvent.objects.get(
        attempt_id=routine.current_attempt_id,
        event_type="routine.result",
    )
    assert event.payload["outcome"] == "failed"
    assert event.payload["text"] == "Routine approval expired before execution."
    assert routine.terminal_receipt["result_event_id"] == str(event.event_id)


def test_expired_routine_lease_reuses_one_lease_with_a_new_acquisition(routine_context):
    state = routine_context
    _command, routine = dispatch(state)
    first_claim = claim_next_execution(state["context"], uuid4(), 2)
    assert first_claim is not None
    old_lease_id = first_claim.lease_id
    Lease.objects.filter(pk=old_lease_id).update(
        expires_at=django_timezone.now() - timedelta(seconds=1)
    )

    disable_routine_admission(state["workspace"].id)
    with pytest.raises(RuntimeNotReadyError):
        claim_next_execution(state["context"], uuid4(), 2)
    enable_routine_admission(
        state["workspace"].id,
        release_digest=state["release_digest"],
        machine_generation=state["workspace"].machine_generation,
        runtime_start_epoch=state["workspace"].runtime_start_epoch,
    )
    second_claim = claim_next_execution(state["context"], uuid4(), 2)

    assert second_claim is not None
    assert second_claim.lease_id == old_lease_id
    acquisitions = list(
        RoutineLeaseAcquisition.objects.filter(lease_id=old_lease_id).order_by("ordinal")
    )
    assert [acquisition.current for acquisition in acquisitions] == [False, True]
    routine.refresh_from_db()
    assert routine.status == RoutineRunStatus.WORKING


def test_profile_fencing_terminalizes_active_routine_with_failed_result(
    routine_context,
):
    state = routine_context
    _command, routine = dispatch(state)
    claim = claim_next_execution(state["context"], uuid4(), 2)
    assert claim is not None

    with transaction.atomic():
        _fence_profile_leases(state["profile"].id)

    routine = RoutineExecution.objects.get(pk=routine.id)
    attempt = routine.current_attempt
    attempt.refresh_from_db()
    execution = Execution.objects.get(pk=routine.execution_id)
    lease = Lease.objects.get(pk=claim.lease_id)
    event = ExecutionEvent.objects.get(
        attempt_id=attempt.id,
        event_type="routine.result",
    )

    assert routine.status == RoutineRunStatus.FAILED
    assert routine.terminal_receipt["code"] == "PROFILE_FENCED"
    assert routine.terminal_receipt["result_event_id"] == str(event.event_id)
    assert attempt.status == AttemptStatus.UNKNOWN
    assert execution.status == ExecutionStatus.FAILED
    assert lease.state == LeaseState.FENCED
    assert event.payload["outcome"] == "failed"
    assert event.payload["text"] == "Routine profile was fenced before completion."

    _replacement_command, replacement = dispatch(
        state, ordinal=2, routine_id=routine.routine_id
    )
    assert replacement.routine_id == routine.routine_id


def test_expired_routine_after_session_bind_is_fenced_not_redispatched(routine_context):
    state = routine_context
    _command, routine = dispatch(state)
    first_claim = claim_next_execution(state["context"], uuid4(), 2)
    assert first_claim is not None
    bind_routine_session(
        state["context"],
        first_claim.attempt_id,
        first_claim.lease_token,
        None,
        "routine-session-bound",
    )
    Lease.objects.filter(pk=first_claim.lease_id).update(
        expires_at=django_timezone.now() - timedelta(seconds=1)
    )

    assert claim_next_execution(state["context"], uuid4(), 2) is None
    routine.refresh_from_db()
    assert routine.status == RoutineRunStatus.FAILED
    assert routine.current_attempt.status == AttemptStatus.UNKNOWN
    event = ExecutionEvent.objects.get(
        attempt_id=routine.current_attempt_id,
        event_type="routine.result",
    )
    assert event.payload["outcome"] == "failed"
    assert event.payload["text"] == "Routine lease expired before completion."
    assert routine.terminal_receipt["result_event_id"] == str(event.event_id)
