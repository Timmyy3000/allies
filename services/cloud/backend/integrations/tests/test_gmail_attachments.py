import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from auths.exceptions import WorkspaceAccessDenied
from auths.models import User
from chat.models import Message
from chat.tests.test_dispatch import dispatch_records  # noqa: F401
from files.exceptions import FileScopeUnavailable
from files.inspection import ClamAvClient
from files.inspection import inspect_file as inspect_bytes
from files.models import (
    FilePublication,
    FileState,
    FileStorageAccount,
    FileVersion,
    PublicationState,
)
from files.services.access import open_file, private_file_stream
from files.services.inspection import inspect_file
from files.services.publication import reconcile_publication, sanitize_reply_file_links
from files.storage import InMemoryFileObjectStore, set_file_store
from files.tests.test_inspection import FakeTransport
from integrations.models import IntegrationToolCall
from integrations.services import gmail_attachments, gmail_tool
from integrations.services.grants import revoke_ally_grant, set_ally_grant
from integrations.tests.test_gmail_tool import (  # noqa: F401
    _next_message,
    _turn,
    gmail,
    run,
)
from integrations.tests.test_grants import gmail_settings  # noqa: F401

PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"


@pytest.fixture
def attachment(gmail, settings, monkeypatch):  # noqa: F811
    settings.ALLIES_FILE_STORAGE_ENABLED = True
    settings.ALLIES_FILE_INSPECTION_ENABLED = True
    settings.ALLIES_FILE_STORAGE_CAPACITY_BYTES = 100_000_000
    settings.ALLIES_FILE_SCANNER_HOST = "scanner.example.test"
    store = InMemoryFileObjectStore()
    set_file_store(store)
    Message.objects.filter(pk=gmail["turn"]["message_id"]).update(
        foundry_binding_id=gmail["binding"].id, execution_claimed_at=timezone.now()
    )
    part = {
        "partId": "1.0",
        "filename": "certificate.pdf",
        "mimeType": "application/pdf",
        "body": {"size": len(PDF), "attachmentId": "external_1"},
    }
    payload = {
        "id": "m1",
        "payload": {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {
                        "data": base64.urlsafe_b64encode(
                            b"Certificate attached"
                        ).decode()
                    },
                },
                {"mimeType": "multipart/mixed", "parts": [part]},
            ],
        },
    }
    calls = []
    data = {
        "size": len(PDF),
        "data": base64.urlsafe_b64encode(PDF).decode().rstrip("="),
    }

    def fetch(token, path, **kwargs):
        calls.append((path, kwargs))
        return data if "/attachments/" in path else payload

    monkeypatch.setattr(gmail_tool, "_gmail", fetch)
    yield {
        **gmail,
        "part": part,
        "payload": payload,
        "data": data,
        "fetches": calls,
        "store": store,
    }
    set_file_store(None)


def download(attachment):
    return run(
        attachment["turn"],
        {
            "action": "download_attachment",
            "message_id": "m1",
            "part_id": attachment["part"]["partId"],
        },
    )


def finish(attachment, scan_response="stream: OK"):
    file = FileVersion.objects.get()
    transport = FakeTransport(scan_response=scan_response, updated_at=timezone.now())

    def inspector(*, name, source, size, scanner_config):
        return inspect_bytes(
            name=name,
            source=source,
            size=size,
            scanner=ClamAvClient(scanner_config, transport=transport),
        )

    inspect_file(file_id=file.id, inspector=inspector)
    reconcile_publication(publication_id=file.publication_id)
    file.refresh_from_db()
    return file, transport


