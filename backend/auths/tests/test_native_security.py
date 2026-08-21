import pytest
from django.test import RequestFactory, override_settings

from auths.api.common import check_native_rate_limit, native_rate_limit_identity
from auths.exceptions import NativeIdentityUnavailable
from auths.throttle import ThrottleExceeded, check_rate_limit


def test_native_railway_identity_uses_only_x_real_ip_and_normalizes_prefixes():
    factory = RequestFactory()
    with override_settings(ALLIES_RAILWAY_PROXY_MODE=True, ALLIES_TRUSTED_PROXY_IPS=[]):
        request = factory.post(
            "/",
            REMOTE_ADDR="10.0.0.8",
            HTTP_X_REAL_IP="198.51.100.73",
            HTTP_X_FORWARDED_FOR="203.0.113.9",
            HTTP_FORWARDED="for=203.0.113.9",
            HTTP_X_ALLIES_CLIENT_ID="client-selected-id",
        )
        assert native_rate_limit_identity(request) == "198.51.100.0/24"

        ipv6_request = factory.post(
            "/",
            REMOTE_ADDR="10.0.0.8",
            HTTP_X_REAL_IP="2001:db8:abcd:1234:5678::9",
        )
        assert native_rate_limit_identity(ipv6_request) == "2001:db8:abcd:1234::/64"


@pytest.mark.parametrize(
    "header_value",
    ["", "not-an-ip", "198.51.100.1, 198.51.100.2"],
)
def test_native_railway_identity_fails_closed_for_missing_or_ambiguous_headers(
    header_value,
):
    request_kwargs = {"REMOTE_ADDR": "10.0.0.8"}
    if header_value:
        request_kwargs["HTTP_X_REAL_IP"] = header_value
    with override_settings(ALLIES_RAILWAY_PROXY_MODE=True, ALLIES_TRUSTED_PROXY_IPS=[]):
        request = RequestFactory().post("/", **request_kwargs)
        with pytest.raises(NativeIdentityUnavailable):
            native_rate_limit_identity(request)


def test_native_non_railway_fixture_uses_remote_addr_only():
    request = RequestFactory().post(
        "/",
        REMOTE_ADDR="198.51.100.73",
        HTTP_X_REAL_IP="203.0.113.11",
        HTTP_X_FORWARDED_FOR="203.0.113.12",
    )
    with override_settings(ALLIES_RAILWAY_PROXY_MODE=False):
        assert native_rate_limit_identity(request) == "198.51.100.0/24"


def test_native_rate_limit_passes_normalized_identity_to_shared_helper(monkeypatch):
    captured = {}

    def capture(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("auths.api.common.check_rate_limit", capture)
    request = RequestFactory().post(
        "/",
        REMOTE_ADDR="198.51.100.73",
    )
    with override_settings(
        ALLIES_RAILWAY_PROXY_MODE=False,
        ALLIES_AUTH_NATIVE_REFRESH_LIMIT=20,
        ALLIES_AUTH_NATIVE_RATE_LIMIT_PERIOD_SECONDS=60,
        ALLIES_AUTH_NATIVE_GLOBAL_LIMIT=1000,
    ):
        assert check_native_rate_limit(request, "refresh") == "198.51.100.0/24"
    assert captured == {
        "scope": "native-refresh",
        "identity": "198.51.100.0/24",
        "limit": 20,
        "period": 60,
        "global_limit": 1000,
        "global_period": 60,
        "global_scope": "native-global",
    }


class MemoryCache:
    def __init__(self):
        self.values = {}

    def add(self, key, value, timeout):
        del timeout
        if key in self.values:
            return False
        self.values[key] = value
        return True

    def incr(self, key):
        self.values[key] += 1
        return self.values[key]


def test_native_global_ceiling_is_shared_across_operations():
    cache = MemoryCache()
    check_rate_limit(
        scope="native-sign_in",
        identity="198.51.100.0/24",
        limit=100,
        period=60,
        cache_backend=cache,
        global_limit=2,
        global_period=60,
        global_scope="native-global",
    )
    check_rate_limit(
        scope="native-refresh",
        identity="203.0.113.0/24",
        limit=100,
        period=60,
        cache_backend=cache,
        global_limit=2,
        global_period=60,
        global_scope="native-global",
    )
    with pytest.raises(ThrottleExceeded):
        check_rate_limit(
            scope="native-logout",
            identity="192.0.2.0/24",
            limit=100,
            period=60,
            cache_backend=cache,
            global_limit=2,
            global_period=60,
            global_scope="native-global",
        )
    assert len([key for key in cache.values if "native-global" in key]) == 1
