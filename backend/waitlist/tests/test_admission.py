from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core.cache import cache
from django.test import override_settings

from waitlist.admission import (
    _acquire_slot,
    _cache_key,
    _compare_and_delete,
    _consume_bucket,
    _consume_generation_budgets,
    _lease_redis,
    acquire_generation,
    admit_bootstrap,
    admit_capability,
    admit_global_creation,
    network_digest,
    release_generation,
)
from waitlist.exceptions import AdmissionUnavailable, Throttled


def test_admission_buckets_are_bounded_and_cache_outage_fails_closed(monkeypatch):
    cache.clear()
    assert _consume_bucket("unit", capacity=2, refill_seconds=1)
    assert _consume_bucket("unit", capacity=2, refill_seconds=1)
    assert not _consume_bucket("unit", capacity=2, refill_seconds=1)
    monkeypatch.setattr(
        cache,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("down")),
    )
    monkeypatch.setattr(
        cache,
        "add",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("down")),
    )
    with pytest.raises(AdmissionUnavailable):
        admit_bootstrap("network")


@override_settings(
    ALLIES_WAITLIST_GLOBAL_CREATION_CAPACITY=1,
    ALLIES_WAITLIST_GLOBAL_CREATION_REFILL_SECONDS=3600,
)
def test_global_creation_budget_is_shared_across_client_identities():
    cache.clear()
    admit_global_creation()
    with pytest.raises(Throttled, match="creation"):
        admit_global_creation()


def test_token_bucket_refill_does_not_allow_window_boundary_burst(monkeypatch):
    cache.clear()
    now = [1000.0]
    monkeypatch.setattr("waitlist.admission.time.time", lambda: now[0])

    assert _consume_bucket("boundary", capacity=2, refill_seconds=1)
    assert _consume_bucket("boundary", capacity=2, refill_seconds=1)
    assert not _consume_bucket("boundary", capacity=2, refill_seconds=1)

    # A fixed-window implementation would admit two fresh tokens here.  The
    # token bucket has exactly one refill after one second.
    now[0] = 1000.999
    assert not _consume_bucket("boundary", capacity=2, refill_seconds=1)
    now[0] = 1001.0
    assert _consume_bucket("boundary", capacity=2, refill_seconds=1)
    assert not _consume_bucket("boundary", capacity=2, refill_seconds=1)


def test_local_token_bucket_is_thread_safe():
    cache.clear()
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(
            executor.map(
                lambda _attempt: _consume_bucket(
                    "concurrent", capacity=5, refill_seconds=3600
                ),
                range(20),
            )
        )
    assert sum(results) == 5


def test_redis_token_bucket_uses_atomic_script(monkeypatch):
    calls = []

    class Client:
        @staticmethod
        def eval(*args):
            calls.append(args)
            return 1

    monkeypatch.setattr("waitlist.admission._lease_redis", lambda: Client())
    assert _consume_bucket("redis", capacity=2, refill_seconds=1)
    assert calls[0][1] == 1
    assert "HSET" in calls[0][0]


def test_redis_token_bucket_denial_and_malformed_local_state(monkeypatch):
    class EmptyClient:
        @staticmethod
        def eval(*args):
            return 0

    monkeypatch.setattr("waitlist.admission._lease_redis", lambda: EmptyClient())
    assert not _consume_bucket("redis-denied", capacity=2, refill_seconds=1)

    monkeypatch.setattr("waitlist.admission._lease_redis", lambda: None)
    cache.clear()
    # State corruption must fail closed rather than minting a token.
    cache.set(_cache_key("bucket:v1:malformed"), ("not-a-number",), timeout=30)
    with pytest.raises(AdmissionUnavailable):
        _consume_bucket("malformed", capacity=2, refill_seconds=1)


def test_redis_token_bucket_outage_fails_closed(monkeypatch):
    class BrokenClient:
        @staticmethod
        def eval(*args):
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr("waitlist.admission._lease_redis", lambda: BrokenClient())
    with pytest.raises(AdmissionUnavailable):
        _consume_bucket("redis-down", capacity=2, refill_seconds=1)


