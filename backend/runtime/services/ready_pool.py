from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from runtime.exceptions import RuntimeConflictError, RuntimeValidationError
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
from runtime.services.runtime_readiness import is_runtime_ready

RESERVED_TENANT_PREFIX = "pool:"
MAX_ASSIGNMENT_CANDIDATES = 8


def is_canonical_cloud_workspace_ref(value: UUID | str) -> bool:
    try:
        raw = str(value)
        return str(UUID(raw)) == raw
    except (AttributeError, TypeError, ValueError):
        return False


def assign_ready_workspace(
    tenant_ref: UUID | str,
    *,
    now: datetime | None = None,
) -> Workspace | None:
    """Atomically transfer one eligible ready bundle to a Cloud workspace."""

    tenant_ref = str(tenant_ref)
    if (
        not is_canonical_cloud_workspace_ref(tenant_ref)
        or getattr(settings, "READY_WORKSPACE_POOL_TARGET", 0) <= 0
    ):
        return None
    observed_at = now or timezone.now()
    try:
        with transaction.atomic():
            return _assign_ready_workspace_once(tenant_ref, observed_at)
    except IntegrityError:
        # A concurrent registration may have won the unique tenant reference.
        # The failed savepoint is rolled back before this idempotent reread.
        return Workspace.objects.filter(tenant_ref=tenant_ref).first()


def _assign_ready_workspace_once(tenant_ref: str, now: datetime) -> Workspace | None:
    existing = (
        Workspace.objects.select_for_update().filter(tenant_ref=tenant_ref).first()
    )
    if existing is not None:
        return existing

    candidate_ids = list(
        ReadyWorkspaceBundle.objects.filter(
            state=ReadyWorkspaceBundleState.READY,
            phase_claim_owner__isnull=True,
            phase_claim_until__isnull=True,
        )
        .values_list("pk", flat=True)
        .order_by("ready_at", "id")[:MAX_ASSIGNMENT_CANDIDATES]
    )
    for candidate_id in candidate_ids:
        candidate = (
            ReadyWorkspaceBundle.objects.select_for_update(skip_locked=True)
            .filter(
                pk=candidate_id,
                state=ReadyWorkspaceBundleState.READY,
                phase_claim_owner__isnull=True,
                phase_claim_until__isnull=True,
            )
            .first()
        )
        if candidate is None:
            continue
        workspace = (
            Workspace.objects.select_for_update()
            .filter(pk=candidate.workspace_id)
            .first()
        )
        if workspace is None:
            _try_mark_candidate_evicting(candidate, now, "workspace_missing")
            continue
        if not _eligible(candidate, workspace, now):
            _try_mark_candidate_evicting(candidate, now, "stale_candidate")
            continue

        workspace.tenant_ref = tenant_ref
        workspace.save(update_fields=["tenant_ref", "updated_at"])
        candidate.state = ReadyWorkspaceBundleState.ASSIGNED
        candidate.assigned_at = now
        candidate.safe_error_code = None
        candidate.save(
            update_fields=["state", "assigned_at", "safe_error_code", "updated_at"]
        )
        return workspace
    return None


def _eligible(
    bundle: ReadyWorkspaceBundle,
    workspace: Workspace,
    now: datetime,
) -> bool:
    if bundle.state != ReadyWorkspaceBundleState.READY:
        return False
    if bundle.region != getattr(settings, "READY_WORKSPACE_POOL_REGION", ""):
        return False
    if bundle.release_fingerprint != getattr(
        settings, "READY_WORKSPACE_POOL_RELEASE_FINGERPRINT", ""
    ):
        return False
    if bundle.config_version != getattr(
        settings, "READY_WORKSPACE_POOL_CONFIG_VERSION", 1
    ):
        return False
    if not workspace.volume_ref or bundle.blank_volume_ref != workspace.volume_ref:
        return False
    if bundle.ready_at is None or bundle.expires_at is None or bundle.expires_at <= now:
        return False
    health_freshness = getattr(
        settings, "READY_WORKSPACE_POOL_HEALTH_FRESHNESS_SECONDS", 60
    )
    if bundle.last_health_at is None or bundle.last_health_at < now - timedelta(
        seconds=health_freshness
    ):
        return False
    if bundle.phase_claim_owner is not None or bundle.phase_claim_until is not None:
        return False
    if not workspace.tenant_ref.startswith(RESERVED_TENANT_PREFIX):
        return False
    if workspace.provisioning_phase != WorkspaceProvisioningPhase.IDLE:
        return False
    if workspace.runtime_operation_state != RuntimeOperationState.IDLE:
        return False
    if (
        workspace.provisioning_claim_token is not None
        or workspace.provisioning_claim_expires_at is not None
        or workspace.activation_claim_token is not None
        or workspace.activation_claim_expires_at is not None
    ):
        return False
    if workspace.release_target:
        return False
    if not is_runtime_ready(workspace, now=now):
        return False
    if (
        RuntimeCredential.objects.filter(
            workspace_id=workspace.id,
            machine_generation=workspace.machine_generation,
            revoked_at__isnull=True,
        ).count()
        != 1
    ):
        return False
    if RuntimeProfile.objects.filter(workspace_id=workspace.id).exists():
        return False
    return not Execution.objects.filter(workspace_id=workspace.id).exists()


def mark_ready_bundle_evicting(
    bundle_id: UUID | str,
    *,
    safe_error_code: str = "stale_candidate",
    now: datetime | None = None,
) -> bool:
    """Mark one unassigned bundle for maintenance cleanup."""

    if not safe_error_code or len(safe_error_code) > 64:
        raise RuntimeValidationError("pool bundle error code is invalid")
    observed_at = now or timezone.now()
    try:
        with transaction.atomic():
            bundle = (
                ReadyWorkspaceBundle.objects.select_for_update()
                .filter(
                    pk=bundle_id,
                    state=ReadyWorkspaceBundleState.READY,
                )
                .first()
            )
            if bundle is None:
                return False
            return _try_mark_candidate_evicting(bundle, observed_at, safe_error_code)
    except (IntegrityError, RuntimeConflictError):
        return False


def _try_mark_candidate_evicting(
    bundle: ReadyWorkspaceBundle,
    now: datetime,
    safe_error_code: str,
) -> bool:
    # Keep a marker failure inside a savepoint.  Assignment can then continue
    # through the normal cold-registration path without a broken transaction.
    try:
        with transaction.atomic():
            _mark_candidate_evicting(bundle, now, safe_error_code)
    except (IntegrityError, RuntimeConflictError, RuntimeValidationError):
        return False
    return True


def _mark_candidate_evicting(
    bundle: ReadyWorkspaceBundle,
    now: datetime,
    safe_error_code: str,
) -> None:
    bundle.state = ReadyWorkspaceBundleState.EVICTING
    bundle.next_attempt_at = now
    bundle.safe_error_code = safe_error_code
    bundle.save(
        update_fields=["state", "next_attempt_at", "safe_error_code", "updated_at"]
    )


__all__ = [
    "MAX_ASSIGNMENT_CANDIDATES",
    "RESERVED_TENANT_PREFIX",
    "assign_ready_workspace",
    "is_canonical_cloud_workspace_ref",
    "mark_ready_bundle_evicting",
]
