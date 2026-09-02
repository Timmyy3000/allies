"""Shared primitives for signed, rotating application cursors."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping

from auths.config import digest_key
from django.conf import settings


def _key_config(value: object) -> dict[str, bytes]:
    if isinstance(value, Mapping):
        return {
            str(key): (item if isinstance(item, bytes) else str(item).encode())
            for key, item in value.items()
            if str(key) and item
        }
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = None
        if isinstance(parsed, Mapping):
            return _key_config(parsed)
    return {}


def cursor_keys() -> tuple[str, dict[str, bytes]]:
    active_id = str(getattr(settings, "ALLIES_CHAT_CURSOR_ACTIVE_KEY_ID", "v1"))
    configured = _key_config(getattr(settings, "ALLIES_CHAT_CURSOR_KEYS", {}))
    active_value = getattr(settings, "ALLIES_CHAT_CURSOR_KEY", "")
    if active_id not in configured and active_value:
        configured[active_id] = (
            active_value
            if isinstance(active_value, bytes)
            else str(active_value).encode()
        )
    if active_id not in configured:
        configured[active_id] = digest_key()
    previous = _key_config(getattr(settings, "ALLIES_CHAT_CURSOR_PREVIOUS_KEYS", {}))
    return active_id, {**previous, **configured}


def b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
