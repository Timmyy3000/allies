from hashlib import sha256
from io import BytesIO

import pytest
from django.core.cache import cache
from django.db import transaction

from allies.gateways.contracts import ExecutionCommand
from allies.models import Ally, AllyBinding, BindingStatus
from auths.models import User
from chat.exceptions import ConversationUnavailable, IdempotencyConflict, TurnConflict
from chat.models import (
    DispatchOutbox,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessagePreparation,
    MessageSender,
)
from chat.services.dispatch import ensure_dispatch_after_accept
from chat.services.messages import accept_message, message_response, retry_message
from files.exceptions import FileConflict, FileScopeUnavailable, FileUnavailable
from files.models import (
    FileDirection,
    FileDraftRecovery,
    FileObjectKind,
    FileStagingObject,
    FileState,
    FileStorageAccount,
    FileVersion,
    MessageFile,
)
from files.services.access import accepted_file_stream
from files.services.cleanup import tombstone_ally_files
from files.services.intake import (
    InspectionResult,
    promote_inspected_file,
    receive_file,
    reserve_send,
)
from files.services.preparation import (
    arm_file_message,
    cancel_file_message,
    discard_file_draft,
    file_draft,
    reconcile_file_message,
    recover_file_preparation,
    remove_inbound_file,
    retry_inbound_file,
)
from files.storage import InMemoryFileObjectStore, set_file_store
from workspaces.models import Membership, Workspace


@pytest.fixture
def file_message(settings, db):
    cache.clear()
    settings.ALLIES_AUTH_DIGEST_KEY = "d" * 32
    settings.ALLIES_FILE_ADMISSION_ENABLED = True
    settings.ALLIES_FILE_STORAGE_ENABLED = True
    settings.ALLIES_FILE_INSPECTION_ENABLED = True
    settings.ALLIES_FILE_INPUT_DELIVERY_ENABLED = False
    settings.ALLIES_FILE_STORAGE_CAPACITY_BYTES = 100_000_000
    set_file_store(InMemoryFileObjectStore())
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Personal")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study",
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    binding = AllyBinding.objects.create(
        ally=ally,
        status=BindingStatus.BOUND,
        receipt_digest="b" * 64,
    )
    from chat.models import Conversation

    conversation = Conversation.objects.create(ally=ally)
    yield user, workspace, ally, binding, conversation
    set_file_store(None)


def _manifest(data: bytes, client_id: str) -> dict:
    return {
        "client_id": client_id,
        "name": "report.pdf",
        "size": len(data),
        "sha256": sha256(data).hexdigest(),
    }


def _ready(
    *,
    user,
    workspace,
    ally,
    conversation,
    data: bytes,
    client_id: str,
    content="",
    key="file-preparation-key-0001",
):
    reservation = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content=content,
        files=[_manifest(data, client_id)],
        key=key,
    )
    file = receive_file(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        file_id=reservation.files[0].id,
        generation=1,
        content_length=str(len(data)),
        stream=BytesIO(data),
    )
    ready = promote_inspected_file(
        file_id=file.id,
        generation=1,
        result=InspectionResult(
            size=len(data),
            sha256=sha256(data).hexdigest(),
            media_type="application/pdf",
            clean=True,
        ),
    )
    reconcile_file_message(message_id=reservation.message.id)
    reservation.message.refresh_from_db()
    return reservation.message, ready


