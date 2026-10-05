"""Small fail-open helpers for bounded runtime timing events."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from uuid import UUID

from observability.events import build_event


def emit_timing_event(
    event_name: str,
    *,
    emitter: Callable[[Mapping[str, object]], None],
    identifier_names: Iterable[str] = (),
    **fields: object,
) -> None:
    """Normalize UUID identifiers and keep diagnostics fail-open."""

    try:
        normalized = dict(fields)
        for name in identifier_names:
            value = normalized.get(name)
            if isinstance(value, UUID):
                normalized[name] = str(value)
        emitter(build_event(event_name, **normalized))
    except Exception:  # noqa: BLE001 - observability cannot block runtime work
        return


@contextmanager
def observed_timing_phase(
    operation: str,
    workspace_id: UUID | str | None = None,
    *,
    emitter: Callable[[Mapping[str, object]], None],
    correlation_id: UUID | str | None = None,
    provider_resource_id: str | None = None,
    provider: str | None = None,
):
    """Pair one bounded phase with monotonic duration and safe terminal data."""

    started_at = time.monotonic()
    identity = {
        "operation": operation,
        "workspace_id": workspace_id,
        "correlation_id": correlation_id,
        "provider_resource_id": provider_resource_id,
        "provider": provider,
    }
    terminal: dict[str, object] = {
        "event_name": "runtime.operation.succeeded",
        "outcome": "success",
    }
    identifiers = ("workspace_id", "correlation_id", "provider_resource_id")
    emit_timing_event(
        "runtime.operation.started",
        emitter=emitter,
        identifier_names=identifiers,
        outcome="started",
        **identity,
    )
    try:
        yield terminal
    except BaseException as error:
        terminal_fields = {**identity, **terminal}
        terminal_fields.pop("event_name", None)
        terminal_fields.update(
            duration_ms=(time.monotonic() - started_at) * 1000,
            outcome="error",
            error_type=type(error).__name__,
            error_code=getattr(error, "code", None),
        )
        emit_timing_event(
            "runtime.operation.failed",
            emitter=emitter,
            identifier_names=identifiers,
            **terminal_fields,
        )
        raise
    else:
        terminal_fields = {**identity, **terminal}
        event_name = terminal_fields.pop("event_name", "runtime.operation.succeeded")
        terminal_fields["duration_ms"] = (time.monotonic() - started_at) * 1000
        emit_timing_event(
            str(event_name),
            emitter=emitter,
            identifier_names=identifiers,
            **terminal_fields,
        )


__all__ = ["emit_timing_event", "observed_timing_phase"]
