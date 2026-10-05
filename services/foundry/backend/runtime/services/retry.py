from __future__ import annotations

from collections.abc import Callable
from time import monotonic_ns, sleep

from django.db import OperationalError

from runtime.exceptions import RuntimeConflictError

_LOCK_BACKOFF_SECONDS = (0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56)
_MAX_LOCK_RETRIES = len(_LOCK_BACKOFF_SECONDS) + 1


def run_with_sqlite_lock_retry[T](operation: Callable[[], T]) -> T:
    """Retry bounded SQLite/transaction locks around a whole transaction."""

    for retry_index in range(_MAX_LOCK_RETRIES):
        try:
            return operation()
        except OperationalError as exc:
            if not is_lock_error(exc):
                raise
            if retry_index == len(_LOCK_BACKOFF_SECONDS):
                raise RuntimeConflictError(
                    "database transaction was serialized"
                ) from exc
            jitter = (monotonic_ns() % 250_000_000) / 1_000_000_000
            sleep(_LOCK_BACKOFF_SECONDS[retry_index] + jitter)
    raise AssertionError("lock retry loop did not return or raise")


def is_lock_error(error: OperationalError) -> bool:
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "database is locked",
            "database table is locked",
            "database is busy",
            "could not serialize access",
            "deadlock detected",
        )
    )
