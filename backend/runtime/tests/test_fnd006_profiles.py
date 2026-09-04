from __future__ import annotations

from datetime import timedelta
from io import StringIO
from uuid import UUID, uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import Client
from django.utils import timezone

import runtime.services.retry as retry_services
from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeIdempotencyConflictError,
    RuntimeNotReadyError,
    RuntimeRepairRequiredError,
    RuntimeValidationError,
)
from runtime.management.commands import expire_profile_cleanups as cleanup_command
from runtime.models import (
    Attempt,
    Execution,
    ExecutionStatus,
    Lease,
    LeaseState,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.profile_keys import derive_hermes_profile_key
from runtime.services.leases import acknowledge_stopped, create_lease
from runtime.services.profiles import (
    ProfileSeed,
    accept_cleanup_receipt,
    accept_materialization_receipt,
    ensure_runtime_profile,
    expire_profile_cleanups,
    list_profile_reconciliation,
    request_profile_cleanup,
)
from runtime.services.runtime_auth import (
    authenticate_runtime_token,
    issue_runtime_credential,
)
from runtime.services.validation import digest_payload


@pytest.fixture
def ready_workspace(db):
    return Workspace.objects.create(
        tenant_ref="fnd006-tenant",
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


def test_profile_fingerprint_contract_includes_memory_policy(ready_workspace):
    profile_id = UUID("00000000-0000-0000-0000-000000000001")
    receipt = ensure_runtime_profile(
        ready_workspace.id,
        profile_id,
        "ally-a",
        ProfileSeed(
            personality="p",
            provider="openai",
            model="gpt-test",
            first_chat_instruction="i",
            credential_refs={"PROVIDER_API": "vault://p"},
        ),
    )

    assert receipt.seed_fingerprint == (
        "cd995ea7543b218b8380d61d6b051548da09af3a13a9bfcc529b33fca9a95db9"
    )
    desired = list_profile_reconciliation(_context(ready_workspace)[0])[0]
    assert desired.seed_payload["memory_provider"] == "allies_mnemosyne"
    assert desired.seed_payload["memory_policy_version"] == "allies-mnemosyne-v1"


@pytest.fixture
def seed():
    return ProfileSeed(
        personality="Exact line one.\nExact line two.",
        provider="openai",
        model="gpt-test",
        first_chat_instruction="Start by asking one useful question.",
        credential_refs={"provider_api": "vault://providers/ally-a"},
    )


def _context(workspace):
    issued = issue_runtime_credential(workspace.id, "runtime-secret")
    return authenticate_runtime_token(issued.raw_token), issued


def test_profile_key_is_stable_and_hermes_valid():
    profile_id = uuid4()
    key = derive_hermes_profile_key(profile_id)
    assert key == f"ally-v1-{profile_id.hex}"
    assert derive_hermes_profile_key(str(profile_id)) == key
    assert len(key) == 40


def test_profile_seed_creation_is_exactly_idempotent_and_conflicts_on_change(
    ready_workspace, seed
):
    profile_id = uuid4()
    first = ensure_runtime_profile(ready_workspace.id, profile_id, "ally-a", seed)
    replay = ensure_runtime_profile(ready_workspace.id, profile_id, "ally-a", seed)
    assert replay == first
    assert RuntimeProfile.objects.filter(workspace=ready_workspace).count() == 1
    changed = ProfileSeed(
        personality=seed.personality + " changed",
        provider=seed.provider,
        model=seed.model,
        first_chat_instruction=seed.first_chat_instruction,
        credential_refs=seed.credential_refs,
    )
    with pytest.raises(RuntimeConflictError):
        ensure_runtime_profile(ready_workspace.id, profile_id, "ally-a", changed)


def test_profile_seed_rejects_mixed_reference_keys_and_normalization_collisions(
    ready_workspace,
):
    with pytest.raises(RuntimeValidationError):
        ensure_runtime_profile(
            ready_workspace.id,
            uuid4(),
            "ally-a",
            {
                "personality": "personality",
                "provider": "openai",
                "model": "gpt-test",
                "first_chat_instruction": "instruction",
                "credential_refs": {
                    1: "vault://providers/one",
                    "api": "vault://providers/two",
                },
            },
        )
    with pytest.raises(RuntimeValidationError):
        ensure_runtime_profile(
            ready_workspace.id,
            uuid4(),
            "ally-b",
            {
                "personality": "personality",
                "provider": "openai",
                "model": "gpt-test",
                "first_chat_instruction": "instruction",
                "credential_refs": {
                    "provider-api": "vault://providers/one",
                    "PROVIDER_API": "vault://providers/two",
                },
            },
        )


def test_reconciliation_receipt_is_stable_and_exposes_no_secret(ready_workspace, seed):
    profile_id = uuid4()
    created = ensure_runtime_profile(ready_workspace.id, profile_id, "ally-a", seed)
    context, _issued = _context(ready_workspace)
    desired = list_profile_reconciliation(context)
    assert desired[0].seed_payload["personality"] == seed.personality
    assert "runtime-secret" not in str(desired[0])
    operation_id = uuid4()
    first = accept_materialization_receipt(
        context,
        profile_id,
        operation_id,
        created.lifecycle_epoch,
        1,
        created.seed_fingerprint,
        "created",
    )
    replay = accept_materialization_receipt(
        context,
        profile_id,
        operation_id,
        created.lifecycle_epoch,
        1,
        created.seed_fingerprint,
        "created",
    )
    assert replay == first
    profile = RuntimeProfile.objects.get(pk=profile_id)
    assert profile.lifecycle_state == RuntimeProfileLifecycleState.ACTIVE
    assert profile.materialized_generation == 1

    with pytest.raises(RuntimeValidationError):
        accept_materialization_receipt(
            context,
            profile_id,
            uuid4(),
            created.lifecycle_epoch,
            1,
            created.seed_fingerprint,
            "repair_required",
        )


def test_pending_profile_blocks_claim_reconciliation_until_receipt(
    ready_workspace, seed
):
    profile_id = uuid4()
    created = ensure_runtime_profile(ready_workspace.id, profile_id, "ally-a", seed)
    Execution.objects.create(
        workspace=ready_workspace,
        profile_id=profile_id,
        idempotency_key="turn-1",
        input_payload={"message": "hello"},
    )
    context, _issued = _context(ready_workspace)
    from runtime.services.claims import claim_next_execution

    with pytest.raises(RuntimeNotReadyError):
        claim_next_execution(context, uuid4(), 1)
    accept_materialization_receipt(
        context,
        profile_id,
        uuid4(),
        created.lifecycle_epoch,
        1,
        created.seed_fingerprint,
        "created",
    )
    assert claim_next_execution(context, uuid4(), 1) is not None


def test_cleanup_fences_active_work_and_late_provision_is_rejected(
    ready_workspace, seed
):
    profile_id = uuid4()
    created = ensure_runtime_profile(ready_workspace.id, profile_id, "ally-a", seed)
    context, _issued = _context(ready_workspace)
    accept_materialization_receipt(
        context,
        profile_id,
        uuid4(),
        created.lifecycle_epoch,
        1,
        created.seed_fingerprint,
        "created",
    )
    profile = RuntimeProfile.objects.get(pk=profile_id)
    execution = Execution.objects.create(
        workspace=ready_workspace,
        profile=profile,
        idempotency_key="turn-1",
        input_payload={"message": "hello"},
        status=ExecutionStatus.RUNNING,
    )
    attempt = Attempt.objects.create(
        execution=execution,
        number=1,
        machine_generation=1,
    )
    lease = create_lease(
        attempt.id,
        "profile-lease-secret",
        timezone.now() + timedelta(minutes=1),
        1,
    )
    cleanup_operation = uuid4()
    pending = request_profile_cleanup(
        ready_workspace.id,
        profile_id,
        cleanup_operation,
        digest_payload({"cloud_binding": "conversation-a"}),
    )
    profile.refresh_from_db()
    assert pending.lifecycle_state == RuntimeProfileLifecycleState.CLEANUP_PENDING
    assert Lease.objects.get(pk=lease.id).state == LeaseState.STOPPING
    stopped = acknowledge_stopped(
        context, attempt.id, "profile-lease-secret", "cleanup"
    )
    assert stopped.requeued is False
    final = accept_cleanup_receipt(
        context,
        profile_id,
        cleanup_operation,
        profile.lifecycle_epoch,
        profile.cleanup_request_digest,
        result_code="deprovisioned",
        deleted=True,
        active_lease_count=0,
    )
    assert final.deleted is True
    assert final.lifecycle_state == RuntimeProfileLifecycleState.DEPROVISIONED
    with pytest.raises(RuntimeRepairRequiredError):
        accept_materialization_receipt(
            context,
            profile_id,
            uuid4(),
            profile.lifecycle_epoch,
            1,
            created.seed_fingerprint,
            "created",
        )


def test_cleanup_replay_is_stable_and_conflicting_operation_is_rejected(
    ready_workspace, seed
):
    profile_id = uuid4()
    ensure_runtime_profile(ready_workspace.id, profile_id, "ally-a", seed)
    operation_id = uuid4()
    binding_digest = digest_payload({"cloud_binding": "conversation-a"})
    first = request_profile_cleanup(
        ready_workspace.id, profile_id, operation_id, binding_digest
    )
    replay = request_profile_cleanup(
        ready_workspace.id, profile_id, operation_id, binding_digest
    )
    assert replay == first
    with pytest.raises(RuntimeIdempotencyConflictError):
        request_profile_cleanup(ready_workspace.id, profile_id, uuid4(), binding_digest)


def test_expired_cleanup_is_server_fenced_without_runtime_receipt(
    ready_workspace, seed
):
    profile_id = uuid4()
    created = ensure_runtime_profile(ready_workspace.id, profile_id, "ally-a", seed)
    context, _issued = _context(ready_workspace)
    accept_materialization_receipt(
        context,
        profile_id,
        uuid4(),
        created.lifecycle_epoch,
        1,
        created.seed_fingerprint,
        "created",
    )
    profile = RuntimeProfile.objects.get(pk=profile_id)
    execution = Execution.objects.create(
        workspace=ready_workspace,
        profile=profile,
        idempotency_key="turn-expired-cleanup",
        input_payload={"message": "hello"},
        status=ExecutionStatus.RUNNING,
    )
    attempt = Attempt.objects.create(
        execution=execution,
        number=1,
        machine_generation=1,
    )
    lease = create_lease(
        attempt.id,
        "expired-cleanup-lease",
        timezone.now() + timedelta(minutes=1),
        1,
    )
    operation_id = uuid4()
    request_profile_cleanup(
        ready_workspace.id,
        profile_id,
        operation_id,
        digest_payload({"cloud_binding": "conversation-expired"}),
        expires_at=timezone.now() + timedelta(minutes=1),
    )
    expired_at = timezone.now() - timedelta(seconds=1)
    RuntimeProfile.objects.filter(pk=profile_id).update(cleanup_expires_at=expired_at)

    receipts = expire_profile_cleanups(now=timezone.now())

    profile.refresh_from_db()
    lease.refresh_from_db()
    attempt.refresh_from_db()
    execution.refresh_from_db()
    assert len(receipts) == 1
    assert receipts[0].deleted is False
    assert receipts[0].result_code == "repair_required"
    assert profile.lifecycle_state == RuntimeProfileLifecycleState.REPAIR_REQUIRED
    assert lease.state == LeaseState.FENCED
    assert attempt.status == "unknown"
    assert execution.status == ExecutionStatus.FAILED
    assert expire_profile_cleanups(now=timezone.now()) == ()


def test_expired_cleanup_retries_a_transient_sqlite_lock(
    ready_workspace, seed, monkeypatch
):
    profile_id = uuid4()
    ensure_runtime_profile(ready_workspace.id, profile_id, "ally-a", seed)
    request_profile_cleanup(
        ready_workspace.id,
        profile_id,
        uuid4(),
        digest_payload({"cloud_binding": "conversation-locked"}),
        expires_at=timezone.now() + timedelta(minutes=1),
    )
    expired_at = timezone.now() - timedelta(seconds=1)
    RuntimeProfile.objects.filter(pk=profile_id).update(cleanup_expires_at=expired_at)

    original_save = RuntimeProfile.save
    save_attempts = 0

    def save_with_transient_lock(self, *args, **kwargs):
        nonlocal save_attempts
        save_attempts += 1
        if save_attempts == 1:
            raise OperationalError("database is locked")
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(RuntimeProfile, "save", save_with_transient_lock)
    monkeypatch.setattr(retry_services, "sleep", lambda _delay: None)

    receipts = expire_profile_cleanups(now=timezone.now())

    assert len(receipts) == 1
    assert save_attempts == 2
    assert RuntimeProfile.objects.get(pk=profile_id).lifecycle_state == (
        RuntimeProfileLifecycleState.REPAIR_REQUIRED
    )


def test_expire_profile_cleanups_command_is_one_shot_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cleanup_command,
        "expire_profile_cleanups",
        lambda: calls.append("run") or (object(),),
    )
    output = StringIO()

    call_command("expire_profile_cleanups", stdout=output)

    assert calls == ["run"]
    assert output.getvalue() == "Fenced 1 expired profile cleanup(s).\n"


def test_expire_profile_cleanups_command_watch_mode_is_bounded(monkeypatch):
    calls = []
    sleeps = []
    monkeypatch.setattr(
        cleanup_command,
        "expire_profile_cleanups",
        lambda: calls.append("run") or (),
    )
    monkeypatch.setattr(cleanup_command, "sleep", sleeps.append)

    call_command(
        "expire_profile_cleanups",
        "--watch",
        "--interval",
        "7",
        "--max-runs",
        "3",
        stdout=StringIO(),
    )

    assert calls == ["run", "run", "run"]
    assert sleeps == [7, 7]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("--watch",), "--watch requires --max-runs"),
        (("--max-runs", "2"), "--interval and --max-runs require --watch"),
        (("--watch", "--max-runs", "0"), "--max-runs must be between 1 and 1440"),
        (
            ("--watch", "--interval", "0", "--max-runs", "1"),
            "--interval must be between 1 and 3600 seconds",
        ),
    ],
)
def test_expire_profile_cleanups_command_validates_watch_options(args, message):
    with pytest.raises(CommandError, match=message):
        call_command("expire_profile_cleanups", *args, stdout=StringIO())


