from celery import shared_task

from allies.services.onboarding import cleanup_expired_onboarding_attempts
from allies.services.provisioning import dispatch_due_provisioning


@shared_task(
    bind=True,
    name="allies.dispatch_due_provisioning",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=270,
    time_limit=300,
)
def dispatch_due_provisioning_task(self, limit: int = 20) -> dict[str, int]:
    return dispatch_due_provisioning(limit=limit).as_dict()


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
