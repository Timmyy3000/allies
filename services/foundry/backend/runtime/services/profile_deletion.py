from __future__ import annotations

from datetime import timedelta
from itertools import batched
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from django.db import transaction
from django.utils import timezone

from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeFencedError,
    RuntimeIdempotencyConflictError,
)
from runtime.models import (
    DeletedProfile,
    Lease,
    LeaseState,
    PublicationIntent,
    RoutineApprovalAction,
    RoutineCommandReceipt,
    RoutineExecution,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
)
from runtime.profile_keys import derive_hermes_profile_key

from .activity import advance_workspace_activity
from .retry import run_with_sqlite_lock_retry
from .runtime_intents import request_execution_wake_locked
from .validation import digest_payload
from .workspaces import register_workspace

_PROFILE_NAMESPACE = uuid5(NAMESPACE_URL, "allies-foundry-profile-v1")
_RECEIPT_NAMESPACE = uuid5(NAMESPACE_URL, "allies-foundry-deleted-profile-v1")


def coordinate_profile_deletion(
    *,
    workspace_id: UUID,
    ally_id: UUID,
    binding_id: UUID,
    operation_id: UUID,
    expected_attempt_id: UUID | None = None,
) -> dict[str, object]:
    workspace = register_workspace(str(workspace_id))
    profile_id = uuid5(_PROFILE_NAMESPACE, str(binding_id))

    @transaction.atomic
    def coordinate_once() -> dict[str, object]:
        locked_workspace = Workspace.objects.select_for_update().get(pk=workspace.id)
        marker = DeletedProfile.objects.filter(profile_id=profile_id).first()
        if marker is not None:
            if marker.workspace_id != workspace.id:
                raise RuntimeConflictError("profile identity conflicts")
            return _complete_response(
                binding_id, operation_id, workspace.id, profile_id
            )
        profile = (
            RuntimeProfile.objects.select_for_update().filter(pk=profile_id).first()
        )
        if profile is not None and (
            profile.workspace_id != workspace.id or profile.ally_ref != str(ally_id)
        ):
            raise RuntimeConflictError("profile identity conflicts")
        if profile is None:
            if expected_attempt_id is not None:
                raise RuntimeFencedError("deletion attempt is unavailable")
            profile = RuntimeProfile.objects.create(
                id=profile_id,
                workspace=locked_workspace,
                ally_ref=str(ally_id),
                hermes_profile_key=derive_hermes_profile_key(profile_id),
            )
        if profile.cleanup_operation_id and (
            not profile.cleanup_requires_quiescence
            or profile.cleanup_operation_id != operation_id
        ):
            raise RuntimeIdempotencyConflictError("deletion operation conflicts")
        now = timezone.now()
        if profile.cleanup_requires_quiescence:
            if profile.lifecycle_state == RuntimeProfileLifecycleState.DEPROVISIONED:
                _purge_profile(locked_workspace, profile)
                return _complete_response(
                    binding_id, operation_id, workspace.id, profile_id
                )
            if profile.cleanup_expires_at is None or profile.cleanup_expires_at <= now:
                profile.lifecycle_state = RuntimeProfileLifecycleState.REPAIR_REQUIRED
                profile.cleanup_result_code = "repair_required"
                profile.save(
                    update_fields=[
                        "lifecycle_state",
                        "cleanup_result_code",
                        "updated_at",
                    ]
                )
            if expected_attempt_id is not None:
                if profile.cleanup_previous_attempt_id == expected_attempt_id:
                    return _pending_response(profile, binding_id, operation_id)
                if (
                    profile.cleanup_attempt_id != expected_attempt_id
                    or profile.lifecycle_state
                    != RuntimeProfileLifecycleState.REPAIR_REQUIRED
                ):
                    raise RuntimeFencedError(
                        "deletion resume belongs to a stale attempt"
                    )
            else:
                return _pending_response(profile, binding_id, operation_id)
        elif expected_attempt_id is not None:
            raise RuntimeFencedError("deletion attempt is unavailable")
        profile.cleanup_previous_attempt_id = profile.cleanup_attempt_id
        profile.cleanup_attempt_id = uuid4()
        profile.cleanup_operation_id = operation_id
        profile.cleanup_requires_quiescence = True
        profile.lifecycle_epoch += 1
        profile.lifecycle_state = RuntimeProfileLifecycleState.CLEANUP_PENDING
        profile.cleanup_expires_at = now + timedelta(hours=24)
        profile.cleanup_context_digest = digest_payload(
            {
                "workspace_id": str(workspace_id),
                "ally_id": str(ally_id),
                "binding_id": str(binding_id),
                "profile_id": str(profile_id),
            }
        )
        profile.cleanup_request_digest = digest_payload(
            {
                "version": 1,
                "context_digest": profile.cleanup_context_digest,
                "operation_id": str(operation_id),
                "attempt_id": str(profile.cleanup_attempt_id),
                "lifecycle_epoch": profile.lifecycle_epoch,
                "expires_at": profile.cleanup_expires_at.isoformat(),
            }
        )
        profile.cleanup_receipt_id = None
        profile.cleanup_completed_at = None
        profile.cleanup_result_code = "cleanup_pending"
        profile.cleanup_retry_after = now
        profile.save()
        Lease.objects.filter(profile=profile, state=LeaseState.ACTIVE).update(
            state=LeaseState.STOPPING
        )
        advance_workspace_activity(locked_workspace)
        request_execution_wake_locked(locked_workspace, now=now)
        return _pending_response(profile, binding_id, operation_id)

    return run_with_sqlite_lock_retry(coordinate_once)


