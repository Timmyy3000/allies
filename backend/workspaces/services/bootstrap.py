"""Idempotent personal Workspace bootstrap."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction

from auths.exceptions import WorkspaceInvariantError
from auths.models import Actor, UserProfile
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


def _workspace_name(actor: Actor) -> str:
    profile = UserProfile.objects.filter(actor=actor).only("display_name").first()
    display_name = profile.display_name.strip() if profile else ""
    if not display_name:
        display_name = "Personal"
    return f"{display_name[:80]}'s Workspace"


def ensure_personal_workspace(actor: Actor) -> WorkspaceContext:
    """Create exactly one personal Workspace and active owner membership.

    The conditional unique owner constraint is authoritative.  A concurrent
    winner is reread after an integrity collision, making sign-in completion
    safe to retry without duplicate durable records.
    """

    with transaction.atomic():
        locked_actor = Actor.objects.select_for_update().get(pk=actor.pk)
        workspace = (
            Workspace.objects.filter(owner=locked_actor, kind=WorkspaceKind.PERSONAL)
            .order_by("pk")
            .first()
        )
        if workspace is None:
            try:
                with transaction.atomic():
                    workspace = Workspace.objects.create(
                        public_id=new_public_id("wsp"),
                        kind=WorkspaceKind.PERSONAL,
                        owner=locked_actor,
                        name=_workspace_name(locked_actor),
                    )
            except IntegrityError:
                workspace = Workspace.objects.get(
                    owner=locked_actor, kind=WorkspaceKind.PERSONAL
                )
        membership, created = Membership.objects.get_or_create(
            workspace=workspace,
            actor=locked_actor,
            defaults={"role": MembershipRole.OWNER, "status": MembershipStatus.ACTIVE},
        )
        if (
            membership.role != MembershipRole.OWNER
            or membership.status != MembershipStatus.ACTIVE
        ):
            raise WorkspaceInvariantError("personal owner membership is not active")
        del created
        return WorkspaceContext(workspace=workspace, membership=membership)