@pytest.mark.django_db
def test_ready_manifest_waits_for_delivery_gate_and_keeps_text_contract(
    file_message, settings
):
    user, workspace, ally, _binding, conversation = file_message
    message, file = _ready(
        user=user,
        workspace=workspace,
        ally=ally,
        conversation=conversation,
        data=b"private bytes",
        client_id="550e8400-e29b-41d4-a716-446655440001",
    )

    assert message.preparation == MessagePreparation.READY
    assert message.send_armed is True
    assert message.execution_claimed_at is None
    assert not DispatchOutbox.objects.filter(message=message).exists()

    assert recover_file_preparation() == 0
    settings.ALLIES_FILE_INPUT_DELIVERY_ENABLED = True
    assert recover_file_preparation() == 1
    assert recover_file_preparation() == 0

    outbox = DispatchOutbox.objects.get(message=message)
    command = ExecutionCommand.model_validate_json(bytes(outbox.command_bytes))
    assert command.payload.text == ""
    assert command.payload.files and command.payload.files[0].file_id == file.id
    assert command.payload.files[0].sha256 == file.sha256
    assert message_response(message)["files"] == [
        {
            "id": str(file.id),
            "name": "report.pdf",
            "size": len(b"private bytes"),
            "state": FileState.READY,
        }
    ]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("content", "key", "client_id"),
    (
        (
            "Review this report",
            "file-execution-retry-key-0001",
            "550e8400-e29b-41d4-a716-446655440011",
        ),
        ("", "file-execution-retry-key-0002", "550e8400-e29b-41d4-a716-446655440012"),
    ),
)
def test_execution_retry_reuses_ready_file_manifest_and_authorizes_fetch(
    file_message, settings, content, key, client_id
):
    user, workspace, ally, binding, conversation = file_message
    greeting = Message.objects.create(
        conversation=conversation,
        sequence=1,
        sender=MessageSender.ASSISTANT,
        origin=MessageOrigin.ONBOARDING,
        content="Hello",
        status=MessageLifecycle.COMPLETED,
    )
    data = b"retry input bytes"
    settings.ALLIES_FILE_INPUT_DELIVERY_ENABLED = True
    original, file = _ready(
        user=user,
        workspace=workspace,
        ally=ally,
        conversation=conversation,
        data=data,
        client_id=client_id,
        content=content,
        key=key,
    )
    generation = file.generation
    Message.objects.filter(pk=original.pk).update(
        status=MessageLifecycle.FAILED, retry_allowed=True
    )

    retried = retry_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=original.id,
        idempotency_key=f"{key}-retry",
    ).message
    replay = retry_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=original.id,
        idempotency_key=f"{key}-retry",
    )
    assert replay.replayed and replay.message.id == retried.id
    if content:
        with pytest.raises(IdempotencyConflict):
            accept_message(
                user=user,
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                content=content,
                idempotency_key=f"{key}-retry",
            )

    links = list(
        MessageFile.objects.filter(message=retried, removed_at__isnull=True).order_by(
            "position", "id"
        )
    )
    assert retried.content == content
    assert retried.preparation == MessagePreparation.READY
    assert retried.preparation_revision == 1
    assert retried.send_armed is True
    assert [link.file_id for link in links] == [file.id]
    file.refresh_from_db()
    assert (file.source_message_id, file.generation) == (original.id, generation)

    outbox = DispatchOutbox.objects.get(message=retried)
    assert outbox.file_manifest == [
        {
            "file_id": str(file.id),
            "name": file.original_name,
            "media_type": file.media_type,
            "size": file.actual_size,
            "sha256": file.sha256,
        }
    ]
    command = ExecutionCommand.model_validate_json(bytes(outbox.command_bytes))
    assert (
        command.payload.bootstrap
        and command.payload.bootstrap.message_id == greeting.id
    )
    assert command.payload.files and command.payload.files[0].file_id == file.id
    accepted = accepted_file_stream(
        binding_id=binding.id, message_id=retried.id, file_id=file.id
    )
    assert b"".join(accepted.content) == data

    Message.objects.filter(pk=retried.pk).update(
        status=MessageLifecycle.FAILED, retry_allowed=True
    )
    with pytest.raises(TurnConflict):
        retry_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            message_id=retried.id,
            idempotency_key=f"{key}-retry-again",
        )
    assert not Message.objects.filter(retry_of=retried).exists()


@pytest.mark.django_db
def test_execution_retry_rejects_a_ready_file_owned_by_another_member(
    file_message, settings
):
    user, workspace, ally, _binding, conversation = file_message
    conversation.is_default = False
    conversation.save(update_fields=("is_default", "updated_at"))
    settings.ALLIES_FILE_INPUT_DELIVERY_ENABLED = True
    original, file = _ready(
        user=user,
        workspace=workspace,
        ally=ally,
        conversation=conversation,
        data=b"private bytes",
        client_id="550e8400-e29b-41d4-a716-446655440013",
        key="file-execution-retry-key-0003",
    )
    foreign = User.objects.create_user()
    Membership.objects.create(
        workspace=workspace, user=foreign, role="owner", status="active"
    )
    file.owner = foreign
    file.save(update_fields=("owner", "updated_at"))
    Message.objects.filter(pk=original.pk).update(
        status=MessageLifecycle.FAILED, retry_allowed=True
    )

    with pytest.raises(TurnConflict):
        retry_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            message_id=original.id,
            idempotency_key="file-execution-retry-key-0003-retry",
        )
    assert not Message.objects.filter(retry_of=original).exists()