@override_settings(CACHE_URL="redis://cache.internal:6379/0")
def test_lease_redis_builds_explicit_connection():
    client = _lease_redis()
    assert client is not None
    assert client.connection_pool.connection_kwargs["host"] == "cache.internal"


def test_local_compare_and_delete_ignores_wrong_owner():
    cache.clear()
    assert not _compare_and_delete("missing-slot", "owner")


@override_settings(
    DEBUG=True, ALLIES_WAITLIST_ENABLED=False, ALLIES_WAITLIST_CAPABILITY_KEY=""
)
def test_network_digest_has_local_fallback_key():
    assert len(network_digest("local")) == 32


@override_settings(ALLIES_WAITLIST_ENABLED=True, ALLIES_WAITLIST_CAPABILITY_KEY="")
def test_enabled_waitlist_network_digest_fails_closed_without_key():
    with pytest.raises(AdmissionUnavailable):
        network_digest("enabled-without-key")


def test_redis_lease_release_uses_atomic_compare_and_delete(monkeypatch):
    calls = []

    class Client:
        @staticmethod
        def eval(script, keys, key, value):
            calls.append((script, keys, key, value))
            return 1

        @staticmethod
        def set(key, value, *, nx, ex):
            calls.append(("set", key, value, nx, ex))
            return True

    monkeypatch.setattr("waitlist.admission._lease_redis", lambda: Client())
    assert _acquire_slot("slot", "owner", 30) is True
    assert _compare_and_delete("slot", "owner") is True
    assert calls[0] == ("set", ":1:slot", "owner", True, 30)
    assert calls[1][1:] == (1, ":1:slot", "owner")


@override_settings(CACHE_URL="redis://cache.internal:6379/0")
def test_configured_redis_lease_release_fails_closed(monkeypatch):
    class BrokenClient:
        @staticmethod
        def eval(*args, **kwargs):
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr("waitlist.admission._lease_redis", lambda: BrokenClient())
    with pytest.raises(AdmissionUnavailable, match="admission unavailable"):
        _compare_and_delete("slot", "owner")


@override_settings(
    ALLIES_WAITLIST_GENERATION_GLOBAL_CONCURRENCY=1,
    ALLIES_WAITLIST_GENERATION_GLOBAL_BUDGET_PER_MINUTE=2,
)
def test_generation_lease_is_global_and_released():
    cache.clear()
    first = acquire_generation("cap-a")
    with pytest.raises(Throttled):
        acquire_generation("cap-b")
    release_generation(first)
    second = acquire_generation("cap-b")
    release_generation(second)
    # Capability buckets remain an independent scope.
    cache.clear()
    admit_capability("cap-a")


@override_settings(
    ALLIES_WAITLIST_GENERATION_GLOBAL_CONCURRENCY=1,
    ALLIES_WAITLIST_GENERATION_GLOBAL_BUDGET_PER_MINUTE=100,
    ALLIES_WAITLIST_GENERATION_CAPABILITY_BUDGET_PER_MINUTE=1,
)
def test_generation_slot_saturation_does_not_consume_capability_budget():
    cache.clear()
    first = acquire_generation("cap-a")
    with pytest.raises(Throttled, match="concurrency"):
        acquire_generation("cap-b")
    release_generation(first)

    # The rejected request never reached paired budget admission, so this
    # capability's one-minute budget remains available.
    second = acquire_generation("cap-b")
    release_generation(second)


@override_settings(
    ALLIES_WAITLIST_GENERATION_GLOBAL_CONCURRENCY=1,
    ALLIES_WAITLIST_GENERATION_GLOBAL_BUDGET_PER_MINUTE=1,
    ALLIES_WAITLIST_GENERATION_CAPABILITY_BUDGET_PER_MINUTE=5,
)
def test_generation_global_budget_releases_slot_without_capability_burn():
    cache.clear()
    first = acquire_generation("cap-a")
    release_generation(first)
    with pytest.raises(Throttled, match="generation budget"):
        acquire_generation("cap-b")


