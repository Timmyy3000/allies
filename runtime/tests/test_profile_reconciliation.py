from __future__ import annotations

from types import SimpleNamespace

import pytest

from allies_runtime.foundry import (
    FoundryClient,
    FoundryError,
    FoundryWorker,
    ProfileDesiredState,
    ProfileReceipt,
    RepairRequiredError,
    ResponseLossError,
)
from allies_runtime.profile_store import (
    CleanupReceipt,
    ProfileCleanupStatus,
    ProfileProvisionStatus,
    ProfileSeed,
    ProfileStore,
)
from allies_runtime.reconciliation import (
    ProfileReconciler,
    ProfileReconciliationBlocked,
)


class QueueTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def request(self, method, path, *, headers, body=None):
        self.calls.append((method, path, dict(headers), body))
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


def desired_payload():
    return {
        "version": 1,
        "machine_generation": 3,
        "profiles": [
            {
                "profile_id": "00000000-0000-0000-0000-000000000001",
                "ally_ref": "ally-a",
                "hermes_profile_key": "ally-v1-00000000000000000000000000000001",
                "hermes_profile_key_version": 1,
                "lifecycle_state": "active",
                "lifecycle_epoch": 0,
                "seed_version": 1,
                "seed_fingerprint": "a" * 64,
                "materialized_generation": 3,
                "seed": {
                    "version": 1,
                    "personality": "Exact personality",
                    "provider": "openai",
                    "model": "gpt-test",
                    "base_url": None,
                    "first_chat_instruction": "Ask one useful question.",
                    "first_chat_instruction_version": 1,
                    "credential_refs": {"provider_api": "vault://providers/ally-a"},
                },
            }
        ],
    }


@pytest.mark.asyncio
async def test_foundry_client_reads_profile_reconciliation_without_echoing_seed_in_repr():
    transport = QueueTransport(desired_payload())
    client = FoundryClient(runtime_token="runtime-secret", transport=transport)
    profiles = await client.reconcile_profiles()
    assert len(profiles) == 1
    assert isinstance(profiles[0], ProfileDesiredState)
    assert profiles[0].seed["personality"] == "Exact personality"
    assert "runtime-secret" not in repr(profiles[0])
    assert transport.calls[0][0:2] == (
        "GET",
        "/api/v1/runtime/profiles/reconciliation",
    )


@pytest.mark.asyncio
async def test_foundry_client_posts_materialization_and_cleanup_receipts():
    materialized = {
        "profile_id": "profile-1",
        "lifecycle_state": "active",
        "lifecycle_epoch": 0,
        "materialized_generation": 3,
        "seed_fingerprint": "a" * 64,
        "receipt_id": "receipt-1",
        "result_code": "existing",
    }
    cleaned = {
        "profile_id": "profile-1",
        "lifecycle_state": "deprovisioned",
        "lifecycle_epoch": 1,
        "materialized_generation": 0,
        "seed_fingerprint": "a" * 64,
        "receipt_id": "receipt-2",
        "result_code": "deprovisioned",
        "deleted": True,
        "active_lease_count": 0,
    }
    transport = QueueTransport(materialized, cleaned)
    client = FoundryClient(runtime_token="runtime-secret", transport=transport)
    first = await client.materialization_receipt(
        "profile-1",
        operation_id="operation-1",
        lifecycle_epoch=0,
        materialized_generation=3,
        seed_fingerprint="a" * 64,
        result_code="existing",
    )
    second = await client.cleanup_receipt(
        "profile-1",
        operation_id="operation-2",
        lifecycle_epoch=1,
        request_digest="b" * 64,
        result_code="deprovisioned",
        deleted=True,
        active_lease_count=0,
    )
    assert isinstance(first, ProfileReceipt)
    assert first.receipt_id == "receipt-1"
    assert second.deleted is True
    assert transport.calls[0][1].endswith("materialization-receipt")
    assert transport.calls[1][1].endswith("cleanup-receipt")
    assert "runtime-secret" not in repr(client)


@pytest.mark.asyncio
async def test_foundry_client_maps_repair_required_response():
    transport = QueueTransport({"status": 409, "body": {"code": "REPAIR_REQUIRED"}})
    client = FoundryClient(runtime_token="runtime-secret", transport=transport)
    with pytest.raises(RepairRequiredError):
        await client.reconcile_profiles()


