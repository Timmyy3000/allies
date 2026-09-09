from __future__ import annotations

from celery import shared_task
from django.conf import settings

from .services.approvals import (
    dispatch_pending_routine_approval_commands,
    expire_routine_approvals,
)
from .services.dispatch import dispatch_pending_routine_outboxes
from .services.scheduler import admit_due_routines


@shared_task(
    bind=True,
    name="routines.admit_due_occurrences",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=270,
    time_limit=300,
)
def admit_due_occurrences_task(self, limit: int = 50) -> dict[str, int]:
    if not getattr(settings, "ALLIES_ROUTINE_SCHEDULER_ENABLED", False):
        return {"disabled": 1}
    return admit_due_routines(limit=limit).as_dict()


@shared_task(
    bind=True,
    name="routines.dispatch_pending_outboxes",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=270,
    time_limit=300,
)
def dispatch_pending_outboxes_task(self, limit: int = 20) -> dict[str, int]:
    return dispatch_pending_routine_outboxes(limit=limit).as_dict()


@shared_task(
    bind=True,
    name="routines.dispatch_pending_approval_commands",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=270,
    time_limit=300,
)
def dispatch_pending_approval_commands_task(self, limit: int = 20) -> dict[str, int]:
    return dispatch_pending_routine_approval_commands(limit=limit).as_dict()


@shared_task(
    bind=True,
    name="routines.expire_approvals",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=270,
    time_limit=300,
)
def expire_approvals_task(self, limit: int = 20) -> dict[str, int]:
    if not getattr(settings, "ALLIES_ROUTINE_APPROVAL_ENABLED", False):
        return {"disabled": 1}
    return {"expired": expire_routine_approvals(limit=limit)}
