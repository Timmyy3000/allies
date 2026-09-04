"""Durable Foundry lifecycle and reconciliation for Hermes profiles.

The database row is the control-plane source of truth.  The runtime only
receives a sanitized desired state and acknowledges what it observed on the
tenant volume.  Secret values never cross this module: provider credentials
are represented by opaque resolver references and the runtime generates its
Hermes API key locally.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction
from django.utils import timezone

from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeFencedError,
    RuntimeIdempotencyConflictError,
    RuntimeNotReadyError,
    RuntimeRepairRequiredError,
    RuntimeValidationError,
)
from runtime.models import (
    IN_FLIGHT_PROVISIONING_PHASES,
    AttemptStatus,
    ExecutionStatus,
    Lease,
    LeaseState,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
)
from runtime.profile_keys import derive_hermes_profile_key

from .retry import run_with_sqlite_lock_retry
from .runtime_auth import RuntimeContext
from .validation import digest_payload, validate_nonempty

PROFILE_SEED_VERSION = 1
PROFILE_FINGERPRINT_VERSION = 2
DEFAULT_MEMORY_PROVIDER = "allies_mnemosyne"
DEFAULT_MEMORY_MODE = "context_only"
DEFAULT_MEMORY_POLICY_VERSION = "allies-mnemosyne-v1"
MEMORY_MODES = frozenset({"context_only", "narrow_tools"})
MEMORY_TOOLS = frozenset(
    {
        "mnemosyne_forget",
        "mnemosyne_forget_canonical",
        "mnemosyne_invalidate",
        "mnemosyne_recall",
        "mnemosyne_recall_canonical",
        "mnemosyne_remember",
        "mnemosyne_remember_canonical",
        "mnemosyne_update",
    }
)
CLEANUP_GRACE_SECONDS = 60
MAX_PROFILE_SEED_BYTES = 128 * 1024
_OPAQUE_REFERENCE = re.compile(
    r"^[a-z][a-z0-9+.-]{1,31}://[^\s]{1,191}$", re.IGNORECASE
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_RESULT_CODE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_MATERIALIZATION_RESULT_CODES = frozenset({"created", "existing"})
_CLEANUP_RESULT_CODES = frozenset(
    {"cleanup_pending", "deprovisioned", "repair_required"}
)


@dataclass(frozen=True, slots=True)
class ProfileSeed:
    """The minimal non-secret desired state for one Hermes profile."""

    personality: str
    provider: str
    model: str
    first_chat_instruction: str
    credential_refs: Mapping[str, str]
    base_url: str | None = None
    version: int = PROFILE_SEED_VERSION
    first_chat_instruction_version: int = 1
    memory_provider: str = DEFAULT_MEMORY_PROVIDER
    memory_mode: str = DEFAULT_MEMORY_MODE
    memory_policy_version: str = DEFAULT_MEMORY_POLICY_VERSION
    memory_tool_allowlist: tuple[str, ...] = ()
    memory_profile_isolation: bool = True
    memory_sync_roles: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        return _normalize_seed(self)


@dataclass(frozen=True, slots=True)
class ProfileProvisioningReceipt:
    profile_id: UUID
    hermes_profile_key: str
    lifecycle_epoch: int
    seed_fingerprint: str
    state: str


@dataclass(frozen=True, slots=True)
class ProfileDesiredState:
    profile_id: UUID
    ally_ref: str
    hermes_profile_key: str
    hermes_profile_key_version: int
    lifecycle_state: str
    lifecycle_epoch: int
    seed_version: int
    seed_fingerprint: str
    materialized_generation: int
    active_lease_count: int
    seed_payload: dict[str, Any]
    materialization_operation_id: UUID | None
    materialization_request_digest: str
    materialization_receipt_id: UUID | None
    materialization_result_code: str
    cleanup_operation_id: UUID | None
    cleanup_context_digest: str
    cleanup_request_digest: str
    cleanup_receipt_id: UUID | None
    cleanup_result_code: str
    cleanup_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProfileReconciliationReceipt:
    profile_id: UUID
    lifecycle_state: str
    lifecycle_epoch: int
    materialized_generation: int
    seed_fingerprint: str
    receipt_id: UUID | None
    result_code: str
    deleted: bool = False
    active_lease_count: int = 0


def ensure_runtime_profile(
    workspace_id: UUID | str,
    profile_id: UUID | str,
    ally_ref: str,
    seed: ProfileSeed | Mapping[str, Any],
) -> ProfileProvisioningReceipt:
    """Create or exact-replay a durable profile desired state."""

    workspace_uuid = _uuid(workspace_id, "workspace_id")
    profile_uuid = _uuid(profile_id, "profile_id")
    ally_ref = validate_nonempty(ally_ref, "ally_ref", max_length=255)
    payload = _normalize_seed(seed)
    key = derive_hermes_profile_key(profile_uuid)
    fingerprint = _seed_fingerprint(profile_uuid, key, ally_ref, payload)

    @transaction.atomic
    def ensure_once() -> ProfileProvisioningReceipt:
        workspace = (
            Workspace.objects.select_for_update().filter(pk=workspace_uuid).first()
        )
        if workspace is None:
            raise RuntimeValidationError("workspace does not exist")
        profile = (
            RuntimeProfile.objects.select_for_update().filter(pk=profile_uuid).first()
        )
        if profile is not None:
            _assert_profile_identity(profile, workspace_uuid, ally_ref, key)
            _assert_seed_compatible(profile, payload, fingerprint)
            if not profile.seed_payload:
                profile.seed_payload = payload
                profile.seed_version = payload["version"]
                profile.seed_fingerprint = fingerprint
                profile.save(
                    update_fields=[
                        "seed_payload",
                        "seed_version",
                        "seed_fingerprint",
                        "updated_at",
                    ]
                )
            return ProfileProvisioningReceipt(
                profile.id,
                profile.hermes_profile_key,
                profile.lifecycle_epoch,
                profile.seed_fingerprint or fingerprint,
                profile.lifecycle_state,
            )
        if RuntimeProfile.objects.filter(
            workspace_id=workspace_uuid, ally_ref=ally_ref
        ).exists():
            raise RuntimeConflictError(
                "ally reference already belongs to another profile"
            )
        if RuntimeProfile.objects.filter(
            workspace_id=workspace_uuid, hermes_profile_key=key
        ).exists():
            raise RuntimeConflictError(
                "Hermes profile key collides with existing state"
            )
        try:
            profile = RuntimeProfile.objects.create(
                id=profile_uuid,
                workspace=workspace,
                ally_ref=ally_ref,
                hermes_profile_key=key,
                hermes_profile_key_version=1,
                lifecycle_state=RuntimeProfileLifecycleState.PENDING,
                seed_version=payload["version"],
                seed_payload=payload,
                seed_fingerprint=fingerprint,
            )
        except IntegrityError as exc:
            raise RuntimeConflictError(
                "profile identity conflicts with existing state"
            ) from exc
        return ProfileProvisioningReceipt(
            profile.id,
            profile.hermes_profile_key,
            profile.lifecycle_epoch,
            fingerprint,
            profile.lifecycle_state,
        )

    return run_with_sqlite_lock_retry(ensure_once)


def list_profile_reconciliation(
    context: RuntimeContext,
) -> tuple[ProfileDesiredState, ...]:
    """Return all workspace profile states for the authenticated generation."""

    _require_context(context)
    workspace = Workspace.objects.filter(pk=context.workspace_id).first()
    if workspace is None:
        raise RuntimeConflictError("runtime workspace does not exist")
    _check_context_generation(workspace, context)
    _require_ready_workspace(workspace)
    return tuple(
        _desired_state(profile)
        for profile in RuntimeProfile.objects.filter(
            workspace_id=workspace.id
        ).order_by("ally_ref", "id")
    )


def accept_materialization_receipt(
    context: RuntimeContext,
    profile_id: UUID | str,
    operation_id: UUID | str,
    lifecycle_epoch: int,
    materialized_generation: int,
    seed_fingerprint: str,
    result_code: str,
) -> ProfileReconciliationReceipt:
    """Commit one runtime materialization observation idempotently."""

    _require_context(context)
    profile_uuid = _uuid(profile_id, "profile_id")
    operation_uuid = _uuid(operation_id, "operation_id")
    _validate_epoch(lifecycle_epoch)
    _validate_generation(materialized_generation)
    _validate_digest(seed_fingerprint, "seed_fingerprint")
    result_code = _validate_result_code(result_code)
    if result_code not in _MATERIALIZATION_RESULT_CODES:
        raise RuntimeValidationError("materialization result_code is not successful")
    request_digest = digest_payload(
        {
            "profile_id": str(profile_uuid),
            "operation_id": str(operation_uuid),
            "lifecycle_epoch": lifecycle_epoch,
            "materialized_generation": materialized_generation,
            "seed_fingerprint": seed_fingerprint,
            "result_code": result_code,
        }
    )

    @transaction.atomic
    def accept_once() -> ProfileReconciliationReceipt:
        workspace = Workspace.objects.select_for_update().get(pk=context.workspace_id)
        _check_context_generation(workspace, context)
        _require_ready_workspace(workspace)
        profile = (
            RuntimeProfile.objects.select_for_update()
            .filter(pk=profile_uuid, workspace_id=workspace.id)
            .first()
        )
        if profile is None:
            raise RuntimeValidationError("profile is not in this workspace")
        if profile.lifecycle_state in {
            RuntimeProfileLifecycleState.CLEANUP_PENDING,
            RuntimeProfileLifecycleState.DEPROVISIONED,
            RuntimeProfileLifecycleState.REPAIR_REQUIRED,
        }:
            raise RuntimeRepairRequiredError(
                "profile lifecycle has fenced provisioning"
            )
        if profile.hermes_profile_key_version != 1:
            raise RuntimeRepairRequiredError(
                "legacy Hermes profile key requires repair"
            )
        if profile.lifecycle_epoch != lifecycle_epoch:
            raise RuntimeFencedError("profile lifecycle operation is stale")
        if profile.materialization_operation_id is not None:
            if (
                profile.materialization_operation_id != operation_uuid
                or profile.materialization_request_digest != request_digest
            ):
                raise RuntimeIdempotencyConflictError(
                    "materialization operation conflicts with stored receipt"
                )
            return _materialization_receipt(profile)
        if profile.seed_fingerprint != seed_fingerprint:
            raise RuntimeConflictError(
                "materialization fingerprint does not match desired state"
            )
        if materialized_generation != workspace.machine_generation:
            raise RuntimeFencedError("materialization belongs to a retired generation")
        profile.lifecycle_state = RuntimeProfileLifecycleState.ACTIVE
        profile.materialized_generation = materialized_generation
        profile.materialization_operation_id = operation_uuid
        profile.materialization_request_digest = request_digest
        profile.materialization_receipt_id = uuid4()
        profile.materialization_result_code = result_code
        profile.save(
            update_fields=[
                "lifecycle_state",
                "materialized_generation",
                "materialization_operation_id",
                "materialization_request_digest",
                "materialization_receipt_id",
                "materialization_result_code",
                "updated_at",
            ]
        )
        return _materialization_receipt(profile)

    return run_with_sqlite_lock_retry(accept_once)


def request_profile_cleanup(
    workspace_id: UUID | str,
    profile_id: UUID | str,
    operation_id: UUID | str,
    binding_context_digest: str,
    expires_at: datetime | None = None,
) -> ProfileReconciliationReceipt:
    """Persist the cleanup fence before the runtime removes any files."""

    workspace_uuid = _uuid(workspace_id, "workspace_id")
    profile_uuid = _uuid(profile_id, "profile_id")
    operation_uuid = _uuid(operation_id, "operation_id")
    _validate_digest(binding_context_digest, "binding_context_digest")
    supplied_expires_at = expires_at
    expires_at = _validate_cleanup_expiry(expires_at)
    request_digest = digest_payload(
        {
            "operation_id": str(operation_uuid),
            "binding_context_digest": binding_context_digest,
            "expires_at": expires_at.isoformat(),
        }
    )

    @transaction.atomic
    def request_once() -> ProfileReconciliationReceipt:
        workspace = Workspace.objects.select_for_update().get(pk=workspace_uuid)
        profile = (
            RuntimeProfile.objects.select_for_update()
            .filter(pk=profile_uuid, workspace_id=workspace.id)
            .first()
        )
        if profile is None:
            raise RuntimeValidationError("profile is not in this workspace")
        if profile.cleanup_operation_id is not None:
            if (
                profile.cleanup_operation_id != operation_uuid
                or profile.cleanup_context_digest != binding_context_digest
                or (
                    supplied_expires_at is not None
                    and profile.cleanup_request_digest != request_digest
                )
            ):
                raise RuntimeIdempotencyConflictError(
                    "cleanup operation conflicts with stored state"
                )
            return _cleanup_receipt(profile)
        if profile.lifecycle_state == RuntimeProfileLifecycleState.DEPROVISIONED:
            raise RuntimeRepairRequiredError(
                "deprovisioned profile has no cleanup operation"
            )
        now = timezone.now()
        profile.lifecycle_epoch += 1
        profile.lifecycle_state = RuntimeProfileLifecycleState.CLEANUP_PENDING
        profile.cleanup_operation_id = operation_uuid
        profile.cleanup_context_digest = binding_context_digest
        profile.cleanup_request_digest = request_digest
        profile.cleanup_expires_at = expires_at
        profile.cleanup_retry_after = min(
            expires_at, now + timedelta(seconds=CLEANUP_GRACE_SECONDS)
        )
        profile.cleanup_result_code = "cleanup_pending"
        active_leases = list(
            Lease.objects.select_for_update().filter(
                profile_id=profile.id,
                state__in=(LeaseState.ACTIVE, LeaseState.STOPPING),
            )
        )
        for lease in active_leases:
            if lease.state == LeaseState.ACTIVE:
                lease.state = LeaseState.STOPPING
                lease.save(update_fields=["state", "updated_at"])
        profile.save(
            update_fields=[
                "lifecycle_state",
                "lifecycle_epoch",
                "cleanup_operation_id",
                "cleanup_context_digest",
                "cleanup_request_digest",
                "cleanup_expires_at",
                "cleanup_retry_after",
                "cleanup_result_code",
                "updated_at",
            ]
        )
        return _cleanup_receipt(profile, active_lease_count=len(active_leases))

    return run_with_sqlite_lock_retry(request_once)


def accept_cleanup_receipt(
    context: RuntimeContext,
    profile_id: UUID | str,
    operation_id: UUID | str,
    lifecycle_epoch: int,
    request_digest: str,
    *,
    result_code: str,
    deleted: bool,
    active_lease_count: int,
) -> ProfileReconciliationReceipt:
    """Apply a runtime cleanup observation or durable repair result."""

    _require_context(context)
    profile_uuid = _uuid(profile_id, "profile_id")
    operation_uuid = _uuid(operation_id, "operation_id")
    _validate_epoch(lifecycle_epoch)
    _validate_digest(request_digest, "request_digest")
    result_code = _validate_result_code(result_code)
    if type(deleted) is not bool:
        raise RuntimeValidationError("deleted must be a boolean")
    if result_code not in _CLEANUP_RESULT_CODES:
        raise RuntimeValidationError("cleanup result_code is invalid")
    if (result_code == "deprovisioned") != deleted:
        raise RuntimeValidationError(
            "cleanup result_code and deleted flag do not agree"
        )
    if result_code == "cleanup_pending" and deleted:
        raise RuntimeValidationError(
            "cleanup_pending receipts cannot report deleted files"
        )
    if (
        isinstance(active_lease_count, bool)
        or not isinstance(active_lease_count, int)
        or active_lease_count < 0
    ):
        raise RuntimeValidationError("active_lease_count must be non-negative")

    @transaction.atomic
    def accept_once() -> ProfileReconciliationReceipt:
        workspace = Workspace.objects.select_for_update().get(pk=context.workspace_id)
        _check_context_generation(workspace, context)
        profile = (
            RuntimeProfile.objects.select_for_update()
            .filter(pk=profile_uuid, workspace_id=workspace.id)
            .first()
        )
        if profile is None:
            raise RuntimeValidationError("profile is not in this workspace")
        if profile.cleanup_operation_id != operation_uuid:
            raise RuntimeIdempotencyConflictError("cleanup operation is stale")
        if profile.cleanup_request_digest != request_digest:
            raise RuntimeIdempotencyConflictError(
                "cleanup receipt does not match the request"
            )
        if profile.cleanup_receipt_id is not None:
            if profile.cleanup_result_code != result_code:
                raise RuntimeIdempotencyConflictError(
                    "cleanup receipt conflicts with stored result"
                )
            return _cleanup_receipt(
                profile,
                deleted=profile.lifecycle_state
                == RuntimeProfileLifecycleState.DEPROVISIONED,
            )
        if profile.lifecycle_epoch != lifecycle_epoch:
            raise RuntimeFencedError(
                "cleanup receipt belongs to a stale lifecycle epoch"
            )
        actual_active = Lease.objects.filter(
            profile_id=profile.id,
            state__in=(LeaseState.ACTIVE, LeaseState.STOPPING),
        ).count()
        if actual_active != active_lease_count:
            raise RuntimeConflictError("cleanup receipt has stale active lease count")
        now = timezone.now()
        if deleted and actual_active:
            raise RuntimeConflictError(
                "profile files cannot be deleted while work is active"
            )
        expired = (
            profile.cleanup_expires_at is not None and now >= profile.cleanup_expires_at
        )
        if deleted:
            profile.lifecycle_state = RuntimeProfileLifecycleState.DEPROVISIONED
            profile.materialized_generation = 0
            profile.cleanup_completed_at = now
            profile.cleanup_receipt_id = uuid4()
            profile.cleanup_result_code = result_code
            profile.cleanup_retry_after = None
            profile.save(
                update_fields=[
                    "lifecycle_state",
                    "materialized_generation",
                    "cleanup_completed_at",
                    "cleanup_receipt_id",
                    "cleanup_result_code",
                    "cleanup_retry_after",
                    "updated_at",
                ]
            )
            return _cleanup_receipt(profile, deleted=True)
        if result_code == "repair_required" or expired:
            _fence_profile_leases(profile.id)
            profile.lifecycle_state = RuntimeProfileLifecycleState.REPAIR_REQUIRED
            profile.cleanup_completed_at = now
            profile.cleanup_receipt_id = uuid4()
            profile.cleanup_result_code = "repair_required"
            profile.cleanup_retry_after = None
            profile.save(
                update_fields=[
                    "lifecycle_state",
                    "cleanup_completed_at",
                    "cleanup_receipt_id",
                    "cleanup_result_code",
                    "cleanup_retry_after",
                    "updated_at",
                ]
            )
            return _cleanup_receipt(profile, deleted=False, active_lease_count=0)
        profile.cleanup_retry_after = min(
            profile.cleanup_expires_at
            or now + timedelta(seconds=CLEANUP_GRACE_SECONDS),
            now + timedelta(seconds=CLEANUP_GRACE_SECONDS),
        )
        profile.cleanup_result_code = "cleanup_pending"
        profile.save(
            update_fields=["cleanup_retry_after", "cleanup_result_code", "updated_at"]
        )
        return _cleanup_receipt(profile, active_lease_count=actual_active)

    return run_with_sqlite_lock_retry(accept_once)


def expire_profile_cleanups(
    *, now: datetime | None = None
) -> tuple[ProfileReconciliationReceipt, ...]:
    """Fence cleanup operations whose bounded grace window has elapsed.

    This is intentionally a server-owned operation so a missing or unhealthy
    runtime cannot leave STOPPING leases and cleanup-pending profiles forever.
    A scheduler can call it repeatedly; the lifecycle transition and receipt
    are idempotent because only cleanup-pending rows are selected.
    """

    effective_now = now or timezone.now()
    if timezone.is_naive(effective_now):
        raise RuntimeValidationError("cleanup expiry must be timezone-aware")
    receipts: list[ProfileReconciliationReceipt] = []
    profile_ids = list(
        RuntimeProfile.objects.filter(
            lifecycle_state=RuntimeProfileLifecycleState.CLEANUP_PENDING,
            cleanup_expires_at__lte=effective_now,
        ).values_list("id", flat=True)
    )

    @transaction.atomic
    def expire_once(profile_id: UUID) -> ProfileReconciliationReceipt | None:
        profile = RuntimeProfile.objects.select_for_update().get(pk=profile_id)
        if (
            profile.lifecycle_state != RuntimeProfileLifecycleState.CLEANUP_PENDING
            or profile.cleanup_expires_at is None
            or profile.cleanup_expires_at > effective_now
        ):
            return None
        _fence_profile_leases(profile.id)
        profile.lifecycle_state = RuntimeProfileLifecycleState.REPAIR_REQUIRED
        profile.cleanup_completed_at = effective_now
        profile.cleanup_receipt_id = profile.cleanup_receipt_id or uuid4()
        profile.cleanup_result_code = "repair_required"
        profile.cleanup_retry_after = None
        profile.save(
            update_fields=[
                "lifecycle_state",
                "cleanup_completed_at",
                "cleanup_receipt_id",
                "cleanup_result_code",
                "cleanup_retry_after",
                "updated_at",
            ]
        )
        return _cleanup_receipt(profile, deleted=False, active_lease_count=0)

    for profile_id in profile_ids:
        receipt = run_with_sqlite_lock_retry(
            lambda profile_id=profile_id: expire_once(profile_id)
        )
        if receipt is not None:
            receipts.append(receipt)
    return tuple(receipts)


def profile_is_claim_ready(profile: RuntimeProfile, generation: int) -> bool:
    return (
        profile.lifecycle_state == RuntimeProfileLifecycleState.ACTIVE
        and profile.hermes_profile_key_version == 1
        and profile.materialized_generation == generation
    )


def profile_allows_runtime_write(profile: RuntimeProfile) -> bool:
    return profile.lifecycle_state == RuntimeProfileLifecycleState.ACTIVE


def profile_allows_stop(profile: RuntimeProfile) -> bool:
    return profile.lifecycle_state in {
        RuntimeProfileLifecycleState.ACTIVE,
        RuntimeProfileLifecycleState.CLEANUP_PENDING,
    }


def _normalize_seed(seed: ProfileSeed | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(seed, ProfileSeed):
        values: Mapping[str, Any] = {
            "personality": seed.personality,
            "provider": seed.provider,
            "model": seed.model,
            "first_chat_instruction": seed.first_chat_instruction,
            "credential_refs": dict(seed.credential_refs),
            "base_url": seed.base_url,
            "version": seed.version,
            "first_chat_instruction_version": seed.first_chat_instruction_version,
            "memory_provider": seed.memory_provider,
            "memory_mode": seed.memory_mode,
            "memory_policy_version": seed.memory_policy_version,
            "memory_tool_allowlist": list(seed.memory_tool_allowlist),
            "memory_profile_isolation": seed.memory_profile_isolation,
            "memory_sync_roles": list(seed.memory_sync_roles),
        }
    elif isinstance(seed, Mapping):
        values = dict(seed)
    else:
        raise RuntimeValidationError("profile seed must be an object")
    version = values.get("version", PROFILE_SEED_VERSION)
    if type(version) is not int or version != PROFILE_SEED_VERSION:
        raise RuntimeValidationError("unsupported profile seed version")
    instruction_version = values.get("first_chat_instruction_version", 1)
    if type(instruction_version) is not int or instruction_version != 1:
        raise RuntimeValidationError("unsupported first-chat instruction version")
    personality = _seed_text(values.get("personality"), "personality", 64 * 1024)
    provider = _seed_text(values.get("provider"), "provider", 128)
    model = _seed_text(values.get("model"), "model", 255)
    instruction = _seed_text(
        values.get("first_chat_instruction"), "first_chat_instruction", 32 * 1024
    )
    base_url = values.get("base_url")
    if base_url is not None:
        base_url = _seed_text(base_url, "base_url", 512)
    raw_refs = values.get("credential_refs", {})
    if type(raw_refs) is not dict:
        raise RuntimeValidationError("credential_refs must be an object")
    if len(raw_refs) > 32:
        raise RuntimeValidationError("credential_refs exceed the bounded size")
    credential_refs: dict[str, str] = {}
    for name, reference in raw_refs.items():
        if (
            type(name) is not str
            or not (
                re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name)
                or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", name)
            )
            or not isinstance(reference, str)
            or not _OPAQUE_REFERENCE.fullmatch(reference)
        ):
            raise RuntimeValidationError(
                "credential_refs must contain opaque references"
            )
        lowered = reference.lower()
        if lowered.startswith(("bearer ", "token=", "key=", "sk-", "api_key=")):
            raise RuntimeValidationError(
                "credential_refs must not contain credential values"
            )
        normalized_name = name.upper().replace("-", "_")
        if normalized_name == "API_SERVER_KEY":
            raise RuntimeValidationError(
                "credential_refs must not reserve the runtime API key"
            )
        if normalized_name in credential_refs:
            raise RuntimeValidationError(
                "credential_refs contain colliding environment names"
            )
        credential_refs[normalized_name] = reference
    credential_refs = dict(sorted(credential_refs.items()))
    memory_provider = values.get("memory_provider", DEFAULT_MEMORY_PROVIDER)
    if memory_provider != DEFAULT_MEMORY_PROVIDER:
        raise RuntimeValidationError("unsupported memory provider")
    memory_mode = values.get("memory_mode", DEFAULT_MEMORY_MODE)
    if memory_mode not in MEMORY_MODES:
        raise RuntimeValidationError("unsupported memory mode")
    memory_policy_version = values.get(
        "memory_policy_version", DEFAULT_MEMORY_POLICY_VERSION
    )
    if memory_policy_version != DEFAULT_MEMORY_POLICY_VERSION:
        raise RuntimeValidationError("unsupported memory policy version")
    memory_tool_allowlist = _memory_string_list(
        values.get("memory_tool_allowlist", []), "memory_tool_allowlist"
    )
    if not set(memory_tool_allowlist).issubset(MEMORY_TOOLS):
        raise RuntimeValidationError("unsupported memory tool allowlist")
    if memory_mode == DEFAULT_MEMORY_MODE and memory_tool_allowlist:
        raise RuntimeValidationError("context-only memory cannot advertise tools")
    if values.get("memory_profile_isolation", True) is not True:
        raise RuntimeValidationError("memory profile isolation is required")
    memory_sync_roles = _memory_string_list(
        values.get("memory_sync_roles", []), "memory_sync_roles"
    )
    if memory_sync_roles:
        raise RuntimeValidationError("memory sync roles are disabled")
    payload = {
        "version": version,
        "personality": personality,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "first_chat_instruction": instruction,
        "first_chat_instruction_version": instruction_version,
        "credential_refs": credential_refs,
        "memory_provider": memory_provider,
        "memory_mode": memory_mode,
        "memory_policy_version": memory_policy_version,
        "memory_tool_allowlist": list(memory_tool_allowlist),
        "memory_profile_isolation": True,
        "memory_sync_roles": [],
    }
    if len(str(payload).encode("utf-8")) > MAX_PROFILE_SEED_BYTES:
        raise RuntimeValidationError("profile seed exceeds the bounded size")
    return payload


def _seed_fingerprint(
    profile_id: UUID,
    hermes_profile_key: str,
    ally_ref: str,
    payload: Mapping[str, Any],
) -> str:
    """Match the dependency-free runtime ProfileSeed fingerprint exactly."""

    canonical = {
        "schema_version": payload["version"],
        "foundry_profile_id": str(profile_id),
        "hermes_profile_key": hermes_profile_key,
        "identity": {"ally_name": ally_ref},
        "personality": payload["personality"],
        "first_chat_version": payload["first_chat_instruction_version"],
        "first_chat_instruction": payload["first_chat_instruction"],
        "model": {
            "provider": payload["provider"],
            "default": payload["model"],
            "base_url": payload["base_url"],
        },
        "credential_refs": payload["credential_refs"],
        "memory": {
            "provider": payload["memory_provider"],
            "mode": payload["memory_mode"],
            "policy_version": payload["memory_policy_version"],
            "tools": payload["memory_tool_allowlist"],
            "profile_isolation": payload["memory_profile_isolation"],
            "sync_roles": payload["memory_sync_roles"],
        },
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(
        f"allies-profile-seed-v{PROFILE_FINGERPRINT_VERSION}\0".encode() + encoded
    ).hexdigest()


def _desired_state(profile: RuntimeProfile) -> ProfileDesiredState:
    try:
        seed_payload = _normalize_seed(profile.seed_payload)
    except RuntimeValidationError:
        # Never echo an untrusted/legacy JSON blob to the runtime.  The
        # profile remains visible so the operator can repair it explicitly.
        seed_payload = {"version": 0, "repair_required": True}
    key_version = profile.hermes_profile_key_version
    lifecycle_state = profile.lifecycle_state
    result_code = profile.materialization_result_code
    if key_version == 0:
        lifecycle_state = RuntimeProfileLifecycleState.REPAIR_REQUIRED
        result_code = "legacy_profile_key"
    return ProfileDesiredState(
        profile_id=profile.id,
        ally_ref=profile.ally_ref,
        hermes_profile_key=profile.hermes_profile_key,
        hermes_profile_key_version=key_version,
        lifecycle_state=lifecycle_state,
        lifecycle_epoch=profile.lifecycle_epoch,
        seed_version=profile.seed_version,
        seed_fingerprint=profile.seed_fingerprint,
        materialized_generation=profile.materialized_generation,
        active_lease_count=Lease.objects.filter(
            profile_id=profile.id,
            state__in=(LeaseState.ACTIVE, LeaseState.STOPPING),
        ).count(),
        seed_payload=seed_payload.copy(),
        materialization_operation_id=profile.materialization_operation_id,
        materialization_request_digest=profile.materialization_request_digest,
        materialization_receipt_id=profile.materialization_receipt_id,
        materialization_result_code=result_code,
        cleanup_operation_id=profile.cleanup_operation_id,
        cleanup_context_digest=profile.cleanup_context_digest,
        cleanup_request_digest=profile.cleanup_request_digest,
        cleanup_receipt_id=profile.cleanup_receipt_id,
        cleanup_result_code=profile.cleanup_result_code,
        cleanup_expires_at=profile.cleanup_expires_at,
    )


def _assert_profile_identity(
    profile: RuntimeProfile,
    workspace_id: UUID,
    ally_ref: str,
    key: str,
) -> None:
    if (
        profile.workspace_id != workspace_id
        or profile.ally_ref != ally_ref
        or profile.hermes_profile_key != key
    ):
        raise RuntimeConflictError("profile identity is immutable")
    if profile.hermes_profile_key_version == 0:
        raise RuntimeRepairRequiredError("legacy Hermes profile key requires repair")


def _assert_seed_compatible(
    profile: RuntimeProfile, payload: dict[str, Any], fingerprint: str
) -> None:
    if profile.seed_fingerprint and profile.seed_fingerprint != fingerprint:
        raise RuntimeConflictError("profile seed conflicts with stored immutable state")
    if profile.seed_payload and profile.seed_payload != payload:
        raise RuntimeConflictError("profile seed conflicts with stored immutable state")


def _materialization_receipt(profile: RuntimeProfile) -> ProfileReconciliationReceipt:
    return ProfileReconciliationReceipt(
        profile.id,
        profile.lifecycle_state,
        profile.lifecycle_epoch,
        profile.materialized_generation,
        profile.seed_fingerprint,
        profile.materialization_receipt_id,
        profile.materialization_result_code or "materialized",
    )


def _cleanup_receipt(
    profile: RuntimeProfile,
    *,
    deleted: bool | None = None,
    active_lease_count: int | None = None,
) -> ProfileReconciliationReceipt:
    if active_lease_count is None:
        active_lease_count = Lease.objects.filter(
            profile_id=profile.id,
            state__in=(LeaseState.ACTIVE, LeaseState.STOPPING),
        ).count()
    return ProfileReconciliationReceipt(
        profile.id,
        profile.lifecycle_state,
        profile.lifecycle_epoch,
        profile.materialized_generation,
        profile.seed_fingerprint,
        profile.cleanup_receipt_id,
        profile.cleanup_result_code or profile.lifecycle_state,
        deleted=(
            profile.lifecycle_state == RuntimeProfileLifecycleState.DEPROVISIONED
            if deleted is None
            else deleted
        ),
        active_lease_count=active_lease_count,
    )


def _fence_profile_leases(profile_id: UUID) -> None:
    leases = list(
        Lease.objects.select_for_update()
        .select_related("attempt__execution")
        .filter(
            profile_id=profile_id,
            state__in=(LeaseState.ACTIVE, LeaseState.STOPPING),
        )
    )
    for lease in leases:
        lease.state = LeaseState.FENCED
        lease.save(update_fields=["state", "updated_at"])
        attempt = lease.attempt
        if attempt.status in {
            AttemptStatus.QUEUED,
            AttemptStatus.LEASED,
            AttemptStatus.RUNNING,
        }:
            attempt.status = AttemptStatus.UNKNOWN
            attempt.save(update_fields=["status", "updated_at"])
        execution = attempt.execution
        if execution.status == ExecutionStatus.RUNNING:
            execution.status = ExecutionStatus.FAILED
            execution.save(update_fields=["status", "updated_at"])


def _require_context(context: RuntimeContext) -> None:
    if not isinstance(context, RuntimeContext):
        raise RuntimeValidationError("runtime context is required")


def _check_context_generation(workspace: Workspace, context: RuntimeContext) -> None:
    if workspace.machine_generation != context.machine_generation:
        raise RuntimeFencedError("runtime generation is stale")


def _require_ready_workspace(workspace: Workspace) -> None:
    if (
        workspace.provisioning_phase in IN_FLIGHT_PROVISIONING_PHASES
        or workspace.machine_generation <= 0
        or not workspace.fly_app_ref
        or not workspace.volume_ref
        or not workspace.machine_ref
    ):
        raise RuntimeNotReadyError("workspace is not ready for profile reconciliation")


def _uuid(value: UUID | str, name: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise RuntimeValidationError(f"{name} must be a UUID") from exc


def _validate_epoch(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeValidationError("lifecycle_epoch must be non-negative")


def _validate_generation(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeValidationError("materialized_generation must be positive")


def _validate_digest(value: str, name: str) -> None:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise RuntimeValidationError(f"{name} must be a lowercase SHA-256 hex digest")


def _validate_result_code(value: str) -> str:
    if not isinstance(value, str) or not _RESULT_CODE.fullmatch(value):
        raise RuntimeValidationError("result_code must be a bounded lowercase code")
    return value


def _validate_cleanup_expiry(value: datetime | None) -> datetime:
    now = timezone.now()
    value = value or now + timedelta(seconds=CLEANUP_GRACE_SECONDS)
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise RuntimeValidationError("cleanup expiry must be timezone-aware")
    if value <= now or value > now + timedelta(hours=24):
        raise RuntimeValidationError("cleanup expiry is outside the bounded window")
    return value


def _seed_text(value: Any, name: str, max_length: int) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise RuntimeValidationError(
            f"{name} must be a non-empty string of at most {max_length} characters"
        )
    if "\x00" in value or "\r" in value:
        raise RuntimeValidationError(f"{name} contains an invalid control character")
    return value


def _memory_string_list(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > 8:
        raise RuntimeValidationError(f"{name} must be a bounded list")
    if any(
        not isinstance(item, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", item)
        for item in value
    ):
        raise RuntimeValidationError(f"{name} contains an invalid value")
    normalized = tuple(sorted(value))
    if len(set(normalized)) != len(normalized):
        raise RuntimeValidationError(f"{name} contains duplicate values")
    return normalized


__all__ = [
    "CLEANUP_GRACE_SECONDS",
    "PROFILE_SEED_VERSION",
    "ProfileDesiredState",
    "ProfileProvisioningReceipt",
    "ProfileReconciliationReceipt",
    "ProfileSeed",
    "accept_cleanup_receipt",
    "accept_materialization_receipt",
    "ensure_runtime_profile",
    "expire_profile_cleanups",
    "list_profile_reconciliation",
    "profile_allows_runtime_write",
    "profile_allows_stop",
    "profile_is_claim_ready",
    "request_profile_cleanup",
]
