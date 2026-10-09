"""Which allies have recent work, so the sidebar does not show them asleep."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

from chat.models import NONTERMINAL_MESSAGE_STATUSES, Message
from integrations.models import BrowserSession
from routines.models import ROUTINE_ACTIVE_RUN_OUTCOMES, RoutineRunSnapshot

# Matches the web client's ALLY_SLEEP_AFTER_MS.
RECENT_WINDOW = timedelta(minutes=20)
# No sweeper closes crashed chat or routine rows; this keeps them from holding an ally awake.
STALE_AFTER = timedelta(hours=2)


def ally_ids_with_recent_activity(ally_ids: Iterable[UUID]) -> frozenset[UUID]:
    """Allies with chat, routine, or browser work in flight or within the window."""

    ids = list(ally_ids)
    if not ids:
        return frozenset()
    now = timezone.now()
    recent_after = now - RECENT_WINDOW
    stale_after = now - STALE_AFTER
    busy: set[UUID] = set()
    busy.update(
        Message.objects.filter(conversation__ally_id__in=ids)
        .filter(
            Q(status__in=NONTERMINAL_MESSAGE_STATUSES, updated_at__gte=stale_after)
            | Q(updated_at__gte=recent_after)
        )
        .order_by()
        .values_list("conversation__ally_id", flat=True)
        .distinct()
    )
    busy.update(
        RoutineRunSnapshot.objects.filter(ally_id__in=ids)
        .filter(
            Q(outcome__in=ROUTINE_ACTIVE_RUN_OUTCOMES, updated_at__gte=stale_after)
            | Q(updated_at__gte=recent_after)
        )
        .order_by()
        .values_list("ally_id", flat=True)
        .distinct()
    )
    busy.update(
        BrowserSession.objects.filter(ally_id__in=ids)
        .filter(Q(ended_at=None, expires_at__gt=now) | Q(ended_at__gte=recent_after))
        .order_by()
        .values_list("ally_id", flat=True)
        .distinct()
    )
    return frozenset(busy)
