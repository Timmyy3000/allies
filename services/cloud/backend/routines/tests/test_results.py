import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from django.test import Client, override_settings

from activities.models import (
    RoutineResultContext,
    RoutineResultInsertionState,
    RoutineResultProjection,
    RoutineResultReceipt,
)
from allies.gateways.contracts import (
    ExecutionCommand,
    RoutineDispatchReceipt,
    canonical_fingerprint,
)
from allies.models import Ally, AllyBinding
from auths.models import User
from chat.models import (
    Conversation,
    DispatchOutbox,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessageSender,
)
from chat.services.dispatch import dispatch_accepted_message
from routines.models import RoutineDispatchState, RoutineRunOutcome, RoutineState
from routines.services.chat_projection import routine_chat_items
from routines.services.dispatch import (
    RoutineDispatchReconciliationConflict,
    claim_pending_routine_dispatches,
    reconcile_late_routine_dispatch_receipt,
    settle_routine_dispatch,
)
from routines.services.management import (
    create_routine_intent,
    delete_routine_intent,
    issue_deletion_confirmation,
    update_routine_intent,
)
from routines.services.results import (
    RoutineResultConflict,
    RoutineResultInvalid,
    RoutineResultUnavailable,
    complete_routine_result_insertion,
    parse_routine_result,
    pending_routine_results,
    project_routine_result,
)
from routines.services.scheduler import admit_due_routines
from workspaces.models import Membership, Workspace


@pytest.fixture
def result_account(db):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Routine results")
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
    admit_due_routines(now=datetime(2026, 9, 10, 7, tzinfo=UTC))
    routine.refresh_from_db()
    run = routine.run_snapshots.get()
    occurrence = run.occurrence
    return user, workspace, ally, conversation, routine, occurrence, run


def _event(account, *, title_snapshot=None, outcome="changed", event_id=None):
    user, workspace, ally, _conversation, routine, occurrence, run = account
    outbox = run.dispatch_outbox
    event = {
        "schema_version": "v1",
        "kind": "routine.result",
        "producer": "foundry",
        "service_identity": "foundry-service",
        "event_id": str(event_id or uuid4()),
        "event_sequence": 1,
        "routine_id": str(routine.id),
        "occurrence_id": str(occurrence.id),
        "run_id": str(run.id),
        "routine_revision": run.routine_revision,
        "execution_id": str(outbox.execution_id or uuid4()),
        "attempt_id": str(outbox.attempt_id or uuid4()),
        "generation": outbox.generation if outbox.generation is not None else 1,
        "main_conversation_id": str(run.main_conversation_id),
        "run_conversation_id": str(run.run_conversation_id),
        "outcome": outcome,
        "text": "I found one urgent message.",
        "references": [{"label": "Inbox", "url": "https://example.com/inbox"}],
        "delayed": False,
        "title_snapshot": title_snapshot or run.title_snapshot,
        "scope": {
            "kind": "workspace",
            "workspace_id": str(workspace.id),
            "owner_user_id": str(user.id),
            "ally_id": str(ally.id),
            "cloud_binding_id": str(routine.binding_id),
        },
        "issued_at": "2026-09-10T07:00:01Z",
        "deadline_at": "2026-09-10T07:00:31Z",
    }
    event["fingerprint"] = canonical_fingerprint(event)
    return event


def _accept_dispatch(account):
    run = account[-1]
    lease = claim_pending_routine_dispatches(now=datetime(2026, 9, 10, 7, tzinfo=UTC))[
        0
    ]
    execution_id = uuid4()
    attempt_id = uuid4()
    assert settle_routine_dispatch(
        lease,
        status=RoutineDispatchState.ACCEPTED,
        execution_id=execution_id,
        attempt_id=attempt_id,
        generation=1,
        receipt_digest="a" * 64,
        now=datetime(2026, 9, 10, 7, tzinfo=UTC),
    )
    run.refresh_from_db()
    return execution_id, attempt_id


def _exhaust_dispatch(account):
    base = datetime(2026, 9, 10, 7, tzinfo=UTC)
    for offset in range(5):
        lease = claim_pending_routine_dispatches(now=base + timedelta(minutes=offset))[
            0
        ]
        assert settle_routine_dispatch(
            lease,
            status=RoutineDispatchState.RECONCILIATION_NEEDED,
            safe_error_code="dispatch_response_lost",
            now=base + timedelta(minutes=offset),
        )
    assert claim_pending_routine_dispatches(now=base + timedelta(minutes=5)) == ()
    run = account[-1]
    run.dispatch_outbox.refresh_from_db()
    assert run.dispatch_outbox.status == RoutineDispatchState.RECONCILIATION_NEEDED
    assert run.dispatch_outbox.safe_error_code == "dispatch_attempts_exhausted"
    return run.dispatch_outbox


