"""Resolve Cloud-held provider keys for an authenticated runtime.

Values transit this process only: they are never persisted, logged, or put in
exception text. The workspace comes from the runtime credential, never from
the request, and only refs currently bound to one of its profiles are asked.
"""

from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from django.conf import settings

from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeNotFoundError,
    RuntimeValidationError,
)
from runtime.models import RuntimeProfile, Workspace

from .event_delivery import _NoRedirect, _validated_cloud_url
from .runtime_auth import RuntimeContext

MAX_BROKER_RESPONSE_BYTES = 4 * 1024
MAX_WORKSPACE_PROFILES = 500
_REFERENCE = re.compile(r"allies-key://[a-z0-9-]{1,32}/[0-9a-f-]{36}", re.IGNORECASE)


def resolve_brokered_credential(context: RuntimeContext, reference: object) -> str:
    if not isinstance(reference, str) or not _REFERENCE.fullmatch(reference):
        raise RuntimeValidationError("credential reference is invalid")
    workspace = Workspace.objects.filter(pk=context.workspace_id).first()
    if workspace is None or not _bound_in_workspace(workspace, reference):
        raise RuntimeNotFoundError("credential unavailable")
    return _ask_cloud(workspace.tenant_ref, reference)


def _bound_in_workspace(workspace: Workspace, reference: str) -> bool:
    rows = RuntimeProfile.objects.filter(workspace=workspace).values_list(
        "model_override", "seed_payload"
    )[:MAX_WORKSPACE_PROFILES]
    for override, seed in rows:
        binding = override.get("binding") if isinstance(override, dict) else None
        for refs in (
            binding.get("key_refs") if isinstance(binding, dict) else None,
            seed.get("credential_refs") if isinstance(seed, dict) else None,
        ):
            if isinstance(refs, dict) and reference in refs.values():
                return True
    return False


def _ask_cloud(tenant_ref: str, reference: str) -> str:
    base_url = _validated_cloud_url(getattr(settings, "ALLIES_CLOUD_URL", None))
    token = getattr(settings, "ALLIES_CLOUD_CREDENTIAL_TOKEN", None)
    if not base_url or not token:
        raise RuntimeConflictError("credential broker unavailable")
    body = json.dumps(
        {"version": 1, "workspace_id": tenant_ref, "reference": reference},
        separators=(",", ":"),
    ).encode()
    request = Request(
        f"{base_url.rstrip('/')}/api/v1/internal/credentials/resolve",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with build_opener(_NoRedirect).open(
            request,
            timeout=float(getattr(settings, "ALLIES_CLOUD_CREDENTIAL_TIMEOUT", 5.0)),
        ) as response:
            raw = response.read(MAX_BROKER_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        if exc.code == 404:
            raise RuntimeNotFoundError("credential unavailable") from None
        raise RuntimeConflictError("credential broker unavailable") from None
    except (TimeoutError, URLError, OSError):
        raise RuntimeConflictError("credential broker unavailable") from None
    if len(raw) > MAX_BROKER_RESPONSE_BYTES:
        raise RuntimeConflictError("credential broker response is invalid")
    try:
        value = json.loads(raw.decode("utf-8")).get("value")
    except (UnicodeDecodeError, ValueError, AttributeError):
        value = None
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        raise RuntimeConflictError("credential broker response is invalid")
    return value