def test_profile_api_reconciliation_and_receipt_are_authenticated(
    ready_workspace, seed
):
    profile_id = uuid4()
    created = ensure_runtime_profile(ready_workspace.id, profile_id, "ally-a", seed)
    context, issued = _context(ready_workspace)
    client = Client()
    response = client.get(
        "/api/v1/runtime/profiles/reconciliation",
        headers={"Authorization": f"Bearer {issued.raw_token}"},
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["version"] == 1
    assert body["profiles"][0]["profile_id"] == str(profile_id)
    receipt = client.post(
        f"/api/v1/runtime/profiles/{profile_id}/materialization-receipt",
        data={
            "profile_id": str(profile_id),
            "operation_id": str(uuid4()),
            "lifecycle_epoch": created.lifecycle_epoch,
            "materialized_generation": 1,
            "seed_fingerprint": created.seed_fingerprint,
            "result_code": "created",
        },
        content_type="application/json",
        headers={"Authorization": f"Bearer {issued.raw_token}"},
    )
    assert receipt.status_code == 200, receipt.content
    assert receipt.json()["lifecycle_state"] == "active"
    assert context.workspace_id == ready_workspace.id


def test_legacy_profile_reconciliation_is_repair_only(ready_workspace):
    profile = RuntimeProfile.objects.create(
        workspace=ready_workspace,
        ally_ref="legacy",
        hermes_profile_key="legacy-key",
        hermes_profile_key_version=0,
    )
    context, _issued = _context(ready_workspace)
    desired = list_profile_reconciliation(context)
    assert desired[0].lifecycle_state == RuntimeProfileLifecycleState.REPAIR_REQUIRED
    assert desired[0].materialization_result_code == "legacy_profile_key"
    assert desired[0].profile_id == profile.id
