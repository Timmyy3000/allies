"""Browser Use sessions for Allies and the CDP calls Cloud makes on them.

Cloud alone holds the Browser Use key. Each Ally gets one profile so its
sign-ins persist; a workspace may hold two open sessions at once.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from websockets.sync.client import connect

from workspaces.models import Workspace

from ..models import AllyBrowser, BrowserSession

logger = logging.getLogger(__name__)

API = "https://api.browser-use.com/api/v4"
SESSION_MINUTES = 20
WORKSPACE_LIMIT = 2


class BrowserUnavailable(Exception):
    pass


def _api(method: str, path: str, body: dict | None = None) -> dict:
    key = getattr(settings, "BROWSER_USE_API_KEY", "")
    if not key:
        raise BrowserUnavailable("browser use key unavailable")
    request = Request(
        API + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"X-Browser-Use-API-Key": key, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read()
    except (HTTPError, URLError, OSError) as exc:
        raise BrowserUnavailable(f"browser use {method} {path} failed") from exc
    return json.loads(raw) if raw else {}


def open_sessions(**filters):
    return BrowserSession.objects.filter(
        ended_at=None, expires_at__gt=timezone.now(), **filters
    )


def stop_session(session: BrowserSession) -> None:
    if session.browser_use_id:
        try:
            _api("PATCH", f"/browsers/{session.browser_use_id}", {"action": "stop"})
        except BrowserUnavailable:
            logger.warning("browser.stop_failed session=%s", session.id)
    session.ended_at = timezone.now()
    session.save(update_fields=["ended_at"])


def open_browser(ally) -> dict:
    # The Ally's current browser is replaced only once the new one works, so
    # it does not count toward the workspace limit here.
    previous = list(open_sessions(ally=ally))
    with transaction.atomic():
        Workspace.objects.select_for_update().get(pk=ally.workspace_id)
        others = open_sessions(workspace_id=ally.workspace_id).exclude(ally=ally)
        if others.count() >= WORKSPACE_LIMIT:
            return {"error": "browser_limit_reached"}
        session = BrowserSession.objects.create(
            workspace_id=ally.workspace_id,
            ally=ally,
            expires_at=timezone.now() + timedelta(minutes=SESSION_MINUTES),
        )
    try:
        browser, _ = AllyBrowser.objects.get_or_create(ally=ally)
        if not browser.profile_id:
            browser.profile_id = _api("POST", "/profiles", {"userId": str(ally.id)})[
                "id"
            ]
            browser.save(update_fields=["profile_id"])
        created = _api(
            "POST",
            "/browsers",
            {
                "profileId": browser.profile_id,
                "timeout": SESSION_MINUTES,
                # Browser Use defaults to a US proxy, which slows every page load.
                "proxyCountryCode": getattr(settings, "BROWSER_USE_PROXY_COUNTRY", "")
                or None,
            },
        )
        session.browser_use_id = created["id"]
        session.cdp_url = created["cdpUrl"]
        session.live_url = created.get("liveUrl") or ""
        session.save(update_fields=["browser_use_id", "cdp_url", "live_url"])
        if browser.pending_clear_sites:
            with Cdp(session.cdp_url) as cdp:
                for site in browser.pending_clear_sites:
                    cdp.clear_site(site)
            browser.pending_clear_sites = []
            browser.save(update_fields=["pending_clear_sites"])
    except (BrowserUnavailable, KeyError, ValueError, OSError, StopIteration):
        if session.browser_use_id:
            stop_session(session)
        session.delete()
        logger.warning("browser.open_failed ally=%s", ally.id)
        return {"error": "browser_unavailable"}
    for old in previous:
        stop_session(old)
    logger.info("browser.opened ally=%s session=%s", ally.id, session.id)
    return {
        "session_id": str(session.id),
        "cdp_url": session.cdp_url,
        "expires_at": session.expires_at.isoformat(),
    }


def close_browser(ally, session_id: str) -> dict:
    try:
        session = open_sessions(ally=ally, pk=UUID(session_id)).first()
    except ValueError:
        return {"error": "invalid_request"}
    if session is not None:
        stop_session(session)
    return {"status": "closed"}


def sign_out_site(ally, site: str) -> None:
    browser, _ = AllyBrowser.objects.get_or_create(ally=ally)
    if site not in browser.pending_clear_sites:
        browser.pending_clear_sites = [*browser.pending_clear_sites, site]
        browser.save(update_fields=["pending_clear_sites"])
    for session in open_sessions(ally=ally):
        stop_session(session)


def delete_profile(profile_id: str) -> None:
    try:
        _api("DELETE", f"/profiles/{profile_id}")
    except BrowserUnavailable:
        logger.warning("browser.profile_delete_failed profile=%s", profile_id)


def _websocket_url(cdp_url: str) -> str:
    if "/devtools/browser/" in cdp_url or cdp_url.startswith(("ws://", "wss://")):
        return cdp_url
    with urlopen(cdp_url.rstrip("/") + "/json/version", timeout=10) as response:
        return json.loads(response.read())["webSocketDebuggerUrl"]


class Cdp:
    """Minimal synchronous CDP client over the browser websocket."""

    def __init__(self, cdp_url: str):
        self._url = _websocket_url(cdp_url)
        self._next = 0

    def __enter__(self):
        self._ws = connect(self._url, open_timeout=10, max_size=2**24)
        return self

    def __exit__(self, *exc):
        self._ws.close()

    def call(self, method: str, params: dict | None = None, session: str | None = None):
        self._next += 1
        message = {"id": self._next, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        self._ws.send(json.dumps(message))
        while True:
            reply = json.loads(self._ws.recv(timeout=15))
            if reply.get("id") == self._next:
                if "error" in reply:
                    raise ValueError(reply["error"].get("message", "cdp error"))
                return reply.get("result", {})

    def page(self) -> str:
        targets = self.call("Target.getTargets")["targetInfos"]
        page = next(t for t in targets if t["type"] == "page")
        return self.call(
            "Target.attachToTarget", {"targetId": page["targetId"], "flatten": True}
        )["sessionId"]

    def clear_site(self, site: str) -> None:
        page = self.page()
        for cookie in self.call("Storage.getCookies").get("cookies", []):
            if host_matches(cookie["domain"].lstrip("."), site):
                fields = {k: cookie[k] for k in ("name", "domain", "path")}
                self.call("Network.deleteCookies", fields, session=page)
        for origin in (f"https://{site}", f"https://www.{site}"):
            self.call(
                "Storage.clearDataForOrigin", {"origin": origin, "storageTypes": "all"}
            )


def normalize_website(value: str) -> str:
    raw = value.strip().lower()
    host = (urlsplit(raw if "//" in raw else "//" + raw).hostname or "").rstrip(".")
    host = host.removeprefix("www.")
    labels = host.split(".")
    if len(labels) < 2 or not all(labels) or len(host) > 253:
        raise ValueError("website must be a site like example.com")
    return host


def host_matches(host: str, website: str) -> bool:
    host = host.lower().rstrip(".")
    return host == website or host.endswith("." + website)
