from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from threading import Barrier, Event
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from allies.models import Ally, AllyBinding, BindingStatus
from auths.models import User
from chat.models import (
    Conversation,
    DispatchOutbox,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessagePreparation,
    MessageSender,
)
from chat.services.messages import claim_next_turn
from files.exceptions import FileConflict, FileScopeUnavailable
from files.inspection import FileInspection
from files.models import (
    FileAllyTombstone,
    FileDirection,
    FileDraftRecovery,
    FileObjectKind,
    FilePublication,
    FileStagingObject,
    FileState,
    FileStorageAccount,
    FileVersion,
    MessageFile,
    PublicationState,
)
from files.services.cleanup import _complete, tombstone_ally_files
from files.services.inspection import inspect_due_files, inspect_file
from files.services.intake import InspectionResult, promote_inspected_file, reserve_send
from files.services.preparation import (
    arm_file_message,
    cancel_file_message,
    remove_inbound_file,
    retry_inbound_file,
)
from files.services.publication import reserve_publication, retry_publication
from files.storage import InMemoryFileObjectStore, set_file_store
from workspaces.models import Membership, Workspace

pytestmark = [
    pytest.mark.postgresql,
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="requires PostgreSQL row locks"
    ),
]


def _prepared_message():
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Race workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study partner",
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    AllyBinding.objects.create(
        ally=ally,
        status=BindingStatus.BOUND,
        receipt_digest="c" * 64,
    )
    conversation = Conversation.objects.create(ally=ally)
    message = Message.objects.create(
        conversation=conversation,
        sequence=1,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="Race this prepared message",
        status=MessageLifecycle.QUEUED,
        send_key_digest="a" * 64,
        content_fingerprint="b" * 64,
        preparation=MessagePreparation.READY,
        preparation_revision=1,
        send_armed=True,
    )
    data = b"pdf"
    file = FileVersion.objects.create(
        workspace=workspace,
        ally=ally,
        owner=user,
        source_message=message,
        direction=FileDirection.INBOUND,
        original_name="report.pdf",
        media_type="application/pdf",
        expected_size=len(data),
        actual_size=len(data),
        sha256=sha256(data).hexdigest(),
        object_key="immutable/race/report.pdf",
        state=FileState.READY,
    )
    MessageFile.objects.create(message=message, file=file, position=0)
    return user, workspace, conversation, message