@pytest.mark.django_db
def test_execution_retry_rejects_a_tombstoned_ally(file_message, settings):
    user, workspace, ally, _binding, conversation = file_message
    conversation.is_default = False
    conversation.save(update_fields=("is_default", "updated_at"))
    settings.ALLIES_FILE_INPUT_DELIVERY_ENABLED = True
    original, _file = _ready(
        user=user,
        workspace=workspace,
        ally=ally,
        conversation=conversation,
        data=b"private bytes",
        client_id="550e8400-e29b-41d4-a716-446655440014",
        key="file-execution-retry-key-0004",
    )
    Message.objects.filter(pk=original.pk).update(
        status=MessageLifecycle.FAILED, retry_allowed=True
    )
    tombstone_ally_files(ally_id=ally.id)
    messages = Message.objects.filter(conversation=conversation).count()
    outboxes = DispatchOutbox.objects.filter(message__conversation=conversation).count()

    with pytest.raises(ConversationUnavailable):
        retry_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            message_id=original.id,
            idempotency_key="file-execution-retry-key-0004-retry",
        )
    assert Message.objects.filter(conversation=conversation).count() == messages
    assert (
        DispatchOutbox.objects.filter(message__conversation=conversation).count()
        == outboxes
    )


@pytest.mark.django_db
def test_retry_preserves_ready_bytes_then_remove_and_cancel_recover_draft(
    file_message,
):
    user, workspace, ally, _binding, conversation = file_message
    first_data, second_data = b"first", b"second"
    reservation = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Keep this draft",
        files=[
            _manifest(first_data, "550e8400-e29b-41d4-a716-446655440001"),
            _manifest(second_data, "550e8400-e29b-41d4-a716-446655440002"),
        ],
        key="file-preparation-key-0002",
    )
    first, second = reservation.files
    received = receive_file(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        file_id=first.id,
        generation=1,
        content_length=str(len(first_data)),
        stream=BytesIO(first_data),
    )
    first = promote_inspected_file(
        file_id=received.id,
        generation=1,
        result=InspectionResult(
            len(first_data), sha256(first_data).hexdigest(), "application/pdf", True
        ),
    )
    first_key = first.object_key
    second.state = FileState.REJECTED
    second.save(update_fields=("state",))
    reconcile_file_message(message_id=reservation.message.id)
    reservation.message.refresh_from_db()
    assert reservation.message.preparation == MessagePreparation.FAILED

    retried = retry_inbound_file(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        file_id=second.id,
        generation=1,
    )
    first.refresh_from_db()
    assert retried.generation == 2
    assert retried.state == FileState.PENDING
    assert (first.generation, first.object_key, first.sha256) == (
        1,
        first_key,
        sha256(first_data).hexdigest(),
    )

    received = receive_file(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        file_id=retried.id,
        generation=2,
        content_length=str(len(second_data)),
        stream=BytesIO(second_data),
    )
    promote_inspected_file(
        file_id=received.id,
        generation=2,
        result=InspectionResult(
            len(second_data), sha256(second_data).hexdigest(), "application/pdf", True
        ),
    )
    reconcile_file_message(message_id=reservation.message.id)
    reservation.message.refresh_from_db()
    assert reservation.message.preparation == MessagePreparation.READY
    assert reservation.message.send_armed is False
    ensure_dispatch_after_accept(reservation.message)
    assert not DispatchOutbox.objects.filter(message=reservation.message).exists()
    armed = arm_file_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=reservation.message.id,
        revision=reservation.message.preparation_revision,
    )
    assert armed.send_armed is True
    assert not DispatchOutbox.objects.filter(message=reservation.message).exists()
    reservation.message.refresh_from_db()
    removed = remove_inbound_file(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=reservation.message.id,
        file_id=first.id,
        revision=reservation.message.preparation_revision,
    )
    repeated = remove_inbound_file(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=reservation.message.id,
        file_id=first.id,
        revision=removed.preparation_revision - 1,
    )
    assert repeated.preparation == MessagePreparation.NEEDS_RETRY
    assert MessageFile.objects.get(message=reservation.message, file=first).removed_at
    assert removed.send_armed is False

    cancelled = cancel_file_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=reservation.message.id,
        revision=removed.preparation_revision,
    )
    replayed = cancel_file_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=reservation.message.id,
        revision=1,
    )
    reservation.message.refresh_from_db()
    assert reservation.message.status == MessageLifecycle.STOPPED
    assert reservation.message.content == ""
    assert reservation.message.preparation == MessagePreparation.CANCELLED
    assert cancelled.draft.id == replayed.draft.id
    assert cancelled.draft.content == "Keep this draft"
    assert [file.id for file in cancelled.files] == [second.id]
    assert FileDraftRecovery.objects.get(message=reservation.message) == cancelled.draft


