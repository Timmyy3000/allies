import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.test import override_settings

from allies.gateways.contracts import RoutineDispatchReceipt, canonical_fingerprint
from allies.models import Ally, AllyBinding
from auths.models import User
from chat.models import Conversation
from routines.models import (
    RoutineDispatchOutbox,
    RoutineOccurrence,
    RoutineOccurrenceDisposition,
    RoutineRunOutcome,
    RoutineRunSnapshot,
    RoutineState,
)
from routines.services.dispatch import (
    claim_pending_routine_dispatches,
    dispatch_pending_routine_outboxes,
    settle_routine_dispatch,
)
from routines.services.management import create_routine_intent, update_routine_intent
from routines.services.scheduler import (
    OCCURRENCE_SKIPPED_ACTIVE,
    STALE_DUE_CANDIDATE,
    admit_due_candidate,
    admit_due_routines,
    due_routine_candidates,
)
from workspaces.models import Membership, Workspace


@pytest.fixture
def scheduler_account(db):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Routine scheduler")
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
    AllyBinding.objects.create(ally=ally)
    conversation = Conversation.objects.create(ally=ally)
    return user, workspace, ally, conversation


def _schedule(kind="recurring"):
    if kind == "once":
        return {
            "kind": "once",
            "local_at": "2026-09-10T09:00:00",
            "timezone": "Europe/Berlin",
        }
    return {
        "kind": "recurring",
        "frequency": "daily",
        "local_time": "09:00:00",
        "timezone": "Europe/Berlin",
    }


def _create(account, *, schedule=None, title="Routine"):
    user, workspace, ally, conversation = account
    return create_routine_intent(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        main_conversation_id=conversation.id,
        title=title,
        execution_prompt="Review the saved task",
        schedule=schedule or _schedule(),
        now=datetime(2026, 9, 10, 6, tzinfo=UTC),
    )


@pytest.mark.django_db
def test_due_admission_commits_snapshot_conversation_and_rev14_dispatch(
    scheduler_account,
):
    routine = _create(scheduler_account)
    now = datetime(2026, 9, 10, 7, tzinfo=UTC)

    report = admit_due_routines(now=now)

    assert report.as_dict() == {
        "candidates": 1,
        "admitted": 1,
        "replayed": 0,
        "skipped_active": 0,
        "stale": 0,
        "not_due": 0,
        "paused": 0,
        "exhausted": 0,
    }
    occurrence = RoutineOccurrence.objects.get(routine=routine)
    run = RoutineRunSnapshot.objects.get(occurrence=occurrence)
    outbox = RoutineDispatchOutbox.objects.get(run=run)
    command = json.loads(bytes(outbox.command_bytes))

    assert occurrence.disposition == RoutineOccurrenceDisposition.ADMITTED
    assert occurrence.delayed is False
    assert run.outcome == RoutineRunOutcome.QUEUED
    assert run.title_snapshot == "Routine"
    assert run.execution_prompt == "Review the saved task"
    assert run.main_conversation_id == routine.main_conversation_id
    assert run.run_conversation_id != run.main_conversation_id
    assert outbox.command_fingerprint == command["fingerprint"]
    assert command["kind"] == "routine.dispatch"
    assert command["routine_id"] == str(routine.id)
    assert command["routine_revision"] == 1
    assert command["schedule_generation"] == 1
    assert command["schedule"] == run.schedule_snapshot
    assert command["schedule"]["kind"] == "recurring"
    assert command["schedule"]["frequency"] == "daily"
    assert command["schedule"]["local_time"] == "09:00:00"
    assert command["schedule"]["timezone"] == "Europe/Berlin"
    assert command["scheduled_at"] == "2026-09-10T07:00:00Z"
    assert command["title_snapshot"] == "Routine"
    assert command["scope"]["cloud_binding_id"] == str(routine.binding_id)
    assert "execution_id" not in command
    assert "attempt_id" not in command
    assert "generation" not in command
    assert command["fingerprint"] == canonical_fingerprint(command)

    routine.refresh_from_db()
    assert routine.state == RoutineState.ACTIVE
    assert routine.next_run_at == datetime(2026, 9, 11, 7, tzinfo=UTC)


@pytest.mark.django_db
def test_stale_candidate_writes_no_occurrence_or_outbox(scheduler_account):
    routine = _create(scheduler_account)
    candidate = due_routine_candidates(
        now=datetime(2026, 9, 10, 7, tzinfo=UTC),
    )[0]
    user, workspace, _, _ = scheduler_account
    update_routine_intent(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=1,
        title="Renamed",
    )

    result = admit_due_candidate(
        candidate,
        now=datetime(2026, 9, 10, 7, tzinfo=UTC),
    )

    assert result.result_code == STALE_DUE_CANDIDATE
    assert not RoutineOccurrence.objects.exists()
    assert not RoutineRunSnapshot.objects.exists()
    assert not RoutineDispatchOutbox.objects.exists()


