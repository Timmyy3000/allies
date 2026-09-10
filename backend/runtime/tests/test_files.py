from __future__ import annotations

import hashlib
from urllib.error import HTTPError
from uuid import uuid4

import pytest
from django.utils import timezone
from pydantic import ValidationError

import runtime.services.files as file_service
from runtime.contracts import FileInputV1
from runtime.exceptions import RuntimeLeaseConflictError, RuntimeValidationError
from runtime.models import (
    Execution,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.services.claims import claim_next_execution
from runtime.services.runtime_auth import (
    authenticate_runtime_token,
    issue_runtime_credential,
)


class _Response:
    status = 200

    def __init__(self, body: bytes):
        self.body = body
        self.closed = False

    def read(self, maximum: int):
        value, self.body = self.body[:maximum], self.body[maximum:]
        return value

    def close(self):
        self.closed = True


class _Opener:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        return self.response


@pytest.fixture
def file_claim(db):
    workspace = Workspace.objects.create(
        tenant_ref=str(uuid4()),
        fly_app_ref="app",
        volume_ref="volume",
        machine_ref="machine-1",
        machine_generation=1,
        provisioning_phase=WorkspaceProvisioningPhase.IDLE,
        ready_generation=1,
        ready_start_epoch=0,
        ready_boot_id=uuid4(),
        runtime_last_seen_at=timezone.now(),
    )
    profile = RuntimeProfile.objects.create(
        workspace=workspace,
        ally_ref="ally",
        hermes_profile_key="ally",
        lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        materialized_generation=1,
        seed_payload={"model": "gpt-5.6-luna"},
    )
    content = b"accepted content"
    file_id = uuid4()
    execution = Execution.objects.create(
        workspace=workspace,
        profile=profile,
        idempotency_key="file-turn",
        source_kind="conversation_message",
        cloud_binding_id=uuid4(),
        cloud_message_id=uuid4(),
        input_payload={
            "message": "",
            "cloud_conversation_ref": str(uuid4()),
            "files": [
                {
                    "file_id": str(file_id),
                    "name": "notes.txt",
                    "media_type": "text/plain",
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            ],
        },
    )
    issued = issue_runtime_credential(workspace.id, "runtime-file-secret")
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 2)
    assert claim is not None
    return context, claim, execution, file_id, content


@pytest.mark.django_db
def test_proxy_derives_cloud_scope_from_the_current_attempt(
    file_claim, settings, monkeypatch
):
    context, claim, execution, file_id, content = file_claim
    settings.ALLIES_RUNTIME_FILE_INPUT_ENABLED = True
    settings.ALLIES_CLOUD_URL = "https://cloud.example.test"
    settings.ALLIES_CLOUD_EVENT_SERVICE_TOKEN = "s" * 32
    opener = _Opener(_Response(content))
    monkeypatch.setattr(file_service, "build_opener", lambda *_handlers: opener)

    proxied = file_service.open_incoming_file(
        context, claim.attempt_id, claim.lease_token, file_id
    )

    assert b"".join(proxied.chunks) == content
    request, timeout = opener.requests[0]
    assert timeout == 120
    assert request.full_url == (
        f"https://cloud.example.test/api/v1/internal/v1/accepted-files/{file_id}/content"
        f"?binding_id={execution.cloud_binding_id}&message_id={execution.cloud_message_id}"
    )
    assert request.get_header("Authorization") == "Bearer " + "s" * 32


@pytest.mark.django_db
@pytest.mark.parametrize(
    "media_type",
    ["text/中文", "text/pläin", "text/plain\r\nX-Test: yes", "text/plain\x7f"],
)
def test_unsafe_media_type_is_rejected_at_ingress_and_before_proxying(
    file_claim, settings, monkeypatch, media_type
):
    context, claim, execution, file_id, _content = file_claim
    settings.ALLIES_RUNTIME_FILE_INPUT_ENABLED = True
    descriptor = execution.input_payload["files"][0]
    descriptor["media_type"] = media_type
    with pytest.raises(ValidationError):
        FileInputV1.model_validate(descriptor)
    execution.save(update_fields=["input_payload"])
    opener = _Opener(_Response(b"unused"))
    monkeypatch.setattr(file_service, "build_opener", lambda *_handlers: opener)

    with pytest.raises(RuntimeLeaseConflictError, match="manifest is invalid"):
        file_service.open_incoming_file(
            context, claim.attempt_id, claim.lease_token, file_id
        )
    assert opener.requests == []


@pytest.mark.django_db
def test_proxy_denies_a_file_outside_the_frozen_manifest(file_claim, settings):
    context, claim, _execution, _file_id, _content = file_claim
    settings.ALLIES_RUNTIME_FILE_INPUT_ENABLED = True

    with pytest.raises(
        RuntimeLeaseConflictError, match="not in the execution manifest"
    ):
        file_service.open_incoming_file(
            context, claim.attempt_id, claim.lease_token, uuid4()
        )


@pytest.mark.django_db
@pytest.mark.parametrize("status, expected_opens", [(404, 1), (503, 3)])
def test_cloud_open_errors_are_terminal_before_model_dispatch(
    file_claim, settings, monkeypatch, status, expected_opens
):
    context, claim, _execution, file_id, _content = file_claim
    settings.ALLIES_RUNTIME_FILE_INPUT_ENABLED = True
    settings.ALLIES_CLOUD_URL = "https://cloud.example.test"
    settings.ALLIES_CLOUD_EVENT_SERVICE_TOKEN = "s" * 32
    sleeps = []

    class FailingOpener:
        opens = 0

        def open(self, request, *, timeout):
            self.opens += 1
            raise HTTPError(request.full_url, status, "failed", {}, None)

    opener = FailingOpener()
    monkeypatch.setattr(file_service, "build_opener", lambda *_handlers: opener)
    monkeypatch.setattr(file_service, "sleep", sleeps.append)

    with pytest.raises(RuntimeValidationError, match="unavailable"):
        file_service.open_incoming_file(
            context, claim.attempt_id, claim.lease_token, file_id
        )

    assert opener.opens == expected_opens
    assert sleeps == ([1, 2] if status == 503 else [])
