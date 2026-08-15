"""Internal-only, authenticated and verified waitlist claim seam."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from auths.models import ExternalIdentity, User

from ..exceptions import ClaimRejected
from ..models import DraftLifecycle, WaitlistDraft
from .email import emails_match

ALLOWED_VERIFICATION_SOURCES = frozenset({"google"})


def claim_waitlist_draft(
    *,
    user: User | None,
    draft: WaitlistDraft | str,
    confirmed: bool = False,
) -> WaitlistDraft:
    if (
        user is None
        or not getattr(user, "is_authenticated", False)
        or not user.is_active
    ):
        raise ClaimRejected("claim is not authorized")
    if not confirmed:
        raise ClaimRejected("claim confirmation is required")
    with transaction.atomic():
        try:
            if isinstance(draft, WaitlistDraft):
                locked = WaitlistDraft.objects.select_for_update().get(pk=draft.pk)
            else:
                locked = WaitlistDraft.objects.select_for_update().get(public_id=draft)
        except WaitlistDraft.DoesNotExist as exc:
            raise ClaimRejected("claim is not authorized") from exc
        if locked.lifecycle != DraftLifecycle.PENDING_CLAIM:
            raise ClaimRejected("claim is not authorized")
        if locked.expires_at is not None and locked.expires_at <= timezone.now():
            raise ClaimRejected("claim is not authorized")
        identities = ExternalIdentity.objects.filter(
            user=user,
            provider="google",
            email_verified=True,
            email_verification_source__in=ALLOWED_VERIFICATION_SOURCES,
            email_snapshot__gt="",
            email_verified_at__isnull=False,
        )
        if not any(
            emails_match(identity.email_snapshot, locked.email_normalized)
            for identity in identities
        ):
            raise ClaimRejected("claim is not authorized")
        locked.claimed_by = user
        locked.claimed_at = timezone.now()
        locked.capability_digest = None
        locked.expires_at = None
        locked.lifecycle = DraftLifecycle.CLAIMED
        locked.revision += 1
        locked.save()
        return locked
