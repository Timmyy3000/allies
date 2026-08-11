import pytest
from django.core.cache import cache

from auths.throttle import ThrottleExceeded, check_rate_limit


@pytest.mark.django_db
def test_cache_throttle_is_bounded_and_keyed():
    cache.clear()
    check_rate_limit(scope="test", identity="same", limit=1, period=60)
    with pytest.raises(ThrottleExceeded):
        check_rate_limit(scope="test", identity="same", limit=1, period=60)
    # A different identity receives an independent keyed bucket.
    check_rate_limit(scope="test", identity="other", limit=1, period=60)
