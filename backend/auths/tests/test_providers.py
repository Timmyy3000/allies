import base64
import hashlib
import time
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import override_settings

from auths.exceptions import ProviderRejected
from auths.providers.base import ProviderFlow, ProviderKey, VerifiedIdentity
from auths.providers.google import GoogleProvider


@override_settings(
    ALLIES_AUTH_GOOGLE_CLIENT_ID="client-id",
    ALLIES_AUTH_GOOGLE_REDIRECT_URI="https://cloud.example/callback",
    ALLIES_AUTH_GOOGLE_AUTHORIZATION_ENDPOINT="https://accounts.google.com/o/oauth2/v2/auth",
)
def test_google_uses_s256_pkce_challenge():
    verifier = "verifier-value"
    url = GoogleProvider().authorization_url(
        ProviderFlow(
            provider=ProviderKey.GOOGLE,
            state="state",
            nonce="nonce",
            redirect_uri="https://cloud.example/callback",
            pkce_verifier=verifier,
        )
    )
    query = parse_qs(urlparse(url).query)
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert query["code_challenge"] == [expected]
    assert query["code_challenge_method"] == ["S256"]


def test_verified_email_provenance_is_google_only():
    with pytest.raises(ProviderRejected):
        VerifiedIdentity(
            provider=ProviderKey.FAKE.value,
            subject="fake-subject",
            email="person@example.com",
            email_verified=True,
            email_verification_source="google",
        )


@pytest.mark.django_db
@override_settings(
    ALLIES_AUTH_GOOGLE_CLIENT_ID="client-id",
    ALLIES_AUTH_GOOGLE_CLIENT_SECRET="client-secret",
    ALLIES_AUTH_GOOGLE_REDIRECT_URI="https://cloud.example/callback",
)
def test_google_callback_normalizes_verified_identity_and_rejects_claim_failures(
    monkeypatch,
):
    provider = GoogleProvider()
    discovery = {
        "issuer": "https://accounts.google.com",
        "token_endpoint": "https://accounts.google.com/token",
        "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
    }
    monkeypatch.setattr(provider, "_discovery", lambda flow=None: discovery)
    monkeypatch.setattr(
        provider, "_fetch_json", lambda *args, **kwargs: {"id_token": "signed"}
    )
    flow = ProviderFlow(
        ProviderKey.GOOGLE,
        "state",
        "nonce",
        "https://cloud.example/callback",
        "verifier",
    )
    # Use a current iat in the fixture so the adapter's skew check passes.
    import time

    monkeypatch.setattr(
        provider,
        "_decode_id_token",
        lambda token, payload, flow=None: {
            "iss": "https://accounts.google.com",
            "aud": "client-id",
            "sub": "google-sub",
            "nonce": "nonce",
            "iat": time.time(),
            "exp": time.time() + 600,
            "email": "person@example.com",
            "email_verified": True,
            "name": "Person",
        },
    )
    identity = provider.verify_callback("authorization-code", flow)
    assert identity.subject == "google-sub"
    assert identity.email == "person@example.com"
    monkeypatch.setattr(
        provider,
        "_decode_id_token",
        lambda token, payload, flow=None: {"sub": "x", "nonce": "wrong"},
    )
    with pytest.raises(ProviderRejected):
        provider.verify_callback("authorization-code", flow)


@override_settings(ALLIES_AUTH_GOOGLE_CLIENT_ID="client-id")
def test_google_rejects_http_endpoints_and_bad_discovery(monkeypatch):
    provider = GoogleProvider()
    with pytest.raises(ProviderRejected):
        provider._https_url("http://insecure")
    monkeypatch.setattr(
        provider,
        "_fetch_json",
        lambda *args, **kwargs: {"issuer": "https://evil.example"},
    )
    with pytest.raises(ProviderRejected):
        provider._discovery()


