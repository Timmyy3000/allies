from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from uuid import UUID

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from allies.exceptions import ProvisioningRejected, ProvisioningRetryable
from allies.gateways.foundry import (
    ProfileProvisioningReceipt,
    ProfileProvisioningRequest,
    ProfileReadinessHint,
    activate_workspace,
    provision_profile,
)
from allies.models import (
    BindingStatus,
    ProvisioningOperation,
    ProvisioningStatus,
    default_operation_expiry,
)
from allies.services.timing import readiness_phase
from chat.exceptions import (
    OnboardingHandoffRepairRequired,
    OnboardingHandoffUnavailable,
)
from observability.events import emit_event


@dataclass(frozen=True, slots=True)
class DispatchReport:
    claimed: int = 0
    succeeded: int = 0
    deferred: int = 0
    failed: int = 0
    repair_required: int = 0
    follow_up_delays: tuple[int, ...] = ()

    def as_dict(self):
        return {
            "claimed": self.claimed,
            "succeeded": self.succeeded,
            "deferred": self.deferred,
            "failed": self.failed,
            "repair_required": self.repair_required,
        }


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    matched: int = 0
    requeued: int = 0


def recover_foundry_rejected(
    *, workspace_id: UUID, operation_id: UUID | None = None, confirm: bool = False
) -> RecoveryReport:
    """Requeue only the legacy Foundry contract rejection for one workspace."""

    filters = {
        "workspace_id": workspace_id,
        "binding__ally__workspace_id": workspace_id,
        "status": ProvisioningStatus.REPAIR_REQUIRED,
        "safe_error_code": "foundry_rejected",
        "binding__status": BindingStatus.PENDING,
    }
    if operation_id is not None:
        filters["pk"] = operation_id

    with transaction.atomic():
        operations = ProvisioningOperation.objects.select_for_update().filter(**filters)
        matched = operations.count()
        if not confirm or not matched:
            return RecoveryReport(matched=matched)

        now = timezone.now()
        requeued = operations.update(
            status=ProvisioningStatus.RETRYABLE,
            safe_error_code="",
            next_attempt_at=now,
            lease_expires_at=None,
            last_attempt_at=None,
            completed_at=None,
            readiness_hint_received_at=None,
            expires_at=default_operation_expiry(),
            updated_at=now,
        )
    return RecoveryReport(matched=matched, requeued=requeued)


def _claim_due(*, now, limit: int) -> list[tuple[UUID, int]]:
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


def _defer(pk: UUID, fence: int, code: str, *, now) -> bool:
    delay = min(
        int(getattr(settings, "ALLIES_PROVISIONING_MAX_BACKOFF_SECONDS", 300)),
        2 ** min(fence, 8),
    )
    # A hint committed while this attempt was running wins over exponential
    # backoff. The row lock closes the race with the hint transaction; either
    # transaction sees the marker and leaves a due operation behind.
    with transaction.atomic():
        operation = (
            ProvisioningOperation.objects.select_for_update()
            .filter(
                pk=pk,
                attempt_count=fence,
                status=ProvisioningStatus.IN_PROGRESS,
            )
            .first()
        )
        if operation is None:
            return False
        hinted = (
            operation.readiness_hint_received_at is not None
            and operation.last_attempt_at is not None
            and operation.readiness_hint_received_at > operation.last_attempt_at
        )
        operation.status = ProvisioningStatus.RETRYABLE
        operation.safe_error_code = code
        operation.next_attempt_at = now if hinted else now + timedelta(seconds=delay)
        operation.lease_expires_at = None
        operation.save(
            update_fields=(
                "status",
                "safe_error_code",
                "next_attempt_at",
                "lease_expires_at",
                "updated_at",
            )
        )
        if hinted:
            transaction.on_commit(_enqueue_due_dispatch)
        return True


@dataclass(frozen=True, slots=True)
class HintResult:
    status: Literal["accepted", "ignored"]


def _enqueue_due_dispatch() -> None:
    """Best-effort wakeup; the periodic due scan is the durable fallback."""

    try:
        from allies.tasks import dispatch_due_provisioning_task

        dispatch_due_provisioning_task.apply_async()
    except Exception as exc:  # noqa: BLE001
        emit_event(
            "runtime.operation.failed",
            operation="readiness.hint_dispatch",
            error_code="broker_unavailable",
            error_type=type(exc).__name__,
        )
        return


