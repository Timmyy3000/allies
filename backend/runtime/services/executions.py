from __future__ import annotations

from uuid import UUID

from django.db import IntegrityError, transaction

from runtime.exceptions import RuntimeConflictError, RuntimeValidationError
from runtime.models import Execution, RuntimeProfile

from .retry import run_with_sqlite_lock_retry
from .validation import (
    MAX_EXECUTION_PAYLOAD_BYTES,
    digest_payload,
    validate_nonempty,
    validate_object_payload,
)


def create_execution(
    workspace_id: UUID,
    profile_id: UUID,
    idempotency_key: str,
    input_payload: dict,
) -> Execution:
    """Create one workspace-scoped execution, safely replaying exact retries."""

    validate_nonempty(idempotency_key, "idempotency_key", max_length=255)
    payload = validate_object_payload(
        input_payload,
        max_bytes=MAX_EXECUTION_PAYLOAD_BYTES,
    )
    payload_digest = digest_payload(payload)
    try:
        profile = RuntimeProfile.objects.select_related("workspace").get(pk=profile_id)
    except RuntimeProfile.DoesNotExist as exc:
        raise RuntimeValidationError("profile does not exist") from exc
    if profile.workspace_id != workspace_id:
        raise RuntimeValidationError("profile does not belong to workspace")
    return run_with_sqlite_lock_retry(
        lambda: _create_execution_once(
            workspace_id,
            profile_id,
            idempotency_key,
            payload,
            payload_digest,
        )
    )


@transaction.atomic
def _create_execution_once(
    workspace_id: UUID,
    profile_id: UUID,
    idempotency_key: str,
    payload: dict,
    payload_digest: str,
) -> Execution:
    try:
        with transaction.atomic():
            return Execution.objects.create(
                workspace_id=workspace_id,
                profile_id=profile_id,
                idempotency_key=idempotency_key,
                input_payload=payload,
                payload_digest=payload_digest,
            )
    except IntegrityError:
        # Another transaction won the unique workspace/key race. Re-read it
        # under the outer transaction and apply the same exact-retry rule.
        existing = (
            Execution.objects.select_for_update()
            .filter(workspace_id=workspace_id, idempotency_key=idempotency_key)
            .first()
        )
        if existing is None:
            raise
        _ensure_exact_retry(existing, profile_id, payload_digest)
        return existing


def _ensure_exact_retry(
    existing: Execution,
    profile_id: UUID,
    payload_digest: str,
) -> None:
    if (
        existing.profile_id != profile_id
        or _stored_payload_digest(existing) != payload_digest
    ):
        raise RuntimeConflictError(
            "idempotency key already identifies a different execution"
        )


def _stored_payload_digest(existing: Execution) -> str:
    if existing.payload_digest:
        return existing.payload_digest
    digest = digest_payload(existing.input_payload)
    existing.payload_digest = digest
    existing.save(update_fields=["payload_digest"])
    return digest
