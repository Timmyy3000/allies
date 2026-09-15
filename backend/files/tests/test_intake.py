from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from threading import Event
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.db import close_old_connections, connection
from django.utils import timezone

from allies.models import Ally, AllyBinding
from allies.services import deletion
from auths.models import User
from chat.exceptions import IdempotencyConflict
from chat.models import Conversation, DispatchOutbox, MessagePreparation
from files.exceptions import (
    FileConflict,
    FileScopeUnavailable,
    FileTooLarge,
    FileUnavailable,
    FileValidation,
)
from files.inspection import FileInspection
from files.models import (
    FileIOOutcome,
    FileStagingObject,
    FileState,
    FileStorageAccount,
    FileVersion,
)
from files.services import inspection as inspection_worker
from files.services.inspection import _claim, inspect_due_files, inspect_file
from files.services.intake import (
    CHUNK_BYTES,
    InspectionResult,
    promote_inspected_file,
    receive_file,
    reserve_send,
)
from files.storage import InMemoryFileObjectStore, set_file_store
from workspaces.models import Membership, Workspace


@pytest.fixture
def admission(settings, db):
    cache.clear()
    settings.ALLIES_AUTH_DIGEST_KEY = "d" * 32
    settings.ALLIES_FILE_ADMISSION_ENABLED = True
    settings.ALLIES_FILE_STORAGE_ENABLED = True
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
    conversation = Conversation.objects.create(ally=ally)
    yield user, workspace, ally, conversation
    set_file_store(None)


def manifest(data: bytes = b"private bytes"):
    return [
        {
            "client_id": "550e8400-e29b-41d4-a716-446655440001",
            "name": "report.pdf",
            "size": len(data),
            "sha256": sha256(data).hexdigest(),
        }
    ]


@pytest.mark.django_db
def test_reservation_is_idempotent_charged_and_blocks_dispatch(admission):
    user, workspace, _ally, conversation = admission
    first = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="",
        files=manifest(),
        key="file-reservation-key-0001",
    )
    replay = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="",
        files=manifest(),
        key="file-reservation-key-0001",
    )
    assert first.replayed is False and replay.replayed is True
    assert first.message.preparation == MessagePreparation.UPLOADING
    assert first.message.send_armed is False
    assert FileStorageAccount.objects.get(workspace=workspace).reserved_bytes == len(
        b"private bytes"
    )
    assert not DispatchOutbox.objects.filter(message=first.message).exists()
    with pytest.raises(IdempotencyConflict):
        reserve_send(
            user=user,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            content="changed",
            files=manifest(),
            key="file-reservation-key-0001",
        )


@pytest.mark.django_db
def test_upload_streams_exact_content_and_stops_at_validating(admission):
    user, workspace, ally, conversation = admission
    data = b"a" * (CHUNK_BYTES + 13)
    reservation = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="",
        files=manifest(data),
        key="file-upload-key-00000001",
    )
    file = reservation.files[0]
    result = receive_file(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        file_id=file.id,
        generation=1,
        content_length=str(len(data)),
        stream=BytesIO(data),
    )
    assert result.state == FileState.VALIDATING
    assert result.object_key.startswith("staging/")
    assert FileStagingObject.objects.filter(file=file, key=result.object_key).exists()
    assert not DispatchOutbox.objects.filter(message=reservation.message).exists()


@pytest.mark.django_db
def test_upload_rejects_oversized_and_mismatched_content_length(admission):
    user, workspace, ally, conversation = admission
    data = b"abc"
    file = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="",
        files=manifest(data),
        key="file-length-key-00000001",
    ).files[0]
    with pytest.raises(FileTooLarge):
        receive_file(
            user=user,
            workspace_id=workspace.id,
            ally_id=ally.id,
            file_id=file.id,
            generation=1,
            content_length="25000001",
            stream=BytesIO(),
        )
    with pytest.raises(FileValidation):
        receive_file(
            user=user,
            workspace_id=workspace.id,
            ally_id=ally.id,
            file_id=file.id,
            generation=1,
            content_length="2",
            stream=BytesIO(data),
        )


@pytest.mark.django_db
def test_expired_receiver_is_fenced_before_replacement(admission):
    user, workspace, ally, conversation = admission
    data = b"abc"
    file = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="",
        files=manifest(data),
        key="file-fence-key-000000001",
    ).files[0]
    file.state = FileState.RECEIVING
    file.lease_until = timezone.now() - timedelta(seconds=1)
    file.save(update_fields=("state", "lease_until"))
    result = receive_file(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        file_id=file.id,
        generation=1,
        content_length="3",
        stream=BytesIO(data),
    )
    assert result.state == FileState.VALIDATING
    with pytest.raises(FileConflict):
        receive_file(
            user=user,
            workspace_id=workspace.id,
            ally_id=ally.id,
            file_id=file.id,
            generation=1,
            content_length="3",
            stream=BytesIO(data),
        )


