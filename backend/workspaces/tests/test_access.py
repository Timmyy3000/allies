import pytest

from auths.exceptions import WorkspaceAccessDenied
from auths.providers.base import VerifiedIdentity
from auths.services.accounts import resolve_or_create_actor
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability


@pytest.mark.django_db
def test_workspace_capability_is_live_and_cross_actor_denied():
    first = resolve_or_create_actor(
        VerifiedIdentity(provider="fake", subject="owner-a")
    )
    second = resolve_or_create_actor(
        VerifiedIdentity(provider="fake", subject="owner-b")
    )
    context = require_workspace_capability(
        actor=first.actor,
        workspace_id=first.workspace.workspace.public_id,
        capability=Capability.WORKSPACE_READ,
    )
    assert context.membership.actor_id == first.actor.id
    with pytest.raises(WorkspaceAccessDenied):
        require_workspace_capability(
            actor=second.actor,
            workspace_id=first.workspace.workspace.public_id,
            capability=Capability.WORKSPACE_READ,
        )
