from types import SimpleNamespace

import pytest
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.urls import path
from django.utils.functional import SimpleLazyObject

from auths.api.common import _new_auth_throttle_cookie
from config.middleware import (
    CANONICAL_CLIENT_ADDRESS_META,
    TrustedProxyHeadersMiddleware,
)
from observability import middleware
from observability.events import get_counters, reset_counters


def _raise_server_error(request):
    raise RuntimeError("password=secret-value")


urlpatterns = [path("observability-error/", _raise_server_error)]


@pytest.fixture(autouse=True)
def reset_error_limiter():
    middleware.reset_error_event_limiter()
    reset_counters()
    yield
    middleware.reset_error_event_limiter()
    reset_counters()


def test_middleware_echoes_safe_request_id_and_emits_one_route_event(monkeypatch):
    emitted = []
    monkeypatch.setattr(
        middleware, "emit_event", lambda kind, **fields: emitted.append((kind, fields))
    )
    request = RequestFactory().get(
        "/api/v1/health?token=secret",
        HTTP_X_REQUEST_ID="req_client_123",
        HTTP_X_CORRELATION_ID="tenant-123",
    )

    response = middleware.WideEventMiddleware(lambda request: HttpResponse("ok"))(
        request
    )

    assert response.status_code == 200
    assert response["X-Request-ID"] == "req_client_123"
    assert len(emitted) == 1
    kind, fields = emitted[0]
    assert kind == "http.request"
    assert fields["route"] == "/api/v1/health"
    assert fields["outcome"] == "success"
    assert fields["request_id"] == "req_client_123"
    assert fields["correlation_id"].startswith("id_")
    assert fields["sampling_key"] != fields["request_id"]
    assert len(fields["sampling_key"]) == 36
    assert "token" not in fields["route"]


def test_middleware_generates_id_and_preserves_view_exception(monkeypatch):
    emitted = []
    monkeypatch.setattr(
        middleware, "emit_event", lambda kind, **fields: emitted.append((kind, fields))
    )
    failure = RuntimeError("password=secret-value")

    def raises(request):
        raise failure

    request = RequestFactory().get("/not-a-route", HTTP_X_REQUEST_ID="bad id")
    with pytest.raises(RuntimeError) as raised:
        middleware.WideEventMiddleware(raises)(request)

    assert raised.value is failure
    assert len(emitted) == 1
    fields = emitted[0][1]
    assert fields["outcome"] == "error"
    assert fields["status_code"] == 500
    assert fields["error_type"] == "RuntimeError"
    assert fields["error_fingerprint"] == "password=secret-value"
    assert " " not in fields["request_id"]


@override_settings(ROOT_URLCONF=__name__)
def test_real_django_chain_captures_converted_view_exception(monkeypatch, client):
    emitted = []
    monkeypatch.setattr(
        middleware, "emit_event", lambda kind, **fields: emitted.append(fields)
    )
    client.raise_request_exception = False

    response = client.get("/observability-error/")

    assert response.status_code == 500
    assert emitted[-1]["outcome"] == "error"
    assert emitted[-1]["status_code"] == 500
    assert emitted[-1]["error_type"] == "RuntimeError"
    assert emitted[-1]["error_fingerprint"] == "password=secret-value"


def test_middleware_sets_error_status_without_replacing_response(monkeypatch):
    emitted = []
    monkeypatch.setattr(
        middleware, "emit_event", lambda kind, **fields: emitted.append(fields)
    )
    response = middleware.WideEventMiddleware(
        lambda request: HttpResponse("bad", status=503)
    )(RequestFactory().get("/api/v1/health"))

    assert response.status_code == 503
    assert response["X-Request-ID"]
    assert emitted[0]["outcome"] == "error"


def test_unauthenticated_error_events_have_a_fixed_route_status_burst(monkeypatch):
    emitted = []
    monkeypatch.setattr(
        middleware,
        "emit_event",
        lambda kind, **fields: emitted.append((kind, fields)),
    )
    handler = middleware.WideEventMiddleware(
        lambda request: HttpResponse("no", status=401)
    )

    for _ in range(6):
        handler(RequestFactory().get("/api/v1/auth/login"))

    assert len(emitted) == 6
    assert get_counters() == {
        "events_emitted": 0,
        "events_sampled_out": 0,
        "events_dropped": 1,
    }


