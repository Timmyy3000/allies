from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.http import StreamingHttpResponse
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from allies.models import Ally, AllyBinding, BindingStatus
from auths.config import cookie_name
from auths.models import User
from auths.services.sessions import issue_session
from chat.models import (
    Conversation,
    Message,
    MessageOrigin,
    MessagePreparation,
    MessageSender,
)
from files.exceptions import FileConflict, FileScopeUnavailable
from files.models import (
    FileDirection,
    FileObjectKind,
    FilePublication,
    FileStagingObject,
    FileState,
    FileStorageAccount,
    FileVersion,
    PublicationState,
)
from files.services.access import (
    BoundedFileStream,
    open_file,
    private_file_preview,
    private_file_stream,
)
from files.services.cleanup import cleanup_files, tombstone_ally_files
from files.services.intake import (
    InspectionResult,
    promote_inspected_file,
    receive_file,
    reserve_send,
)
from files.services.preparation import (
    cancel_file_message,
    discard_file_draft,
    retry_inbound_file,
)
from files.services.publication import retry_publication
from files.storage import InMemoryFileObjectStore, set_file_store
from workspaces.models import Membership, Workspace


@pytest.fixture
def file_context(settings, db):
    cache.clear()
    settings.ALLIES_AUTH_DIGEST_KEY = "d" * 32
    settings.ALLIES_FILE_ADMISSION_ENABLED = True
    settings.ALLIES_FILE_STORAGE_ENABLED = True
    settings.ALLIES_FILE_INSPECTION_ENABLED = True
    settings.ALLIES_FILE_STORAGE_CAPACITY_BYTES = 100_000_000
    set_file_store(InMemoryFileObjectStore())
    owner = User.objects.create_user()
    workspace = Workspace.objects.create(owner=owner, name="Personal")
    Membership.objects.create(
        workspace=workspace, user=owner, role="owner", status="active"
    )
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study",
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    AllyBinding.objects.create(
        ally=ally, status=BindingStatus.BOUND, receipt_digest="b" * 64
    )
    conversation = Conversation.objects.create(ally=ally)
    yield owner, workspace, ally, conversation
    set_file_store(None)


def _reserve(context, data: bytes, key: str):
    owner, workspace, _ally, conversation = context
    return reserve_send(
        user=owner,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        content="",
        files=[
            {
                "client_id": "550e8400-e29b-41d4-a716-446655440001",
                "name": "report.pdf",
                "size": len(data),
                "sha256": sha256(data).hexdigest(),
            }
        ],
        key=key,
    )


def _ready(context, data: bytes):
    owner, workspace, ally, _conversation = context
    reservation = _reserve(context, data, "cleanup-ready-key-0001")
    received = receive_file(
        user=owner,
        workspace_id=workspace.id,
        ally_id=ally.id,
        file_id=reservation.files[0].id,
        generation=1,
        content_length=str(len(data)),
        stream=BytesIO(data),
    )
    return promote_inspected_file(
        file_id=received.id,
        generation=1,
        result=InspectionResult(
            size=len(data),
            sha256=sha256(data).hexdigest(),
            media_type="application/pdf",
            clean=True,
        ),
    )


@pytest.mark.django_db
def test_private_open_has_bounded_range_and_tombstone_revokes_immediately(file_context):
    owner, workspace, ally, _conversation = file_context
    data = b"private return bytes"
    file = _ready(file_context, data)
    opened = open_file(
        user=owner, workspace_id=workspace.id, ally_id=ally.id, file_id=file.id
    )
    assert b"".join(private_file_stream(opened=opened, start=2, end=8)) == data[2:9]

    tombstone_ally_files(ally_id=ally.id)
    with pytest.raises(FileScopeUnavailable):
        open_file(
            user=owner, workspace_id=workspace.id, ally_id=ally.id, file_id=file.id
        )


