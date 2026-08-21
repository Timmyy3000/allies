from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from allies.exceptions import ProvisioningRejected, ProvisioningRetryable
from allies.gateways.foundry import (
    ProfileProvisioningReceipt,
    ProfileProvisioningRequest,
    provision_profile,
)
from allies.models import BindingStatus, ProvisioningOperation, ProvisioningStatus


@dataclass(frozen=True, slots=True)
class DispatchReport:
    claimed: int = 0
    succeeded: int = 0
    deferred: int = 0
    failed: int = 0

    def as_dict(self):
        return {
            "claimed": self.claimed,
            "succeeded": self.succeeded,
            "deferred": self.deferred,
            "failed": self.failed,
        }


def _claim_due(*, now, limit: int) -> list[tuple[int, int]]:
    lease_until = now + timedelta(
        seconds=int(getattr(settings, "ALLIES_PROVISIONING_LEASE_SECONDS", 60))
    )
    lease_available = Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now)
    due = (
        Q(
            status__in=[ProvisioningStatus.PENDING, ProvisioningStatus.RETRYABLE],
            next_attempt_at__lte=now,
        )
        & lease_available
    ) | Q(
        status=ProvisioningStatus.IN_PROGRESS,
        lease_expires_at__lte=now,
    )
    with transaction.atomic():
        ProvisioningOperation.objects.filter(
            expires_at__lte=now,
            status__in=[
                ProvisioningStatus.PENDING,
                ProvisioningStatus.RETRYABLE,
                ProvisioningStatus.IN_PROGRESS,
            ],
        ).update(
            status=ProvisioningStatus.EXPIRED,
            safe_error_code="retry_expired",
            lease_expires_at=None,
        )
        query = ProvisioningOperation.objects.filter(due, expires_at__gt=now).order_by(
            "next_attempt_at", "id"
        )
        query = query.select_for_update(
            skip_locked=connection.features.has_select_for_update_skip_locked
        )
        claimed = []
        for operation in query[:limit]:
            operation.attempt_count += 1
            operation.status = ProvisioningStatus.IN_PROGRESS
            operation.last_attempt_at = now
            operation.lease_expires_at = lease_until
            operation.save(
                update_fields=(
                    "attempt_count",
                    "status",
                    "last_attempt_at",
                    "lease_expires_at",
                    "updated_at",
                )
            )
            claimed.append((operation.pk, operation.attempt_count))
        return claimed


def _receipt_digest(receipt: ProfileProvisioningReceipt) -> str:
    raw = json.dumps(
        receipt.model_dump(), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _defer(pk: int, fence: int, code: str, *, now) -> bool:
    delay = min(
        int(getattr(settings, "ALLIES_PROVISIONING_MAX_BACKOFF_SECONDS", 300)),
        2 ** min(fence, 8),
    )
    return bool(
        ProvisioningOperation.objects.filter(
            pk=pk,
            attempt_count=fence,
            status=ProvisioningStatus.IN_PROGRESS,
        ).update(
            status=ProvisioningStatus.RETRYABLE,
            safe_error_code=code,
            next_attempt_at=now + timedelta(seconds=delay),
            lease_expires_at=None,
        )
    )


def _dispatch_one(pk: int, fence: int, *, now) -> str:
    operation = ProvisioningOperation.objects.select_related(
        "workspace", "binding__ally"
    ).get(pk=pk)
    request = ProfileProvisioningRequest(
        workspace_id=operation.workspace.public_id,
        binding_id=operation.binding.cloud_binding_id,
        ally_ref=operation.binding.ally.public_id,
        operation_id=operation.public_id,
        request_fingerprint=operation.content_fingerprint,
        job=operation.binding.ally.job,
        personality=operation.binding.ally.personality,
    )
    try:
        receipt = provision_profile(request)
    except ProvisioningRetryable:
        _defer(pk, fence, "foundry_retryable", now=now)
        return "deferred"
    except ProvisioningRejected:
        ProvisioningOperation.objects.filter(
            pk=pk,
            attempt_count=fence,
            status=ProvisioningStatus.IN_PROGRESS,
        ).update(
            status=ProvisioningStatus.REPAIR_REQUIRED,
            safe_error_code="foundry_rejected",
            lease_expires_at=None,
            completed_at=now,
        )
        return "failed"
    if (
        receipt.version != request.version
        or receipt.binding_id != request.binding_id
        or receipt.operation_id != request.operation_id
        or receipt.request_fingerprint != request.request_fingerprint
    ):
        ProvisioningOperation.objects.filter(
            pk=pk,
            attempt_count=fence,
            status=ProvisioningStatus.IN_PROGRESS,
        ).update(
            status=ProvisioningStatus.FAILED,
            safe_error_code="receipt_identity_mismatch",
            lease_expires_at=None,
            completed_at=now,
        )
        return "failed"
    digest = _receipt_digest(receipt)
    if receipt.status == "active":
        with transaction.atomic():
            updated = ProvisioningOperation.objects.filter(
                pk=pk,
                attempt_count=fence,
                status=ProvisioningStatus.IN_PROGRESS,
            ).update(
                status=ProvisioningStatus.SUCCEEDED,
                safe_error_code="",
                receipt_digest=digest,
                lease_expires_at=None,
                completed_at=now,
            )
            if updated:
                operation.binding.status = BindingStatus.BOUND
                operation.binding.receipt_digest = digest
                operation.binding.save(
                    update_fields=("status", "receipt_digest", "updated_at")
                )
        return "succeeded" if updated else "deferred"
    if receipt.status == "pending":
        _defer(pk, fence, "materialization_pending", now=now)
        return "deferred"
    with transaction.atomic():
        updated = ProvisioningOperation.objects.filter(
            pk=pk,
            attempt_count=fence,
            status=ProvisioningStatus.IN_PROGRESS,
        ).update(
            status=ProvisioningStatus.REPAIR_REQUIRED,
            safe_error_code="foundry_repair_required",
            receipt_digest=digest,
            lease_expires_at=None,
            completed_at=now,
        )
        if updated:
            operation.binding.status = BindingStatus.INCOMPATIBLE
            operation.binding.save(update_fields=("status", "updated_at"))
    return "failed"


def dispatch_due_provisioning(*, now=None, limit: int = 20) -> DispatchReport:
    now = now or timezone.now()
    limit = max(1, min(limit, 100))
    claims = _claim_due(now=now, limit=limit)
    outcomes = [_dispatch_one(pk, fence, now=now) for pk, fence in claims]
    return DispatchReport(
        claimed=len(claims),
        succeeded=outcomes.count("succeeded"),
        deferred=outcomes.count("deferred"),
        failed=outcomes.count("failed"),
    )
