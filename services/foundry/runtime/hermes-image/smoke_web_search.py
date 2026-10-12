"""Smoke for the Allies web provider: relay, refusals, and the managed backend pin."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOME = tempfile.mkdtemp(prefix="allies-web-smoke-")
Path(HOME, "config.yaml").write_text(
    "web:\n  backend: parallel\n  search_backend: exa\n  extract_backend: tavily\n",
    encoding="utf-8",
)
os.environ["HERMES_HOME"] = HOME

from agent.web_search_registry import get_provider
from hermes_cli.plugins import _ensure_plugins_discovered
from model_tools import get_tool_definitions
from tools import web_tools
from tools.allies_routines import context, turn_context

TOKEN = "smoke-turn-token"
PAGE_URL = "https://93.184.216.34/page"
SEARCH_HIT = {
    "title": "Allies",
    "url": "https://example.com/a",
    "description": "Snippet",
    "position": 1,
}
PAGE = {
    "url": PAGE_URL,
    "title": "Page",
    "content": "Body text",
    "raw_content": "",
    "metadata": {},
}
NOT_GRANTED = "Web search is off for this ally. Turn it on in Account → Connections."
UNAVAILABLE = "Web search is temporarily unavailable. Try again later."
LEGACY = {
    "PARALLEL_API_KEY": "legacy-parallel-key-0001",  # gitleaks:allow
    "TAVILY_API_KEY": "legacy-tavily-key-0001",  # gitleaks:allow
    "EXA_API_KEY": "legacy-exa-key-0001",  # gitleaks:allow
    "FIRECRAWL_API_KEY": "legacy-firecrawl-key-0001",  # gitleaks:allow
    "SEARXNG_URL": "http://192.0.2.1:8888/",
}


class Foundry:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.reply = None

    def answer(self, body: dict) -> tuple[int, dict]:
        if self.reply is not None:
            return self.reply(body)
        if body["arguments"]["action"] == "search":
            return 200, {"success": True, "data": {"web": [SEARCH_HIT]}}
        return 200, {"success": True, "data": [PAGE]}


FOUNDRY = Foundry()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FOUNDRY.requests.append(
            {"auth": self.headers.get("Authorization"), "body": body}
        )
        status, payload = FOUNDRY.answer(body)
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: object) -> None:
        return


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
ORIGIN = f"http://127.0.0.1:{server.server_address[1]}"

_REAL_CONNECT = socket.socket.connect
BLOCKED: list = []


def _guarded_connect(self: socket.socket, address: object) -> None:
    if address != ("127.0.0.1", server.server_address[1]):
        BLOCKED.append(address)
        raise OSError("blocked by web search smoke")
    return _REAL_CONNECT(self, address)


socket.socket.connect = _guarded_connect


def search(limit: int = 3) -> dict:
    return json.loads(web_tools.web_search_tool("allies smoke", limit))


def extract() -> dict:
    return json.loads(asyncio.run(web_tools.web_extract_tool([PAGE_URL])))


def with_reply(reply, action):
    FOUNDRY.reply = reply
    try:
        return action()
    finally:
        FOUNDRY.reply = None


def check_registration() -> None:
    _ensure_plugins_discovered()
    assert get_provider("allies") is not None
    names = {
        definition["function"]["name"]
        for definition in get_tool_definitions(
            enabled_toolsets=["web"], quiet_mode=True
        )
    }
    assert {"web_search", "web_extract"} <= names, names


def check_pin(label: str) -> None:
    assert web_tools._get_search_backend() == "allies", label
    assert web_tools._get_extract_backend() == "allies", label


def check_managed_file() -> None:
    if os.geteuid() != 0:
        assert os.access("/etc/hermes", os.R_OK | os.X_OK), (
            "runtime user cannot traverse /etc/hermes"
        )
        assert os.access("/etc/hermes/config.yaml", os.R_OK), (
            "runtime user cannot read the pin"
        )
        assert not os.access("/etc/hermes", os.W_OK), (
            "runtime user can write /etc/hermes"
        )
        assert not os.access("/etc/hermes/config.yaml", os.W_OK), (
            "runtime user can write the pin"
        )
    for path in (Path("/etc/hermes"), Path("/etc/hermes/config.yaml")):
        status = path.stat()
        assert status.st_uid == 0, path
        assert not status.st_mode & 0o022, path


def check_happy_path() -> None:
    check_pin("user config conflicts with managed pin")
    token = context.set(turn_context(TOKEN, ORIGIN))
    try:
        before = len(FOUNDRY.requests)
        result = search(limit=50)
        assert result["success"] is True, result
        assert result["data"]["web"][0]["url"] == SEARCH_HIT["url"], result
        request = FOUNDRY.requests[before]
        assert request["auth"] == f"Bearer {TOKEN}", request
        assert request["body"]["integration"] == "web_search", request
        assert request["body"]["arguments"] == {
            "action": "search",
            "query": "allies smoke",
            "limit": 10,
        }, request
        extracted = extract()
        assert extracted["results"][0]["content"] == PAGE["content"], extracted
        assert extracted["results"][0].get("error") is None, extracted
    finally:
        context.reset(token)


def check_refusals() -> None:
    token = context.set(turn_context(TOKEN, ORIGIN))
    try:
        refused = with_reply(
            lambda _: (
                403,
                {"error": "web_search_not_granted", "instruction": NOT_GRANTED},
            ),
            search,
        )
        assert refused == {"success": False, "error": NOT_GRANTED}, refused
        refused_extract = with_reply(
            lambda _: (
                403,
                {"error": "web_search_not_granted", "instruction": NOT_GRANTED},
            ),
            extract,
        )
        assert refused_extract["results"][0]["error"] == NOT_GRANTED, refused_extract
        check_registration()

        not_connected = with_reply(
            lambda _: (403, {"error": "web_search_not_connected"}),
            search,
        )
        assert not_connected["error"] == (
            "Web search isn't connected for this ally. Connect it in Account → Connections."
        ), not_connected

        before = len(FOUNDRY.requests)
        limited = with_reply(
            lambda _: (200, {"success": False, "error": "web_search_rate_limited"}),
            search,
        )
        assert len(FOUNDRY.requests) == before + 1, "provider 429 must not retry"
        assert limited["error"] == (
            "The web search provider is rate limiting requests. Try again in a minute."
        ), limited

        before = len(FOUNDRY.requests)
        down = with_reply(
            lambda _: (503, {"error": "integration_service_unavailable"}), search
        )
        assert len(FOUNDRY.requests) == before + 2, "relay makes exactly two attempts"
        assert down == {"success": False, "error": UNAVAILABLE}, down

        stale = with_reply(lambda _: (409, {"error": "stale_turn"}), search)
        assert stale["error"] == "Web search couldn't run for this turn.", stale
    finally:
        context.reset(token)


def check_no_turn_context() -> None:
    token = context.set(None)
    try:
        before = len(FOUNDRY.requests)
        result = search()
        assert result == {
            "success": False,
            "error": "Web search isn't available in this context.",
        }, result
        assert len(FOUNDRY.requests) == before
    finally:
        context.reset(token)


def check_legacy_overrides() -> None:
    cases = [{key: value} for key, value in LEGACY.items()] + [dict(LEGACY)]
    token = context.set(turn_context(TOKEN, ORIGIN))
    try:
        for case in cases:
            for key in LEGACY:
                os.environ.pop(key, None)
            os.environ.update(case)
            label = ",".join(sorted(case))
            check_pin(label)
            before = len(FOUNDRY.requests)
            result = search()
            assert result["success"] is True, (label, result)
            assert len(FOUNDRY.requests) == before + 1, label
            assert extract()["results"][0]["content"] == PAGE["content"], label
    finally:
        context.reset(token)
        for key in LEGACY:
            os.environ.pop(key, None)


def main() -> None:
    check_managed_file()
    check_registration()
    check_happy_path()
    check_refusals()
    check_no_turn_context()
    check_legacy_overrides()
    assert BLOCKED == [], BLOCKED
    print("allies web search provider: PASS")


if __name__ == "__main__":
    main()
