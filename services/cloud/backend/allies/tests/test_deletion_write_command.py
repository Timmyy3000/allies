from hashlib import sha256
from io import BytesIO, StringIO
from uuid import uuid4

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from allies.models import Ally, AllyDeletionState
from auths.models import User
from files.models import (
    FileAllyTombstone,
    FileDirection,
    FileIOOutcome,
    FileStagingObject,
    FileState,
    FileVersion,
)
from files.services.cleanup import cleanup_files
from files.storage import InMemoryFileObjectStore, set_file_store
from workspaces.models import Workspace


@pytest.fixture
def write(db):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Synthetic recovery")
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study",
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
        deletion_state=AllyDeletionState.REPAIR_REQUIRED,
    )
    FileAllyTombstone.objects.create(
        ally=ally,
        tombstoned_at=timezone.now(),
        foundry_cleanup_receipt="synthetic-verified-receipt",
    )
    file = FileVersion.objects.create(
        workspace=workspace,
        ally=ally,
        owner=user,
        direction=FileDirection.INBOUND,
        original_name="test.txt",
        media_type="text/plain",
        expected_size=4,
        sha256=sha256(b"test").hexdigest(),
        object_key="synthetic/exact-key",
        state=FileState.CLEANUP_PENDING,
    )
    candidate = FileStagingObject.objects.create(
        file=file,
        key=file.object_key,
        generation=file.generation,
        write_fence=file.write_fence,
        cleanup_after=timezone.now(),
        io_outcome=FileIOOutcome.AMBIGUOUS,
    )
    store = InMemoryFileObjectStore()
    store.put_stream(
        key=file.object_key,
        stream=BytesIO(b"test"),
        content_type="text/plain",
        size=4,
        sha256=file.sha256,
    )
    set_file_store(store)
    yield (
        file,
        candidate,
        {
            "workspace_id": str(workspace.id),
            "ally_id": str(ally.id),
            "file_id": str(file.id),
            "write_fence": str(candidate.write_fence),
            "key": candidate.key,
            "outcome": "completed",
        },
    )
    set_file_store(None)


@pytest.mark.django_db
@pytest.mark.parametrize("outcome", ["completed", "aborted"])
def test_verified_settlement_keeps_candidate_until_cleanup(write, outcome):
    file, candidate, arguments = write
    assert cleanup_files(ally_id=file.ally_id).deleted == 0
    output = StringIO()
    call_command(
        "settle_ally_deletion_file_write",
        stdout=output,
        **{**arguments, "outcome": outcome},
    )
    candidate.refresh_from_db()
    assert candidate.io_outcome == outcome
    assert candidate.deleted_at is None
    assert candidate.key not in output.getvalue()
    assert cleanup_files(ally_id=file.ally_id).deleted == 1
    candidate.refresh_from_db()
    assert candidate.deleted_at is not None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field", ["workspace_id", "ally_id", "file_id", "write_fence", "key", "outcome"]
)
def test_settlement_rejects_wrong_identity_or_outcome(write, field):
    _file, candidate, arguments = write
    invalid = "wrong" if field in {"key", "outcome"} else str(uuid4())
    with pytest.raises(CommandError):
        call_command("settle_ally_deletion_file_write", **{**arguments, field: invalid})
    candidate.refresh_from_db()
    assert candidate.io_outcome == FileIOOutcome.AMBIGUOUS
    assert candidate.deleted_at is None


@pytest.mark.django_db
def test_settlement_rejects_active_ally_and_already_settled_write(write):
    file, candidate, arguments = write
    Ally.objects.filter(pk=file.ally_id).update(deletion_state=AllyDeletionState.ACTIVE)
    with pytest.raises(CommandError):
        call_command("settle_ally_deletion_file_write", **arguments)
    Ally.objects.filter(pk=file.ally_id).update(
        deletion_state=AllyDeletionState.REPAIR_REQUIRED
    )
    candidate.io_outcome = FileIOOutcome.ABORTED
    candidate.save(update_fields=("io_outcome",))
    with pytest.raises(CommandError):
        call_command("settle_ally_deletion_file_write", **arguments)
    candidate.refresh_from_db()
    assert candidate.io_outcome == FileIOOutcome.ABORTED
