from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.test import Client

from allies.gateways.contracts import RoutineApprovalReceipt, canonical_fingerprint
from allies.models import Ally, AllyBinding
from auths.models import SessionClientKind, User
from auths.services.sessions import issue_session
from chat.models import Conversation
from routines.models import (
    RoutineApprovalCommand,
    RoutineApprovalCommandKind,
    RoutineApprovalDeliveryState,
    RoutineApprovalProjection,
    RoutineApprovalStatus,
    RoutineDispatchState,
    RoutineOccurrence,
    RoutineOccurrenceDisposition,
    RoutineRunOutcome,
)
from routines.services.approvals import (
    RoutineApprovalConflict,
    RoutineApprovalInvalid,
    apply_routine_approval_requested_event,
    build_routine_cancel_wait_command,
    claim_pending_routine_approval_commands,
    dispatch_pending_routine_approval_commands,
    expire_routine_approvals,
    record_routine_approval_decision,
    request_routine_approval_replacement,
    settle_routine_approval_command,
)
from routines.services.dispatch import (
    claim_pending_routine_dispatches,
    settle_routine_dispatch,
)
from routines.services.management import create_routine_intent
from routines.services.scheduler import (
    OCCURRENCE_ADMITTED,
    OCCURRENCE_REPLACEMENT_PENDING,
    DueRoutineCandidate,
    admit_due_candidate,
    admit_due_routines,
)
from workspaces.models import Membership, Workspace

BASE = datetime(2026, 9, 10, 7, tzinfo=UTC)


@pytest.fixture
def approval_account(db):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Routine approvals")
    Membership.objects.create(
        workspace=workspace,
        user=user,
        role="owner",
        status="active",
    )
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study partner",
        personality="Calm and specific.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    binding = AllyBinding.objects.create(ally=ally)
    conversation = Conversation.objects.create(ally=ally)
    routine = create_routine_intent(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        main_conversation_id=conversation.id,
        title="Morning inbox",
        execution_prompt="Review the inbox and summarize urgent messages.",
        schedule={
            "kind": "recurring",
            "frequency": "daily",
            "local_time": "09:00:00",
            "timezone": "Europe/Berlin",
        },
        now=datetime(2026, 9, 10, 6, tzinfo=UTC),
    )
    admit_due_routines(now=BASE)
    routine.refresh_from_db()
    run = routine.run_snapshots.get()
    return user, workspace, ally, binding, conversation, routine, run.occurrence, run


def _accept_dispatch(account):
    run = account[-1]
    lease = claim_pending_routine_dispatches(now=BASE)[0]
    execution_id = uuid4()
    attempt_id = uuid4()
    assert settle_routine_dispatch(
        lease,
        status=RoutineDispatchState.ACCEPTED,
        execution_id=execution_id,
        attempt_id=attempt_id,
        generation=7,
        receipt_digest="a" * 64,
        now=BASE,
    )
    run.refresh_from_db()
    return execution_id, attempt_id, run.dispatch_outbox.generation


