import logging

from celery import shared_task

from allies.services.deletion import (
    reconcile_ally_deletion,
    reconcile_due_ally_deletions,
)
from allies.services.labels import generate_label_for_ally, generate_pending_labels
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


@shared_task(
    bind=True,
    name="allies.generate_ally_label",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=270,
    time_limit=300,
)
def generate_ally_label_task(self, ally_id: str) -> bool:
    return generate_label_for_ally(ally_id)


@shared_task(
    bind=True,
    name="allies.generate_pending_labels",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=270,
    time_limit=300,
)
def generate_pending_labels_task(self, limit: int = 100) -> dict[str, int]:
    return generate_pending_labels(limit=limit)


@shared_task(
    bind=True,
    name="allies.reconcile_ally_deletion",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=270,
    time_limit=300,
)
def reconcile_ally_deletion_task(self, operation_id: str):
    return reconcile_ally_deletion(operation_id=operation_id)


@shared_task(
    bind=True,
    name="allies.reconcile_due_ally_deletions",
    acks_late=True,
    ignore_result=True,
    soft_time_limit=270,
    time_limit=300,
)
def reconcile_due_ally_deletions_task(self, limit: int = 100) -> dict[str, int]:
    return reconcile_due_ally_deletions(limit=limit)
