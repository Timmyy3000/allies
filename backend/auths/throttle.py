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
    limit: int,
    period: int,
    cache_backend=None,
) -> None:
    """Increment one bounded counter, failing closed when cache is unavailable."""

    if limit < 1 or period < 1:
        raise ValueError("invalid throttle configuration")
    key = _cache_key(scope, identity)
    throttle_cache = cache if cache_backend is None else cache_backend
    try:
        if throttle_cache.add(key, 1, timeout=period):
            return
        count = throttle_cache.incr(key)
    except Exception as exc:
        raise ThrottleUnavailable("auth throttle cache unavailable") from exc
    if count > limit:
        raise ThrottleExceeded("auth operation throttled")