@pytest.mark.django_db
def test_inspection_unavailable_rejects_instead_of_promoting(admission, settings):
    user, workspace, ally, conversation = admission
    data = b"abc"
    file = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="",
        files=manifest(data),
        key="file-inspection-key-000001",
    ).files[0]
    file = receive_file(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        file_id=file.id,
        generation=1,
        content_length="3",
        stream=BytesIO(data),
    )
    settings.ALLIES_FILE_INSPECTION_ENABLED = False
    result = promote_inspected_file(
        file_id=file.id,
        generation=1,
        result=InspectionResult(3, sha256(data).hexdigest(), "application/pdf", True),
    )
    assert result.state == FileState.REJECTED
    assert result.safe_error_code == "inspection_unavailable"


@pytest.mark.django_db
def test_ambiguous_upload_failure_keeps_the_fenced_receiver_recoverable(admission):
    user, workspace, ally, conversation = admission

    class FailingStore:
        def put_stream(self, **kwargs):
            raise TimeoutError("provider response lost")

    data = b"abc"
    file = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="",
        files=manifest(data),
        key="file-ambiguous-put-key-01",
    ).files[0]
    set_file_store(FailingStore())
    with pytest.raises(FileUnavailable):
        receive_file(
            user=user,
            workspace_id=workspace.id,
            ally_id=ally.id,
            file_id=file.id,
            generation=1,
            content_length="3",
            stream=BytesIO(data),
        )
    file.refresh_from_db()
    assert file.state == FileState.RECEIVING
    assert file.safe_error_code == "storage_unavailable"
    assert file.lease_until is not None


def _validating_file(admission, *, key="file-promotion-key-00001"):
    user, workspace, ally, conversation = admission
    data = b"abc"
    file = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="",
        files=manifest(data),
        key=key,
    ).files[0]
    file = receive_file(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        file_id=file.id,
        generation=1,
        content_length="3",
        stream=BytesIO(data),
    )
    return file, data


@pytest.mark.django_db(transaction=True)
def test_receive_file_enqueues_inspection_after_commit(admission, monkeypatch):
    user, workspace, ally, conversation = admission
    queued = []
    monkeypatch.setattr("files.services.intake._enqueue_file_inspection", queued.append)
    data = b"abc"
    file = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="",
        files=manifest(data),
        key="file-immediate-inspection-001",
    ).files[0]

    received = receive_file(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        file_id=file.id,
        generation=1,
        content_length="3",
        stream=BytesIO(data),
    )

    assert queued == [received.id]


@pytest.mark.django_db(transaction=True)
def test_direct_inspection_schedules_retry_from_persisted_state(
    admission, settings, monkeypatch
):
    file, _data = _validating_file(admission, key="file-direct-inspection-retry-001")
    settings.ALLIES_FILE_SCANNER_HOST = "scanner.internal"
    queued = []
    monkeypatch.setattr(
        "files.tasks.enqueue_file_inspection",
        lambda file_id, *, countdown=0: queued.append((file_id, countdown)),
    )

    def inspector(**_kwargs):
        return FileInspection(
            accepted=False,
            media_type="application/pdf",
            preview_kind="pdf",
            safe_error_code="scanner_timeout",
            scanner_clean=False,
        )

    assert inspect_file(file_id=file.id, inspector=inspector) == 1
    file.refresh_from_db()
    assert file.state == FileState.VALIDATING
    assert file.inspection_attempts == 1
    assert queued == [(file.id, 5)]
    assert inspect_file(file_id=file.id, inspector=inspector) == 0

    FileVersion.objects.filter(pk=file.id).update(
        inspection_due_at=timezone.now() - timedelta(seconds=1)
    )
    assert inspect_file(file_id=file.id, inspector=inspector) == 1
    file.refresh_from_db()
    assert file.inspection_attempts == 2
    assert queued == [(file.id, 5), (file.id, 30)]

    FileVersion.objects.filter(pk=file.id).update(
        inspection_due_at=timezone.now() - timedelta(seconds=1)
    )
    assert inspect_file(file_id=file.id, inspector=inspector) == 1
    file.refresh_from_db()
    assert file.state == FileState.REJECTED
    assert file.inspection_attempts == 3
    assert queued == [(file.id, 5), (file.id, 30)]
    assert inspect_file(file_id=file.id, inspector=inspector) == 0


