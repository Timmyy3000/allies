from __future__ import annotations

import json
import time
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_RESPONSE_BYTES = 1024 * 1024
READ_CHUNK_BYTES = 16 * 1024


class ProviderError(Exception):
    def __init__(self, status: int | None) -> None:
        super().__init__(status)
        self.status = status


class _RefuseRedirects(HTTPRedirectHandler):
    # urllib would resend the auth header to whatever host a redirect names.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(_RefuseRedirects)


def _post(
    url: str, headers: dict[str, str], body: dict[str, Any], timeout: float
) -> Any:
    request = Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            **headers,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    deadline = time.monotonic() + timeout
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = _read_until(response, deadline)
    except HTTPError as exc:
        raise ProviderError(exc.code) from None
    except (OSError, HTTPException):
        raise ProviderError(None) from None
    try:
        return json.loads(raw)
    except ValueError:
        raise ProviderError(None) from None


def _read_until(response: Any, deadline: float) -> bytes:
    # read1 returns after one socket read, so the deadline is checked between reads.
    raw = bytearray()
    while chunk := response.read1(READ_CHUNK_BYTES):
        raw += chunk
        if len(raw) > MAX_RESPONSE_BYTES or time.monotonic() > deadline:
            raise ProviderError(None)
    return bytes(raw)


def _parse_parallel(payload: Any) -> list[dict[str, Any]]:
    return [
        {
            "title": item.get("title") or "",
            "url": item["url"],
            "description": " ".join(item.get("excerpts") or []),
            "position": position,
        }
        for position, item in enumerate(payload["results"], start=1)
    ]


def _parse_tavily(payload: Any) -> list[dict[str, Any]]:
    return [
        {
            "title": item.get("title") or "",
            "url": item["url"],
            "description": item.get("content") or "",
            "position": position,
        }
        for position, item in enumerate(payload["results"], start=1)
    ]


def _parse_exa(payload: Any) -> list[dict[str, Any]]:
    return [
        {
            "title": item.get("title") or "",
            "url": item["url"],
            "description": " ".join(item.get("highlights") or []),
            "position": position,
        }
        for position, item in enumerate(payload["results"], start=1)
    ]


BACKENDS: dict[str, dict[str, Any]] = {
    "parallel": {
        "label": "Parallel",
        "search_url": "https://api.parallel.ai/v1beta/search",
        "auth_header": ("x-api-key", ""),
        "static_headers": {"parallel-beta": "search-extract-2025-10-10"},
        "search_body": lambda query, limit: {
            "objective": query,
            "search_queries": [query],
            "mode": "fast",
            "max_results": limit,
        },
        "parse_search": _parse_parallel,
    },
    "tavily": {
        "label": "Tavily",
        "search_url": "https://api.tavily.com/search",
        "auth_header": ("Authorization", "Bearer "),
        "static_headers": {},
        "search_body": lambda query, limit: {"query": query, "max_results": limit},
        "parse_search": _parse_tavily,
    },
    "exa": {
        "label": "Exa",
        "search_url": "https://api.exa.ai/search",
        "auth_header": ("x-api-key", ""),
        "static_headers": {},
        "search_body": lambda query, limit: {
            "query": query,
            "numResults": limit,
            "contents": {"highlights": True},
        },
        "parse_search": _parse_exa,
    },
}


def search(
    *, backend: str, api_key: str, query: str, limit: int, timeout: float
) -> list[dict[str, Any]]:
    spec = BACKENDS[backend]
    header, prefix = spec["auth_header"]
    headers = {**spec["static_headers"], header: f"{prefix}{api_key}"}
    payload = _post(
        spec["search_url"], headers, spec["search_body"](query, limit), timeout
    )
    try:
        return spec["parse_search"](payload)
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ProviderError(None) from None
