import json
import logging

import pytest
from django.test import override_settings

from observability.events import (
    AuditEventFormatter,
    _serialize,
    build_event,
    emit_event,
    emit_suppression_diagnostic,
    emit_task_suppression_diagnostic,
    get_counters,
    normalize_identifier,
    reset_counters,
    should_sample,
)


@pytest.fixture(autouse=True)
def clear_event_counters():
    reset_counters()
    yield
    reset_counters()


def test_build_event_allowlists_and_redacts_sensitive_exception_context():
    event = build_event(
        "http.request",
        request_id="req_safe_123",
        route="/api/v1/items/{item_id}",
        status_code=500,
        outcome="error",
        error_type="providers.ProviderTimeout",
        error_fingerprint=(
            "password=secret-value contact user@example.com "
            "https://internal.example/items?token=secret"
        ),
        headers={"Authorization": "Bearer secret"},
        prompt="private message",
    )

    encoded = json.dumps(event, sort_keys=True)
    assert event["schema_version"] == 1
    assert event["error_type"] == "ProviderTimeout"
    assert event["request_id"] == "req_safe_123"
    assert "secret-value" not in encoded
    assert "user@example.com" not in encoded
    assert "internal.example" not in encoded
    assert "headers" not in event
    assert "prompt" not in event


def test_build_event_rejects_unknown_event_name():
    with pytest.raises(ValueError, match="not allowlisted"):
        build_event("arbitrary.foo")


def test_build_event_normalizes_invalid_and_opaque_identifiers():
    assert normalize_identifier("not safe") is None
    assert normalize_identifier("x" * 129) is None
    opaque = normalize_identifier("tenant-linked-123")
    assert opaque is not None
    assert opaque != "tenant-linked-123"
    assert opaque.startswith("id_")


@override_settings(ALLIES_WIDE_EVENTS_MAX_BYTES=256)
def test_build_event_is_bounded_even_for_large_fields():
    event = build_event(
        "http.request",
        request_id="req_safe",
        route="/" + "x" * 5000,
        method="GET",
        status_code=500,
        outcome="error",
        error_fingerprint="x" * 5000,
    )

    assert len(_serialize(event)) <= 256
    assert event["schema_version"] == 1
    assert event["event"] == "http.request"
    assert event["truncated"] is True


@override_settings(ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE=0)
def test_success_sampling_keeps_errors_and_slow_events():
    success = build_event("http.request", outcome="success", duration_ms=10)
    error = build_event("http.request", outcome="error", duration_ms=10)
    slow = build_event("http.request", outcome="success", duration_ms=1000)

    assert should_sample(success) is False
    assert should_sample(error) is True
    assert should_sample(slow) is True


@override_settings(ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE=0.5)
def test_success_sampling_uses_server_key_when_provided():
    event = build_event("http.request", request_id="client-selected", outcome="success")

    assert should_sample(event, sampling_key="server-a") is False
    assert should_sample(event, sampling_key="server-b") is True


@override_settings(ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE=0.5)
def test_task_lifecycle_events_share_the_task_sampling_bucket():
    task_id = "11111111-1111-4111-8111-111111111111"
    started = build_event("task.started", task_id=task_id, outcome="started")
    succeeded = build_event("task.succeeded", task_id=task_id, outcome="success")

    assert should_sample(started) == should_sample(succeeded)


@override_settings(
    ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE=0.05,
    ALLIES_WIDE_EVENTS_SLOW_MS=1000,
)
def test_slow_task_retention_is_terminal_only_by_contract():
    task_id = "11111111-1111-4111-8111-111111111111"
    started = build_event("task.started", task_id=task_id, outcome="started")
    terminal = build_event(
        "task.succeeded", task_id=task_id, outcome="success", duration_ms=1000
    )

    assert should_sample(started) is False
    assert should_sample(terminal) is True


def test_audit_formatter_keeps_structured_auth_payload_visible():
    record = logging.LogRecord(
        "allies.auth", logging.INFO, __file__, 1, "auth event", (), None
    )
    record.auth_event = {
        "event_name": "auth.refresh.reuse_detected",
        "outcome": "revoked",
    }

    rendered = AuditEventFormatter().format(record)

    assert "INFO allies.auth auth event" in rendered
    assert (
        '{"event_name":"auth.refresh.reuse_detected","outcome":"revoked"}' in rendered
    )


def test_suppression_diagnostic_is_bounded_and_operator_visible(monkeypatch):
    messages = []
    monkeypatch.setattr(
        "observability.events.logger.warning", lambda message: messages.append(message)
    )

    emit_suppression_diagnostic("/" + "x" * 500, 401, 8)

    diagnostic = json.loads(messages[0])
    assert diagnostic == {
        "diagnostic": "wide_event_suppression",
        "reason": "error_burst_limit",
        "route": "/" + "x" * 127,
        "status_code": 401,
        "suppressed_count": 8,
    }


@override_settings(ALLIES_WIDE_EVENTS_ENABLED=False)
def test_suppression_diagnostic_is_disabled_with_wide_events(monkeypatch):
    monkeypatch.setattr(
        "observability.events.logger.warning",
        lambda message: pytest.fail("diagnostic should not write when disabled"),
    )

    emit_suppression_diagnostic("/login", 401, 1)


def test_task_suppression_diagnostic_is_bounded_and_operator_visible(monkeypatch):
    messages = []
    monkeypatch.setattr(
        "observability.events.logger.warning", lambda message: messages.append(message)
    )

    emit_task_suppression_diagnostic("auths.cleanup" + "x" * 500, "failed", 8)

    diagnostic = json.loads(messages[0])
    assert diagnostic == {
        "diagnostic": "wide_event_suppression",
        "reason": "task_error_burst_limit",
        "task_name": "auths.cleanup" + "x" * 115,
        "lifecycle": "failed",
        "suppressed_count": 8,
    }


@override_settings(ALLIES_WIDE_EVENTS_ENABLED=False)
def test_task_suppression_diagnostic_is_disabled_with_wide_events(monkeypatch):
    monkeypatch.setattr(
        "observability.events.logger.warning",
        lambda message: pytest.fail("diagnostic should not write when disabled"),
    )

    emit_task_suppression_diagnostic("auths.cleanup", "failed", 1)


def test_default_success_sampling_rate_is_bounded_for_deployments():
    from config import settings

    assert settings.ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE == 0.05


@override_settings(
    ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE=0,
    ALLIES_WIDE_EVENTS_SLOW_MS=1000,
)
def test_sampling_counters_distinguish_sampled_out_and_emitted():
    assert emit_event("http.request", outcome="success", duration_ms=10) is None
    emitted = emit_event("http.request", outcome="error", status_code=500)

    assert emitted is not None
    assert emitted["sampled"] is True
    assert get_counters() == {
        "events_emitted": 1,
        "events_sampled_out": 1,
        "events_dropped": 0,
    }


def test_fixture_declares_the_python_contract():
    fixture_path = (
        __import__("pathlib").Path(__file__).parents[3]
        / "docs"
        / "contracts"
        / "observability"
        / "wide-event-v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["contract"] == "WideEventV1"
    assert fixture["schema_version"] == 1
    assert {
        "http.request",
        "task.started",
        "task.succeeded",
        "task.failed",
        "task.retried",
    }.issubset(set(fixture["events"]))
    event = build_event("http.request")
    assert set(fixture["required"]).issubset(event)