@pytest.mark.django_db
def test_removing_ready_file_persists_cleanup_and_repairs_repeat(file_message):
    user, workspace, ally, _binding, conversation = file_message
    message, file = _ready(
        user=user,
        workspace=workspace,
        ally=ally,
        conversation=conversation,
        data=b"ready cleanup bytes",
        client_id="550e8400-e29b-41d4-a716-446655440099",
    )

    with pytest.raises(RuntimeError, match="rollback"), transaction.atomic():
        remove_inbound_file(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            message_id=message.id,
            file_id=file.id,
            revision=message.preparation_revision,
        )
        raise RuntimeError("rollback")

    file.refresh_from_db()
    assert file.state == FileState.READY
    assert MessageFile.objects.get(message=message, file=file).removed_at is None
    assert not FileStagingObject.objects.filter(
        file=file, kind=FileObjectKind.OBJECT
    ).exists()

    removed = remove_inbound_file(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=message.id,
        file_id=file.id,
        revision=message.preparation_revision,
    )

    file.refresh_from_db()
    assert removed.preparation == MessagePreparation.NEEDS_RETRY
    assert file.state == FileState.CLEANUP_PENDING
    candidate = FileStagingObject.objects.get(file=file, kind=FileObjectKind.OBJECT)

    candidate.delete()
    FileVersion.objects.filter(pk=file.id).update(state=FileState.READY)
    repeated = remove_inbound_file(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=message.id,
        file_id=file.id,
        revision=removed.preparation_revision,
    )

    assert repeated.preparation == MessagePreparation.NEEDS_RETRY
    file.refresh_from_db()
    assert file.state == FileState.CLEANUP_PENDING
    assert FileStagingObject.objects.filter(
        file=file, kind=FileObjectKind.OBJECT
    ).exists()


@pytest.mark.django_db
def test_file_message_cannot_cancel_after_claim(file_message, settings):
    user, workspace, ally, _binding, conversation = file_message
    message, _file = _ready(
        user=user,
        workspace=workspace,
        ally=ally,
        conversation=conversation,
        data=b"private bytes",
        client_id="550e8400-e29b-41d4-a716-446655440001",
    )
    settings.ALLIES_FILE_INPUT_DELIVERY_ENABLED = True
    ensure_dispatch_after_accept(message)

    with pytest.raises(FileConflict):
        cancel_file_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            message_id=message.id,
            revision=message.preparation_revision,
        )


@pytest.mark.django_db
@pytest.mark.parametrize("foreign_scope", ("ally", "workspace", "owner"))
def test_manifest_freeze_rejects_corrupt_file_ancestry(
    file_message, settings, foreign_scope
):
    user, workspace, ally, _binding, conversation = file_message
    message, original = _ready(
        user=user,
        workspace=workspace,
        ally=ally,
        conversation=conversation,
        data=b"private bytes",
        client_id="550e8400-e29b-41d4-a716-446655440001",
    )
    foreign_workspace = workspace
    foreign_ally = ally
    foreign_owner = user
    if foreign_scope == "ally":
        foreign_ally = Ally.objects.create(
            workspace=workspace,
            name="Other",
            job="Study",
            personality="Calm",
            appearance_catalog_version="v1",
            appearance_key="sunrise",
        )
    elif foreign_scope == "workspace":
        foreign_owner = User.objects.create_user()
        foreign_workspace = Workspace.objects.create(
            owner=foreign_owner, name="Other workspace"
        )
        Membership.objects.create(
            workspace=foreign_workspace,
            user=foreign_owner,
            role="owner",
            status="active",
        )
        foreign_ally = Ally.objects.create(
            workspace=foreign_workspace,
            name="Other",
            job="Study",
            personality="Calm",
            appearance_catalog_version="v1",
            appearance_key="sunrise",
        )
    else:
        foreign_owner = User.objects.create_user()
    foreign = FileVersion.objects.create(
        workspace=foreign_workspace,
        ally=foreign_ally,
        owner=foreign_owner,
        source_message=message,
        direction=FileDirection.INBOUND,
        original_name=original.original_name,
        media_type=original.media_type,
        expected_size=original.expected_size,
        actual_size=original.actual_size,
        sha256=original.sha256,
        object_key="immutable/corrupt",
        state=FileState.READY,
    )
    MessageFile.objects.filter(message=message, file=original).update(file=foreign)
    settings.ALLIES_FILE_INPUT_DELIVERY_ENABLED = True

    ensure_dispatch_after_accept(message)

    message.refresh_from_db()
    outbox = DispatchOutbox.objects.get(message=message)
    assert message.execution_claimed_at is None
    assert outbox.file_manifest == []


