"""Hermes bundled-memory discovery bridge for the Allies provider."""

# Keep ``MemoryProvider`` and ``register_memory_provider`` in this module so
# the pinned Hermes directory scanner recognizes this plugin without relying
# on a newer entry-point implementation.
from allies_mnemosyne import AlliesMnemosyneProvider, MemoryProvider  # noqa: F401


def register_memory_provider(ctx):
    ctx.register_memory_provider(AlliesMnemosyneProvider())


def register(ctx):
    register_memory_provider(ctx)
