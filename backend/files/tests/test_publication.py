from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from allies.models import Ally, AllyBinding, BindingStatus
from auths.models import User
from chat.models import Conversation, Message, MessageOrigin, MessageSender
from files.exceptions import FileConflict, FileScopeUnavailable
from files.models import (
    FileAllyTombstone,
    FilePublication,
    FileState,
    PublicationState,
)
from files.services.intake import InspectionResult, promote_inspected_file
from files.services.publication import (
    claim_publication_retries,
    create_publication_placeholder,
    due_publication_bindings,
    publication_retry_result,
    publication_view,
    receive_publication_file,
    reconcile_publication,
    reserve_publication,
)
from files.storage import InMemoryFileObjectStore, set_file_store
from workspaces.models import Membership, Workspace


@pytest.fixture
def publication_source(settings, db):
    cache.clear()
    settings.ALLIES_AUTH_DIGEST_KEY = "d" * 32
    settings.ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN = "f" * 32
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
    binding = AllyBinding.objects.create(
        ally=ally, status=BindingStatus.BOUND, receipt_digest="b" * 64
    )
    conversation = Conversation.objects.create(ally=ally)
    message = Message.objects.create(
        conversation=conversation,
        sequence=1,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="return a file",
        send_key_digest="a" * 64,
        content_fingerprint="c" * 64,
        execution_claimed_at=timezone.now(),
        foundry_binding_id=binding.id,
    )
    yield owner, workspace, ally, binding, message
    set_file_store(None)


def _manifest(data: bytes, source_version_id=None):
    return [
        {
            "source_version_id": str(source_version_id or uuid4()),
            "name": "result.pdf",
            "size": len(data),
            "sha256": sha256(data).hexdigest(),
        }
    ]


@pytest.mark.django_db
def test_placeholder_is_create_only_then_reservation_fills_once(publication_source):
    _owner, _workspace, _ally, binding, message = publication_source
    publication_id = uuid4()
    placeholder = create_publication_placeholder(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        error_code="publication_unavailable",
    )
    assert placeholder["state"] == PublicationState.FAILED

    data = b"fixed return bytes"
    reserved = reserve_publication(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        files=_manifest(data),
    )
    assert reserved["state"] == PublicationState.UPLOADING
    assert len(reserved["files"]) == 1
    assert (
        create_publication_placeholder(
            binding_id=binding.id,
            message_id=message.id,
            publication_id=publication_id,
            error_code="publication_unavailable",
        )["state"]
        == PublicationState.UPLOADING
    )
    with pytest.raises(FileConflict):
        reserve_publication(
            binding_id=binding.id,
            message_id=message.id,
            publication_id=publication_id,
            files=_manifest(b"changed"),
        )


@pytest.mark.django_db
def test_publication_upload_keeps_fixed_source_and_only_links_when_ready(
    publication_source,
):
    _owner, _workspace, _ally, binding, message = publication_source
    data = b"fixed return bytes"
    publication_id = uuid4()
    reserved = reserve_publication(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        files=_manifest(data),
    )
    file_id = reserved["files"][0]["id"]
    received = receive_publication_file(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        file_id=file_id,
        generation=1,
        revision=1,
        lease_token=None,
        content_length=str(len(data)),
        stream=BytesIO(data),
    )
    assert received.state == FileState.VALIDATING
    assert (
        "open_path" not in publication_view(publication_id=publication_id)["files"][0]
    )

    promote_inspected_file(
        file_id=received.id,
        generation=1,
        result=InspectionResult(
            len(data), sha256(data).hexdigest(), "application/pdf", True
        ),
    )
    reconcile_publication(publication_id=publication_id)
    ready = publication_view(publication_id=publication_id)
    assert ready["state"] == PublicationState.READY
    assert ready["files"][0]["open_path"] == f"/files/{file_id}"
    assert FilePublication.objects.get(pk=publication_id).files.get().source_version_id


@pytest.mark.django_db
def test_publication_view_maps_files_by_fixed_source_version(publication_source):
    _owner, _workspace, _ally, binding, message = publication_source
    first, second = uuid4(), uuid4()
    files = [
        {
            "source_version_id": str(first),
            "name": "first.pdf",
            "size": 3,
            "sha256": sha256(b"one").hexdigest(),
        },
        {
            "source_version_id": str(second),
            "name": "second.pdf",
            "size": 3,
            "sha256": sha256(b"two").hexdigest(),
        },
    ]
    publication_id = uuid4()
    reserve_publication(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        files=files,
    )
    FilePublication.objects.get(pk=publication_id).files.update(
        created_at=timezone.now()
    )
    rows = publication_view(publication_id=publication_id)["files"]
    assert {
        row["source_version_id"]: (row["name"], row["size"], row["sha256"])
        for row in rows
    } == {
        str(first): ("first.pdf", 3, sha256(b"one").hexdigest()),
        str(second): ("second.pdf", 3, sha256(b"two").hexdigest()),
    }


