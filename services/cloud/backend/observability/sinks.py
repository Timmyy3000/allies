"""Non-blocking, bounded sink seam for a future collector adapter."""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Protocol

_logger = logging.getLogger("allies.observability.sink")


@dataclass(frozen=True, slots=True)
class OfferResult:
    accepted: bool
    dropped: bool


class EventSink(Protocol):
    def offer(self, envelope: bytes) -> OfferResult:
        """Offer immutable, already-bounded bytes without waiting on I/O."""


class NullSink:
    def offer(self, envelope: bytes) -> OfferResult:
        return OfferResult(accepted=False, dropped=False)


class SinkDispatcher:
    """A daemon worker drains a bounded queue into an optional adapter."""

    def __init__(
        self,
        adapter: EventSink | None = None,
        *,
        max_queue_size: int = 256,
        start_worker: bool = True,
    ) -> None:
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be positive")
        self.adapter = adapter or NullSink()
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=max_queue_size)
        self._closed = threading.Event()
        self._thread: threading.Thread | None = None
        if start_worker:
            self._thread = threading.Thread(
                target=self._run,
                name="allies-observability-sink",
                daemon=True,
            )
            self._thread.start()

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def offer(self, envelope: bytes) -> OfferResult:
        if self._closed.is_set():
            return OfferResult(accepted=False, dropped=True)
        if not isinstance(envelope, bytes):
            try:
                envelope = bytes(envelope)
            except (TypeError, ValueError):
                return OfferResult(accepted=False, dropped=True)
        try:
            self._queue.put_nowait(envelope)
        except queue.Full:
            return OfferResult(accepted=False, dropped=True)
        return OfferResult(accepted=True, dropped=False)

    def drain_once(self) -> bool:
        try:
            envelope = self._queue.get_nowait()
        except queue.Empty:
            return False
        try:
            self.adapter.offer(envelope)
        except Exception:  # noqa: BLE001 - adapters are outside the app failure domain.
            _logger.debug("observability sink offer failed", exc_info=False)
        finally:
            self._queue.task_done()
        return True

    def _run(self) -> None:
        while not self._closed.is_set():
            try:
                envelope = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self.adapter.offer(envelope)
            except Exception:  # noqa: BLE001 - adapters are outside the app failure domain.
                _logger.debug("observability sink offer failed", exc_info=False)
            finally:
                self._queue.task_done()

    def close(self) -> None:
        self._closed.set()