def test_google_fetch_json_bounds_and_decode_fail_closed(monkeypatch):
    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            return self.body[:size]

    provider = GoogleProvider()
    monkeypatch.setattr(
        "auths.providers.google.urlopen",
        lambda request, timeout: Response(b'{"ok": true}'),
    )
    assert provider._fetch_json("https://example.test") == {"ok": True}
    monkeypatch.setattr(
        "auths.providers.google.urlopen", lambda request, timeout: Response(b"not-json")
    )
    with pytest.raises(ProviderRejected):
        provider._fetch_json("https://example.test")
    monkeypatch.setattr(
        "auths.providers.google.urlopen",
        lambda request, timeout: Response(b"x" * 1_000_001),
    )
    with pytest.raises(ProviderRejected):
        provider._fetch_json("https://example.test")
    with pytest.raises(ProviderRejected):
        provider._decode_id_token(
            "not-a-jwt", {"jwks_uri": "https://example.test/jwks"}
        )


def test_google_jwks_cache_is_populated_with_uri_and_value(monkeypatch):
    import jwt

    cache_calls = []
    jwk_set = object()

    class Cache:
        def get(self, key):
            del key

        def put(self, *args):
            cache_calls.append(args)

    def init(client, uri, **kwargs):
        client.uri = uri
        client.jwk_set_cache = Cache()

    def get_signing_key(client, token):
        del token
        assert client.fetch_data() is jwk_set
        raise RuntimeError("stop after cache write")

    monkeypatch.setattr(jwt.PyJWKClient, "__init__", init)
    monkeypatch.setattr(jwt.PyJWKClient, "get_signing_key_from_jwt", get_signing_key)
    monkeypatch.setattr(jwt.api_jwk.PyJWKSet, "from_dict", lambda payload: jwk_set)
    provider = GoogleProvider()
    monkeypatch.setattr(
        provider,
        "_fetch_json",
        lambda *args, **kwargs: {"keys": [{"kid": "test"}]},
    )

    with pytest.raises(ProviderRejected, match="id token invalid"):
        provider._decode_id_token(
            "signed-token", {"jwks_uri": "https://example.test/jwks"}
        )

    assert cache_calls == [("https://example.test/jwks", jwk_set)]


def test_google_provider_bounds_http_timeout_by_flow_deadline(monkeypatch):
    class Response:
        def __init__(self):
            self.body = b'{"ok": true}'
            self.offset = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            chunk = self.body[self.offset : self.offset + size]
            self.offset += len(chunk)
            return chunk

    observed = []
    monkeypatch.setattr(
        "auths.providers.google.urlopen",
        lambda request, timeout: observed.append(timeout) or Response(),
    )
    flow = ProviderFlow(
        ProviderKey.GOOGLE,
        "state",
        "nonce",
        "https://cloud.example/callback",
        "verifier",
        deadline_monotonic=time.monotonic() + 1,
    )

    assert GoogleProvider()._fetch_json("https://example.test", flow=flow) == {
        "ok": True
    }
    assert 0 < observed[0] <= 1

    expired_flow = ProviderFlow(
        ProviderKey.GOOGLE,
        "state",
        "nonce",
        "https://cloud.example/callback",
        "verifier",
        deadline_monotonic=time.monotonic() - 1,
    )
    with pytest.raises(ProviderRejected, match="timed out"):
        GoogleProvider()._fetch_json("https://example.test", flow=expired_flow)


def test_google_provider_stops_slow_stream_at_absolute_deadline(monkeypatch):
    class SlowResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            time.sleep(0.02)
            return b"x"

    monkeypatch.setattr(
        "auths.providers.google.urlopen",
        lambda request, timeout: SlowResponse(),
    )
    flow = ProviderFlow(
        ProviderKey.GOOGLE,
        "state",
        "nonce",
        "https://cloud.example/callback",
        "verifier",
        deadline_monotonic=time.monotonic() + 0.05,
    )

    started = time.monotonic()
    with pytest.raises(ProviderRejected, match="timed out"):
        GoogleProvider()._fetch_json("https://example.test", flow=flow)
    assert time.monotonic() - started < 0.5


