import json
import threading
import time

import pytest

from allies_runtime import observability
from allies_runtime.config import WideEventSettings


@pytest.fixture(autouse=True)
def reset_runtime_observability_configuration():
    dispatcher = observability._STDOUT_DISPATCHER
    queue_size = observability._STDOUT_QUEUE_SIZE
    observability.configure_runtime_observability()
    yield
    observability.configure_runtime_observability()
    observability._STDOUT_DISPATCHER = dispatcher
    observability._STDOUT_QUEUE_SIZE = queue_size


def test_build_event_redacts_payload_and_hashes_tenant_id(monkeypatch):
    monkeypatch.setenv("ALLIES_OBSERVABILITY_DIGEST_KEY", "runtime-test-key")

    event = observability.build_event(
        "runtime.operation.failed",
        workspace_id="workspace-123",
        route="/api/v1/workspaces/123?token=secret",
        message="password=secret alice@example.com https://private.example",
    )

    assert event["workspace_id"].startswith("id_")
    encoded = json.dumps(event)
    assert "alice@example.com" not in encoded
    assert "private.example" not in encoded
    assert "password=secret" not in encoded


def test_build_event_rejects_unknown_name():
    with pytest.raises(ValueError):
        observability.build_event("not-allowlisted")


def test_field_normalization_drops_invalid_values(monkeypatch):
    monkeypatch.setenv("ALLIES_OBSERVABILITY_DIGEST_KEY", "runtime-test-key")

    event = observability.build_event(
        "http.request",
        request_id="bad id",
        route=123,
        status_code=99,
        duration_ms="slow",
        retry_count=-1,
        sampled="yes",
    )

    assert "request_id" not in event
    assert "route" not in event
    assert "status_code" not in event
    assert "duration_ms" not in event
    assert "retry_count" not in event
    assert event["sampled"] is True


def test_serialize_event_bounds_large_message():
    event = observability.build_event("worker.failed", message="x" * 5000)

    encoded = observability.serialize_event(event, max_bytes=512)

    assert len(encoded) <= 512
    assert json.loads(encoded)["schema_version"] == 1


def test_event_strings_match_shared_contract_limit(monkeypatch):
    monkeypatch.setenv("ALLIES_OBSERVABILITY_DIGEST_KEY", "test-digest")
    event = observability.build_event("runtime.operation.failed", message="x" * 512)

    assert len(event["message"]) <= 256


def test_method_is_bounded_at_the_event_boundary():
    event = observability.build_event("http.request", method="x" * 4096)

    assert event["method"] == "X" * 16


def test_serialize_event_rejects_impossibly_small_limit():
    event = observability.build_event("worker.failed")

    with pytest.raises(ValueError, match="exceeds configured"):
        observability.serialize_event(event, max_bytes=20)


def test_invalid_runtime_observability_settings_are_fail_open(monkeypatch):
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_MAX_BYTES", "not-an-int")

    assert observability._settings().max_bytes >= 512


def test_emit_runtime_event_writes_json_and_counts(monkeypatch, capsys):
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_ENABLED", "true")
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE", "1")
    before = observability.event_counters()["events_emitted"]

    observability.emit_runtime_event(observability.build_event("worker.idle"))

    output = ""
    deadline = time.monotonic() + 2
    while not output and time.monotonic() < deadline:
        output = capsys.readouterr().out
        if not output:
            time.sleep(0.005)
    assert json.loads(output)["event"] == "worker.idle"
    assert observability.event_counters()["events_emitted"] == before + 1


def test_runtime_settings_configuration_controls_emission(monkeypatch):
    monkeypatch.delenv("ALLIES_WIDE_EVENTS_ENABLED", raising=False)
    observability.configure_runtime_observability(
        config=WideEventSettings(enabled=False)
    )
    before = observability.event_counters()["events_dropped"]

    observability.emit_runtime_event(observability.build_event("worker.idle"))

    assert observability.event_counters()["events_dropped"] == before + 1


