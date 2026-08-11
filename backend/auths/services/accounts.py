"""Provider-subject account resolution and first-sign-in bootstrap."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction

from auths.models import Actor, ExternalIdentity, UserProfile
from auths.providers.base import VerifiedIdentity
from common.identifiers import new_public_id
from workspaces.services.bootstrap import WorkspaceContext, ensure_personal_workspace


@dataclass(frozen=True)
class ActorBootstrap:
    actor: Actor
    identity: ExternalIdentity
    profile: UserProfile
    workspace: WorkspaceContext
    created: bool


def _safe_display_name(value: str) -> str:
    value = " ".join((value or "").split())
    return value[:80]


def resolve_or_create_actor(identity: VerifiedIdentity) -> ActorBootstrap:
    """Resolve only by immutable ``(provider, subject)``.

    Equal email snapshots are intentionally ignored.  The entire first-sign-in
    bootstrap is one transaction; actor row locking makes repeat/concurrent
    callbacks converge on one profile, Workspace and owner membership.
    """

    with transaction.atomic():
        existing = (
            ExternalIdentity.objects.select_related("actor", "actor__profile")
            .filter(provider=identity.provider, subject=identity.subject)
            .first()
        )
        created = False
        if existing is None:
            try:
                with transaction.atomic():
                    actor = Actor.objects.create_user(
                        public_id=new_public_id("act"), is_active=True
                    )
                    UserProfile.objects.create(
                        actor=actor,
                        display_name=_safe_display_name(identity.display_name),
                    )
                    existing = ExternalIdentity.objects.create(
                        actor=actor,
                        provider=identity.provider,
                        subject=identity.subject,
                        issuer=identity.issuer[:255],
                        email_snapshot=identity.email[:254],
                        display_name_snapshot=_safe_display_name(identity.display_name),
                    )
                    created = True
            except IntegrityError:
                # Another transaction won the unique provider/subject race.
                existing = ExternalIdentity.objects.select_related("actor").get(
                    provider=identity.provider, subject=identity.subject
                )
                actor = existing.actor
            else:
                actor = existing.actor
        else:
            actor = existing.actor

        actor = Actor.objects.select_for_update().get(pk=actor.pk)
        if not actor.is_active:
            raise ValueError("actor is inactive")
        profile = UserProfile.objects.filter(actor=actor).first()
        if profile is None:
            profile = UserProfile.objects.create(actor=actor, display_name="")
        # Provider snapshots seed an empty profile only.  A user-owned name is
        # never overwritten on repeat sign-in.
        if not profile.display_name and identity.display_name:
            profile.display_name = _safe_display_name(identity.display_name)
            profile.save(update_fields=("display_name", "updated_at"))
        workspace = ensure_personal_workspace(actor)
        return ActorBootstrap(actor, existing, profile, workspace, created)
