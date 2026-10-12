"""Workspace web search connection: a provider key checked live, then sealed.

The key is sealed with ``common.vault`` and never stored in plaintext. It is
sent to the provider only in the request's auth header. Replacing the key
updates the live row in place, so ally grants survive.
"""

from __future__ import annotations

import logging
import re
import secrets

from django.db import IntegrityError, transaction
from django.utils import timezone

from common.vault import require_configured_keys, seal_secret

from ..exceptions import (
    IntegrationConflict,
    IntegrationInvalid,
    WebSearchCheckFailed,
    WebSearchKeyRejected,
)
from ..models import PROVIDER_WEB_SEARCH, IntegrationSecret
from . import web_search_backends
from .web_search_backends import BACKENDS, ProviderError

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
