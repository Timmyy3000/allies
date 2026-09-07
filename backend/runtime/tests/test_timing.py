from __future__ import annotations

import pytest

from runtime.services.timing import observed_timing_phase


def test_observed_timing_phase_merges_mutable_terminal_fields(monkeypatch):
    captured = []
    monkeypatch.setenv("ALLIES_OBSERVABILITY_DIGEST_KEY", "test-digest")

    with observed_timing_phase(
        "runtime.wake.machine_state_observation",
        emitter=captured.append,
        provider_resource_id="before",
    ) as terminal:
        terminal.update(provider_resource_id="after", outcome="observed")

    assert captured[0]["event"] == "runtime.operation.started"
    assert captured[-1]["event"] == "runtime.operation.succeeded"
    assert captured[-1]["provider_resource_id"] != captured[0]["provider_resource_id"]
    assert captured[-1]["outcome"] == "observed"


def test_observed_timing_phase_pairs_base_exception_with_failure():
    captured = []

    with (
        pytest.raises(KeyboardInterrupt),
        observed_timing_phase(
            "runtime.wake.machine_start_request",
            emitter=captured.append,
        ),
    ):
        raise KeyboardInterrupt

    assert captured[-1]["event"] == "runtime.operation.failed"
    assert captured[-1]["error_type"] == "KeyboardInterrupt"
