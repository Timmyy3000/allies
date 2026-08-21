"""Small cache-backed abuse controls for browser auth operations."""

from __future__ import annotations

import hashlib
import hmac

from django.core.cache import cache

from auths.config import digest_key


class ThrottleExceeded(Exception):
    pass


class ThrottleUnavailable(Exception):
    pass


def _cache_key(scope: str, identity: str) -> str:
    digest = hmac.new(digest_key(), identity.encode(), hashlib.sha256).hexdigest()[:24]
    return f"allies:auth:throttle:{scope}:{digest}"


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
) -> None:
    """Increment one bounded counter, failing closed when cache is unavailable."""

    if (limit is not None and limit < 1) or period < 1:
        raise ValueError("invalid throttle configuration")
    throttle_cache = cache if cache_backend is None else cache_backend
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
