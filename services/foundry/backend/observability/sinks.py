"""A narrow asynchronous, bounded and fail-open sink seam."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OfferResult:
    accepted: bool
    dropped: bool


class EventSink(Protocol):
    """Future adapters receive only an immutable serialized JSON envelope."""

    def offer(self, envelope: bytes) -> OfferResult: ...


class NoopSink:
    def offer(self, envelope: bytes) -> OfferResult:
        return OfferResult(accepted=False, dropped=False)


class BoundedSinkDispatcher:
    """Offer bytes without blocking the request or runtime call path."""

    def __init__(
        self,
        sink: EventSink | None = None,
        *,
        max_queue_size: int = 128,
        enabled: bool = False,
        on_write_failure: Callable[[], None] | None = None,
    ) -> None:
        if type(max_queue_size) is not int or not 1 <= max_queue_size <= 4096:
            raise ValueError("max_queue_size must be between 1 and 4096")
        self.sink = sink or NoopSink()
        self.enabled = bool(enabled and sink is not None)
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=max_queue_size)
        self._dropped = 0
        self._failed = 0
        self._on_write_failure = on_write_failure
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._thread: threading.Thread | None = None
        if self.enabled:
            self._thread = threading.Thread(
                target=self._drain,
                name="foundry-observability-sink",
                daemon=True,
            )
            self._thread.start()

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped

    @property
    def failed(self) -> int:
        """Number of queued envelopes rejected by the sink adapter."""

        with self._lock:
            return self._failed

    def _drop(self) -> OfferResult:
        with self._lock:
            self._dropped += 1
        return OfferResult(accepted=False, dropped=True)

    def _fail(self) -> OfferResult:
        with self._lock:
            self._dropped += 1
            self._failed += 1
        if self._on_write_failure is not None:
            try:
                self._on_write_failure()
            except Exception:  # noqa: BLE001 - diagnostics must not kill the worker
                return OfferResult(accepted=False, dropped=True)
        return OfferResult(accepted=False, dropped=True)

    def offer(self, envelope: bytes) -> OfferResult:
        if not self.enabled or self._closed.is_set():
            return OfferResult(accepted=False, dropped=False)
        if not isinstance(envelope, bytes):
            return self._drop()
        try:
            self._queue.put_nowait(bytes(envelope))
        except queue.Full:
            return self._drop()
        return OfferResult(accepted=True, dropped=False)

    def _drain(self) -> None:
        while True:
            envelope = self._queue.get()
            try:
                if envelope is None:
                    return
                try:
                    result = self.sink.offer(envelope)
                    if not isinstance(result, OfferResult) or not result.accepted:
                        self._fail()
                except Exception:  # noqa: BLE001 - adapter failures are isolated
                    self._fail()
            finally:
                self._queue.task_done()
            if self._closed.is_set():
                return

    def close(self) -> None:
        """Stop the best-effort worker without waiting for adapter I/O."""

        if self._thread is None:
            return
        self._closed.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            # The worker will finish its current item and observe the closed
            # flag before taking another queued envelope.
            return
        self._thread = None


AsyncEventSinkDispatcher = BoundedSinkDispatcher
SinkDispatcher = BoundedSinkDispatcher


__all__ = [
    "AsyncEventSinkDispatcher",
    "BoundedSinkDispatcher",
    "EventSink",
    "NoopSink",
    "OfferResult",
    "SinkDispatcher",
]
