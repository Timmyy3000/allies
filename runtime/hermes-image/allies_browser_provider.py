"""Allies browser provider; replaces the bundled Browser Use provider.

Cloud holds the Browser Use key and each Ally's profile. This provider only
asks Cloud to open or close the Ally's browser and connects to the CDP URL
it returns. Hermes auto-detect picks it up under the same class name.
"""

from __future__ import annotations

import threading
import uuid

from agent.browser_provider import BrowserProvider

# close_session may run on the inactivity reaper thread, where the turn's
# capability context is not set, so keep the context captured at open.
_opened: dict[str, tuple] = {}
_lock = threading.Lock()


class BrowserUseBrowserProvider(BrowserProvider):
    @property
    def name(self) -> str:
        return "browser-use"

    @property
    def display_name(self) -> str:
        return "Allies browser"

    def is_available(self) -> bool:
        return True

    def create_session(self, task_id: str) -> dict[str, object]:
        from tools.allies_routines import context
        from tools.allies_safe_inputs import relay

        current = context.get()
        result = relay("browser", {"action": "open"}, uuid.uuid4().hex, current)
        if not result.get("session_id") or not result.get("cdp_url"):
            raise RuntimeError(
                "Allies browser unavailable: " + str(result.get("error"))
            )
        with _lock:
            _opened[result["session_id"]] = current
        return {
            "session_name": f"hermes_{task_id}_{uuid.uuid4().hex[:8]}",
            "bb_session_id": result["session_id"],
            "cdp_url": result["cdp_url"],
            "expires_at": result.get("expires_at"),
            "features": {"browser_use": True},
        }

    def close_session(self, session_id: str) -> bool:
        from tools.allies_safe_inputs import relay

        with _lock:
            current = _opened.pop(session_id, None)
        if current is None:
            return False
        result = relay(
            "browser",
            {"action": "close", "session_id": session_id},
            uuid.uuid4().hex,
            current,
        )
        return result.get("status") == "closed"

    def emergency_cleanup(self, session_id: str) -> None:
        self.close_session(session_id)
