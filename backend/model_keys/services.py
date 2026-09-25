"""Connect, select, disconnect, sync, and broker model keys.

Every product entry point resolves the workspace through membership and
capability first. Foundry calls happen outside transactions: rows record the
desired state, ``push_selection`` sends it, and a compare-and-set on
``revision`` keeps a slow push from overwriting a newer choice.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from allies.gateways import foundry
from allies.models import Ally, AllyDeletionState, BindingStatus
from common.uuids import canonical_uuid
from common.vault import VaultUnavailable, seal_secret, unseal_secret
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability

from .models import (
    PROVIDERS,
    REASONING_LEVELS,
    REFERENCE_PREFIX,
    AllyModelSelection,
    ModelKey,
    SelectionStatus,
)

logger = logging.getLogger(__name__)

MAX_SYNC_ATTEMPTS = 10
SYNC_BATCH = 25
REPAIR_REASON = "binding_repair_required"
_KEY = re.compile(r"[\x21-\x7e]{16,512}")
_MODEL = re.compile(r"[A-Za-z0-9._:/-]{1,128}")


class ModelKeyInvalid(ValueError):
    pass


class ModelKeyMissing(Exception):
    pass


class ModelKeyUnavailable(Exception):
    pass


@dataclass(frozen=True)
class ModelKeysState:
    keys: list[ModelKey]
    selections: list[AllyModelSelection]


def get_state(*, user, workspace_id) -> ModelKeysState:
    context = require_workspace_capability(
        user=user, workspace_id=workspace_id, capability=Capability.PROFILE_READ
    )
    return ModelKeysState(
        keys=list(
            ModelKey.objects.filter(
                workspace=context.workspace, revoked_at__isnull=True
            ).order_by("provider")
        ),
        selections=list(
            AllyModelSelection.objects.select_related("model_key")
            .filter(ally__workspace=context.workspace)
            .order_by("ally_id")
        ),
    )


def connect_key(*, user, workspace_id, provider: str, value: str) -> ModelKey:
    context = require_workspace_capability(
        user=user, workspace_id=workspace_id, capability=Capability.PROFILE_WRITE
    )
    _require_provider(provider)
    if not isinstance(value, str) or not _KEY.fullmatch(value):
        raise ModelKeyInvalid("key is invalid")
    ciphertext = seal_secret(value)
    with transaction.atomic():
        previous = _lock_active_key(context.workspace, provider)
        if previous is not None:
            _revoke(previous)
        key = ModelKey.objects.create(
            workspace=context.workspace,
            provider=provider,
            ciphertext=ciphertext,
            key_hint=value[-4:],
            created_by=user,
        )
        affected = _repoint(previous, key) if previous is not None else []
    _push_now(affected)
    return key


def disconnect_key(*, user, workspace_id, provider: str) -> bool:
    context = require_workspace_capability(
        user=user, workspace_id=workspace_id, capability=Capability.PROFILE_WRITE
    )
    _require_provider(provider)
    with transaction.atomic():
        key = _lock_active_key(context.workspace, provider)
        if key is None:
            return False
        _revoke(key)
        affected = _repoint(key, None)
    _push_now(affected)
    return True


def select_model(
    *,
    user,
    workspace_id,
    ally_id,
    provider: str | None,
    model: str | None = None,
    reasoning: str | None = None,
) -> AllyModelSelection | None:
    context = require_workspace_capability(
        user=user, workspace_id=workspace_id, capability=Capability.PROFILE_WRITE
    )
    try:
        parsed_ally_id = canonical_uuid(ally_id)
    except (TypeError, ValueError):
        raise ModelKeyUnavailable("ally unavailable") from None
    if provider is not None:
        _require_provider(provider)
        if not isinstance(model, str) or not _MODEL.fullmatch(model):
            raise ModelKeyInvalid("model is invalid")
        if reasoning is not None and reasoning not in REASONING_LEVELS:
            raise ModelKeyInvalid("reasoning is invalid")
    with transaction.atomic():
        ally = (
            Ally.objects.select_for_update()
            .select_related("binding")
            .filter(
                workspace=context.workspace,
                pk=parsed_ally_id,
                deletion_state=AllyDeletionState.ACTIVE,
            )
            .first()
        )
        binding = getattr(ally, "binding", None) if ally is not None else None
        if binding is None or binding.status != BindingStatus.BOUND:
            raise ModelKeyUnavailable("ally unavailable")
        selection = (
            AllyModelSelection.objects.select_for_update().filter(ally=ally).first()
        )
        if provider is None:
            if selection is None:
                return None
            desired = {"model_key": None, "model": "", "reasoning": ""}
        else:
            key = _lock_active_key(context.workspace, provider)
            if key is None:
                raise ModelKeyMissing("no key for provider")
            desired = {"model_key": key, "model": model, "reasoning": reasoning or ""}
        if selection is None:
            selection = AllyModelSelection(
                ally=ally,
                foundry_profile_id=foundry.foundry_profile_id(binding.id),
                revision=0,
            )
        for field, value in desired.items():
            setattr(selection, field, value)
        _mark_unsynced(selection)
        selection.save()
    _push_now([selection.id])
    return (
        AllyModelSelection.objects.select_related("model_key")
        .filter(pk=selection.id)
        .first()
    )


def push_selection(selection_id: UUID) -> bool:
    """Send one desired selection to Foundry; True when it is now synced."""

    selection = (
        AllyModelSelection.objects.select_related("model_key")
        .filter(pk=selection_id, synced=False)
        .first()
    )
    if selection is None:
        return True
    revision = selection.revision
    clearing = selection.model_key_id is None
    try:
        if clearing:
            foundry.clear_model_binding(selection.foundry_profile_id)
        else:
            foundry.set_model_binding(
                selection.foundry_profile_id, _binding_body(selection)
            )
    except (
        foundry.FoundryGatewayRetryable,
        foundry.FoundryGatewayUnknownOutcome,
        foundry.FoundryGatewayConflict,
    ):
        _record_failure(selection_id, revision, permanent=False)
        return False
    except (
        foundry.FoundryGatewayInvalid,
        foundry.FoundryGatewayNotFound,
        foundry.FoundryGatewayRejected,
    ) as exc:
        if clearing and isinstance(
            exc, (foundry.FoundryGatewayInvalid, foundry.FoundryGatewayNotFound)
        ):
            # Foundry reports a missing or retiring profile as 404/422; either
            # way it cannot hold a stale key.
            AllyModelSelection.objects.filter(
                pk=selection_id, revision=revision
            ).delete()
            return True
        logger.warning(
            "model selection rejected by foundry",
            extra={"selection_id": str(selection_id), "error": type(exc).__name__},
        )
        _record_failure(selection_id, revision, permanent=True)
        return False
    with transaction.atomic():
        current = (
            AllyModelSelection.objects.select_for_update()
            .filter(pk=selection_id, revision=revision)
            .first()
        )
        if current is None:
            return False
        if clearing:
            current.delete()
        else:
            current.synced = True
            current.synced_at = timezone.now()
            current.sync_attempts = 0
            current.save(update_fields=["synced", "synced_at", "sync_attempts"])
    return True


def sync_pending(limit: int = SYNC_BATCH) -> int:
    ids = list(
        AllyModelSelection.objects.filter(
            synced=False, sync_attempts__lt=MAX_SYNC_ATTEMPTS
        )
        .order_by("updated_at")
        .values_list("id", flat=True)[:limit]
    )
    return sum(1 for selection_id in ids if push_selection(selection_id))


def resolve_for_broker(*, workspace_id: str, reference: str) -> str:
    """Return a key value for Foundry, or raise one indistinguishable error."""

    if not isinstance(reference, str) or not reference.startswith(REFERENCE_PREFIX):
        raise ModelKeyUnavailable("credential unavailable")
    try:
        key_id = canonical_uuid(reference[len(REFERENCE_PREFIX) :])
        tenant = canonical_uuid(workspace_id)
    except (TypeError, ValueError):
        raise ModelKeyUnavailable("credential unavailable") from None
    key = ModelKey.objects.filter(
        pk=key_id,
        workspace_id=tenant,
        revoked_at__isnull=True,
        selections__isnull=False,
    ).first()
    if key is None:
        raise ModelKeyUnavailable("credential unavailable")
    try:
        return unseal_secret(key.ciphertext)
    except VaultUnavailable:
        raise ModelKeyUnavailable("credential unavailable") from None


def note_execution_outcome(
    *, ally_id, event_type: str, reason: str | None, message_created_at: datetime
) -> None:
    """Prove or fail the current selection from a turn started after it synced."""

    if event_type == "execution.completed":
        status = SelectionStatus.CONNECTED
    elif event_type == "execution.stopped" and reason == REPAIR_REASON:
        status = SelectionStatus.DEGRADED
    else:
        return
    AllyModelSelection.objects.filter(
        ally_id=ally_id,
        model_key__isnull=False,
        synced=True,
        synced_at__lte=message_created_at,
    ).exclude(status=status).update(status=status)


def _require_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ModelKeyInvalid("provider is unsupported")


def _lock_active_key(workspace, provider: str) -> ModelKey | None:
    return (
        ModelKey.objects.select_for_update()
        .filter(workspace=workspace, provider=provider, revoked_at__isnull=True)
        .first()
    )


def _revoke(key: ModelKey) -> None:
    key.revoked_at = timezone.now()
    key.ciphertext = b""
    key.save(update_fields=["revoked_at", "ciphertext"])


def _repoint(old: ModelKey, new: ModelKey | None) -> list[UUID]:
    affected = []
    for selection in AllyModelSelection.objects.select_for_update().filter(
        model_key=old
    ):
        selection.model_key = new
        if new is None:
            selection.model = ""
            selection.reasoning = ""
        _mark_unsynced(selection)
        selection.save()
        affected.append(selection.id)
    return affected


def _mark_unsynced(selection: AllyModelSelection) -> None:
    selection.revision += 1
    selection.synced = False
    selection.sync_attempts = 0
    selection.status = SelectionStatus.PENDING


def _binding_body(selection: AllyModelSelection) -> dict:
    key = selection.model_key
    body = {
        "provider": key.provider,
        "model": selection.model,
        "key_refs": {PROVIDERS[key.provider]: key.reference},
    }
    if selection.reasoning:
        body["reasoning"] = selection.reasoning
    return body


def _record_failure(selection_id: UUID, revision: int, *, permanent: bool) -> None:
    with transaction.atomic():
        current = (
            AllyModelSelection.objects.select_for_update()
            .filter(pk=selection_id, revision=revision)
            .first()
        )
        if current is None:
            return
        current.sync_attempts = (
            MAX_SYNC_ATTEMPTS if permanent else current.sync_attempts + 1
        )
        if current.sync_attempts >= MAX_SYNC_ATTEMPTS:
            current.status = SelectionStatus.DEGRADED
        current.save(update_fields=["sync_attempts", "status"])


def _push_now(selection_ids: list[UUID]) -> None:
    for selection_id in selection_ids[:SYNC_BATCH]:
        push_selection(selection_id)
