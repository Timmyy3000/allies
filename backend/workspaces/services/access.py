"""Live Workspace membership and capability authorization."""

from __future__ import annotations

from auths.exceptions import WorkspaceAccessDenied
from auths.models import User

from ..capabilities import Capability, capabilities_for_role
from ..models import Membership, MembershipStatus
from .bootstrap import WorkspaceContext


def require_workspace_capability(
    *, user: User, workspace_id: str, capability: Capability | str
) -> WorkspaceContext:
    try:
        requested = Capability(str(capability))
    except ValueError as exc:
        raise WorkspaceAccessDenied("workspace denied") from exc
    membership = (
        Membership.objects.select_related("workspace", "user")
        .filter(
            user=user,
            workspace__public_id=workspace_id,
            workspace__is_active=True,
            status=MembershipStatus.ACTIVE,
        )
        .first()
    )
    if membership is None or requested.value not in capabilities_for_role(
        membership.role
    ):
        raise WorkspaceAccessDenied("workspace denied")
    return WorkspaceContext(workspace=membership.workspace, membership=membership)