@pytest.mark.django_db(transaction=True)
def test_direct_inspection_and_sweep_share_one_postgresql_lease(settings, monkeypatch):
    _user, _workspace, _conversation, message = _prepared_message()
    file = FileVersion.objects.get(source_message=message)
    file.state = FileState.VALIDATING
    file.object_key = "staging/race/report.pdf"
    file.actual_size = None
    file.save(update_fields=("state", "object_key", "actual_size", "updated_at"))
    store = InMemoryFileObjectStore()
    data = b"pdf"
    store.put_stream(
        key=file.object_key,
        stream=BytesIO(data),
        content_type="application/octet-stream",
        size=len(data),
        sha256=sha256(data).hexdigest(),
    )
    set_file_store(store)
    settings.ALLIES_FILE_SCANNER_HOST = "scanner.internal"
    entered = Event()
    release = Event()
    monkeypatch.setattr(
        "files.tasks.enqueue_file_inspection", lambda *_args, **_kwargs: None
    )

    def blocking_inspector(**_kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return FileInspection(
            accepted=False,
            media_type="application/pdf",
            preview_kind="pdf",
            safe_error_code="scanner_timeout",
            scanner_clean=False,
        )

    def inspect_direct():
        close_old_connections()
        try:
            return inspect_file(file_id=file.id, inspector=blocking_inspector)
        finally:
            close_old_connections()
            connection.close()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            direct = executor.submit(inspect_direct)
            assert entered.wait(timeout=10)
            swept = inspect_due_files(
                limit=20,
                inspector=lambda **_kwargs: pytest.fail("leased file was rescanned"),
            )
            release.set()
            assert direct.result(timeout=10) == 1
        file.refresh_from_db()
        assert swept == 0
        assert file.inspection_attempts == 1
    finally:
        release.set()
        set_file_store(None)


@pytest.mark.django_db(transaction=True)
def test_cancel_and_claim_have_one_postgresql_winner(settings):
    settings.ALLIES_FILE_INPUT_DELIVERY_ENABLED = True
    user, workspace, conversation, message = _prepared_message()
    gate = Barrier(2)

    def claim_once():
        close_old_connections()
        try:
            gate.wait(timeout=10)
            claimed = claim_next_turn(conversation_id=conversation.id)
            return "claimed" if claimed is not None else "idle"
        finally:
            close_old_connections()
            connection.close()

    def cancel_once():
        close_old_connections()
        try:
            gate.wait(timeout=10)
            try:
                cancel_file_message(
                    user=user,
                    workspace_id=workspace.id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    revision=1,
                )
                return "cancelled"
            except FileConflict:
                return "delivery_started"
        finally:
            close_old_connections()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        claim_result, cancel_result = list(
            executor.map(lambda fn: fn(), (claim_once, cancel_once))
        )

    message.refresh_from_db()
    assert {claim_result, cancel_result} in (
        {"idle", "cancelled"},
        {"claimed", "delivery_started"},
    )
    if cancel_result == "cancelled":
        assert message.status == MessageLifecycle.STOPPED
        assert message.execution_claimed_at is None
        assert FileDraftRecovery.objects.filter(message=message).exists()
        assert not DispatchOutbox.objects.filter(message=message).exists()
    else:
        assert message.deleted_at is None
        assert message.execution_claimed_at is not None
        assert not FileDraftRecovery.objects.filter(message=message).exists()


@pytest.mark.django_db(transaction=True)
def test_arm_and_cancel_do_not_promote_or_draft_together(settings):
    settings.ALLIES_FILE_INPUT_DELIVERY_ENABLED = True
    user, workspace, conversation, message = _prepared_message()
    message.preparation = MessagePreparation.NEEDS_RETRY
    message.send_armed = False
    message.save(update_fields=("preparation", "send_armed", "updated_at"))
    gate = Barrier(2)

    def arm_once():
        close_old_connections()
        try:
            gate.wait(timeout=10)
            try:
                arm_file_message(
                    user=user,
                    workspace_id=workspace.id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    revision=1,
                )
                return "armed"
            except FileConflict:
                return "cancelled"
        finally:
            close_old_connections()
            connection.close()

    def cancel_once():
        close_old_connections()
        try:
            gate.wait(timeout=10)
            try:
                cancel_file_message(
                    user=user,
                    workspace_id=workspace.id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    revision=1,
                )
                return "cancelled"
            except FileConflict:
                return "armed"
        finally:
            close_old_connections()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        arm_result, cancel_result = list(
            executor.map(lambda fn: fn(), (arm_once, cancel_once))
        )

    message.refresh_from_db()
    if message.status == MessageLifecycle.STOPPED:
        assert arm_result == cancel_result == "cancelled"
        assert message.preparation == MessagePreparation.CANCELLED
        assert message.execution_claimed_at is None
        assert FileDraftRecovery.objects.filter(message=message).exists()
        assert not DispatchOutbox.objects.filter(message=message).exists()
    else:
        assert arm_result == cancel_result == "armed"
        assert message.preparation == MessagePreparation.READY
        assert message.send_armed is True
        assert message.execution_claimed_at is not None
        assert DispatchOutbox.objects.filter(message=message).exists()
        assert not FileDraftRecovery.objects.filter(message=message).exists()


@pytest.mark.django_db(transaction=True)
def test_retry_locks_the_account_before_preparation_scope(settings, monkeypatch):
    settings.ALLIES_AUTH_DIGEST_KEY = "d" * 32
    settings.ALLIES_FILE_ADMISSION_ENABLED = True
    settings.ALLIES_FILE_STORAGE_ENABLED = True
    settings.ALLIES_FILE_STORAGE_CAPACITY_BYTES = 100_000_000
    user, workspace, conversation, message = _prepared_message()
    file = FileVersion.objects.get(source_message=message)
    file.state = FileState.FAILED
    file.actual_size = None
    file.object_key = ""
    file.reserved_accounted = False
    file.save(
        update_fields=(
            "state",
            "actual_size",
            "object_key",
            "reserved_accounted",
            "updated_at",
        )
    )
    FileStorageAccount.objects.create(workspace=workspace)
    from files.services import intake, preparation

    reserve_has_account, release_reserve = Event(), Event()
    retry_account_attempt, retry_scope_attempt = Event(), Event()
    original_account_locked = intake._account_locked
    original_scope_locked = intake._scope_locked
    original_scope = preparation._scope

    def block_reservation_scope(*args, **kwargs):
        reserve_has_account.set()
        assert release_reserve.wait(timeout=10)
        return original_scope_locked(*args, **kwargs)

    def observe_account(workspace):
        if reserve_has_account.is_set():
            retry_account_attempt.set()
        return original_account_locked(workspace)

    def observe_retry_scope(*args, **kwargs):
        retry_scope_attempt.set()
        return original_scope(*args, **kwargs)

    monkeypatch.setattr(intake, "_scope_locked", block_reservation_scope)
    monkeypatch.setattr(intake, "_account_locked", observe_account)
    monkeypatch.setattr(preparation, "_scope", observe_retry_scope)

    def reserve_once():
        close_old_connections()
        try:
            reserve_send(
                user=user,
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                content="",
                files=[
                    {
                        "client_id": str(uuid4()),
                        "name": "second.pdf",
                        "size": 3,
                        "sha256": sha256(b"pdf").hexdigest(),
                    }
                ],
                key="postgresql-account-first-reservation",
            )
            return "reserved"
        finally:
            close_old_connections()
            connection.close()

    def retry_once():
        close_old_connections()
        try:
            retry_inbound_file(
                user=user,
                workspace_id=workspace.id,
                ally_id=file.ally_id,
                file_id=file.id,
                generation=file.generation,
            )
            return "retried"
        finally:
            close_old_connections()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        reservation = executor.submit(reserve_once)
        assert reserve_has_account.wait(timeout=10)
        retry = executor.submit(retry_once)
        try:
            assert retry_account_attempt.wait(timeout=10)
            assert not retry_scope_attempt.is_set()
        finally:
            release_reserve.set()
        assert reservation.result(timeout=10) == "reserved"
        assert retry.result(timeout=10) == "retried"


@pytest.mark.django_db(transaction=True)
def test_tombstone_locks_account_before_ally_and_denies_retry(settings, monkeypatch):
    settings.ALLIES_AUTH_DIGEST_KEY = "d" * 32
    settings.ALLIES_FILE_ADMISSION_ENABLED = True
    settings.ALLIES_FILE_STORAGE_ENABLED = True
    settings.ALLIES_FILE_STORAGE_CAPACITY_BYTES = 100_000_000
    user, workspace, _conversation, message = _prepared_message()
    retry_file = FileVersion.objects.get(source_message=message)
    retry_file.state = FileState.FAILED
    retry_file.actual_size = None
    retry_file.object_key = ""
    retry_file.reserved_accounted = False
    retry_file.save(
        update_fields=(
            "state",
            "actual_size",
            "object_key",
            "reserved_accounted",
            "updated_at",
        )
    )
    sibling = FileVersion.objects.create(
        workspace=workspace,
        ally_id=retry_file.ally_id,
        owner=user,
        direction=FileDirection.INBOUND,
        original_name="pending.pdf",
        media_type="application/pdf",
        expected_size=3,
        sha256=sha256(b"new").hexdigest(),
        state=FileState.PENDING,
        reserved_accounted=True,
    )
    FileStorageAccount.objects.create(
        workspace=workspace, reserved_bytes=sibling.expected_size
    )
    from files.services import cleanup, intake, preparation

    cleanup_has_account, release_cleanup = Event(), Event()
    retry_account_attempt, retry_scope_attempt = Event(), Event()
    original_cleanup_account = cleanup._account_locked
    original_intake_account = intake._account_locked
    original_ally_lock = cleanup.Ally.objects.select_for_update
    original_scope = preparation._scope

    def block_cleanup_account(workspace_id):
        account = original_cleanup_account(workspace_id)
        cleanup_has_account.set()
        assert release_cleanup.wait(timeout=10)
        return account

    def observe_retry_account(locked_workspace):
        retry_account_attempt.set()
        return original_intake_account(locked_workspace)

    def assert_account_before_ally(*args, **kwargs):
        assert cleanup_has_account.is_set()
        return original_ally_lock(*args, **kwargs)

    def observe_retry_scope(*args, **kwargs):
        retry_scope_attempt.set()
        return original_scope(*args, **kwargs)

    monkeypatch.setattr(cleanup, "_account_locked", block_cleanup_account)
    monkeypatch.setattr(intake, "_account_locked", observe_retry_account)
    monkeypatch.setattr(
        cleanup.Ally.objects, "select_for_update", assert_account_before_ally
    )
    monkeypatch.setattr(preparation, "_scope", observe_retry_scope)

    def tombstone_once():
        close_old_connections()
        try:
            tombstone_ally_files(ally_id=retry_file.ally_id)
            return "tombstoned"
        finally:
            close_old_connections()
            connection.close()

    def retry_once():
        close_old_connections()
        try:
            try:
                retry_inbound_file(
                    user=user,
                    workspace_id=workspace.id,
                    ally_id=retry_file.ally_id,
                    file_id=retry_file.id,
                    generation=retry_file.generation,
                )
            except FileScopeUnavailable:
                return "denied"
            return "retried"
        finally:
            close_old_connections()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        tombstone = executor.submit(tombstone_once)
        assert cleanup_has_account.wait(timeout=10)
        retry = executor.submit(retry_once)
        assert retry_account_attempt.wait(timeout=10)
        assert not retry_scope_attempt.is_set()
        release_cleanup.set()
        assert tombstone.result(timeout=10) == "tombstoned"
        assert retry.result(timeout=10) == "denied"

    account = FileStorageAccount.objects.get(workspace=workspace)
    assert account.reserved_bytes == 0


@pytest.mark.django_db(transaction=True)
def test_tombstone_serializes_claim_before_file_dispatch(settings, monkeypatch):
    settings.ALLIES_FILE_INPUT_DELIVERY_ENABLED = True
    _user, _workspace, conversation, _message = _prepared_message()
    from chat.services import messages
    from files.services import cleanup

    tombstone_ready, release_tombstone = Event(), Event()
    claim_started, claim_entered = Event(), Event()
    original_create = cleanup.FileAllyTombstone.objects.get_or_create
    original_claim = messages._claim_next_turn_locked

    def block_tombstone_create(*args, **kwargs):
        tombstone_ready.set()
        assert release_tombstone.wait(timeout=10)
        return original_create(*args, **kwargs)

    def observe_claim(*args, **kwargs):
        claim_entered.set()
        return original_claim(*args, **kwargs)

    monkeypatch.setattr(
        cleanup.FileAllyTombstone.objects, "get_or_create", block_tombstone_create
    )
    monkeypatch.setattr(messages, "_claim_next_turn_locked", observe_claim)

    def tombstone_once():
        close_old_connections()
        try:
            tombstone_ally_files(ally_id=conversation.ally_id)
            return "tombstoned"
        finally:
            close_old_connections()
            connection.close()

    def claim_once():
        close_old_connections()
        try:
            claim_started.set()
            return claim_next_turn(conversation_id=conversation.id)
        finally:
            close_old_connections()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        tombstone = executor.submit(tombstone_once)
        assert tombstone_ready.wait(timeout=10)
        claim = executor.submit(claim_once)
        assert claim_started.wait(timeout=10)
        assert not claim_entered.wait(timeout=1)
        release_tombstone.set()
        assert tombstone.result(timeout=10) == "tombstoned"
        assert claim.result(timeout=10) is None

    assert not DispatchOutbox.objects.filter(
        message__conversation=conversation
    ).exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("action", ("cancel", "remove"))
def test_cancel_or_remove_fences_a_late_postgresql_promotion(settings, action):
    settings.ALLIES_FILE_INSPECTION_ENABLED = True
    user, workspace, conversation, message = _prepared_message()
    file = FileVersion.objects.get(source_message=message)
    data = b"pdf"
    file.state = FileState.VALIDATING
    file.actual_size = None
    file.object_key = "staging/race/report.pdf"
    file.reserved_accounted = True
    file.retained_accounted = False
    file.save(
        update_fields=(
            "state",
            "actual_size",
            "object_key",
            "reserved_accounted",
            "retained_accounted",
            "updated_at",
        )
    )
    FileStorageAccount.objects.create(workspace=workspace, reserved_bytes=len(data))
    blocked, release = Event(), Event()

    class BlockingStore(InMemoryFileObjectStore):
        def promote(self, **kwargs):
            blocked.set()
            assert release.wait(timeout=10)
            super().promote(**kwargs)

    store = BlockingStore()
    store.put_stream(
        key=file.object_key,
        stream=BytesIO(data),
        content_type="application/octet-stream",
        size=len(data),
        sha256=sha256(data).hexdigest(),
    )
    set_file_store(store)

    def promote_once():
        close_old_connections()
        try:
            with pytest.raises(FileConflict):
                promote_inspected_file(
                    file_id=file.id,
                    generation=1,
                    result=InspectionResult(
                        len(data),
                        sha256(data).hexdigest(),
                        "application/pdf",
                        True,
                    ),
                )
        finally:
            close_old_connections()
            connection.close()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(promote_once)
            assert blocked.wait(timeout=10)
            if action == "cancel":
                cancel_file_message(
                    user=user,
                    workspace_id=workspace.id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    revision=message.preparation_revision,
                )
            else:
                remove_inbound_file(
                    user=user,
                    workspace_id=workspace.id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    file_id=file.id,
                    revision=message.preparation_revision,
                )
            release.set()
            future.result(timeout=10)
        file.refresh_from_db()
        account = FileStorageAccount.objects.get(workspace=workspace)
        assert file.state == FileState.VALIDATING
        assert file.reserved_accounted
        assert not file.retained_accounted
        assert account.reserved_bytes == len(data)
        assert account.retained_bytes == 0
    finally:
        set_file_store(None)


def _publication_source(*, label: str):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name=f"Publication {label}")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    ally = Ally.objects.create(
        workspace=workspace,
        name=f"Mira {label}",
        job="Study partner",
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    binding = AllyBinding.objects.create(
        ally=ally, status=BindingStatus.BOUND, receipt_digest="d" * 64
    )
    conversation = Conversation.objects.create(ally=ally)
    message = Message.objects.create(
        conversation=conversation,
        sequence=1,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="Return a file",
        send_key_digest="e" * 64,
        content_fingerprint="f" * 64,
        execution_claimed_at=timezone.now(),
        foundry_binding_id=binding.id,
    )
    return binding, message


@pytest.mark.django_db(transaction=True)
def test_publication_reservation_and_tombstone_do_not_deadlock(settings):
    settings.ALLIES_FILE_STORAGE_CAPACITY_BYTES = 100_000_000
    binding, message = _publication_source(label="reservation-tombstone")
    workspace = message.conversation.ally.workspace
    FileStorageAccount.objects.create(workspace=workspace)
    gate = Barrier(2)

    def reserve_once():
        close_old_connections()
        try:
            gate.wait(timeout=10)
            reserve_publication(
                binding_id=binding.id,
                message_id=message.id,
                publication_id=uuid4(),
                files=[
                    {
                        "source_version_id": str(uuid4()),
                        "name": "result.pdf",
                        "size": 3,
                        "sha256": sha256(b"pdf").hexdigest(),
                    }
                ],
            )
            return "reserved"
        except FileScopeUnavailable:
            return "denied"
        finally:
            close_old_connections()
            connection.close()

    def tombstone_once():
        close_old_connections()
        try:
            gate.wait(timeout=10)
            tombstone_ally_files(ally_id=binding.ally_id)
            return "tombstoned"
        finally:
            close_old_connections()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        reservation = executor.submit(reserve_once)
        tombstone = executor.submit(tombstone_once)
        assert reservation.result(timeout=10) in {"reserved", "denied"}
        assert tombstone.result(timeout=10) == "tombstoned"

    assert FileAllyTombstone.objects.filter(ally_id=binding.ally_id).exists()
    account = FileStorageAccount.objects.get(workspace=workspace)
    assert account.reserved_bytes == account.retained_bytes == 0
    publication = FilePublication.objects.filter(source_message=message).first()
    if publication is not None:
        file = publication.files.get()
        assert file.state == FileState.DELETED
        assert file.safe_error_code == "ally_deleted"
        assert not file.reserved_accounted


@pytest.mark.django_db(transaction=True)
def test_foreign_publication_id_race_keeps_the_first_source(settings):
    settings.ALLIES_FILE_STORAGE_CAPACITY_BYTES = 100_000_000
    first_binding, first_message = _publication_source(label="first")
    second_binding, second_message = _publication_source(label="second")
    publication_id = uuid4()
    sources = (
        (first_binding, first_message, uuid4()),
        (second_binding, second_message, uuid4()),
    )
    gate = Barrier(2)

    def reserve_once(source):
        binding, message, source_version_id = source
        close_old_connections()
        try:
            gate.wait(timeout=10)
            result = reserve_publication(
                binding_id=binding.id,
                message_id=message.id,
                publication_id=publication_id,
                files=[
                    {
                        "source_version_id": str(source_version_id),
                        "name": "result.pdf",
                        "size": 3,
                        "sha256": sha256(b"pdf").hexdigest(),
                    }
                ],
            )
            return "reserved", message.id, result
        except FileConflict:
            return "conflict", message.id, None
        finally:
            close_old_connections()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(reserve_once, sources))

    assert sorted(outcome[0] for outcome in outcomes) == ["conflict", "reserved"]
    publication = FilePublication.objects.get(pk=publication_id)
    winner = next(outcome for outcome in outcomes if outcome[0] == "reserved")
    assert publication.source_message_id == winner[1]
    assert publication.files.get().source_version_id == next(
        source_version_id
        for _binding, message, source_version_id in sources
        if message.id == winner[1]
    )


