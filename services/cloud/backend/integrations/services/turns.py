"""Resolve the Ally behind a relayed Foundry tool call and re-check the turn."""

from dataclasses import dataclass
from uuid import UUID

from allies.models import Ally
from chat.models import DispatchOutbox, Message
from routines.models import RoutineDispatchOutbox, RoutineState
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability


@dataclass(frozen=True, slots=True)
class ToolTurn:
    ally: Ally
    message: Message | None = None


def routine_action_unavailable() -> tuple[int, dict]:
    return 403, {
        "error": "routine_action_unavailable",
        "instruction": "This action did not run. Routine runs cannot use it yet. Tell the user it was not done; do not claim success.",
    }


def resolve_tool_turn(
    *,
    message_id: UUID | None = None,
    run_id: UUID | None = None,
    binding_id: UUID,
    command_fingerprint: str,
) -> ToolTurn:
    if run_id is not None:
        return _resolve_routine_turn(run_id, binding_id, command_fingerprint)
    message = Message.objects.select_related(
        "conversation__ally__workspace__owner", "conversation__ally__binding"
    ).get(pk=message_id, sender="user", origin="send", deleted_at__isnull=True)
    ally = message.conversation.ally
    workspace = ally.workspace
    if ally.binding.id != binding_id or not workspace.is_active:
        raise PermissionError("tool binding unavailable")
    require_workspace_capability(
        user=workspace.owner,
        workspace_id=workspace.id,
        capability=Capability.WORKSPACE_WRITE,
    )
    outbox = DispatchOutbox.objects.get(message=message)
    if not command_fingerprint or outbox.command_fingerprint != command_fingerprint:
        raise PermissionError("tool dispatch unavailable")
    return ToolTurn(ally=ally, message=message)


def _resolve_routine_turn(
    run_id: UUID, binding_id: UUID, command_fingerprint: str
) -> ToolTurn:
    outbox = RoutineDispatchOutbox.objects.select_related(
        "routine__ally", "routine__workspace", "routine__owner"
    ).get(run_id=run_id)
    routine = outbox.routine
    workspace = routine.workspace
    if (
        routine.binding_id != binding_id
        or routine.state in {RoutineState.PAUSED, RoutineState.DELETED}
        or not workspace.is_active
    ):
        raise PermissionError("tool binding unavailable")
    require_workspace_capability(
        user=routine.owner,
        workspace_id=workspace.id,
        capability=Capability.WORKSPACE_WRITE,
    )
    if not command_fingerprint or outbox.command_fingerprint != command_fingerprint:
        raise PermissionError("tool dispatch unavailable")
    return ToolTurn(ally=routine.ally)
