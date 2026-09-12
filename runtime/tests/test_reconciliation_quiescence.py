from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest

from allies_runtime.errors import HermesError
from allies_runtime.foundry import (
    ProfileDesiredState,
    ProfileReceipt,
    RuntimeReconciliationSnapshot,
)
from allies_runtime.profile_store import CleanupReceipt, ProfileCleanupStatus
from allies_runtime.quiescence import QuiescenceProof
from allies_runtime.reconciliation import ProfileReconciler


def profile(*, requires_quiescence=True) -> ProfileDesiredState:
    return ProfileDesiredState(
        machine_generation=3,
        profile_id=str(uuid4()),
        ally_ref="ally-a",
        hermes_profile_key="ally-v1-00000000000000000000000000000001",
        hermes_profile_key_version=1,
        lifecycle_state="cleanup_pending",
        lifecycle_epoch=4,
        seed_version=1,
        seed_fingerprint="a" * 64,
        materialized_generation=3,
        seed={},
        materialization_operation_id=None,
        materialization_request_digest="",
        materialization_receipt_id=None,
        materialization_result_code="",
        cleanup_operation_id=str(uuid4()),
        cleanup_context_digest="",
        cleanup_request_digest="b" * 64,
        cleanup_receipt_id=None,
        cleanup_result_code="pending",
        cleanup_expires_at=None,
        active_lease_count=0,
        cleanup_attempt_id=str(uuid4()) if requires_quiescence else None,
        cleanup_requires_quiescence=requires_quiescence,
    )


def proof_for(item: ProfileDesiredState, identity: str):
    return {
        "state": "quiesced",
        "safe_error_code": "",
        "active_runs": 0,
        "active_profile_io": 0,
        "open_profile_stores": 0,
        "owned_children": 0,
        "operation_id": item.cleanup_operation_id,
        "attempt_id": item.cleanup_attempt_id,
        "lifecycle_epoch": item.lifecycle_epoch,
        "request_digest": item.cleanup_request_digest,
        "machine_generation": item.machine_generation,
        "runtime_start_epoch": 12,
        "hermes_instance_id": identity,
    }


class FenceStore:
    def __init__(
        self,
        item,
        *,
        fence_status=ProfileCleanupStatus.FENCED,
        cleanup_status=ProfileCleanupStatus.DEPROVISIONED,
    ):
        self.item = item
        self.fence_status = fence_status
        self.cleanup_status = cleanup_status
        self.fences = []
        self.cleanups = []

    def fence_deletion(self, *args, **kwargs):
        self.fences.append((args, kwargs))
        return CleanupReceipt(
            self.fence_status,
            self.item.hermes_profile_key,
            self.item.lifecycle_epoch,
            self.item.cleanup_operation_id,
            "cr-" + "a" * 32,
            None,
            self.item.cleanup_attempt_id,
            self.item.cleanup_request_digest,
        )

    def cleanup(self, *args, **kwargs):
        self.cleanups.append((args, kwargs))
        return CleanupReceipt(
            self.cleanup_status,
            self.item.hermes_profile_key,
            self.item.lifecycle_epoch,
            self.item.cleanup_operation_id,
            "cr-" + "b" * 32,
            None,
            self.item.cleanup_attempt_id,
            self.item.cleanup_request_digest,
        )


class QFoundry:
    def __init__(self, item, *, recheck=None, recheck_error=None):
        self.item = item
        self.recheck = recheck
        self.recheck_error = recheck_error
        self.reconcile_calls = 0
        self.receipts = []
        self.last_reconciliation_snapshot = RuntimeReconciliationSnapshot(
            machine_generation=item.machine_generation,
            runtime_start_epoch=12,
            profiles=(item,),
        )

    async def reconcile_profiles(self):
        self.reconcile_calls += 1
        if self.reconcile_calls > 1 and self.recheck_error is not None:
            raise self.recheck_error
        return (self.recheck or self.item,)

    async def cleanup_receipt(self, profile_id, **kwargs):
        self.receipts.append((profile_id, kwargs))
        return ProfileReceipt(
            profile_id=str(profile_id),
            lifecycle_state="deprovisioned",
            lifecycle_epoch=kwargs["lifecycle_epoch"],
            materialized_generation=0,
            seed_fingerprint=self.item.seed_fingerprint,
            receipt_id="receipt-cleaned",
            result_code=kwargs["result_code"],
            deleted=kwargs["deleted"],
            active_lease_count=kwargs["active_lease_count"],
            attempt_id=kwargs.get("attempt_id"),
            machine_generation=kwargs.get("machine_generation"),
            runtime_start_epoch=kwargs.get("runtime_start_epoch"),
            runtime_boot_id=kwargs.get("runtime_boot_id"),
            hermes_instance_id=kwargs.get("hermes_instance_id"),
            quiescence=kwargs.get("quiescence"),
        )


class Worker:
    def __init__(self, *, state="quiesced", missing=False):
        self.fenced = []
        self.state = state
        self.missing = missing

    def fence_profile(self, profile_key):
        self.fenced.append(profile_key)

    async def quiesce_profile(self, _profile_key, *, timeout_seconds):
        return (self.state, ())


class Hermes:
    def __init__(self, item, *, identity=None, proof=None, error=None):
        self.item = item
        self.identity = identity or str(uuid4())
        self.proof = proof
        self.error = error
        self.identities = 0
        self.requests = []

    async def hermes_instance_id(self):
        self.identities += 1
        if self.error is not None:
            raise self.error
        return self.identity

    async def quiesce_profile(self, profile_key, **kwargs):
        self.requests.append((profile_key, kwargs))
        if self.error is not None:
            raise self.error
        return (
            self.proof
            if self.proof is not None
            else proof_for(self.item, self.identity)
        )


