"""Keyed retry digests and immutable operation receipts."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

from .exceptions import IdempotencyConflict, OperationInProgress, Throttled
from .models import OperationKind, OperationStatus, WaitlistDraft, WaitlistOperation


def _digest_key() -> bytes:
    configured = str(getattr(settings, "ALLIES_WAITLIST_CAPABILITY_KEY", ""))
    if configured:
        return configured.encode()
    if getattr(settings, "DEBUG", True):
        return b"allies-local-waitlist-idempotency-key-not-for-production"
    return b""


def digest_value(value: str | bytes) -> str:
    raw = value.encode() if isinstance(value, str) else value
    return hmac.new(_digest_key(), raw, hashlib.sha256).hexdigest()


def idempotency_digest(raw_key: str) -> str:
    if not isinstance(raw_key, str) or not 1 <= len(raw_key) <= 200:
        raise ValueError("idempotency key is invalid")
    return digest_value(raw_key)


def request_digest(payload: Any) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return digest_value(canonical)


@dataclass(frozen=True)
class Acknowledgement:
    operation: str
    result_revision: int
    result_lifecycle: str


def acknowledgement(operation: WaitlistOperation) -> Acknowledgement:
    return Acknowledgement(
        operation=(
            operation.kind.value if hasattr(operation.kind, "value") else operation.kind
        ),
        result_revision=int(operation.result_revision or 0),
        result_lifecycle=(
            operation.result_lifecycle.value
            if hasattr(operation.result_lifecycle, "value")
            else operation.result_lifecycle
        ),
    )


def reserve_operation(
    *,
    draft: WaitlistDraft,
    kind: OperationKind | str,
    raw_key: str,
    payload: Any,
    lease_seconds: int = 30,
) -> tuple[WaitlistOperation, bool]:
    """Reserve one receipt, returning ``(receipt, replay)``.

    Callers must hold a row lock on ``draft``.  Unknown provider outcomes remain
    terminal and are handled by the generation service with an explicit new key.
    """

    kind_value = kind.value if isinstance(kind, OperationKind) else str(kind)
    digest = idempotency_digest(raw_key)
    payload_digest = request_digest(payload)
    existing = (
        WaitlistOperation.objects.select_for_update()
        .filter(draft=draft, kind=kind_value, idempotency_digest=digest)
        .first()
    )
    now = timezone.now()
    if existing is not None:
        if existing.request_digest != payload_digest:
            raise IdempotencyConflict("idempotency key was reused")
        if existing.status == OperationStatus.IN_PROGRESS:
            if existing.lease_expires_at and existing.lease_expires_at > now:
                raise OperationInProgress("waitlist operation is in progress")
            if kind_value == OperationKind.GENERATE.value:
                # A crashed/expired generation lease is ambiguous: the
                # provider may have accepted the request.  Never re-use the
                # same key or silently spend twice.
                mark_unknown(existing)
                return existing, True
            existing.lease_expires_at = now + timedelta(seconds=lease_seconds)
            existing.save(update_fields=("lease_expires_at", "updated_at"))
            return existing, False
        return existing, True

    # Every mutating endpoint reserves a durable receipt before it changes the
    # draft.  The draft row lock held by each service serializes both the hard
    # total and per-kind quotas, bounding fresh-key growth without letting
    # configuration/generation retries consume reply/join headroom.
    receipt_cap = int(getattr(settings, "ALLIES_WAITLIST_OPERATION_RECEIPT_CAP", 64))
    receipt_caps = getattr(settings, "ALLIES_WAITLIST_OPERATION_RECEIPT_CAPS", {})
    kind_cap = int(receipt_caps.get(kind_value, 1))
    draft_operations = WaitlistOperation.objects.filter(draft=draft)
    if (
        draft_operations.count() >= receipt_cap
        or draft_operations.filter(kind=kind_value).count() >= kind_cap
    ):
        raise Throttled("waitlist operation receipt limit reached")

    operation = WaitlistOperation.objects.create(
        draft=draft,
        kind=kind_value,
        idempotency_digest=digest,
        request_digest=payload_digest,
        status=OperationStatus.IN_PROGRESS,
        lease_expires_at=now + timedelta(seconds=lease_seconds),
    )
    return operation, False


def mark_succeeded(
    operation: WaitlistOperation, *, revision: int, lifecycle: str
) -> Acknowledgement:
    lifecycle_value = lifecycle.value if hasattr(lifecycle, "value") else lifecycle
    operation.status = OperationStatus.SUCCEEDED
    operation.lease_expires_at = None
    operation.result_revision = revision
    operation.result_lifecycle = lifecycle_value
    operation.failure_code = ""
    operation.completed_at = timezone.now()
    operation.save(
        update_fields=(
            "status",
            "lease_expires_at",
            "result_revision",
            "result_lifecycle",
            "failure_code",
            "completed_at",
            "updated_at",
        )
    )
    return acknowledgement(operation)


def mark_failed(operation: WaitlistOperation, *, failure_code: str) -> None:
    operation.status = OperationStatus.FAILED
    operation.lease_expires_at = None
    operation.result_revision = None
    operation.result_lifecycle = ""
    operation.failure_code = failure_code[:64]
    operation.completed_at = timezone.now()
    operation.save(
        update_fields=(
            "status",
            "lease_expires_at",
            "result_revision",
            "result_lifecycle",
            "failure_code",
            "completed_at",
            "updated_at",
        )
    )


def mark_unknown(operation: WaitlistOperation) -> None:
    operation.status = OperationStatus.OUTCOME_UNKNOWN
    operation.lease_expires_at = None
    operation.result_revision = None
    operation.result_lifecycle = ""
    operation.failure_code = "generation_outcome_unknown"
    operation.completed_at = timezone.now()
    operation.save(
        update_fields=(
            "status",
            "lease_expires_at",
            "result_revision",
            "result_lifecycle",
            "failure_code",
            "completed_at",
            "updated_at",
        )
    )