def test_stdout_emission_does_not_flush_synchronously(monkeypatch):
    written = threading.Event()

    class NoFlushStream:
        buffer = None

        def __init__(self):
            self.buffer = self
            self.writes = []

        def write(self, value):
            self.writes.append(value)
            written.set()
            return len(value)

        def flush(self):
            raise AssertionError("wide-event emission must not synchronously flush")

    stream = NoFlushStream()
    monkeypatch.setattr(observability.sys, "stdout", stream)
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_ENABLED", "true")
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE", "1")

    observability.emit_runtime_event(observability.build_event("worker.idle"))

    assert written.wait(2)
    assert len(stream.writes) == 1


def test_stdout_write_blocking_does_not_block_event_caller(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    class BlockingStream:
        buffer = None

        def __init__(self):
            self.buffer = self

        def write(self, value):
            started.set()
            release.wait(2)
            return len(value)

    monkeypatch.setattr(observability.sys, "stdout", BlockingStream())
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_ENABLED", "true")
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE", "1")

    started_at = time.monotonic()
    observability.emit_runtime_event(observability.build_event("worker.idle"))
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.5
    assert started.wait(2)
    release.set()


def test_stdout_queue_drop_is_fail_open(monkeypatch):
    class FullDispatcher:
        def offer(self, envelope):
            return False

    monkeypatch.setattr(observability, "_STDOUT_DISPATCHER", FullDispatcher())
    monkeypatch.setattr(observability, "_STDOUT_QUEUE_SIZE", 128)
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_ENABLED", "true")
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE", "1")
    before = observability.event_counters()["events_dropped"]

    observability.emit_runtime_event(observability.build_event("worker.idle"))

    assert observability.event_counters()["events_dropped"] == before + 1


def test_stdout_dispatcher_close_and_write_failures_are_fail_open(monkeypatch):
    class TextOnlyStream:
        buffer = None

        def __init__(self):
            self.buffer = self

        def write(self, value):
            if isinstance(value, bytes):
                raise TypeError("text stream")
            return len(value)

    monkeypatch.setattr(observability.sys, "stdout", TextOnlyStream())
    assert observability._StdoutDispatcher._write(b"event")

    class BrokenStream:
        buffer = None

        def write(self, value):
            raise OSError("stdout unavailable")

    monkeypatch.setattr(observability.sys, "stdout", BrokenStream())
    assert not observability._StdoutDispatcher._write(b"event")

    dispatcher = observability._StdoutDispatcher(1)
    thread = dispatcher._thread
    dispatcher.close()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert not dispatcher.offer(b"after-close")


def test_stdout_write_failures_are_counted(monkeypatch):
    class BrokenStream:
        buffer = None

        def write(self, _value):
            raise OSError("stdout unavailable")

    dispatcher = observability._StdoutDispatcher(1)
    monkeypatch.setattr(observability, "_STDOUT_DISPATCHER", dispatcher)
    monkeypatch.setattr(observability, "_STDOUT_QUEUE_SIZE", 1)
    monkeypatch.setattr(observability.sys, "stdout", BrokenStream())
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_ENABLED", "true")
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE", "1")

    before = observability.event_counters()["events_write_failures"]
    observability.emit_runtime_event(observability.build_event("worker.failed"))

    deadline = time.monotonic() + 2
    while (
        observability.event_counters()["events_write_failures"] == before
        and time.monotonic() < deadline
    ):
        time.sleep(0.005)
    assert observability.event_counters()["events_write_failures"] >= before + 1
    dispatcher.close()


def test_emit_runtime_event_drops_sampled_success(monkeypatch):
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_ENABLED", "true")
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE", "0")
    before = observability.event_counters()["events_sampled_out"]

    observability.emit_runtime_event(observability.build_event("worker.idle"))

    assert observability.event_counters()["events_sampled_out"] == before + 1


def test_error_rate_limit_drops_client_flood_but_retains_server_evidence(monkeypatch):
    monkeypatch.setattr(
        observability,
        "_ERROR_RATE_LIMITER",
        observability._ErrorRateLimiter(),
    )
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_ENABLED", "true")
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE", "1")
    before_dropped = observability.event_counters()["events_dropped"]
    before_emitted = observability.event_counters()["events_emitted"]

    for _ in range(observability._MAX_CLIENT_ERROR_EVENTS + 4):
        observability.emit_runtime_event(
            observability.build_event(
                "http.request", status_code=401, outcome="error"
            )
        )
    observability.emit_runtime_event(
        observability.build_event("http.request", status_code=500, outcome="error")
    )

    counters = observability.event_counters()
    assert counters["events_dropped"] >= before_dropped + 4
    assert counters["events_emitted"] >= before_emitted + 1


def test_error_rate_limiter_bounds_successful_http_flood(monkeypatch):
    monkeypatch.setattr(
        observability,
        "_ERROR_RATE_LIMITER",
        observability._ErrorRateLimiter(),
    )
    monkeypatch.setattr(observability, "_offer_stdout", lambda *_args, **_kwargs: True)
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_ENABLED", "true")
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE", "1")
    before_dropped = observability.event_counters()["events_dropped"]

    for _ in range(observability._MAX_SUCCESS_EVENTS + 4):
        observability.emit_runtime_event(
            observability.build_event(
                "http.request", status_code=200, outcome="success"
            )
        )

    assert observability.event_counters()["events_dropped"] >= before_dropped + 4


def test_error_rate_limiter_bounds_lifecycle_flood(monkeypatch):
    monkeypatch.setattr(
        observability,
        "_ERROR_RATE_LIMITER",
        observability._ErrorRateLimiter(),
    )
    monkeypatch.setattr(observability, "_offer_stdout", lambda *_args, **_kwargs: True)
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_ENABLED", "true")
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE", "1")
    before_dropped = observability.event_counters()["events_dropped"]

    for _ in range(observability._MAX_LIFECYCLE_EVENTS + 4):
        observability.emit_runtime_event(
            observability.build_event(
                "provider.operation.started", operation="inspect_app", outcome="started"
            )
        )

    assert observability.event_counters()["events_dropped"] >= before_dropped + 4


@pytest.mark.parametrize("status_code", [101, 302])
def test_error_rate_limiter_bounds_other_http_status_flood(monkeypatch, status_code):
    monkeypatch.setattr(
        observability,
        "_ERROR_RATE_LIMITER",
        observability._ErrorRateLimiter(),
    )
    monkeypatch.setattr(observability, "_offer_stdout", lambda *_args, **_kwargs: True)
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_ENABLED", "true")
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE", "1")
    before_dropped = observability.event_counters()["events_dropped"]

    for _ in range(observability._MAX_OTHER_HTTP_EVENTS + 4):
        observability.emit_runtime_event(
            observability.build_event(
                "http.request", status_code=status_code, outcome="success"
            )
        )

    assert observability.event_counters()["events_dropped"] >= before_dropped + 4


def test_sink_failure_is_fail_open(monkeypatch):
    class BrokenSink:
        def offer(self, envelope):
            raise RuntimeError("sink unavailable")

    monkeypatch.setenv("ALLIES_WIDE_EVENTS_ENABLED", "true")
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_SINK_ENABLED", "true")
    observability.configure_runtime_observability(sink=BrokenSink())

    observability.emit_runtime_event(observability.build_event("worker.idle"))

    observability.configure_runtime_observability(sink=None)


def test_disabled_and_rejected_sink_paths_are_counted(monkeypatch):
    before = observability.event_counters()["events_dropped"]
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_ENABLED", "false")
    observability.emit_runtime_event(observability.build_event("worker.idle"))

    class RejectingSink:
        def offer(self, envelope):
            return type("OfferResult", (), {"accepted": False})()

    monkeypatch.setenv("ALLIES_WIDE_EVENTS_ENABLED", "true")
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_SINK_ENABLED", "true")
    monkeypatch.setenv("ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE", "1")
    observability.configure_runtime_observability(sink=RejectingSink())
    observability.emit_runtime_event(observability.build_event("worker.idle"))
    observability.configure_runtime_observability(sink=None)

    assert observability.event_counters()["events_dropped"] >= before + 2
