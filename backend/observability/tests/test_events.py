import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import Http404, HttpResponse
from django.test import Client, RequestFactory
from django.test.utils import override_settings
from django.urls import Resolver404, path

from observability import events as events_module
from observability.events import (
    ALLOWED_EVENT_NAMES,
    MAX_COLLECTION_ITEMS,
    build_event,
    identifier_fingerprint,
    serialize_event,
)
from observability.middleware import WideEventMiddleware, current_request_id
from observability.settings import MAX_WIDE_EVENT_BYTES


def _raise_runtime_error(_request):
    raise RuntimeError("boom")


urlpatterns = [path("raise/", _raise_runtime_error)]


def test_event_is_allowlisted_and_redacts_sensitive_text(monkeypatch):
    monkeypatch.setenv("ALLIES_OBSERVABILITY_DIGEST_KEY", "test-digest-key")

    event = build_event(
        "http.request",
        request_id="req_123",
        workspace_id="workspace-123",
        route="/api/v1/workspaces/123?token=secret",
        message="password=secret alice@example.com https://private.example/x",
    )

    assert event["request_id"] == "req_123"
    assert event["workspace_id"].startswith("id_")
    assert "alice@example.com" not in json.dumps(event)
    assert "private.example" not in json.dumps(event)
    assert "token=secret" not in json.dumps(event)


def test_tenant_identifier_is_omitted_without_digest_key(monkeypatch):
    monkeypatch.delenv("ALLIES_OBSERVABILITY_DIGEST_KEY", raising=False)
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)

    assert identifier_fingerprint("workspace-123") is None


def test_serialized_event_respects_byte_bound():
    event = build_event("runtime.operation.failed", operation="profile_turn", error_type="RuntimeError")

    encoded = serialize_event(event, max_bytes=512)

    assert len(encoded) <= 512
    assert json.loads(encoded)["schema_version"] == 1


def test_event_strings_match_shared_contract_limit(monkeypatch):
    monkeypatch.setenv("ALLIES_OBSERVABILITY_DIGEST_KEY", "test-digest")
    event = build_event("runtime.operation.failed", message="x" * 512)

    assert len(event["message"]) <= 256


def test_method_is_bounded_at_the_event_boundary():
    event = build_event("http.request", method="x" * 4096)

    assert event["method"] == "X" * 16


def test_event_implementation_conforms_to_shared_contract():
    contract = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "docs/contracts/observability/wide-event-v1.json"
        ).read_text()
    )
    assert ALLOWED_EVENT_NAMES <= set(contract["events"])
    assert MAX_COLLECTION_ITEMS == contract["limits"]["max_collection_items"]
    assert MAX_WIDE_EVENT_BYTES == contract["limits"]["max_event_bytes"]

    event = build_event(
        "task.started",
        task_name="runtime.tasks.profile_turn",
        task_id="task_123",
        queue="default",
        outcome="started",
    )
    encoded = json.loads(serialize_event(event))
    assert set(contract["required"]) <= set(encoded)
    assert set(encoded) <= set(contract["required"]) | set(contract["optional"])


def test_middleware_emits_request_event_and_propagates_request_id(monkeypatch):
    factory = RequestFactory()
    captured = []

    def response(request):
        assert current_request_id() == "req_client"
        return HttpResponse(status=202)

    middleware = WideEventMiddleware(response)
    request = factory.get(
        "/api/v1/workspaces/123?secret=hidden", HTTP_X_REQUEST_ID="req_client"
    )
    monkeypatch.setattr(
        "observability.middleware.emit_event",
        lambda event, **kwargs: captured.append(event),
    )

    result = middleware(request)

    assert result.status_code == 202
    assert result["X-Request-ID"] == "req_client"
    assert current_request_id() is None
    assert captured[0]["event"] == "http.request"
    assert captured[0]["outcome"] == "success"
    assert captured[0]["status_code"] == 202
    assert captured[0]["request_id"] == "req_client"
    assert captured[0]["route"].endswith("/:id")


