from hashlib import sha256
from io import BytesIO

import pytest
from django.core.cache import cache
from django.test import Client

from allies.models import Ally, AllyBinding, BindingStatus
from auths.models import User
from chat.models import Conversation, DispatchOutbox, DispatchState
from chat.services.dispatch import ensure_dispatch_after_accept
from files.exceptions import FileScopeUnavailable
from files.services.access import accepted_file_stream
from files.services.cleanup import tombstone_ally_files
from files.services.intake import (
    InspectionResult,
    promote_inspected_file,
    receive_file,
    reserve_send,
)
from files.storage import InMemoryFileObjectStore, set_file_store
from workspaces.models import Membership, Workspace


@pytest.fixture
def accepted_file(settings, db):
    cache.clear()
    settings.ALLIES_AUTH_DIGEST_KEY = "d" * 32
    settings.ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN = "f" * 32
    settings.ALLIES_FILE_ADMISSION_ENABLED = True
    settings.ALLIES_FILE_STORAGE_ENABLED = True
    settings.ALLIES_FILE_INSPECTION_ENABLED = True
    settings.ALLIES_FILE_INPUT_DELIVERY_ENABLED = True
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
    conversation = Conversation.objects.create(ally=ally)
    data = b"bounded private bytes"
    reservation = reserve_send(
        user=user,
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
        key="accepted-file-reader-key",
    )
    received = receive_file(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        file_id=reservation.files[0].id,
        generation=1,
        content_length=str(len(data)),
        stream=BytesIO(data),
    )
    file = promote_inspected_file(
        file_id=received.id,
        generation=1,
        result=InspectionResult(
            len(data), sha256(data).hexdigest(), "application/pdf", True
        ),
    )
    reservation.message.refresh_from_db()
    from files.services.preparation import reconcile_file_message

    reconcile_file_message(message_id=reservation.message.id)
    ensure_dispatch_after_accept(reservation.message)
    yield binding, reservation.message, file, data
    set_file_store(None)


@pytest.mark.django_db
def test_accepted_file_reader_requires_exact_manifest_binding_and_message(
    accepted_file,
):
    binding, message, file, data = accepted_file
    accepted = accepted_file_stream(
        binding_id=binding.id,
        message_id=message.id,
        file_id=file.id,
    )
    assert b"".join(accepted.content) == data

    with pytest.raises(FileScopeUnavailable):
        accepted_file_stream(
            binding_id=binding.id,
            message_id=message.id,
            file_id="550e8400-e29b-41d4-a716-446655440099",
        )
    with pytest.raises(FileScopeUnavailable):
        accepted_file_stream(
            binding_id="550e8400-e29b-41d4-a716-446655440099",
            message_id=message.id,
            file_id=file.id,
        )
    binding.status = BindingStatus.PENDING
    binding.save(update_fields=("status", "updated_at"))
    with pytest.raises(FileScopeUnavailable):
        accepted_file_stream(
            binding_id=binding.id,
            message_id=message.id,
            file_id=file.id,
        )


@pytest.mark.django_db
def test_accepted_file_reader_uses_frozen_manifest_after_receipt_redaction(
    accepted_file,
):
    binding, message, file, data = accepted_file
    outbox = DispatchOutbox.objects.get(message=message)
    outbox.status = DispatchState.ACCEPTED
    outbox.command_bytes = b""
    outbox.command_byte_length = 0
    outbox.save(update_fields=("status", "command_bytes", "command_byte_length"))
    file.source_message = None
    file.save(update_fields=("source_message", "updated_at"))

    accepted = accepted_file_stream(
        binding_id=binding.id,
        message_id=message.id,
        file_id=file.id,
    )

    assert b"".join(accepted.content) == data
    outbox.file_manifest[0]["sha256"] = "0" * 64
    outbox.save(update_fields=("file_manifest", "updated_at"))
    with pytest.raises(FileScopeUnavailable):
        accepted_file_stream(
            binding_id=binding.id,
            message_id=message.id,
            file_id=file.id,
        )


@pytest.mark.django_db
def test_accepted_file_reader_denies_unclaimed_message(accepted_file):
    binding, message, file, _data = accepted_file
    message.execution_claimed_at = None
    message.save(update_fields=("execution_claimed_at", "updated_at"))

    with pytest.raises(FileScopeUnavailable):
        accepted_file_stream(
            binding_id=binding.id,
            message_id=message.id,
            file_id=file.id,
        )


@pytest.mark.django_db
def test_accepted_file_reader_denies_a_tombstoned_ally(accepted_file):
    binding, message, file, _data = accepted_file
    tombstone_ally_files(ally_id=file.ally_id)

    with pytest.raises(FileScopeUnavailable):
        accepted_file_stream(
            binding_id=binding.id,
            message_id=message.id,
            file_id=file.id,
        )


@pytest.mark.django_db
def test_accepted_file_reader_requires_the_dispatched_binding_after_rebind(
    accepted_file,
):
    binding, message, file, _data = accepted_file
    original_binding_id = binding.id
    binding.delete()
    replacement = AllyBinding.objects.create(
        ally=message.conversation.ally,
        status=BindingStatus.BOUND,
        receipt_digest="c" * 64,
    )
    message.refresh_from_db()
    assert message.foundry_binding_id == original_binding_id

    for binding_id in (original_binding_id, replacement.id):
        with pytest.raises(FileScopeUnavailable):
            accepted_file_stream(
                binding_id=binding_id,
                message_id=message.id,
                file_id=file.id,
            )


@pytest.mark.django_db
def test_internal_accepted_file_route_uses_existing_foundry_service_token(
    accepted_file,
):
    binding, message, file, data = accepted_file
    route = (
        f"/api/v1/internal/v1/accepted-files/{file.id}/content?binding_id={binding.id}"
        f"&message_id={message.id}"
    )
    client = Client()

    denied = client.get(route)
    accepted = client.get(route, HTTP_AUTHORIZATION="Bearer " + "f" * 32)

    assert denied.status_code == 401
    assert accepted.status_code == 200
    assert accepted["Content-Length"] == str(len(data))
    assert accepted["X-Content-Type-Options"] == "nosniff"
    assert b"".join(accepted.streaming_content) == data


@pytest.mark.django_db
def test_preview_throttle_stops_parser_and_fails_closed(accepted_file, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from auths.throttle import ThrottleUnavailable
    from files.api import controllers
    from files.previews import Preview

    _binding, _message, file, _data = accepted_file
    monkeypatch.setattr(
        controllers, "_session", lambda request: SimpleNamespace(user=file.owner)
    )
    parser = Mock(
        return_value=Preview(kind="text", content="safe", media_type="text/plain")
    )
    monkeypatch.setattr(controllers, "private_file_preview", parser)
    route = f"/api/v1/workspaces/{file.workspace_id}/allies/{file.ally_id}/files/{file.id}/preview"
    client = Client()
    for _ in range(20):
        assert client.get(route).status_code == 200
    assert client.get(route).status_code == 429
    assert parser.call_count == 20

    def unavailable(**kwargs):
        raise ThrottleUnavailable

    monkeypatch.setattr(controllers, "check_rate_limit", unavailable)
    assert client.get(route).status_code == 503
    assert parser.call_count == 20
