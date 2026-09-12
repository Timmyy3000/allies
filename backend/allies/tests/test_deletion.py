from __future__ import annotations

from datetime import timedelta
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from allies.exceptions import FoundryGatewayUnknownOutcome
from allies.gateways.foundry import ProfileDeletionReceipt
from allies.models import (
    Ally,
    AllyBinding,
    AllyDeletionMarker,
    AllyDeletionState,
    DeletionOperation,
    DeletionOperationState,
    ProvisioningOperation,
)
from allies.services import deletion
from auths.models import User
from chat.models import Conversation
from files.models import (
    FileAllyTombstone,
    FileDirection,
    FileIOOutcome,
    FileObjectKind,
    FilePublication,
    FileStagingObject,
    FileState,
    FileVersion,
)
from files.services.cleanup import cleanup_files, mark_file_io_outcome
from files.storage import InMemoryFileObjectStore, set_file_store
from workspaces.models import Membership, Workspace


@pytest.fixture
def account(db):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Deletion workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    target = _ally(workspace, user, "Mira")
    sibling = _ally(workspace, user, "Nova")
    target_conversation = Conversation.objects.create(ally=target)
    sibling_conversation = Conversation.objects.create(ally=sibling)
    return {
        "user": user,
        "workspace": workspace,
        "target": target,
        "target_binding": target.binding,
        "target_conversation": target_conversation,
        "sibling": sibling,
        "sibling_conversation": sibling_conversation,
    }


