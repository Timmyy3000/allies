from __future__ import annotations

import re

from runtime.exceptions import RuntimeValidationError

PROFILE_KEY_REGEX = r"^[a-z0-9][a-z0-9_-]{0,63}$"
PROFILE_KEY_PATTERN = re.compile(PROFILE_KEY_REGEX)
RESERVED_PROFILE_KEYS = ("hermes", "default", "test", "tmp", "root", "sudo")


def validate_hermes_profile_key(value: str) -> str:
    if not isinstance(value, str) or not PROFILE_KEY_PATTERN.fullmatch(value):
        raise RuntimeValidationError(
            "Hermes profile key must match [a-z0-9][a-z0-9_-]{0,63}"
        )
    if value in RESERVED_PROFILE_KEYS:
        raise RuntimeValidationError("Hermes profile key is reserved")
    return value