@pytest.mark.django_db
def test_publication_id_cannot_move_to_a_different_source(publication_source):
    _owner, workspace, _ally, binding, message = publication_source
    publication_id = uuid4()
    initial = reserve_publication(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        files=_manifest(b"fixed return bytes"),
    )
    other_ally = Ally.objects.create(
        workspace=workspace,
        name="Nova",
        job="Study",
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    other_binding = AllyBinding.objects.create(
        ally=other_ally, status=BindingStatus.BOUND, receipt_digest="c" * 64
    )
    other_conversation = Conversation.objects.create(ally=other_ally)
    other_message = Message.objects.create(
        conversation=other_conversation,
        sequence=1,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="return a file",
        send_key_digest="d" * 64,
        content_fingerprint="e" * 64,
        execution_claimed_at=timezone.now(),
        foundry_binding_id=other_binding.id,
    )
    with pytest.raises(FileConflict):
        reserve_publication(
            binding_id=other_binding.id,
            message_id=other_message.id,
            publication_id=publication_id,
            files=_manifest(b"other return bytes"),
        )
    assert publication_view(publication_id=publication_id) == initial
    assert (
        FilePublication.objects.get(pk=publication_id).source_message_id == message.id
    )


@pytest.mark.django_db
def test_retry_claim_fences_result_and_due_binding(publication_source):
    _owner, _workspace, _ally, binding, message = publication_source
    publication_id = uuid4()
    reserve_publication(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        files=_manifest(b"fixed return bytes"),
    )
    FilePublication.objects.filter(pk=publication_id).update(
        state=PublicationState.RETRY_PENDING, retry_due_at=timezone.now()
    )
    claim = claim_publication_retries(binding_id=binding.id, limit=20)[0]
    assert claim.publication.lease_token
    result = publication_retry_result(
        publication_id=publication_id,
        revision=claim.publication.revision,
        lease_token=claim.publication.lease_token,
        outcome="failed",
        safe_error_code="source_unavailable",
    )
    assert result["state"] == PublicationState.RETRY_PENDING
    with pytest.raises(FileConflict):
        publication_retry_result(
            publication_id=publication_id,
            revision=claim.publication.revision,
            lease_token=claim.publication.lease_token,
            outcome="submitted",
        )


@pytest.mark.django_db
def test_publication_requires_the_original_execution_binding(publication_source):
    _owner, _workspace, ally, binding, message = publication_source
    original_binding_id = binding.id
    binding.delete()
    replacement = AllyBinding.objects.create(
        ally=ally, status=BindingStatus.BOUND, receipt_digest="c" * 64
    )
    message.refresh_from_db()
    assert message.foundry_binding_id == original_binding_id
    with pytest.raises(FileScopeUnavailable):
        reserve_publication(
            binding_id=replacement.id,
            message_id=message.id,
            publication_id=uuid4(),
            files=_manifest(b"fixed return bytes"),
        )


@pytest.mark.django_db
def test_retry_result_rejects_expired_or_incomplete_claim(publication_source):
    _owner, _workspace, _ally, binding, message = publication_source
    publication_id = uuid4()
    reserve_publication(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        files=_manifest(b"fixed return bytes"),
    )
    FilePublication.objects.filter(pk=publication_id).update(
        state=PublicationState.RETRY_PENDING,
        retry_due_at=timezone.now(),
    )
    claim = claim_publication_retries(binding_id=binding.id, limit=20)[0]
    with pytest.raises(FileConflict, match="not submitted"):
        publication_retry_result(
            publication_id=publication_id,
            revision=claim.publication.revision,
            lease_token=claim.publication.lease_token,
            outcome="submitted",
        )
    FilePublication.objects.filter(pk=publication_id).update(
        lease_until=timezone.now() - timedelta(seconds=1)
    )
    with pytest.raises(FileConflict, match="lease"):
        publication_retry_result(
            publication_id=publication_id,
            revision=claim.publication.revision,
            lease_token=claim.publication.lease_token,
            outcome="failed",
            safe_error_code="source_unavailable",
        )


@pytest.mark.django_db
def test_scanner_ready_before_retry_ack_preserves_ready(publication_source):
    _owner, _workspace, _ally, binding, message = publication_source
    data = b"fixed return bytes"
    publication_id = uuid4()
    reserved = reserve_publication(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        files=_manifest(data),
    )
    file_id = reserved["files"][0]["id"]
    received = receive_publication_file(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        file_id=file_id,
        generation=1,
        revision=1,
        lease_token=None,
        content_length=str(len(data)),
        stream=BytesIO(data),
    )
    FilePublication.objects.filter(pk=publication_id).update(
        state=PublicationState.RETRY_PENDING,
        retry_due_at=timezone.now(),
    )
    claim = claim_publication_retries(binding_id=binding.id, limit=20)[0]
    promote_inspected_file(
        file_id=received.id,
        generation=1,
        result=InspectionResult(
            len(data), sha256(data).hexdigest(), "application/pdf", True
        ),
    )
    result = publication_retry_result(
        publication_id=publication_id,
        revision=claim.publication.revision,
        lease_token=claim.publication.lease_token,
        outcome="submitted",
    )
    assert result["state"] == PublicationState.READY


@pytest.mark.django_db
def test_fifth_expired_retry_stops_due_wakes(publication_source):
    _owner, _workspace, _ally, binding, message = publication_source
    publication_id = uuid4()
    reserve_publication(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        files=_manifest(b"fixed return bytes"),
    )
    FilePublication.objects.filter(pk=publication_id).update(
        state=PublicationState.RETRY_PENDING,
        retry_due_at=timezone.now(),
        retry_attempts=4,
    )
    claim_publication_retries(binding_id=binding.id, limit=20)
    FilePublication.objects.filter(pk=publication_id).update(
        lease_until=timezone.now() - timedelta(seconds=1)
    )
    assert due_publication_bindings(limit=20) == ((str(binding.id),), None)
    assert claim_publication_retries(binding_id=binding.id, limit=20) == ()
    assert due_publication_bindings(limit=20) == ((), None)
    publication = FilePublication.objects.get(pk=publication_id)
    assert publication.state == PublicationState.FAILED
    assert publication.safe_error_code == "publication_retry_exhausted"


@pytest.mark.django_db
def test_inactive_binding_or_tombstone_cannot_mutate_retries(publication_source):
    _owner, _workspace, ally, binding, message = publication_source
    publication_id = uuid4()
    reserve_publication(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        files=_manifest(b"fixed return bytes"),
    )
    FilePublication.objects.filter(pk=publication_id).update(
        state=PublicationState.RETRY_PENDING,
        retry_due_at=timezone.now(),
    )
    binding.status = BindingStatus.PENDING
    binding.save(update_fields=("status", "updated_at"))

    assert due_publication_bindings(limit=20) == ((), None)
    assert claim_publication_retries(binding_id=binding.id, limit=20) == ()
    publication = FilePublication.objects.get(pk=publication_id)
    assert publication.state == PublicationState.RETRY_PENDING
    assert publication.retry_attempts == 0

    binding.status = BindingStatus.BOUND
    binding.save(update_fields=("status", "updated_at"))
    claim = claim_publication_retries(binding_id=binding.id, limit=20)[0]
    FileAllyTombstone.objects.create(ally=ally, tombstoned_at=timezone.now())
    baseline = FilePublication.objects.get(pk=publication_id)

    assert due_publication_bindings(limit=20) == ((), None)
    assert claim_publication_retries(binding_id=binding.id, limit=20) == ()
    with pytest.raises(FileScopeUnavailable):
        publication_retry_result(
            publication_id=publication_id,
            revision=claim.publication.revision,
            lease_token=claim.publication.lease_token,
            outcome="failed",
            safe_error_code="source_unavailable",
        )
    publication.refresh_from_db()
    assert publication.state == baseline.state
    assert publication.retry_attempts == baseline.retry_attempts
    assert publication.lease_token == baseline.lease_token


@pytest.mark.django_db
def test_internal_publication_status_uses_established_bearer_header(publication_source):
    _owner, _workspace, _ally, binding, message = publication_source
    publication_id = uuid4()
    payload = {
        "binding_id": str(binding.id),
        "message_id": str(message.id),
        "publication_id": str(publication_id),
        "state": "failed",
        "error_code": "publication_unavailable",
    }
    client = Client()
    denied = client.post(
        "/api/v1/internal/v1/file-publication-status",
        data=payload,
        content_type="application/json",
    )
    accepted = client.post(
        "/api/v1/internal/v1/file-publication-status",
        data=payload,
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + "f" * 32,
    )
    assert denied.status_code == 401
    assert accepted.status_code == 202


@pytest.mark.django_db
def test_retry_claim_api_returns_frozen_file_size_and_digest(publication_source):
    _owner, _workspace, _ally, binding, message = publication_source
    source_version_id = uuid4()
    data = b"frozen return bytes"
    publication_id = uuid4()
    reserved = reserve_publication(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        files=_manifest(data, source_version_id=source_version_id),
    )
    FilePublication.objects.filter(pk=publication_id).update(
        state=PublicationState.RETRY_PENDING,
        retry_due_at=timezone.now(),
    )

    response = Client().post(
        "/api/v1/internal/v1/file-publication-retries/claim",
        data={"binding_id": str(binding.id), "limit": 20},
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + "f" * 32,
    )

    assert response.status_code == 200
    row = response.json()["data"]["items"][0]["files"][0]
    assert row == {
        "id": reserved["files"][0]["id"],
        "source_version_id": str(source_version_id),
        "size": len(data),
        "sha256": sha256(data).hexdigest(),
        "generation": 1,
        "state": FileState.PENDING,
    }


@pytest.mark.django_db
def test_retry_claim_lease_token_authorizes_the_following_http_upload(
    publication_source,
):
    _owner, _workspace, _ally, binding, message = publication_source
    data = b"retry upload bytes"
    publication_id = uuid4()
    reserved = reserve_publication(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        files=_manifest(data),
    )
    FilePublication.objects.filter(pk=publication_id).update(
        state=PublicationState.RETRY_PENDING,
        retry_due_at=timezone.now(),
        revision=2,
    )
    client = Client()
    claim = client.post(
        "/api/v1/internal/v1/file-publication-retries/claim",
        data={"binding_id": str(binding.id), "limit": 20},
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + "f" * 32,
    ).json()["data"]["items"][0]

    response = client.put(
        f"/api/v1/internal/v1/file-publications/{publication_id}/files/"
        f"{reserved['files'][0]['id']}/content?generation=1",
        data=data,
        content_type="application/octet-stream",
        HTTP_AUTHORIZATION="Bearer " + "f" * 32,
        HTTP_X_ALLIES_PUBLICATION_REVISION=str(claim["revision"]),
        HTTP_X_ALLIES_PUBLICATION_LEASE_TOKEN=claim["lease_token"],
    )

    assert response.status_code == 202
    assert response.json()["data"]["state"] == FileState.VALIDATING


@pytest.mark.django_db
def test_internal_upload_hides_an_unknown_publication_file(publication_source):
    _owner, _workspace, _ally, binding, message = publication_source
    data = b"unknown file"
    publication_id = uuid4()
    reserve_publication(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        files=_manifest(data),
    )

    response = Client().put(
        f"/api/v1/internal/v1/file-publications/{publication_id}/files/"
        f"{uuid4()}/content?generation=1",
        data=data,
        content_type="application/octet-stream",
        HTTP_AUTHORIZATION="Bearer " + "f" * 32,
        HTTP_X_ALLIES_PUBLICATION_REVISION="1",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_inspection_promotes_first_file_before_sibling_upload(publication_source):
    _owner, _workspace, _ally, binding, message = publication_source
    data = b"fixed return bytes"
    publication_id = uuid4()
    reserved = reserve_publication(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        files=_manifest(data) + _manifest(data),
    )
    for index, file in enumerate(reserved["files"]):
        received = receive_publication_file(
            binding_id=binding.id,
            message_id=message.id,
            publication_id=publication_id,
            file_id=file["id"],
            generation=1,
            revision=1,
            lease_token=None,
            content_length=str(len(data)),
            stream=BytesIO(data),
        )
        if index == 0:
            assert (
                FilePublication.objects.get(pk=publication_id).state
                == PublicationState.UPLOADING
            )
        promoted = promote_inspected_file(
            file_id=received.id,
            generation=1,
            result=InspectionResult(
                len(data), sha256(data).hexdigest(), "application/pdf", True
            ),
        )
        assert promoted.state == FileState.READY
        reconcile_publication(publication_id=publication_id)
    assert (
        publication_view(publication_id=publication_id)["state"]
        == PublicationState.READY
    )


@pytest.mark.django_db
def test_partial_retry_remains_claimable_after_inspection(publication_source):
    _owner, _workspace, _ally, binding, message = publication_source
    publication_id = uuid4()
    reserved = reserve_publication(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        files=_manifest(b"first") + _manifest(b"second"),
    )
    FilePublication.objects.filter(pk=publication_id).update(
        state=PublicationState.RETRY_PENDING, retry_due_at=timezone.now()
    )
    claim = claim_publication_retries(binding_id=binding.id, limit=20)[0]
    received = receive_publication_file(
        binding_id=binding.id,
        message_id=message.id,
        publication_id=publication_id,
        file_id=reserved["files"][0]["id"],
        generation=1,
        revision=1,
        lease_token=claim.publication.lease_token,
        content_length="5",
        stream=BytesIO(b"first"),
    )
    promote_inspected_file(
        file_id=received.id,
        generation=1,
        result=InspectionResult(
            5, sha256(b"first").hexdigest(), "application/pdf", True
        ),
    )
    reconcile_publication(publication_id=publication_id)
    FilePublication.objects.filter(pk=publication_id).update(
        lease_until=timezone.now() - timedelta(seconds=1)
    )
    assert len(claim_publication_retries(binding_id=binding.id, limit=20)) == 1
