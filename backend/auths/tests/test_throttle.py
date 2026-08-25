import pytest
from django.core.cache import cache

from auths.throttle import (
    ThrottleExceeded,
    ThrottleUnavailable,
    check_rate_limit,
    reconcile_rate_limit,
    reserve_rate_limit,
)


@pytest.mark.django_db
def test_cache_throttle_is_bounded_and_keyed():
    cache.clear()
    check_rate_limit(scope="test", identity="same", limit=1, period=60)
    with pytest.raises(ThrottleExceeded):
        check_rate_limit(scope="test", identity="same", limit=1, period=60)
    # A different identity receives an independent keyed bucket.
    check_rate_limit(scope="test", identity="other", limit=1, period=60)


@pytest.mark.django_db
def test_failed_reservation_reconciliation_stays_fail_closed(monkeypatch):
    cache.clear()
    reservation = reserve_rate_limit(
        scope="chat-send",
        identity="workspace:user",
        reservation_key="same-send",
        limit=2,
        period=60,
    )

    monkeypatch.setattr(reservation.cache_backend, "delete", lambda _key: 0)
    reconcile_rate_limit(reservation, committed=False)

    with pytest.raises(ThrottleUnavailable):
        reserve_rate_limit(
            scope="chat-send",
            identity="workspace:user",
            reservation_key="same-send",
            limit=2,
            period=60,
        )
