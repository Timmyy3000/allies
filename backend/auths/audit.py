"""Privacy-safe structured authentication outcomes.

The envelope intentionally accepts opaque references only.  Callers should not
pass provider claims, cookies, authorization codes, object keys or profile
payloads; this helper also bounds free-form reason/provider values.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime

from auths.config import digest_key

logger = logging.getLogger("allies.auth")


def opaque_ref(value: str) -> str:
    return hmac.new(digest_key(), value.encode(), hashlib.sha256).hexdigest()[:16]


def emit_auth_event(
    event_name: str,
    *,
    outcome: str,
    reason_code: str = "",
    provider: str = "",
    actor_ref: str = "",
    family_ref: str = "",
    correlation_id: str = "",
) -> None:
    envelope = {
        "event_name": event_name[:80],
        "outcome": outcome[:32],
        "reason_code": reason_code[:64],
        "provider": provider[:32],
        "actor_ref": opaque_ref(actor_ref) if actor_ref else "",
        "family_ref": opaque_ref(family_ref) if family_ref else "",
        "correlation_id": correlation_id[:64],
        "timestamp": datetime.now(UTC).isoformat(),
    }
    logger.info("auth event", extra={"auth_event": envelope})
