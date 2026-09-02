"""Bounded cleanup use case shared by operators and Celery."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta

from auths.config import native_terminal_retention_seconds
from auths.exceptions import ValidationError
from auths.models import (
    AuthFlow,
    NativeAuthorizationTransaction,
    NativeExchangeCode,
    NativeTransactionStatus,
    RefreshToken,
)
from auths.services.avatars import cleanup_avatar_assets
from django.db import transaction
from django.db.models import Q
from django.utils import timezone


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
        stale_claim_ids = list(
            NativeAuthorizationTransaction.objects.filter(
                status=NativeTransactionStatus.CLAIMED,
                claim_expires_at__lt=now,
            )
            .order_by("claim_expires_at", "pk")
            .values_list("pk", flat=True)[:batch_size]
        )
        if stale_claim_ids:
            NativeAuthorizationTransaction.objects.filter(
                pk__in=stale_claim_ids,
                status=NativeTransactionStatus.CLAIMED,
            ).update(
                status=NativeTransactionStatus.FAILED,
                error_code="provider_unavailable",
                terminal_at=now,
            )
        native_code_ids = list(
            NativeExchangeCode.objects.filter(expires_at__lt=now)
            .order_by("expires_at", "pk")
            .values_list("pk", flat=True)[:batch_size]
        )
        NativeExchangeCode.objects.filter(pk__in=native_code_ids).delete()
        flow_ids = list(
            AuthFlow.objects.filter(expires_at__lt=now)
            .order_by("expires_at", "pk")
            .values_list("pk", flat=True)[:batch_size]
        )
        flow_count, _ = AuthFlow.objects.filter(pk__in=flow_ids).delete()
        terminal_statuses = (
            NativeTransactionStatus.COMPLETED,
            NativeTransactionStatus.DENIED,
            NativeTransactionStatus.FAILED,
        )
        terminal_cutoff = now - timedelta(seconds=native_terminal_retention_seconds())
        deletable_native_transactions = Q(
            status=NativeTransactionStatus.PENDING,
            expires_at__lt=now,
        ) | Q(
            status__in=terminal_statuses,
            terminal_at__lt=terminal_cutoff,
        )
        native_transaction_ids = list(
            NativeAuthorizationTransaction.objects.filter(
                deletable_native_transactions,
                # A completed transaction may still protect a terminal exchange
                # row. Codes are deleted above before this relation is removed.
                exchange_code__isnull=True,
            )
            .order_by("terminal_at", "expires_at", "pk")
            .values_list("pk", flat=True)[:batch_size]
        )
        # Re-assert eligibility because a callback may claim after selection.
        native_transaction_count, _ = (
            NativeAuthorizationTransaction.objects.filter(
                pk__in=native_transaction_ids,
            )
            .filter(
                deletable_native_transactions,
                exchange_code__isnull=True,
            )
            .delete()
        )
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
        flows=flow_count + native_transaction_count,
        refresh_tokens=token_count,
        avatars=deleted,
        failures=failed,
    )