def _approval_event(account, *, event_id=None, event_sequence=2, **changes):
    user, workspace, ally, binding, _conversation, _routine, _occurrence, run = account
    execution_id, attempt_id, generation = _accept_dispatch(account)
    event = {
        "schema_version": "v1",
        "kind": "routine.approval_requested",
        "producer": "foundry",
        "service_identity": "foundry-service",
        "event_id": str(event_id or uuid4()),
        "event_sequence": event_sequence,
        "approval_request_id": str(uuid4()),
        "action_attempt_id": str(uuid4()),
        "run_id": str(run.id),
        "execution_id": str(execution_id),
        "attempt_id": str(attempt_id),
        "generation": generation,
        "status": "pending",
        "created_at": BASE.isoformat().replace("+00:00", "Z"),
        "expires_at": (BASE + timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
        "action_digest": "b" * 64,
        "provider_idempotency_key": "routine-action-00000000000d",
        "scope": {
            "kind": "workspace",
            "workspace_id": str(workspace.id),
            "owner_user_id": str(user.id),
            "ally_id": str(ally.id),
            "cloud_binding_id": str(binding.id),
        },
        "issued_at": (BASE + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "deadline_at": (BASE + timedelta(seconds=31))
        .isoformat()
        .replace("+00:00", "Z"),
    }
    event.update(changes)
    event["fingerprint"] = canonical_fingerprint(event)
    return event


def _replacement_occurrence(account):
    _user, _workspace, ally, binding, _conversation, routine, _occurrence, _run = (
        account
    )
    return RoutineOccurrence.objects.create(
        routine=routine,
        workspace=routine.workspace,
        owner=routine.owner,
        ally=ally,
        binding=binding,
        scheduled_at=BASE + timedelta(days=1),
        observed_revision=routine.revision,
        observed_schedule_generation=routine.schedule_generation,
        disposition=RoutineOccurrenceDisposition.CANCELLED,
        delayed=False,
    )


def _approval_receipt(
    account,
    command,
    *,
    result_code="APPROVAL_AUTHORIZED",
    action_attempt_state="pre_dispatch",
    run_status="working",
    permission_consumed=True,
):
    user, workspace, ally, binding, _conversation, _routine, _occurrence, _run = account
    base = BASE + timedelta(hours=1)
    values = {
        "schema_version": "v1",
        "kind": "routine.approval_receipt",
        "producer": "foundry",
        "service_identity": "foundry-service",
        "command_id": str(command.command_id),
        "idempotency_key": str(command.idempotency_key),
        "result_code": result_code,
        "request_status": "authorizing",
        "run_status": run_status,
        "permission_consumed": permission_consumed,
        "action_attempt_state": action_attempt_state,
        "scope": {
            "kind": "workspace",
            "workspace_id": str(workspace.id),
            "owner_user_id": str(user.id),
            "ally_id": str(ally.id),
            "cloud_binding_id": str(binding.id),
        },
        "issued_at": base.isoformat().replace("+00:00", "Z"),
        "deadline_at": (base + timedelta(seconds=30))
        .isoformat()
        .replace("+00:00", "Z"),
    }
    values["fingerprint"] = canonical_fingerprint(values)
    return values


@pytest.mark.django_db
def test_approval_event_duplicate_and_conflicting_replay(approval_account):
    event = _approval_event(approval_account)
    first = apply_routine_approval_requested_event(event)
    duplicate = apply_routine_approval_requested_event(event)

    assert first.status == "applied"
    assert duplicate.status == "duplicate"
    assert duplicate.approval.id == first.approval.id
    assert RoutineApprovalProjection.objects.count() == 1

    conflicting = dict(event)
    conflicting["action_digest"] = "c" * 64
    conflicting["fingerprint"] = canonical_fingerprint(conflicting)
    with pytest.raises(RoutineApprovalConflict):
        apply_routine_approval_requested_event(conflicting)
    assert RoutineApprovalProjection.objects.count() == 1


@pytest.mark.django_db
def test_approval_request_rejects_non_24_hour_deadline(approval_account):
    event = _approval_event(approval_account)
    event["expires_at"] = (
        (BASE + timedelta(hours=23)).isoformat().replace("+00:00", "Z")
    )
    event["fingerprint"] = canonical_fingerprint(event)

    with pytest.raises(RoutineApprovalInvalid):
        apply_routine_approval_requested_event(event)


@pytest.mark.django_db
def test_owner_decision_replay_and_conflict_preserve_one_command(approval_account):
    user, workspace, _ally, _binding, _conversation, _routine, _occurrence, _run = (
        approval_account
    )
    projection = apply_routine_approval_requested_event(
        _approval_event(approval_account)
    ).approval
    key = uuid4()

    first = record_routine_approval_decision(
        user=user,
        workspace_id=workspace.id,
        approval_id=projection.id,
        decision="approve",
        idempotency_key=key,
        now=BASE + timedelta(hours=1),
    )
    replay = record_routine_approval_decision(
        user=user,
        workspace_id=workspace.id,
        approval_id=projection.id,
        decision="approve",
        idempotency_key=key,
        now=BASE + timedelta(hours=2),
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.payload == first.payload
    assert (
        RoutineApprovalCommand.objects.filter(
            approval=projection,
            kind=RoutineApprovalCommandKind.DECISION,
        ).count()
        == 1
    )

    with pytest.raises(RoutineApprovalConflict):
        record_routine_approval_decision(
            user=user,
            workspace_id=workspace.id,
            approval_id=projection.id,
            decision="reject",
            idempotency_key=uuid4(),
            now=BASE + timedelta(hours=2),
        )


@pytest.mark.django_db
def test_expiry_equality_marks_local_unavailable_and_enqueues_cancel(approval_account):
    projection = apply_routine_approval_requested_event(
        _approval_event(approval_account)
    ).approval
    expires_at = projection.expires_at

    assert expire_routine_approvals(now=expires_at) == 1
    projection.refresh_from_db()
    command = RoutineApprovalCommand.objects.get(
        approval=projection,
        kind=RoutineApprovalCommandKind.CANCEL_WAIT,
    )
    assert projection.status == RoutineApprovalStatus.EXPIRED
    assert projection.last_result_code == "APPROVAL_EXPIRED"
    assert projection.run.outcome == RoutineRunOutcome.EXPIRED
    assert command.status == RoutineApprovalDeliveryState.PENDING
    assert command.reason == "expiry"
    assert build_routine_cancel_wait_command(command_id=command.command_id).reason == (
        "expiry"
    )


@pytest.mark.django_db
def test_replacement_is_pending_until_cancel_receipt(approval_account):
    projection = apply_routine_approval_requested_event(
        _approval_event(approval_account)
    ).approval
    replacement = _replacement_occurrence(approval_account)

    first = request_routine_approval_replacement(
        approval_id=projection.id,
        replacing_occurrence_id=replacement.id,
        now=BASE + timedelta(hours=1),
    )
    replay = request_routine_approval_replacement(
        approval_id=projection.id,
        replacing_occurrence_id=replacement.id,
        now=BASE + timedelta(hours=2),
    )

    assert first.status == "replacement_pending"
    assert first.replayed is False
    assert replay.replayed is True
    assert replay.payload == first.payload
    assert first.approval.status == RoutineApprovalStatus.PENDING
    assert (
        RoutineApprovalCommand.objects.filter(
            approval=projection,
            kind=RoutineApprovalCommandKind.CANCEL_WAIT,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_delivery_retry_is_fenced_and_recoverable(approval_account):
    user, workspace, _ally, _binding, _conversation, _routine, _occurrence, _run = (
        approval_account
    )
    projection = apply_routine_approval_requested_event(
        _approval_event(approval_account)
    ).approval
    result = record_routine_approval_decision(
        user=user,
        workspace_id=workspace.id,
        approval_id=projection.id,
        decision="reject",
        idempotency_key=uuid4(),
        now=BASE + timedelta(hours=1),
    )
    first = claim_pending_routine_approval_commands(now=BASE + timedelta(hours=1))[0]
    assert settle_routine_approval_command(
        first,
        status=RoutineApprovalDeliveryState.FAILED,
        safe_error_code="transport_timeout",
        now=BASE + timedelta(hours=1),
    )
    command = RoutineApprovalCommand.objects.get(pk=result.command.id)
    assert command.status == RoutineApprovalDeliveryState.FAILED
    retry_at = command.next_attempt_at
    assert retry_at is not None
    assert (
        claim_pending_routine_approval_commands(
            now=retry_at - timedelta(microseconds=1)
        )
        == ()
    )

    second = claim_pending_routine_approval_commands(now=retry_at)[0]
    assert second.attempt_count == 2
    assert (
        settle_routine_approval_command(
            first,
            status=RoutineApprovalDeliveryState.ACCEPTED,
            now=retry_at,
        )
        is False
    )


@pytest.mark.django_db
def test_authorized_receipt_projects_authorizing_without_claiming_completion(
    approval_account,
):
    projection = apply_routine_approval_requested_event(
        _approval_event(approval_account)
    ).approval
    user, workspace, _ally, _binding, _conversation, _routine, _occurrence, run = (
        approval_account
    )
    result = record_routine_approval_decision(
        user=user,
        workspace_id=workspace.id,
        approval_id=projection.id,
        decision="approve",
        idempotency_key=uuid4(),
        now=BASE + timedelta(hours=1),
    )
    lease = claim_pending_routine_approval_commands(now=BASE + timedelta(hours=1))[0]

    assert settle_routine_approval_command(
        lease,
        status=RoutineApprovalDeliveryState.ACCEPTED,
        receipt=_approval_receipt(approval_account, result.command),
        now=BASE + timedelta(hours=1),
    )
    projection.refresh_from_db()
    run.refresh_from_db()
    assert projection.status == RoutineApprovalStatus.AUTHORIZING
    assert projection.last_result_code == "APPROVAL_AUTHORIZED"
    assert run.outcome == RoutineRunOutcome.WORKING


@pytest.mark.django_db
def test_manual_reconciliation_receipt_stops_automatic_processing(approval_account):
    projection = apply_routine_approval_requested_event(
        _approval_event(approval_account)
    ).approval
    user, workspace, _ally, _binding, _conversation, _routine, _occurrence, run = (
        approval_account
    )
    result = record_routine_approval_decision(
        user=user,
        workspace_id=workspace.id,
        approval_id=projection.id,
        decision="approve",
        idempotency_key=uuid4(),
        now=BASE + timedelta(hours=1),
    )
    lease = claim_pending_routine_approval_commands(now=BASE + timedelta(hours=1))[0]

    assert settle_routine_approval_command(
        lease,
        status=RoutineApprovalDeliveryState.ACCEPTED,
        receipt=_approval_receipt(
            approval_account,
            result.command,
            result_code="ACTION_MANUAL_RECONCILIATION",
            action_attempt_state="manual_reconciliation",
            run_status="failed",
            permission_consumed=False,
        ),
        now=BASE + timedelta(hours=1),
    )
    projection.refresh_from_db()
    run.refresh_from_db()
    assert projection.status == RoutineApprovalStatus.OUTCOME_UNKNOWN
    assert projection.action_attempt_state == "manual_reconciliation"
    assert projection.last_result_code == "ACTION_MANUAL_RECONCILIATION"
    assert run.outcome == RoutineRunOutcome.FAILED


@pytest.mark.django_db
def test_approval_transport_uses_persisted_command_and_receipt_fence(
    approval_account, monkeypatch, settings
):
    projection = apply_routine_approval_requested_event(
        _approval_event(approval_account)
    ).approval
    user, workspace, _ally, _binding, _conversation, _routine, _occurrence, run = (
        approval_account
    )
    result = record_routine_approval_decision(
        user=user,
        workspace_id=workspace.id,
        approval_id=projection.id,
        decision="approve",
        idempotency_key=uuid4(),
        now=BASE + timedelta(hours=1),
    )
    captured = {}

    def decide(*, raw_body):
        captured["body"] = raw_body
        return RoutineApprovalReceipt.model_validate(
            _approval_receipt(approval_account, result.command)
        )

    settings.ALLIES_ROUTINE_APPROVAL_ENABLED = True
    monkeypatch.setattr("routines.services.approvals.decide_routine_approval", decide)

    report = dispatch_pending_routine_approval_commands(now=BASE + timedelta(hours=1))

    assert report.claimed == 1
    assert report.accepted == 1
    assert report.reconciliation == 0
    assert captured["body"] == bytes(result.command.command_bytes)
    result.command.refresh_from_db()
    projection.refresh_from_db()
    run.refresh_from_db()
    assert result.command.status == RoutineApprovalDeliveryState.ACCEPTED
    assert result.command.receipt_digest
    assert projection.status == RoutineApprovalStatus.AUTHORIZING
    assert run.outcome == RoutineRunOutcome.WORKING


@pytest.mark.django_db
def test_earlier_occurrence_waits_for_effective_cancel_before_replacement(
    approval_account,
):
    projection = apply_routine_approval_requested_event(
        _approval_event(approval_account)
    ).approval
    routine = approval_account[5]
    next_due = BASE + timedelta(days=1)
    routine.next_run_at = next_due
    routine.save(update_fields=("next_run_at", "updated_at"))
    candidate = DueRoutineCandidate(
        routine_id=routine.id,
        scheduled_at=next_due,
        observed_revision=routine.revision,
        observed_schedule_generation=routine.schedule_generation,
    )

    pending = admit_due_candidate(candidate, now=next_due)

    assert pending.result_code == OCCURRENCE_REPLACEMENT_PENDING
    replacement = pending.occurrence
    assert replacement is not None
    command = RoutineApprovalCommand.objects.get(
        approval=projection,
        kind=RoutineApprovalCommandKind.CANCEL_WAIT,
    )
    lease = claim_pending_routine_approval_commands(now=next_due)[0]
    assert settle_routine_approval_command(
        lease,
        status=RoutineApprovalDeliveryState.ACCEPTED,
        receipt={
            "code": "WAIT_CANCELLED",
            "routine_execution_id": str(projection.execution_id),
            "fence": 4,
            "status": "cancelled",
            "replayed": False,
        },
        now=next_due,
    )
    command.refresh_from_db()
    assert command.status == RoutineApprovalDeliveryState.ACCEPTED

    admitted = admit_due_candidate(candidate, now=next_due)

    assert admitted.result_code == OCCURRENCE_ADMITTED
    assert admitted.occurrence == replacement
    assert admitted.run is not None
    assert admitted.outbox is not None
    assert admitted.run.outcome == RoutineRunOutcome.QUEUED


@pytest.mark.django_db
def test_owner_decision_api_returns_pending_delivery_state(approval_account):
    user, workspace, _ally, _binding, _conversation, routine, _occurrence, _run = (
        approval_account
    )
    projection = apply_routine_approval_requested_event(
        _approval_event(approval_account)
    ).approval
    session = issue_session(user, client_kind=SessionClientKind.NATIVE)
    response = Client().post(
        f"/api/v1/workspaces/{workspace.id}/routines/{routine.id}/"
        f"approvals/{projection.id}/decision",
        data='{"decision":"approve"}',
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {session.access_token}",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 202
    body = response.json()["data"]
    assert body["approval_request_id"] == str(projection.approval_request_id)
    assert body["status"] == RoutineApprovalStatus.DECISION_RECORDED
    assert body["delivery_status"] == RoutineApprovalDeliveryState.PENDING
