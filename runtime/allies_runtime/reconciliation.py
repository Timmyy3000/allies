"""Startup reconciliation between Foundry desired state and the volume store."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .foundry import (
    FencedError,
    FoundryClient,
    ProfileDesiredState,
    ProfileReceipt,
    RepairRequiredError,
)
from .profile_store import (
    DEFAULT_MEMORY_MODE,
    DEFAULT_MEMORY_POLICY_VERSION,
    DEFAULT_MEMORY_PROVIDER,
    ProfileCleanupStatus,
    ProfileProvisionStatus,
    ProfileSeed,
    ProfileStore,
)


class ProfileReconciliationBlocked(RuntimeError):
    """The runtime cannot safely acknowledge an incomplete profile state."""


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    materialized: tuple[ProfileReceipt, ...] = ()
    cleaned: tuple[ProfileReceipt, ...] = ()
    blocked_profile_ids: tuple[str, ...] = ()


class ProfileReconciler:
    """Run profile reconciliation before a worker is allowed to claim work."""

    def __init__(self, foundry: FoundryClient, store: ProfileStore) -> None:
        self.foundry = foundry
        self.store = store

    async def reconcile(self) -> ReconciliationReport:
        desired = await self.foundry.reconcile_profiles()
        materialized: list[ProfileReceipt] = []
        cleaned: list[ProfileReceipt] = []
        blocked: list[str] = []
        for profile in desired:
            if profile.cleanup_operation_id and profile.lifecycle_state in {
                "cleanup_pending",
                "deprovisioned",
            }:
                receipt = await self._cleanup(profile)
                if receipt is None:
                    blocked.append(profile.profile_id)
                else:
                    cleaned.append(receipt)
                continue
            if profile.lifecycle_state not in {"pending", "active"}:
                blocked.append(profile.profile_id)
                continue
            if (
                profile.materialized_generation == profile.machine_generation
                and profile.materialization_operation_id
                and profile.materialization_receipt_id
            ):
                continue
            receipt = await self._materialize(profile)
            if receipt is None:
                blocked.append(profile.profile_id)
            else:
                materialized.append(receipt)
        if blocked:
            raise ProfileReconciliationBlocked(
                "one or more Hermes profiles require repair"
            )
        return ReconciliationReport(tuple(materialized), tuple(cleaned), ())

    async def _materialize(self, profile: ProfileDesiredState) -> ProfileReceipt | None:
        operation_id = profile.materialization_operation_id or str(
            uuid5(
                NAMESPACE_URL,
                "allies-foundry:profile-materialize:"
                f"{profile.profile_id}:{profile.lifecycle_epoch}:"
                f"{profile.machine_generation}:{profile.seed_fingerprint}",
            )
        )
        seed = _runtime_seed(profile, operation_id)
        store_receipt = await asyncio.to_thread(self.store.materialize, seed)
        if store_receipt.status not in {
            ProfileProvisionStatus.CREATED,
            ProfileProvisionStatus.EXISTING,
        }:
            return None
        try:
            return await self.foundry.materialization_receipt(
                profile.profile_id,
                operation_id=operation_id,
                lifecycle_epoch=profile.lifecycle_epoch,
                materialized_generation=profile.machine_generation,
                seed_fingerprint=store_receipt.seed_fingerprint
                or profile.seed_fingerprint,
                result_code=store_receipt.result_code,
            )
        except (FencedError, RepairRequiredError):
            # Cleanup may have fenced the snapshot after the local publish.
            # Re-read the authority and compensate immediately so a stale
            # materialization cannot remain on the volume until restart.
            latest = await self.foundry.reconcile_profiles()
            current = next(
                (item for item in latest if item.profile_id == profile.profile_id),
                None,
            )
            if current is not None and current.cleanup_operation_id:
                await self._cleanup(current)
            return None

    async def _cleanup(self, profile: ProfileDesiredState) -> ProfileReceipt | None:
        if profile.cleanup_operation_id is None or not profile.cleanup_request_digest:
            return None
        if profile.active_lease_count:
            return None
        store_receipt = await asyncio.to_thread(
            self.store.cleanup,
            profile.hermes_profile_key,
            profile.cleanup_operation_id,
            profile.lifecycle_epoch,
            profile.cleanup_expires_at,
        )
        if store_receipt.status is ProfileCleanupStatus.FENCED:
            return None
        deleted = store_receipt.status is ProfileCleanupStatus.DEPROVISIONED
        result_code = "deprovisioned" if deleted else "repair_required"
        return await self.foundry.cleanup_receipt(
            profile.profile_id,
            operation_id=profile.cleanup_operation_id,
            lifecycle_epoch=profile.lifecycle_epoch,
            request_digest=profile.cleanup_request_digest,
            result_code=result_code,
            deleted=deleted,
            active_lease_count=0,
        )


def _runtime_seed(profile: ProfileDesiredState, operation_id: str) -> ProfileSeed:
    payload = profile.seed
    try:
        return ProfileSeed(
            foundry_profile_id=profile.profile_id,
            ally_name=profile.ally_ref,
            personality=_text(payload, "personality"),
            provider=_text(payload, "provider"),
            model=_text(payload, "model"),
            first_chat_instruction=_text(payload, "first_chat_instruction"),
            credential_refs=_mapping(payload, "credential_refs"),
            seed_version=profile.seed_version,
            first_chat_version=int(payload.get("first_chat_instruction_version", 1)),
            base_url=payload.get("base_url"),
            hermes_profile_key=profile.hermes_profile_key,
            lifecycle_epoch=profile.lifecycle_epoch,
            materialized_generation=profile.machine_generation,
            operation_id=operation_id,
            memory_provider=_optional_text(
                payload, "memory_provider", DEFAULT_MEMORY_PROVIDER
            ),
            memory_mode=_optional_text(payload, "memory_mode", DEFAULT_MEMORY_MODE),
            memory_policy_version=_optional_text(
                payload, "memory_policy_version", DEFAULT_MEMORY_POLICY_VERSION
            ),
            memory_tool_allowlist=_optional_list(payload, "memory_tool_allowlist"),
            memory_profile_isolation=payload.get("memory_profile_isolation", True),
            memory_sync_roles=_optional_list(payload, "memory_sync_roles"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProfileReconciliationBlocked(
            "profile desired state could not be represented safely"
        ) from exc


def _text(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise TypeError(key)
    return value


def _mapping(payload: dict[str, Any], key: str) -> dict[str, str]:
    value = payload[key]
    if not isinstance(value, dict) or not all(
        isinstance(name, str) and isinstance(item, str) for name, item in value.items()
    ):
        raise TypeError(key)
    return dict(value)


def _optional_text(payload: dict[str, Any], key: str, default: str) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str):
        raise TypeError(key)
    return value


def _optional_list(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key, ())
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(item, str) for item in value
    ):
        raise TypeError(key)
    return tuple(value)


__all__ = [
    "ProfileReconciler",
    "ProfileReconciliationBlocked",
    "ReconciliationReport",
]