def _ally(workspace, user, name):
    ally = Ally.objects.create(
        workspace=workspace,
        name=name,
        job="Study partner",
        personality="Calm and specific.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    binding = AllyBinding.objects.create(ally=ally)
    digest = str(ally.id).replace("-", "")
    ProvisioningOperation.objects.create(
        binding=binding,
        workspace=workspace,
        user=user,
        api_idempotency_key_digest=(digest * 2)[:64],
        content_fingerprint=(digest[::-1] * 2)[:64],
    )
    return ally


def _start(account, monkeypatch):
    monkeypatch.setattr(deletion, "_enqueue_reconciliation", lambda _id: None)
    return deletion.request_ally_deletion(
        user=account["user"],
        workspace_id=account["workspace"].id,
        ally_id=account["target"].id,
        confirmation="Mira - deletes me",
    )


def _complete_receipt(operation, *, state="complete", attempt_id=None):
    return ProfileDeletionReceipt(
        version=1,
        binding_id=str(operation.binding_id),
        operation_id=str(operation.id),
        state=state,
        attempt_id=str(attempt_id) if attempt_id else None,
        receipt_id=str(uuid4()) if state == "complete" else None,
        safe_error_code="" if state == "complete" else "runtime_cleanup_unresolved",
    )


@pytest.mark.django_db
def test_transient_object_cleanup_retries_without_operator_repair(account, monkeypatch):
    file = FileVersion.objects.create(
        workspace=account["workspace"],
        ally=account["target"],
        owner=account["user"],
        direction=FileDirection.INBOUND,
        original_name="retry.txt",
        media_type="text/plain",
        expected_size=1,
        actual_size=1,
        sha256="a" * 64,
        object_key="synthetic/retry",
        state=FileState.READY,
    )
    FileStagingObject.objects.create(
        file=file,
        key=file.object_key,
        generation=file.generation,
        write_fence=file.write_fence,
        kind=FileObjectKind.OBJECT,
        cleanup_after=timezone.now(),
        io_outcome=FileIOOutcome.COMPLETED,
    )
    operation = _start(account, monkeypatch)

    class TransientStore(InMemoryFileObjectStore):
        failed = False

        def delete(self, *, key):
            if not self.failed:
                self.failed = True
                raise OSError("synthetic transient storage failure")
            return super().delete(key=key)

    store = TransientStore()
    store.objects[file.object_key] = (b"x", "text/plain", file.sha256)
    set_file_store(store)
    monkeypatch.setattr(
        deletion,
        "request_profile_deletion",
        lambda payload: _complete_receipt(operation),
    )
    try:
        deletion.reconcile_ally_deletion(operation_id=operation.id)
        operation.refresh_from_db()
        assert operation.state == DeletionOperationState.PENDING
        assert operation.safe_error_code == "storage_cleanup_pending"
        assert (
            Ally.objects.get(pk=file.ally_id).deletion_state
            == AllyDeletionState.PENDING
        )
        assert file.object_key in store.objects
        assert FileStagingObject.objects.get(file=file).cleanup_attempts == 1
        now = timezone.now()
        DeletionOperation.objects.filter(pk=operation.id).update(next_attempt_at=now)
        FileStagingObject.objects.filter(file=file).update(cleanup_after=now)
        result = deletion.reconcile_ally_deletion(operation_id=operation.id)
        assert result.state == DeletionOperationState.COMPLETE
        assert file.object_key not in store.objects
        assert not FileVersion.objects.filter(pk=file.id).exists()
    finally:
        set_file_store(None)


@pytest.mark.django_db
def test_confirmed_delete_purges_populated_target_graph_and_keeps_sibling(
    account, monkeypatch
):
    operation = _start(account, monkeypatch)
    _populate_target_graph(account)
    monkeypatch.setattr(
        deletion,
        "request_profile_deletion",
        lambda payload: _complete_receipt(operation),
    )

    result = deletion.reconcile_ally_deletion(operation_id=operation.id)

    assert result.state == DeletionOperationState.COMPLETE
    assert not Ally.objects.filter(pk=account["target"].id).exists()
    assert Ally.objects.filter(pk=account["sibling"].id).exists()
    assert Conversation.objects.filter(pk=account["sibling_conversation"].id).exists()
    assert AllyDeletionMarker.objects.filter(
        workspace=account["workspace"], ally_id=account["target"].id
    ).exists()
    assert not DeletionOperation.objects.filter(pk=operation.id).exists()
    assert not FileAllyTombstone.objects.filter(ally_id=account["target"].id).exists()
    assert not FileVersion.objects.filter(ally_id=account["target"].id).exists()
    assert not FilePublication.objects.filter(
        binding=account["target_binding"]
    ).exists()


@pytest.mark.django_db
def test_duplicate_request_and_lost_receipt_replay_through_marker(account, monkeypatch):
    operation = _start(account, monkeypatch)
    replay = _start(account, monkeypatch)
    assert replay.id == operation.id

    monkeypatch.setattr(
        deletion,
        "request_profile_deletion",
        lambda payload: _complete_receipt(operation),
    )
    assert deletion.reconcile_ally_deletion(operation_id=operation.id).state == (
        DeletionOperationState.COMPLETE
    )

    status = deletion.get_ally_deletion(
        user=account["user"],
        workspace_id=account["workspace"].id,
        ally_id=account["target"].id,
    )
    assert status.state == DeletionOperationState.COMPLETE
    assert status.operation_id is None
    assert status.safe_error_code == ""
    assert deletion.reconcile_ally_deletion(operation_id=operation.id) is None


@pytest.mark.django_db
def test_foundry_repair_resume_preserves_failed_attempt_and_uses_resume_route(
    account, monkeypatch
):
    operation = _start(account, monkeypatch)
    failed_attempt = uuid4()
    monkeypatch.setattr(
        deletion,
        "request_profile_deletion",
        lambda payload: _complete_receipt(
            operation, state="repair_required", attempt_id=failed_attempt
        ),
    )
    deletion.reconcile_ally_deletion(operation_id=operation.id)
    operation.refresh_from_db()
    assert operation.state == DeletionOperationState.REPAIR_REQUIRED
    assert operation.foundry_attempt_id == failed_attempt
    assert Ally.objects.get(pk=account["target"].id).deletion_state == (
        AllyDeletionState.REPAIR_REQUIRED
    )

    resumed = deletion.resume_ally_deletion(
        operation_id=operation.id, expected_attempt_id=failed_attempt
    )
    assert resumed.foundry_resume_attempt_id == failed_attempt
    assert resumed.foundry_attempt_id == failed_attempt
    assert Ally.objects.get(pk=account["target"].id).deletion_state == (
        AllyDeletionState.PENDING
    )

    calls = []

    def resume(payload, expected_attempt_id):
        calls.append(expected_attempt_id)
        return _complete_receipt(resumed)

    monkeypatch.setattr(deletion, "resume_profile_deletion", resume)
    result = deletion.reconcile_ally_deletion(operation_id=operation.id)

    assert calls == [failed_attempt]
    assert result.state == DeletionOperationState.COMPLETE


def _mark_repair(account, operation, attempt):
    operation.state = DeletionOperationState.REPAIR_REQUIRED
    operation.foundry_attempt_id = attempt
    operation.attempt_id = attempt
    operation.save(
        update_fields=("state", "foundry_attempt_id", "attempt_id", "updated_at")
    )
    account["target"].deletion_state = AllyDeletionState.REPAIR_REQUIRED
    account["target"].save(update_fields=("deletion_state", "updated_at"))


@pytest.mark.django_db(transaction=True)
def test_operator_resume_command_is_idempotent_and_rejects_stale_attempt(
    account, monkeypatch
):
    operation = _start(account, monkeypatch)
    failed_attempt = uuid4()
    _mark_repair(account, operation, failed_attempt)
    enqueued = []
    monkeypatch.setattr(
        deletion,
        "_enqueue_reconciliation",
        lambda operation_id: enqueued.append(operation_id),
    )
    arguments = {
        "workspace_id": str(account["workspace"].id),
        "ally_id": str(account["target"].id),
        "expected_attempt_id": str(failed_attempt),
    }

    call_command("resume_ally_deletion", stdout=StringIO(), **arguments)
    operation.refresh_from_db()
    successor = operation.attempt_id
    assert operation.state == DeletionOperationState.PENDING
    assert operation.lifecycle_epoch == 2
    assert enqueued == [operation.id]

    call_command("resume_ally_deletion", stdout=StringIO(), **arguments)
    operation.refresh_from_db()
    assert operation.attempt_id == successor
    assert operation.lifecycle_epoch == 2
    assert enqueued == [operation.id, operation.id]

    with pytest.raises(CommandError, match="already active"):
        call_command(
            "resume_ally_deletion",
            stdout=StringIO(),
            **{
                **arguments,
                "expected_attempt_id": str(uuid4()),
            },
        )
    operation.refresh_from_db()
    assert operation.attempt_id == successor
    assert operation.lifecycle_epoch == 2


@pytest.mark.django_db(transaction=True)
def test_operator_resume_command_validates_target_scope(account, monkeypatch):
    operation = _start(account, monkeypatch)
    failed_attempt = uuid4()
    _mark_repair(account, operation, failed_attempt)
    with pytest.raises(CommandError, match="deletion operation unavailable"):
        call_command(
            "resume_ally_deletion",
            workspace_id=str(account["workspace"].id),
            ally_id=str(account["sibling"].id),
            expected_attempt_id=str(failed_attempt),
        )
    operation.refresh_from_db()
    assert operation.state == DeletionOperationState.REPAIR_REQUIRED


@pytest.mark.django_db(transaction=True)
def test_operator_resume_command_can_reconcile_to_completion(account, monkeypatch):
    operation = _start(account, monkeypatch)
    failed_attempt = uuid4()
    _mark_repair(account, operation, failed_attempt)
    queued = []
    monkeypatch.setattr(
        deletion,
        "_enqueue_reconciliation",
        lambda operation_id: queued.append(operation_id),
    )
    call_command(
        "resume_ally_deletion",
        workspace_id=str(account["workspace"].id),
        ally_id=str(account["target"].id),
        expected_attempt_id=str(failed_attempt),
        stdout=StringIO(),
    )
    operation.refresh_from_db()
    calls = []

    def resume(payload, expected_attempt_id):
        calls.append(expected_attempt_id)
        return _complete_receipt(operation)

    monkeypatch.setattr(deletion, "resume_profile_deletion", resume)
    result = deletion.reconcile_ally_deletion(operation_id=operation.id)

    assert queued == [operation.id]
    assert calls == [failed_attempt]
    assert result.state == DeletionOperationState.COMPLETE
    assert AllyDeletionMarker.objects.filter(
        workspace=account["workspace"], ally_id=account["target"].id
    ).exists()


@pytest.mark.django_db
def test_resume_rearms_only_target_exhausted_file_cleanup_and_completes(
    account, monkeypatch
):
    operation = _start(account, monkeypatch)
    now = timezone.now()
    key = "private/target/exhausted"
    file = FileVersion.objects.create(
        workspace=account["workspace"],
        ally=account["target"],
        owner=account["user"],
        direction=FileDirection.INBOUND,
        original_name="exhausted.txt",
        media_type="text/plain",
        expected_size=1,
        actual_size=1,
        sha256="a" * 64,
        object_key=key,
        state=FileState.CLEANUP_PENDING,
    )
    candidate = FileStagingObject.objects.create(
        file=file,
        key=key,
        generation=file.generation,
        write_fence=file.write_fence,
        kind=FileObjectKind.OBJECT,
        cleanup_attempts=5,
        cleanup_last_error="storage_unavailable",
        io_outcome=FileIOOutcome.AMBIGUOUS,
        version_key_marker="page-key",
        version_id_marker="page-version",
        cleanup_after=now - timedelta(seconds=1),
    )
    operation.state = DeletionOperationState.REPAIR_REQUIRED
    operation.safe_error_code = "storage_retry_exhausted"
    operation.save(update_fields=("state", "safe_error_code", "updated_at"))
    account["target"].deletion_state = AllyDeletionState.REPAIR_REQUIRED
    account["target"].save(update_fields=("deletion_state", "updated_at"))

    resumed = deletion.resume_ally_deletion(
        operation_id=operation.id, expected_attempt_id=operation.attempt_id
    )
    candidate.refresh_from_db()
    assert resumed.state == DeletionOperationState.PENDING
    assert candidate.cleanup_attempts == 0
    assert candidate.cleanup_last_error == ""
    assert candidate.cleanup_lease_until is None
    assert candidate.io_outcome == FileIOOutcome.AMBIGUOUS
    assert (candidate.version_key_marker, candidate.version_id_marker) == (
        "page-key",
        "page-version",
    )
    assert (
        mark_file_io_outcome(
            file_id=file.id,
            write_fence=candidate.write_fence,
            key=key,
            outcome=FileIOOutcome.COMPLETED,
        )
        == 1
    )

    store = InMemoryFileObjectStore()
    store.objects[key] = (b"x", "text/plain", "a" * 64)
    set_file_store(store)
    try:
        monkeypatch.setattr(
            deletion,
            "request_profile_deletion",
            lambda payload: _complete_receipt(resumed),
        )
        result = deletion.reconcile_ally_deletion(operation_id=operation.id)
    finally:
        set_file_store(None)

    assert result.state == DeletionOperationState.COMPLETE
    assert not FileVersion.objects.filter(pk=file.id).exists()


@pytest.mark.django_db
def test_deletion_file_reconcile_scopes_cleanup_behind_unrelated_backlog(
    account, monkeypatch
):
    _start(account, monkeypatch)
    now = timezone.now()
    sibling_files = [
        FileVersion(
            workspace=account["workspace"],
            ally=account["sibling"],
            owner=account["user"],
            direction=FileDirection.INBOUND,
            original_name=f"backlog-{index}.txt",
            media_type="text/plain",
            expected_size=1,
            actual_size=1,
            sha256="b" * 64,
            object_key=f"private/sibling/backlog-{index}",
            state=FileState.CLEANUP_PENDING,
        )
        for index in range(101)
    ]
    FileVersion.objects.bulk_create(sibling_files)
    sibling_candidates = [
        FileStagingObject(
            file=file,
            key=file.object_key,
            generation=file.generation,
            write_fence=file.write_fence,
            kind=FileObjectKind.OBJECT,
            io_outcome=FileIOOutcome.COMPLETED,
            cleanup_after=now,
        )
        for file in sibling_files
    ]
    FileStagingObject.objects.bulk_create(sibling_candidates)

    target_key = "private/target/behind-backlog"
    target_file = FileVersion.objects.create(
        workspace=account["workspace"],
        ally=account["target"],
        owner=account["user"],
        direction=FileDirection.INBOUND,
        original_name="target.txt",
        media_type="text/plain",
        expected_size=1,
        actual_size=1,
        sha256="c" * 64,
        object_key=target_key,
        state=FileState.CLEANUP_PENDING,
    )
    target_candidate = FileStagingObject.objects.create(
        file=target_file,
        key=target_key,
        generation=target_file.generation,
        write_fence=target_file.write_fence,
        kind=FileObjectKind.OBJECT,
        io_outcome=FileIOOutcome.COMPLETED,
        cleanup_after=now,
    )

    store = InMemoryFileObjectStore()
    for file in [*sibling_files, target_file]:
        store.objects[file.object_key] = (b"x", "text/plain", file.sha256)
    set_file_store(store)
    try:
        global_result = cleanup_files(now=now, limit=100)
        target_result = cleanup_files(now=now, limit=100, ally_id=account["target"].id)
    finally:
        set_file_store(None)

    target_candidate.refresh_from_db()
    assert global_result.deleted == 100
    assert target_result.deleted == 1
    assert target_candidate.deleted_at is not None


@pytest.mark.django_db
def test_unknown_writer_candidate_blocks_cleanup_without_storage_call(account):
    store = InMemoryFileObjectStore()
    set_file_store(store)
    try:
        now = timezone.now()
        file = FileVersion.objects.create(
            workspace=account["workspace"],
            ally=account["target"],
            owner=account["user"],
            direction=FileDirection.INBOUND,
            original_name="pending.txt",
            media_type="text/plain",
            expected_size=1,
            actual_size=1,
            sha256="a" * 64,
            object_key="private/target/pending.txt",
            state=FileState.CLEANUP_PENDING,
            cleanup_after=now,
        )
        candidate = FileStagingObject.objects.create(
            file=file,
            key=file.object_key,
            generation=file.generation,
            write_fence=file.write_fence,
            kind=FileObjectKind.OBJECT,
            io_outcome=FileIOOutcome.IN_FLIGHT,
            cleanup_after=now,
        )

        report = cleanup_files(now=now)

        candidate.refresh_from_db()
        assert report.claimed == 0
        assert candidate.deleted_at is None
        assert file.state == FileState.CLEANUP_PENDING
        assert store.objects == {}
    finally:
        set_file_store(None)


@pytest.mark.django_db
def test_unknown_foundry_outcome_is_retryable_and_does_not_report_success(
    account, monkeypatch
):
    operation = _start(account, monkeypatch)
    monkeypatch.setattr(
        deletion,
        "request_profile_deletion",
        lambda payload: (_ for _ in ()).throw(
            FoundryGatewayUnknownOutcome("lost response")
        ),
    )

    result = deletion.reconcile_ally_deletion(operation_id=operation.id)

    assert result.state == DeletionOperationState.PENDING
    operation.refresh_from_db()
    assert operation.safe_error_code == "foundry_outcome_unknown"
    assert Ally.objects.get(pk=account["target"].id).deletion_state == (
        AllyDeletionState.PENDING
    )


def _populate_target_graph(account):
    from activities.models import (
        Activity,
        Approval,
        FoundryEventReceipt,
        ProjectionState,
        RoutineResultContext,
        RoutineResultOutcome,
        RoutineResultProjection,
        RoutineResultReceipt,
    )
    from chat.models import (
        AssistantReply,
        DispatchOutbox,
        Message,
        MessageLifecycle,
        MessageOrigin,
        MessageSender,
    )
    from routines.models import (
        Routine,
        RoutineApprovalCommand,
        RoutineApprovalCommandKind,
        RoutineApprovalProjection,
        RoutineDeletionConfirmation,
        RoutineDispatchOutbox,
        RoutineManagementReceipt,
        RoutineOccurrence,
        RoutineOccurrenceDisposition,
        RoutineRunOutcome,
        RoutineRunSnapshot,
        RoutineState,
    )

    now = timezone.now()
    user = account["user"]
    workspace = account["workspace"]
    ally = account["target"]
    binding = account["target_binding"]
    conversation = account["target_conversation"]
    message = Message.objects.create(
        conversation=conversation,
        sequence=1,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="Delete graph fixture",
        status=MessageLifecycle.COMPLETED,
        foundry_binding_id=binding.id,
        send_key_digest="b" * 64,
        content_fingerprint="c" * 64,
    )
    AssistantReply.objects.create(message=message, content="Reply")
    DispatchOutbox.objects.create(message=message)
    approval = Approval.objects.create(
        workspace=workspace,
        ally=ally,
        conversation=conversation,
        message=message,
        approval_request_id=uuid4(),
        cloud_binding_id=binding.id,
        execution_id=uuid4(),
        attempt_id=uuid4(),
        generation=1,
        attempt_sequence=1,
        action_kind="send",
        action_label="Send reply",
        action_preview="Reply",
        requested_at=now,
        expires_at=now + timedelta(hours=1),
    )
    Activity.objects.create(
        conversation=conversation,
        message=message,
        approval=approval,
        sequence=1,
        conversation_turn_ordinal=1,
        generation=1,
        attempt_id=uuid4(),
        attempt_sequence=1,
        event_id=uuid4(),
        event_type="turn.completed",
        kind="assistant",
        state=ProjectionState.COMPLETED,
        event_fingerprint="canonical-json-sha256:v1:" + "a" * 64,
    )
    FoundryEventReceipt.objects.create(
        conversation=conversation,
        message=message,
        event_id=uuid4(),
        event_dedupe_key="target-event",
        attempt_id=uuid4(),
        generation=1,
        attempt_sequence=1,
        event_fingerprint="canonical-json-sha256:v1:" + "b" * 64,
        result="applied",
    )

    publication = FilePublication.objects.create(
        binding=binding,
        source_message=message,
        state="ready",
    )
    file = FileVersion.objects.create(
        workspace=workspace,
        ally=ally,
        owner=user,
        source_message=message,
        direction=FileDirection.OUTBOUND,
        original_name="fixture.txt",
        media_type="text/plain",
        expected_size=1,
        actual_size=1,
        sha256="d" * 64,
        state=FileState.DELETED,
        publication=publication,
    )
    FileStagingObject.objects.create(
        file=file,
        key="private/target/fixture.txt",
        generation=file.generation,
        write_fence=file.write_fence,
        kind=FileObjectKind.OBJECT,
        io_outcome=FileIOOutcome.COMPLETED,
        deleted_at=now,
        cleanup_after=now,
    )
    from files.models import FileDraftFile, FileDraftRecovery, MessageFile

    MessageFile.objects.create(message=message, file=file, position=0)
    draft = FileDraftRecovery.objects.create(
        message=message, owner=user, ally=ally, content="draft"
    )
    FileDraftFile.objects.create(draft=draft, file=file, position=0)

    routine = Routine.objects.create(
        workspace=workspace,
        owner=user,
        ally=ally,
        binding=binding,
        main_conversation_id=conversation.id,
        source_message=message,
        title="Daily fixture",
        execution_prompt="Review the fixture.",
        schedule={
            "kind": "recurring",
            "frequency": "daily",
            "local_time": "09:00:00",
            "timezone": "UTC",
        },
        state=RoutineState.ACTIVE,
    )
    confirmation = RoutineDeletionConfirmation.objects.create(
        reference_digest="e" * 64,
        routine=routine,
        workspace=workspace,
        owner=user,
        ally=ally,
        binding=binding,
        main_conversation_id=conversation.id,
        expected_revision=1,
        issued_at=now,
    )
    RoutineManagementReceipt.objects.create(
        confirmation=confirmation,
        routine=routine,
        workspace=workspace,
        owner=user,
        ally=ally,
        binding=binding,
        operation="delete",
        result_code="routine_deleted",
        revision=1,
        schedule_state="active",
        issued_at=now,
    )
    occurrence = RoutineOccurrence.objects.create(
        routine=routine,
        workspace=workspace,
        owner=user,
        ally=ally,
        binding=binding,
        scheduled_at=now + timedelta(hours=1),
        observed_revision=1,
        observed_schedule_generation=1,
        disposition=RoutineOccurrenceDisposition.ADMITTED,
    )
    run = RoutineRunSnapshot.objects.create(
        occurrence=occurrence,
        routine=routine,
        workspace=workspace,
        owner=user,
        ally=ally,
        binding=binding,
        routine_revision=1,
        schedule_generation=1,
        title_snapshot="Daily fixture",
        execution_prompt="Review the fixture.",
        schedule_snapshot=routine.schedule,
        timezone="UTC",
        scheduled_at=occurrence.scheduled_at,
        occurrence_disposition=RoutineOccurrenceDisposition.ADMITTED,
        main_conversation_id=conversation.id,
        run_conversation_id=uuid4(),
        outcome=RoutineRunOutcome.QUEUED,
    )
    RoutineDispatchOutbox.objects.create(
        routine=routine,
        occurrence=occurrence,
        run=run,
        command_id=uuid4(),
        idempotency_key=uuid4(),
    )
    routine_approval = RoutineApprovalProjection.objects.create(
        routine=routine,
        occurrence=occurrence,
        run=run,
        workspace=workspace,
        owner=user,
        ally=ally,
        binding=binding,
        approval_request_id=uuid4(),
        action_attempt_id=uuid4(),
        execution_id=uuid4(),
        attempt_id=uuid4(),
        generation=1,
        event_id=uuid4(),
        event_sequence=1,
        event_fingerprint="canonical-json-sha256:v1:" + "f" * 64,
        action_digest="1" * 64,
        provider_idempotency_key="target-routine-approval",
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    RoutineApprovalCommand.objects.create(
        approval=routine_approval,
        kind=RoutineApprovalCommandKind.DECISION,
        command_id=uuid4(),
        idempotency_key=uuid4(),
        command_bytes=b"{}",
        command_byte_length=2,
        command_sha256="3" * 64,
        command_fingerprint="canonical-json-sha256:v1:" + "4" * 64,
    )
    result = RoutineResultProjection.objects.create(
        event_id=uuid4(),
        event_sequence=1,
        routine=routine,
        occurrence=occurrence,
        run=run,
        routine_revision=1,
        execution_id=uuid4(),
        attempt_id=uuid4(),
        generation=1,
        main_conversation_id=conversation.id,
        run_conversation_id=run.run_conversation_id,
        workspace=workspace,
        owner=user,
        ally=ally,
        binding=binding,
        title_snapshot="Daily fixture",
        outcome=RoutineResultOutcome.CHANGED,
        text="Result",
        issued_at=now,
        deadline_at=now + timedelta(seconds=30),
        fingerprint="canonical-json-sha256:v1:" + "2" * 64,
    )
    RoutineResultReceipt.objects.create(
        result=result, event_id=uuid4(), event_sequence=1
    )
    RoutineResultContext.objects.create(
        result=result,
        conversation=conversation,
        context_text="Result context",
        insertion_watermark=1,
    )
