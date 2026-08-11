"""Authenticated external-identity linking."""

from __future__ import annotations

from django.db import IntegrityError, transaction

from auths.exceptions import IdentityConflict
from auths.models import Actor, ExternalIdentity
from auths.providers.base import VerifiedIdentity


@transaction.atomic
def link_identity(*, actor: Actor, identity: VerifiedIdentity) -> ExternalIdentity:
    current = (
        ExternalIdentity.objects.select_for_update()
        .filter(provider=identity.provider, subject=identity.subject)
        .first()
    )
    if current is not None:
        if current.actor_id != actor.pk:
            raise IdentityConflict("identity already linked")
        return current
    try:
        return ExternalIdentity.objects.create(
            actor=actor,
            provider=identity.provider,
            subject=identity.subject,
            issuer=identity.issuer[:255],
            email_snapshot=identity.email[:254],
            display_name_snapshot=identity.display_name[:80],
        )
    except IntegrityError as exc:
        winner = ExternalIdentity.objects.filter(
            provider=identity.provider, subject=identity.subject
        ).first()
        if winner is not None and winner.actor_id == actor.pk:
            return winner
        raise IdentityConflict("identity already linked") from exc