@pytest.mark.django_db
def test_result_projection_preserves_admitted_title_after_rename_and_delete(
    result_account,
):
    user, workspace, _, conversation, routine, _, run = result_account
    _accept_dispatch(result_account)
    updated = update_routine_intent(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=routine.revision,
        title="Renamed inbox",
    )
    challenge = issue_deletion_confirmation(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=updated.revision,
        main_conversation_id=conversation.id,
    )
    delete_routine_intent(
        user=user,
        workspace_id=workspace.id,
        routine_id=routine.id,
        expected_revision=updated.revision,
        main_conversation_id=conversation.id,
        confirmation_ref=challenge["confirmation_ref"],
    )

    projected = project_routine_result(_event(result_account))

    assert projected.status == "applied"
    assert projected.result.title_snapshot == run.title_snapshot == "Morning inbox"
    assert projected.result.insertion_state == RoutineResultInsertionState.PENDING
    assert projected.receipt.result_insertion == RoutineResultInsertionState.PENDING
    assert projected.result.routine.state == RoutineState.DELETED
    assert run.refresh_from_db() is None
    assert run.outcome == RoutineRunOutcome.SUCCEEDED


@pytest.mark.django_db
def test_identical_result_replay_is_deduplicated_and_conflicting_replay_is_rejected(
    result_account,
):
    _accept_dispatch(result_account)
    event = _event(result_account)
    first = project_routine_result(event)
    duplicate = project_routine_result(event)

    assert duplicate.status == "duplicate"
    assert duplicate.result.id == first.result.id
    assert RoutineResultProjection.objects.count() == 1
    assert RoutineResultReceipt.objects.count() == 1

    conflicting = dict(event)
    conflicting["text"] = "Different result"
    conflicting["fingerprint"] = canonical_fingerprint(conflicting)
    with pytest.raises(RoutineResultConflict):
        project_routine_result(conflicting)
    assert RoutineResultProjection.objects.count() == 1


@pytest.mark.django_db
@override_settings(
    ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN="event-secret",
    ALLIES_ROUTINE_RESULT_INGESTION_ENABLED=True,
)
def test_authenticated_result_ingress_replay_and_next_command_context(
    result_account,
):
    _accept_dispatch(result_account)
    event = _event(result_account)
    client = Client()
    headers = {"HTTP_AUTHORIZATION": "Bearer event-secret"}

    first = client.post(
        "/api/v1/internal/foundry/events",
        data=json.dumps(event),
        content_type="application/json",
        **headers,
    )
    duplicate = client.post(
        "/api/v1/internal/foundry/events",
        data=json.dumps(event),
        content_type="application/json",
        **headers,
    )

    assert first.status_code == duplicate.status_code == 202
    assert first.json() == {"event_id": event["event_id"], "status": "applied"}
    assert duplicate.json() == {
        "event_id": event["event_id"],
        "status": "duplicate",
    }
    assert RoutineResultProjection.objects.count() == 1
    assert RoutineResultReceipt.objects.count() == 1

    context = RoutineResultContext.objects.get()
    message = Message.objects.create(
        conversation_id=result_account[3].id,
        sequence=1,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="What changed?",
        status=MessageLifecycle.QUEUED,
        send_key_digest="b" * 64,
        content_fingerprint="c" * 64,
    )
    dispatch_accepted_message(message)
    command = ExecutionCommand.model_validate_json(
        bytes(DispatchOutbox.objects.get(message=message).command_bytes)
    )

    assert command.payload.text.count(context.context_text) == 1
    assert command.payload.text.endswith("[User message]\nWhat changed?")
    context.refresh_from_db()
    assert context.target_message_id == message.id
    assert context.consumed_at is not None


