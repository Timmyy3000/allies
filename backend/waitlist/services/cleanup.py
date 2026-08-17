from dataclasses import asdict, dataclass

from django.db import transaction
from django.utils import timezone

from ..models import WaitlistEntry


@dataclass(frozen=True)
class CleanupResult:
    deleted: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def cleanup_waitlist_entries(*, batch_size: int = 100) -> CleanupResult:
    if not isinstance(batch_size, int) or not 1 <= batch_size <= 100:
        raise ValueError("batch-size must be between 1 and 100")
    with transaction.atomic():
        ids = list(
            WaitlistEntry.objects.select_for_update()
            .filter(expires_at__lte=timezone.now())
            .order_by("expires_at", "pk")
            .values_list("pk", flat=True)[:batch_size]
        )
        WaitlistEntry.objects.filter(pk__in=ids).delete()
    return CleanupResult(deleted=len(ids))
