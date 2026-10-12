"""Workspace web search: a provider key checked live, then sealed, and relayed to granted allies.

The key is sealed with ``common.vault`` and never stored in plaintext. It is
sent to the provider only in the request's auth header. Replacing the key
updates the live row in place, so ally grants survive.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.utils import timezone
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from common.vault import (
    VaultUnavailable,
    require_configured_keys,
    seal_secret,
    unseal_secret,
)

from ..exceptions import (
    IntegrationConflict,
    IntegrationInvalid,
    WebSearchCheckFailed,
    WebSearchKeyRejected,
)
from ..models import PROVIDER_WEB_SEARCH, IntegrationSecret
from . import web_search_backends
from .grants import check_grant
from .turns import resolve_tool_turn
from .web_search_backends import BACKENDS, PAGE_CHARS, ProviderError

logger = logging.getLogger(__name__)

CONNECTION_TEST_QUERY = "allies connection test"
CONNECTION_TEST_TIMEOUT_SECONDS = 8
_KEY = re.compile(r"[\x21-\x7e]{16,512}")
_REJECTED_STATUSES = frozenset({401, 403})


def connect(*, workspace, backend: str, api_key: str) -> IntegrationSecret:
    if backend not in BACKENDS:
        raise IntegrationInvalid("unknown web search backend")
    if not isinstance(api_key, str) or not _KEY.fullmatch(api_key):
        raise IntegrationInvalid("web search key is invalid")
    require_configured_keys()
    _test_key(backend=backend, api_key=api_key)
    ciphertext = seal_secret(api_key)
    key_hint = api_key[-4:]
    with transaction.atomic():
        secret = (
            IntegrationSecret.objects.select_for_update()
            .filter(
                workspace=workspace, provider_key=PROVIDER_WEB_SEARCH, revoked_at=None
            )
            .first()
        )
        if secret is not None:
            secret.backend = backend
            secret.ciphertext = ciphertext
            secret.key_hint = key_hint
            secret.save(update_fields=["backend", "ciphertext", "key_hint"])
            return secret
        try:
            with transaction.atomic():
                return IntegrationSecret.objects.create(
                    workspace=workspace,
                    provider_key=PROVIDER_WEB_SEARCH,
                    account_ref_hash=secrets.token_hex(32),
                    ciphertext=ciphertext,
                    backend=backend,
                    key_hint=key_hint,
                )
        except IntegrityError as exc:
            raise IntegrationConflict("web search connection changed") from exc


def _test_key(*, backend: str, api_key: str) -> None:
    label = BACKENDS[backend]["label"]
    try:
        web_search_backends.search(
            backend=backend,
            api_key=api_key,
            query=CONNECTION_TEST_QUERY,
            limit=1,
            timeout=CONNECTION_TEST_TIMEOUT_SECONDS,
        )
        logger.info("web search connection test passed", extra={"backend": backend})
    except ProviderError as exc:
        if exc.status in _REJECTED_STATUSES:
            logger.info("web search key rejected", extra={"backend": backend})
            raise WebSearchKeyRejected(
                f"{label} rejected this key. Check it and paste it again."
            ) from None
        logger.warning(
            "web search connection test failed",
            extra={"backend": backend, "status": exc.status},
        )
        raise WebSearchCheckFailed(
            "Couldn't check the key right now. Try again."
        ) from None


def disconnect(*, secret: IntegrationSecret) -> str:
    with transaction.atomic():
        locked = IntegrationSecret.objects.select_for_update().get(pk=secret.pk)
        if locked.revoked_at is not None and not bytes(locked.ciphertext):
            return "already_cleaned"
        if locked.revoked_at is None:
            locked.revoked_at = timezone.now()
        locked.ciphertext = b""
        locked.save(update_fields=["revoked_at", "ciphertext"])
        locked.ally_grants.all().delete()
    return "deprovisioned"


SEARCH_TIMEOUT_SECONDS = 15
EXTRACT_TIMEOUT_SECONDS = 20
RESPONSE_BUDGET_BYTES = 60_000
URL_CHARS = 2048
TITLE_CHARS = 300
DESCRIPTION_CHARS = 500
_OPERATION = {"search": "web search", "extract": "web extract"}
_FIELDS = {"search": {"query", "limit"}, "extract": {"urls"}}
_NOT_CONNECTED = (
    "Web search isn't connected for this ally. Connect it in Account → Connections."
)
_NOT_GRANTED = "Web search is off for this ally. Turn it on in Account → Connections."
_KEY_REJECTED = "The web search key was rejected. Ask the user to replace it in Account → Connections."
_RATE_LIMITED = (
    "The web search provider is rate limiting requests. Try again in a minute."
)
_UNAVAILABLE = "Web search is temporarily unavailable. Try again later."
_INVALID = "Web search rejected the request. Check the query, limit and URLs."


class WebSearchToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["search", "extract"]
    query: str | None = Field(default=None, max_length=400)
    limit: int | None = Field(default=None, ge=1, le=10)
    urls: list[str] | None = Field(default=None, min_length=1, max_length=5)

    @field_validator("query")
    @classmethod
    def check_query(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("query is blank")
        return value

    @field_validator("urls")
    @classmethod
    def check_urls(cls, value: list[str] | None) -> list[str] | None:
        for url in value or []:
            parts = urlsplit(url)
            if (
                len(url) > URL_CHARS
                or parts.scheme not in {"http", "https"}
                or not parts.netloc
            ):
                raise ValueError("url must be http(s) and at most 2048 characters")
        return value

    @model_validator(mode="after")
    def action_fields(self):
        if self.model_fields_set - _FIELDS[self.action] - {"action"}:
            raise ValueError("unexpected fields for this action")
        if self.action == "search" and (self.query is None or self.limit is None):
            raise ValueError("query and limit are required")
        if self.action == "extract" and self.urls is None:
            raise ValueError("urls are required")
        return self


def _success(data) -> dict:
    return {"success": True, "data": data}


def _failure(error: str, instruction: str) -> dict:
    return {"success": False, "error": error, "instruction": instruction}


def _unavailable() -> dict:
    return _failure("web_search_unavailable", _UNAVAILABLE)


def _provider_failure(status: int | None) -> dict:
    if status in _REJECTED_STATUSES:
        return _failure("web_search_key_rejected", _KEY_REJECTED)
    if status == 429:
        return _failure("web_search_rate_limited", _RATE_LIMITED)
    return _unavailable()


NOT_CONNECTED = (403, _failure("web_search_not_connected", _NOT_CONNECTED))
NOT_GRANTED = (403, _failure("web_search_not_granted", _NOT_GRANTED))


def _size(body: dict) -> int:
    # Matches JsonResponse's encoding, which is the byte count Foundry reads.
    return len(json.dumps(body, cls=DjangoJSONEncoder).encode())


def _usable(item: dict) -> bool:
    url = item.get("url")
    return isinstance(url, str) and 0 < len(url) <= URL_CHARS


def _clip(item: dict, **limits: int) -> dict:
    clipped = dict(item)
    for key, limit in limits.items():
        value = item.get(key)
        clipped[key] = value[:limit] if isinstance(value, str) else ""
    return clipped


def _fit_search(hits: list[dict]) -> list[dict]:
    while hits and _size(_success({"web": hits})) > RESPONSE_BUDGET_BYTES:
        hits = hits[:-1]
    return hits


def _capped(pages: list[dict], limit: int) -> list[dict]:
    return [{**page, "content": page["content"][:limit]} for page in pages]


def _fit_pages(pages: list[dict]) -> list[dict]:
    # Find the longest shared content cap that fits, so only the longest pages are cut.
    while pages and _size(_success(_capped(pages, 0))) > RESPONSE_BUDGET_BYTES:
        pages = pages[:-1]
    low, high = 0, max((len(page["content"]) for page in pages), default=0)
    while low < high:
        middle = (low + high + 1) // 2
        if _size(_success(_capped(pages, middle))) <= RESPONSE_BUDGET_BYTES:
            low = middle
        else:
            high = middle - 1
    return _capped(pages, low)


def _search(backend: str, api_key: str, args: WebSearchToolRequest) -> dict:
    hits = web_search_backends.search(
        backend=backend,
        api_key=api_key,
        query=args.query,
        limit=args.limit,
        timeout=SEARCH_TIMEOUT_SECONDS,
    )
    clipped = [
        _clip(hit, title=TITLE_CHARS, description=DESCRIPTION_CHARS)
        for hit in hits
        if _usable(hit)
    ]
    return _success({"web": _fit_search(clipped)})


def _extract(backend: str, api_key: str, args: WebSearchToolRequest) -> dict:
    pages = web_search_backends.extract(
        backend=backend,
        api_key=api_key,
        urls=args.urls,
        timeout=EXTRACT_TIMEOUT_SECONDS,
    )
    clipped = [
        _clip(page, title=TITLE_CHARS, content=PAGE_CHARS)
        for page in pages
        if _usable(page)
    ]
    return _success(_fit_pages(clipped))


def _run(secret: IntegrationSecret, args: WebSearchToolRequest) -> dict:
    if secret.backend not in BACKENDS:
        return _unavailable()
    try:
        api_key = unseal_secret(bytes(secret.ciphertext))
        if args.action == "search":
            return _search(secret.backend, api_key, args)
        return _extract(secret.backend, api_key, args)
    except VaultUnavailable:
        return _unavailable()
    except ProviderError as exc:
        return _provider_failure(exc.status)


def execute_web_search_tool(
    *,
    message_id: UUID | None = None,
    run_id: UUID | None = None,
    binding_id: UUID,
    command_fingerprint: str,
    call_id: UUID,
    arguments: dict,
) -> tuple[int, dict]:
    try:
        args = WebSearchToolRequest.model_validate(arguments)
    except ValidationError:
        return 422, _failure("invalid_web_search_request", _INVALID)
    turn = resolve_tool_turn(
        message_id=message_id,
        run_id=run_id,
        binding_id=binding_id,
        command_fingerprint=command_fingerprint,
    )
    ally = turn.ally
    secret = IntegrationSecret.objects.filter(
        workspace=ally.workspace, provider_key=PROVIDER_WEB_SEARCH, revoked_at=None
    ).first()
    if secret is None:
        return NOT_CONNECTED
    decision = check_grant(secret=secret, ally=ally)
    if not decision.allowed or _OPERATION[args.action] not in decision.tool_allowlist:
        return NOT_GRANTED
    started = time.monotonic()
    body = _run(secret, args)
    logger.info(
        "web search tool call",
        extra={
            "action": args.action,
            "backend": secret.backend,
            "outcome": body.get("error", "ok"),
            "latency_ms": round((time.monotonic() - started) * 1000),
        },
    )
    # Provider and vault failures stay 200 so Hermes reads the instruction and does not retry.
    return 200, body
