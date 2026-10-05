"""Validated, portable settings for Foundry wide events.

The six environment variables in this module are the complete alpha
configuration surface.  Sink batching, retry, and timeout policy belongs to a
future adapter and is deliberately not represented here.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured

MAX_WIDE_EVENT_BYTES = 16 * 1024
MAX_WIDE_EVENT_QUEUE_SIZE = 4096


def _bool_value(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True
    if isinstance(value, str) and value.strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean")


def _float_value(value: object, name: str, *, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ImproperlyConfigured(f"{name} must be a number") from error
    if result < minimum or result > maximum:
        raise ImproperlyConfigured(
            f"{name} must be between {minimum:g} and {maximum:g}"
        )
    return result


def _int_value(value: object, name: str, *, minimum: int, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ImproperlyConfigured(f"{name} must be an integer") from error
    if result < minimum or result > maximum:
        raise ImproperlyConfigured(
            f"{name} must be between {minimum} and {maximum}"
        )
    return result


@dataclass(frozen=True, slots=True)
class FoundryObservabilitySettings:
    """The bounded wide-event configuration for one web process."""

    enabled: bool = True
    success_sample_rate: float = 1.0
    slow_ms: float = 1000.0
    max_bytes: int = 16 * 1024
    sink_enabled: bool = False
    max_queue_size: int = 128

    @classmethod
    def from_env(
        cls, env: Mapping[str, object] | None = None
    ) -> FoundryObservabilitySettings:
        values = os.environ if env is None else env
        return cls(
            enabled=_bool_value(
                values.get("ALLIES_WIDE_EVENTS_ENABLED", "true"),
                "ALLIES_WIDE_EVENTS_ENABLED",
            ),
            success_sample_rate=_float_value(
                values.get("ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE", "1.0"),
                "ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE",
                minimum=0.0,
                maximum=1.0,
            ),
            slow_ms=_float_value(
                values.get("ALLIES_WIDE_EVENTS_SLOW_MS", "1000"),
                "ALLIES_WIDE_EVENTS_SLOW_MS",
                minimum=0.0,
                maximum=86_400_000.0,
            ),
            max_bytes=_int_value(
                values.get("ALLIES_WIDE_EVENTS_MAX_BYTES", str(16 * 1024)),
                "ALLIES_WIDE_EVENTS_MAX_BYTES",
                minimum=512,
                maximum=MAX_WIDE_EVENT_BYTES,
            ),
            sink_enabled=_bool_value(
                values.get("ALLIES_WIDE_EVENTS_SINK_ENABLED", "false"),
                "ALLIES_WIDE_EVENTS_SINK_ENABLED",
            ),
            max_queue_size=_int_value(
                values.get("ALLIES_WIDE_EVENTS_MAX_QUEUE_SIZE", "128"),
                "ALLIES_WIDE_EVENTS_MAX_QUEUE_SIZE",
                minimum=1,
                maximum=MAX_WIDE_EVENT_QUEUE_SIZE,
            ),
        )


__all__ = ["FoundryObservabilitySettings"]