def test_server_error_events_have_a_bounded_per_client_error_burst(monkeypatch):
    emitted = []
    monkeypatch.setattr(
        middleware,
        "emit_event",
        lambda kind, **fields: emitted.append((kind, fields)),
    )
    handler = middleware.WideEventMiddleware(
        lambda request: HttpResponse("server error", status=500)
    )

    for _ in range(6):
        handler(RequestFactory().get("/api/v1/auth/login"))

    assert len(emitted) == 6
    assert get_counters()["events_dropped"] == 1


def test_error_bursts_are_isolated_by_client(monkeypatch):
    emitted = []
    monkeypatch.setattr(
        middleware,
        "emit_event",
        lambda kind, **fields: emitted.append((kind, fields)),
    )
    handler = middleware.WideEventMiddleware(
        lambda request: HttpResponse("no", status=401)
    )

    for _ in range(5):
        handler(RequestFactory().get("/api/v1/auth/login", REMOTE_ADDR="192.0.2.1"))
    handler(RequestFactory().get("/api/v1/auth/login", REMOTE_ADDR="192.0.2.2"))

    assert len(emitted) == 6
    assert get_counters()["events_dropped"] == 0


def test_client_bucket_does_not_resolve_lazy_user_or_session(monkeypatch):
    request = RequestFactory().get(
        "/api/v1/health",
        REMOTE_ADDR="198.51.100.2",
        HTTP_COOKIE="sessionid=database-backed-session",
    )
    request.user = SimpleLazyObject(
        lambda: pytest.fail("observability must not resolve request.user")
    )
    request.META[CANONICAL_CLIENT_ADDRESS_META] = "198.51.100.0/24"

    bucket = middleware._client_bucket(request)

    assert bucket.startswith("id_")


@override_settings(ALLIES_RAILWAY_PROXY_MODE=True)
def test_railway_signed_browser_buckets_isolate_shared_edge(monkeypatch):
    emitted = []
    monkeypatch.setattr(
        middleware,
        "emit_event",
        lambda kind, **fields: emitted.append((kind, fields)),
    )
    handler = TrustedProxyHeadersMiddleware(
        middleware.WideEventMiddleware(lambda request: HttpResponse("no", status=401))
    )
    cookie_a = _new_auth_throttle_cookie()
    cookie_b = _new_auth_throttle_cookie()

    for _ in range(5):
        handler(
            RequestFactory().get(
                "/api/v1/auth/login",
                REMOTE_ADDR="10.0.0.1",
                HTTP_COOKIE=f"allies_throttle={cookie_a}",
            )
        )
    handler(
        RequestFactory().get(
            "/api/v1/auth/login",
            REMOTE_ADDR="10.0.0.1",
            HTTP_COOKIE=f"allies_throttle={cookie_b}",
        )
    )

    assert len(emitted) == 6
    assert get_counters()["events_dropped"] == 0


@override_settings(ALLIES_RAILWAY_PROXY_MODE=True)
def test_railway_session_cookies_cannot_mint_limiter_budgets(monkeypatch):
    emitted = []
    monkeypatch.setattr(
        middleware,
        "emit_event",
        lambda kind, **fields: emitted.append((kind, fields)),
    )
    handler = TrustedProxyHeadersMiddleware(
        middleware.WideEventMiddleware(lambda request: HttpResponse("no", status=401))
    )

    for index in range(6):
        request = RequestFactory().get(
            "/api/v1/auth/login",
            REMOTE_ADDR="10.0.0.1",
            HTTP_COOKIE=f"sessionid=attacker-rotated-{index}",
        )
        handler(request)
    handler(
        RequestFactory().get(
            "/api/v1/auth/login",
            REMOTE_ADDR="10.0.0.1",
            HTTP_COOKIE="sessionid=attacker-rotated-final",
        )
    )

    assert len(emitted) == 6
    assert get_counters()["events_dropped"] == 2


