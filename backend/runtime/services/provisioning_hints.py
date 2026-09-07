"""Durable, bounded delivery of profile-readiness nudges to Cloud."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
from uuid import UUID, uuid5

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from runtime.exceptions import RuntimeConflictError, RuntimeValidationError
from runtime.models import (
    ProvisioningHintDelivery,
    ProvisioningHintDeliveryState,
    RuntimeProfile,
    Workspace,
)

from .event_delivery import (
    DELIVERY_LEASE_SECONDS,
    MAX_DELIVERY_ATTEMPTS,
    MAX_DELIVERY_BACKOFF_SECONDS,
    MAX_RESPONSE_BYTES,
    _backoff_seconds,
    _NoRedirect,
    _safe_error_code,
    _safe_response_code,
    _validated_cloud_url,
)

MAX_HINT_DELIVERY_BATCH = 1
HINT_DELIVERY_LEASE_SECONDS = DELIVERY_LEASE_SECONDS
MAX_HINT_DELIVERY_ATTEMPTS = MAX_DELIVERY_ATTEMPTS
MAX_HINT_DELIVERY_BACKOFF_SECONDS = MAX_DELIVERY_BACKOFF_SECONDS
HINT_VERSION = 1
_HINT_NAMESPACE = UUID("f6f79a46-9f66-4da4-93f8-2df9ed2c1b94")


@dataclass(frozen=True, slots=True)
class ProvisioningHintClaim:
    delivery_id: UUID
    hint_id: UUID
    workspace_id: str
    ally_ref: str
    runtime_profile_id: UUID
    generation: int
    receipt_id: UUID
    occurred_at: datetime
    attempt: int

    def payload(self) -> dict[str, object]:
        return {
            "version": HINT_VERSION,
            "hint_id": str(self.hint_id),
            "workspace_id": str(self.workspace_id),
            "ally_ref": self.ally_ref,
            "runtime_profile_id": str(self.runtime_profile_id),
            "generation": self.generation,
            "receipt_id": str(self.receipt_id),
            "occurred_at": self.occurred_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class PublishResult:
    claimed: int = 0
    delivered: int = 0
    deferred: int = 0
    exhausted: int = 0


def hint_id_for(profile_id: UUID, receipt_id: UUID) -> UUID:
    """Return the stable logical identity for one materialization receipt."""

    return uuid5(_HINT_NAMESPACE, f"{profile_id}:{receipt_id}")


@transaction.atomic
def ensure_provisioning_hint_delivery(
    workspace: Workspace,
    profile: RuntimeProfile,
    *,
    now: datetime | None = None,
) -> tuple[ProvisioningHintDelivery, bool]:
    """Insert the one hint row associated with a current profile receipt.

    This function intentionally does no network work.  Receipt callers invoke
    it while holding the workspace/profile transaction; the row is therefore
    committed or rolled back together with the authoritative receipt.
    """

    receipt_id = profile.materialization_receipt_id
    generation = profile.materialized_generation
    if receipt_id is None or generation <= 0:
        raise RuntimeValidationError("materialization receipt is required for a hint")
    if profile.workspace_id != workspace.id:
        raise RuntimeConflictError("profile and workspace do not match")
    if generation != workspace.machine_generation:
        raise RuntimeConflictError("materialization generation is not current")
    observed_at = now or timezone.now()
    hint_id = hint_id_for(profile.id, receipt_id)
    existing = (
        ProvisioningHintDelivery.objects.select_for_update()
        .filter(runtime_profile_id=profile.id, receipt_id=receipt_id)
        .first()
    )
    if existing is not None:
        if (
            existing.id != hint_id
            or existing.workspace_id != workspace.id
            or existing.ally_ref != profile.ally_ref
            or existing.generation != generation
        ):
            raise RuntimeConflictError(
                "readiness hint identity conflicts with stored state"
            )
        return existing, False
    try:
        with transaction.atomic():
            delivery = ProvisioningHintDelivery.objects.create(
                id=hint_id,
                workspace=workspace,
                runtime_profile=profile,
                ally_ref=profile.ally_ref,
                generation=generation,
                receipt_id=receipt_id,
                occurred_at=observed_at,
                state=ProvisioningHintDeliveryState.PENDING,
                delivery_attempts=0,
                next_attempt_at=observed_at,
            )
    except IntegrityError:
        delivery = (
            ProvisioningHintDelivery.objects.select_for_update()
            .filter(runtime_profile_id=profile.id, receipt_id=receipt_id)
            .first()
        )
        if delivery is None:
            raise
        return delivery, False
    return delivery, True


def claim_provisioning_hint_deliveries(
    limit: int = MAX_HINT_DELIVERY_BATCH,
    *,
    now: datetime | None = None,
) -> tuple[ProvisioningHintClaim, ...]:
    if isinstance(limit, bool) or not 1 <= limit <= MAX_HINT_DELIVERY_BATCH:
        raise RuntimeValidationError("hint delivery limit must be 1")
    observed_at = now or timezone.now()
    with transaction.atomic():
        expired = list(
            ProvisioningHintDelivery.objects.select_for_update()
            .filter(
                state=ProvisioningHintDeliveryState.DELIVERING,
                delivery_attempts=MAX_HINT_DELIVERY_ATTEMPTS,
                lease_expires_at__lte=observed_at,
            )
            .order_by("lease_expires_at", "created_at", "id")[:limit]
        )
        for row in expired:
            row.state = ProvisioningHintDeliveryState.EXHAUSTED
            row.lease_expires_at = None
            row.safe_error_code = "hint_lease_expired"
            row.save(
                update_fields=[
                    "state",
                    "lease_expires_at",
                    "safe_error_code",
                    "updated_at",
                ]
            )
        rows = list(
            ProvisioningHintDelivery.objects.select_for_update()
            .select_related("workspace")
            .filter(
                Q(
                    state=ProvisioningHintDeliveryState.PENDING,
                    next_attempt_at__lte=observed_at,
                )
                | Q(
                    state=ProvisioningHintDeliveryState.DELIVERING,
                    lease_expires_at__lte=observed_at,
                )
            )
            .filter(delivery_attempts__lt=MAX_HINT_DELIVERY_ATTEMPTS)
            .order_by("next_attempt_at", "created_at", "id")[:limit]
        )
        claims: list[ProvisioningHintClaim] = []
        for row in rows:
            row.state = ProvisioningHintDeliveryState.DELIVERING
            row.delivery_attempts += 1
            row.lease_expires_at = observed_at + timedelta(
                seconds=HINT_DELIVERY_LEASE_SECONDS
            )
            row.save(
                update_fields=[
                    "state",
                    "delivery_attempts",
                    "lease_expires_at",
                    "updated_at",
                ]
            )
            claims.append(
                ProvisioningHintClaim(
                    delivery_id=row.id,
                    hint_id=row.id,
                    workspace_id=row.workspace.tenant_ref,
                    ally_ref=row.ally_ref,
                    runtime_profile_id=row.runtime_profile_id,
                    generation=row.generation,
                    receipt_id=row.receipt_id,
                    occurred_at=row.occurred_at,
                    attempt=row.delivery_attempts,
                )
            )
    return tuple(claims)


def mark_provisioning_hint_delivery(
    delivery_id: UUID,
    *,
    attempt: int,
    success: bool,
    safe_error_code: str = "",
    terminal: bool = False,
    now: datetime | None = None,
) -> ProvisioningHintDelivery | None:
    if isinstance(attempt, bool) or not 1 <= attempt <= MAX_HINT_DELIVERY_ATTEMPTS:
        raise RuntimeValidationError("hint delivery attempt is invalid")
    observed_at = now or timezone.now()
    with transaction.atomic():
        row = ProvisioningHintDelivery.objects.select_for_update().get(pk=delivery_id)
        if (
            row.state != ProvisioningHintDeliveryState.DELIVERING
            or row.delivery_attempts != attempt
        ):
            return None
        if success:
            row.state = ProvisioningHintDeliveryState.DELIVERED
            row.delivered_at = observed_at
            row.lease_expires_at = None
            row.safe_error_code = ""
        else:
            if safe_error_code and not _safe_error_code(safe_error_code):
                raise RuntimeValidationError("hint delivery error code is invalid")
            row.safe_error_code = safe_error_code or "hint_delivery_failed"
            row.lease_expires_at = None
            if terminal or row.delivery_attempts >= MAX_HINT_DELIVERY_ATTEMPTS:
                row.state = ProvisioningHintDeliveryState.EXHAUSTED
            else:
                row.state = ProvisioningHintDeliveryState.PENDING
                row.next_attempt_at = observed_at + timedelta(
                    seconds=_backoff_seconds(row.delivery_attempts)
                )
        row.save(
            update_fields=[
                "state",
                "delivered_at",
                "lease_expires_at",
                "safe_error_code",
                "next_attempt_at",
                "updated_at",
            ]
        )
    return row


def publish_due_profile_readiness_hints(
    *,
    limit: int = MAX_HINT_DELIVERY_BATCH,
    now: datetime | None = None,
) -> PublishResult:
    """Publish one bounded batch while leaving retries durable."""

    if not getattr(settings, "ALLIES_RUNTIME_READINESS_HINT_ENABLED", False):
        return PublishResult()
    observed_at = now or timezone.now()
    claims = claim_provisioning_hint_deliveries(limit, now=observed_at)
    delivered = deferred = exhausted = 0
    for claim in claims:
        status, code = _post_hint_to_cloud(claim)
        if status == 202:
            marked = mark_provisioning_hint_delivery(
                claim.delivery_id,
                attempt=claim.attempt,
                success=True,
                now=observed_at,
            )
            delivered += int(marked is not None)
            deferred += int(marked is None)
            continue
        terminal = status in (401, 403, 404, 422) or (
            status == 409 and code == "conflict"
        )
        marked = mark_provisioning_hint_delivery(
            claim.delivery_id,
            attempt=claim.attempt,
            success=False,
            safe_error_code=code or "hint_delivery_unavailable",
            terminal=terminal,
            now=observed_at,
        )
        if marked is None:
            deferred += 1
        elif marked.state == ProvisioningHintDeliveryState.EXHAUSTED:
            exhausted += 1
        else:
            deferred += 1
    return PublishResult(len(claims), delivered, deferred, exhausted)


def _post_hint_to_cloud(claim: ProvisioningHintClaim) -> tuple[int, str]:
    if not getattr(settings, "ALLIES_RUNTIME_READINESS_HINT_ENABLED", False):
        return 503, "hint_delivery_disabled"
    base_url = _validated_cloud_url(getattr(settings, "ALLIES_CLOUD_URL", None))
    token = getattr(settings, "ALLIES_CLOUD_EVENT_SERVICE_TOKEN", None)
    if not base_url or not token:
        return 503, "hint_delivery_not_configured"
    body = json.dumps(
        claim.payload(),
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}/api/v1/internal/foundry/profile-readiness-hints",
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with build_opener(_NoRedirect).open(request, timeout=5) as response:
            status = int(response.status)
            response_body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(response_body) > MAX_RESPONSE_BYTES:
                return 503, "hint_delivery_response_too_large"
            if status == 202:
                try:
                    receipt = json.loads(response_body.decode("utf-8"))
                except (UnicodeDecodeError, TypeError, ValueError):
                    return 503, "hint_delivery_receipt_invalid"
                if not isinstance(receipt, dict) or receipt.get("status") != "accepted":
                    return 503, "hint_delivery_receipt_invalid"
                return 202, ""
            return status, _safe_response_code(response_body)
    except HTTPError as exc:
        try:
            response_body = exc.read(MAX_RESPONSE_BYTES + 1)
        finally:
            exc.close()
        if len(response_body) > MAX_RESPONSE_BYTES:
            return int(exc.code), "hint_delivery_response_too_large"
        return int(exc.code), _safe_response_code(response_body)
    except (TimeoutError, URLError, OSError):
        return 503, "hint_delivery_unavailable"


__all__ = [
    "HINT_DELIVERY_LEASE_SECONDS",
    "MAX_HINT_DELIVERY_ATTEMPTS",
    "MAX_HINT_DELIVERY_BACKOFF_SECONDS",
    "MAX_HINT_DELIVERY_BATCH",
    "ProvisioningHintClaim",
    "ProvisioningHintDeliveryState",
    "PublishResult",
    "claim_provisioning_hint_deliveries",
    "ensure_provisioning_hint_delivery",
    "hint_id_for",
    "mark_provisioning_hint_delivery",
    "publish_due_profile_readiness_hints",
]
