"""Opaque public identifiers used at Cloud API boundaries.

The database primary key is deliberately not exposed by the product API.  A
public id contains a short type prefix and 128 bits of random Crockford base32
entropy.  The alphabet avoids characters which are commonly confused when an
id is copied from a log or URL.
"""

from __future__ import annotations

import secrets
from typing import Final

CROCKFORD_ALPHABET: Final[str] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PUBLIC_ID_BITS: Final[int] = 128
PUBLIC_ID_LENGTH: Final[int] = 26  # ceil(128 / 5)


def _encode_crockford(value: int, length: int = PUBLIC_ID_LENGTH) -> str:
    chars: list[str] = []
    for _ in range(length):
        value, remainder = divmod(value, len(CROCKFORD_ALPHABET))
        chars.append(CROCKFORD_ALPHABET[remainder])
    return "".join(reversed(chars))


def new_public_id(prefix: str) -> str:
    """Return an opaque ``prefix_RANDOM`` id.

    Prefixes are kept intentionally small and are validated so an accidental
    user supplied string cannot alter the shape of identifiers.
    """

    normalized = prefix.strip().lower()
    if not normalized or not normalized.replace("_", "").isalnum():
        raise ValueError("identifier prefix must be alphanumeric")
    return f"{normalized}_{_encode_crockford(secrets.randbits(PUBLIC_ID_BITS))}"


def is_public_id(value: str, prefix: str | None = None) -> bool:
    if not isinstance(value, str) or "_" not in value:
        return False
    actual_prefix, token = value.split("_", 1)
    if prefix is not None and actual_prefix != prefix.strip().lower():
        return False
    if len(token) != PUBLIC_ID_LENGTH:
        return False
    return all(char in CROCKFORD_ALPHABET for char in token.upper())
