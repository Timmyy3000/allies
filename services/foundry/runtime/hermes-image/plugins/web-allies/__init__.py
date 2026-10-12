# ruff: noqa: N999  # Hermes discovers this required hyphenated plugin ID.
"""Allies web provider: search and extract relayed through Cloud."""

from plugins.web.allies.provider import AlliesWebSearchProvider


def register(ctx) -> None:
    ctx.register_web_search_provider(AlliesWebSearchProvider())
