from __future__ import annotations

import json
import time
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_RESPONSE_BYTES = 1024 * 1024
READ_CHUNK_BYTES = 16 * 1024
PAGE_CHARS = 15_000
PAGE_FAILED = "The page could not be read."


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


def _page(url: str, title: str = "", content: str = "", **extra: str) -> dict[str, Any]:
    return {
        "url": url,
        "title": title,
        "content": content,
        "raw_content": "",
        "metadata": {},
        **extra,
    }


def _parse_parallel_extract(payload: Any) -> list[dict[str, Any]]:
    pages = [
        _page(
            item["url"],
            item.get("title") or "",
            item.get("full_content") or "\n\n".join(item.get("excerpts") or []),
        )
        for item in payload["results"]
    ]
    return pages + [
        _page(item.get("url") or "", error=PAGE_FAILED)
        for item in payload.get("errors") or []
    ]


def _parse_tavily_extract(payload: Any) -> list[dict[str, Any]]:
    pages = [
        _page(item["url"], item.get("title") or "", item.get("raw_content") or "")
        for item in payload["results"]
    ]
    return pages + [
        _page(item.get("url") or "", error=PAGE_FAILED)
        for item in payload.get("failed_results") or []
    ]


def _parse_exa_extract(payload: Any) -> list[dict[str, Any]]:
    pages = [
        _page(item["url"], item.get("title") or "", item.get("text") or "")
        for item in payload["results"]
    ]
    return pages + [
        _page(status.get("id") or "", error=PAGE_FAILED)
        for status in payload.get("statuses") or []
        if status.get("status") == "error"
    ]


BACKENDS: dict[str, dict[str, Any]] = {
    "parallel": {
        "label": "Parallel",
        "search_url": "https://api.parallel.ai/v1beta/search",
        "extract_url": "https://api.parallel.ai/v1beta/extract",
        "auth_header": ("x-api-key", ""),
        "static_headers": {"parallel-beta": "search-extract-2025-10-10"},
        "search_body": lambda query, limit: {
            "objective": query,
            "search_queries": [query],
            "mode": "fast",
            "max_results": limit,
        },
        "extract_body": lambda urls: {"urls": urls, "full_content": True},
        "parse_search": _parse_parallel,
        "parse_extract": _parse_parallel_extract,
    },
    "tavily": {
        "label": "Tavily",
        "search_url": "https://api.tavily.com/search",
        "extract_url": "https://api.tavily.com/extract",
        "auth_header": ("Authorization", "Bearer "),
        "static_headers": {},
        "search_body": lambda query, limit: {"query": query, "max_results": limit},
        "extract_body": lambda urls: {"urls": urls},
        "parse_search": _parse_tavily,
        "parse_extract": _parse_tavily_extract,
    },
    "exa": {
        "label": "Exa",
        "search_url": "https://api.exa.ai/search",
        "extract_url": "https://api.exa.ai/contents",
        "auth_header": ("x-api-key", ""),
        "static_headers": {},
        "search_body": lambda query, limit: {
            "query": query,
            "numResults": limit,
            "contents": {"highlights": True},
        },
        "extract_body": lambda urls: {
            "urls": urls,
            "text": {"maxCharacters": PAGE_CHARS},
        },
        "parse_search": _parse_exa,
        "parse_extract": _parse_exa_extract,
    },
}


def _send(
    spec: dict[str, Any], api_key: str, url: str, body: dict[str, Any], timeout: float
) -> Any:
    header, prefix = spec["auth_header"]
    headers = {**spec["static_headers"], header: f"{prefix}{api_key}"}
    return _post(url, headers, body, timeout)


def _parsed(parse, payload: Any) -> Any:
    try:
        return parse(payload)
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ProviderError(None) from None


def search(
    *, backend: str, api_key: str, query: str, limit: int, timeout: float
) -> list[dict[str, Any]]:
    spec = BACKENDS[backend]
    payload = _send(
        spec, api_key, spec["search_url"], spec["search_body"](query, limit), timeout
    )
    return _parsed(spec["parse_search"], payload)


def extract(
    *, backend: str, api_key: str, urls: list[str], timeout: float
) -> list[dict[str, Any]]:
    spec = BACKENDS[backend]
    payload = _send(
        spec, api_key, spec["extract_url"], spec["extract_body"](urls), timeout
    )
    return _parsed(spec["parse_extract"], payload)
