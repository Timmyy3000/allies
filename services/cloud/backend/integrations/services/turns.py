"""Resolve the Ally behind a relayed Foundry tool call and re-check the turn."""

from uuid import UUID

from chat.models import DispatchOutbox, Message
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability


def resolve_tool_turn(
    message_id: UUID, binding_id: UUID, command_fingerprint: str
) -> Message:
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
    return message
