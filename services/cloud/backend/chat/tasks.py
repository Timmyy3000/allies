from __future__ import annotations

from celery import shared_task

from chat.services.dispatch import dispatch_pending_messages


@shared_task(
    bind=True,
    name="chat.dispatch_pending_messages",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=270,
    time_limit=300,
)
def dispatch_pending_messages_task(self, limit: int = 20) -> dict[str, int]:
    return dispatch_pending_messages(limit=limit).as_dict()