@pytest.mark.django_db(transaction=True)
def test_broker_failure_keeps_upload_recoverable_by_sweep(
    admission, settings, monkeypatch
):
    def unavailable(**_kwargs):
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr("files.tasks.current_app.connection_for_write", unavailable)
    file, data = _validating_file(admission, key="file-broker-recovery-001")
    file.refresh_from_db()
    assert file.state == FileState.VALIDATING
    settings.ALLIES_FILE_INSPECTION_ENABLED = True
    settings.ALLIES_FILE_SCANNER_HOST = "scanner.internal"

    def inspector(**_kwargs):
        return FileInspection(
            accepted=True,
            media_type="application/pdf",
            preview_kind="pdf",
            safe_error_code=None,
            scanner_clean=True,
            actual_size=len(data),
            sha256=sha256(data).hexdigest(),
        )

    assert inspect_due_files(limit=20, inspector=inspector) == 1
    file.refresh_from_db()
    assert file.state == FileState.READY


@pytest.mark.django_db
def test_inspection_claim_uses_a_240_second_token_fence(admission, settings):
    file, data = _validating_file(admission)
    settings.ALLIES_FILE_INSPECTION_ENABLED = True
    first = _claim(file_id=file.id, now=timezone.now())

    assert first is not None
    assert first.inspection_lease_until >= timezone.now() + timedelta(seconds=239)
    second = _claim(
        file_id=file.id,
        now=first.inspection_lease_until + timedelta(seconds=1),
    )

    assert second is not None
    with pytest.raises(FileConflict):
        promote_inspected_file(
            file_id=file.id,
            generation=file.generation,
            inspection_lease_token=first.inspection_lease_token,
            result=InspectionResult(
                len(data), sha256(data).hexdigest(), "application/pdf", True
            ),
        )


@pytest.mark.django_db
def test_inspection_worker_promotes_only_the_isolated_runner_result(
    admission, settings
):
    file, data = _validating_file(admission)
    settings.ALLIES_FILE_INSPECTION_ENABLED = True
    settings.ALLIES_FILE_SCANNER_HOST = "scanner.internal"
    seen = {}

    def inspector(**kwargs):
        seen.update(kwargs)
        return FileInspection(
            accepted=True,
            media_type="application/pdf",
            preview_kind="pdf",
            safe_error_code=None,
            scanner_clean=True,
            actual_size=len(data),
            sha256=sha256(data).hexdigest(),
        )

    assert inspect_due_files(limit=20, inspector=inspector) == 1
    file.refresh_from_db()
    assert file.state == FileState.READY
    assert seen["name"] == "report.pdf"
    assert seen["size"] == len(data)
    assert seen["scanner_config"].host == "scanner.internal"


@pytest.mark.django_db
def test_inspection_page_refreshes_the_lease_for_each_claim(
    admission, settings, monkeypatch
):
    _validating_file(admission, key="file-inspection-page-key-1")
    _validating_file(admission, key="file-inspection-page-key-2")
    settings.ALLIES_FILE_INSPECTION_ENABLED = True
    settings.ALLIES_FILE_SCANNER_HOST = "scanner.internal"
    start = timezone.now()
    moments = iter((start, start, start + timedelta(seconds=210)))
    monkeypatch.setattr(
        inspection_worker, "timezone", SimpleNamespace(now=lambda: next(moments))
    )
    original_claim = inspection_worker._claim
    leases = []

    def claim(**kwargs):
        claimed = original_claim(**kwargs)
        if claimed is not None:
            leases.append(claimed.inspection_lease_until)
        return claimed

    def inspector(**kwargs):
        data = b"abc"
        return FileInspection(
            accepted=True,
            media_type="application/pdf",
            preview_kind="pdf",
            safe_error_code=None,
            scanner_clean=True,
            actual_size=len(data),
            sha256=sha256(data).hexdigest(),
        )

    monkeypatch.setattr(inspection_worker, "_claim", claim)
    assert inspection_worker.inspect_due_files(limit=20, inspector=inspector) == 2
    assert leases == [
        start + timedelta(seconds=240),
        start + timedelta(seconds=450),
    ]