@pytest.mark.django_db
def test_retry_rejects_a_foreign_file_owner(file_message):
    user, workspace, ally, _binding, conversation = file_message
    reservation = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="",
        files=[_manifest(b"private bytes", "550e8400-e29b-41d4-a716-446655440001")],
        key="file-foreign-owner-key-0001",
    )
    file = reservation.files[0]
    file.state = FileState.REJECTED
    file.save(update_fields=("state", "updated_at"))
    foreign = User.objects.create_user()
    Membership.objects.create(
        workspace=workspace, user=foreign, role="owner", status="active"
    )

    with pytest.raises(FileScopeUnavailable):
        retry_inbound_file(
            user=foreign,
            workspace_id=workspace.id,
            ally_id=ally.id,
            file_id=file.id,
            generation=1,
        )


@pytest.mark.django_db
def test_tombstone_denies_preparation_without_mutating_file_or_account(file_message):
    user, workspace, ally, _binding, conversation = file_message
    reservation = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="",
        files=[_manifest(b"private bytes", "550e8400-e29b-41d4-a716-446655440030")],
        key="file-tombstone-preparation-key",
    )
    message = reservation.message
    file = reservation.files[0]
    account = FileStorageAccount.objects.get(workspace=workspace)
    file.state = FileState.FAILED
    file.reserved_accounted = False
    file.save(update_fields=("state", "reserved_accounted", "updated_at"))
    account.reserved_bytes = 0
    account.save(update_fields=("reserved_bytes", "updated_at"))
    tombstone_ally_files(ally_id=ally.id)
    expected_file = (file.generation, file.state, file.reserved_accounted)
    expected_message = (
        message.preparation,
        message.preparation_revision,
        message.send_armed,
    )

    with pytest.raises(FileScopeUnavailable):
        retry_inbound_file(
            user=user,
            workspace_id=workspace.id,
            ally_id=ally.id,
            file_id=file.id,
            generation=file.generation,
        )
    with pytest.raises(FileScopeUnavailable):
        arm_file_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            message_id=message.id,
            revision=message.preparation_revision,
        )
    with pytest.raises(FileScopeUnavailable):
        remove_inbound_file(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            message_id=message.id,
            file_id=file.id,
            revision=message.preparation_revision,
        )
    with pytest.raises(FileScopeUnavailable):
        cancel_file_message(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            message_id=message.id,
            revision=message.preparation_revision,
        )
    with pytest.raises(FileScopeUnavailable):
        file_draft(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            message_id=message.id,
        )
    with pytest.raises(FileScopeUnavailable):
        discard_file_draft(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            message_id=message.id,
        )

    file.refresh_from_db()
    message.refresh_from_db()
    account.refresh_from_db()
    assert (file.generation, file.state, file.reserved_accounted) == expected_file
    assert (
        message.preparation,
        message.preparation_revision,
        message.send_armed,
    ) == expected_message
    assert account.reserved_bytes == 0
    assert not FileDraftRecovery.objects.filter(message=message).exists()
    assert MessageFile.objects.filter(message=message, removed_at__isnull=True).exists()


