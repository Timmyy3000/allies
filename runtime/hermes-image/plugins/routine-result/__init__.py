# ruff: noqa: N999  # Hermes discovers this required hyphenated plugin ID.
"""Typed result producer for the Allies scheduled-routine boundary."""

from __future__ import annotations

from .tools import ROUTINE_RESULT_SCHEMA, handle_routine_result


def register(ctx) -> None:
    ctx.register_tool(
        name="allies_routine_result",
        toolset="allies-routine-result",
        schema=ROUTINE_RESULT_SCHEMA["function"],
        handler=handle_routine_result,
        description=ROUTINE_RESULT_SCHEMA["function"]["description"],
    )
