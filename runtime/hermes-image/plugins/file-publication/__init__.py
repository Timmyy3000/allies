# ruff: noqa: N999  # Hermes discovers this required hyphenated plugin ID.
"""Private Hermes tool registration for bounded Allies file publication."""

from __future__ import annotations

from .tools import PUBLISH_FILES_SCHEMA, handle_publish_files


def register(ctx) -> None:
    ctx.register_tool(
        name="publish_files",
        toolset="allies-file-publication",
        schema=PUBLISH_FILES_SCHEMA,
        handler=handle_publish_files,
        description=PUBLISH_FILES_SCHEMA["function"]["description"],
    )
