"""Redis-backed, fail-closed waitlist abuse and generation admission.

All three scopes live here deliberately: network bootstrap, capability-bound
operations, and the distributed global generation lease.  Redis Lua scripts
provide cross-worker atomicity, with deterministic thread-safe cache fallbacks
for local development and tests.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings
from django.core.cache import cache
from redis import Redis

from .exceptions import AdmissionUnavailable, Throttled

_LOCAL_NETWORK_KEY = secrets.token_bytes(32)


def _cache_key(value: str) -> str:
    digest = hashlib.sha256(value.encode()).hexdigest()[:32]
    return f"waitlist:{digest}"


_COMPARE_AND_DELETE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


# Token-bucket admission is evaluated in Redis' single-threaded Lua runtime so
# the refill and decrement cannot be interleaved across Cloud workers.  The
# timestamp is deliberately retained when a caller's clock moves backwards;
# that fails closed until wall time catches up instead of minting free tokens.
_TOKEN_BUCKET_SCRIPT = """
local now = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local refill_ms = tonumber(ARGV[3])
local ttl_seconds = tonumber(ARGV[4])
local tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens'))
local timestamp = tonumber(redis.call('HGET', KEYS[1], 'timestamp'))

if tokens == nil or timestamp == nil then
    tokens = capacity
    timestamp = now
elseif now > timestamp then
    tokens = math.min(capacity, tokens + ((now - timestamp) / refill_ms))
    timestamp = now
end

local allowed = 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'timestamp', timestamp)
redis.call('EXPIRE', KEYS[1], ttl_seconds)
return allowed
"""


_GENERATION_BUDGET_BUCKET_SCRIPT = """
local now = tonumber(ARGV[1])
local global_capacity = tonumber(ARGV[2])
local capability_capacity = tonumber(ARGV[3])
local global_refill_ms = tonumber(ARGV[4])
local capability_refill_ms = tonumber(ARGV[5])
local ttl_seconds = tonumber(ARGV[6])

local global_tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens'))
local global_timestamp = tonumber(redis.call('HGET', KEYS[1], 'timestamp'))
if global_tokens == nil or global_timestamp == nil then
    global_tokens = global_capacity
    global_timestamp = now
elseif now > global_timestamp then
    global_tokens = math.min(
        global_capacity,
        global_tokens + ((now - global_timestamp) / global_refill_ms)
    )
    global_timestamp = now
end

local capability_tokens = tonumber(redis.call('HGET', KEYS[2], 'tokens'))
local capability_timestamp = tonumber(redis.call('HGET', KEYS[2], 'timestamp'))
if capability_tokens == nil or capability_timestamp == nil then
    capability_tokens = capability_capacity
    capability_timestamp = now
elseif now > capability_timestamp then
    capability_tokens = math.min(
        capability_capacity,
        capability_tokens + ((now - capability_timestamp) / capability_refill_ms)
    )
    capability_timestamp = now
end

local reason = 0
if global_tokens < 1 then
    reason = 1
elseif capability_tokens < 1 then
    reason = 2
else
    global_tokens = global_tokens - 1
    capability_tokens = capability_tokens - 1
end

redis.call('HSET', KEYS[1], 'tokens', global_tokens, 'timestamp', global_timestamp)
redis.call('HSET', KEYS[2], 'tokens', capability_tokens, 'timestamp', capability_timestamp)
redis.call('EXPIRE', KEYS[1], ttl_seconds)
redis.call('EXPIRE', KEYS[2], ttl_seconds)
return reason
"""


_REFUND_GENERATION_BUDGET_SCRIPT = """
local global_capacity = tonumber(ARGV[1])
local capability_capacity = tonumber(ARGV[2])
local global_tokens = tonumber(redis.call('HGET', KEYS[1], 'tokens'))
local capability_tokens = tonumber(redis.call('HGET', KEYS[2], 'tokens'))

if global_tokens ~= nil then
    redis.call('HSET', KEYS[1], 'tokens', math.min(global_capacity, global_tokens + 1))
end
if capability_tokens ~= nil then
    redis.call(
        'HSET',
        KEYS[2],
        'tokens',
        math.min(capability_capacity, capability_tokens + 1)
    )
