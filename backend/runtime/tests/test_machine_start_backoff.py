from datetime import timedelta
from email.utils import format_datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.utils import timezone

from runtime.providers import (
    MachineState,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderRetryableError,
    ProviderTerminalError,
    ProviderTimeoutError,
)
from runtime.services.workspaces import WorkspaceLifecycle


@pytest.fixture
def start_context(monkeypatch):
    elapsed = [0.0]
    delays = []

    def sleep(delay):
        delays.append(delay)
        elapsed[0] += delay

    monkeypatch.setattr(
        "runtime.services.workspaces.time.monotonic", lambda: elapsed[0]
    )
    provider = Mock()
    provider.inspect_machine_by_id.return_value = SimpleNamespace(
        state=MachineState.STOPPED
    )
    provider.wait_machine.return_value = SimpleNamespace(state=MachineState.STARTED)
    lifecycle = WorkspaceLifecycle(provider, sleep=sleep, jitter=False)
    return lifecycle, provider, delays


def test_start_retries_back_off_and_stop_at_deadline(start_context):
    lifecycle, provider, delays = start_context
    error = ProviderRateLimitError("limited")
    provider.start_machine.side_effect = error

    with pytest.raises(ProviderRateLimitError) as caught:
        lifecycle._start_machine_if_needed("app", "machine", 20)

    assert caught.value is error
    assert delays == [1, 2, 4, 8, 5]
    assert provider.start_machine.call_count == 5
    assert provider.inspect_machine_by_id.call_count == 5


@pytest.mark.parametrize("header", ["6", "date"])
def test_start_honors_retry_after(start_context, header):
    lifecycle, provider, delays = start_context
    now = timezone.now().replace(microsecond=0)
    lifecycle.clock = lambda: now
    if header == "date":
        header = format_datetime(now + timedelta(seconds=6))
    provider.start_machine.side_effect = [
        ProviderRateLimitError("limited", details={"retry_after": header}),
        None,
    ]

    lifecycle._start_machine_if_needed("app", "machine", 20)

    assert delays == [6]
    assert provider.start_machine.call_count == 2


def test_retry_after_beyond_deadline_does_not_retry_early(start_context):
    lifecycle, provider, delays = start_context
    provider.start_machine.side_effect = ProviderRateLimitError(
        "limited", details={"retry_after": "60"}
    )
    with pytest.raises(ProviderRateLimitError):
        lifecycle._start_machine_if_needed("app", "machine", 5)
    assert delays == [5]
    provider.start_machine.assert_called_once()


@pytest.mark.parametrize("header", ["garbage", "NaN", "inf", "-5", ""])
def test_invalid_retry_after_uses_backoff(start_context, header):
    lifecycle, provider, delays = start_context
    provider.start_machine.side_effect = [
        ProviderRetryableError("retry", details={"retry_after": header}),
        None,
    ]
    lifecycle._start_machine_if_needed("app", "machine", 10)
    assert delays == [1]


@pytest.mark.parametrize("state", [MachineState.STARTED, MachineState.UNKNOWN])
def test_retry_observes_start_in_progress_without_another_start(start_context, state):
    lifecycle, provider, delays = start_context
    provider.inspect_machine_by_id.side_effect = [
        SimpleNamespace(state=MachineState.STOPPED),
        SimpleNamespace(state=state),
    ]
    provider.start_machine.side_effect = ProviderTimeoutError("uncertain start")
    lifecycle._start_machine_if_needed("app", "machine", 10)
    provider.start_machine.assert_called_once()
    assert delays == [1]


def test_destroyed_machine_during_retry_is_not_started(start_context):
    lifecycle, provider, _ = start_context
    provider.inspect_machine_by_id.side_effect = [
        SimpleNamespace(state=MachineState.STOPPED),
        SimpleNamespace(state=MachineState.DESTROYED),
    ]
    provider.start_machine.side_effect = ProviderRetryableError("retry")
    with pytest.raises(ProviderNotFoundError):
        lifecycle._start_machine_if_needed("app", "machine", 10)
    provider.start_machine.assert_called_once()


def test_transitional_machine_that_starts_during_wait_is_recognized(start_context):
    lifecycle, provider, _ = start_context
    provider.inspect_machine_by_id.side_effect = [
        SimpleNamespace(state=MachineState.UNKNOWN),
        SimpleNamespace(state=MachineState.STARTED),
    ]
    provider.wait_machine.side_effect = ProviderTimeoutError("not stopped")
    lifecycle._start_machine_if_needed("app", "machine", 10)
    provider.start_machine.assert_not_called()
    provider.wait_machine.assert_called_once()


def test_terminal_start_error_is_not_retried(start_context):
    lifecycle, provider, delays = start_context
    provider.start_machine.side_effect = ProviderTerminalError("denied")
    with pytest.raises(ProviderTerminalError):
        lifecycle._start_machine_if_needed("app", "machine", 10)
    provider.start_machine.assert_called_once()
    assert delays == []


def test_expired_deadline_does_not_start_machine(start_context):
    lifecycle, provider, _ = start_context
    with pytest.raises(ProviderTimeoutError):
        lifecycle._start_machine_if_needed("app", "machine", 0)
    provider.start_machine.assert_not_called()


def test_jitter_adds_bounded_delay(start_context, monkeypatch):
    lifecycle, provider, delays = start_context
    lifecycle.jitter = True
    monkeypatch.setattr("runtime.services.workspaces.random.random", lambda: 0.5)
    provider.start_machine.side_effect = [ProviderRetryableError("retry"), None]
    lifecycle._start_machine_if_needed("app", "machine", 10)
    assert delays == [1.125]
