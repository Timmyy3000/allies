from types import SimpleNamespace

import pytest
from celery import signals
from django.test import override_settings

import observability.celery as lifecycle
from observability.events import get_counters, reset_counters


def _task(task_id="11111111-1111-4111-8111-111111111111", retries=0):
    request = SimpleNamespace(
        id=task_id,
        retries=retries,
        delivery_info={"routing_key": "cloud"},
        headers={"correlation_id": "22222222-2222-4222-8222-222222222222"},
    )
    return SimpleNamespace(name="auths.cleanup", request=request)


def test_worker_task_lifecycle_is_deduplicated_and_duration_is_recorded(monkeypatch):
    emitted = []
    monkeypatch.setattr(lifecycle, "_is_worker_or_beat", lambda: True)
    monkeypatch.setattr(
        lifecycle, "emit_event", lambda kind, **fields: emitted.append((kind, fields))
    )
    lifecycle.reset_state()
    task = _task()
    sender = SimpleNamespace(name="auths.cleanup")
    ticks = iter((10.0, 10.125))
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: next(ticks))

    lifecycle.on_task_prerun(sender=sender, task_id=task.request.id, task=task)
    lifecycle.on_task_prerun(sender=sender, task_id=task.request.id, task=task)
    lifecycle.on_task_postrun(
        sender=sender, task_id=task.request.id, task=task, state="SUCCESS"
    )
    lifecycle.on_task_postrun(
        sender=sender, task_id=task.request.id, task=task, state="SUCCESS"
    )

    assert [kind for kind, _ in emitted] == ["task.started", "task.succeeded"]
    assert emitted[0][1]["task_id"] == task.request.id
    assert emitted[0][1]["queue"] == "cloud"
    assert emitted[1][1]["duration_ms"] == 125


def test_worker_retry_and_failure_events_are_distinct(monkeypatch):
    emitted = []
    monkeypatch.setattr(lifecycle, "_is_worker_or_beat", lambda: True)
    monkeypatch.setattr(
        lifecycle, "emit_event", lambda kind, **fields: emitted.append((kind, fields))
    )
    lifecycle.reset_state()
    task = _task(retries=1)
    lifecycle.on_task_retry(
        sender=task, request=task.request, reason=RuntimeError("private")
    )
    lifecycle.on_task_retry(
        sender=task, request=task.request, reason=RuntimeError("private")
    )
    lifecycle.on_task_failure(
        sender=task,
        task_id=task.request.id,
        task=task,
        exception=RuntimeError("password=secret"),
    )

    assert [kind for kind, _ in emitted] == ["task.retried", "task.failed"]
    assert emitted[0][1]["retry_count"] == 1
    assert emitted[1][1]["error_type"] == "RuntimeError"


def test_worker_failure_events_are_bounded_with_one_representative(monkeypatch):
    emitted = []
    diagnostics = []
    monkeypatch.setattr(lifecycle, "_is_worker_or_beat", lambda: True)
    monkeypatch.setattr(
        lifecycle, "emit_event", lambda kind, **fields: emitted.append((kind, fields))
    )
    monkeypatch.setattr(
        lifecycle,
        "emit_task_suppression_diagnostic",
        lambda *args: diagnostics.append(args),
    )
    lifecycle.reset_state()
    reset_counters()

    for index in range(lifecycle._TASK_ERROR_BURST + 2):
        task = _task(task_id=f"11111111-1111-4111-8111-{index:012d}")
        lifecycle.on_task_failure(
            sender=task,
            task_id=task.request.id,
            task=task,
            exception=RuntimeError("provider unavailable"),
        )

    assert len(emitted) == lifecycle._TASK_ERROR_BURST + 1
    assert diagnostics == [
        ("auths.cleanup", "failed", 1),
        ("auths.cleanup", "failed", 2),
    ]
    assert get_counters()["events_dropped"] == 2


def test_worker_retry_events_are_bounded_with_one_representative(monkeypatch):
    emitted = []
    monkeypatch.setattr(lifecycle, "_is_worker_or_beat", lambda: True)
    monkeypatch.setattr(
        lifecycle, "emit_event", lambda kind, **fields: emitted.append((kind, fields))
    )
    lifecycle.reset_state()
    reset_counters()

    for index in range(lifecycle._TASK_ERROR_BURST + 2):
        task = _task(task_id=f"33333333-3333-4333-8333-{index:012d}", retries=1)
        lifecycle.on_task_retry(
            sender=task, request=task.request, reason=RuntimeError("retryable")
        )

    assert len(emitted) == lifecycle._TASK_ERROR_BURST + 1
    assert get_counters()["events_dropped"] == 2


@override_settings(ALLIES_WIDE_EVENTS_ENABLED=False)
def test_disabled_events_skip_task_limiter_and_diagnostics(monkeypatch):
    monkeypatch.setattr(lifecycle, "_is_worker_or_beat", lambda: True)
    monkeypatch.setattr(
        lifecycle._task_error_limiter,
        "allow",
        lambda *args, **kwargs: pytest.fail(
            "task limiter should not run when disabled"
        ),
    )
    monkeypatch.setattr(
        lifecycle,
        "emit_task_suppression_diagnostic",
        lambda *args, **kwargs: pytest.fail("diagnostic should not run when disabled"),
    )
    lifecycle.reset_state()
    reset_counters()
    task = _task()

    lifecycle.on_task_failure(
        sender=task,
        task_id=task.request.id,
        task=task,
        exception=RuntimeError("provider unavailable"),
    )
    lifecycle.on_task_retry(
        sender=task, request=task.request, reason=RuntimeError("retryable")
    )

    assert get_counters() == {
        "events_emitted": 0,
        "events_sampled_out": 0,
        "events_dropped": 0,
    }