@pytest.mark.django_db(transaction=True)
def test_retry_and_confirmed_staging_cleanup_do_not_deadlock(settings):
    settings.ALLIES_FILE_STORAGE_CAPACITY_BYTES = 100_000_000
    binding, message = _publication_source(label="retry-cleanup")
    workspace = message.conversation.ally.workspace
    owner = workspace.owner
    publication_id = uuid4()
    reserved = reserve_publication(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        files=[
            {
                "source_version_id": str(uuid4()),
                "name": "result.pdf",
                "size": 3,
                "sha256": sha256(b"pdf").hexdigest(),
            }
        ],
    )
    publication = FilePublication.objects.get(pk=publication_id)
    file = publication.files.get(pk=reserved["files"][0]["id"])
    staging_key = "staging/race/retry-cleanup"
    file.state = FileState.FAILED
    file.object_key = ""
    file.save(update_fields=("state", "object_key", "updated_at"))
    FilePublication.objects.filter(pk=publication_id).update(
        state=PublicationState.FAILED
    )
    candidate = FileStagingObject.objects.create(
        file=file,
        key=staging_key,
        generation=file.generation,
        write_fence=file.write_fence,
        kind=FileObjectKind.STAGING,
        cleanup_after=timezone.now(),
    )
    gate = Barrier(2)

    def complete_once():
        close_old_connections()
        try:
            gate.wait(timeout=10)
            _complete(candidate_id=candidate.id, now=timezone.now())
            return "completed"
        finally:
            close_old_connections()
            connection.close()

    def retry_once():
        close_old_connections()
        try:
            gate.wait(timeout=10)
            try:
                retry_publication(
                    user=owner,
                    workspace_id=workspace.id,
                    ally_id=message.conversation.ally_id,
                    message_id=message.id,
                    publication_id=publication_id,
                    revision=1,
                )
                return "retried"
            except FileConflict:
                return "cleanup_pending"
        finally:
            close_old_connections()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        complete_result, retry_result = list(
            executor.map(lambda fn: fn(), (complete_once, retry_once))
        )

    assert complete_result == "completed"
    assert retry_result in {"retried", "cleanup_pending"}
    candidate.refresh_from_db()
    assert candidate.deleted_at is not None
