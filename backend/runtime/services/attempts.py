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
from .validation import (
    MAX_EVENT_PAYLOAD_BYTES,
    digest_lease_token,
    digest_payload,
    validate_bounded_receipt,
    validate_nonempty,
    validate_object_payload,
)


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
    *,
    terminal_event: dict | None = None,
) -> TerminalReceipt:
    return _finish_attempt(
        context,
        attempt_id,
        lease_token,
        receipt,
        retryable=False,
        terminal_status=AttemptStatus.SUCCEEDED,
        terminal_event=_terminal_event(terminal_event, "execution.completed"),
    )


def fail_attempt(
    context: RuntimeContext,
    attempt_id: UUID,
    lease_token: str,
    failure: dict,
    *,
    terminal_event: dict | None = None,
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
    normalized_terminal_event = _terminal_event(terminal_event, "execution.failed")
    if retryable and normalized_terminal_event is not None:
        raise RuntimeValidationError(
            "terminal failure events cannot request automatic replay"
        )
    return _finish_attempt(
        context,
        attempt_id,
        lease_token,
        {"code": code, "retryable": retryable, "receipt": receipt},
        retryable=retryable,
        terminal_status=AttemptStatus.FAILED,
        terminal_event=normalized_terminal_event,
    )


def _finish_attempt(
    context: RuntimeContext,
    attempt_id: UUID,
    lease_token: str,
    value: dict,
    *,
    retryable: bool,
    terminal_status: str,
    terminal_event: dict | None,
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
    request_value = (
        canonical
        if terminal_event is None
        else {"terminal": canonical, "terminal_event": terminal_event}
    )
    request_digest = digest_payload(request_value)
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
        if terminal_status == AttemptStatus.SUCCEEDED and terminal_event is not None:
            session_receipt = attempt.session_receipt or {}
            if (
                not isinstance(session_receipt.get("session_id"), str)
                or attempt.session_lease_digest != lease_digest
            ):
                raise RuntimeLeaseConflictError(
                    "effective session receipt is required before completion"
                )
        if attempt.status in {
            AttemptStatus.SUCCEEDED,
            AttemptStatus.FAILED,
            AttemptStatus.CANCELLED,
            AttemptStatus.UNKNOWN,
        }:
            raise RuntimeLeaseConflictError("attempt is already terminal")
        if terminal_event is not None:
            from .events import _append_event_once

            _append_event_once(
                attempt.id,
                lease.id,
                terminal_event["event_id"],
                terminal_event["sequence"],
                terminal_event["type"],
                terminal_event["payload"],
                token_digest=lease_digest,
                machine_generation=context.machine_generation,
                stream_id=terminal_event["stream_id"],
            )
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


def _terminal_event(value: dict | None, event_type: str) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RuntimeValidationError("terminal_event must be an object")
    try:
        event_id = UUID(str(value.get("event_id")))
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError("terminal event_id must be a UUID") from exc
    stream_id = validate_nonempty(
        value.get("stream_id"), "terminal stream_id", max_length=255
    )
    sequence = value.get("sequence")
    if (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or not 1 <= sequence <= 513
    ):
        raise RuntimeValidationError(
            "terminal sequence must be an integer from 1 to 513"
        )
    payload = validate_object_payload(
        value.get("payload"), max_bytes=MAX_EVENT_PAYLOAD_BYTES
    )
    if event_type == "execution.completed":
        if set(payload) != {"run_id", "status"} or payload.get("status") != "completed":
            raise RuntimeValidationError("completion event payload is invalid")
        validate_nonempty(payload.get("run_id"), "terminal run_id", max_length=128)
    elif event_type == "execution.failed":
        if (
            set(payload) != {"code", "retryable"}
            or type(payload.get("retryable")) is not bool
        ):
            raise RuntimeValidationError("failure event payload is invalid")
        validate_nonempty(payload.get("code"), "terminal code", max_length=64)
    return {
        "event_id": str(event_id),
        "stream_id": stream_id,
        "sequence": sequence,
        "type": event_type,
        "payload": payload,
    }


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
