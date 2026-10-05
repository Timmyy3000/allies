from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.test import override_settings
from django.utils import timezone

from runtime.exceptions import (
    RuntimeIdempotencyConflictError,
    RuntimeLeaseConflictError,
)
from runtime.models import (
    Attempt,
    Execution,
    PublicationIntent,
    PublicationIntentState,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.services import publications as publication_service
from runtime.services.claims import claim_next_execution
from runtime.services.publications import (
    acknowledge_frozen_publication,
    claim_publication_retries,
    create_publication_intent,
    record_publication_retry,
    register_publication,
    upload_publication_file,
    wake_due_publications,
)
from runtime.services.runtime_auth import (
    authenticate_runtime_token,
    issue_runtime_credential,
)


@pytest.mark.django_db
@pytest.mark.parametrize("size", [3_000_000, 25_000_000, 30_000_000])
def test_publication_upload_api_reads_the_bounded_binary_body(
    publication_claim, client, monkeypatch, size
):
    _context, _claim, profile, _execution, token = publication_claim
    received = []

    def receive(*args):
        content = args[5]
        received.append(len(content))
        if len(content) > publication_service.MAX_PUBLICATION_FILE_BYTES:
            return publication_service.upload_publication_file(*args)
        return 202, {"state": "validating"}

    monkeypatch.setattr("runtime.api.register.upload_publication_file", receive)
    path = (
        f"/api/v1/runtime/profiles/{profile.id}/file-publications/{uuid4()}"
        f"/files/{uuid4()}/content?generation=1"
    )
    response = client.put(
        path,
        b"x" * size,
        content_type="application/octet-stream",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_X_ALLIES_PUBLICATION_REVISION="1",
    )
    assert response.status_code == (202 if size <= 25_000_000 else 422)
    assert received == [min(size, 25_000_001)]


@pytest.fixture
def publication_claim(db):
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
    execution = Execution.objects.create(
        workspace=workspace,
        profile=profile,
        idempotency_key="publication-turn",
        source_kind="conversation_message",
        cloud_binding_id=uuid4(),
        cloud_message_id=uuid4(),
        input_payload={"message": "publish this"},
    )
    issued = issue_runtime_credential(workspace.id, "runtime-publication-secret")
    context = authenticate_runtime_token(issued.raw_token)
    claim = claim_next_execution(context, uuid4(), 2)
    assert claim is not None
    return context, claim, profile, execution, issued.raw_token


@pytest.mark.django_db
@override_settings(ALLIES_RUNTIME_FILE_PUBLICATION_ENABLED=True)
def test_intent_precedes_and_fences_the_frozen_manifest(publication_claim):
    context, claim, profile, execution, _token = publication_claim
    first = create_publication_intent(
        context,
        claim.attempt_id,
        claim.lease_token,
        "call-1",
        [{"name": "result.csv", "size": 12}],
    )
    replay = create_publication_intent(
        context,
        claim.attempt_id,
        claim.lease_token,
        "call-1",
        [{"name": "result.csv", "size": 12}],
    )

    assert replay == first
    intent = PublicationIntent.objects.get(pk=first.publication_id)
    assert intent.execution_id == execution.id
    assert intent.profile_id == profile.id
    assert intent.state == PublicationIntentState.PREPARING
    assert intent.manifest_digest is None

    frozen = acknowledge_frozen_publication(
        context,
        profile.id,
        first.publication_id,
        [
            {
                "source_version_id": str(uuid4()),
                "name": "result.csv",
                "size": 12,
                "sha256": "a" * 64,
            }
        ],
    )
    assert frozen.state == PublicationIntentState.FROZEN
    assert frozen.manifest_digest

    with pytest.raises(RuntimeIdempotencyConflictError, match="manifest changed"):
        acknowledge_frozen_publication(
            context,
            profile.id,
            first.publication_id,
            [
                {
                    "source_version_id": str(uuid4()),
                    "name": "result.csv",
                    "size": 12,
                    "sha256": "b" * 64,
                }
            ],
        )


@pytest.mark.django_db
@override_settings(ALLIES_RUNTIME_FILE_PUBLICATION_ENABLED=True)
def test_intent_api_replays_the_same_tool_identity(publication_claim, client):
    _context, claim, profile, _execution, token = publication_claim
    headers = {
        "HTTP_AUTHORIZATION": f"Bearer {token}",
        "HTTP_X_FOUNDRY_LEASE_TOKEN": claim.lease_token,
    }
    path = f"/api/v1/runtime/attempts/{claim.attempt_id}/file-publication-intents"
    body = {"tool_call_id": "call-1", "files": [{"name": "result.csv", "size": 12}]}

    first = client.post(path, body, content_type="application/json", **headers)
    replay = client.post(path, body, content_type="application/json", **headers)

    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    publication_id = first.json()["publication_id"]
    frozen = client.post(
        f"/api/v1/runtime/profiles/{profile.id}/file-publication-intents/{publication_id}/frozen",
        {
            "files": [
                {
                    "source_version_id": str(uuid4()),
                    "name": "result.csv",
                    "size": 12,
                    "sha256": "a" * 64,
                }
            ]
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert frozen.status_code == 200
    assert frozen.json()["state"] == "frozen"


@pytest.mark.django_db
@override_settings(
    ALLIES_RUNTIME_FILE_PUBLICATION_ENABLED=True,
    ALLIES_CLOUD_URL="https://cloud.example.test",
    ALLIES_CLOUD_EVENT_SERVICE_TOKEN="foundry-event-token",
)
def test_due_publication_wake_uses_existing_workspace_operation_without_an_execution(
    publication_claim, monkeypatch
):
    context, claim, _profile, execution, _token = publication_claim
    intent = create_publication_intent(
        context,
        claim.attempt_id,
        claim.lease_token,
        "call-wake",
        [{"name": "result.csv", "size": 12}],
    )
    PublicationIntent.objects.filter(pk=intent.publication_id).update(
        state=PublicationIntentState.FROZEN,
        manifest_digest="a" * 64,
        next_due_at=timezone.now(),
    )
    monkeypatch.setattr(
        publication_service,
        "cloud_publication_request",
        lambda method, path: (
            200,
            {
                "binding_ids": [str(execution.cloud_binding_id)],
                "next_cursor": "next-page",
            },
        ),
    )

    page = wake_due_publications(limit=20)

    assert page.woken == 1
    assert page.next_cursor == "next-page"
    assert Execution.objects.count() == 1


@pytest.mark.django_db
@override_settings(ALLIES_RUNTIME_FILE_PUBLICATION_ENABLED=True)
def test_newer_cloud_retry_reopens_an_exhausted_frozen_manifest(
    publication_claim, monkeypatch
):
    context, claim, profile, _execution, _token = publication_claim
    frozen_files = [
        {
            "source_version_id": str(uuid4()),
            "name": "result.csv",
            "size": 12,
            "sha256": "a" * 64,
        }
    ]
    receipt = create_publication_intent(
        context,
        claim.attempt_id,
        claim.lease_token,
        "call-retry",
        [{"name": "result.csv", "size": 12}],
    )
    acknowledge_frozen_publication(
        context, profile.id, receipt.publication_id, frozen_files
    )
    intent = PublicationIntent.objects.get(pk=receipt.publication_id)
    digest = intent.manifest_digest
    intent.state = PublicationIntentState.FAILED
    intent.attempts = PublicationIntent.MAX_ATTEMPTS
    intent.cloud_revision = 1
    intent.safe_error_code = "publication_unavailable"
    intent.save()
    claimed_revision = 2
    uploaded = []

    def cloud_request(method, path, **_kwargs):
        if path == "/file-publication-retries/claim":
            return 200, {
                "items": [
                    {
                        "publication_id": str(intent.id),
                        "revision": claimed_revision,
                    }
                ]
            }
        if method == "PUT":
            uploaded.append(path)
            return 202, {}
        if path.endswith("/retry-result"):
            return 200, {}
        raise AssertionError((method, path))

    monkeypatch.setattr(publication_service, "cloud_publication_request", cloud_request)

    assert claim_publication_retries(context, profile.id, 20)[0]["revision"] == 2
    upload_publication_file(
        context,
        profile.id,
        intent.id,
        uuid4(),
        1,
        b"frozen bytes",
        2,
        uuid4(),
    )
    record_publication_retry(
        context, profile.id, intent.id, 2, uuid4(), "failed", "source_unavailable"
    )

    intent.refresh_from_db()
    assert uploaded and intent.state == PublicationIntentState.FAILED
    assert intent.attempts == PublicationIntent.MAX_ATTEMPTS
    assert intent.manifest_digest == digest
    assert intent.cloud_revision == 2
    assert intent.cloud_retry_revision == 2

    claimed_revision = 1
    assert claim_publication_retries(context, profile.id, 20) == ()

    claimed_revision = 2
    assert claim_publication_retries(context, profile.id, 20)[0]["revision"] == 2
    intent.refresh_from_db()
    assert intent.state == PublicationIntentState.REGISTERED
    assert intent.attempts == PublicationIntent.MAX_ATTEMPTS
    assert intent.manifest_digest == digest
    upload_publication_file(
        context,
        profile.id,
        intent.id,
        uuid4(),
        2,
        b"frozen bytes",
        2,
        uuid4(),
    )
    assert len(uploaded) == 2


@pytest.mark.django_db
@override_settings(
    ALLIES_RUNTIME_FILE_PUBLICATION_ENABLED=True,
    ALLIES_CLOUD_URL="https://cloud.example.test",
    ALLIES_CLOUD_EVENT_SERVICE_TOKEN="foundry-event-token",
)
def test_wake_excludes_exhausted_local_intents_and_preserves_unscheduled_cursor(
    publication_claim, monkeypatch
):
    _context, claim, profile, execution, _token = publication_claim

    def make_workspace(key):
        workspace = Workspace.objects.create(
            tenant_ref=str(uuid4()),
            fly_app_ref=f"app-{key}",
            volume_ref=f"volume-{key}",
            machine_ref=f"machine-{key}",
            machine_generation=1,
            provisioning_phase=WorkspaceProvisioningPhase.IDLE,
            ready_generation=1,
            ready_start_epoch=0,
            ready_boot_id=uuid4(),
            runtime_last_seen_at=timezone.now(),
        )
        runtime_profile = RuntimeProfile.objects.create(
            workspace=workspace,
            ally_ref=f"ally-{key}",
            hermes_profile_key=f"ally-{key}",
            lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
            materialized_generation=1,
            seed_payload={"model": "gpt-5.6-luna"},
        )
        return workspace, runtime_profile

    def add_intent(
        workspace,
        runtime_profile,
        binding,
        key,
        *,
        attempts=0,
        state=PublicationIntentState.FAILED,
    ):
        item_execution = Execution.objects.create(
            workspace=workspace,
            profile=runtime_profile,
            idempotency_key=f"publication-{key}",
            source_kind="conversation_message",
            cloud_binding_id=binding,
            cloud_message_id=uuid4(),
            input_payload={"message": "publish"},
        )
        item_attempt = Attempt.objects.create(
            execution=item_execution, number=1, machine_generation=1
        )
        return PublicationIntent.objects.create(
            workspace=workspace,
            profile=runtime_profile,
            execution=item_execution,
            source_attempt=item_attempt,
            cloud_binding_id=binding,
            cloud_message_id=item_execution.cloud_message_id,
            tool_call_digest=f"{key:064x}",
            request_digest=f"{key + 10:064x}",
            manifest_digest="a" * 64,
            state=state,
            attempts=attempts,
            next_due_at=timezone.now(),
        )

    exhausted = PublicationIntent.objects.create(
        workspace=execution.workspace,
        profile=profile,
        execution=execution,
        source_attempt_id=claim.attempt_id,
        cloud_binding_id=execution.cloud_binding_id,
        cloud_message_id=execution.cloud_message_id,
        tool_call_digest="b" * 64,
        request_digest="c" * 64,
        manifest_digest="a" * 64,
        state=PublicationIntentState.FAILED,
        attempts=PublicationIntent.MAX_ATTEMPTS,
        next_due_at=timezone.now(),
    )
    first_workspace, first_profile = make_workspace(1)
    second_workspace, second_profile = make_workspace(2)
    first_binding, duplicate_binding, second_binding = uuid4(), uuid4(), uuid4()
    add_intent(
        first_workspace,
        first_profile,
        first_binding,
        1,
        state=PublicationIntentState.REGISTERED,
    )
    add_intent(
        first_workspace,
        first_profile,
        duplicate_binding,
        2,
        state=PublicationIntentState.REGISTERED,
    )
    second = add_intent(second_workspace, second_profile, second_binding, 3)
    second.next_due_at = timezone.now() - timedelta(seconds=1)
    second.save(update_fields=["next_due_at"])
    captured = []

    def cloud_request(_method, path):
        binding_ids = [str(first_binding)]
        if "limit=2" in path:
            binding_ids.append(str(duplicate_binding))
        return 200, {"binding_ids": binding_ids, "next_cursor": "advanced"}

    monkeypatch.setattr(publication_service, "cloud_publication_request", cloud_request)
    monkeypatch.setattr(
        publication_service,
        "_wake_publication_workspaces",
        lambda workspace_ids: (
            captured.append(tuple(workspace_ids)) or len(workspace_ids)
        ),
    )

    page = wake_due_publications(limit=2, cursor="keep")

    assert exhausted.attempts == PublicationIntent.MAX_ATTEMPTS
    assert captured == [(second_workspace.id, first_workspace.id)]
    assert page.woken == 2 and page.next_cursor == "advanced"

    page = wake_due_publications(limit=1, cursor="keep")

    assert captured[-1] == (second_workspace.id,)
    assert page.next_cursor == "keep"


class _CloudResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self, _limit):
        return self._body

    def close(self):
        return None


@pytest.mark.django_db
@override_settings(
    ALLIES_RUNTIME_FILE_PUBLICATION_ENABLED=True,
    ALLIES_CLOUD_URL="https://cloud.example.test",
    ALLIES_CLOUD_EVENT_SERVICE_TOKEN="foundry-event-token",
)
def test_frozen_intent_replays_the_exact_cloud_reservation(
    publication_claim, monkeypatch
):
    context, claim, profile, _execution, _token = publication_claim
    requests = []

    class Opener:
        def open(self, request, timeout):
            requests.append((request, timeout))
            if len(requests) == 1:
                return _CloudResponse(
                    503,
                    b'{"status":"error","data":{"code":"publication_unavailable"}}',
                )
            return _CloudResponse(
                202,
                b'{"status":"success","message":"accepted","data":'
                b'{"publication_id":"00000000-0000-0000-0000-000000000000",'
                b'"state":"uploading","revision":1,"files":[]}}',
            )

    monkeypatch.setattr(publication_service, "build_opener", lambda _handler: Opener())
    intent = create_publication_intent(
        context,
        claim.attempt_id,
        claim.lease_token,
        "tool-call-1",
        [{"name": "result.csv", "size": 12}],
    )
    frozen_files = [
        {
            "source_version_id": str(uuid4()),
            "name": "result.csv",
            "size": 12,
            "sha256": "a" * 64,
        }
    ]

    acknowledge_frozen_publication(
        context, profile.id, intent.publication_id, frozen_files
    )
    assert len(requests) == 2
    with pytest.raises(RuntimeLeaseConflictError, match="not due"):
        register_publication(
            context,
            claim.attempt_id,
            claim.lease_token,
            intent.publication_id,
            frozen_files,
        )
    assert len(requests) == 2
    PublicationIntent.objects.filter(pk=intent.publication_id).update(
        next_due_at=timezone.now()
    )
    acknowledge_frozen_publication(
        context, profile.id, intent.publication_id, frozen_files
    )

    assert len(requests) == 3
    request, timeout = requests[0]
    assert timeout == 120
    assert request.full_url == (
        "https://cloud.example.test/api/v1/internal/v1/file-publications"
    )
    assert request.get_header("Authorization") == "Bearer foundry-event-token"
    assert request.get_header("Idempotency-key") == str(intent.publication_id)
    assert request.data == (
        b'{"binding_id":"'
        + str(
            PublicationIntent.objects.get(pk=intent.publication_id).cloud_binding_id
        ).encode()
        + b'","files":[{"name":"result.csv","sha256":"'
        + b"a" * 64
        + b'","size":12,"source_version_id":"'
        + frozen_files[0]["source_version_id"].encode()
        + b'"}],"message_id":"'
        + str(
            PublicationIntent.objects.get(pk=intent.publication_id).cloud_message_id
        ).encode()
        + b'","publication_id":"'
        + str(intent.publication_id).encode()
        + b'"}'
    )
    failure_request, failure_timeout = requests[1]
    assert failure_timeout == 120
    assert failure_request.full_url == (
        "https://cloud.example.test/api/v1/internal/v1/file-publication-status"
    )
    assert failure_request.get_header("Authorization") == "Bearer foundry-event-token"
    assert failure_request.data == (
        b'{"binding_id":"'
        + str(
            PublicationIntent.objects.get(pk=intent.publication_id).cloud_binding_id
        ).encode()
        + b'","error_code":"publication_unavailable","message_id":"'
        + str(
            PublicationIntent.objects.get(pk=intent.publication_id).cloud_message_id
        ).encode()
        + b'","publication_id":"'
        + str(intent.publication_id).encode()
        + b'","state":"failed"}'
    )
    record = PublicationIntent.objects.get(pk=intent.publication_id)
    assert record.state == PublicationIntentState.REGISTERED
    assert record.cloud_revision == 1


@pytest.mark.django_db
@override_settings(ALLIES_RUNTIME_FILE_PUBLICATION_ENABLED=True)
@pytest.mark.parametrize("cloud_state", ["ready", "failed"])
def test_registered_publication_wakes_until_cloud_terminal(
    publication_claim, monkeypatch, cloud_state
):
    context, claim, profile, _execution, _token = publication_claim
    receipt = create_publication_intent(
        context,
        claim.attempt_id,
        claim.lease_token,
        "call-registered-recovery",
        [{"name": "result.csv", "size": 12}],
    )
    PublicationIntent.objects.filter(pk=receipt.publication_id).update(
        state=PublicationIntentState.REGISTERED,
        manifest_digest="a" * 64,
        cloud_revision=1,
        attempts=5,
    )

    def cloud(method, path):
        if "due-bindings" in path:
            return 200, {"binding_ids": []}
        return 200, {"state": cloud_state, "revision": 1}

    monkeypatch.setattr(publication_service, "cloud_publication_request", cloud)
    assert wake_due_publications(limit=20).woken == 1
    assert wake_due_publications(limit=20).woken == 0
    publication_service.get_publication(context, profile.id, receipt.publication_id)
    assert PublicationIntent.objects.get(pk=receipt.publication_id).state == cloud_state
    PublicationIntent.objects.filter(pk=receipt.publication_id).update(
        next_due_at=timezone.now()
    )
    assert wake_due_publications(limit=20).woken == 0
    assert Execution.objects.count() == 1