@pytest.mark.django_db
@override_settings(ALLIES_AUTH_JWT_KEY="j" * 32)
def test_private_file_http_metadata_and_single_range_are_inert(file_context):
    owner, workspace, ally, _conversation = file_context
    data = b"private return bytes"
    file = _ready(file_context, data)
    client = Client()
    client.cookies[cookie_name("access")] = issue_session(owner).access_token
    base = f"/api/v1/workspaces/{workspace.id}/allies/{ally.id}/files/{file.id}"

    metadata = client.get(base)
    downloaded = client.get(base + "/download", HTTP_RANGE="bytes=2-8")
    invalid = client.get(base + "/download", HTTP_RANGE="bytes=0-1,2-3")

    assert metadata.status_code == 200
    assert "object_key" not in metadata.json()["data"]
    assert downloaded.status_code == 206
    assert downloaded["Content-Range"] == f"bytes 2-8/{len(data)}"
    assert b"".join(downloaded.streaming_content) == data[2:9]
    assert invalid.status_code == 416


@pytest.mark.django_db
@override_settings(ALLIES_AUTH_JWT_KEY="j" * 32)
def test_private_file_preview_uses_the_isolated_adapter_and_owner_scope(file_context):
    owner, workspace, ally, _conversation = file_context
    file = _ready(file_context, b"private return bytes")
    opened = open_file(
        user=owner, workspace_id=workspace.id, ally_id=ally.id, file_id=file.id
    )
    preview = private_file_preview(opened=opened)
    member = User.objects.create_user()
    Membership.objects.create(
        workspace=workspace, user=member, role="owner", status="active"
    )
    client = Client()
    client.cookies[cookie_name("access")] = issue_session(member).access_token
    base = f"/api/v1/workspaces/{workspace.id}/allies/{ally.id}/files/{file.id}"

    assert preview.kind == "none"
    assert preview.safe_error_code
    with pytest.raises(FileScopeUnavailable):
        open_file(
            user=member, workspace_id=workspace.id, ally_id=ally.id, file_id=file.id
        )
    assert client.get(base).status_code == 404
    assert client.get(base + "/download").status_code == 404
    assert client.get(base + "/preview").status_code == 404


@pytest.mark.django_db
def test_tombstone_cleanup_deletes_once_and_releases_retained_charge(file_context):
    _owner, workspace, ally, _conversation = file_context
    file = _ready(file_context, b"private return bytes")
    account = FileStorageAccount.objects.get(workspace=workspace)
    assert account.retained_bytes == file.expected_size

    tombstone_ally_files(ally_id=ally.id)
    result = cleanup_files(limit=100)
    file.refresh_from_db()
    account.refresh_from_db()
    assert result.deleted == 1
    assert file.state == FileState.DELETED
    assert account.retained_bytes == 0
    assert cleanup_files(limit=100).deleted == 0


@pytest.mark.django_db
def test_protected_object_candidate_rearms_after_draft_discard(file_context):
    owner, workspace, _ally, conversation = file_context
    file = _ready(file_context, b"protected return bytes")
    FileStagingObject.objects.create(
        file=file,
        key=file.object_key,
        generation=file.generation,
        write_fence=file.write_fence,
        kind=FileObjectKind.OBJECT,
        cleanup_after=timezone.now(),
    )

    assert cleanup_files(limit=100).deleted == 0
    candidate = FileStagingObject.objects.get(key=file.object_key)
    assert candidate.deleted_at is None
    cancel_file_message(
        user=owner,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=file.source_message_id,
        revision=file.source_message.preparation_revision,
    )
    with TestCase.captureOnCommitCallbacks(execute=True):
        discard_file_draft(
            user=owner,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            message_id=file.source_message_id,
        )

    assert cleanup_files(limit=100).deleted == 1
    file.refresh_from_db()
    account = FileStorageAccount.objects.get(workspace=workspace)
    assert file.state == FileState.DELETED
    assert account.retained_bytes == 0


@pytest.mark.django_db
def test_stale_object_cleanup_cannot_release_the_current_file_charge(file_context):
    _owner, workspace, _ally, _conversation = file_context
    file = _ready(file_context, b"stale candidate bytes")
    old_key, old_fence = file.object_key, file.write_fence
    FileStagingObject.objects.create(
        file=file,
        key=old_key,
        generation=file.generation,
        write_fence=old_fence,
        kind=FileObjectKind.OBJECT,
        cleanup_after=timezone.now(),
    )
    file.object_key = "immutable/current/replacement"
    file.write_fence = uuid4()
    file.state = FileState.CLEANUP_PENDING
    file.save(update_fields=("object_key", "write_fence", "state", "updated_at"))

    assert cleanup_files(limit=100).deleted == 1
    file.refresh_from_db()
    account = FileStorageAccount.objects.get(workspace=workspace)
    assert file.object_key == "immutable/current/replacement"
    assert file.state == FileState.CLEANUP_PENDING
    assert file.retained_accounted
    assert account.retained_bytes == file.actual_size


