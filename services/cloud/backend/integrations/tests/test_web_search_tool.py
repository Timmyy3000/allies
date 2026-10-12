"""Web search relay: granted allies' search and extract reach the provider; other calls are refused.

Calls go through the Foundry relay endpoint. Provider replies are synthetic and
``urlopen`` is replaced by a fake opener, so no test reaches the network.
"""

import io
import json
import logging
import secrets
from urllib.error import HTTPError, URLError
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from django.db import transaction
from django.test import Client

from chat.models import DispatchOutbox
from chat.services.dispatch import _ensure_outbox_locked
from chat.tests.test_dispatch import dispatch_records  # noqa: F401
from common.vault import VaultUnavailable, seal_secret
from integrations.models import PROVIDER_WEB_SEARCH, IntegrationSecret
from integrations.services import web_search, web_search_backends
from integrations.services.grants import revoke_ally_grant, set_ally_grant
from integrations.tests.test_grants import gmail_settings  # noqa: F401
from integrations.tests.test_routine_tools import routine_turn  # noqa: F401

URL = "/api/v1/internal/foundry/integrations/tool"
AUTH = {"HTTP_AUTHORIZATION": "Bearer test-service-token"}
KEY = "sk-test-KEY-abcdefgh9876"  # gitleaks:allow
QUERY = "allies research query"
PAGE = "https://example.com/a"
OTHER_PAGE = "https://example.com/b"
URLS = [PAGE, OTHER_PAGE]
NOT_CONNECTED = (
    "Web search isn't connected for this ally. Connect it in Account → Connections."
)
NOT_GRANTED = "Web search is off for this ally. Turn it on in Account → Connections."
KEY_REJECTED = "The web search key was rejected. Ask the user to replace it in Account → Connections."
RATE_LIMITED = (
    "The web search provider is rate limiting requests. Try again in a minute."
)
UNAVAILABLE = "Web search is temporarily unavailable. Try again later."
INVALID = "Web search rejected the request. Check the query, limit and URLs."


def _page(url, title="", content="", **extra):
    return {
        "url": url,
        "title": title,
        "content": content,
        "raw_content": "",
        "metadata": {},
        **extra,
    }


PROVIDERS = {
    "parallel": {
        "search_url": "https://api.parallel.ai/v1beta/search",
        "extract_url": "https://api.parallel.ai/v1beta/extract",
        "header": "x-api-key",
        "auth": KEY,
        "static_headers": {"parallel-beta": "search-extract-2025-10-10"},
        "extract_body": {"urls": URLS, "full_content": True},
        "search_reply": {
            "search_id": "s-1",
            "results": [
                {"url": PAGE, "title": "Alpha", "excerpts": ["First", "excerpt"]}
            ],
        },
        "extract_reply": {
            "results": [
                {
                    "url": PAGE,
                    "title": "Alpha",
                    "excerpts": [],
                    "full_content": "Full page text",
                }
            ],
            "errors": [
                {"url": OTHER_PAGE, "error_type": "fetch_error", "content": "blocked"}
            ],
        },
        "hits": [
            {
                "url": PAGE,
                "title": "Alpha",
                "description": "First excerpt",
                "position": 1,
            }
        ],
        "pages": [
            _page(PAGE, "Alpha", "Full page text"),
            _page(OTHER_PAGE, error=web_search_backends.PAGE_FAILED),
        ],
    },
    "tavily": {
        "search_url": "https://api.tavily.com/search",
        "extract_url": "https://api.tavily.com/extract",
        "header": "authorization",
        "auth": f"Bearer {KEY}",
        "static_headers": {},
        "extract_body": {"urls": URLS},
        "search_reply": {
            "query": QUERY,
            "results": [{"title": "Alpha", "url": PAGE, "content": "Tavily snippet"}],
        },
        "extract_reply": {
            "results": [{"url": PAGE, "raw_content": "Full page text"}],
            "failed_results": [{"url": OTHER_PAGE, "error": "blocked"}],
        },
        "hits": [
            {
                "url": PAGE,
                "title": "Alpha",
                "description": "Tavily snippet",
                "position": 1,
            }
        ],
        "pages": [
            _page(PAGE, "", "Full page text"),
            _page(OTHER_PAGE, error=web_search_backends.PAGE_FAILED),
        ],
    },
    "exa": {
        "search_url": "https://api.exa.ai/search",
        "extract_url": "https://api.exa.ai/contents",
        "header": "x-api-key",
        "auth": KEY,
        "static_headers": {},
        "extract_body": {
            "urls": URLS,
            "text": {"maxCharacters": web_search_backends.PAGE_CHARS},
        },
        "search_reply": {
            "requestId": "r-1",
            "results": [
                {"title": "Alpha", "url": PAGE, "highlights": ["Exa highlight"]}
            ],
        },
        "extract_reply": {
            "results": [{"url": PAGE, "title": "Alpha", "text": "Full page text"}],
            "statuses": [
                {"id": PAGE, "status": "success", "source": "cached"},
                {
                    "id": OTHER_PAGE,
                    "status": "error",
                    "error": {"tag": "CRAWL_NOT_FOUND", "httpStatusCode": 404},
                },
            ],
        },
        "hits": [
            {
                "url": PAGE,
                "title": "Alpha",
                "description": "Exa highlight",
                "position": 1,
            }
        ],
        "pages": [
            _page(PAGE, "Alpha", "Full page text"),
            _page(OTHER_PAGE, error=web_search_backends.PAGE_FAILED),
        ],
    },
}


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self._offset = 0

    def read1(self, size):
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _reply_for(url):
    for spec in PROVIDERS.values():
        if url == spec["search_url"]:
            return spec["search_reply"]
        if url == spec["extract_url"]:
            return spec["extract_reply"]
    raise AssertionError(url)


