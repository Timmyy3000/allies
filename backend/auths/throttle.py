"""Small cache-backed abuse controls for browser auth operations."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from django.core.cache import cache

from auths.config import digest_key


class ThrottleExceeded(Exception):
    pass


class ThrottleUnavailable(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RateLimitReservation:
    scope: str
    identity: str
    token: str
    period: int
    cache_backend: object


def _cache_key(scope: str, identity: str) -> str:
    digest = hmac.new(digest_key(), identity.encode(), hashlib.sha256).hexdigest()[:24]
    return f"allies:auth:throttle:{scope}:{digest}"


def reserve_rate_limit(
    *,
    scope: str,
    identity: str,
    reservation_key: str,
    limit: int,
    period: int,
    cache_backend=None,
) -> RateLimitReservation:
    """Increment a bucket once for a deterministic reservation token."""

    if limit < 1 or period < 1:
        raise ValueError("invalid throttle configuration")
    throttle_cache = cache if cache_backend is None else cache_backend
    marker_key = _cache_key(f"{scope}:reservation", f"{identity}:{reservation_key}")
    count_key = _cache_key(scope, identity)
    marker_created = False
    try:
        marker_created = throttle_cache.add(marker_key, 1, timeout=period)
        if not marker_created:
            raise ThrottleUnavailable("auth throttle reservation unavailable")
        if not throttle_cache.add(count_key, 1, timeout=period):
            count = throttle_cache.incr(count_key)
            if count > limit:
                throttle_cache.delete(marker_key)
                marker_created = False
                raise ThrottleExceeded("auth operation throttled")
        return RateLimitReservation(
            scope, identity, reservation_key, period, throttle_cache
        )
    except ThrottleExceeded:
        raise
    except Exception as exc:
        if marker_created:
            try:
                throttle_cache.delete(marker_key)
            except Exception:  # noqa: BLE001, S110 - preserve fail-closed behavior.
                pass
        raise ThrottleUnavailable("auth throttle cache unavailable") from exc


def reconcile_rate_limit(reservation: RateLimitReservation, *, committed: bool) -> None:
    """Clear a failed request marker while retaining its fail-closed quota count."""

    if committed:
        return
    marker_key = _cache_key(
        f"{reservation.scope}:reservation",
        f"{reservation.identity}:{reservation.token}",
    )
    try:
        reservation.cache_backend.delete(marker_key)
    except Exception:  # noqa: BLE001 - retained quota remains fail-closed.
        return


def check_rate_limit(
    *,
    scope: str,
    identity: str,
    limit: int | None,
    period: int,
    cache_backend=None,
    global_limit: int | None = None,
    global_period: int | None = None,
    global_scope: str | None = None,
    reservation_key: str | None = None,
) -> RateLimitReservation | None:
    """Increment one bounded counter, failing closed when cache is unavailable."""

    if (limit is not None and limit < 1) or period < 1:
        raise ValueError("invalid throttle configuration")
    throttle_cache = cache if cache_backend is None else cache_backend
    if reservation_key is not None:
        if global_limit is not None:
            raise ValueError("reservations do not support global limits")
        return reserve_rate_limit(
            scope=scope,
            identity=identity,
            reservation_key=reservation_key,
            limit=limit if limit is not None else 1,
            period=period,
            cache_backend=throttle_cache,
        )
    try:
        key = _cache_key(scope, identity)
        if limit is not None and not throttle_cache.add(key, 1, timeout=period):
            count = throttle_cache.incr(key)
            if count > limit:
                raise ThrottleExceeded("auth operation throttled")
        if global_limit is not None:
            if global_limit < 1:
                raise ValueError("invalid global throttle configuration")
            global_window = period if global_period is None else global_period
            if global_window < 1:
                raise ValueError("invalid global throttle configuration")
            global_key = _cache_key(global_scope or f"{scope}:global", "all")
            if not throttle_cache.add(global_key, 1, timeout=global_window):
                global_count = throttle_cache.incr(global_key)
                if global_count > global_limit:
                    raise ThrottleExceeded("auth operation throttled")
    except Exception as exc:
        if isinstance(exc, ThrottleExceeded):
            raise
        raise ThrottleUnavailable("auth throttle cache unavailable") from exc
