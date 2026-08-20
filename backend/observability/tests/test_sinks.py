import threading
import time

from observability import events
from observability.settings import FoundryObservabilitySettings
from observability.sinks import BoundedSinkDispatcher, OfferResult


def _wait_for(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    assert predicate()


def test_full_queue_increments_drop_counter():
    started = threading.Event()
    release = threading.Event()

    class BlockingSink:
        def offer(self, envelope):
            started.set()
            release.wait(2)
            return OfferResult(accepted=True, dropped=False)

    dispatcher = BoundedSinkDispatcher(
        BlockingSink(), max_queue_size=1, enabled=True
    )
    assert dispatcher.offer(b"first").accepted
    _wait_for(started.is_set)
    assert dispatcher.offer(b"queued").accepted
    dropped = dispatcher.offer(b"overflow")
    assert dropped.dropped
    assert dispatcher.dropped == 1
    release.set()
    dispatcher.close()


def test_adapter_exception_isolated_and_worker_survives():
    calls = []
    finished = threading.Event()

    class FailingOnceSink:
        def offer(self, envelope):
            calls.append(envelope)
            if len(calls) == 1:
                raise RuntimeError("adapter unavailable")
            finished.set()
            return OfferResult(accepted=True, dropped=False)

    dispatcher = BoundedSinkDispatcher(FailingOnceSink(), enabled=True)
    assert dispatcher.offer(b"first").accepted
    assert dispatcher.offer(b"second").accepted
    _wait_for(finished.is_set)
    assert len(calls) == 2
    assert dispatcher.dropped == 1
    assert dispatcher.failed == 1
    dispatcher.close()


def test_close_terminates_worker_and_rejects_later_offers():
    class Sink:
        def offer(self, envelope):
            return OfferResult(accepted=True, dropped=False)

    dispatcher = BoundedSinkDispatcher(Sink(), enabled=True)
    thread = dispatcher._thread
    assert thread is not None and thread.is_alive()
    dispatcher.close()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert dispatcher.offer(b"after-close") == OfferResult(
        accepted=False, dropped=False
    )


def test_stdout_write_isolated_from_event_caller(monkeypatch):
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

    monkeypatch.setattr(events.sys, "stdout", BlockingStream())
    started_at = time.monotonic()
    events.emit_event(
        events.build_event("worker.idle", outcome="success"),
        config=FoundryObservabilitySettings(success_sample_rate=1),
    )

    assert time.monotonic() - started_at < 0.5
    assert started.wait(2)
    release.set()
