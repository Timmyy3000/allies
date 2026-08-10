from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from runtime.exceptions import (
    RuntimeFencedError,
    RuntimeIdempotencyConflictError,
    RuntimeLeaseConflictError,
    RuntimeValidationError,
)
from runtime.models import (
    Attempt,
    AttemptStatus,
    ExecutionStatus,
    Lease,
    LeaseState,
    RuntimeProfile,
    Workspace,
)

from .profiles import profile_allows_runtime_write
from .retry import run_with_sqlite_lock_retry
from .runtime_auth import RuntimeContext
from .validation import digest_lease_token, digest_payload, validate_bounded_receipt


@dataclass(frozen=True, slots=True)
class TerminalReceipt:
    attempt_id: UUID
    status: str
    receipt_id: UUID
    requeued: bool = False
    receipt: dict | None = None


def complete_attempt(
    context: RuntimeContext,
    attempt_id: UUID,
    lease_token: str,
    receipt: dict,
) -> TerminalReceipt:
    return _finish_attempt(
        context,
        attempt_id,
        lease_token,
        receipt,
        retryable=False,
        terminal_status=AttemptStatus.SUCCEEDED,
    )


def fail_attempt(
    context: RuntimeContext,
    attempt_id: UUID,
    lease_token: str,
    failure: dict,
) -> TerminalReceipt:
    if not isinstance(failure, dict):
        raise RuntimeValidationError("failure must be an object")
    code = failure.get("code")
    if not isinstance(code, str) or not code:
        raise RuntimeValidationError("failure.code is required")
    retryable = failure.get("retryable", False)
    if type(retryable) is not bool:
        raise RuntimeValidationError("failure.retryable must be a boolean")
    receipt = failure.get("receipt")
    if receipt is None:
        receipt = {"code": code}
    receipt = validate_bounded_receipt(receipt)
    return _finish_attempt(
        context,
        attempt_id,
        lease_token,
        {"code": code, "retryable": retryable, "receipt": receipt},
        retryable=retryable,
        terminal_status=AttemptStatus.FAILED,
    )


def _finish_attempt(
    context: RuntimeContext,
    attempt_id: UUID,
    lease_token: str,
    value: dict,
    *,
    retryable: bool,
    terminal_status: str,
) -> TerminalReceipt:
    if not isinstance(context, RuntimeContext):
        raise RuntimeValidationError("runtime context is required")
    try:
        attempt_uuid = UUID(str(attempt_id))
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError("attempt_id must be a UUID") from exc
    if retryable:
        bounded = validate_bounded_receipt(value.get("receipt", {}))
        canonical = {"code": value["code"], "retryable": True, "receipt": bounded}
    else:
        canonical = validate_bounded_receipt(value)
    request_digest = digest_payload(canonical)
    lease_digest = digest_lease_token(lease_token)

    @transaction.atomic
    def finish_once() -> TerminalReceipt:
        workspace = Workspace.objects.select_for_update().get(pk=context.workspace_id)
        if workspace.machine_generation != context.machine_generation:
            raise RuntimeFencedError("runtime generation is stale")
        attempt = (
            Attempt.objects.select_for_update()
            .select_related("execution")
            .filter(pk=attempt_uuid, execution__workspace_id=workspace.id)
            .first()
        )
        if attempt is None:
            raise RuntimeLeaseConflictError("attempt is not in this workspace")
        profile = RuntimeProfile.objects.select_for_update().get(
            pk=attempt.execution.profile_id
        )
        if not profile_allows_runtime_write(profile):
            raise RuntimeLeaseConflictError("profile lifecycle is not active")
        if attempt.terminal_request_digest is not None:
            if (
                attempt.terminal_request_digest != request_digest
                or attempt.terminal_lease_digest != lease_digest
            ):
                raise RuntimeIdempotencyConflictError(
                    "terminal request conflicts with its stored receipt"
                )
            return _terminal_from_attempt(attempt)
        lease = Lease.objects.select_for_update().filter(attempt=attempt).first()
        if lease is None or lease.token_digest != lease_digest:
            raise RuntimeLeaseConflictError("lease token does not authorize attempt")
        if lease.machine_generation != workspace.machine_generation:
            raise RuntimeFencedError("lease belongs to a retired generation")
        if lease.state != LeaseState.ACTIVE:
            raise RuntimeLeaseConflictError("lease is no longer active")
        if lease.expires_at <= timezone.now():
            raise RuntimeLeaseConflictError("lease has expired")
        if attempt.status in {
            AttemptStatus.SUCCEEDED,
            AttemptStatus.FAILED,
            AttemptStatus.CANCELLED,
            AttemptStatus.UNKNOWN,
        }:
            raise RuntimeLeaseConflictError("attempt is already terminal")
        receipt_id = uuid4()
        status = terminal_status
        execution_status = (
            ExecutionStatus.QUEUED
            if retryable
            else (
                ExecutionStatus.SUCCEEDED
                if terminal_status == AttemptStatus.SUCCEEDED
                else ExecutionStatus.FAILED
            )
        )
        attempt.status = status
        attempt.terminal_request_digest = request_digest
        attempt.terminal_lease_digest = lease_digest
        attempt.terminal_receipt = canonical
        attempt.terminal_receipt_id = receipt_id
        attempt.save(
            update_fields=[
                "status",
                "terminal_request_digest",
                "terminal_lease_digest",
                "terminal_receipt",
                "terminal_receipt_id",
                "updated_at",
            ]
        )
        execution = attempt.execution
        execution.status = execution_status
        execution.save(update_fields=["status", "updated_at"])
        lease.state = LeaseState.RELEASED
        lease.save(update_fields=["state", "updated_at"])
        return TerminalReceipt(
            attempt_id=attempt.id,
            status=status,
            receipt_id=receipt_id,
            requeued=retryable,
            receipt=canonical,
        )

    return run_with_sqlite_lock_retry(finish_once)


def _terminal_from_attempt(attempt: Attempt) -> TerminalReceipt:
    if attempt.terminal_receipt_id is None or attempt.terminal_receipt is None:
        raise RuntimeLeaseConflictError("terminal receipt is unavailable")
    value = attempt.terminal_receipt
    return TerminalReceipt(
        attempt_id=attempt.id,
        status=attempt.status,
        receipt_id=attempt.terminal_receipt_id,
        requeued=bool(isinstance(value, dict) and value.get("retryable") is True),
        receipt=value,
    )


__all__ = [
    "TerminalReceipt",
    "complete_attempt",
    "fail_attempt",
]