@pytest.mark.asyncio
async def test_reconciler_completes_quiescent_delete_and_binds_receipt():
    item = profile()
    identity = str(uuid4())
    foundry = QFoundry(item)
    store = FenceStore(item)
    worker = Worker()
    hermes = Hermes(item, identity=identity)
    reconciler = ProfileReconciler(
        foundry,
        store,
        correlation_id=str(uuid4()),
        hermes=hermes,
        worker=worker,
    )
    report = await reconciler.reconcile()
    assert len(report.cleaned) == 1
    assert foundry.reconcile_calls == 2
    assert store.fences and store.cleanups
    assert worker.fenced == [item.hermes_profile_key]
    receipt_kwargs = foundry.receipts[0][1]
    assert receipt_kwargs["attempt_id"] == item.cleanup_attempt_id
    assert receipt_kwargs["hermes_instance_id"] == identity
    assert receipt_kwargs["quiescence"]["state"] == "quiesced"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing", ["hermes", "worker", "correlation", "runtime_epoch", "attempt"]
)
async def test_reconciler_keeps_quiescent_delete_pending_without_required_identity(
    missing,
):
    item = profile()
    foundry = QFoundry(item)
    store = FenceStore(item)
    worker = Worker()
    hermes = Hermes(item)
    correlation = str(uuid4())
    if missing == "hermes":
        hermes = None
    if missing == "worker":
        worker = None
    if missing == "correlation":
        correlation = None
    if missing == "runtime_epoch":
        foundry.last_reconciliation_snapshot = replace(
            foundry.last_reconciliation_snapshot, runtime_start_epoch=None
        )
    if missing == "attempt":
        item = replace(item, cleanup_attempt_id=None)
        foundry = QFoundry(item)
        store = FenceStore(item)
        hermes = Hermes(item)
    report = await ProfileReconciler(
        foundry, store, correlation_id=correlation, hermes=hermes, worker=worker
    ).reconcile()
    assert report.cleaned == ()
    assert report.blocked_profile_ids == (item.profile_id,)


@pytest.mark.asyncio
async def test_reconciler_does_not_acknowledge_fence_or_worker_failures():
    item = profile()
    foundry = QFoundry(item)
    store = FenceStore(item, fence_status=ProfileCleanupStatus.REPAIR_REQUIRED)
    report = await ProfileReconciler(
        foundry,
        store,
        correlation_id=str(uuid4()),
        hermes=Hermes(item),
        worker=Worker(),
    ).reconcile()
    assert report.cleaned == ()
    assert foundry.receipts == []

    foundry = QFoundry(item)
    store = FenceStore(item)
    report = await ProfileReconciler(
        foundry,
        store,
        correlation_id=str(uuid4()),
        hermes=Hermes(item),
        worker=Worker(state="quiescing"),
    ).reconcile()
    assert report.cleaned == ()
    assert store.cleanups == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "proof",
    [
        {
            "state": "quiesced",
            "safe_error_code": "",
            "active_runs": 1,
            "active_profile_io": 0,
            "open_profile_stores": 0,
            "owned_children": 0,
        },
        {
            "state": "repair_required",
            "safe_error_code": "needs_repair",
            "active_runs": 0,
            "active_profile_io": 0,
            "open_profile_stores": 0,
            "owned_children": 0,
        },
        {
            "state": "quiesced",
            "safe_error_code": "",
            "active_runs": 0,
            "active_profile_io": 0,
            "open_profile_stores": 0,
        },
    ],
)
async def test_reconciler_rejects_incomplete_hermes_proof(proof):
    item = profile()
    foundry = QFoundry(item)
    store = FenceStore(item)
    hermes = Hermes(item, proof=proof)
    report = await ProfileReconciler(
        foundry,
        store,
        correlation_id=str(uuid4()),
        hermes=hermes,
        worker=Worker(),
    ).reconcile()
    assert report.cleaned == ()
    assert store.cleanups == []


@pytest.mark.asyncio
async def test_reconciler_rechecks_leases_and_rejects_stale_or_unavailable_authority():
    item = profile()
    changed = replace(item, active_lease_count=1)
    foundry = QFoundry(item, recheck=changed)
    store = FenceStore(item)
    report = await ProfileReconciler(
        foundry,
        store,
        correlation_id=str(uuid4()),
        hermes=Hermes(item),
        worker=Worker(),
    ).reconcile()
    assert report.cleaned == ()
    assert store.cleanups == []

    foundry = QFoundry(item, recheck_error=HermesError("lost authority"))
    report = await ProfileReconciler(
        foundry,
        FenceStore(item),
        correlation_id=str(uuid4()),
        hermes=Hermes(item),
        worker=Worker(),
    ).reconcile()
    assert report.cleaned == ()


@pytest.mark.asyncio
async def test_reconciler_accepts_quiescence_proof_object_and_rejects_fenced_store():
    item = profile()
    identity = str(uuid4())
    proof = QuiescenceProof(
        profile_key=item.hermes_profile_key,
        operation_id=item.cleanup_operation_id,
        attempt_id=item.cleanup_attempt_id,
        lifecycle_epoch=item.lifecycle_epoch,
        request_digest=item.cleanup_request_digest,
        machine_generation=item.machine_generation,
        runtime_start_epoch=12,
        hermes_instance_id=identity,
        state="quiesced",
        safe_error_code="",
    )
    foundry = QFoundry(item)
    store = FenceStore(item, cleanup_status=ProfileCleanupStatus.FENCED)
    report = await ProfileReconciler(
        foundry,
        store,
        correlation_id=str(uuid4()),
        hermes=Hermes(item, identity=identity, proof=proof),
        worker=Worker(),
    ).reconcile()
    assert report.cleaned == ()
    assert foundry.receipts == []
