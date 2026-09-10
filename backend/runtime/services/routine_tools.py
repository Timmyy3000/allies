"""Attempt-scoped routine management through the existing Cloud control plane."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
from uuid import UUID

from django.conf import settings
from django.core import signing
from django.db import transaction

from runtime.exceptions import RuntimeAuthorizationError, RuntimeValidationError
from runtime.models import Attempt, AttemptStatus
from runtime.services.event_delivery import _NoRedirect, _validated_cloud_url
from runtime.services.leases import _authorize_attempt_mutation
from runtime.services.validation import digest_lease_token

_SALT = "allies.routine-tool.v1"
_MAX_BYTES = 64 * 1024


def routine_tool_token(claim):
    if claim.routine_id is not None:
        return None
    attempt = Attempt.objects.select_related("execution").get(pk=claim.attempt_id)
    if not attempt.execution.cloud_message_id:
        return None
    return signing.dumps(
        {
            "attempt_id": str(claim.attempt_id),
            "lease_id": str(claim.lease_id),
            "token_digest": digest_lease_token(claim.lease_token),
            "machine_generation": attempt.machine_generation,
        },
        salt=_SALT,
    )


def call_routine_tool(token: str, *, call_id: UUID, arguments: dict):
    try:
        capability = signing.loads(token, salt=_SALT, max_age=86400)
    except (signing.BadSignature, ValueError, TypeError) as exc:
        raise RuntimeAuthorizationError("routine capability invalid") from exc
    with transaction.atomic():
        authorization = _authorize_attempt_mutation(**capability)
        if authorization.status not in {AttemptStatus.LEASED, AttemptStatus.RUNNING}:
            raise RuntimeAuthorizationError("routine capability inactive")
        attempt = Attempt.objects.select_related("execution").get(
            pk=authorization.attempt_id
        )
        execution = attempt.execution
        if not execution.cloud_message_id or not execution.cloud_binding_id:
            raise RuntimeAuthorizationError("routine capability unavailable")
        body = json.dumps(
            {
                "message_id": str(execution.cloud_message_id),
                "binding_id": str(execution.cloud_binding_id),
                "command_fingerprint": execution.command_fingerprint,
                "call_id": str(call_id),
                "arguments": arguments,
            }
        ).encode()
    if len(body) > _MAX_BYTES:
        raise RuntimeValidationError("routine request too large")
    origin = _validated_cloud_url(getattr(settings, "ALLIES_CLOUD_URL", None))
    service_token = getattr(settings, "ALLIES_CLOUD_EVENT_SERVICE_TOKEN", None)
    if not origin or not service_token:
        return 503, {"error": "routine_service_unavailable"}
    request = Request(
        f"{origin}/api/v1/internal/foundry/routines/tool",
        data=body,
        headers={
            "Authorization": f"Bearer {service_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        try:
            response = build_opener(_NoRedirect).open(request, timeout=10)
        except HTTPError as exc:
            response = exc
        with response:
            status = response.status
            raw = response.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES or status not in {200, 403, 409, 413, 422}:
            return 503, {"error": "routine_service_unavailable"}
        result = json.loads(raw)
        if not isinstance(result, dict):
            return 503, {"error": "routine_service_unavailable"}
        return status, result
    except (URLError, OSError, ValueError):
        return 503, {
            "error": "routine_service_unavailable",
            "instruction": "Retry the same call identity; do not claim it was saved.",
        }