def accept_profile_readiness_hint(
    payload: ProfileReadinessHint, *, now=None
) -> HintResult:
    """Record one Foundry readiness signal and wake the durable operation."""

    if not isinstance(payload, ProfileReadinessHint):
        try:
            payload = ProfileReadinessHint.model_validate(payload)
        except ValueError as exc:
            raise ValueError("readiness hint is invalid") from exc
    now = now or timezone.now()
    if timezone.is_naive(now):
        raise ValueError("readiness hint receive time must include a timezone")

    try:
        with transaction.atomic():
            operation = (
                ProvisioningOperation.objects.select_for_update()
                .select_related("binding__ally")
                .get(
                    workspace_id=payload.workspace_id,
                    binding__ally_id=payload.ally_ref,
                    binding__ally__workspace_id=payload.workspace_id,
                )
            )
            if operation.expires_at <= now or operation.status in {
                ProvisioningStatus.SUCCEEDED,
                ProvisioningStatus.FAILED,
                ProvisioningStatus.REPAIR_REQUIRED,
                ProvisioningStatus.EXPIRED,
            }:
                return HintResult("ignored")

            marker_changed = (
                operation.readiness_hint_received_at is None
                or operation.readiness_hint_received_at < now
            )
            if marker_changed:
                operation.readiness_hint_received_at = now

            schedule = (
                operation.status
                in {
                    ProvisioningStatus.PENDING,
                    ProvisioningStatus.RETRYABLE,
                }
                or operation.status == ProvisioningStatus.IN_PROGRESS
                and (
                    operation.lease_expires_at is not None
                    and operation.lease_expires_at <= now
                )
            )
            if schedule:
                operation.next_attempt_at = now

            update_fields = ["updated_at"]
            if marker_changed:
                update_fields.append("readiness_hint_received_at")
            if schedule:
                update_fields.append("next_attempt_at")
            operation.save(update_fields=tuple(dict.fromkeys(update_fields)))
            transaction.on_commit(
                lambda: emit_event(
                    "runtime.operation.succeeded",
                    operation="readiness.hint_received",
                    request_id=str(payload.hint_id),
                    correlation_id=str(operation.pk),
                    workspace_id=str(operation.workspace_id),
                    resource_id=str(payload.runtime_profile_id),
                )
            )
            if schedule:
                transaction.on_commit(_enqueue_due_dispatch)
    except ProvisioningOperation.DoesNotExist as exc:
        raise ValueError("readiness hint operation unavailable") from exc
    return HintResult("accepted")


def _dispatch_one(pk: UUID, fence: int) -> tuple[str, int | None]:
    with readiness_phase(
        "provisioning.reconcile", correlation_id=str(pk), retry_count=fence - 1
    ) as timing:
        result = _dispatch_claimed(pk, fence)
        timing["outcome"] = result[0]
        return result