def test_middleware_uses_resolved_route_template(monkeypatch):
    captured = []

    def response(_request):
        return HttpResponse(status=200)

    request = RequestFactory().get("/workspaces/0123456789abcdef")
    request.resolver_match = SimpleNamespace(
        route="api/v1/workspaces/<uuid:workspace_id>/"
    )
    monkeypatch.setattr(
        "observability.middleware.emit_event",
        lambda event, **kwargs: captured.append(event),
    )

    WideEventMiddleware(response)(request)

    assert captured[0]["route"] == "/api/v1/workspaces/:workspace_id/"


def test_middleware_emits_error_event_and_re_raises(monkeypatch):
    captured = []

    def response(_request):
        raise ValueError("boom")

    monkeypatch.setattr(
        "observability.middleware.emit_event",
        lambda event, **kwargs: captured.append(event),
    )

    with pytest.raises(ValueError, match="boom"):
        WideEventMiddleware(response)(RequestFactory().get("/api/v1/fail"))

    assert captured[0]["event"] == "http.request"
    assert captured[0]["outcome"] == "error"
    assert captured[0]["status_code"] == 500
    assert captured[0]["error_type"] == "ValueError"


def test_django_exception_response_echoes_request_id_after_conversion(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "observability.middleware.emit_event",
        lambda event, **kwargs: captured.append(event),
    )

    response = Client().get(
        "/not-found",
        HTTP_HOST="localhost",
        HTTP_X_REQUEST_ID="req_chain",
    )

    assert response.status_code == 404
    assert response["X-Request-ID"] == "req_chain"
    assert captured[0]["status_code"] == 404


@override_settings(DEBUG=False, ROOT_URLCONF=__name__)
def test_django_uncaught_exception_response_echoes_request_id(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "observability.middleware.emit_event",
        lambda event, **kwargs: captured.append(event),
    )

    response = Client(raise_request_exception=False).get(
        "/raise/",
        HTTP_HOST="localhost",
        HTTP_X_REQUEST_ID="req_exception",
    )

    assert response.status_code == 500
    assert response["X-Request-ID"] == "req_exception"
    assert captured[0]["status_code"] == 500


@pytest.mark.parametrize("supplied", ["bad id", "x" * 129])
def test_middleware_replaces_invalid_or_oversized_request_id(monkeypatch, supplied):
    captured = []
    monkeypatch.setattr(
        "observability.middleware.emit_event",
        lambda event, **kwargs: captured.append(event),
    )

    response = WideEventMiddleware(
        lambda _request: HttpResponse(status=200)
    )(RequestFactory().get("/healthz", HTTP_X_REQUEST_ID=supplied))

    generated = response["X-Request-ID"]
    assert generated != supplied
    assert generated.startswith("req_")
    assert len(generated) <= 128
    assert captured[0]["request_id"] == generated


@pytest.mark.parametrize(
    ("error_type", "status_code"),
    [
        (Http404, 404),
        (Resolver404, 404),
        (PermissionDenied, 403),
        (SuspiciousOperation, 400),
    ],
)
def test_middleware_maps_framework_errors_to_client_status(
    monkeypatch, error_type, status_code
):
    captured = []

    def response(_request):
        raise error_type()

    monkeypatch.setattr(
        "observability.middleware.emit_event",
        lambda event, **kwargs: captured.append(event),
    )

    with pytest.raises(error_type):
        WideEventMiddleware(response)(RequestFactory().get("/api/v1/fail"))

    assert captured[0]["status_code"] == status_code