class FakeProvider:
    """Records each provider call. Tests set ``status``, ``error`` or ``body`` to fail it."""

    def __init__(self) -> None:
        self.calls = []
        self.status = None
        self.error = None
        self.body = None

    def open(self, request, timeout=None):
        self.calls.append((request, timeout))
        if self.error is not None:
            raise self.error
        if self.status is not None:
            raise HTTPError(
                request.full_url, self.status, "provider", None, io.BytesIO()
            )
        if self.body is not None:
            return FakeResponse(self.body)
        return FakeResponse(json.dumps(_reply_for(request.full_url)).encode())


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(web_search_backends, "_OPENER", fake)
    return fake


@pytest.fixture
def vault(settings):
    settings.ALLOWED_HOSTS = ["testserver"]
    settings.ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN = "test-service-token"
    settings.ALLIES_VAULT_KEYS = Fernet.generate_key().decode()
    return settings


def _connect(workspace, backend="parallel"):
    return IntegrationSecret.objects.create(
        workspace=workspace,
        provider_key=PROVIDER_WEB_SEARCH,
        account_ref_hash=secrets.token_hex(32),
        ciphertext=seal_secret(KEY),
        backend=backend,
        key_hint=KEY[-4:],
    )


def _setup(turn, backend="parallel"):
    secret = _connect(turn["workspace"], backend)
    set_ally_grant(secret=secret, ally=turn["ally"], level="use")
    return secret


@pytest.fixture
def chat_turn(db, dispatch_records, vault):  # noqa: F811
    workspace, binding, _, message = dispatch_records
    with transaction.atomic():
        _ensure_outbox_locked(message)
    outbox = DispatchOutbox.objects.get(message=message)
    return {
        "workspace": workspace,
        "ally": binding.ally,
        "identity": {
            "message_id": str(message.id),
            "binding_id": str(binding.id),
            "command_fingerprint": outbox.command_fingerprint,
        },
    }


def _post(identity, arguments):
    body = {
        **identity,
        "call_id": str(uuid4()),
        "integration": "web_search",
        "arguments": arguments,
    }
    return Client().post(URL, json.dumps(body), content_type="application/json", **AUTH)


def _search(query=QUERY, limit=3):
    return {"action": "search", "query": query, "limit": limit}


def _extract(urls=URLS):
    return {"action": "extract", "urls": urls}


@pytest.mark.django_db
@pytest.mark.parametrize("backend", list(PROVIDERS))
def test_search_returns_the_hermes_shape_and_keeps_the_key_in_the_auth_header(
    chat_turn, provider, backend, caplog
):
    spec = PROVIDERS[backend]
    _setup(chat_turn, backend)

    with caplog.at_level(logging.INFO):
        response = _post(chat_turn["identity"], _search())

    assert response.status_code == 200
    assert response.json() == {"success": True, "data": {"web": spec["hits"]}}
    assert len(provider.calls) == 1
    request, timeout = provider.calls[0]
    assert request.get_method() == "POST"
    assert request.full_url == spec["search_url"]
    assert timeout == web_search.SEARCH_TIMEOUT_SECONDS
    headers = {name.lower(): value for name, value in request.headers.items()}
    assert headers[spec["header"]] == spec["auth"]
    for name, value in spec["static_headers"].items():
        assert headers[name.lower()] == value
    assert KEY not in request.full_url and KEY.encode() not in request.data
    assert KEY not in response.content.decode()

    (record,) = [r for r in caplog.records if r.getMessage() == "web search tool call"]
    assert (record.action, record.backend, record.outcome) == ("search", backend, "ok")
    logs = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert KEY not in logs and QUERY not in logs and PAGE not in logs


