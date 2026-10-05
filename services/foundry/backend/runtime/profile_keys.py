from __future__ import annotations

import re
from uuid import UUID

from runtime.exceptions import RuntimeValidationError

PROFILE_KEY_REGEX = r"^[a-z0-9][a-z0-9_-]{0,63}$"
PROFILE_KEY_PATTERN = re.compile(PROFILE_KEY_REGEX)
RESERVED_PROFILE_KEYS = ("hermes", "default", "test", "tmp", "root", "sudo")


def derive_hermes_profile_key(profile_id: UUID | str) -> str:
    """Derive the immutable v1 Hermes key for one Foundry profile ID."""

    try:
        normalized = (
            profile_id if isinstance(profile_id, UUID) else UUID(str(profile_id))
        )
    except (TypeError, ValueError, AttributeError) as exc:
        raise RuntimeValidationError("Foundry profile ID must be a UUID") from exc
    return validate_hermes_profile_key(f"ally-v1-{normalized.hex}")


def validate_hermes_profile_key(value: str) -> str:
    if not isinstance(value, str) or not PROFILE_KEY_PATTERN.fullmatch(value):
        raise RuntimeValidationError(
            "Hermes profile key must match [a-z0-9][a-z0-9_-]{0,63}"
        )
    if value in RESERVED_PROFILE_KEYS:
        raise RuntimeValidationError("Hermes profile key is reserved")
    return value


__all__ = [
    "PROFILE_KEY_PATTERN",
    "PROFILE_KEY_REGEX",
    "RESERVED_PROFILE_KEYS",
    "derive_hermes_profile_key",
    "validate_hermes_profile_key",
]