def _pending_response(
    profile: RuntimeProfile, binding_id: UUID, operation_id: UUID
) -> dict[str, object]:
    repair = profile.lifecycle_state == RuntimeProfileLifecycleState.REPAIR_REQUIRED
    return {
        "version": 1,
        "binding_id": str(binding_id),
        "operation_id": str(operation_id),
        "state": "repair_required" if repair else "pending",
        "attempt_id": str(profile.cleanup_attempt_id),
        "receipt_id": None,
        "safe_error_code": "runtime_cleanup_unresolved" if repair else "",
    }


def _complete_response(
    binding_id: UUID,
    operation_id: UUID,
    workspace_id: UUID,
    profile_id: UUID,
) -> dict[str, object]:
    return {
        "version": 1,
        "binding_id": str(binding_id),
        "operation_id": str(operation_id),
        "state": "complete",
        "attempt_id": None,
        "receipt_id": str(uuid5(_RECEIPT_NAMESPACE, f"{workspace_id}:{profile_id}")),
        "safe_error_code": "",
    }


def _purge_profile(workspace: Workspace, profile: RuntimeProfile) -> None:
    if not profile.cleanup_requires_quiescence or not profile.cleanup_receipt_id:
        raise RuntimeConflictError("verified cleanup receipt is required")
    if Lease.objects.filter(
        profile=profile, state__in=[LeaseState.ACTIVE, LeaseState.STOPPING]
    ).exists():
        raise RuntimeConflictError("profile still owns unresolved work")
    RoutineCommandReceipt.objects.filter(
        workspace=workspace, response__scope__ally_id=profile.ally_ref
    ).delete()
    routine_ids = RoutineExecution.objects.filter(profile=profile).values_list(
        "id", flat=True
    )
    for batch in batched(routine_ids.iterator(chunk_size=100), 100):
        RoutineCommandReceipt.objects.filter(
            workspace=workspace,
            response__routine_execution_id__in=[str(value) for value in batch],
        ).delete()
    RoutineApprovalAction.objects.filter(routine_execution__profile=profile).delete()
    RoutineExecution.objects.filter(profile=profile).delete()
    PublicationIntent.objects.filter(profile=profile).delete()
    DeletedProfile.objects.create(workspace=workspace, profile_id=profile.id)
    profile.delete()
    advance_workspace_activity(workspace)