@pytest.mark.django_db
@pytest.mark.postgresql
@override_settings(
    ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN="event-secret",
    ALLIES_ROUTINE_RESULT_INGESTION_ENABLED=True,
)
def test_late_accepted_result_reconciles_exhausted_dispatch_and_projects(
    result_account,
):
    outbox = _exhaust_dispatch(result_account)
    event = _event(result_account)
    event["execution_id"] = str(uuid4())
    event["attempt_id"] = str(uuid4())
    event["generation"] = 1
    event["delayed"] = True
    event["fingerprint"] = canonical_fingerprint(event)

    command = json.loads(bytes(outbox.command_bytes))
    receipt_values = {
        "schema_version": "v1",
        "kind": "routine.dispatch_receipt",
        "producer": "foundry",
        "service_identity": "foundry-service",
        "command_id": command["command_id"],
        "idempotency_key": command["idempotency_key"],
        "outcome": "accepted",
        "occurrence_id": command["occurrence_id"],
        "run_id": command["run_id"],
        "execution_id": event["execution_id"],
        "attempt_id": event["attempt_id"],
        "generation": event["generation"],
        "acceptance_is_completion": False,
        "scope": command["scope"],
        "issued_at": "2026-09-10T07:00:01Z",
        "deadline_at": "2026-09-10T07:00:31Z",
    }
    receipt_values["fingerprint"] = canonical_fingerprint(receipt_values)
    receipt = RoutineDispatchReceipt.model_validate(receipt_values)
    response = Client().post(
        "/api/v1/internal/foundry/events",
        data=json.dumps(receipt.model_dump(mode="json")),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer event-secret",
    )
    assert response.status_code == 202
    assert response.json() == {
        "command_id": str(receipt.command_id),
        "status": "applied",
    }

    projected = project_routine_result(event)

    outbox.refresh_from_db()
    assert outbox.status == RoutineDispatchState.ACCEPTED
    assert outbox.execution_id == UUID(event["execution_id"])
    assert outbox.attempt_id == UUID(event["attempt_id"])
    assert outbox.generation == 1
    assert outbox.safe_error_code == "late_acceptance_reconciled"
    assert projected.status == "applied"
    assert projected.result.delayed is True


@pytest.mark.django_db
def test_late_result_rejects_foreign_execution_without_reopening_dispatch(
    result_account,
):
    outbox = _exhaust_dispatch(result_account)
    event = _event(result_account)
    event["execution_id"] = str(uuid4())
    event["attempt_id"] = str(uuid4())
    event["generation"] = 1
    event["fingerprint"] = canonical_fingerprint(event)
    event["scope"]["owner_user_id"] = str(uuid4())
    event["fingerprint"] = canonical_fingerprint(event)

    with pytest.raises(RoutineResultInvalid):
        project_routine_result(event)

    outbox.refresh_from_db()
    assert outbox.status == RoutineDispatchState.RECONCILIATION_NEEDED
    assert outbox.execution_id is None
    assert outbox.attempt_id is None
    assert outbox.generation is None
    assert not RoutineResultProjection.objects.exists()


@pytest.mark.django_db
def test_late_receipt_rejects_stale_command_identity_without_mutation(result_account):
    outbox = _exhaust_dispatch(result_account)
    command = json.loads(bytes(outbox.command_bytes))
    values = {
        "schema_version": "v1",
        "kind": "routine.dispatch_receipt",
        "producer": "foundry",
        "service_identity": "foundry-service",
        "command_id": command["command_id"],
        "idempotency_key": command["idempotency_key"],
        "outcome": "accepted",
        "occurrence_id": command["occurrence_id"],
        "run_id": str(uuid4()),
        "execution_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "generation": 1,
        "acceptance_is_completion": False,
        "scope": command["scope"],
        "issued_at": "2026-09-10T07:00:01Z",
        "deadline_at": "2026-09-10T07:00:31Z",
    }
    values["fingerprint"] = canonical_fingerprint(values)
    receipt = RoutineDispatchReceipt.model_validate(values)

    with pytest.raises(RoutineDispatchReconciliationConflict):
        reconcile_late_routine_dispatch_receipt(receipt)

    outbox.refresh_from_db()
    assert outbox.status == RoutineDispatchState.RECONCILIATION_NEEDED
    assert outbox.execution_id is None
    assert outbox.receipt_digest == ""


@pytest.mark.django_db
def test_late_receipt_duplicate_requires_exact_receipt_digest(result_account):
    outbox = _exhaust_dispatch(result_account)
    command = json.loads(bytes(outbox.command_bytes))
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
        "deadline_at": "2026-09-10T07:00:31Z",
    }
    values["fingerprint"] = canonical_fingerprint(values)
    receipt = RoutineDispatchReceipt.model_validate(values)
    assert reconcile_late_routine_dispatch_receipt(receipt) == "applied"

    changed = receipt.model_dump(mode="json")
    changed["deadline_at"] = "2026-09-10T07:00:30Z"
    changed["fingerprint"] = canonical_fingerprint(changed)
    changed_receipt = RoutineDispatchReceipt.model_validate(changed)
    with pytest.raises(RoutineDispatchReconciliationConflict):
        reconcile_late_routine_dispatch_receipt(changed_receipt)


@pytest.mark.django_db
def test_result_title_mismatch_is_rejected_before_projection(result_account):
    _accept_dispatch(result_account)
    event = _event(result_account, title_snapshot="Current renamed title")

    with pytest.raises(RoutineResultConflict):
        project_routine_result(event)

    assert not RoutineResultProjection.objects.exists()


