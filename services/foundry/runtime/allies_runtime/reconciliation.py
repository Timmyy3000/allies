"""Startup reconciliation between Foundry desired state and the volume store."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .errors import HermesError
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
    DEFAULT_MEMORY_TOOL_ALLOWLIST,
    ProfileCleanupStatus,
    ProfileProvisionStatus,
    ProfileSeed,
    ProfileStore,
)
from .quiescence import QuiescenceError


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
        hermes: Any | None = None,
        worker: Any | None = None,
    ) -> None:
        self.foundry = foundry
        self.store = store
        self.correlation_id = correlation_id
        self.hermes = hermes
        self.worker = worker
        self._hermes_instance_id: str | None = None

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
            deletion_pending: list[str] = []
            for profile in desired:
                if profile.cleanup_operation_id and profile.lifecycle_state in {
                    "cleanup_pending",
                    "deprovisioned",
                    "repair_required",
                }:
                    receipt = await self._cleanup(profile)
                    if receipt is None:
                        if profile.cleanup_requires_quiescence:
                            # A fenced deletion may remain pending while the
                            # target writer drains.  Keep that profile out of
                            # admission, but do not make an unrelated sibling
                            # miss readiness or claims.
                            deletion_pending.append(profile.profile_id)
                        else:
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
            return ReconciliationReport(
                tuple(materialized), tuple(cleaned), tuple(deletion_pending)
            )

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
        requires_quiescence = bool(profile.cleanup_requires_quiescence)
        quiescence = None
        runtime_start_epoch = getattr(
            getattr(self.foundry, "last_reconciliation_snapshot", None),
            "runtime_start_epoch",
            None,
        )
        attempt_id = profile.cleanup_attempt_id
        if requires_quiescence:
            if (
                self.hermes is None
                or not attempt_id
                or not isinstance(runtime_start_epoch, int)
                or not isinstance(self.correlation_id, str)
            ):
                return None
            prepare_fence = getattr(self.store, "fence_deletion", None)
            if not callable(prepare_fence):
                return None
            try:
                fence_receipt = await asyncio.to_thread(
                    prepare_fence,
                    profile.hermes_profile_key,
                    profile.cleanup_operation_id,
                    profile.lifecycle_epoch,
                    profile.cleanup_expires_at,
                    attempt_id=attempt_id,
                    request_digest=profile.cleanup_request_digest,
                )
                if getattr(fence_receipt, "status", None) not in {
                    ProfileCleanupStatus.FENCED,
                    ProfileCleanupStatus.DEPROVISIONED,
                } or getattr(fence_receipt, "repair_code", None):
                    return None
            except (HermesError, QuiescenceError, TimeoutError, OSError, ValueError):
                return None
            worker_fence = getattr(self.worker, "fence_profile", None)
            worker_quiesce = getattr(self.worker, "quiesce_profile", None)
            if not callable(worker_fence) or not callable(worker_quiesce):
                return None
            try:
                # Fence runtime admission before contacting Hermes, but do
                # not wait for a worker that may be blocked inside Hermes.
                fence_result = worker_fence(profile.hermes_profile_key)
                if asyncio.iscoroutine(fence_result) or hasattr(
                    fence_result, "__await__"
                ):
                    await fence_result
            except (HermesError, QuiescenceError, TimeoutError, OSError, ValueError):
                return None
            identity = getattr(self.hermes, "hermes_instance_id", None)
            if not callable(identity):
                return None
            try:
                # A listener boot identity is single-use.  Resolve it fresh
                # for every deletion attempt, including retries after a
                # Hermes restart; a cached acknowledgement could authorize a
                # different process.
                identity = identity()
                if asyncio.iscoroutine(identity) or hasattr(identity, "__await__"):
                    identity = await identity
                hermes_instance_id = str(identity)
                self._hermes_instance_id = hermes_instance_id
            except (HermesError, TimeoutError, OSError, ValueError):
                return None
            quiesce = getattr(self.hermes, "quiesce_profile", None)
            if not callable(quiesce):
                return None
            try:
                proof = quiesce(
                    profile.hermes_profile_key,
                    operation_id=profile.cleanup_operation_id,
                    attempt_id=attempt_id,
                    lifecycle_epoch=profile.lifecycle_epoch,
                    request_digest=profile.cleanup_request_digest,
                    machine_generation=profile.machine_generation,
                    runtime_start_epoch=runtime_start_epoch,
                    hermes_instance_id=hermes_instance_id,
                )
                if asyncio.iscoroutine(proof) or hasattr(proof, "__await__"):
                    proof = await proof
                if hasattr(proof, "complete") and not proof.complete:
                    return None
                if not isinstance(proof, Mapping):
                    proof = proof.to_dict() if hasattr(proof, "to_dict") else None
                if not isinstance(proof, Mapping):
                    return None
                quiescence = {
                    name: proof[name]
                    for name in (
                        "state",
                        "safe_error_code",
                        "active_runs",
                        "active_profile_io",
                        "open_profile_stores",
                        "owned_children",
                    )
                    if name in proof
                }
                if (
                    set(quiescence)
                    != {
                        "state",
                        "safe_error_code",
                        "active_runs",
                        "active_profile_io",
                        "open_profile_stores",
                        "owned_children",
                    }
                    or quiescence["state"] != "quiesced"
                    or quiescence["safe_error_code"] != ""
                    or any(quiescence[name] != 0 for name in (
                        "active_runs",
                        "active_profile_io",
                        "open_profile_stores",
                        "owned_children",
                    ))
                ):
                    return None
            except (HermesError, QuiescenceError, TimeoutError, OSError, ValueError):
                return None
            try:
                worker_result = worker_quiesce(
                    profile.hermes_profile_key, timeout_seconds=30.0
                )
                if asyncio.iscoroutine(worker_result) or hasattr(
                    worker_result, "__await__"
                ):
                    worker_result = await worker_result
                worker_state = (
                    worker_result[0]
                    if isinstance(worker_result, tuple)
                    else getattr(worker_result, "state", None)
                )
                if worker_state != "quiesced":
                    return None
            except (HermesError, QuiescenceError, TimeoutError, OSError, ValueError):
                return None

            # Hermes quiescence settles STOPPING work; ask Foundry again so a
            # stale first snapshot cannot be reported as a zero-lease delete.
            try:
                current_profiles = await self.foundry.reconcile_profiles()
            except Exception:  # noqa: BLE001 - failed lease recheck is unsafe
                return None
            current = next(
                (
                    item
                    for item in current_profiles
                    if item.profile_id == profile.profile_id
                ),
                None,
            )
            if (
                current is None
                or current.cleanup_operation_id != profile.cleanup_operation_id
                or current.cleanup_request_digest != profile.cleanup_request_digest
                or current.lifecycle_epoch != profile.lifecycle_epoch
                or current.active_lease_count != 0
            ):
                return None
        elif profile.active_lease_count:
            return None
        cleanup_kwargs = (
            {
                "attempt_id": attempt_id,
                "request_digest": profile.cleanup_request_digest,
                "deletion": True,
            }
            if requires_quiescence
            else {}
        )
        store_receipt = await asyncio.to_thread(
            self.store.cleanup,
            profile.hermes_profile_key,
            profile.cleanup_operation_id,
            profile.lifecycle_epoch,
            profile.cleanup_expires_at,
            **cleanup_kwargs,
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
            **(
                {
                    "attempt_id": attempt_id,
                    "machine_generation": profile.machine_generation,
                    "runtime_start_epoch": runtime_start_epoch,
                    "runtime_boot_id": self.correlation_id,
                    "hermes_instance_id": hermes_instance_id,
                    "quiescence": quiescence,
                }
                if requires_quiescence
                else {}
            ),
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
            memory_tool_allowlist=_optional_list(
                payload,
                "memory_tool_allowlist",
                DEFAULT_MEMORY_TOOL_ALLOWLIST,
            ),
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


def _optional_list(
    payload: dict[str, Any], key: str, default: tuple[str, ...] = ()
) -> tuple[str, ...]:
    value = payload.get(key, default)
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
