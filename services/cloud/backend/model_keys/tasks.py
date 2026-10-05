from celery import shared_task

from model_keys.services import sync_pending


@shared_task(
    name="model_keys.sync_selections",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=120,
    time_limit=150,
)
def sync_selections_task() -> int:
    return sync_pending()
