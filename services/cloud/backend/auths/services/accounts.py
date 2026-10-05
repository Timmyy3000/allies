"""Provider-subject account resolution and first-sign-in bootstrap."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from auths.config import beta_invites_required
from auths.exceptions import InviteRequired, InviteValidation
from auths.models import ExternalIdentity, User, UserProfile
from auths.providers.base import VerifiedIdentity
from workspaces.services.bootstrap import WorkspaceContext, ensure_personal_workspace

from .invites import consume_invite, lock_invite_for_signup, normalize_invite_email


@dataclass(frozen=True)
class UserBootstrap:
    user: User
    identity: ExternalIdentity
    profile: UserProfile
    workspace: WorkspaceContext
    created: bool


def _safe_display_name(value: str) -> str:
    value = " ".join((value or "").split())
    return value[:80]


def _verified_signup_email(identity: VerifiedIdentity) -> str:
    if (
        identity.provider != "google"
        or not identity.email_verified
        or identity.email_verification_source != "google"
        or not identity.email
    ):
        raise InviteRequired("a verified Google email and beta invite are required")
    try:
        return normalize_invite_email(identity.email)
    except InviteValidation as exc:
        raise InviteRequired(
            "a verified Google email and beta invite are required"
        ) from exc


def resolve_or_create_user(identity: VerifiedIdentity) -> UserBootstrap:
    """Resolve only by immutable ``(provider, subject)``.

    Equal email snapshots are intentionally ignored.  The entire first-sign-in
    bootstrap is one transaction; user row locking makes repeat/concurrent
    callbacks converge on one profile, Workspace and owner membership.
    """

    with transaction.atomic():
        existing = (
            ExternalIdentity.objects.select_related("user", "user__profile")
            .filter(provider=identity.provider, subject=identity.subject)
            .first()
        )
        created = False
        invite = None
        if existing is None:
            if beta_invites_required():
                invite = lock_invite_for_signup(email=_verified_signup_email(identity))
                # The grant lock serializes same-grant callbacks. Recheck the
                # immutable provider identity after waiting on it.
                existing = (
                    ExternalIdentity.objects.select_related("user", "user__profile")
                    .filter(provider=identity.provider, subject=identity.subject)
                    .first()
                )
                if existing is None and (
                    invite.revoked_at is not None or invite.consumed_at is not None
                ):
                    raise InviteRequired("a beta invite is required")
                if existing is not None:
                    invite = None
            if existing is None:
                try:
                    with transaction.atomic():
                        user = User.objects.create_user(is_active=True)
                        UserProfile.objects.create(
                            user=user,
                            display_name=_safe_display_name(identity.display_name),
                        )
                        existing = ExternalIdentity.objects.create(
                            user=user,
                            provider=identity.provider,
                            subject=identity.subject,
                            issuer=identity.issuer[:255],
                            email_snapshot=identity.email[:254],
                            email_verified=identity.email_verified,
                            email_verified_at=timezone.now()
                            if identity.email_verified
                            else None,
                            email_verification_source=(
                                identity.email_verification_source[:32]
                                if identity.email_verified
                                else ""
                            ),
                            display_name_snapshot=_safe_display_name(
                                identity.display_name
                            ),
                        )
                        created = True
                except IntegrityError:
                    # A concurrent callback may have won the provider/subject
                    # uniqueness race. Preserve unrelated constraint failures.
                    existing = (
                        ExternalIdentity.objects.select_related("user")
                        .filter(provider=identity.provider, subject=identity.subject)
                        .first()
                    )
                    if existing is None:
                        raise
                    user = existing.user
                else:
                    user = existing.user
            else:
                user = existing.user
        else:
            user = existing.user

        user = User.objects.select_for_update().get(pk=user.pk)
        if not user.is_active:
            raise ValueError("user is inactive")
        profile = UserProfile.objects.filter(user=user).first()
        if profile is None:
            profile = UserProfile.objects.create(user=user, display_name="")
        # Provider snapshots seed an empty profile only.  A user-owned name is
        # never overwritten on repeat sign-in.
        if not profile.display_name and identity.display_name:
            profile.display_name = _safe_display_name(identity.display_name)
            profile.save(update_fields=("display_name", "updated_at"))
        if identity.email_verified and identity.email:
            # A fresh allowlisted assertion can refresh durable verification
            # provenance without making email equality an account key.
            existing.email_snapshot = identity.email[:254]
            existing.email_verified = True
            existing.email_verified_at = timezone.now()
            existing.email_verification_source = identity.email_verification_source[:32]
            existing.save(
                update_fields=(
                    "email_snapshot",
                    "email_verified",
                    "email_verified_at",
                    "email_verification_source",
                    "updated_at",
                )
            )
        workspace = ensure_personal_workspace(user)
        if invite is not None and created:
            consume_invite(invite)
        return UserBootstrap(user, existing, profile, workspace, created)
