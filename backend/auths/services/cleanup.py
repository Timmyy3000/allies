"""Bounded cleanup use case shared by operators and Celery."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from django.db import transaction
from django.utils import timezone

from auths.exceptions import ValidationError
from auths.models import AuthFlow, RefreshToken
from auths.services.avatars import cleanup_avatar_assets


@dataclass(frozen=True)
class CleanupResult:
    flows: int
    refresh_tokens: int
    avatars: int
    failures: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def cleanup_auth_artifacts(*, batch_size: int = 100) -> CleanupResult:
    """Delete one repeat-safe, bounded batch of expired authentication state."""

    if not isinstance(batch_size, int) or not 1 <= batch_size <= 100:
        raise ValidationError("batch size is invalid")
    now = timezone.now()
    with transaction.atomic():
        flow_ids = list(
            AuthFlow.objects.filter(expires_at__lt=now)
            .order_by("expires_at", "pk")
            .values_list("pk", flat=True)[:batch_size]
        )
        flow_count, _ = AuthFlow.objects.filter(pk__in=flow_ids).delete()
        token_ids = list(
            RefreshToken.objects.filter(
                expires_at__lt=now, family__absolute_expires_at__lt=now
            )
            .order_by("expires_at", "pk")
            .values_list("pk", flat=True)[:batch_size]
        )
        token_count, _ = RefreshToken.objects.filter(pk__in=token_ids).delete()
    deleted, failed = cleanup_avatar_assets(batch_size=batch_size)
    return CleanupResult(
        flows=flow_count,
        refresh_tokens=token_count,
        avatars=deleted,
        failures=failed,
    )