@pytest.mark.django_db
def test_copy_failure_remains_validating_and_retryable(admission, settings):
    file, data = _validating_file(admission)
    settings.ALLIES_FILE_INSPECTION_ENABLED = True
    source = InMemoryFileObjectStore()
    source.put_stream(
        key=file.object_key,
        stream=BytesIO(data),
        content_type="application/octet-stream",
        size=3,
        sha256=sha256(data).hexdigest(),
    )

    class FailingCopyStore:
        metadata = source.metadata

        def promote(self, **kwargs):
            raise TimeoutError("copy outcome unknown")

    set_file_store(FailingCopyStore())
    with pytest.raises(FileUnavailable):
        promote_inspected_file(
            file_id=file.id,
            generation=1,
            result=InspectionResult(
                3, sha256(data).hexdigest(), "application/pdf", True
            ),
        )
    file.refresh_from_db()
    assert file.state == FileState.VALIDATING
    assert file.safe_error_code == "storage_unavailable"


@pytest.mark.django_db
def test_promotion_rejects_a_verified_destination_mismatch(admission, settings):
    file, data = _validating_file(admission)
    settings.ALLIES_FILE_INSPECTION_ENABLED = True

    class MismatchedDestinationStore(InMemoryFileObjectStore):
        def promote(self, **kwargs):
            super().promote(**kwargs)
            payload, content_type, _ = self.objects[kwargs["destination_key"]]
            self.objects[kwargs["destination_key"]] = (payload, content_type, "0" * 64)

    store = MismatchedDestinationStore()
    store.put_stream(
        key=file.object_key,
        stream=BytesIO(data),
        content_type="application/octet-stream",
        size=3,
        sha256=sha256(data).hexdigest(),
    )
    set_file_store(store)
    with pytest.raises(FileValidation, match="immutable promotion"):
        promote_inspected_file(
            file_id=file.id,
            generation=1,
            result=InspectionResult(
                3, sha256(data).hexdigest(), "application/pdf", True
            ),
        )
    file.refresh_from_db()
    assert file.state == FileState.REJECTED


@pytest.mark.postgresql
@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="requires PostgreSQL row-lock semantics",
)
@pytest.mark.django_db(transaction=True)
def test_delete_after_verified_promotion_copy_settles_candidate_before_fence(
    admission, settings, monkeypatch
):
    user, workspace, ally, conversation = admission
    AllyBinding.objects.create(ally=ally)
    file, data = _validating_file(admission, key="file-promotion-delete-race-1")
    settings.ALLIES_FILE_INSPECTION_ENABLED = True
    source = InMemoryFileObjectStore()
    source.put_stream(
        key=file.object_key,
        stream=BytesIO(data),
        content_type="application/octet-stream",
        size=len(data),
        sha256=sha256(data).hexdigest(),
    )
    set_file_store(source)
    final_lock_entered, release_final_lock = Event(), Event()

    from files.services import intake

    original_account_locked = intake._account_locked
    account_lock_calls = 0

    def hold_final_account_lock(workspace_id):
        nonlocal account_lock_calls
        account_lock_calls += 1
        if account_lock_calls == 2:
            final_lock_entered.set()
            assert release_final_lock.wait(timeout=10)
        return original_account_locked(workspace_id)

    monkeypatch.setattr(intake, "_account_locked", hold_final_account_lock)
    monkeypatch.setattr(
        "allies.services.deletion._enqueue_reconciliation", lambda _id: None
    )

    def promote_once():
        close_old_connections()
        try:
            with pytest.raises(FileConflict):
                promote_inspected_file(
                    file_id=file.id,
                    generation=file.generation,
                    result=InspectionResult(
                        len(data), sha256(data).hexdigest(), "application/pdf", True
                    ),
                )
        finally:
            close_old_connections()
            connection.close()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(promote_once)
            assert final_lock_entered.wait(timeout=10)
            deletion.request_ally_deletion(
                user=user,
                workspace_id=workspace.id,
                ally_id=ally.id,
                confirmation="Mira - deletes me",
            )
            release_final_lock.set()
            future.result(timeout=10)
        candidate = FileStagingObject.objects.get(
            file=file, key__startswith="immutable/"
        )
        assert candidate.io_outcome == FileIOOutcome.COMPLETED
        assert file.state == FileState.VALIDATING
        assert conversation.ally_id == ally.id
    finally:
        set_file_store(None)


@pytest.mark.django_db
def test_foreign_file_scope_is_not_reported_as_a_storage_fault(admission):
    user, workspace, _ally, conversation = admission
    data = b"abc"
    file = reserve_send(
        user=user,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="",
        files=manifest(data),
        key="file-scope-key-000000001",
    ).files[0]
    foreign = Ally.objects.create(
        workspace=workspace,
        name="Other",
        job="Study",
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    with pytest.raises(FileScopeUnavailable):
        receive_file(
            user=user,
            workspace_id=workspace.id,
            ally_id=foreign.id,
            file_id=file.id,
            generation=1,
            content_length="3",
            stream=BytesIO(data),
        )
