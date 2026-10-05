"""Content-free timings for the Cloud side of runtime readiness."""

from contextlib import contextmanager
from time import monotonic

from observability.events import emit_event


@contextmanager
def readiness_phase(operation: str, **identity):
    started = monotonic()
    result = {}
    emit_event("runtime.operation.started", operation=operation, **identity)
    try:
        yield result
    except Exception as exc:
        emit_event(
            "runtime.operation.failed",
            operation=operation,
            duration_ms=(monotonic() - started) * 1000,
            error_type=type(exc).__name__,
            **identity,
        )
        raise
    else:
        emit_event(
            "runtime.operation.succeeded",
            operation=operation,
            duration_ms=(monotonic() - started) * 1000,
            outcome=result.get("outcome", "success"),
            **identity,
        )
