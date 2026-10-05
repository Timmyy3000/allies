from unittest.mock import patch
from uuid import uuid4

import pytest

from allies.services.timing import readiness_phase
from observability.events import build_event, should_sample


def test_phase_reports_monotonic_duration_and_preserves_failure():
    failure = TimeoutError("token=private https://private.example")
    correlation = str(uuid4())
    with (
        patch("allies.services.timing.monotonic", side_effect=[10, 10.25]),
        patch("allies.services.timing.emit_event") as emit,
        pytest.raises(TimeoutError) as caught,
        readiness_phase("wake.forward", correlation_id=correlation),
    ):
        raise failure
    assert caught.value is failure
    assert emit.call_args.args == ("runtime.operation.failed",)
    assert emit.call_args.kwargs == {
        "operation": "wake.forward",
        "duration_ms": 250,
        "error_type": "TimeoutError",
        "correlation_id": correlation,
    }
    assert "private" not in str(emit.call_args_list)


def test_phase_reports_success():
    with (
        patch("allies.services.timing.monotonic", side_effect=[10, 10.125]),
        patch("allies.services.timing.emit_event") as emit,
        readiness_phase("provisioning.profile_roundtrip"),
    ):
        pass
    assert emit.call_args.args == ("runtime.operation.succeeded",)
    assert emit.call_args.kwargs["duration_ms"] == 125


def test_timing_event_hashes_resource_identity_and_drops_content(settings):
    settings.SECRET_KEY = "test-only-observability-key"
    workspace, resource, correlation = (str(uuid4()) for _ in range(3))
    event = build_event(
        "runtime.operation.succeeded",
        operation="readiness.hint_received",
        workspace_id=workspace,
        resource_id=resource,
        correlation_id=correlation,
        prompt="private prompt",
    )
    assert event["workspace_id"].startswith("id_")
    assert event["resource_id"].startswith("id_")
    assert event["correlation_id"] == correlation
    assert workspace not in str(event) and resource not in str(event)
    assert "prompt" not in event


def test_short_readiness_steps_are_retained_with_http_sampling_disabled(settings):
    settings.ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE = 0
    event = build_event(
        "runtime.operation.succeeded", operation="wake.forward", duration_ms=2
    )
    assert should_sample(event)
    assert event["outcome"] == "success"
    failed = build_event("runtime.operation.failed", operation="wake.forward")
    assert failed["outcome"] == "error"
    assert should_sample(failed)