@pytest.mark.django_db
def test_remove_then_rearm_rebuilds_frozen_manifest(file_message, settings):
    user, workspace, ally, _binding, conversation = file_message
    conversation.is_default = False
    conversation.save(update_fields=("is_default",))
    accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Earlier turn",
        idempotency_key="earlier-turn-before-file-removal",
    )
    from datetime import UTC, datetime

    from activities.models import RoutineResultContext
    from routines.services.management import create_routine_intent
    from routines.services.results import project_routine_result
    from routines.services.scheduler import admit_due_routines
    from routines.tests.test_results import _accept_dispatch, _event

    routine = create_routine_intent(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        main_conversation_id=conversation.id,
        title="File context",
        execution_prompt="Summarize results",
        schedule={
            "kind": "recurring",
            "frequency": "daily",
            "local_time": "09:00:00",
            "timezone": "Europe/Berlin",
        },
        now=datetime(2026, 9, 10, 6, tzinfo=UTC),
    )
    admit_due_routines(now=datetime(2026, 9, 10, 7, tzinfo=UTC))
    run = routine.run_snapshots.get()
    account = user, workspace, ally, conversation, routine, run.occurrence, run
    _accept_dispatch(account)
    projected = project_routine_result(_event(account))
    context = RoutineResultContext.objects.create(
        result=projected.result,
        conversation=conversation,
        context_text="Routine result: one urgent message.",
        insertion_watermark=1,
    )
    data = b"private bytes"
    reservation = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Review",
        files=[
            _manifest(data, "550e8400-e29b-41d4-a716-446655440021"),
            _manifest(data, "550e8400-e29b-41d4-a716-446655440022"),
        ],
        key="remove-then-rearm-files-key",
    )
    for file in reservation.files:
        receive_file(
            user=user,
            workspace_id=workspace.id,
            ally_id=ally.id,
            file_id=file.id,
            generation=1,
            content_length=str(len(data)),
            stream=BytesIO(data),
        )
        promote_inspected_file(
            file_id=file.id,
            generation=1,
            result=InspectionResult(
                len(data), sha256(data).hexdigest(), "application/pdf", True
            ),
        )
    reconcile_file_message(message_id=reservation.message.id)
    message = reservation.message
    message.refresh_from_db()
    settings.ALLIES_FILE_INPUT_DELIVERY_ENABLED = True
    ensure_dispatch_after_accept(message)
    original = DispatchOutbox.objects.get(message=message)
    assert len(original.file_manifest) == 2
    context.refresh_from_db()
    assert context.target_message_id == message.id
    message = remove_inbound_file(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=message.id,
        file_id=reservation.files[0].id,
        revision=message.preparation_revision,
    )
    assert not DispatchOutbox.objects.filter(message=message).exists()
    arm_file_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=message.id,
        revision=message.preparation_revision,
    )
    rebuilt = DispatchOutbox.objects.get(message=message)
    command = ExecutionCommand.model_validate_json(bytes(rebuilt.command_bytes))
    assert [str(file.file_id) for file in command.payload.files] == [
        str(reservation.files[1].id)
    ]
    assert rebuilt.command_fingerprint != original.command_fingerprint
    assert command.payload.text.count(context.context_text) == 1
    context.refresh_from_db()
    assert context.target_message_id == message.id
    assert context.consumed_at is not None


@pytest.mark.django_db
@pytest.mark.parametrize("old_state", (FileState.PENDING, FileState.FAILED))
def test_preparation_recovery_skips_unchanged_old_messages(file_message, old_state):
    user, workspace, ally, _binding, conversation = file_message
    messages = []
    for index in range(2):
        message, file = _ready(
            user=user,
            workspace=workspace,
            ally=ally,
            conversation=conversation,
            data=b"private bytes",
            client_id=f"550e8400-e29b-41d4-a716-44665544003{index}",
            key=f"preparation-recovery-fairness-{index}",
        )
        Message.objects.filter(pk=message.pk).update(
            preparation=MessagePreparation.FAILED
            if index == 0 and old_state == FileState.FAILED
            else MessagePreparation.UPLOADING,
            send_armed=False,
        )
        if index == 0:
            FileVersion.objects.filter(pk=file.pk).update(state=old_state)
        messages.append(message)
    assert recover_file_preparation(limit=1) == 1
    messages[1].refresh_from_db()
    assert messages[1].preparation == MessagePreparation.READY
    assert messages[1].send_armed
    assert recover_file_preparation(limit=1) == 0


@pytest.mark.django_db
def test_cancel_upload_releases_next_text_message(file_message):
    user, workspace, _ally, _binding, conversation = file_message
    conversation.is_default = False
    conversation.save(update_fields=("is_default",))
    reservation = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="",
        files=[_manifest(b"abc", "550e8400-e29b-41d4-a716-446655440021")],
        key="cancel-release-file-key",
    )
    next_message = accept_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Next",
        idempotency_key="cancel-release-text-key",
    ).message
    assert next_message.execution_claimed_at is None
    cancel_file_message(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=reservation.message.id,
        revision=reservation.message.preparation_revision,
    )
    next_message.refresh_from_db()
    assert next_message.execution_claimed_at is not None
    assert DispatchOutbox.objects.filter(message=next_message).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("interrupted_upload", [False, True])