@pytest.mark.parametrize(
    "claims",
    [
        {},
        {"sub": "subject", "nonce": "wrong", "iat": time.time()},
        {"sub": "subject", "nonce": "nonce", "iat": time.time() - 2_000},
    ],
)
@override_settings(
    ALLIES_AUTH_GOOGLE_CLIENT_ID="client-id",
    ALLIES_AUTH_GOOGLE_CLIENT_SECRET="client-secret",
    ALLIES_AUTH_GOOGLE_REDIRECT_URI="https://cloud.example/callback",
)
def test_google_callback_claim_rejection_matrix(monkeypatch, claims):
    provider = GoogleProvider()
    monkeypatch.setattr(
        provider,
        "_discovery",
        lambda flow=None: {
            "issuer": "https://accounts.google.com",
            "token_endpoint": "https://accounts.google.com/token",
            "jwks_uri": "https://www.googleapis.com/certs",
        },
    )
    monkeypatch.setattr(
        provider, "_fetch_json", lambda *args, **kwargs: {"id_token": "signed"}
    )
    monkeypatch.setattr(
        provider,
        "_decode_id_token",
        lambda token, discovery, flow=None: claims,
    )
    flow = ProviderFlow(
        ProviderKey.GOOGLE,
        "state",
        "nonce",
        "https://cloud.example/callback",
        "verifier",
    )
    with pytest.raises(ProviderRejected):
        provider.verify_callback("code", flow)


@pytest.mark.parametrize(
    "issuer", ["https://accounts.google.com", "accounts.google.com"]
)
@override_settings(
    ALLIES_AUTH_GOOGLE_CLIENT_ID="client-id",
    ALLIES_AUTH_GOOGLE_CLIENT_SECRET="client-secret",
    ALLIES_AUTH_GOOGLE_REDIRECT_URI="https://cloud.example/callback",
)
def test_google_accepts_both_documented_issuers(monkeypatch, issuer):
    provider = GoogleProvider()
    monkeypatch.setattr(
        provider,
        "_discovery",
        lambda flow=None: {
            "issuer": issuer,
            "token_endpoint": "https://accounts.google.com/token",
            "jwks_uri": "https://www.googleapis.com/certs",
        },
    )
    monkeypatch.setattr(
        provider, "_fetch_json", lambda *args, **kwargs: {"id_token": "signed"}
    )
    monkeypatch.setattr(
        provider,
        "_decode_id_token",
        lambda token, discovery, flow=None: {
            "iss": issuer,
            "aud": "client-id",
            "sub": "subject",
            "nonce": "nonce",
            "iat": time.time(),
        },
    )
    identity = provider.verify_callback(
        "code",
        ProviderFlow(
            ProviderKey.GOOGLE,
            "state",
            "nonce",
            "https://cloud.example/callback",
            "verifier",
        ),
    )
    assert identity.issuer == issuer


@pytest.mark.parametrize(
    ("audience", "authorized_party"),
    [
        (["client-id", "other-client"], None),
        (["client-id", "other-client"], "other-client"),
        ("client-id", "other-client"),
        (["other-client"], "client-id"),
    ],
)
@override_settings(
    ALLIES_AUTH_GOOGLE_CLIENT_ID="client-id",
    ALLIES_AUTH_GOOGLE_CLIENT_SECRET="client-secret",
    ALLIES_AUTH_GOOGLE_REDIRECT_URI="https://cloud.example/callback",
)
def test_google_rejects_ambiguous_or_mismatched_audience(
    monkeypatch, audience, authorized_party
):
    provider = GoogleProvider()
    monkeypatch.setattr(
        provider,
        "_discovery",
        lambda flow=None: {
            "issuer": "https://accounts.google.com",
            "token_endpoint": "https://accounts.google.com/token",
            "jwks_uri": "https://www.googleapis.com/certs",
        },
    )
    monkeypatch.setattr(
        provider, "_fetch_json", lambda *args, **kwargs: {"id_token": "signed"}
    )
    monkeypatch.setattr(
        provider,
        "_decode_id_token",
        lambda token, discovery, flow=None: {
            "iss": "https://accounts.google.com",
            "aud": audience,
            "azp": authorized_party,
            "sub": "subject",
            "nonce": "nonce",
            "iat": time.time(),
        },
    )
    with pytest.raises(ProviderRejected, match="audience"):
        provider.verify_callback(
            "code",
            ProviderFlow(
                ProviderKey.GOOGLE,
                "state",
                "nonce",
                "https://cloud.example/callback",
                "verifier",
            ),
        )