@pytest.mark.django_db
def test_bounded_file_stream_closes_when_the_response_closes_before_iteration():
    source = BytesIO(b"private bytes")
    response = StreamingHttpResponse(BoundedFileStream(source, size=13))

    response.close()

    assert source.closed


@pytest.mark.django_db
def test_retry_waits_for_partial_cleanup_then_rereserves_once(file_context):
    owner, workspace, ally, _conversation = file_context
    data = b"unfinished"
    reservation = _reserve(file_context, data, "cleanup-retry-key-0001")
    file = reservation.files[0]
    file.state = FileState.FAILED
    file.object_key = "staging/private"
    file.save(update_fields=("state", "object_key", "updated_at"))
    from files.models import FileObjectKind, FileStagingObject

    FileStagingObject.objects.create(
        file=file,
        key=file.object_key,
        generation=1,
        write_fence=file.write_fence,
        kind=FileObjectKind.STAGING,
        cleanup_after=timezone.now(),
    )
    with pytest.raises(FileConflict, match="cleanup"):
        retry_inbound_file(
            user=owner,
            workspace_id=workspace.id,
            ally_id=ally.id,
            file_id=file.id,
            generation=1,
        )
    cleanup_files(limit=100)
    file.refresh_from_db()
    assert not file.reserved_accounted
    retry = retry_inbound_file(
        user=owner,
        workspace_id=workspace.id,
        ally_id=ally.id,
        file_id=file.id,
        generation=1,
    )
    account = FileStorageAccount.objects.get(workspace=workspace)
    assert retry.generation == 2
    assert retry.reserved_accounted
    assert account.reserved_bytes == len(data)


@pytest.mark.django_db
def test_retry_replays_committed_next_generation_while_receiving(file_context):
    owner, workspace, ally, _conversation = file_context
    reservation = _reserve(file_context, b"unfinished", "cleanup-replay-key-0001")
    file = reservation.files[0]
    file.state = FileState.FAILED
    file.save(update_fields=("state", "updated_at"))
    retry = retry_inbound_file(
        user=owner,
        workspace_id=workspace.id,
        ally_id=ally.id,
        file_id=file.id,
        generation=1,
    )
    retry.state = FileState.RECEIVING
    retry.save(update_fields=("state", "updated_at"))
    replay = retry_inbound_file(
        user=owner,
        workspace_id=workspace.id,
        ally_id=ally.id,
        file_id=file.id,
        generation=1,
    )
    assert replay.id == retry.id
    assert replay.generation == 2


@pytest.mark.django_db
def test_discarded_cancelled_draft_allows_cleanup(file_context):
    owner, workspace, _ally, conversation = file_context
    file = _ready(file_context, b"discardable return bytes")
    message = file.source_message
    cancel_file_message(
        user=owner,
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        message_id=message.id,
        revision=message.preparation_revision,
    )
    with TestCase.captureOnCommitCallbacks(execute=True):
        assert discard_file_draft(
            user=owner,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            message_id=message.id,
        )
    result = cleanup_files(limit=100)
    file.refresh_from_db()
    assert result.deleted == 1
    assert file.state == FileState.DELETED