def test_retry_commits_cleanup_before_conflict(
    file_message, monkeypatch, interrupted_upload
):
    from datetime import timedelta

    from django.utils import timezone

    from files.services.cleanup import cleanup_files

    user, workspace, ally, _binding, conversation = file_message
    reservation = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="",
        files=[_manifest(b"abc", "550e8400-e29b-41d4-a716-446655440022")],
        key="retry-cleanup-file-key",
    )
    file = reservation.files[0]
    if interrupted_upload:
        original = InMemoryFileObjectStore.put_stream

        def fail_upload(*args, **kwargs):
            raise OSError("storage interrupted")

        monkeypatch.setattr(InMemoryFileObjectStore, "put_stream", fail_upload)
        with pytest.raises(FileUnavailable):
            receive_file(
                user=user,
                workspace_id=workspace.id,
                ally_id=ally.id,
                file_id=file.id,
                generation=1,
                content_length="3",
                stream=BytesIO(b"abc"),
            )
        FileVersion.objects.filter(pk=file.pk).update(
            lease_until=timezone.now() - timedelta(seconds=1)
        )
        monkeypatch.setattr(InMemoryFileObjectStore, "put_stream", original)
    receive_file(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        file_id=file.id,
        generation=1,
        content_length="3",
        stream=BytesIO(b"abc"),
    )
    FileVersion.objects.filter(pk=file.pk).update(state=FileState.REJECTED)
    with pytest.raises(FileConflict, match="cleanup"):
        retry_inbound_file(
            user=user,
            workspace_id=workspace.id,
            ally_id=ally.id,
            file_id=file.id,
            generation=1,
        )
    candidates = FileStagingObject.objects.filter(file=file)
    assert candidates.count() == 1 + interrupted_upload
    assert all(candidate.cleanup_after <= timezone.now() for candidate in candidates)
    if interrupted_upload:
        file.refresh_from_db()
        current_key = file.object_key
        original_delete = InMemoryFileObjectStore.delete

        def fail_obsolete_delete(store, *, key):
            if key != current_key:
                raise OSError("delete interrupted")
            original_delete(store, key=key)

        monkeypatch.setattr(InMemoryFileObjectStore, "delete", fail_obsolete_delete)
        assert cleanup_files().deleted == 1
        with pytest.raises(FileConflict, match="cleanup"):
            retry_inbound_file(
                user=user,
                workspace_id=workspace.id,
                ally_id=ally.id,
                file_id=file.id,
                generation=1,
            )
        monkeypatch.setattr(InMemoryFileObjectStore, "delete", original_delete)
    assert cleanup_files().deleted == 1
    retried = retry_inbound_file(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        file_id=file.id,
        generation=1,
    )
    assert retried.generation == 2
    assert retried.state == FileState.PENDING


@pytest.mark.django_db
@pytest.mark.parametrize("discard", [False, True])
def test_abandoned_unuploaded_file_releases_capacity(
    file_message, django_capture_on_commit_callbacks, discard
):
    from files.services.cleanup import schedule_file_cleanup

    user, workspace, _ally, _binding, conversation = file_message
    reservation = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="Keep text",
        files=[_manifest(b"abc", "550e8400-e29b-41d4-a716-446655440023")],
        key="discard-pending-file-key",
    )
    file = reservation.files[0]
    assert not schedule_file_cleanup(file_id=file.id)
    with django_capture_on_commit_callbacks(execute=True):
        if discard:
            cancel_file_message(
                user=user,
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                message_id=reservation.message.id,
                revision=reservation.message.preparation_revision,
            )
            assert not schedule_file_cleanup(file_id=file.id)
            discard_file_draft(
                user=user,
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                message_id=reservation.message.id,
            )
        else:
            remove_inbound_file(
                user=user,
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                message_id=reservation.message.id,
                file_id=file.id,
                revision=reservation.message.preparation_revision,
            )
    schedule_file_cleanup(file_id=file.id)
    file.refresh_from_db()
    assert file.state == FileState.DELETED
    assert not file.reserved_accounted
    assert FileStorageAccount.objects.get(workspace=workspace).reserved_bytes == 0
