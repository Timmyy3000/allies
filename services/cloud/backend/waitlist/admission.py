"""Bounded distributed admission for the single waitlist AI operation."""

from dataclasses import dataclass
from uuid import uuid4

from django.conf import settings
from django.core.cache import cache

from .exceptions import AdmissionUnavailable, Throttled


@dataclass(frozen=True)
class GenerationLease:
    slot_key: str
    token: str


def _key(value: str) -> str:
    return f"allies:waitlist:{value}"


def _consume_budget(identity: str) -> None:
    limit = int(
        getattr(settings, "ALLIES_WAITLIST_GENERATION_ATTEMPT_BUDGET_PER_MINUTE", 5)
    )
    key = _key(f"generation:budget:{identity}")
    if cache.add(key, 1, timeout=60):
        return
    try:
        if cache.incr(key) > limit:
            raise Throttled("generation budget exhausted")
    except ValueError as exc:
        raise AdmissionUnavailable("waitlist admission unavailable") from exc


def acquire_generation(identity: str) -> GenerationLease:
    token = uuid4().hex
    timeout = max(
        30, int(getattr(settings, "ALLIES_WAITLIST_GENERATION_TIMEOUT_SECONDS", 8)) + 30
    )
    slots = int(getattr(settings, "ALLIES_WAITLIST_GENERATION_GLOBAL_CONCURRENCY", 4))
    for index in range(slots):
        slot_key = _key(f"generation:slot:{index}")
        if cache.add(slot_key, token, timeout=timeout):
            try:
                _consume_budget(identity)
            except Exception:
                cache.delete(slot_key)
                raise
            return GenerationLease(slot_key=slot_key, token=token)
    raise Throttled("generation concurrency limit reached")


def release_generation(lease: GenerationLease) -> None:
    if cache.get(lease.slot_key) == lease.token:
        cache.delete(lease.slot_key)
