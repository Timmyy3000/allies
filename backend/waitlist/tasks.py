"""Celery maintenance entry point for waitlist retention."""

from __future__ import annotations

from celery import shared_task

from .services.cleanup import cleanup_waitlist_drafts


@shared_task(
    bind=True,
    name="waitlist.cleanup_waitlist_drafts",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=270,
    time_limit=300,
)
def cleanup_waitlist_drafts_task(self, batch_size: int = 100) -> dict[str, int]:
    return cleanup_waitlist_drafts(batch_size=batch_size).as_dict()
