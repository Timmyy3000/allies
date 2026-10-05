import pytest

from auths.exceptions import WorkspaceAccessDenied
from auths.providers.base import VerifiedIdentity
from auths.services.accounts import resolve_or_create_user
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability


@pytest.mark.django_db
def test_workspace_capability_is_live_and_cross_user_denied():
    first = resolve_or_create_user(VerifiedIdentity(provider="fake", subject="owner-a"))
    second = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="owner-b")
    )
    context = require_workspace_capability(
        user=first.user,
        workspace_id=first.workspace.workspace.id,
        capability=Capability.WORKSPACE_READ,
    )
    assert context.membership.user_id == first.user.id
    with pytest.raises(WorkspaceAccessDenied):
        require_workspace_capability(
            user=second.user,
            workspace_id=first.workspace.workspace.id,
            capability=Capability.WORKSPACE_READ,
        )
