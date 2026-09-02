"""Self-profile read/update use cases."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime

from auths.exceptions import ValidationError
from auths.models import AvatarStatus, User, UserProfile
from auths.services.sessions import AuthenticatedSession
from django.db import transaction
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
    user_id: str
    profile: ProfileResult
    session: SessionResult
    workspace: WorkspaceResult


def get_self_profile(session: AuthenticatedSession) -> MeResult:
    """Return a joined singleton projection without provider/runtime details."""

    user = User.objects.get(pk=session.user.pk)
    profile = UserProfile.objects.select_related("current_avatar").get(user=user)
    membership = (
        Membership.objects.select_related("workspace")
        .filter(
            user=user,
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
            _asset, avatar_url, _expires = signed_avatar_read(user=user)
        except Exception:  # noqa: BLE001 - signed-read outages do not expose keys or fail /me
            # A temporary storage outage must not leak an object key or fail the
            # rest of the self projection.
            avatar_url = None
    expires_at = datetime.fromtimestamp(int(session.claims["exp"]), tz=UTC)
    return MeResult(
        user_id=str(user.id),
        profile=ProfileResult(profile.display_name, avatar_url),
        session=SessionResult(str(session.family.id), expires_at),
        workspace=WorkspaceResult(
            str(membership.workspace.id),
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
def update_display_name(user: User, display_name: str) -> UserProfile:
    value = _validate_display_name(display_name)
    profile, _ = UserProfile.objects.select_for_update().get_or_create(
        user=user, defaults={"display_name": value}
    )
    if profile.display_name != value:
        profile.display_name = value
        profile.save(update_fields=("display_name", "updated_at"))
    return profile
