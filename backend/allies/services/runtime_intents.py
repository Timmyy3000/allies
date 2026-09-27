"""Authorize and forward privacy-safe runtime wake hints."""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from allies.exceptions import FoundryGatewayRetryable, RuntimeIntentInvalid
from allies.gateways.foundry import request_runtime_intent as forward_runtime_intent
from allies.models import AllyDeletionState
from allies.services.timing import readiness_phase
from auths.config import digest_key
from auths.exceptions import WorkspaceAccessDenied
from auths.models import User
from auths.throttle import ThrottleUnavailable, check_rate_limit
from common.uuids import canonical_uuid
from workspaces.capabilities import Capability, capabilities_for_role
from workspaces.models import Membership, MembershipStatus, RuntimeIntentMode

RuntimeIntentStatus = Literal[
    "disabled",
    "already_ready",
    "waking",
    "ready",
    "first_provision_required",
    "rate_limited",
    "failed",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RuntimeIntentResult:
    status: RuntimeIntentStatus


def _validated_key(value: UUID | str) -> UUID:
    try:
        return canonical_uuid(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeIntentInvalid("idempotency key is invalid") from exc


def _validate_timestamp(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise RuntimeIntentInvalid("occurred_at must include a timezone")
    if value.utcoffset() is None:
        raise RuntimeIntentInvalid("occurred_at must include a timezone")
    return value


def _workspace_intent_cache_key(*, user_id, workspace_id, idempotency_key: UUID) -> str:
    identity = f"{user_id}:{workspace_id}:{idempotency_key}".encode()
    digest = hmac.new(digest_key(), identity, hashlib.sha256).hexdigest()[:32]
    return f"allies:runtime-intent:workspace:{digest}"


def request_runtime_intent(
    *,
    user: User,
    ally_id: UUID | str,
    intent: str,
    occurred_at: datetime,
    idempotency_key: UUID | str,
    now: datetime | None = None,
) -> RuntimeIntentResult:
    """Apply Cloud policy before sending a content-free hint to Foundry."""

    try:
        parsed_ally_id = canonical_uuid(ally_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("ally unavailable") from exc
    if intent != "composing_started":
        raise RuntimeIntentInvalid("runtime intent is invalid")
    _validate_timestamp(occurred_at)
    parsed_key = _validated_key(idempotency_key)

    # The join proves Ally existence, active membership, and Workspace scope in
    # one query; no Ally or user-authored fields cross the Foundry boundary.
    membership = (
        Membership.objects.select_related("workspace")
        .filter(
            user=user,
            status=MembershipStatus.ACTIVE,
            workspace__is_active=True,
            workspace__allies__pk=parsed_ally_id,
            workspace__allies__deletion_state=AllyDeletionState.ACTIVE,
        )
        .first()
    )
    if (
        membership is None
        or Capability.WORKSPACE_WRITE.value
        not in capabilities_for_role(membership.role)
    ):
        raise WorkspaceAccessDenied("workspace denied")

    workspace = membership.workspace
    if not getattr(
        settings, "ALLIES_RUNTIME_INTENT_ENABLED", False
    ) or workspace.runtime_intent_mode not in {
        RuntimeIntentMode.COMPOSING,
        RuntimeIntentMode.OPEN,
    }:
        return RuntimeIntentResult("disabled")

    check_rate_limit(
        scope="runtime-intent-user",
        identity=str(user.id),
        limit=int(getattr(settings, "ALLIES_RUNTIME_INTENT_RATE_LIMIT", 60)),
        period=int(getattr(settings, "ALLIES_RUNTIME_INTENT_RATE_PERIOD_SECONDS", 60)),
    )

    with readiness_phase(
        "wake.forward",
        workspace_id=str(workspace.id),
        correlation_id=str(parsed_key),
    ) as timing:
        receipt = forward_runtime_intent(
            workspace_id=workspace.id,
            intent=intent,
            received_at=now or timezone.now(),
            idempotency_key=parsed_key,
        )
        timing["outcome"] = receipt.status
    return RuntimeIntentResult(receipt.status)


def request_workspace_runtime_intent(
    *,
    user: User,
    intent: str,
    occurred_at: datetime,
    idempotency_key: UUID | str,
    now: datetime | None = None,
) -> RuntimeIntentResult:
    """Wake the authenticated principal's workspace before Ally creation."""

    if intent != "ally_creation_started":
        raise RuntimeIntentInvalid("runtime intent is invalid")
    _validate_timestamp(occurred_at)
    parsed_key = _validated_key(idempotency_key)
    membership = (
        Membership.objects.select_related("workspace")
        .filter(
            user=user,
            status=MembershipStatus.ACTIVE,
            workspace__owner_id=user.id,
            workspace__is_active=True,
        )
        .order_by("workspace_id")
        .first()
    )
    if (
        membership is None
        or Capability.WORKSPACE_WRITE.value
        not in capabilities_for_role(membership.role)
    ):
        raise WorkspaceAccessDenied("workspace denied")

    workspace = membership.workspace
    if not getattr(settings, "ALLIES_RUNTIME_INTENT_ENABLED", False) or (
        workspace.runtime_intent_mode
        not in {RuntimeIntentMode.COMPOSING, RuntimeIntentMode.OPEN}
    ):
        return RuntimeIntentResult("disabled")

    cache_key = _workspace_intent_cache_key(
        user_id=user.id,
        workspace_id=workspace.id,
        idempotency_key=parsed_key,
    )
    ttl = int(getattr(settings, "ALLIES_RUNTIME_INTENT_DEDUPE_TTL_SECONDS", 600))
    try:
        first_request = cache.add(cache_key, "pending", timeout=ttl)
        if not first_request:
            cached_status = cache.get(cache_key)
            if cached_status in RuntimeIntentStatus.__args__:
                return RuntimeIntentResult(cached_status)
            raise FoundryGatewayRetryable("runtime intent is still pending")
    except FoundryGatewayRetryable:
        raise
    except Exception as exc:
        raise ThrottleUnavailable("runtime intent cache unavailable") from exc

    try:
        check_rate_limit(
            scope="runtime-intent-user",
            identity=str(user.id),
            limit=int(getattr(settings, "ALLIES_RUNTIME_INTENT_RATE_LIMIT", 60)),
            period=int(
                getattr(settings, "ALLIES_RUNTIME_INTENT_RATE_PERIOD_SECONDS", 60)
            ),
        )
        check_rate_limit(
            scope="runtime-intent-workspace",
            identity=str(workspace.id),
            limit=int(
                getattr(settings, "ALLIES_RUNTIME_INTENT_WORKSPACE_RATE_LIMIT", 5)
            ),
            period=int(
                getattr(
                    settings,
                    "ALLIES_RUNTIME_INTENT_WORKSPACE_RATE_PERIOD_SECONDS",
                    60,
                )
            ),
        )
        with readiness_phase(
            "creation_wake.forward",
            workspace_id=str(workspace.id),
            correlation_id=str(parsed_key),
        ) as timing:
            receipt = forward_runtime_intent(
                workspace_id=workspace.id,
                intent=intent,
                received_at=now or timezone.now(),
                idempotency_key=parsed_key,
            )
            timing["outcome"] = receipt.status
    except Exception:
        try:
            cache.delete(cache_key)
        except Exception:  # noqa: BLE001 - preserve the original request failure.
            logger.debug("runtime intent failure marker could not be stored")
        raise
    try:
        cache.set(cache_key, receipt.status, timeout=ttl)
    except Exception as exc:
        try:
            cache.delete(cache_key)
        except Exception:  # noqa: BLE001 - preserve the cache failure.
            logger.debug("runtime intent pending marker could not be cleared")
        raise ThrottleUnavailable("runtime intent cache unavailable") from exc
    return RuntimeIntentResult(receipt.status)