end
return 1
"""


# The URL-less path is intentionally deterministic for local development and
# tests.  Cache operations alone do not make a read/refill/decrement sequence
# atomic, so a process-local lock protects the fallback while Redis uses the
# Lua script above for cross-worker atomicity.
_LOCAL_BUCKET_LOCK = threading.Lock()
_LOCAL_BUDGET_LOCK = threading.Lock()


@lru_cache(maxsize=4)
def _redis_connection(url: str, connect_timeout: float, socket_timeout: float) -> Redis:
    return Redis.from_url(
        url,
        socket_connect_timeout=connect_timeout,
        socket_timeout=socket_timeout,
        decode_responses=False,
    )


def _lease_redis() -> Redis | None:
    """Return the explicit Redis lease client or a local-debug fallback."""

    url = str(getattr(settings, "CACHE_URL", ""))
    if not url:
        # Production settings reject waitlist enablement without CACHE_URL.
        # The URL-less path therefore exists only for local development/tests.
        return None
    return _redis_connection(
        url,
        float(getattr(settings, "CACHE_CONNECT_TIMEOUT_SECONDS", 10.0)),
        float(getattr(settings, "CACHE_SOCKET_TIMEOUT_SECONDS", 10.0)),
    )


def _lease_key(key: str) -> str:
    return str(cache.make_key(key))


def _acquire_slot(key: str, token: str, timeout: int) -> bool:
    """Acquire a generation slot through the same backend used for release."""

    client = _lease_redis()
    if client is None:
        return bool(cache.add(key, token, timeout=timeout))
    try:
        return bool(client.set(_lease_key(key), token, nx=True, ex=timeout))
    except Exception as exc:
        raise AdmissionUnavailable("waitlist admission unavailable") from exc


def _compare_and_delete(key: str, token: str) -> bool:
    """Release a lease atomically; never use a production compare/delete fallback."""

    client = _lease_redis()
    if client is None:
        # Local-memory development and tests have no cross-process successor race.
        if cache.get(key) == token:
            return bool(cache.delete(key))
        return False
    try:
        return bool(
            client.eval(
                _COMPARE_AND_DELETE_SCRIPT,
                1,
                _lease_key(key),
                token,
            )
        )
    except Exception as exc:
        raise AdmissionUnavailable("waitlist admission unavailable") from exc


def network_digest(identity: str) -> str:
    key = str(getattr(settings, "ALLIES_WAITLIST_CAPABILITY_KEY", ""))
    if not key:
        if getattr(settings, "DEBUG", True) and not getattr(
            settings, "ALLIES_WAITLIST_ENABLED", False
        ):
            key_bytes = _LOCAL_NETWORK_KEY
        else:
            raise AdmissionUnavailable("waitlist admission unavailable")
    else:
        key_bytes = key.encode()
    return hmac.new(key_bytes, identity.encode(), hashlib.sha256).hexdigest()[:32]


def _consume_bucket(key: str, *, capacity: int, refill_seconds: float) -> bool:
    """Consume one token from a strict distributed token bucket.

    A fixed-window counter permits two full bursts at a window boundary.  The
    token bucket instead admits an initial ``capacity`` burst and then refills
    one token every ``refill_seconds``.  Redis evaluates that state transition
    atomically; URL-less local development uses the same semantics behind a
    process lock so tests remain deterministic.
    """

    if capacity <= 0 or refill_seconds <= 0:
        raise AdmissionUnavailable("waitlist admission unavailable")

    try:
        capacity = int(capacity)
        refill_seconds = float(refill_seconds)
        # Millisecond precision keeps normal settings accurate while avoiding
        # a zero divisor for unusually small local test intervals.
        refill_ms = max(1, round(refill_seconds * 1000))
        ttl_seconds = max(1, math.ceil(capacity * refill_seconds * 2))
        state_key = _cache_key(f"bucket:v1:{key}")
        client = _lease_redis()
        if client is not None:
            result = client.eval(
                _TOKEN_BUCKET_SCRIPT,
                1,
                _lease_key(state_key),
                int(time.time() * 1000),
                capacity,
                refill_ms,
                ttl_seconds,
            )
            return int(result) == 1

        now = time.time()
        with _LOCAL_BUCKET_LOCK:
            state = cache.get(state_key)
            if state is None:
                tokens = float(capacity)
                last_timestamp = now
            else:
                try:
                    tokens, last_timestamp = state
                    tokens = float(tokens)
                    last_timestamp = float(last_timestamp)
                except (TypeError, ValueError) as exc:
                    raise TypeError("invalid admission bucket") from exc
                elapsed = max(0.0, now - last_timestamp)
                tokens = min(capacity, tokens + elapsed / refill_seconds)
                # Do not move the clock backwards.  That mirrors the Redis
                # script and prevents a clock rollback from minting tokens.
                last_timestamp = max(last_timestamp, now)
            allowed = tokens >= 1.0
            if allowed:
                tokens -= 1.0
            cache.set(
                state_key,
                (tokens, last_timestamp),
                timeout=ttl_seconds,
            )
            return allowed
    except AdmissionUnavailable:
        raise
    except Exception as exc:
        raise AdmissionUnavailable("waitlist admission unavailable") from exc


def admit_bootstrap(identity: str) -> None:
    key = f"bootstrap:{network_digest(identity)}"
    if not _consume_bucket(
        key,
        capacity=int(getattr(settings, "ALLIES_WAITLIST_BOOTSTRAP_CAPACITY", 30)),
        refill_seconds=float(
            getattr(settings, "ALLIES_WAITLIST_BOOTSTRAP_REFILL_SECONDS", 1.0)
        ),
    ):
        raise Throttled("waitlist bootstrap throttled")


def admit_creation(identity: str) -> None:
    """Bound unaffiliated draft creation without throttling session issuance."""

    key = f"creation:{network_digest(identity)}"
    if not _consume_bucket(
        key,
        capacity=int(getattr(settings, "ALLIES_WAITLIST_CREATION_CAPACITY", 120)),
        refill_seconds=float(
            getattr(settings, "ALLIES_WAITLIST_CREATION_REFILL_SECONDS", 1.0)
        ),
    ):
        raise Throttled("waitlist creation throttled")


def admit_global_creation() -> None:
    """Keep aggregate draft creation below the bounded cleanup throughput."""

    if not _consume_bucket(
        "creation:global",
        capacity=int(
            getattr(settings, "ALLIES_WAITLIST_GLOBAL_CREATION_CAPACITY", 100)
        ),
        refill_seconds=float(
            getattr(settings, "ALLIES_WAITLIST_GLOBAL_CREATION_REFILL_SECONDS", 9.0)
        ),
    ):
        raise Throttled("waitlist creation throttled")


def admit_capability(digest: str) -> None:
    if not _consume_bucket(
        f"capability:{digest}",
        capacity=int(getattr(settings, "ALLIES_WAITLIST_CAPABILITY_CAPACITY", 30)),
        refill_seconds=float(
            getattr(settings, "ALLIES_WAITLIST_CAPABILITY_REFILL_SECONDS", 1.0)
        ),
    ):
        raise Throttled("waitlist capability throttled")


def _consume_generation_budgets(
    digest: str,
    *,
    global_limit: int,
    capability_limit: int,
    budget_identity: str | None = None,
) -> tuple[str, str, str]:
    """Atomically reserve the global and capability generation budgets.

    A paired token bucket checks both scopes before decrementing either one,
    so a rejected generation leaves both budgets untouched.  The caller may
    provide a stable browser/network identity for the per-capability fairness
    bucket; direct service callers fall back to the capability digest.
    """

    budget_scope = budget_identity or digest
    global_key = _cache_key("generation:budget:global")
    capability_key = _cache_key(f"generation:budget:capability:{budget_scope}")
    if global_limit <= 0 or capability_limit <= 0:
        return (
            "global" if global_limit <= 0 else "capability",
            global_key,
            capability_key,
        )

    global_refill_seconds = 60.0 / global_limit
    capability_refill_seconds = 60.0 / capability_limit
    global_refill_ms = max(1, round(global_refill_seconds * 1000))
    capability_refill_ms = max(1, round(capability_refill_seconds * 1000))
    ttl_seconds = 120
    client = _lease_redis()
    try:
        if client is not None:
            result = client.eval(
                _GENERATION_BUDGET_BUCKET_SCRIPT,
                2,
                _lease_key(global_key),
                _lease_key(capability_key),
                int(time.time() * 1000),
                global_limit,
                capability_limit,
                global_refill_ms,
                capability_refill_ms,
                ttl_seconds,
            )
            reason = int(result)
            return (
                ("ok", global_key, capability_key)
                if reason == 0
                else (
                    "global" if reason == 1 else "capability",
                    global_key,
                    capability_key,
                )
            )

        now = time.time()

        def local_state(key: str, capacity: int, refill_seconds: float):
            state = cache.get(key)
            if state is None:
                return float(capacity), now
            try:
                tokens, timestamp = state
                tokens = float(tokens)
                timestamp = float(timestamp)
            except (TypeError, ValueError) as exc:
                raise TypeError("invalid generation budget bucket") from exc
            elapsed = max(0.0, now - timestamp)
            tokens = min(capacity, tokens + elapsed / refill_seconds)
            return tokens, max(timestamp, now)

        with _LOCAL_BUDGET_LOCK:
            global_state = local_state(global_key, global_limit, global_refill_seconds)
            capability_state = local_state(
                capability_key, capability_limit, capability_refill_seconds
            )
            global_tokens, global_timestamp = global_state
            capability_tokens, capability_timestamp = capability_state
            reason = (
                "global"
                if global_tokens < 1
                else "capability"
                if capability_tokens < 1
                else "ok"
            )
            if reason == "ok":
                global_state = (global_tokens - 1, global_timestamp)
                capability_state = (capability_tokens - 1, capability_timestamp)

            # Both writes happen under the same lock. Roll back the first
            # write if the cache fails part-way through so a rejected request
            # cannot consume only one side of the paired budget.
            previous_global = cache.get(global_key)
            cache.set(global_key, global_state, timeout=ttl_seconds)
            try:
                cache.set(capability_key, capability_state, timeout=ttl_seconds)
            except Exception:
                if previous_global is None:
                    cache.delete(global_key)
                else:
                    cache.set(global_key, previous_global, timeout=ttl_seconds)
                raise
            return reason, global_key, capability_key
    except AdmissionUnavailable:
        raise
    except Exception as exc:
        raise AdmissionUnavailable("waitlist admission unavailable") from exc


@dataclass(frozen=True)
class GenerationLease:
    token: str
    slot_key: str
    budget_key: str
    capability_budget_key: str
    global_budget_capacity: int
    capability_budget_capacity: int


def acquire_generation(
    digest: str, *, budget_identity: str | None = None
) -> GenerationLease:
    """Acquire one distributed concurrency and token-budget lease."""

    budget_key = ""
    capability_budget_key = ""
    token = uuid.uuid4().hex
    slot_key = ""
    try:
        max_concurrency = int(
            getattr(settings, "ALLIES_WAITLIST_GENERATION_GLOBAL_CONCURRENCY", 4)
        )
        max_budget = int(
            getattr(
                settings, "ALLIES_WAITLIST_GENERATION_GLOBAL_BUDGET_PER_MINUTE", 100
            )
        )
        capability_budget = int(
            getattr(
                settings,
                "ALLIES_WAITLIST_GENERATION_CAPABILITY_BUDGET_PER_MINUTE",
                5,
            )
        )
        lease_timeout = max(
            30,
            int(
                float(
                    getattr(settings, "ALLIES_WAITLIST_GENERATION_TIMEOUT_SECONDS", 8.0)
                )
            )
            + 30,
        )
        for slot in range(max_concurrency):
            candidate = _cache_key(f"generation:slot:{slot}")
            if _acquire_slot(candidate, token, lease_timeout):
                slot_key = candidate
                break
        if not slot_key:
            raise Throttled("generation concurrency limit reached")
        budget_reason, budget_key, capability_budget_key = _consume_generation_budgets(
            digest,
            global_limit=max_budget,
            capability_limit=capability_budget,
            budget_identity=budget_identity,
        )
        if budget_reason == "global":
            _compare_and_delete(slot_key, token)
            raise Throttled("generation budget exhausted")
        if budget_reason == "capability":
            _compare_and_delete(slot_key, token)
            raise Throttled("generation capability budget exhausted")
        return GenerationLease(
            token=token,
            slot_key=slot_key,
            budget_key=budget_key,
            capability_budget_key=capability_budget_key,
            global_budget_capacity=max_budget,
            capability_budget_capacity=capability_budget,
        )
    except Throttled:
        raise
    except Exception as exc:
        try:
            if slot_key:
                _compare_and_delete(slot_key, token)
        except Exception as cleanup_error:  # noqa: BLE001 - cleanup is best effort
            del cleanup_error
        raise AdmissionUnavailable("waitlist generation admission unavailable") from exc


def _refund_generation_budgets(lease: GenerationLease) -> None:
    """Best-effort atomic refund for a generation with no provider result."""

    if not lease.budget_key or not lease.capability_budget_key:
        return
    try:
        client = _lease_redis()
        if client is not None:
            client.eval(
                _REFUND_GENERATION_BUDGET_SCRIPT,
                2,
                _lease_key(lease.budget_key),
                _lease_key(lease.capability_budget_key),
                lease.global_budget_capacity,
                lease.capability_budget_capacity,
            )
            return

        with _LOCAL_BUDGET_LOCK:
            for key, capacity in (
                (lease.budget_key, lease.global_budget_capacity),
                (lease.capability_budget_key, lease.capability_budget_capacity),
            ):
                state = cache.get(key)
                if state is None:
                    continue
                tokens, timestamp = state
                cache.set(
                    key,
                    (min(float(capacity), float(tokens) + 1), timestamp),
                    timeout=120,
                )
    except Exception:  # noqa: BLE001 - a refund must not strand the lease
        return


def release_generation(lease: GenerationLease, *, refund_budget: bool = False) -> None:
    if refund_budget:
        _refund_generation_budgets(lease)
    try:
        _compare_and_delete(lease.slot_key, lease.token)
    except Exception:  # noqa: BLE001 - lease release is intentionally best effort
        # Lease release is best effort.  TTL bounds a crashed process and the
        # provider result remains protected by the operation receipt.
        return
