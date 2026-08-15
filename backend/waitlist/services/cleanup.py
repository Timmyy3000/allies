"""Bounded, repeat-safe retention cleanup."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..models import DraftLifecycle, WaitlistDraft


@dataclass(frozen=True)
class CleanupResult:
    deleted: int
    abandoned: int
    joined: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def cleanup_waitlist_drafts(*, batch_size: int = 100) -> CleanupResult:
    if not isinstance(batch_size, int) or not 1 <= batch_size <= 100:
        raise ValueError("batch-size must be between 1 and 100")
    now = timezone.now()
    joined_retention = getattr(
        settings, "ALLIES_WAITLIST_JOINED_RETENTION_SECONDS", None
    )
    with transaction.atomic():
        abandoned = list(
            WaitlistDraft.objects.select_for_update()
            .filter(
                joined_at__isnull=True,
                lifecycle__in=[
                    DraftLifecycle.CONFIGURING,
                    DraftLifecycle.READY_FOR_GREETING,
                    DraftLifecycle.GREETING_READY,
                    DraftLifecycle.REPLY_PENDING,
                    DraftLifecycle.EXPIRED,
                ],
                expires_at__lte=now,
            )
            .order_by("expires_at", "pk")
            .values_list("pk", flat=True)[:batch_size]
        )
        remaining = max(0, batch_size - len(abandoned))
        joined: list[int] = []
        if joined_retention:
            joined = list(
                WaitlistDraft.objects.select_for_update()
                .filter(
                    joined_at__isnull=False,
                    lifecycle__in=[
                        DraftLifecycle.PENDING_CLAIM,
                        DraftLifecycle.EXPIRED,
                    ],
                    expires_at__lte=now,
                )
                .order_by("expires_at", "pk")
                .values_list("pk", flat=True)[:remaining]
            )
        ids = abandoned + joined
        # Keep the row locks from the candidate queries until deletion.  If a
        # claim won the race before cleanup selected the row, PostgreSQL
        # rechecks the SELECT FOR UPDATE predicate after waiting and excludes
        # the now-claimed draft.  Repeating the lifecycle/expiry predicates in
        # the delete is a second guard against destructive PK-only deletion.
        WaitlistDraft.objects.filter(
            Q(
                pk__in=abandoned,
                joined_at__isnull=True,
                lifecycle__in=[
                    DraftLifecycle.CONFIGURING,
                    DraftLifecycle.READY_FOR_GREETING,
                    DraftLifecycle.GREETING_READY,
                    DraftLifecycle.REPLY_PENDING,
                    DraftLifecycle.EXPIRED,
                ],
                expires_at__lte=now,
            )
            | Q(
                pk__in=joined,
                joined_at__isnull=False,
                lifecycle__in=[DraftLifecycle.PENDING_CLAIM, DraftLifecycle.EXPIRED],
                expires_at__lte=now,
            )
        ).delete()
    # QuerySet.delete() counts cascaded operation receipts as well as drafts;
    # the service result reports the number of product drafts removed.
    return CleanupResult(deleted=len(ids), abandoned=len(abandoned), joined=len(joined))