def test_error_rate_limit_drops_client_flood_but_retains_server_evidence(
    monkeypatch,
):
    monkeypatch.setattr(events_module, "_error_rate_limiter", events_module._ErrorRateLimiter())
    config = events_module.FoundryObservabilitySettings(success_sample_rate=1)
    before_dropped = events_module.event_counters()["events_dropped"]
    before_emitted = events_module.event_counters()["events_emitted"]

    for _ in range(events_module._MAX_CLIENT_ERROR_EVENTS + 4):
        events_module.emit_event(
            events_module.build_event(
                "http.request", status_code=401, outcome="error"
            ),
            config=config,
        )
    events_module.emit_event(
        events_module.build_event("http.request", status_code=500, outcome="error"),
        config=config,
    )

    counters = events_module.event_counters()
    assert counters["events_dropped"] >= before_dropped + 4
    assert counters["events_emitted"] >= before_emitted + 1


def test_error_rate_limiter_bounds_successful_http_flood(monkeypatch):
    monkeypatch.setattr(events_module, "_error_rate_limiter", events_module._ErrorRateLimiter())
    monkeypatch.setattr(
        events_module,
        "_offer_stdout",
        lambda *_args, **_kwargs: events_module.OfferResult(
            accepted=True, dropped=False
        ),
    )
    config = events_module.FoundryObservabilitySettings(success_sample_rate=1)
    before_dropped = events_module.event_counters()["events_dropped"]

    for _ in range(events_module._MAX_SUCCESS_EVENTS + 4):
        events_module.emit_event(
            events_module.build_event(
                "http.request", status_code=200, outcome="success"
            ),
            config=config,
        )

    assert events_module.event_counters()["events_dropped"] >= before_dropped + 4


def test_error_rate_limiter_bounds_lifecycle_flood(monkeypatch):
    monkeypatch.setattr(events_module, "_error_rate_limiter", events_module._ErrorRateLimiter())
    monkeypatch.setattr(
        events_module,
        "_offer_stdout",
        lambda *_args, **_kwargs: events_module.OfferResult(
            accepted=True, dropped=False
        ),
    )
    config = events_module.FoundryObservabilitySettings(success_sample_rate=1)
    before_dropped = events_module.event_counters()["events_dropped"]

    for _ in range(events_module._MAX_LIFECYCLE_EVENTS + 4):
        events_module.emit_event(
            events_module.build_event(
                "provider.operation.started", operation="inspect_app", outcome="started"
            ),
            config=config,
        )

    assert events_module.event_counters()["events_dropped"] >= before_dropped + 4


@pytest.mark.parametrize("status_code", [101, 302])
def test_error_rate_limiter_bounds_other_http_status_flood(monkeypatch, status_code):
    monkeypatch.setattr(events_module, "_error_rate_limiter", events_module._ErrorRateLimiter())
    monkeypatch.setattr(
        events_module,
        "_offer_stdout",
        lambda *_args, **_kwargs: events_module.OfferResult(
            accepted=True, dropped=False
        ),
    )
    config = events_module.FoundryObservabilitySettings(success_sample_rate=1)
    before_dropped = events_module.event_counters()["events_dropped"]

    for _ in range(events_module._MAX_OTHER_HTTP_EVENTS + 4):
        events_module.emit_event(
            events_module.build_event(
                "http.request", status_code=status_code, outcome="success"
            ),
            config=config,
        )

    assert events_module.event_counters()["events_dropped"] >= before_dropped + 4


def test_stdout_write_failures_are_counted(monkeypatch):
    class BrokenStream:
        buffer = None

        def write(self, _value):
            raise OSError("stdout unavailable")

    monkeypatch.setattr(events_module.sys, "stdout", BrokenStream())
    with events_module._stdout_lock:
        if events_module._stdout_dispatcher is not None:
            events_module._stdout_dispatcher.close()
        events_module._stdout_dispatcher = None
        events_module._stdout_queue_size = None

    before = events_module.event_counters()["events_write_failures"]
    events_module.emit_event(
        events_module.build_event("worker.failed", outcome="error"),
        config=events_module.FoundryObservabilitySettings(success_sample_rate=1),
    )

    deadline = time.monotonic() + 2
    while (
        events_module.event_counters()["events_write_failures"] == before
        and time.monotonic() < deadline
    ):
        time.sleep(0.005)
    assert events_module.event_counters()["events_write_failures"] >= before + 1
