"""Allies policy wrapper for the pinned Hermes Mnemosyne provider.

The image copies a very small registration bridge into Hermes' bundled memory
plugin directory.  Keeping policy here, instead of changing either upstream
project, makes the selected provider and its failure behaviour reviewable.
"""

from .provider import (
    ALLOWED_TOOLS,
    POLICY_VERSION,
    AlliesMnemosyneProvider,
    MemoryProvider,
    register,
    register_memory_provider,
)

__all__ = [
    "ALLOWED_TOOLS",
    "POLICY_VERSION",
    "AlliesMnemosyneProvider",
    "MemoryProvider",
    "register",
    "register_memory_provider",
]
