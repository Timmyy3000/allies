"""Authorize and forward privacy-safe runtime wake hints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from django.conf import settings
from django.utils import timezone

from allies.exceptions import RuntimeIntentInvalid
from allies.gateways.foundry import request_runtime_intent as forward_runtime_intent
from auths.exceptions import WorkspaceAccessDenied
from auths.models import User
from auths.throttle import check_rate_limit
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
        limit=int(getattr(settings, "ALLIES_RUNTIME_INTENT_RATE_LIMIT", 20)),
        period=int(getattr(settings, "ALLIES_RUNTIME_INTENT_RATE_PERIOD_SECONDS", 60)),
    )

    receipt = forward_runtime_intent(
        workspace_id=workspace.id,
        intent=intent,
        received_at=now or timezone.now(),
        idempotency_key=parsed_key,
    )
    return RuntimeIntentResult(receipt.status)
