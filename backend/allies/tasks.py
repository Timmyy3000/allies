import logging

from celery import shared_task

from allies.services.onboarding import cleanup_expired_onboarding_attempts
from allies.services.provisioning import dispatch_due_provisioning

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="allies.dispatch_due_provisioning",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=270,
    time_limit=300,
)
def dispatch_due_provisioning_task(self, limit: int = 20) -> dict[str, int]:
    report = dispatch_due_provisioning(limit=limit)
    for countdown in report.follow_up_delays:
        try:
            dispatch_due_provisioning_task.apply_async(
                kwargs={"limit": limit}, countdown=countdown
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "provisioning follow-up scheduling failed",
                extra={"outcome": "broker_unavailable", "countdown": countdown},
            )
            continue
    return report.as_dict()


@shared_task(
    bind=True,
    name="allies.cleanup_expired_onboarding_attempts",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=270,
    time_limit=300,
)
def cleanup_expired_onboarding_attempts_task(self, limit: int = 500) -> int:
    return cleanup_expired_onboarding_attempts(limit=limit)