@pytest.mark.django_db
@pytest.mark.parametrize("backend", list(PROVIDERS))
def test_extract_returns_page_content_and_reports_failed_pages_per_url(
    chat_turn, provider, backend
):
    spec = PROVIDERS[backend]
    _setup(chat_turn, backend)

    response = _post(chat_turn["identity"], _extract())

    assert response.status_code == 200
    assert response.json() == {"success": True, "data": spec["pages"]}
    request, timeout = provider.calls[0]
    assert request.full_url == spec["extract_url"]
    assert json.loads(request.data) == spec["extract_body"]
    assert timeout == web_search.EXTRACT_TIMEOUT_SECONDS
    headers = {name.lower(): value for name, value in request.headers.items()}
    assert headers[spec["header"]] == spec["auth"]
    for name, value in spec["static_headers"].items():
        assert headers[name.lower()] == value


@pytest.mark.django_db
def test_an_ally_in_an_unconnected_workspace_is_refused_without_a_provider_call(
    chat_turn, provider
):
    secret = _setup(chat_turn)
    web_search.disconnect(secret=secret)

    response = _post(chat_turn["identity"], _search())

    assert response.status_code == 403
    assert response.json() == {
        "success": False,
        "error": "web_search_not_connected",
        "instruction": NOT_CONNECTED,
    }
    assert provider.calls == []


@pytest.mark.django_db
def test_an_ungranted_ally_is_refused_and_a_revoked_grant_applies_on_the_next_call(
    chat_turn, provider
):
    secret = _connect(chat_turn["workspace"])

    refused = _post(chat_turn["identity"], _search())
    assert refused.status_code == 403
    assert refused.json() == {
        "success": False,
        "error": "web_search_not_granted",
        "instruction": NOT_GRANTED,
    }

    set_ally_grant(secret=secret, ally=chat_turn["ally"], level="use")
    assert _post(chat_turn["identity"], _search()).status_code == 200

    revoke_ally_grant(secret=secret, ally=chat_turn["ally"])
    after = _post(chat_turn["identity"], _search())
    assert after.status_code == 403
    assert after.json()["error"] == "web_search_not_granted"
    assert len(provider.calls) == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "search", "query": QUERY, "limit": 0},
        {"action": "search", "query": QUERY, "limit": 11},
        {"action": "search", "query": QUERY, "limit": "5"},
        {"action": "search", "query": "   ", "limit": 3},
        {"action": "search", "query": "q" * 401, "limit": 3},
        {"action": "search", "query": QUERY},
        {"action": "search", "query": QUERY, "limit": 3, "urls": [PAGE]},
        {"action": "search", "query": QUERY, "limit": 3, "extra": True},
        {"action": "extract", "urls": [PAGE] * 6},
        {"action": "extract", "urls": []},
        {"action": "extract", "urls": ["ftp://example.com/file"]},
        {"action": "extract", "urls": ["javascript:alert(1)"]},
        {"action": "extract", "urls": ["https://"]},
        {"action": "extract", "urls": ["https://example.com/" + "a" * 2048]},
        {"action": "extract", "urls": [PAGE], "query": QUERY},
        {"action": "extract"},
        {"action": "status"},
    ],
)
def test_malformed_calls_are_refused_before_any_lookup(chat_turn, provider, arguments):
    response = _post(chat_turn["identity"], arguments)

    assert response.status_code == 422
    assert response.json() == {
        "success": False,
        "error": "invalid_web_search_request",
        "instruction": INVALID,
    }
    assert provider.calls == []


@pytest.mark.django_db
@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_key_is_reported_in_band_and_not_retried(
    chat_turn, provider, status
):
    _setup(chat_turn)
    provider.status = status

    response = _post(chat_turn["identity"], _search())

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "error": "web_search_key_rejected",
        "instruction": KEY_REJECTED,
    }
    assert len(provider.calls) == 1


@pytest.mark.django_db
def test_a_rate_limit_is_reported_in_band_and_never_retried(chat_turn, provider):
    _setup(chat_turn)
    provider.status = 429

    response = _post(chat_turn["identity"], _extract())

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "error": "web_search_rate_limited",
        "instruction": RATE_LIMITED,
    }
    assert len(provider.calls) == 1