@pytest.mark.asyncio
async def test_foundry_client_rejects_malformed_profile_response():
    transport = QueueTransport({"version": 1, "profiles": [{"profile_id": "only-id"}]})
    client = FoundryClient(runtime_token="runtime-secret", transport=transport)
    with pytest.raises(FoundryError):
        await client.reconcile_profiles()


@pytest.mark.asyncio
async def test_profile_reconciler_materializes_then_acknowledges_store_receipt(
    tmp_path,
):
    seed = ProfileSeed(
        foundry_profile_id="12345678-1234-5678-1234-567812345678",
        ally_name="ally-a",
        personality="Exact personality",
        provider="openai",
        model="gpt-test",
        first_chat_instruction="Ask one useful question.",
        credential_refs={"PROVIDER_API": "vault://providers/ally-a"},
        lifecycle_epoch=0,
        materialized_generation=3,
        operation_id="operation-1",
    )
    desired = ProfileDesiredState(
        machine_generation=3,
        profile_id=seed.foundry_profile_id,
        ally_ref="ally-a",
        hermes_profile_key=seed.profile_key,
        hermes_profile_key_version=1,
        lifecycle_state="pending",
        lifecycle_epoch=0,
        seed_version=1,
        seed_fingerprint=seed.fingerprint,
        materialized_generation=0,
        seed={
            "version": 1,
            "personality": seed.personality,
            "provider": seed.provider,
            "model": seed.model,
            "base_url": None,
            "first_chat_instruction": seed.first_chat_instruction,
            "first_chat_instruction_version": 1,
            "credential_refs": dict(seed.credential_refs),
        },
        materialization_operation_id=None,
        materialization_request_digest="",
        materialization_receipt_id=None,
        materialization_result_code="",
        cleanup_operation_id=None,
        cleanup_context_digest="",
        cleanup_request_digest="",
        cleanup_receipt_id=None,
        cleanup_result_code="",
        cleanup_expires_at=None,
    )

    class FakeFoundry:
        def __init__(self):
            self.receipts = []

        async def reconcile_profiles(self):
            return (desired,)

        async def materialization_receipt(self, profile_id, **kwargs):
            self.receipts.append((profile_id, kwargs))
            return ProfileReceipt(
                profile_id=str(profile_id),
                lifecycle_state="active",
                lifecycle_epoch=0,
                materialized_generation=3,
                seed_fingerprint=kwargs["seed_fingerprint"],
                receipt_id="receipt-1",
                result_code=kwargs["result_code"],
            )

    foundry = FakeFoundry()
    store = ProfileStore(
        tmp_path / "volume",
        api_key_factory=lambda: "profile-local-key-0123456789",
        credential_resolver={"vault://providers/ally-a": "secret"},
    )
    report = await ProfileReconciler(foundry, store).reconcile()
    assert len(report.materialized) == 1
    assert foundry.receipts[0][1]["seed_fingerprint"] == seed.fingerprint
    profile_config = (
        tmp_path / "volume" / "profiles" / seed.profile_key / "config.yaml"
    ).read_text(encoding="utf-8")
    assert 'provider: "allies_mnemosyne"' in profile_config
    assert 'mode: "context_only"' in profile_config


class StaticFoundry:
    def __init__(self, profiles):
        self.profiles = tuple(profiles)
        self.materialized = []
        self.cleaned = []

    async def reconcile_profiles(self):
        return self.profiles

    async def materialization_receipt(self, profile_id, **kwargs):
        self.materialized.append((profile_id, kwargs))
        return ProfileReceipt(
            profile_id=str(profile_id),
            lifecycle_state="active",
            lifecycle_epoch=kwargs["lifecycle_epoch"],
            materialized_generation=kwargs["materialized_generation"],
            seed_fingerprint=kwargs["seed_fingerprint"],
            receipt_id="receipt-materialized",
            result_code=kwargs["result_code"],
        )

    async def cleanup_receipt(self, profile_id, **kwargs):
        self.cleaned.append((profile_id, kwargs))
        return ProfileReceipt(
            profile_id=str(profile_id),
            lifecycle_state="deprovisioned",
            lifecycle_epoch=kwargs["lifecycle_epoch"],
            materialized_generation=0,
            seed_fingerprint="a" * 64,
            receipt_id="receipt-cleaned",
            result_code=kwargs["result_code"],
            deleted=kwargs["deleted"],
            active_lease_count=kwargs["active_lease_count"],
        )