@pytest.mark.django_db
def test_same_routine_active_run_skips_without_backlog(scheduler_account):
    routine = _create(scheduler_account)
    first_now = datetime(2026, 9, 10, 7, tzinfo=UTC)
    assert admit_due_routines(now=first_now).admitted == 1
    routine.refresh_from_db()
    routine.next_run_at = datetime(2026, 9, 11, 7, tzinfo=UTC)
    routine.save(update_fields=("next_run_at", "updated_at"))

    second_now = datetime(2026, 9, 11, 7, tzinfo=UTC)
    candidate = due_routine_candidates(now=second_now)[0]
    result = admit_due_candidate(candidate, now=second_now)

    assert result.result_code == OCCURRENCE_SKIPPED_ACTIVE
    assert RoutineOccurrence.objects.filter(
        disposition=RoutineOccurrenceDisposition.SKIPPED_ACTIVE
    ).exists()
    assert RoutineRunSnapshot.objects.count() == 1
    assert RoutineDispatchOutbox.objects.count() == 1
    routine.refresh_from_db()
    assert routine.next_run_at == datetime(2026, 9, 12, 7, tzinfo=UTC)


@pytest.mark.django_db
def test_missed_one_time_admission_exhausts_schedule(scheduler_account):
    routine = _create(scheduler_account, schedule=_schedule("once"))
    report = admit_due_routines(now=datetime(2026, 9, 10, 8, tzinfo=UTC))

    assert report.admitted == 1
    routine.refresh_from_db()
    assert routine.state == RoutineState.EXHAUSTED
    assert routine.next_run_at is None
    assert RoutineOccurrence.objects.get(routine=routine).delayed is True


@pytest.mark.django_db
def test_dispatch_lease_fences_stale_worker(scheduler_account):
    _create(scheduler_account)
    admit_due_routines(now=datetime(2026, 9, 10, 7, tzinfo=UTC))
    lease = claim_pending_routine_dispatches(now=datetime(2026, 9, 10, 7, tzinfo=UTC))[
        0
    ]

    stale = lease.__class__(
        outbox_id=lease.outbox_id,
        command_id=lease.command_id,
        attempt_count=lease.attempt_count,
        lease_expires_at=lease.lease_expires_at - timedelta(seconds=1),
        command_bytes=lease.command_bytes,
    )
    assert not settle_routine_dispatch(
        stale,
        status="accepted",
        now=datetime(2026, 9, 10, 7, tzinfo=UTC),
    )
    assert RoutineDispatchOutbox.objects.get().status == "in_progress"


@pytest.mark.django_db
@override_settings(ALLIES_ROUTINE_DISPATCH_ENABLED=True)
def test_dispatch_adapter_unavailable_reconciles_without_new_command(scheduler_account):
    _create(scheduler_account)
    admit_due_routines(now=datetime(2026, 9, 10, 7, tzinfo=UTC))

    report = dispatch_pending_routine_outboxes(now=datetime(2026, 9, 10, 7, tzinfo=UTC))

    assert report.claimed == 1
    assert report.deferred == 1
    assert report.reconciliation == 1
    assert RoutineDispatchOutbox.objects.get().status == "reconciliation_needed"
    assert RoutineDispatchOutbox.objects.count() == 1


@pytest.mark.django_db
@override_settings(ALLIES_ROUTINE_DISPATCH_ENABLED=True)
def test_dispatch_accepts_matching_foundry_receipt_without_rebuilding_command(
    scheduler_account, monkeypatch
):
    _create(scheduler_account)
    admit_due_routines(now=datetime(2026, 9, 10, 7, tzinfo=UTC))
    outbox = RoutineDispatchOutbox.objects.get()
    command = json.loads(bytes(outbox.command_bytes))
    captured = {}

    def accept(*, raw_body):
        captured["body"] = raw_body
        values = {
            "schema_version": "v1",
            "kind": "routine.dispatch_receipt",
            "producer": "foundry",
            "service_identity": "foundry-service",
            "command_id": command["command_id"],
            "idempotency_key": command["idempotency_key"],
            "outcome": "accepted",
            "occurrence_id": command["occurrence_id"],
            "run_id": command["run_id"],
            "execution_id": str(uuid4()),
            "attempt_id": str(uuid4()),
            "generation": 1,
            "acceptance_is_completion": False,
            "scope": command["scope"],
            "issued_at": "2026-09-10T07:00:01Z",
            "deadline_at": "2026-09-10T07:01:01Z",
            "fingerprint": "",
        }
        values["fingerprint"] = canonical_fingerprint(values)
        return RoutineDispatchReceipt.model_validate(values)

    monkeypatch.setattr("routines.services.dispatch.accept_routine_dispatch", accept)
    report = dispatch_pending_routine_outboxes(now=datetime(2026, 9, 10, 7, tzinfo=UTC))

    assert report.claimed == 1
    assert report.accepted == 1
    assert captured["body"] == bytes(outbox.command_bytes)
    outbox.refresh_from_db()
    assert outbox.status == "accepted"
    assert outbox.execution_id is not None
    assert outbox.attempt_id is not None
    assert outbox.generation == 1
    assert outbox.receipt_digest
