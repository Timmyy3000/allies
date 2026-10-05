"""Asynchronous authentication maintenance entry points."""

from __future__ import annotations

import logging

from celery import shared_task
from django.db import DatabaseError

from auths.services.cleanup import cleanup_auth_artifacts

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="auths.cleanup_auth_artifacts",
    autoretry_for=(DatabaseError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=1,
    acks_late=True,
    ignore_result=True,
    soft_time_limit=270,
    time_limit=300,
)
def cleanup_auth_artifacts_task(self) -> dict[str, int]:
    """Run one cleanup pass; counted object failures reconcile next run."""

    result = cleanup_auth_artifacts()
    if result.failures:
        logger.warning(
            "auth artifact cleanup completed with object failures",
            extra={"cleanup_failures": result.failures},
        )
    else:
        logger.info("auth artifact cleanup completed")
    return result.as_dict()
