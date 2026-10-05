from __future__ import annotations

import asyncio
import json
import time
from uuid import uuid4

import pytest

from allies_runtime.foundry import (
    ProfileDesiredState,
    RuntimeReconciliationSnapshot,
)
from allies_runtime.profile_store import (
    ProfileCleanupStatus,
    ProfileProvisionStatus,
    ProfileSeed,
    ProfileStore,
    derive_profile_key,
)
from allies_runtime.quiescence import (
    ProfileResourceRegistry,
    QuiescenceError,
    QuiescenceRequest,
    parse_quiescence_proof,
)
from allies_runtime.reconciliation import ProfileReconciler


def _request() -> QuiescenceRequest:
    return QuiescenceRequest(
        operation_id=str(uuid4()),
        attempt_id=str(uuid4()),
        lifecycle_epoch=2,
        request_digest="a" * 64,
        machine_generation=3,
        runtime_start_epoch=4,
        hermes_instance_id=str(uuid4()),
    )


def _proof_payload(request: QuiescenceRequest) -> dict[str, object]:
    return {
        **request.to_dict(),
        "profile_key": "ally-v1-test",
        "state": "quiesced",
        "safe_error_code": "",
        "active_runs": 0,
        "active_profile_io": 0,
        "open_profile_stores": 0,
        "owned_children": 0,
    }


def test_quiescence_proof_requires_explicit_version_counters_and_shape():
    request = _request()
    payload = _proof_payload(request)
    assert parse_quiescence_proof(
        payload, expected=request, profile_key="ally-v1-test"
    ).complete

    for mutation in (
        lambda value: value.pop("version"),
        lambda value: value.pop("active_runs"),
        lambda value: value.update(unexpected=True),
    ):
        malformed = dict(payload)
        mutation(malformed)
        with pytest.raises(QuiescenceError):
            parse_quiescence_proof(
                malformed, expected=request, profile_key="ally-v1-test"
            )

    with pytest.raises(ValueError):
        QuiescenceRequest(
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            lifecycle_epoch=request.lifecycle_epoch,
            request_digest=request.request_digest,
            machine_generation=0,
            runtime_start_epoch=request.runtime_start_epoch,
            hermes_instance_id=request.hermes_instance_id,
        )


@pytest.mark.asyncio
async def test_registry_waits_for_real_worker_completion_before_release():
    registry = ProfileResourceRegistry()
    released = asyncio.Event()
    interrupted = asyncio.Event()

    async def worker():
        await released.wait()

    task = asyncio.create_task(worker())

    class Agent:
        def hard_interrupt(self, _reason):
            interrupted.set()
            released.set()

    token = registry.register(
        "ally-v1-test",
        "claim-1",
        future=task,
        agent=Agent(),
    )

    def close():
        registry.release(token)
        return True

    registry.release(token)
    token = registry.register(
        "ally-v1-test",
        "claim-1",
        future=task,
        agent=Agent(),
        close=close,
    )
    state, failures = await registry.quiesce("ally-v1-test", timeout_seconds=1)

    assert interrupted.is_set()
    assert task.done()
    assert state == "quiesced"
    assert failures == ()


def test_profile_store_deletion_fence_and_terminal_marker_are_content_free(tmp_path):
    profile_id = str(uuid4())
    profile_key = derive_profile_key(profile_id)
    store = ProfileStore(
        tmp_path,
        api_key_factory=lambda: "profile-local-key-0123456789",
        credential_resolver=lambda _reference: "provider-secret",
    )
    operation_id = str(uuid4())
    attempt_id = str(uuid4())
    digest = "b" * 64
    receipt = store.fence_deletion(
        profile_key,
        operation_id,
        2,
        time.time() + 30,
        attempt_id=attempt_id,
        request_digest=digest,
    )
    assert receipt.status is ProfileCleanupStatus.FENCED
    pending = json.loads(store._tombstone_path(profile_key).read_text())
    assert pending["status"] == "CLEANUP_PENDING"
    assert pending["attempt_id"] == attempt_id
    assert pending["request_digest"] == digest
    late_provision = store.materialize(
        ProfileSeed(
            foundry_profile_id=profile_id,
            ally_name="Aster",
            personality="Keep this text.",
            provider="openai",
            model="gpt-test",
            first_chat_instruction="Start with one useful question.",
            hermes_profile_key=profile_key,
        )
    )
    assert late_provision.status is ProfileProvisionStatus.FENCED

    deleted = store.cleanup(
        profile_key,
        operation_id,
        2,
        time.time() + 30,
        attempt_id=attempt_id,
        request_digest=digest,
        deletion=True,
    )
    assert deleted.status is ProfileCleanupStatus.DEPROVISIONED
    terminal = json.loads(store._tombstone_path(profile_key).read_text())
    assert set(terminal) == {
        "schema",
        "schema_version",
        "profile_key",
        "status",
        "deleted",
    }


@pytest.mark.asyncio
async def test_deletion_pending_profile_does_not_block_sibling_reconciliation():
    target_id = str(uuid4())
    target_key = derive_profile_key(target_id)
    sibling_id = str(uuid4())
    sibling_key = derive_profile_key(sibling_id)
    target = ProfileDesiredState(
        machine_generation=3,
        profile_id=target_id,
        ally_ref="target",
        hermes_profile_key=target_key,
        hermes_profile_key_version=1,
        lifecycle_state="cleanup_pending",
        lifecycle_epoch=2,
        seed_version=1,
        seed_fingerprint="a" * 64,
        materialized_generation=3,
        seed={},
        materialization_operation_id=None,
        materialization_request_digest="",
        materialization_receipt_id=None,
        materialization_result_code="",
        cleanup_operation_id=str(uuid4()),
        cleanup_context_digest="c" * 64,
        cleanup_request_digest="d" * 64,
        cleanup_receipt_id=None,
        cleanup_result_code="pending",
        cleanup_expires_at=None,
        cleanup_attempt_id=str(uuid4()),
        cleanup_requires_quiescence=True,
    )
    sibling = ProfileDesiredState(
        machine_generation=3,
        profile_id=sibling_id,
        ally_ref="sibling",
        hermes_profile_key=sibling_key,
        hermes_profile_key_version=1,
        lifecycle_state="active",
        lifecycle_epoch=0,
        seed_version=1,
        seed_fingerprint="e" * 64,
        materialized_generation=3,
        seed={},
        materialization_operation_id=str(uuid4()),
        materialization_request_digest="f" * 64,
        materialization_receipt_id="pr-" + "1" * 32,
        materialization_result_code="existing",
        cleanup_operation_id=None,
        cleanup_context_digest="",
        cleanup_request_digest="",
        cleanup_receipt_id=None,
        cleanup_result_code="",
        cleanup_expires_at=None,
    )

    class Foundry:
        last_reconciliation_snapshot = RuntimeReconciliationSnapshot(
            machine_generation=3,
            runtime_start_epoch=4,
            profiles=(target, sibling),
        )

        async def reconcile_profiles(self):
            return (target, sibling)

    report = await ProfileReconciler(Foundry(), object()).reconcile()

    assert report.blocked_profile_ids == (target_id,)
    assert report.materialized == ()
    assert report.cleaned == ()
