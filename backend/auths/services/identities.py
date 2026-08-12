"""Authenticated external-identity linking."""

from __future__ import annotations

from django.db import IntegrityError, transaction

from auths.exceptions import IdentityConflict
from auths.models import ExternalIdentity, User
from auths.providers.base import VerifiedIdentity


@transaction.atomic
def link_identity(*, user: User, identity: VerifiedIdentity) -> ExternalIdentity:
    current = (
        ExternalIdentity.objects.select_for_update()
        .filter(provider=identity.provider, subject=identity.subject)
        .first()
    )
    if current is not None:
        if current.user_id != user.pk:
            raise IdentityConflict("identity already linked")
        return current
    try:
        # The unique provider/subject constraint can race.  Catch its failure
        # only after this savepoint has rolled back so the outer transaction is
        # usable for reading the winning row on PostgreSQL.
        with transaction.atomic():
            return ExternalIdentity.objects.create(
                user=user,
                provider=identity.provider,
                subject=identity.subject,
                issuer=identity.issuer[:255],
                email_snapshot=identity.email[:254],
                display_name_snapshot=identity.display_name[:80],
            )
    except IntegrityError as exc:
        winner = (
            ExternalIdentity.objects.select_for_update()
            .filter(provider=identity.provider, subject=identity.subject)
            .first()
        )
        if winner is None:
            # This was not the expected identity uniqueness collision.
            raise
        if winner.user_id == user.pk:
            return winner
        raise IdentityConflict("identity already linked") from exc
