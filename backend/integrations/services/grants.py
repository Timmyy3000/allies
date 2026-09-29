"""Per-Ally Google grants and account disconnect.

Grants are read live on every tool call — never cached.
``check_grant`` returns the operations the Ally may perform.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from ..exceptions import (
    IntegrationConflict,
    IntegrationInvalid,
    IntegrationUnavailable,
)
from ..models import (
    GRANT_READ,
    GRANT_SEND,
    GRANT_WRITE,
    PROVIDER_CALENDAR,
    PROVIDER_GMAIL,
    PROVIDER_GRANT_LEVELS,
    AllyIntegrationGrant,
)
from .google_oauth import gmail_enabled

logger = logging.getLogger(__name__)

_GMAIL_READ = ("gmail search", "gmail get")
_CALENDAR_READ = ("calendar list", "calendar get")
ALLOWLISTS = {
    (PROVIDER_GMAIL, GRANT_READ): _GMAIL_READ,
    (PROVIDER_GMAIL, GRANT_SEND): (
        *_GMAIL_READ,
        "gmail send",
        "gmail reply",
        "gmail organize",
    ),
    (PROVIDER_CALENDAR, GRANT_READ): _CALENDAR_READ,
    (PROVIDER_CALENDAR, GRANT_WRITE): (*_CALENDAR_READ, "calendar write"),
}


def _require_enabled() -> None:
    if not gmail_enabled():
        raise IntegrationUnavailable("gmail integration disabled")


@dataclass(frozen=True)
class GrantDecision:
    allowed: bool
    grant_generation: int
    tool_allowlist: tuple[str, ...] = ()
    reason_code: str | None = None


def _live_grant(secret, ally) -> AllyIntegrationGrant | None:
    return (
        AllyIntegrationGrant.objects.filter(secret=secret, ally=ally)
        .order_by("-grant_generation")
        .first()
    )


def set_ally_grant(
    *, secret, ally, level: str, created_by=None
) -> AllyIntegrationGrant:
    _require_enabled()
    if level not in PROVIDER_GRANT_LEVELS[secret.provider_key]:
        raise IntegrationInvalid("unknown grant level")
    if str(ally.workspace_id) != str(secret.workspace_id):
        raise IntegrationInvalid("ally is outside the connection workspace")
    if secret.revoked_at is not None:
        raise IntegrationConflict("connection revoked")
    with transaction.atomic():
        locked_secret = secret.__class__.objects.select_for_update().get(pk=secret.pk)
        grant, created = AllyIntegrationGrant.objects.select_for_update().get_or_create(
            secret=locked_secret,
            ally=ally,
            defaults={
                "level": level,
                "grant_generation": locked_secret.generation_epoch,
                "created_by": created_by,
            },
        )
        if not created and grant.level != level:
            grant.level = level
            grant.grant_generation = locked_secret.generation_epoch
            if created_by is not None:
                grant.created_by = created_by
            grant.save(
                update_fields=["level", "grant_generation", "created_by", "updated_at"]
            )
    return grant


def revoke_ally_grant(*, secret, ally) -> int:
    _require_enabled()
    with transaction.atomic():
        locked_secret = secret.__class__.objects.select_for_update().get(pk=secret.pk)
        grant = (
            AllyIntegrationGrant.objects.select_for_update()
            .filter(secret=locked_secret, ally=ally)
            .first()
        )
        if grant is None:
            return 0
        generation = grant.grant_generation
        grant.delete()
        locked_secret.generation_epoch += 1
        locked_secret.save(update_fields=["generation_epoch"])
    return generation


def check_grant(*, secret, ally) -> GrantDecision:
    _require_enabled()
    if secret.revoked_at is not None:
        return GrantDecision(
            allowed=False, grant_generation=0, reason_code="connection_revoked"
        )
    grant = _live_grant(secret, ally)
    if grant is None:
        return GrantDecision(
            allowed=False, grant_generation=0, reason_code="grant_missing"
        )
    allowlist = ALLOWLISTS.get((secret.provider_key, grant.level))
    if allowlist is None:
        return GrantDecision(
            allowed=False,
            grant_generation=grant.grant_generation,
            reason_code="grant_level_unknown",
        )
    return GrantDecision(
        allowed=True,
        grant_generation=grant.grant_generation,
        tool_allowlist=allowlist,
    )


@dataclass(frozen=True)
class DisconnectResult:
    status: str


def disconnect_account(*, secret) -> DisconnectResult:
    _require_enabled()
    from .google_oauth import revoke_at_google
    from .vault import unseal_refresh_token

    with transaction.atomic():
        locked = secret.__class__.objects.select_for_update().get(pk=secret.pk)
        if locked.revoked_at is not None and not bytes(locked.ciphertext):
            return DisconnectResult(status="already_cleaned")
        try:
            refresh_token = unseal_refresh_token(
                locked.ciphertext, key_version=locked.key_version
            )
        except IntegrationUnavailable:
            refresh_token = ""
        if locked.revoked_at is None:
            locked.revoked_at = timezone.now()
            locked.save(update_fields=["revoked_at"])
        locked.ally_grants.all().delete()
    if refresh_token and not revoke_at_google(refresh_token):
        logger.warning(
            "google revoke failed",
            extra={"secret_id": str(locked.id)},
        )
        return DisconnectResult(status="repair_required")
    wiped = secret.__class__.objects.filter(
        pk=locked.pk, revoked_at=locked.revoked_at
    ).update(ciphertext=b"", scope_set=[])
    if wiped == 0:
        logger.warning(
            "disconnect wipe skipped",
            extra={"secret_id": str(locked.id)},
        )
        return DisconnectResult(status="repair_required")
    return DisconnectResult(status="deprovisioned")
