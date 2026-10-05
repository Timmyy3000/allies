"""Owner-scoped routine cards and result projections for the main chat."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from activities.models import RoutineResultProjection
from auths.models import User
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability

from ..models import Routine, RoutineApprovalProjection, RoutineRunSnapshot


def _creation_item(routine: Routine) -> dict[str, Any]:
    return {
        "id": routine.id,
        "kind": "created",
        "routine_id": routine.id,
        "conversation_id": routine.main_conversation_id,
        "source_message_id": routine.source_message_id,
        "title_snapshot": routine.title,
        "routine_revision": routine.revision,
        "schedule_generation": routine.schedule_generation,
        "status": "created",
        "schedule": routine.schedule,
        "occurred_at": routine.created_at,
        "occurrence_id": None,
        "run_id": None,
        "execution_id": None,
        "attempt_id": None,
        "generation": None,
        "result_id": None,
        "result_insertion": None,
        "text": None,
        "references": [],
        "delayed": None,
    }


def _run_item(
    run: RoutineRunSnapshot,
    approval: RoutineApprovalProjection | None = None,
) -> dict[str, Any]:
    item = {
        "id": run.id,
        "kind": "running",
        "routine_id": run.routine_id,
        "conversation_id": run.main_conversation_id,
        "title_snapshot": run.title_snapshot,
        "routine_revision": run.routine_revision,
        "schedule_generation": run.schedule_generation,
        "status": run.outcome,
        "schedule": run.schedule_snapshot,
        "occurred_at": run.created_at,
        "occurrence_id": run.occurrence_id,
        "run_id": run.id,
        "execution_id": None,
        "attempt_id": None,
        "generation": None,
        "result_id": None,
        "result_insertion": None,
        "text": None,
        "references": [],
        "delayed": run.delayed,
    }
    if approval is not None:
        item.update(
            {
                "approval_id": approval.id,
                "approval_request_id": approval.approval_request_id,
                "approval_status": approval.status,
                "approval_decision": approval.decision or None,
                "action_digest": approval.action_digest,
                "action_attempt_id": approval.action_attempt_id,
                "approval_expires_at": approval.expires_at,
            }
        )
    return item


def _result_item(result: RoutineResultProjection) -> dict[str, Any]:
    return {
        "id": result.id,
        "kind": "result",
        "routine_id": result.routine_id,
        "conversation_id": result.main_conversation_id,
        "title_snapshot": result.title_snapshot,
        "routine_revision": result.routine_revision,
        "schedule_generation": result.run.schedule_generation,
        "status": result.outcome,
        "schedule": result.run.schedule_snapshot,
        "occurred_at": result.created_at,
        "occurrence_id": result.occurrence_id,
        "run_id": result.run_id,
        "execution_id": result.execution_id,
        "attempt_id": result.attempt_id,
        "generation": result.generation,
        "result_id": result.id,
        "result_insertion": result.insertion_state,
        "text": result.text,
        "references": result.references,
        "delayed": result.delayed,
        "approval_id": None,
        "approval_request_id": None,
        "approval_status": None,
        "approval_decision": None,
        "action_digest": None,
        "action_attempt_id": None,
        "approval_expires_at": None,
    }


def routine_chat_items(
    *,
    user: User,
    workspace_id: UUID | str,
    conversation_id: UUID | str,
    limit: int = 100,
) -> tuple[dict[str, Any], ...]:
    """Return routine identity, running, and result cards for one chat."""

    context = require_workspace_capability(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.PROFILE_READ,
    )
    bound = max(1, min(int(limit), 100))
    routines = Routine.objects.filter(
        workspace_id=context.workspace.id,
        owner_id=user.id,
        main_conversation_id=conversation_id,
    ).order_by("created_at", "id")
    results = RoutineResultProjection.objects.filter(
        workspace_id=context.workspace.id,
        owner_id=user.id,
        main_conversation_id=conversation_id,
    ).select_related("run")
    results_by_run = {result.run_id: result for result in results}
    approvals = RoutineApprovalProjection.objects.filter(
        workspace_id=context.workspace.id,
        owner_id=user.id,
        run__main_conversation_id=conversation_id,
    ).order_by("created_at", "id")
    approvals_by_run = {approval.run_id: approval for approval in approvals}
    items: list[dict[str, Any]] = []
    for routine in routines:
        items.append(_creation_item(routine))
        runs = RoutineRunSnapshot.objects.filter(
            routine=routine,
            main_conversation_id=conversation_id,
        ).order_by("created_at", "id")
        for run in runs:
            result = results_by_run.get(run.id)
            items.append(
                _result_item(result)
                if result is not None
                else _run_item(run, approvals_by_run.get(run.id))
            )
    items.sort(key=lambda item: (item["occurred_at"], str(item["id"])))
    return tuple(items[-bound:])


__all__ = ["routine_chat_items"]