def test_distinct_server_error_fingerprints_are_bounded_by_client_scope(monkeypatch):
    emitted = []
    monkeypatch.setattr(
        middleware,
        "emit_event",
        lambda kind, **fields: emitted.append((kind, fields)),
    )

    def raises(request):
        raise RuntimeError(request.META["HTTP_X_ERROR_MESSAGE"])

    handler = middleware.WideEventMiddleware(raises)

    for index in range(middleware._ERROR_EVENT_5XX_SCOPE_BURST + 1):
        with pytest.raises(RuntimeError):
            handler(
                RequestFactory().get(
                    "/api/v1/auth/login",
                    REMOTE_ADDR="192.0.2.1",
                    HTTP_X_ERROR_MESSAGE=f"error-{index}",
                )
            )

    assert len(emitted) == middleware._ERROR_EVENT_5XX_SCOPE_BURST + 1
    assert emitted[-1][1]["error_fingerprint"] == "error-20"
    assert get_counters()["events_dropped"] == 1


@override_settings(ALLIES_WIDE_EVENTS_ENABLED=False)
def test_disabled_events_skip_limiter_and_suppression_diagnostics(monkeypatch):
    monkeypatch.setattr(
        middleware._error_event_limiter,
        "allow",
        lambda *args, **kwargs: pytest.fail("limiter should not run when disabled"),
    )
    monkeypatch.setattr(
        middleware,
        "emit_suppression_diagnostic",
        lambda *args, **kwargs: pytest.fail("diagnostic should not run when disabled"),
    )
    handler = middleware.WideEventMiddleware(
        lambda request: HttpResponse("no", status=401)
    )

    for _ in range(6):
        response = handler(RequestFactory().get("/api/v1/auth/login"))

    assert response.status_code == 401
    assert get_counters() == {
        "events_emitted": 0,
        "events_sampled_out": 0,
        "events_dropped": 0,
    }


def test_rate_limit_events_are_burst_limited(monkeypatch):
    emitted = []
    monkeypatch.setattr(
        middleware,
        "emit_event",
        lambda kind, **fields: emitted.append((kind, fields)),
    )

    def limited(request):
        response = HttpResponse("limited", status=429)
        response._allies_rate_limit_reason = "send_rate_limited"
        return response

    handler = middleware.WideEventMiddleware(limited)
    for _ in range(middleware._ERROR_EVENT_BURST + 1):
        handler(RequestFactory().post("/api/v1/chat/messages"))

    assert len(emitted) == middleware._ERROR_EVENT_BURST
    assert all(kind == "chat.rate_limited" for kind, _ in emitted)
    assert get_counters()["events_dropped"] == 1


def test_suppression_diagnostics_are_emitted_at_bounded_count_steps(monkeypatch):
    diagnostics = []
    monkeypatch.setattr(middleware, "emit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        middleware,
        "emit_suppression_diagnostic",
        lambda route, status, count: diagnostics.append((route, status, count)),
    )
    handler = middleware.WideEventMiddleware(
        lambda request: HttpResponse("no", status=401)
    )

    for _ in range(13):
        handler(RequestFactory().get("/api/v1/auth/login"))

    assert diagnostics == [
        ("<unmatched>", 401, 1),
        ("<unmatched>", 401, 2),
        ("<unmatched>", 401, 4),
        ("<unmatched>", 401, 8),
    ]


def test_error_events_are_limited_for_authenticated_requests(monkeypatch):
    emitted = []
    monkeypatch.setattr(
        middleware,
        "emit_event",
        lambda kind, **fields: emitted.append((kind, fields)),
    )
    handler = middleware.WideEventMiddleware(
        lambda request: HttpResponse("no", status=403)
    )

    for _ in range(6):
        request = RequestFactory().get("/api/v1/auth/login")
        request.user = SimpleNamespace(is_authenticated=True)
        handler(request)

    assert len(emitted) == 6
    assert get_counters()["events_dropped"] == 1


def test_error_limiter_resets_at_window_boundary_and_keys_route_status():
    limiter = middleware._ErrorEventLimiter()

    assert all(
        limiter.allow("/one", 401, "client-a", "client-error", now=0) for _ in range(5)
    )
    assert limiter.allow("/one", 401, "client-a", "client-error", now=0) is False
    assert limiter.allow("/one", 403, "client-a", "client-error", now=0) is True
    assert limiter.allow("/two", 401, "client-a", "client-error", now=0) is True
    assert limiter.allow("/one", 401, "client-a", "client-error", now=60) is True
    assert limiter.allow("/one", 500, "client-a", "error-a", now=0) is True
    assert limiter.allow("/one", 500, "client-a", "error-b", now=0) is True
