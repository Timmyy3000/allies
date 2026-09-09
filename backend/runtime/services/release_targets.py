from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def is_pending_release_target(target: Any) -> bool:
    """Return whether a release_target contains image replacement state."""

    return isinstance(target, Mapping) and any(
        key != "routine_admission" for key in target
    )
