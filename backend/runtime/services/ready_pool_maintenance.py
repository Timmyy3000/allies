"""Bounded maintenance for complete, unassigned runtime bundles.

The pool is deliberately a one-shot control-plane pass.  Database rows reserve
capacity and phase claims; provider work runs after those short transactions
commit and is reconciled against the claim before durable state advances.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from django.conf import settings
from django.db import OperationalError, connection, transaction
from django.db.models import Q
from django.utils import timezone

from runtime.exceptions import RuntimeValidationError
from runtime.models import (
    Execution,
    ReadyWorkspaceBundle,
    ReadyWorkspaceBundleState,
    RuntimeCredential,
    RuntimeOperationState,
    RuntimeProfile,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.providers import ContainerState, MachineState, ProviderError
from runtime.services.ready_pool import RESERVED_TENANT_PREFIX
from runtime.services.release_targets import is_pending_release_target
from runtime.services.runtime_readiness import is_runtime_ready

MAX_MAINTENANCE_LIMIT = 8
ACTIVATION_CLAIM_SECONDS = 1200
CAPACITY_LOCK_KEY = 0x41524C5953504F4F  # stable advisory lock for pool capacity
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_IMMUTABLE_IMAGE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$", re.IGNORECASE)
_POOL_STATES = (
    ReadyWorkspaceBundleState.PREPARING,
    ReadyWorkspaceBundleState.READY,
    ReadyWorkspaceBundleState.EVICTING,
    ReadyWorkspaceBundleState.FAILED,
)


class PoolReadinessPending(RuntimeError):
    """The provider is alive but has not produced the current ready proof."""

    code = "readiness_pending"
    retryable = True
    readiness_pending = True


class PoolValidationError(RuntimeError):
    """A provider proof is incompatible with the configured pool contract."""

    def __init__(self, code: str) -> None:
        if not _SAFE_CODE.fullmatch(code):
            raise ValueError("pool validation code is invalid")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PoolProviderSnapshot:
    """Provider-neutral evidence for one complete bundle."""

    app_ref: str
    volume_ref: str
    machine_ref: str
    region: str
    machine_state: str
    health_containers: Mapping[str, str]
    ownership_workspace_id: UUID | str
    ownership_operation_id: UUID | str | None
    ownership_generation: int
    volume_attached_machine_ref: str | None
    images: Mapping[str, str]
    config_fingerprint: str
    blank: bool = False


class ReadyPoolAdapter(Protocol):
    """Optional provider seam used by the core maintainer."""

    def activate(self, workspace_id: UUID) -> Any: ...

    def inspect(self, workspace: Workspace) -> PoolProviderSnapshot | Any: ...

    def cleanup(self, workspace: Workspace) -> Any: ...


@dataclass(frozen=True, slots=True)
class MaintenanceResult:
    enabled: bool
    target: int
    created: int = 0
    resumed: int = 0
    refreshed: int = 0
    evicted: int = 0
    failed: int = 0
    skipped: int = 0
    ready: int = 0
    preparing: int = 0
    evicting: int = 0
    failed_rows: int = 0

    @property
    def disabled(self) -> bool:
        return not self.enabled

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "enabled": self.enabled,
            "target": self.target,
            "created": self.created,
            "resumed": self.resumed,
            "refreshed": self.refreshed,
            "evicted": self.evicted,
            "failed": self.failed,
            "skipped": self.skipped,
            "ready": self.ready,
            "preparing": self.preparing,
            "evicting": self.evicting,
            "failed_rows": self.failed_rows,
        }


@dataclass(frozen=True, slots=True)
class _PoolConfig:
    target: int
    region: str
    release_fingerprint: str
    config_version: int
    max_preparing: int
    max_attempts: int
    ready_ttl_seconds: int
    health_freshness_seconds: int
    phase_claim_seconds: int


@dataclass(frozen=True, slots=True)
class _Claim:
    bundle_id: UUID
    workspace_id: UUID
    owner: str
    action: str
    created: bool = False


def pool_config_fingerprint(
    *,
    region: str,
    images: Mapping[str, str],
    containers: Mapping[str, str] | tuple[str, ...] | list[str],
    mount_path: str = "/opt/data",
) -> str:
    """Derive a stable fingerprint from the actual pinned topology."""

    if not isinstance(images, Mapping) or not images:
        raise ValueError("pool fingerprint requires images")
    normalized_images = sorted(
        (str(name), str(image)) for name, image in images.items()
    )
    normalized_containers = sorted(str(name) for name in containers)
    payload = {
        "containers": normalized_containers,
        "images": normalized_images,
        "mount_path": mount_path,
        "region": region,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def maintain_ready_pool_once(
    *,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    adapter: ReadyPoolAdapter | None = None,
    limit: int = 1,
    drain: bool = False,
) -> MaintenanceResult:
    """Run one bounded repair/replenishment pass.

    ``READY_WORKSPACE_POOL_TARGET=0`` is the only creation gate.  ``drain``
    permits an explicitly requested cleanup pass while that gate is off.
    """

    if type(limit) is not int or not 1 <= limit <= MAX_MAINTENANCE_LIMIT:
        raise RuntimeValidationError("maintenance limit is outside the bounded range")
    if now is not None and clock is not None:
        raise RuntimeValidationError("maintenance accepts now or clock, not both")
    if clock is None:
        if now is not None:
            observed_at = _aware(now)
            clock = lambda: observed_at
        else:
            clock = lambda: _aware(timezone.now())
            observed_at = _clock_now(clock)
    else:
        observed_at = _clock_now(clock)
    config = _pool_config()
    if config.target <= 0 and not drain:
        return _result(False, config.target)
    if adapter is None:
        adapter = _default_adapter()

    counters = {
        "created": 0,
        "resumed": 0,
        "refreshed": 0,
        "evicted": 0,
        "failed": 0,
        "skipped": 0,
    }
    for _ in range(limit):
        claim_now = _clock_now(clock)
        claim = _claim_or_reserve(
            config,
            claim_now,
            allow_create=config.target > 0,
            drain=drain,
        )
        if claim is None:
            break
        if claim.created:
            counters["created"] += 1
        elif claim.action in {"prepare", "cleanup"}:
            counters["resumed"] += 1
        outcome = _run_claim(claim, adapter, config, claim_now, clock)
        counters[outcome] += 1

    return _result(True, config.target, **counters)


def _pool_config() -> _PoolConfig:
    target = int(getattr(settings, "READY_WORKSPACE_POOL_TARGET", 0))
    if not 0 <= target <= MAX_MAINTENANCE_LIMIT:
        raise RuntimeValidationError("pool target is outside the bounded range")
    region = str(getattr(settings, "READY_WORKSPACE_POOL_REGION", "")).strip()
    release = str(
        getattr(settings, "READY_WORKSPACE_POOL_RELEASE_FINGERPRINT", "")
    ).strip()
    if target and (not region or not release):
        raise RuntimeValidationError(
            "pool region and release fingerprint are required when enabled"
        )
    max_preparing = int(getattr(settings, "READY_WORKSPACE_POOL_MAX_PREPARING", 1))
    max_attempts = int(getattr(settings, "READY_WORKSPACE_POOL_MAX_ATTEMPTS", 5))
    ready_ttl_seconds = int(
        getattr(settings, "READY_WORKSPACE_POOL_READY_TTL_SECONDS", 900)
    )
    health_freshness_seconds = int(
        getattr(settings, "READY_WORKSPACE_POOL_HEALTH_FRESHNESS_SECONDS", 60)
    )
    if max_preparing != 1:
        raise RuntimeValidationError("pool preparing capacity must be one")
    if not 1 <= max_attempts <= ReadyWorkspaceBundle.MAX_ATTEMPTS:
        raise RuntimeValidationError("pool attempts are outside the bounded range")
    if ready_ttl_seconds <= 0 or health_freshness_seconds <= 0:
        raise RuntimeValidationError("pool timing settings must be positive")
    return _PoolConfig(
        target=target,
        region=region,
        release_fingerprint=release,
        config_version=int(getattr(settings, "READY_WORKSPACE_POOL_CONFIG_VERSION", 1)),
        max_preparing=max_preparing,
        max_attempts=max_attempts,
        ready_ttl_seconds=ready_ttl_seconds,
        health_freshness_seconds=health_freshness_seconds,
        phase_claim_seconds=max(
            ACTIVATION_CLAIM_SECONDS,
            int(getattr(settings, "READY_WORKSPACE_POOL_PHASE_CLAIM_SECONDS", 60)),
        ),
    )


def _claim_or_reserve(
    config: _PoolConfig,
    now: datetime,
    *,
    allow_create: bool,
    drain: bool = False,
) -> _Claim | None:
    owner = uuid4().hex
    claim_until = now + timedelta(seconds=config.phase_claim_seconds)
    with transaction.atomic(), _capacity_lock():
        available_claim = Q(phase_claim_owner__isnull=True) | Q(
            phase_claim_until__lte=now
        )
        rows = (
            ReadyWorkspaceBundle.objects.select_for_update(skip_locked=True)
            .filter(
                workspace__tenant_ref__startswith=RESERVED_TENANT_PREFIX,
                state__in=[
                    ReadyWorkspaceBundleState.EVICTING,
                    ReadyWorkspaceBundleState.PREPARING,
                    ReadyWorkspaceBundleState.FAILED,
                ],
            )
            .filter(available_claim, next_attempt_at__lte=now)
            .order_by("state", "next_attempt_at", "created_at", "id")[
                :MAX_MAINTENANCE_LIMIT
            ]
        )
        for bundle in rows:
            workspace = (
                Workspace.objects.select_for_update()
                .filter(pk=bundle.workspace_id)
                .first()
            )
            if workspace is None or _workspace_claim_live(workspace, now):
                continue
            if (
                not workspace.tenant_ref.startswith(RESERVED_TENANT_PREFIX)
                and bundle.state != ReadyWorkspaceBundleState.EVICTING
            ):
                continue
            exhausted = bundle.attempt_count >= config.max_attempts
            owned_for_cleanup = _has_owned_resources(workspace)
            if (
                bundle.state == ReadyWorkspaceBundleState.FAILED
                and exhausted
                and not owned_for_cleanup
            ):
                continue
            action = (
                "cleanup"
                if bundle.state == ReadyWorkspaceBundleState.EVICTING
                or (bundle.state == ReadyWorkspaceBundleState.FAILED and exhausted)
                else "prepare"
            )
            bundle.phase_claim_owner = owner
            bundle.phase_claim_until = claim_until
            bundle.save(
                update_fields=[
                    "phase_claim_owner",
                    "phase_claim_until",
                    "updated_at",
                ]
            )
            return _Claim(bundle.id, workspace.id, owner, action)

        if drain and config.target <= 0:
            ready = _drain_ready_bundle(now)
            if ready is not None:
                bundle, workspace = ready
                bundle.state = ReadyWorkspaceBundleState.EVICTING
                bundle.next_attempt_at = now
                bundle.safe_error_code = "pool_disabled"
                bundle.phase_claim_owner = owner
                bundle.phase_claim_until = claim_until
                bundle.save(
                    update_fields=[
                        "state",
                        "next_attempt_at",
                        "safe_error_code",
                        "phase_claim_owner",
                        "phase_claim_until",
                        "updated_at",
                    ]
                )
                return _Claim(bundle.id, workspace.id, owner, "cleanup")

        stale = _stale_ready_bundle(config, now)
        if stale is not None:
            bundle, workspace = stale
            bundle.state = ReadyWorkspaceBundleState.EVICTING
            bundle.next_attempt_at = now
            bundle.safe_error_code = _stale_code(bundle, workspace, config, now)
            bundle.phase_claim_owner = owner
            bundle.phase_claim_until = claim_until
            bundle.save(
                update_fields=[
                    "state",
                    "next_attempt_at",
                    "safe_error_code",
                    "phase_claim_owner",
                    "phase_claim_until",
                    "updated_at",
                ]
            )
            return _Claim(bundle.id, workspace.id, owner, "cleanup")

        # Revalidate one healthy row per pass so a live provider failure is
        # discovered even when the durable health timestamp is still fresh.
        if config.target > 0:
            health_candidate = _health_candidate(config, now)
            if health_candidate is not None:
                bundle, workspace = health_candidate
                bundle.phase_claim_owner = owner
                bundle.phase_claim_until = claim_until
                bundle.save(
                    update_fields=[
                        "phase_claim_owner",
                        "phase_claim_until",
                        "updated_at",
                    ]
                )
                return _Claim(bundle.id, workspace.id, owner, "health")

        if not allow_create:
            return None
        if _fresh_ready_count(config, now) >= config.target:
            return None
        occupied = _occupied_count()
        preparing = ReadyWorkspaceBundle.objects.filter(
            state=ReadyWorkspaceBundleState.PREPARING,
            workspace__tenant_ref__startswith=RESERVED_TENANT_PREFIX,
        ).count()
        if occupied >= config.target + config.max_preparing:
            return None
        if preparing >= config.max_preparing:
            return None

        workspace = Workspace.objects.create(
            tenant_ref=f"{RESERVED_TENANT_PREFIX}{uuid4()}"
        )
        bundle = ReadyWorkspaceBundle.objects.create(
            workspace=workspace,
            state=ReadyWorkspaceBundleState.PREPARING,
            region=config.region,
            release_fingerprint=config.release_fingerprint,
            config_version=config.config_version,
            next_attempt_at=now,
            phase_claim_owner=owner,
            phase_claim_until=claim_until,
        )
        return _Claim(bundle.id, workspace.id, owner, "prepare", created=True)


def _drain_ready_bundle(
    now: datetime,
) -> tuple[ReadyWorkspaceBundle, Workspace] | None:
    available_claim = Q(phase_claim_owner__isnull=True) | Q(phase_claim_until__lte=now)
    rows = (
        ReadyWorkspaceBundle.objects.select_for_update(skip_locked=True)
        .filter(
            state=ReadyWorkspaceBundleState.READY,
            workspace__tenant_ref__startswith=RESERVED_TENANT_PREFIX,
        )
        .filter(available_claim)
        .order_by("ready_at", "id")[:MAX_MAINTENANCE_LIMIT]
    )
    for bundle in rows:
        workspace = (
            Workspace.objects.select_for_update().filter(pk=bundle.workspace_id).first()
        )
        if (
            workspace is not None
            and workspace.tenant_ref.startswith(RESERVED_TENANT_PREFIX)
            and not _workspace_claim_live(workspace, now)
        ):
            return bundle, workspace
    return None


def _stale_ready_bundle(
    config: _PoolConfig,
    now: datetime,
) -> tuple[ReadyWorkspaceBundle, Workspace] | None:
    rows = (
        ReadyWorkspaceBundle.objects.select_for_update(skip_locked=True)
        .filter(
            state=ReadyWorkspaceBundleState.READY,
            workspace__tenant_ref__startswith=RESERVED_TENANT_PREFIX,
        )
        .filter(Q(phase_claim_owner__isnull=True) | Q(phase_claim_until__lte=now))
        .order_by("ready_at", "id")[:MAX_MAINTENANCE_LIMIT]
    )
    for bundle in rows:
        workspace = (
            Workspace.objects.select_for_update().filter(pk=bundle.workspace_id).first()
        )
        if (
            workspace is None
            or not workspace.tenant_ref.startswith(RESERVED_TENANT_PREFIX)
            or _workspace_claim_live(workspace, now)
        ):
            continue
        if (
            _db_ready_evidence(
                bundle, workspace, config, now, require_fresh_health=False
            )
            and bundle.last_health_at is not None
        ):
            continue
        return bundle, workspace
    return None


def _health_candidate(
    config: _PoolConfig,
    now: datetime,
) -> tuple[ReadyWorkspaceBundle, Workspace] | None:
    rows = (
        ReadyWorkspaceBundle.objects.select_for_update(skip_locked=True)
        .filter(
            state=ReadyWorkspaceBundleState.READY,
            workspace__tenant_ref__startswith=RESERVED_TENANT_PREFIX,
            region=config.region,
            release_fingerprint=config.release_fingerprint,
            config_version=config.config_version,
            next_attempt_at__lte=now,
        )
        .filter(Q(phase_claim_owner__isnull=True) | Q(phase_claim_until__lte=now))
        .order_by("last_health_at", "ready_at", "id")[:MAX_MAINTENANCE_LIMIT]
    )
    for bundle in rows:
        workspace = (
            Workspace.objects.select_for_update().filter(pk=bundle.workspace_id).first()
        )
        if (
            workspace is not None
            and workspace.tenant_ref.startswith(RESERVED_TENANT_PREFIX)
            and not _workspace_claim_live(workspace, now)
        ):
            return bundle, workspace
    return None


def _run_claim(
    claim: _Claim,
    adapter: ReadyPoolAdapter,
    config: _PoolConfig,
    now: datetime,
    clock: Callable[[], datetime],
) -> str:
    if not _claim_is_live(claim, now):
        return "skipped"
    workspace = Workspace.objects.filter(pk=claim.workspace_id).first()
    if workspace is None:
        return _record_failure(claim, "workspace_missing", config, _clock_now(clock))
    if claim.action == "cleanup":
        return _run_cleanup(claim, workspace, adapter, config, now, clock)
    if claim.action == "health":
        return _run_health_check(claim, workspace, adapter, config, now, clock)
    return _run_prepare(claim, workspace, adapter, config, now, clock)


def _run_prepare(
    claim: _Claim,
    workspace: Workspace,
    adapter: ReadyPoolAdapter,
    config: _PoolConfig,
    now: datetime,
    clock: Callable[[], datetime],
) -> str:
    try:
        _call_adapter(adapter, "activate", workspace.id)
        workspace.refresh_from_db()
        snapshot = _call_adapter(adapter, "inspect", workspace)
        completed_at = _clock_now(clock)
        _validate_ready(workspace, snapshot, config, completed_at)
        if not _record_blank_volume(claim, workspace.id, snapshot, completed_at):
            return "skipped"
    except PoolReadinessPending:
        _persist_pending_fresh_volume(claim, workspace, adapter, clock)
        return _record_pending(claim, config, _clock_now(clock))
    except Exception as exc:  # noqa: BLE001 - classify into durable safe state
        completed_at = _clock_now(clock)
        if _readiness_pending(exc):
            _persist_pending_fresh_volume(claim, workspace, adapter, clock)
            return _record_pending(claim, config, _clock_now(clock))
        if _is_retryable(exc):
            return _record_retry(
                claim, _safe_code(exc, "provider_retryable"), config, completed_at
            )
        try:
            workspace.refresh_from_db()
        except Workspace.DoesNotExist:
            return _record_failure(claim, "workspace_missing", config, now)
        if _has_owned_resources(workspace):
            transition = _transition_to_evicting(
                claim, _safe_code(exc, "bundle_validation_failed"), completed_at
            )
            if transition:
                workspace.refresh_from_db()
                return _run_cleanup(
                    claim, workspace, adapter, config, completed_at, clock
                )
            return "skipped"
        return _record_terminal_failure(
            claim, _safe_code(exc, "bundle_prepare_failed"), config, completed_at
        )

    if _mark_ready(claim, workspace.id, config, completed_at):
        return "refreshed"
    return "skipped"


def _run_health_check(
    claim: _Claim,
    workspace: Workspace,
    adapter: ReadyPoolAdapter,
    config: _PoolConfig,
    now: datetime,
    clock: Callable[[], datetime],
) -> str:
    try:
        snapshot = _call_adapter(adapter, "inspect", workspace)
        completed_at = _clock_now(clock)
        _validate_ready(
            workspace, snapshot, config, completed_at, require_blank_proof=True
        )
    except Exception as exc:  # noqa: BLE001 - health is an external boundary
        completed_at = _clock_now(clock)
        if _is_retryable(exc) and not _readiness_pending(exc):
            return _record_retry(
                claim, _safe_code(exc, "health_check_failed"), config, completed_at
            )
        if _readiness_pending(exc):
            code = _safe_code(exc, "provider_not_ready")
        else:
            code = _safe_code(exc, "stale_bundle")
        if not _transition_to_evicting(claim, code, completed_at):
            return "skipped"
        workspace.refresh_from_db()
        return _run_cleanup(claim, workspace, adapter, config, completed_at, clock)
    if _refresh_health(claim, config, completed_at):
        return "refreshed"
    return "skipped"


def _run_cleanup(
    claim: _Claim,
    workspace: Workspace,
    adapter: ReadyPoolAdapter,
    config: _PoolConfig,
    now: datetime,
    clock: Callable[[], datetime],
) -> str:
    if not _cleanup_allowed(workspace, _clock_now(clock)):
        _record_terminal_failure(
            claim, "assigned_cleanup_refused", config, _clock_now(clock)
        )
        return "failed"
    try:
        completed = _call_adapter(adapter, "cleanup", workspace)
        if completed is False:
            raise PoolReadinessPending()
    except Exception as exc:  # noqa: BLE001 - cleanup stays resumable
        completed_at = _clock_now(clock)
        if isinstance(exc, PoolReadinessPending) or _is_retryable(exc):
            return _record_retry(
                claim, _safe_code(exc, "cleanup_pending"), config, completed_at
            )
        if _safe_code(exc, "") == "provider_not_found":
            completed = True
        else:
            return _record_retry(
                claim, _safe_code(exc, "cleanup_failed"), config, completed_at
            )
    completed_at = _clock_now(clock)
    if completed is not False and _mark_evicted(claim, completed_at):
        return "evicted"
    return "skipped"


def _validate_ready(
    workspace: Workspace,
    snapshot: Any,
    config: _PoolConfig,
    now: datetime,
    *,
    require_blank_proof: bool = False,
) -> None:
    if not _db_blank_ready(workspace, now):
        raise PoolValidationError("workspace_not_blank")
    if snapshot is None:
        raise PoolReadinessPending()
    if isinstance(snapshot, bool):
        if not snapshot:
            raise PoolReadinessPending()
        raise PoolValidationError("provider_snapshot_missing")
    if _snapshot_value(snapshot, "blank", False) is not True:
        raise PoolValidationError("volume_not_blank")
    if require_blank_proof and not _blank_volume_proven(
        workspace.id, workspace.volume_ref
    ):
        raise PoolValidationError("blank_volume_proof_missing")
    if (
        _normalize_state(_snapshot_value(snapshot, "machine_state"))
        != MachineState.STARTED.value
    ):
        raise PoolReadinessPending()
    containers = _snapshot_value(snapshot, "health_containers", {})
    if not isinstance(containers, Mapping):
        raise PoolReadinessPending()
    required = {"hermes", "allies-runtime"}
    if set(containers) != required or any(
        _normalize_state(value)
        not in {ContainerState.STARTED.value, "healthy", "passing"}
        for value in containers.values()
    ):
        raise PoolReadinessPending()
    expected = {
        "app_ref": workspace.fly_app_ref,
        "volume_ref": workspace.volume_ref,
        "machine_ref": workspace.machine_ref,
        "region": config.region,
    }
    for key, value in expected.items():
        if not value or _snapshot_value(snapshot, key) != value:
            raise PoolValidationError(f"provider_{key}_mismatch")
    if (
        _snapshot_value(snapshot, "volume_attached_machine_ref")
        != workspace.machine_ref
    ):
        raise PoolValidationError("volume_attachment_mismatch")
    owner = _snapshot_value(snapshot, "ownership_workspace_id")
    if str(owner) != str(workspace.id):
        raise PoolValidationError("provider_workspace_ownership_mismatch")
    if (
        _snapshot_value(snapshot, "ownership_generation")
        != workspace.machine_generation
    ):
        raise PoolValidationError("provider_generation_mismatch")
    operation = _snapshot_value(snapshot, "ownership_operation_id")
    if workspace.provisioning_id is not None and str(operation) != str(
        workspace.provisioning_id
    ):
        raise PoolValidationError("provider_operation_ownership_mismatch")
    images = _snapshot_value(snapshot, "images", {})
    if not isinstance(images, Mapping) or set(images) != required:
        raise PoolValidationError("provider_topology_mismatch")
    if any(
        not isinstance(image, str) or not _IMMUTABLE_IMAGE.fullmatch(image)
        for image in images.values()
    ):
        raise PoolValidationError("provider_images_unpinned")
    fingerprint = _snapshot_value(snapshot, "config_fingerprint")
    expected_fingerprint = pool_config_fingerprint(
        region=config.region,
        images=images,
        containers=tuple(images),
    )
    if fingerprint != expected_fingerprint:
        raise PoolValidationError("provider_config_fingerprint_invalid")
    if fingerprint != config.release_fingerprint:
        raise PoolValidationError("provider_config_fingerprint_mismatch")


def _db_blank_ready(workspace: Workspace, now: datetime) -> bool:
    return bool(
        workspace.tenant_ref.startswith(RESERVED_TENANT_PREFIX)
        and workspace.provisioning_phase == WorkspaceProvisioningPhase.IDLE
        and workspace.runtime_operation_state == RuntimeOperationState.IDLE
        and not is_pending_release_target(workspace.release_target)
        and workspace.activation_claim_token is None
        and workspace.activation_claim_expires_at is None
        and workspace.provisioning_claim_token is None
        and workspace.provisioning_claim_expires_at is None
        and is_runtime_ready(workspace, now=now)
        and RuntimeCredential.objects.filter(
            workspace_id=workspace.id,
            machine_generation=workspace.machine_generation,
            revoked_at__isnull=True,
        ).count()
        == 1
        and not RuntimeProfile.objects.filter(workspace_id=workspace.id).exists()
        and not Execution.objects.filter(workspace_id=workspace.id).exists()
    )


def _blank_volume_proven(workspace_id: UUID, volume_ref: str | None) -> bool:
    return bool(
        volume_ref
        and ReadyWorkspaceBundle.objects.filter(
            workspace_id=workspace_id,
            blank_volume_ref=volume_ref,
        ).exists()
    )


def _record_blank_volume(
    claim: _Claim,
    workspace_id: UUID,
    snapshot: Any,
    now: datetime,
) -> bool:
    volume_ref = _snapshot_value(snapshot, "volume_ref")
    if not isinstance(volume_ref, str) or not volume_ref:
        return False
    with transaction.atomic():
        bundle = (
            ReadyWorkspaceBundle.objects.select_for_update()
            .filter(
                pk=claim.bundle_id,
                workspace_id=workspace_id,
                state=ReadyWorkspaceBundleState.PREPARING,
                phase_claim_owner=claim.owner,
                phase_claim_until__gt=now,
            )
            .first()
        )
        workspace = (
            Workspace.objects.select_for_update().filter(pk=workspace_id).first()
        )
        if (
            bundle is None
            or workspace is None
            or bundle.blank_volume_ref not in (None, volume_ref)
            or workspace.volume_ref != volume_ref
            or not _db_blank_ready(workspace, now)
        ):
            return False
        bundle.blank_volume_ref = volume_ref
        bundle.save(update_fields=["blank_volume_ref", "updated_at"])
        return True


def _persist_pending_fresh_volume(
    claim: _Claim,
    workspace: Workspace,
    adapter: ReadyPoolAdapter,
    clock: Callable[[], datetime],
) -> bool:
    """Persist a fresh-volume proof while readiness remains pending."""

    recorder = getattr(adapter, "record_fresh_volume", None)
    if not callable(recorder):
        return False
    try:
        workspace.refresh_from_db()
        volume_ref = recorder(workspace)
    except Exception:  # noqa: BLE001 - retain the original pending outcome
        return False
    return _record_fresh_blank_volume(
        claim, workspace.id, volume_ref, _clock_now(clock)
    )


def _record_fresh_blank_volume(
    claim: _Claim,
    workspace_id: UUID,
    volume_ref: Any,
    now: datetime,
) -> bool:
    if not isinstance(volume_ref, str) or not volume_ref:
        return False
    with transaction.atomic():
        bundle = (
            ReadyWorkspaceBundle.objects.select_for_update()
            .filter(
                pk=claim.bundle_id,
                workspace_id=workspace_id,
                state=ReadyWorkspaceBundleState.PREPARING,
                phase_claim_owner=claim.owner,
                phase_claim_until__gt=now,
            )
            .first()
        )
        workspace = (
            Workspace.objects.select_for_update().filter(pk=workspace_id).first()
        )
        active_credentials = RuntimeCredential.objects.filter(
            workspace_id=workspace_id,
            machine_generation=workspace.machine_generation if workspace else 0,
            revoked_at__isnull=True,
        ).count()
        if (
            bundle is None
            or workspace is None
            or bundle.blank_volume_ref not in (None, volume_ref)
            or not workspace.tenant_ref.startswith(RESERVED_TENANT_PREFIX)
            or workspace.provisioning_phase != WorkspaceProvisioningPhase.IDLE
            or workspace.runtime_operation_state
            not in {
                RuntimeOperationState.IDLE,
                RuntimeOperationState.AWAITING_READINESS,
            }
            or is_pending_release_target(workspace.release_target)
            or workspace.activation_claim_token is not None
            or workspace.activation_claim_expires_at is not None
            or workspace.provisioning_claim_token is not None
            or workspace.provisioning_claim_expires_at is not None
            or not workspace.fly_app_ref
            or workspace.volume_ref != volume_ref
            or not workspace.machine_ref
            or workspace.machine_generation <= 0
            or active_credentials != 1
            or RuntimeProfile.objects.filter(workspace_id=workspace_id).exists()
            or Execution.objects.filter(workspace_id=workspace_id).exists()
        ):
            return False
        bundle.blank_volume_ref = volume_ref
        bundle.save(update_fields=["blank_volume_ref", "updated_at"])
        return True


def _db_ready_evidence(
    bundle: ReadyWorkspaceBundle,
    workspace: Workspace,
    config: _PoolConfig,
    now: datetime,
    *,
    require_fresh_health: bool = True,
) -> bool:
    return bool(
        bundle.state == ReadyWorkspaceBundleState.READY
        and bundle.region == config.region
        and bundle.release_fingerprint == config.release_fingerprint
        and bundle.config_version == config.config_version
        and bundle.blank_volume_ref == workspace.volume_ref
        and bundle.ready_at is not None
        and bundle.expires_at is not None
        and bundle.expires_at > now
        and (
            not require_fresh_health
            or (
                bundle.last_health_at is not None
                and bundle.last_health_at
                >= now - timedelta(seconds=config.health_freshness_seconds)
            )
        )
        and _db_blank_ready(workspace, now)
    )


def _mark_ready(
    claim: _Claim,
    workspace_id: UUID,
    config: _PoolConfig,
    now: datetime,
) -> bool:
    with transaction.atomic():
        bundle = (
            ReadyWorkspaceBundle.objects.select_for_update()
            .filter(
                pk=claim.bundle_id,
                workspace_id=workspace_id,
                phase_claim_until__gt=now,
            )
            .first()
        )
        workspace = (
            Workspace.objects.select_for_update().filter(pk=workspace_id).first()
        )
        if (
            bundle is None
            or workspace is None
            or bundle.state != ReadyWorkspaceBundleState.PREPARING
            or bundle.phase_claim_owner != claim.owner
            or bundle.blank_volume_ref != workspace.volume_ref
            or not _db_blank_ready(workspace, now)
        ):
            return False
        bundle.state = ReadyWorkspaceBundleState.READY
        bundle.ready_at = now
        bundle.expires_at = now + timedelta(seconds=config.ready_ttl_seconds)
        bundle.last_health_at = now
        bundle.next_attempt_at = now + timedelta(
            seconds=config.health_freshness_seconds
        )
        bundle.safe_error_code = None
        bundle.attempt_count = 0
        bundle.phase_claim_owner = None
        bundle.phase_claim_until = None
        bundle.save(
            update_fields=[
                "state",
                "ready_at",
                "expires_at",
                "last_health_at",
                "next_attempt_at",
                "safe_error_code",
                "attempt_count",
                "phase_claim_owner",
                "phase_claim_until",
                "updated_at",
            ]
        )
        return True


def _refresh_health(claim: _Claim, config: _PoolConfig, now: datetime) -> bool:
    with transaction.atomic():
        bundle = (
            ReadyWorkspaceBundle.objects.select_for_update()
            .filter(
                pk=claim.bundle_id,
                state=ReadyWorkspaceBundleState.READY,
                phase_claim_until__gt=now,
            )
            .first()
        )
        workspace = (
            Workspace.objects.select_for_update().filter(pk=claim.workspace_id).first()
        )
        if (
            bundle is None
            or workspace is None
            or bundle.phase_claim_owner != claim.owner
            or bundle.blank_volume_ref != workspace.volume_ref
            or not _db_blank_ready(workspace, now)
        ):
            return False
        bundle.last_health_at = now
        bundle.expires_at = now + timedelta(seconds=config.ready_ttl_seconds)
        bundle.next_attempt_at = now + timedelta(
            seconds=config.health_freshness_seconds
        )
        bundle.attempt_count = 0
        bundle.safe_error_code = None
        bundle.phase_claim_owner = None
        bundle.phase_claim_until = None
        bundle.save(
            update_fields=[
                "last_health_at",
                "expires_at",
                "next_attempt_at",
                "attempt_count",
                "safe_error_code",
                "phase_claim_owner",
                "phase_claim_until",
                "updated_at",
            ]
        )
        return True


def _transition_to_evicting(claim: _Claim, code: str, now: datetime) -> bool:
    with transaction.atomic():
        bundle = (
            ReadyWorkspaceBundle.objects.select_for_update()
            .filter(
                pk=claim.bundle_id,
                phase_claim_until__gt=now,
            )
            .first()
        )
        if bundle is None or bundle.phase_claim_owner != claim.owner:
            return False
        if bundle.state == ReadyWorkspaceBundleState.ASSIGNED:
            return False
        bundle.state = ReadyWorkspaceBundleState.EVICTING
        bundle.next_attempt_at = now
        bundle.safe_error_code = _safe_code_value(code, "stale_bundle")
        bundle.save(
            update_fields=["state", "next_attempt_at", "safe_error_code", "updated_at"]
        )
        return True


def _mark_evicted(claim: _Claim, now: datetime) -> bool:
    with transaction.atomic():
        bundle = (
            ReadyWorkspaceBundle.objects.select_for_update()
            .filter(
                pk=claim.bundle_id,
                phase_claim_until__gt=now,
            )
            .first()
        )
        workspace = (
            Workspace.objects.select_for_update().filter(pk=claim.workspace_id).first()
        )
        if (
            bundle is None
            or workspace is None
            or bundle.phase_claim_owner != claim.owner
        ):
            return False
        if bundle.state == ReadyWorkspaceBundleState.ASSIGNED or not _cleanup_allowed(
            workspace, now
        ):
            return False
        bundle.state = ReadyWorkspaceBundleState.EVICTED
        bundle.phase_claim_owner = None
        bundle.phase_claim_until = None
        bundle.next_attempt_at = now
        bundle.save(
            update_fields=[
                "state",
                "phase_claim_owner",
                "phase_claim_until",
                "next_attempt_at",
                "updated_at",
            ]
        )
        return True


def _record_pending(claim: _Claim, config: _PoolConfig, now: datetime) -> str:
    with transaction.atomic():
        bundle = (
            ReadyWorkspaceBundle.objects.select_for_update()
            .filter(
                pk=claim.bundle_id,
                phase_claim_until__gt=now,
            )
            .first()
        )
        if bundle is None or bundle.phase_claim_owner != claim.owner:
            return "skipped"
        bundle.next_attempt_at = now + timedelta(seconds=1)
        bundle.phase_claim_owner = None
        bundle.phase_claim_until = None
        bundle.safe_error_code = "readiness_pending"
        bundle.save(
            update_fields=[
                "next_attempt_at",
                "phase_claim_owner",
                "phase_claim_until",
                "safe_error_code",
                "updated_at",
            ]
        )
        return "skipped"


def _record_retry(claim: _Claim, code: str, config: _PoolConfig, now: datetime) -> str:
    with transaction.atomic():
        bundle = (
            ReadyWorkspaceBundle.objects.select_for_update()
            .filter(
                pk=claim.bundle_id,
                phase_claim_until__gt=now,
            )
            .first()
        )
        if bundle is None or bundle.phase_claim_owner != claim.owner:
            return "skipped"
        bundle.attempt_count = min(bundle.attempt_count + 1, config.max_attempts)
        bundle.safe_error_code = _safe_code_value(code, "provider_retryable")
        bundle.next_attempt_at = now + timedelta(
            seconds=min(60, 2 ** max(0, bundle.attempt_count - 1))
        )
        if bundle.attempt_count >= config.max_attempts:
            bundle.state = ReadyWorkspaceBundleState.FAILED
        bundle.phase_claim_owner = None
        bundle.phase_claim_until = None
        bundle.save(
            update_fields=[
                "attempt_count",
                "safe_error_code",
                "next_attempt_at",
                "state",
                "phase_claim_owner",
                "phase_claim_until",
                "updated_at",
            ]
        )
        return (
            "failed" if bundle.state == ReadyWorkspaceBundleState.FAILED else "skipped"
        )


def _record_failure(
    claim: _Claim, code: str, config: _PoolConfig, now: datetime
) -> str:
    return _record_terminal_failure(claim, code, config, now)


def _record_terminal_failure(
    claim: _Claim,
    code: str,
    config: _PoolConfig,
    now: datetime,
) -> str:
    with transaction.atomic():
        bundle = (
            ReadyWorkspaceBundle.objects.select_for_update()
            .filter(
                pk=claim.bundle_id,
                phase_claim_until__gt=now,
            )
            .first()
        )
        if bundle is None or bundle.phase_claim_owner != claim.owner:
            return "skipped"
        if bundle.state != ReadyWorkspaceBundleState.ASSIGNED:
            bundle.state = ReadyWorkspaceBundleState.FAILED
            bundle.attempt_count = min(bundle.attempt_count + 1, config.max_attempts)
            bundle.safe_error_code = _safe_code_value(code, "bundle_failed")
            bundle.next_attempt_at = now + timedelta(seconds=60)
            bundle.phase_claim_owner = None
            bundle.phase_claim_until = None
            bundle.save(
                update_fields=[
                    "state",
                    "attempt_count",
                    "safe_error_code",
                    "next_attempt_at",
                    "phase_claim_owner",
                    "phase_claim_until",
                    "updated_at",
                ]
            )
            return "failed"
    return "skipped"


def _cleanup_allowed(workspace: Workspace, now: datetime) -> bool:
    return bool(
        workspace.tenant_ref.startswith(RESERVED_TENANT_PREFIX)
        and not _workspace_claim_live(workspace, now)
        and not RuntimeProfile.objects.filter(workspace_id=workspace.id).exists()
        and not Execution.objects.filter(workspace_id=workspace.id).exists()
    )


def _has_owned_resources(workspace: Workspace) -> bool:
    return bool(
        workspace.fly_app_ref
        or workspace.volume_ref
        or workspace.machine_ref
        or RuntimeCredential.objects.filter(workspace_id=workspace.id).exists()
    )


def _workspace_claim_live(workspace: Workspace, now: datetime) -> bool:
    return bool(
        _claim_value_live(
            workspace.activation_claim_token,
            workspace.activation_claim_expires_at,
            now,
        )
        or _claim_value_live(
            workspace.provisioning_claim_token,
            workspace.provisioning_claim_expires_at,
            now,
        )
    )


def _claim_value_live(
    token: str | None, expires_at: datetime | None, now: datetime
) -> bool:
    if not token:
        return False
    return expires_at is None or expires_at > now


def _claim_is_live(claim: _Claim, now: datetime) -> bool:
    return ReadyWorkspaceBundle.objects.filter(
        pk=claim.bundle_id,
        workspace_id=claim.workspace_id,
        phase_claim_owner=claim.owner,
        phase_claim_until__gt=now,
    ).exists()


def _fresh_ready_count(config: _PoolConfig, now: datetime) -> int:
    return ReadyWorkspaceBundle.objects.filter(
        state=ReadyWorkspaceBundleState.READY,
        workspace__tenant_ref__startswith=RESERVED_TENANT_PREFIX,
        region=config.region,
        release_fingerprint=config.release_fingerprint,
        config_version=config.config_version,
        ready_at__isnull=False,
        expires_at__gt=now,
        last_health_at__gte=now - timedelta(seconds=config.health_freshness_seconds),
    ).count()


def _occupied_count() -> int:
    active_states = tuple(
        state for state in _POOL_STATES if state != ReadyWorkspaceBundleState.FAILED
    )
    failed_with_resources = (
        ReadyWorkspaceBundle.objects.filter(state=ReadyWorkspaceBundleState.FAILED)
        .filter(workspace__tenant_ref__startswith=RESERVED_TENANT_PREFIX)
        .filter(
            Q(workspace__fly_app_ref__isnull=False)
            | Q(workspace__volume_ref__isnull=False)
            | Q(workspace__machine_ref__isnull=False)
            | Q(workspace__runtime_credentials__revoked_at__isnull=True)
        )
        .distinct()
        .count()
    )
    return (
        ReadyWorkspaceBundle.objects.filter(
            state__in=active_states,
            workspace__tenant_ref__startswith=RESERVED_TENANT_PREFIX,
        ).count()
        + failed_with_resources
    )


@contextmanager
def _capacity_lock():
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [CAPACITY_LOCK_KEY])
    yield


def _call_adapter(adapter: ReadyPoolAdapter, method: str, *args: Any) -> Any:
    function = getattr(adapter, method, None)
    if not callable(function):
        aliases = {
            "activate": "activate_workspace",
            "inspect": "inspect_bundle",
            "cleanup": "cleanup_owned_resources",
        }
        function = getattr(adapter, aliases[method], None)
    if not callable(function):
        raise RuntimeValidationError(f"pool adapter does not implement {method}")
    return function(*args)


def _snapshot_value(snapshot: Any, key: str, default: Any = None) -> Any:
    if isinstance(snapshot, Mapping):
        return snapshot.get(key, default)
    return getattr(snapshot, key, default)


def _normalize_state(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value)).lower()


def _stale_code(
    bundle: ReadyWorkspaceBundle,
    workspace: Workspace,
    config: _PoolConfig,
    now: datetime,
) -> str:
    if not workspace.tenant_ref.startswith(RESERVED_TENANT_PREFIX):
        return "assigned_cleanup_refused"
    if bundle.expires_at is None or bundle.expires_at <= now:
        return "bundle_expired"
    if bundle.last_health_at is None or bundle.last_health_at < now - timedelta(
        seconds=config.health_freshness_seconds
    ):
        return "bundle_health_stale"
    if bundle.region != config.region:
        return "bundle_region_mismatch"
    if bundle.release_fingerprint != config.release_fingerprint:
        return "bundle_release_mismatch"
    if bundle.config_version != config.config_version:
        return "bundle_config_mismatch"
    return "bundle_not_blank"


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, ProviderError):
        return bool(exc.retryable)
    return isinstance(exc, OperationalError) or bool(getattr(exc, "retryable", False))


def _readiness_pending(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "readiness_pending", False):
            return True
        code = str(getattr(current, "code", "")).lower()
        if code in {"readiness_pending", "provider_not_ready", "runtime_not_ready"}:
            return True
        message = str(current).lower()
        if any(
            marker in message
            for marker in (
                "readiness receipt is pending",
                "activation is pending",
                "machine is not ready",
            )
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def _safe_code(exc: BaseException, fallback: str) -> str:
    return _safe_code_value(getattr(exc, "code", None), fallback)


def _safe_code_value(value: Any, fallback: str) -> str:
    candidate = value if isinstance(value, str) else fallback
    return candidate if _SAFE_CODE.fullmatch(candidate) else fallback


def _result(enabled: bool, target: int, **values: int) -> MaintenanceResult:
    counts = _pool_counts()
    return MaintenanceResult(
        enabled=enabled,
        target=target,
        created=int(values.get("created", 0)),
        resumed=int(values.get("resumed", 0)),
        refreshed=int(values.get("refreshed", 0)),
        evicted=int(values.get("evicted", 0)),
        failed=int(values.get("failed", 0)),
        skipped=int(values.get("skipped", 0)),
        **counts,
    )


def _pool_counts() -> dict[str, int]:
    return {
        "ready": ReadyWorkspaceBundle.objects.filter(
            state=ReadyWorkspaceBundleState.READY
        ).count(),
        "preparing": ReadyWorkspaceBundle.objects.filter(
            state=ReadyWorkspaceBundleState.PREPARING
        ).count(),
        "evicting": ReadyWorkspaceBundle.objects.filter(
            state=ReadyWorkspaceBundleState.EVICTING
        ).count(),
        "failed_rows": ReadyWorkspaceBundle.objects.filter(
            state=ReadyWorkspaceBundleState.FAILED
        ).count(),
    }


def _aware(value: datetime) -> datetime:
    if timezone.is_naive(value):
        raise RuntimeValidationError("maintenance timestamps must include a timezone")
    return value


def _clock_now(clock: Callable[[], datetime]) -> datetime:
    return _aware(clock())


def _default_adapter() -> ReadyPoolAdapter:
    from runtime.providers.fly_pool import FlyPoolAdapter

    return FlyPoolAdapter.from_environment()


__all__ = [
    "ACTIVATION_CLAIM_SECONDS",
    "CAPACITY_LOCK_KEY",
    "MaintenanceResult",
    "PoolProviderSnapshot",
    "PoolReadinessPending",
    "PoolValidationError",
    "ReadyPoolAdapter",
    "maintain_ready_pool_once",
    "pool_config_fingerprint",
]
