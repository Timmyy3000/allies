from __future__ import annotations

from celery import shared_task

from activities.services.approvals import dispatch_pending_approvals
from activities.services.projection import expire_stalled_held_gaps


@shared_task(
    bind=True,
    name="activities.dispatch_pending_approvals",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=270,
    time_limit=300,
)
def dispatch_pending_approvals_task(self, limit: int = 20) -> dict[str, int]:
    return dispatch_pending_approvals(limit=limit).as_dict()


@shared_task(
    bind=True,
    name="activities.expire_stalled_held_gaps",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=270,
    time_limit=300,
)
def expire_stalled_held_gaps_task(self, limit: int = 50) -> int:
    return expire_stalled_held_gaps(limit=limit)
