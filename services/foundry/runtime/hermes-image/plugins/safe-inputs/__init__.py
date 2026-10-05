# ruff: noqa: N999  # Hermes discovers this required hyphenated plugin ID.
from tools.allies_safe_inputs import (
    APPROVAL_SCHEMA,
    SCHEMA,
    handle_ask_approval,
    handle_safe_inputs,
)


def register(ctx):
    for schema, handler in (
        (SCHEMA, handle_safe_inputs),
        (APPROVAL_SCHEMA, handle_ask_approval),
    ):
        ctx.register_tool(
            name=schema["function"]["name"],
            toolset="allies-safe-inputs",
            schema=schema["function"],
            handler=handler,
            description=schema["function"]["description"],
        )