def test_nested_discovery_download_scan_and_private_bytes(
    attachment, monkeypatch, caplog
):
    set_ally_grant(secret=attachment["secret"], ally=attachment["ally"], level="read")
    status, result = run(attachment["turn"], {"action": "get", "message_id": "m1"})
    assert status == 200 and result["body"] == "Certificate attached"
    assert result["attachments"] == [
        {
            "part_id": "1.0",
            "filename": "certificate.pdf",
            "mime_type": "application/pdf",
            "size": len(PDF),
            "download_supported": True,
        }
    ]
    status, result = download(attachment)
    assert status == 200 and result["state"] == "validating" and "files" not in result
    assert len(attachment["fetches"]) == 3
    assert not IntegrationToolCall.objects.exists()
    file, scanner = finish(attachment)
    assert file.state == FileState.READY and scanner.scanned_chunks == [len(PDF)]
    status, result = run(
        attachment["turn"],
        {"action": "attachment_status", "publication_id": str(file.publication_id)},
    )
    reference = result["files"][0]["chat_reference"]
    assert status == 200 and result["state"] == "ready"
    assert sanitize_reply_file_links(
        message_id=attachment["turn"]["message_id"],
        binding_id=attachment["binding"].id,
        text=reference,
    ) == (reference, "")
    opened = open_file(
        user=file.owner,
        workspace_id=file.workspace_id,
        ally_id=file.ally_id,
        file_id=file.id,
    )
    assert b"".join(private_file_stream(opened=opened)) == PDF
    with pytest.raises((FileScopeUnavailable, WorkspaceAccessDenied)):
        open_file(
            user=User.objects.create_user(),
            workspace_id=file.workspace_id,
            ally_id=file.ally_id,
            file_id=file.id,
        )
    assert PDF.decode() not in json.dumps(result) + caplog.text
    assert attachment["data"]["data"] not in json.dumps(result) + caplog.text
    assert "ya29.live" not in json.dumps(result) + caplog.text


def test_inline_root_and_large_discovery_use_attachment_budget(attachment):
    content = PDF + b"x" * 5_000_000
    attachment["part"].update(
        partId="",
        body={"size": len(content), "data": base64.urlsafe_b64encode(content).decode()},
    )
    attachment["payload"]["payload"] = attachment["part"]
    status, result = run(attachment["turn"], {"action": "get", "message_id": "m1"})
    assert status == 200 and result["attachments"][0]["part_id"] == ""
    assert (
        attachment["fetches"][0][1]["max_bytes"] == gmail_attachments.MAX_RESPONSE_BYTES
    )
    assert result["body"] == "" and "data" not in result["attachments"][0]
    assert download(attachment)[1]["state"] == "validating"
    assert len(attachment["fetches"]) == 2


def test_repeat_download_and_active_upload_do_not_duplicate(attachment):
    result = download(attachment)[1]
    assert download(attachment)[1] == result
    assert len(attachment["fetches"]) == 2
    assert FilePublication.objects.count() == FileVersion.objects.count() == 1
    file = FileVersion.objects.get()
    FilePublication.objects.update(state=PublicationState.UPLOADING)
    FileVersion.objects.update(
        state=FileState.RECEIVING, lease_until=timezone.now() + timedelta(seconds=30)
    )
    assert download(attachment)[1]["state"] == "uploading"
    assert len(attachment["fetches"]) == 2
    assert file.expected_size == len(PDF)


def test_status_waits_for_inspection_and_rechecks_grant(attachment, monkeypatch):
    result = download(attachment)[1]
    waited = []

    def wait(seconds):
        waited.append(seconds)
        finish(attachment)
        revoke_ally_grant(secret=attachment["secret"], ally=attachment["ally"])

    monkeypatch.setattr(gmail_attachments.time, "sleep", wait)
    status, result = run(
        attachment["turn"],
        {"action": "attachment_status", "publication_id": result["publication_id"]},
    )
    assert waited and status == 403 and result["error"] == "gmail_not_granted"
    assert "files" not in result


def test_revoked_status_never_starts_file_polling(attachment, monkeypatch):
    result = download(attachment)[1]
    revoke_ally_grant(secret=attachment["secret"], ally=attachment["ally"])
    monkeypatch.setattr(
        gmail_attachments, "status", lambda *args: pytest.fail("unauthorized polling")
    )
    status, response = run(
        attachment["turn"],
        {"action": "attachment_status", "publication_id": result["publication_id"]},
    )
    assert status == 403 and response["error"] == "gmail_not_granted"


def test_resume_with_missing_file_returns_scoped_error(attachment):
    download(attachment)
    FilePublication.objects.update(state=PublicationState.UPLOADING)
    FileVersion.objects.all().delete()
    status, result = download(attachment)
    assert status == 403 and result["error"] == "gmail_attachment_unavailable"
    assert "files" not in result