async def parsed_profile(**changes):
    payload = desired_payload()["profiles"][0]
    payload.update(changes)
    client = FoundryClient(
        runtime_token="runtime-secret",
        transport=QueueTransport(
            {"version": 1, "machine_generation": 3, "profiles": [payload]}
        ),
    )
    return (await client.reconcile_profiles())[0]


@pytest.mark.asyncio
async def test_profile_reconciler_skips_current_generation_receipts():
    profile = await parsed_profile(
        materialization_operation_id="operation-1",
        materialization_receipt_id="pr-" + "a" * 32,
    )
    foundry = StaticFoundry([profile])

    class NeverCalledStore:
        def materialize(self, _seed):
            raise AssertionError("already materialized profiles must be skipped")

    report = await ProfileReconciler(foundry, NeverCalledStore()).reconcile()

    assert report.materialized == ()
    assert report.cleaned == ()


@pytest.mark.asyncio
async def test_profile_reconciler_cleans_and_acknowledges_deprovisioning():
    profile = await parsed_profile(
        lifecycle_state="cleanup_pending",
        lifecycle_epoch=1,
        cleanup_operation_id="cleanup-1",
        cleanup_request_digest="b" * 64,
    )

    class CleanupStore:
        def cleanup(self, *_args):
            return CleanupReceipt(
                status=ProfileCleanupStatus.DEPROVISIONED,
                profile_key=profile.hermes_profile_key,
                lifecycle_epoch=1,
                operation_id="cleanup-1",
                receipt_id="cr-" + "a" * 32,
            )

    foundry = StaticFoundry([profile])
    report = await ProfileReconciler(foundry, CleanupStore()).reconcile()

    assert len(report.cleaned) == 1
    assert foundry.cleaned[0][1]["deleted"] is True
    assert foundry.cleaned[0][1]["active_lease_count"] == 0


@pytest.mark.asyncio
async def test_profile_reconciler_does_not_acknowledge_fenced_cleanup():
    profile = await parsed_profile(
        lifecycle_state="deprovisioned",
        lifecycle_epoch=1,
        cleanup_operation_id="cleanup-1",
        cleanup_request_digest="b" * 64,
    )

    class FencedCleanupStore:
        def cleanup(self, *_args):
            return CleanupReceipt(
                status=ProfileCleanupStatus.FENCED,
                profile_key=profile.hermes_profile_key,
                lifecycle_epoch=1,
                operation_id="cleanup-1",
                receipt_id="cr-" + "a" * 32,
                repair_code="stale_cleanup_epoch",
            )

    foundry = StaticFoundry([profile])
    with pytest.raises(ProfileReconciliationBlocked):
        await ProfileReconciler(foundry, FencedCleanupStore()).reconcile()
    assert foundry.cleaned == []


@pytest.mark.asyncio
async def test_profile_reconciler_blocks_cleanup_without_request_digest():
    profile = await parsed_profile(
        lifecycle_state="cleanup_pending",
        lifecycle_epoch=1,
        cleanup_operation_id="cleanup-1",
        cleanup_request_digest="",
    )

    with pytest.raises(ProfileReconciliationBlocked):
        await ProfileReconciler(StaticFoundry([profile]), object()).reconcile()


@pytest.mark.asyncio
async def test_profile_reconciler_waits_for_active_leases_before_cleanup():
    profile = await parsed_profile(
        lifecycle_state="cleanup_pending",
        lifecycle_epoch=1,
        cleanup_operation_id="cleanup-1",
        cleanup_request_digest="b" * 64,
        active_lease_count=1,
    )

    with pytest.raises(ProfileReconciliationBlocked):
        await ProfileReconciler(StaticFoundry([profile]), object()).reconcile()


