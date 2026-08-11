"""Self-profile read/update use cases."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime

from django.db import transaction

from auths.exceptions import ValidationError
from auths.models import Actor, AvatarStatus, UserProfile
from auths.services.sessions import AuthenticatedSession
from workspaces.capabilities import capabilities_for_role
from workspaces.models import Membership, MembershipStatus, WorkspaceKind


@dataclass(frozen=True)
class ProfileResult:
    display_name: str
    avatar_url: str | None


@dataclass(frozen=True)
class SessionResult:
    id: str
    expires_at: datetime


@dataclass(frozen=True)
class WorkspaceResult:
    id: str
    name: str
    role: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class MeResult:
    actor_id: str
    profile: ProfileResult
    session: SessionResult
    workspace: WorkspaceResult


def get_self_profile(session: AuthenticatedSession) -> MeResult:
    """Return a joined singleton projection without provider/runtime details."""

    actor = Actor.objects.get(pk=session.actor.pk)
    profile = UserProfile.objects.select_related("current_avatar").get(actor=actor)
    membership = (
        Membership.objects.select_related("workspace")
        .filter(
            actor=actor,
            status=MembershipStatus.ACTIVE,
            workspace__kind=WorkspaceKind.PERSONAL,
        )
        .first()
    )
    if membership is None:
        raise ValidationError("personal Workspace is unavailable")
    avatar_url = None
    if profile.current_avatar and profile.current_avatar.status == AvatarStatus.READY:
        from auths.services.avatars import signed_avatar_read

        try:
            avatar_url, _ = signed_avatar_read(actor=actor)
        except Exception:  # noqa: BLE001 - signed-read outages do not expose keys or fail /me
            # A temporary storage outage must not leak an object key or fail the
            # rest of the self projection.
            avatar_url = None
    expires_at = datetime.fromtimestamp(int(session.claims["exp"]), tz=UTC)
    return MeResult(
        actor_id=actor.public_id,
        profile=ProfileResult(profile.display_name, avatar_url),
        session=SessionResult(session.family.public_id, expires_at),
        workspace=WorkspaceResult(
            membership.workspace.public_id,
            membership.workspace.name,
            membership.role,
            capabilities_for_role(membership.role),
        ),
    )


def _validate_display_name(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("display name is invalid")
    value = " ".join(value.strip().split())
    if not 1 <= len(value) <= 80:
        raise ValidationError("display name is invalid")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValidationError("display name is invalid")
    return value


@transaction.atomic
def update_display_name(actor: Actor, display_name: str) -> UserProfile:
    value = _validate_display_name(display_name)
    profile, _ = UserProfile.objects.select_for_update().get_or_create(
        actor=actor, defaults={"display_name": value}
    )
    if profile.display_name != value:
        profile.display_name = value
        profile.save(update_fields=("display_name", "updated_at"))
    return profile