@pytest.mark.django_db
def test_result_insertion_stays_pending_until_turn_boundary_completion(result_account):
    conversation = result_account[3]
    _accept_dispatch(result_account)
    event = _event(result_account, outcome="unchanged")
    projected = project_routine_result(event)
    assert list(
        pending_routine_results(conversation_id=projected.result.main_conversation_id)
    ) == [projected.result]

    inserted = complete_routine_result_insertion(
        result_id=projected.result.id,
        insertion_watermark=7,
        now=datetime(2026, 9, 10, 7, 1, tzinfo=UTC),
    )

    assert inserted.insertion_state == RoutineResultInsertionState.INSERTED
    assert inserted.insertion_watermark == 7
    assert (
        pending_routine_results(
            conversation_id=projected.result.main_conversation_id
        ).count()
        == 0
    )
    receipt = RoutineResultReceipt.objects.get(result=inserted)
    assert receipt.result_insertion == RoutineResultInsertionState.INSERTED
    assert receipt.insertion_watermark == 7
    context = RoutineResultContext.objects.get(result=inserted)
    assert context.conversation_id == conversation.id
    assert context.target_message_id is None
    assert "I found one urgent message." in context.context_text
    items = routine_chat_items(
        user=result_account[0],
        workspace_id=result_account[1].id,
        conversation_id=conversation.id,
    )
    assert [item["kind"] for item in items] == ["created", "result"]
    assert items[-1]["result_id"] == inserted.id
    assert items[-1]["title_snapshot"] == result_account[-1].title_snapshot
    assert items[-1]["result_insertion"] == RoutineResultInsertionState.INSERTED

    message = Message.objects.create(
        conversation=conversation,
        sequence=1,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="What changed?",
        status=MessageLifecycle.QUEUED,
        send_key_digest="b" * 64,
        content_fingerprint="c" * 64,
    )
    dispatch_accepted_message(message)
    outbox = DispatchOutbox.objects.get(message=message)
    command = ExecutionCommand.model_validate_json(bytes(outbox.command_bytes))
    assert context.context_text in command.payload.text
    assert command.payload.text.endswith("[User message]\nWhat changed?")
    context.refresh_from_db()
    assert context.target_message_id == message.id
    assert context.consumed_at is not None


@pytest.mark.django_db
def test_result_parser_rejects_oversized_text_and_invalid_reference(result_account):
    oversized = _event(result_account)
    oversized["text"] = "x" * (16 * 1024 + 1)
    oversized["fingerprint"] = canonical_fingerprint(oversized)
    with pytest.raises(RoutineResultInvalid):
        project_routine_result(oversized)

    for url in (
        "javascript:alert(1)",
        "https://token@example.com/path",
        "https://user:secret@example.com/path",
        "https://user%40example.com/path",
    ):
        invalid_reference = _event(result_account)
        invalid_reference["references"] = [{"label": "bad", "url": url}]
        invalid_reference["fingerprint"] = canonical_fingerprint(invalid_reference)
        with pytest.raises(RoutineResultInvalid):
            parse_routine_result(invalid_reference)

    oversized_window = _event(result_account)
    oversized_window["deadline_at"] = "2026-09-10T08:01:02Z"
    oversized_window["fingerprint"] = canonical_fingerprint(oversized_window)
    with pytest.raises(RoutineResultInvalid):
        project_routine_result(oversized_window)

    unicode_title = _event(result_account)
    unicode_title["title_snapshot"] = "🙂" * 60
    unicode_title["fingerprint"] = canonical_fingerprint(unicode_title)
    assert parse_routine_result(unicode_title).title_snapshot == "🙂" * 60


@pytest.mark.django_db
def test_result_requires_accepted_dispatch_and_matching_foundry_identity(
    result_account,
):
    with pytest.raises(RoutineResultUnavailable):
        project_routine_result(_event(result_account))
    assert not RoutineResultProjection.objects.exists()

    _accept_dispatch(result_account)
    wrong_attempt = _event(result_account)
    wrong_attempt["attempt_id"] = str(uuid4())
    wrong_attempt["fingerprint"] = canonical_fingerprint(wrong_attempt)
    with pytest.raises(RoutineResultConflict):
        project_routine_result(wrong_attempt)

    wrong_generation = _event(result_account)
    wrong_generation["generation"] = 2
    wrong_generation["fingerprint"] = canonical_fingerprint(wrong_generation)
    with pytest.raises(RoutineResultConflict):
        project_routine_result(wrong_generation)

    assert not RoutineResultProjection.objects.exists()
