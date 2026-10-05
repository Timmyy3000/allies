"""Provider-neutral encryption for tenant secrets held by Cloud.

``ALLIES_VAULT_KEYS`` is a comma-separated list of Fernet keys, newest first:
new values seal under the first key and every listed key can still unseal,
so rotation is "prepend a key, re-seal, then drop the old one". A missing or
malformed key fails closed; only ``DEBUG`` gets a fixed development key.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

_DEBUG_KEY = base64.urlsafe_b64encode(
    hashlib.sha256(b"allies-local-vault-key-not-for-production").digest()
)


class VaultUnavailable(Exception):
    pass


def _vault() -> MultiFernet:
    raw = [
        item.strip()
        for item in str(getattr(settings, "ALLIES_VAULT_KEYS", "") or "").split(",")
        if item.strip()
    ]
    if not raw:
        if not settings.DEBUG:
            raise VaultUnavailable("vault key unavailable")
        raw = [_DEBUG_KEY.decode()]
    try:
        return MultiFernet([Fernet(key.encode()) for key in raw])
    except (ValueError, TypeError):
        raise VaultUnavailable("vault key invalid") from None


def seal_secret(value: str) -> bytes:
    return _vault().encrypt(value.encode())


def unseal_secret(token: bytes) -> str:
    try:
        return _vault().decrypt(bytes(token)).decode()
    except (InvalidToken, UnicodeDecodeError):
        raise VaultUnavailable("secret unreadable") from None
