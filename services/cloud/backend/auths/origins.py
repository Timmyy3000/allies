"""Origin matching shared by browser auth admission and redirect validation."""

from __future__ import annotations

import re
from urllib.parse import urlsplit


def origin_allowed(origin: str, trusted_origins: object) -> bool:
    """Return whether an origin matches the configured exact/wildcard origins."""
    if not isinstance(origin, str):
        return False
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    if not isinstance(trusted_origins, (list, tuple, set, frozenset)):
        return False
    return any(
        isinstance(trusted, str)
        and re.fullmatch(re.escape(trusted).replace(r"\*", r"[^./:]+"), origin)
        for trusted in trusted_origins
    )