def test_generation_budget_redis_script_reports_each_admission_reason(monkeypatch):
    class Client:
        result = 0

        @classmethod
        def eval(cls, *args):
            return cls.result

    monkeypatch.setattr("waitlist.admission._lease_redis", lambda: Client())
    assert (
        _consume_generation_budgets("cap", global_limit=2, capability_limit=2)[0]
        == "ok"
    )
    Client.result = 1
    assert (
        _consume_generation_budgets("cap", global_limit=2, capability_limit=2)[0]
        == "global"
    )
    Client.result = 2
    assert (
        _consume_generation_budgets("cap", global_limit=2, capability_limit=2)[0]
        == "capability"
    )


@override_settings(
    ALLIES_WAITLIST_GENERATION_GLOBAL_CONCURRENCY=1,
    ALLIES_WAITLIST_GENERATION_GLOBAL_BUDGET_PER_MINUTE=100,
    ALLIES_WAITLIST_GENERATION_CAPABILITY_BUDGET_PER_MINUTE=2,
)
def test_generation_budget_preserves_capacity_for_other_capabilities():
    cache.clear()
    for _ in range(2):
        lease = acquire_generation("cap-a")
        release_generation(lease)
    with pytest.raises(Throttled, match="capability budget"):
        acquire_generation("cap-a")

    other = acquire_generation("cap-b")
    release_generation(other)


@override_settings(
    ALLIES_WAITLIST_GENERATION_GLOBAL_CONCURRENCY=1,
    ALLIES_WAITLIST_GENERATION_GLOBAL_BUDGET_PER_MINUTE=10,
    ALLIES_WAITLIST_GENERATION_CAPABILITY_BUDGET_PER_MINUTE=1,
)
def test_generation_budget_can_be_refunded_for_definitive_provider_failure():
    cache.clear()
    first = acquire_generation("cap-refund")
    release_generation(first, refund_budget=True)
    second = acquire_generation("cap-refund")
    release_generation(second)


@override_settings(
    ALLIES_WAITLIST_GENERATION_GLOBAL_CONCURRENCY=1,
    ALLIES_WAITLIST_GENERATION_GLOBAL_BUDGET_PER_MINUTE=2,
    ALLIES_WAITLIST_GENERATION_CAPABILITY_BUDGET_PER_MINUTE=2,
)
def test_generation_budget_refills_as_a_strict_token_bucket(monkeypatch):
    cache.clear()
    now = [1_000.0]
    monkeypatch.setattr("waitlist.admission.time.time", lambda: now[0])

    for _ in range(2):
        lease = acquire_generation("cap-boundary")
        release_generation(lease)
    with pytest.raises(Throttled, match="generation budget"):
        acquire_generation("cap-boundary")

    now[0] = 1_029.9
    with pytest.raises(Throttled, match="generation budget"):
        acquire_generation("cap-boundary")

    now[0] = 1_030.0
    lease = acquire_generation("cap-boundary")
    release_generation(lease)


@override_settings(
    ALLIES_WAITLIST_GENERATION_GLOBAL_CONCURRENCY=1,
    ALLIES_WAITLIST_GENERATION_GLOBAL_BUDGET_PER_MINUTE=10,
    ALLIES_WAITLIST_GENERATION_CAPABILITY_BUDGET_PER_MINUTE=1,
)
def test_generation_budget_fairness_survives_capability_rotation():
    cache.clear()
    first = acquire_generation("cap-before", budget_identity="browser:stable")
    release_generation(first)

    with pytest.raises(Throttled, match="capability budget"):
        acquire_generation("cap-after", budget_identity="browser:stable")

    second = acquire_generation("cap-after", budget_identity="browser:other")
    release_generation(second)