@pytest.mark.django_db
def test_staging_cleanup_reconciles_an_outbound_publication_for_owner_retry(
    file_context, monkeypatch
):
    owner, workspace, ally, conversation = file_context
    binding = AllyBinding.objects.get(ally=ally)
    message = Message.objects.create(
        conversation=conversation,
        sequence=1,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="return a file",
        send_key_digest="a" * 64,
        content_fingerprint="b" * 64,
        execution_claimed_at=timezone.now(),
        foundry_binding_id=binding.id,
    )
    publication = FilePublication.objects.create(
        binding=binding,
        source_message=message,
        state=PublicationState.UPLOADING,
    )
    data = b"abandoned outbound bytes"
    file = FileVersion.objects.create(
        workspace=workspace,
        ally=ally,
        owner=owner,
        source_message=message,
        publication=publication,
        direction=FileDirection.OUTBOUND,
        original_name="result.pdf",
        media_type="application/pdf",
        expected_size=len(data),
        sha256=sha256(data).hexdigest(),
        object_key="staging/outbound-abandoned",
        state=FileState.RECEIVING,
        reserved_accounted=True,
    )
    account = FileStorageAccount.objects.create(
        workspace=workspace, reserved_bytes=len(data)
    )
    candidate = FileStagingObject.objects.create(
        file=file,
        key=file.object_key,
        generation=file.generation,
        write_fence=file.write_fence,
        kind=FileObjectKind.STAGING,
        cleanup_after=timezone.now(),
    )

    active_cleanup_after = timezone.now() + timedelta(hours=1)
    candidate.cleanup_after = active_cleanup_after
    candidate.save(update_fields=("cleanup_after",))
    with pytest.raises(FileConflict, match="not retryable"):
        retry_publication(
            user=owner,
            workspace_id=workspace.id,
            ally_id=ally.id,
            message_id=message.id,
            publication_id=publication.id,
            revision=publication.revision,
        )
    candidate.refresh_from_db()
    assert candidate.cleanup_after == active_cleanup_after
    candidate.cleanup_after = timezone.now()
    candidate.save(update_fields=("cleanup_after",))

    from files.services import publication as publication_services

    reconcile = publication_services.reconcile_publication

    def unavailable(**_kwargs):
        raise RuntimeError("temporary reconciliation failure")

    monkeypatch.setattr(publication_services, "reconcile_publication", unavailable)
    first = cleanup_files(limit=100)
    file.refresh_from_db()
    publication.refresh_from_db()
    assert first.failures == 1
    assert file.state == FileState.FAILED
    assert publication.state == PublicationState.UPLOADING
    candidate = FileStagingObject.objects.get(file=file)
    assert candidate.deleted_at is None
    failed_cleanup_after = candidate.cleanup_after

    FilePublication.objects.filter(pk=publication.id).update(
        state=PublicationState.FAILED
    )
    publication.refresh_from_db()
    with pytest.raises(FileConflict, match="revision"):
        retry_publication(
            user=owner,
            workspace_id=workspace.id,
            ally_id=ally.id,
            message_id=message.id,
            publication_id=publication.id,
            revision=publication.revision - 1,
        )
    candidate.refresh_from_db()
    assert candidate.cleanup_after == failed_cleanup_after
    with pytest.raises(FileConflict, match="cleanup"):
        retry_publication(
            user=owner,
            workspace_id=workspace.id,
            ally_id=ally.id,
            message_id=message.id,
            publication_id=publication.id,
            revision=publication.revision,
        )
    candidate.refresh_from_db()
    assert candidate.cleanup_after <= timezone.now()
    FilePublication.objects.filter(pk=publication.id).update(
        state=PublicationState.UPLOADING
    )
    monkeypatch.setattr(publication_services, "reconcile_publication", reconcile)

    assert cleanup_files(limit=100).deleted == 1
    publication.refresh_from_db()
    file.refresh_from_db()
    account.refresh_from_db()
    assert publication.state == PublicationState.FAILED
    assert file.state == FileState.FAILED
    assert account.reserved_bytes == 0

    retry = retry_publication(
        user=owner,
        workspace_id=workspace.id,
        ally_id=ally.id,
        message_id=message.id,
        publication_id=publication.id,
        revision=publication.revision,
    )
    account.refresh_from_db()
    assert retry["state"] == PublicationState.RETRY_PENDING
    assert account.reserved_bytes == len(data)


@pytest.mark.django_db
def test_staging_cleanup_reconciles_an_inbound_message(file_context):
    _owner, _workspace, _ally, _conversation = file_context
    reservation = _reserve(
        file_context,
        b"abandoned inbound bytes",
        "cleanup-inbound-abandoned-key",
    )
    file = reservation.files[0]
    file.state = FileState.RECEIVING
    file.object_key = "staging/inbound-abandoned"
    file.save(update_fields=("state", "object_key", "updated_at"))
    FileStagingObject.objects.create(
        file=file,
        key=file.object_key,
        generation=file.generation,
        write_fence=file.write_fence,
        kind=FileObjectKind.STAGING,
        cleanup_after=timezone.now(),
    )

    with TestCase.captureOnCommitCallbacks(execute=True):
        assert cleanup_files(limit=100).deleted == 1

    reservation.message.refresh_from_db()
    assert reservation.message.preparation == MessagePreparation.FAILED
