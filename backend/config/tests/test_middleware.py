import json

from django.http import HttpResponse
from django.middleware.security import SecurityMiddleware
from django.test import RequestFactory, override_settings

from config.middleware import TrustedProxyHeadersMiddleware


def _header_echo(request):
    from django.http import JsonResponse

    return JsonResponse(
        {
            "for": request.META.get("HTTP_X_FORWARDED_FOR"),
            "host": request.META.get("HTTP_X_FORWARDED_HOST"),
            "proto": request.META.get("HTTP_X_FORWARDED_PROTO"),
        }
    )


@override_settings(ALLIES_TRUSTED_PROXY_IPS=[])
def test_untrusted_peer_cannot_supply_forwarded_headers():
    request = RequestFactory().get(
        "/",
        REMOTE_ADDR="203.0.113.10",
        HTTP_X_FORWARDED_FOR="198.51.100.2",
        HTTP_X_FORWARDED_HOST="evil.example",
        HTTP_X_FORWARDED_PROTO="https",
    )

    response = TrustedProxyHeadersMiddleware(_header_echo)(request)

    assert json.loads(response.content) == {"for": None, "host": None, "proto": None}


@override_settings(ALLIES_TRUSTED_PROXY_IPS=["10.0.0.8"])
def test_trusted_peer_preserves_forwarded_headers():
    request = RequestFactory().get(
        "/",
        REMOTE_ADDR="10.0.0.8",
        HTTP_X_FORWARDED_FOR="198.51.100.2",
        HTTP_X_FORWARDED_HOST="cloud.example",
        HTTP_X_FORWARDED_PROTO="https",
    )

    response = TrustedProxyHeadersMiddleware(_header_echo)(request)

    assert json.loads(response.content) == {
        "for": "198.51.100.2",
        "host": "cloud.example",
        "proto": "https",
    }


@override_settings(ALLIES_RAILWAY_PROXY_MODE=True, ALLIES_TRUSTED_PROXY_IPS=[])
def test_railway_mode_trusts_only_exact_https_protocol():
    request = RequestFactory().get(
        "/",
        REMOTE_ADDR="203.0.113.10",
        HTTP_X_FORWARDED_FOR="198.51.100.2",
        HTTP_X_FORWARDED_HOST="evil.example",
        HTTP_X_FORWARDED_PROTO="https",
    )

    response = TrustedProxyHeadersMiddleware(_header_echo)(request)

    assert json.loads(response.content) == {
        "for": None,
        "host": None,
        "proto": "https",
    }


@override_settings(ALLIES_RAILWAY_PROXY_MODE=True, ALLIES_TRUSTED_PROXY_IPS=[])
def test_railway_mode_strips_non_https_forwarded_protocol():
    request = RequestFactory().get(
        "/", REMOTE_ADDR="203.0.113.10", HTTP_X_FORWARDED_PROTO="http,https"
    )

    response = TrustedProxyHeadersMiddleware(_header_echo)(request)

    assert json.loads(response.content)["proto"] == "http"


@override_settings(
    ALLIES_RAILWAY_PROXY_MODE=True,
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    SECURE_SSL_REDIRECT=True,
    SECURE_REDIRECT_EXEMPT=[],
)
def test_railway_security_middleware_redirects_plain_http_before_header_cleanup():
    request = RequestFactory().get(
        "/",
        REMOTE_ADDR="203.0.113.10",
        HTTP_X_FORWARDED_PROTO="http",
    )

    response = TrustedProxyHeadersMiddleware(
        SecurityMiddleware(lambda request: HttpResponse("ok"))
    )(request)

    assert response.status_code == 301
    assert response["Location"] == "https://testserver/"


@override_settings(
    ALLIES_RAILWAY_PROXY_MODE=True,
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    SECURE_SSL_REDIRECT=True,
    SECURE_REDIRECT_EXEMPT=[],
)
def test_railway_security_middleware_rejects_comma_separated_protocol():
    request = RequestFactory().get(
        "/",
        REMOTE_ADDR="203.0.113.10",
        HTTP_X_FORWARDED_PROTO="https,http",
    )

    response = TrustedProxyHeadersMiddleware(
        SecurityMiddleware(lambda request: HttpResponse("ok"))
    )(request)

    assert response.status_code == 301
    assert response["Location"] == "https://testserver/"
