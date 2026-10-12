"""Allies web search and extract, relayed through Cloud; no provider key reaches this machine."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from agent.web_search_provider import WebSearchProvider
from tools.allies_safe_inputs import relay

_UNAVAILABLE = "Web search is temporarily unavailable. Try again later."
_NOT_RUN = "Web search couldn't run for this turn."
_INSTRUCTIONS = {
    "web_search_tool_unavailable": "Web search isn't available in this context.",
    "web_search_service_unavailable": _UNAVAILABLE,
    "web_search_unavailable": _UNAVAILABLE,
    "web_search_not_connected": (
        "Web search isn't connected for this ally. Connect it in Account → Connections."
    ),
    "web_search_not_granted": (
        "Web search is off for this ally. Turn it on in Account → Connections."
    ),
    "web_search_key_rejected": (
        "The web search key was rejected. Ask the user to replace it in Account → Connections."
    ),
    "web_search_rate_limited": (
        "The web search provider is rate limiting requests. Try again in a minute."
    ),
}


def _failure(result: dict[str, Any]) -> str:
    instruction = result.get("instruction")
    if isinstance(instruction, str) and instruction:
        return instruction
    code = result.get("error")
    if isinstance(code, str) and code in _INSTRUCTIONS:
        return _INSTRUCTIONS[code]
    return _NOT_RUN


def _call_key() -> str:
    from tools.approval import _approval_tool_call_id

    return _approval_tool_call_id.get() or uuid4().hex


class AlliesWebSearchProvider(WebSearchProvider):
    """Search and extract through the workspace's connection; Cloud decides access per call."""

    @property
    def name(self) -> str:
        return "allies"

    @property
    def display_name(self) -> str:
        return "Allies"

    def is_available(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return True

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        arguments = {
            "action": "search",
            "query": query,
            "limit": min(max(int(limit), 1), 10),
        }
        result = relay("web_search", arguments, _call_key())
        data = result.get("data")
        if (
            result.get("success") is True
            and isinstance(data, dict)
            and isinstance(data.get("web"), list)
        ):
            return {"success": True, "data": {"web": data["web"]}}
        return {"success": False, "error": _failure(result)}

    def extract(self, urls: list[str], **kwargs: Any) -> list[dict[str, Any]]:
        result = relay(
            "web_search", {"action": "extract", "urls": list(urls)}, _call_key()
        )
        data = result.get("data")
        if result.get("success") is True and isinstance(data, list):
            # Hermes pairs extract results with the requested URLs by position.
            by_url = {
                item["url"]: item
                for item in data
                if isinstance(item, dict) and isinstance(item.get("url"), str)
            }
            return [
                by_url.get(url)
                or {"url": url, "title": "", "content": "", "error": _NOT_RUN}
                for url in urls
            ]
        instruction = _failure(result)
        return [
            {"url": url, "title": "", "content": "", "error": instruction}
            for url in urls
        ]
