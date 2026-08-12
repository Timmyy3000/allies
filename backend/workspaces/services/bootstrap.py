"""Idempotent personal Workspace bootstrap."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction

from auths.exceptions import WorkspaceInvariantError
from auths.models import User, UserProfile
from common.identifiers import new_public_id

from ..models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Workspace,
    WorkspaceKind,
)


@dataclass(frozen=True)
class WorkspaceContext:
    workspace: Workspace
    membership: Membership


def _workspace_name(user: User) -> str:
    profile = UserProfile.objects.filter(user=user).only("display_name").first()
    display_name = profile.display_name.strip() if profile else ""
    if not display_name:
        display_name = "Personal"
    return f"{display_name[:80]}'s Workspace"


def ensure_personal_workspace(user: User) -> WorkspaceContext:
    """Create exactly one personal Workspace and active owner membership.

    The conditional unique owner constraint is authoritative.  A concurrent
    winner is reread after an integrity collision, making sign-in completion
    safe to retry without duplicate durable records.
    """

    with transaction.atomic():
        locked_user = User.objects.select_for_update().get(pk=user.pk)
        workspace = (
            Workspace.objects.filter(owner=locked_user, kind=WorkspaceKind.PERSONAL)
            .order_by("pk")
            .first()
        )
        if workspace is None:
            try:
                with transaction.atomic():
                    workspace = Workspace.objects.create(
                        public_id=new_public_id("wsp"),
                        kind=WorkspaceKind.PERSONAL,
                        owner=locked_user,
                        name=_workspace_name(locked_user),
                    )
            except IntegrityError:
                workspace = Workspace.objects.get(
                    owner=locked_user, kind=WorkspaceKind.PERSONAL
                )
        membership, created = Membership.objects.get_or_create(
            workspace=workspace,
            user=locked_user,
            defaults={"role": MembershipRole.OWNER, "status": MembershipStatus.ACTIVE},
        )
        if (
            membership.role != MembershipRole.OWNER
            or membership.status != MembershipStatus.ACTIVE
        ):
            raise WorkspaceInvariantError("personal owner membership is not active")
        del created
        return WorkspaceContext(workspace=workspace, membership=membership)