@pytest.mark.asyncio
async def test_profile_reconciler_compensates_after_cleanup_fences_publish():
    active = await parsed_profile(lifecycle_state="pending")
    cleanup = await parsed_profile(
        lifecycle_state="cleanup_pending",
        lifecycle_epoch=1,
        cleanup_operation_id="cleanup-1",
        cleanup_request_digest="b" * 64,
    )

    class RaceFoundry(StaticFoundry):
        def __init__(self):
            super().__init__([active])
            self.reconcile_calls = 0

        async def reconcile_profiles(self):
            self.reconcile_calls += 1
            return (active,) if self.reconcile_calls == 1 else (cleanup,)

        async def materialization_receipt(self, *_args, **_kwargs):
            raise RepairRequiredError("cleanup fenced materialization")

    class CompensatingStore:
        def __init__(self):
            self.cleaned = []

        def materialize(self, _seed):
            return SimpleNamespace(
                status=ProfileProvisionStatus.EXISTING,
                seed_fingerprint="a" * 64,
                result_code="existing",
            )

        def cleanup(self, *args):
            self.cleaned.append(args)
            return CleanupReceipt(
                status=ProfileCleanupStatus.DEPROVISIONED,
                profile_key=cleanup.hermes_profile_key,
                lifecycle_epoch=1,
                operation_id="cleanup-1",
                receipt_id="cr-" + "a" * 32,
            )

    foundry = RaceFoundry()
    store = CompensatingStore()
    with pytest.raises(ProfileReconciliationBlocked):
        await ProfileReconciler(foundry, store).reconcile()

    assert foundry.reconcile_calls == 2
    assert len(store.cleaned) == 1


@pytest.mark.asyncio
async def test_foundry_worker_reconciles_again_after_startup():
    clock_value = 0.0
    reconciliations = 0

    def clock():
        nonlocal clock_value
        clock_value += 1.0
        return clock_value

    class PollingFoundry:
        async def reconcile(self):
            nonlocal reconciliations
            reconciliations += 1

        async def reconcile_profiles(self):
            nonlocal reconciliations
            reconciliations += 1
            return ()

        async def claim(self, *_args, **_kwargs):
            return None

    foundry = PollingFoundry()
    worker = FoundryWorker(
        foundry,
        object(),
        profile_reconciler=foundry,
        profile_reconcile_interval=0.5,
        clock=clock,
    )
    await worker.run(idle_cycles=2)

    assert reconciliations >= 2


@pytest.mark.asyncio
async def test_foundry_worker_retries_lost_profile_reconciliation_response():
    class RecoveringReconciler:
        def __init__(self):
            self.calls = 0

        async def reconcile(self):
            self.calls += 1
            if self.calls == 1:
                raise ResponseLossError("response lost")

    class IdleFoundry:
        async def claim(self, *_args, **_kwargs):
            return None

    reconciler = RecoveringReconciler()
    worker = FoundryWorker(
        IdleFoundry(),
        object(),
        profile_reconciler=reconciler,
    )

    result = await worker.run(idle_cycles=1)

    assert result == ()
    assert reconciler.calls == 2


@pytest.mark.asyncio
async def test_profile_reconciler_blocks_repair_state_and_store_failures():
    repair_profile = await parsed_profile(lifecycle_state="repair_required")
    with pytest.raises(ProfileReconciliationBlocked):
        await ProfileReconciler(StaticFoundry([repair_profile]), object()).reconcile()

    pending_profile = await parsed_profile(lifecycle_state="pending")

    class BrokenStore:
        def materialize(self, _seed):
            return SimpleNamespace(status=ProfileProvisionStatus.REPAIR_REQUIRED)

    with pytest.raises(ProfileReconciliationBlocked):
        await ProfileReconciler(
            StaticFoundry([pending_profile]), BrokenStore()
        ).reconcile()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "seed_change",
    [
        {"seed": {}},
        {
            "seed": {
                "personality": "ok",
                "provider": "openai",
                "model": "gpt-test",
                "first_chat_instruction": "ask",
                "credential_refs": [],
            }
        },
        {
            "seed": {
                "personality": 17,
                "provider": "openai",
                "model": "gpt-test",
                "first_chat_instruction": "ask",
                "credential_refs": {},
            }
        },
    ],
)
async def test_profile_reconciler_rejects_unrepresentable_seed(seed_change):
    profile = await parsed_profile(**seed_change)

    with pytest.raises(ProfileReconciliationBlocked):
        await ProfileReconciler(StaticFoundry([profile]), object()).reconcile()
