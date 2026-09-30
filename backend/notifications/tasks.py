from celery import shared_task

from .services import dispatch_push


@shared_task(
    name="notifications.dispatch_push",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=540,
    time_limit=570,
)
def dispatch_push_task(limit=50):
    return dispatch_push(limit=limit)