def test_malformed_retry_metadata_defaults_to_zero(monkeypatch):
    emitted = []
    monkeypatch.setattr(lifecycle, "_is_worker_or_beat", lambda: True)
    monkeypatch.setattr(
        lifecycle, "emit_event", lambda kind, **fields: emitted.append((kind, fields))
    )
    lifecycle.reset_state()
    task = _task(retries="not-a-number")

    lifecycle.on_task_prerun(sender=task, task_id=task.request.id, task=task)

    assert emitted[0][1]["retry_count"] == 0


@override_settings(ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE=0)
def test_started_and_succeeded_use_success_sampling(monkeypatch):
    monkeypatch.setattr(lifecycle, "_is_worker_or_beat", lambda: True)
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(
        "observability.events.logger.info", lambda *args, **kwargs: None
    )
    lifecycle.reset_state()
    reset_counters()
    task = _task()

    lifecycle.on_task_prerun(sender=task, task_id=task.request.id, task=task)
    lifecycle.on_task_postrun(
        sender=task, task_id=task.request.id, task=task, state="SUCCESS"
    )

    assert get_counters() == {
        "events_emitted": 0,
        "events_sampled_out": 2,
        "events_dropped": 0,
    }


@override_settings(
    ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE=0,
    ALLIES_WIDE_EVENTS_SLOW_MS=1000,
)
def test_slow_task_retains_terminal_event_when_start_is_sampled_out(monkeypatch):
    monkeypatch.setattr(lifecycle, "_is_worker_or_beat", lambda: True)
    monkeypatch.setattr(
        "observability.events.logger.info", lambda *args, **kwargs: None
    )
    lifecycle.reset_state()
    reset_counters()
    task = _task()
    ticks = iter((10.0, 11.0))
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: next(ticks))

    lifecycle.on_task_prerun(sender=task, task_id=task.request.id, task=task)
    lifecycle.on_task_postrun(
        sender=task, task_id=task.request.id, task=task, state="SUCCESS"
    )

    assert get_counters() == {
        "events_emitted": 1,
        "events_sampled_out": 1,
        "events_dropped": 0,
    }


def test_real_celery_signals_reuse_prerun_context_for_terminal_events(monkeypatch):
    emitted = []
    monkeypatch.setattr(lifecycle, "_is_worker_or_beat", lambda: True)
    monkeypatch.setattr(
        lifecycle, "emit_event", lambda kind, **fields: emitted.append((kind, fields))
    )
    lifecycle.reset_state()
    ticks = iter((10.0, 10.25, 20.0, 20.5, 20.5))
    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: next(ticks))
    first = _task(retries=2)
    second = _task(task_id="33333333-3333-4333-8333-333333333333", retries=3)
    first_terminal = SimpleNamespace(name=first.name, request=None)
    second_terminal = SimpleNamespace(name=second.name, request=None)
    dispatch_uid = "observability-test-real-signals"
    signals.task_prerun.connect(
        lifecycle.on_task_prerun, weak=False, dispatch_uid=dispatch_uid
    )
    signals.task_postrun.connect(
        lifecycle.on_task_postrun, weak=False, dispatch_uid=dispatch_uid
    )
    signals.task_failure.connect(
        lifecycle.on_task_failure, weak=False, dispatch_uid=dispatch_uid
    )
    try:
        signals.task_prerun.send(
            sender=first.name, task_id=first.request.id, task=first
        )
        signals.task_postrun.send(
            sender=first.name,
            task_id=first.request.id,
            task=first_terminal,
            state="SUCCESS",
        )
        signals.task_postrun.send(
            sender=first.name,
            task_id=first.request.id,
            task=first_terminal,
            state="SUCCESS",
        )
        signals.task_prerun.send(
            sender=second.name, task_id=second.request.id, task=second
        )
        signals.task_failure.send(
            sender=second.name,
            task_id=second.request.id,
            task=second_terminal,
            exception=RuntimeError("provider unavailable"),
        )
    finally:
        signals.task_prerun.disconnect(
            lifecycle.on_task_prerun, dispatch_uid=dispatch_uid
        )
        signals.task_postrun.disconnect(
            lifecycle.on_task_postrun, dispatch_uid=dispatch_uid
        )
        signals.task_failure.disconnect(
            lifecycle.on_task_failure, dispatch_uid=dispatch_uid
        )

    assert [kind for kind, _ in emitted] == [
        "task.started",
        "task.succeeded",
        "task.started",
        "task.failed",
    ]
    assert emitted[1][1]["retry_count"] == 2
    assert emitted[1][1]["correlation_id"] == first.request.headers["correlation_id"]
    assert emitted[1][1]["duration_ms"] == 250
    assert emitted[3][1]["retry_count"] == 3
    assert emitted[3][1]["correlation_id"] == second.request.headers["correlation_id"]
