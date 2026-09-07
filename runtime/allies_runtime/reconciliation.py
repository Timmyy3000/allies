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
from .observability import observe_runtime_operation
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

    def __init__(
        self,
        foundry: FoundryClient,
        store: ProfileStore,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self.foundry = foundry
        self.store = store
        self.correlation_id = correlation_id

    async def reconcile(self) -> ReconciliationReport:
        with observe_runtime_operation(
            "profile_reconciliation",
            **self._context_fields(),
        ) as operation:
            with observe_runtime_operation(
                "profile.reconciliation_fetch",
                **self._context_fields(),
            ) as fetch:
                desired = await self.foundry.reconcile_profiles()
                fetch.update(**self._context_fields())
            operation.update(**self._context_fields())
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
        with observe_runtime_operation(
            "profile_materialization",
            **self._context_fields(profile),
        ) as operation:
            operation_id = profile.materialization_operation_id or str(
                uuid5(
                    NAMESPACE_URL,
                    "allies-foundry:profile-materialize:"
                    f"{profile.profile_id}:{profile.lifecycle_epoch}:"
                    f"{profile.machine_generation}:{profile.seed_fingerprint}",
                )
            )
            seed = _runtime_seed(profile, operation_id)
            with observe_runtime_operation(
                "profile.local_materialization",
                request_id=operation_id,
                **self._context_fields(profile),
            ) as local_operation:
                store_receipt = await asyncio.to_thread(self.store.materialize, seed)
                if store_receipt.status not in {
                    ProfileProvisionStatus.CREATED,
                    ProfileProvisionStatus.EXISTING,
                }:
                    failure = {
                        "outcome": "error",
                        "error_type": "ProfileMaterializationError",
                        "error_code": getattr(store_receipt, "repair_code", None)
                        or "materialization_failed",
                        "reason_code": "repair_required",
                    }
                    local_operation.update(**failure)
                    operation.update(**failure)
                    return None
            try:
                with observe_runtime_operation(
                    "profile.materialization_receipt",
                    request_id=operation_id,
                    **self._context_fields(profile),
                ):
                    return await self.foundry.materialization_receipt(
                        profile.profile_id,
                        operation_id=operation_id,
                        lifecycle_epoch=profile.lifecycle_epoch,
                        materialized_generation=profile.machine_generation,
                        seed_fingerprint=store_receipt.seed_fingerprint
                        or profile.seed_fingerprint,
                        result_code=store_receipt.result_code,
                    )
            except (FencedError, RepairRequiredError) as error:
                # Cleanup may have fenced the snapshot after the local publish.
                # Re-read the authority and compensate immediately so a stale
                # materialization cannot remain on the volume until restart.
                operation.update(
                    outcome="error",
                    error_type=type(error).__name__,
                    error_code=getattr(error, "code", None),
                    reason_code="fenced",
                )
                with observe_runtime_operation(
                    "profile.reconciliation_fetch",
                    **self._context_fields(profile),
                ) as fetch:
                    latest = await self.foundry.reconcile_profiles()
                    fetch.update(**self._context_fields(profile))
                current = next(
                    (item for item in latest if item.profile_id == profile.profile_id),
                    None,
                )
                if current is not None and current.cleanup_operation_id:
                    await self._cleanup(current)
                return None

    def _context_fields(
        self, profile: ProfileDesiredState | None = None
    ) -> dict[str, object]:
        snapshot = getattr(self.foundry, "last_reconciliation_snapshot", None)
        fields: dict[str, object] = {}
        if self.correlation_id is not None:
            fields["correlation_id"] = self.correlation_id
        profile_id = getattr(profile, "profile_id", None)
        if profile_id is not None:
            fields["profile_id"] = profile_id
        workspace_id = getattr(snapshot, "workspace_id", None)
        if workspace_id is not None:
            fields["workspace_id"] = workspace_id
        generation = getattr(snapshot, "machine_generation", None)
        if generation is None and profile is not None:
            generation = profile.machine_generation
        if generation is not None:
            fields["generation"] = generation
        runtime_start_epoch = getattr(snapshot, "runtime_start_epoch", None)
        if runtime_start_epoch is not None:
            fields["runtime_start_epoch"] = runtime_start_epoch
        return fields

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