def test_malformed_attachment_metadata_preserves_message_body(attachment):
    attachment["part"]["partId"] = "invalid"
    status, result = run(attachment["turn"], {"action": "get", "message_id": "m1"})
    assert status == 200 and result["body"] == "Certificate attached"
    assert result["attachments"] == [] and result["attachments_truncated"]


def test_pending_budget_and_rejected_file_never_emit_link(attachment, monkeypatch):
    result = download(attachment)[1]
    clock = iter([0, 0, 20])
    monkeypatch.setattr(gmail_attachments.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(gmail_attachments.time, "sleep", lambda _: None)
    status, pending = run(
        attachment["turn"],
        {"action": "attachment_status", "publication_id": result["publication_id"]},
    )
    assert status == 200 and pending["state"] == "validating" and "files" not in pending
    assert pending["publication_id"] == result["publication_id"]
    finish(attachment, "stream: Eicar FOUND")
    monkeypatch.setattr(gmail_attachments.time, "monotonic", lambda: 0)
    status, failed = run(
        attachment["turn"],
        {"action": "attachment_status", "publication_id": result["publication_id"]},
    )
    assert status == 200 and failed["state"] == "failed" and "files" not in failed


def test_status_is_source_turn_scoped_and_revocation_blocks_download(attachment):
    result = download(attachment)[1]
    later = _next_message(attachment["conversation"], 2)
    status, response = run(
        _turn(later, attachment["binding"]),
        {"action": "attachment_status", "publication_id": result["publication_id"]},
    )
    assert status == 403 and "files" not in response
    revoke_ally_grant(secret=attachment["secret"], ally=attachment["ally"])
    assert download(attachment)[0] == 403
    assert len(attachment["fetches"]) == 2


@pytest.mark.parametrize(
    "change,code",
    [
        ({"data": "not base64!"}, "gmail_attachment_invalid"),
        ({"size": len(PDF) + 1}, "gmail_attachment_invalid"),
        ({"data": ""}, "gmail_attachment_invalid"),
    ],
)
def test_invalid_attachment_bytes_are_not_reserved(attachment, change, code):
    attachment["data"].update(change)
    status, result = download(attachment)
    assert status == 422 and result["error"] == code
    assert not FilePublication.objects.exists()


@pytest.mark.parametrize(
    "name,size,code",
    [
        ("file.exe", len(PDF), "gmail_attachment_unsupported"),
        ("file.pdf", 25_000_001, "gmail_attachment_too_large"),
    ],
)
def test_unsupported_and_oversized_metadata_fail_before_fetch(
    attachment, name, size, code
):
    attachment["part"]["filename"] = name
    attachment["part"]["body"]["size"] = size
    status, result = download(attachment)
    assert status == 422 and result["error"] == code
    assert len(attachment["fetches"]) == 1 and not FilePublication.objects.exists()


def test_missing_duplicate_and_malformed_parts_fail_closed(attachment):
    attachment["part"]["partId"] = "2"
    assert (
        run(
            attachment["turn"],
            {"action": "download_attachment", "message_id": "m1", "part_id": "1"},
        )[0]
        == 422
    )
    attachment["payload"]["payload"]["parts"].append(attachment["part"])
    assert download(attachment)[0] == 422
    attachment["payload"]["payload"]["parts"] = "invalid"
    assert download(attachment)[0] == 422


def test_filename_sanitization_and_body_and_metadata_bounds(attachment):
    attachment["part"]["filename"] = "../../folder\\cert[1]\n.pdf"
    attachment["payload"]["payload"]["parts"][0]["body"]["data"] = (
        base64.urlsafe_b64encode(("😀" * 20_000).encode()).decode()
    )
    status, result = run(attachment["turn"], {"action": "get", "message_id": "m1"})
    assert (
        status == 200
        and result["truncated"]
        and len(json.dumps(result).encode()) < 64 * 1024
    )
    assert result["attachments"][0]["filename"] == "cert[1].pdf"
    assert download(attachment)[1]["state"] == "validating"
    file, _ = finish(attachment)
    ready = run(
        attachment["turn"],
        {"action": "attachment_status", "publication_id": str(file.publication_id)},
    )[1]
    assert "cert\\[1\\].pdf" in ready["files"][0]["chat_reference"]


def test_provider_limit_is_enforced_not_silently_truncated(monkeypatch):
    monkeypatch.setattr(gmail_tool, "urlopen", lambda *a, **kw: BytesIO(b"{}extra"))
    with pytest.raises(gmail_attachments.AttachmentError) as error:
        gmail_tool._gmail("token", "/messages/m1", max_bytes=2)
    assert error.value.code == "gmail_attachment_too_large"


def test_storage_failure_has_no_link_and_expired_upload_is_recoverable(
    attachment, monkeypatch
):
    original = attachment["store"].put_stream
    monkeypatch.setattr(
        attachment["store"],
        "put_stream",
        lambda **kw: (_ for _ in ()).throw(OSError("private failure")),
    )
    status, result = download(attachment)
    assert (
        status == 503
        and result["error"] == "gmail_attachment_unavailable"
        and "files" not in result
    )
    monkeypatch.setattr(attachment["store"], "put_stream", original)
    FileVersion.objects.update(lease_until=timezone.now() - timedelta(seconds=1))
    assert download(attachment)[1]["state"] == "validating"
    assert FileVersion.objects.count() == 1


def test_changed_provider_bytes_conflict_with_recoverable_publication(
    attachment, monkeypatch
):
    monkeypatch.setattr(
        attachment["store"],
        "put_stream",
        lambda **kw: (_ for _ in ()).throw(OSError("unavailable")),
    )
    assert download(attachment)[0] == 503
    FileVersion.objects.update(lease_until=timezone.now() - timedelta(seconds=1))
    changed = PDF.replace(b"Catalog", b"Changed")
    attachment["data"]["data"] = base64.urlsafe_b64encode(changed).decode()
    status, result = download(attachment)
    assert status == 422 and result["error"] == "gmail_attachment_conflict"
    assert "files" not in result and FileVersion.objects.count() == 1
    assert FileStorageAccount.objects.get().reserved_bytes == len(PDF)


@pytest.mark.parametrize(
    "args",
    [
        {"action": "download_attachment", "message_id": "m1"},
        {"action": "download_attachment", "message_id": "../m1", "part_id": "1"},
        {"action": "download_attachment", "message_id": "m1", "part_id": "../1"},
        {"action": "attachment_status", "publication_id": "not-an-id"},
        {
            "action": "attachment_status",
            "publication_id": str(uuid4()),
            "message_id": "m1",
        },
    ],
)
def test_new_actions_reject_invalid_fields(attachment, args):
    assert run(attachment["turn"], args)[0] == 422
    assert attachment["fetches"] == []


@pytest.mark.postgresql
@pytest.mark.skipif(
    connection.vendor != "postgresql", reason="requires PostgreSQL row locks"
)
@pytest.mark.django_db(transaction=True)
def test_concurrent_downloads_reserve_and_upload_one_file(attachment, monkeypatch):
    from files.services import publication

    monkeypatch.setattr(publication, "_enqueue_file_inspection", lambda _: None)
    barrier = Barrier(2)
    original = gmail_tool._gmail
    uploaded = []
    put = attachment["store"].put_stream

    def upload(**kwargs):
        uploaded.append(kwargs["key"])
        return put(**kwargs)

    monkeypatch.setattr(attachment["store"], "put_stream", upload)

    def fetch(token, path, **kwargs):
        if path == "/messages/m1":
            barrier.wait(timeout=10)
        return original(token, path, **kwargs)

    monkeypatch.setattr(gmail_tool, "_gmail", fetch)

    def retrieve():
        close_old_connections()
        try:
            return download(attachment)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(retrieve) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert all(status == 200 for status, _ in results)
    assert results[0][1]["publication_id"] == results[1][1]["publication_id"]
    assert FilePublication.objects.count() == FileVersion.objects.count() == 1
    assert FileVersion.objects.get().state == FileState.VALIDATING
    assert len(uploaded) == 1
    account = FileStorageAccount.objects.get()
    assert account.reserved_bytes == len(PDF) and account.retained_bytes == 0
