from __future__ import annotations

from celery import shared_task

from activities.services.approvals import dispatch_pending_approvals


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