def _dispatch_claimed(pk: UUID, fence: int) -> tuple[str, int | None]:
    operation = ProvisioningOperation.objects.select_related(
        "workspace", "binding__ally"
    ).get(pk=pk)
    identity = {
        "correlation_id": str(pk),
        "workspace_id": str(operation.workspace_id),
        "retry_count": fence - 1,
    }
    if operation.readiness_hint_received_at is not None:
        emit_event(
            "runtime.operation.succeeded",
            operation="readiness.hint_to_dispatch_wall",
            duration_ms=(
                timezone.now() - operation.readiness_hint_received_at
            ).total_seconds()
            * 1000,
            **identity,
        )
    try:
        request = ProfileProvisioningRequest(
            workspace_id=str(operation.workspace.id),
            binding_id=str(operation.binding.id),
            ally_ref=str(operation.binding.ally.id),
            operation_id=str(operation.id),
            request_fingerprint=operation.content_fingerprint,
            name=operation.binding.ally.name,
            job=operation.binding.ally.job,
            personality=operation.binding.ally.personality,
        )
    except ValueError:
        with transaction.atomic():
            updated = ProvisioningOperation.objects.filter(
                pk=pk,
                attempt_count=fence,
                status=ProvisioningStatus.IN_PROGRESS,
            ).update(
                status=ProvisioningStatus.REPAIR_REQUIRED,
                safe_error_code="stored_ally_invalid",
                lease_expires_at=None,
                completed_at=timezone.now(),
            )
            if updated:
                operation.binding.status = BindingStatus.INCOMPATIBLE
                operation.binding.save(update_fields=("status", "updated_at"))
        return "repair_required", None
    try:
        with readiness_phase("provisioning.profile_roundtrip", **identity):
            receipt = provision_profile(request)
    except ProvisioningRetryable:
        _defer(pk, fence, "foundry_retryable", now=timezone.now())
        return "deferred", None
    except ProvisioningRejected:
        ProvisioningOperation.objects.filter(
            pk=pk,
            attempt_count=fence,
            status=ProvisioningStatus.IN_PROGRESS,
        ).update(
            status=ProvisioningStatus.REPAIR_REQUIRED,
            safe_error_code="foundry_rejected",
            lease_expires_at=None,
            completed_at=timezone.now(),
        )
        return "failed", None
    try:
        with readiness_phase("provisioning.activation_roundtrip", **identity):
            activate_workspace(request.workspace_id)
    except ProvisioningRetryable:
        _defer(pk, fence, "foundry_activation_retryable", now=timezone.now())
        return "deferred", None
    except ProvisioningRejected:
        ProvisioningOperation.objects.filter(
            pk=pk,
            attempt_count=fence,
            status=ProvisioningStatus.IN_PROGRESS,
        ).update(
            status=ProvisioningStatus.REPAIR_REQUIRED,
            safe_error_code="foundry_activation_rejected",
            lease_expires_at=None,
            completed_at=timezone.now(),
        )
        return "failed", None
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
            completed_at=timezone.now(),
        )
        return "failed", None
    digest = _receipt_digest(receipt)
    if receipt.status == "active":
        activation_repair_required = False
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
            )
            if updated:
                operation.binding.status = BindingStatus.BOUND
                operation.binding.receipt_digest = digest
                operation.binding.save(
                    update_fields=("status", "receipt_digest", "updated_at")
                )
                try:
                    from chat.services.conversations import activate_onboarding_reply

                    activate_onboarding_reply(ally=operation.binding.ally)
                except (
                    OnboardingHandoffUnavailable,
                    OnboardingHandoffRepairRequired,
                ) as exc:
                    activation_repair_required = True
                    # Foundry has active compute; retain the bound identity and
                    # stop provisioning retries while recording handoff repair.
                    ProvisioningOperation.objects.filter(
                        pk=pk,
                        attempt_count=fence,
                        status=ProvisioningStatus.SUCCEEDED,
                    ).update(
                        status=ProvisioningStatus.REPAIR_REQUIRED,
                        safe_error_code=exc.code,
                        lease_expires_at=None,
                        completed_at=timezone.now(),
                    )
                else:
                    ProvisioningOperation.objects.filter(
                        pk=pk,
                        attempt_count=fence,
                        status=ProvisioningStatus.SUCCEEDED,
                    ).update(completed_at=timezone.now())
                    transaction.on_commit(
                        lambda: emit_event(
                            "runtime.operation.succeeded",
                            operation="provisioning.ready_committed_wall",
                            duration_ms=(
                                timezone.now() - operation.created_at
                            ).total_seconds()
                            * 1000,
                            **identity,
                        )
                    )
        if activation_repair_required:
            return "repair_required", None
        return ("succeeded", None) if updated else ("deferred", None)
    if receipt.status == "pending":
        deferred = _defer(pk, fence, "materialization_pending", now=timezone.now())
        return "deferred", (2**fence if deferred and fence in (1, 2, 3) else None)
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
            completed_at=timezone.now(),
        )
        if updated:
            operation.binding.status = BindingStatus.INCOMPATIBLE
            operation.binding.save(update_fields=("status", "updated_at"))
    return "failed", None


def dispatch_due_provisioning(*, now=None, limit: int = 20) -> DispatchReport:
    now = now or timezone.now()
    limit = max(1, min(limit, 100))
    claims = _claim_due(now=now, limit=limit)
    outcomes = [_dispatch_one(pk, fence) for pk, fence in claims]
    return DispatchReport(
        claimed=len(claims),
        succeeded=sum(outcome == "succeeded" for outcome, _ in outcomes),
        deferred=sum(outcome == "deferred" for outcome, _ in outcomes),
        failed=sum(outcome == "failed" for outcome, _ in outcomes),
        repair_required=sum(outcome == "repair_required" for outcome, _ in outcomes),
        follow_up_delays=tuple(
            sorted({delay for _, delay in outcomes if delay is not None})
        ),
    )