OUTAGES = {
    "server-error": {"status": 500},
    "unavailable": {"status": 503},
    "timeout": {"error": TimeoutError("timed out")},
    "unreachable": {"error": URLError("unreachable")},
    "not-json": {"body": b"<html>not json</html>"},
    "wrong-shape": {"body": json.dumps({"unexpected": True}).encode()},
    "oversized": {
        "body": json.dumps(
            {"results": [], "pad": "x" * web_search_backends.MAX_RESPONSE_BYTES}
        ).encode()
    },
}


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["search", "extract"])
@pytest.mark.parametrize("outage", list(OUTAGES.values()), ids=list(OUTAGES))
def test_provider_outages_are_reported_in_band_and_never_retried(
    chat_turn, provider, action, outage
):
    _setup(chat_turn)
    provider.status = outage.get("status")
    provider.error = outage.get("error")
    provider.body = outage.get("body")
    arguments = _search() if action == "search" else _extract()

    response = _post(chat_turn["identity"], arguments)

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "error": "web_search_unavailable",
        "instruction": UNAVAILABLE,
    }
    assert len(provider.calls) == 1


@pytest.mark.django_db
def test_a_vault_failure_is_reported_in_band_without_a_provider_call(
    chat_turn, provider, monkeypatch
):
    _setup(chat_turn)

    def unreadable(token):
        raise VaultUnavailable("secret unreadable")

    monkeypatch.setattr(web_search, "unseal_secret", unreadable)

    response = _post(chat_turn["identity"], _search())

    assert response.status_code == 200
    assert response.json()["error"] == "web_search_unavailable"
    assert provider.calls == []


FILLERS = {"ascii": "a", "cjk": "界", "emoji": "😀"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("filler", "trimmed"),
    [(FILLERS["ascii"], False), (FILLERS["cjk"], False), (FILLERS["emoji"], True)],
    ids=list(FILLERS),
)
def test_search_response_stays_within_the_byte_budget(
    chat_turn, provider, filler, trimmed
):
    _setup(chat_turn)
    results = [
        {"url": f"{PAGE}/{index}", "title": filler * 300, "excerpts": [filler * 500]}
        for index in range(10)
    ]
    provider.body = json.dumps({"results": results}, ensure_ascii=False).encode()

    response = _post(chat_turn["identity"], _search(limit=10))

    assert response.status_code == 200
    assert len(response.content) <= web_search.RESPONSE_BUDGET_BYTES
    hits = response.json()["data"]["web"]
    assert [hit["position"] for hit in hits] == list(range(1, len(hits) + 1))
    assert all(len(hit["title"]) <= 300 for hit in hits)
    assert all(len(hit["description"]) <= 500 for hit in hits)
    assert (len(hits) < 10) == trimmed


@pytest.mark.django_db
@pytest.mark.parametrize("filler", list(FILLERS.values()), ids=list(FILLERS))
def test_extract_pages_share_the_byte_budget_evenly(chat_turn, provider, filler):
    _setup(chat_turn)
    urls = [f"{PAGE}/{index}" for index in range(5)]
    results = [
        {
            "url": url,
            "title": "Long page",
            "excerpts": [],
            "full_content": filler * 20_000,
        }
        for url in urls
    ]
    provider.body = json.dumps({"results": results}, ensure_ascii=False).encode()

    response = _post(chat_turn["identity"], _extract(urls))

    assert response.status_code == 200
    assert len(response.content) <= web_search.RESPONSE_BUDGET_BYTES
    pages = response.json()["data"]
    assert [page["url"] for page in pages] == urls
    lengths = {len(page["content"]) for page in pages}
    assert len(lengths) == 1
    assert 0 < lengths.pop() <= web_search.PAGE_CHARS


@pytest.mark.django_db
def test_content_within_the_budget_is_returned_whole(chat_turn, provider):
    _setup(chat_turn)
    page_text = "界" * 1_000
    provider.body = json.dumps(
        {
            "results": [
                {
                    "url": PAGE,
                    "title": "Short",
                    "excerpts": [],
                    "full_content": page_text,
                }
            ]
        },
        ensure_ascii=False,
    ).encode()

    response = _post(chat_turn["identity"], _extract([PAGE]))

    assert response.json()["data"][0]["content"] == page_text


def _routine_identity(turn):
    return {
        "run_id": str(turn["run_id"]),
        "binding_id": str(turn["binding_id"]),
        "command_fingerprint": turn["command_fingerprint"],
    }


@pytest.mark.django_db
def test_a_routine_run_searches_under_its_dispatch_identity(
    routine_turn,  # noqa: F811
    vault,
    provider,
):
    secret = _connect(routine_turn["workspace"])
    set_ally_grant(secret=secret, ally=routine_turn["routine"].ally, level="use")

    response = _post(_routine_identity(routine_turn), _search())

    assert response.status_code == 200
    assert response.json()["data"]["web"] == PROVIDERS["parallel"]["hits"]


@pytest.mark.django_db
def test_a_routine_run_without_a_grant_is_refused(routine_turn, vault, provider):  # noqa: F811
    _connect(routine_turn["workspace"])

    response = _post(_routine_identity(routine_turn), _search())

    assert response.status_code == 403
    assert response.json()["error"] == "web_search_not_granted"
    assert provider.calls == []
