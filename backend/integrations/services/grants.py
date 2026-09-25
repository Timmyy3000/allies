"""Per-Ally Gmail grants and per-execution credential minting.

Grants are read live on every dispatch — never cached. ``check_gmail_grant``
emits the execution's allowed-operation list (SIM-001: no requested-tool
input at the dispatcher, which holds the whole command rather than later
skill arguments). The single provider-neutral gate at the actual tool-call
boundary enforces that list plus the live generation.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from ..exceptions import (
    GrantDenied,
    IntegrationConflict,
    IntegrationInvalid,
    IntegrationUnavailable,
)
from ..models import GRANT_LEVELS, GRANT_READ, GRANT_SEND, AllyIntegrationGrant
from .google_oauth import MintedAccess, gmail_enabled, refresh_access_token

logger = logging.getLogger(__name__)

READ_ALLOWLIST = ("gmail search", "gmail get")
SEND_ALLOWLIST = ("gmail search", "gmail get", "gmail send", "gmail reply")


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
    if level not in GRANT_LEVELS:
        raise IntegrationInvalid("unknown grant level")
    if str(ally.workspace_id) != str(secret.workspace_id):
        raise IntegrationInvalid("ally is outside the connection workspace")
    if secret.revoked_at is not None:
        raise IntegrationConflict("gmail connection revoked")
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
    _scrub_refs_for_grant(secret, ally)
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
    _scrub_refs_for_grant(secret, ally)
    return generation


def check_gmail_grant(*, secret, ally) -> GrantDecision:
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
    if grant.level == GRANT_SEND:
        allowlist = SEND_ALLOWLIST
    elif grant.level == GRANT_READ:
        allowlist = READ_ALLOWLIST
    else:
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
class MintedCredential:
    ref: str
    access_token: str
    expires_at: object
    tool_allowlist: tuple[str, ...] = ()
    grant_generation: int = 0


_registry: dict[str, tuple[str, float, str, str, int]] = {}
_registry_lock = threading.Lock()


def _register_ref(
    ref: str, access_token: str, expires_at, *, secret, ally, generation: int
) -> None:
    with _registry_lock:
        _registry[ref] = (
            access_token,
            expires_at.timestamp(),
            str(secret.id),
            str(ally.id),
            generation,
        )
        now = time.time()
        stale = [key for key, (_, expiry, *_rest) in _registry.items() if expiry <= now]
        for key in stale:
            del _registry[key]


def _scrub_refs_for_grant(secret, ally) -> int:
    secret_id, ally_id = str(secret.id), str(ally.id)
    with _registry_lock:
        doomed = [
            key
            for key, (_, _, ref_secret, ref_ally, _gen) in _registry.items()
            if ref_secret == secret_id and ref_ally == ally_id
        ]
        for key in doomed:
            del _registry[key]
        return len(doomed)


def resolve_credential_ref(ref: str, *, command_id: str) -> str:
    from ..models import AllyIntegrationGrant as GrantModel

    parts = ref.split(":")
    if len(parts) != 4 or parts[0] != "gmail" or parts[2] != command_id:
        raise GrantDenied("credential reference rejected")
    with _registry_lock:
        entry = _registry.get(ref)
        if entry is None:
            raise GrantDenied("unknown credential reference")
        access_token, expiry, secret_id, ally_id, generation = entry
        if expiry <= time.time():
            del _registry[ref]
            raise GrantDenied("expired credential reference")
    live = (
        GrantModel.objects.select_related("secret")
        .filter(secret_id=secret_id, ally_id=ally_id)
        .first()
    )
    if live is None or live.grant_generation != generation:
        raise GrantDenied("credential grant changed")
    if live.secret.revoked_at is not None:
        raise GrantDenied("gmail connection revoked")
    return access_token


def mint_execution_credential(
    *, secret, ally, command_id: str, minted: MintedAccess | None = None
) -> MintedCredential:
    _require_enabled()
    if not command_id or len(command_id) > 128:
        raise IntegrationInvalid("command identity invalid")
    decision = check_gmail_grant(secret=secret, ally=ally)
    if not decision.allowed:
        raise GrantDenied(decision.reason_code or "grant_denied")
    fresh = minted if minted is not None else refresh_access_token(secret)
    ref = f"gmail:{secret.id}:{command_id}:{secrets.token_hex(8)}"
    credential = MintedCredential(
        ref=ref,
        access_token=fresh.access_token,
        expires_at=fresh.expires_at,
        tool_allowlist=decision.tool_allowlist,
        grant_generation=decision.grant_generation,
    )
    _register_ref(
        ref,
        fresh.access_token,
        fresh.expires_at,
        secret=secret,
        ally=ally,
        generation=decision.grant_generation,
    )
    logger.info(
        "gmail credential minted",
        extra={
            "secret_id": str(secret.id),
            "expires_at": fresh.expires_at.isoformat(),
            "allowlist_hash": hashlib.sha256(
                ",".join(decision.tool_allowlist).encode()
            ).hexdigest()[:16],
            "grant_generation": decision.grant_generation,
        },
    )
    return credential


def _scrub_refs_for_secret(secret) -> int:
    prefix = f"gmail:{secret.id}:"
    with _registry_lock:
        doomed = [key for key in _registry if key.startswith(prefix)]
        for key in doomed:
            del _registry[key]
        return len(doomed)


@dataclass(frozen=True)
class DisconnectResult:
    status: str
    scrubbed_refs: int


def disconnect_gmail_account(*, secret) -> DisconnectResult:
    _require_enabled()
    from .google_oauth import revoke_at_google
    from .vault import unseal_refresh_token

    with transaction.atomic():
        locked = secret.__class__.objects.select_for_update().get(pk=secret.pk)
        if locked.revoked_at is not None and not bytes(locked.ciphertext):
            return DisconnectResult(status="already_cleaned", scrubbed_refs=0)
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
    scrubbed = _scrub_refs_for_secret(locked)
    if refresh_token and not revoke_at_google(refresh_token):
        logger.warning(
            "gmail google-revoke failed",
            extra={"secret_id": str(locked.id)},
        )
        return DisconnectResult(status="repair_required", scrubbed_refs=scrubbed)
    wiped = secret.__class__.objects.filter(
        pk=locked.pk, revoked_at=locked.revoked_at
    ).update(ciphertext=b"", scope_set=[])
    if wiped == 0:
        logger.warning(
            "gmail disconnect wipe skipped",
            extra={"secret_id": str(locked.id)},
        )
        return DisconnectResult(status="repair_required", scrubbed_refs=scrubbed)
    return DisconnectResult(status="deprovisioned", scrubbed_refs=scrubbed)
