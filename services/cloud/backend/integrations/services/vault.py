"""Envelope encryption for integration refresh credentials.

Refresh tokens never sit in plaintext: each ``IntegrationSecret`` row holds
Fernet ciphertext plus the key version that sealed it. Key rotation adds a
new ``ALLIES_INTEGRATIONS_VAULT_KEY_V<n>`` setting and bumps
``VAULT_KEY_CURRENT_VERSION``; old rows keep decrypting until re-sealed.
A missing key fails closed — no derive-from-other-secret fallback.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os

from django.conf import settings

from ..exceptions import IntegrationUnavailable

VAULT_KEY_CURRENT_VERSION = 1


def _raw_key(version: int) -> bytes:
    if version == 1:
        name = "ALLIES_INTEGRATIONS_VAULT_KEY"
    else:
        name = f"ALLIES_INTEGRATIONS_VAULT_KEY_V{version}"
    configured = getattr(settings, name, "") or os.environ.get(name, "")
    if configured:
        return configured.encode()
    if getattr(settings, "DEBUG", True):
        return f"allies-local-integrations-vault-key-v{version}-not-for-production".encode()
    return b""


def vault_key(version: int) -> bytes:
    raw = _raw_key(version)
    if not raw:
        raise IntegrationUnavailable("integration vault key unavailable")
    try:
        key = base64.urlsafe_b64decode(raw)
    except (binascii.Error, ValueError):
        return hashlib.sha256(raw).digest()
    if len(key) != 32:
        raise IntegrationUnavailable("integration vault key invalid")
    return key


def seal_refresh_token(refresh_token: str) -> tuple[bytes, int]:
    from cryptography.fernet import Fernet

    version = VAULT_KEY_CURRENT_VERSION
    token = Fernet(base64.urlsafe_b64encode(vault_key(version))).encrypt(
        refresh_token.encode()
    )
    return token, version


def unseal_refresh_token(ciphertext: bytes, *, key_version: int) -> str:
    from cryptography.fernet import Fernet, InvalidToken

    try:
        return (
            Fernet(base64.urlsafe_b64encode(vault_key(key_version)))
            .decrypt(bytes(ciphertext))
            .decode()
        )
    except InvalidToken as exc:
        raise IntegrationUnavailable("integration credential unreadable") from exc
