from __future__ import annotations

from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from runtime.exceptions import (
    RuntimeConflictError,
    RuntimeFencedError,
    RuntimeIdempotencyConflictError,
    RuntimeLeaseConflictError,
    RuntimeValidationError,
)
from runtime.models import (
    Attempt,
    ConversationBinding,
    Lease,
    LeaseState,
    RuntimeProfile,
    Workspace,
)

from .profiles import profile_allows_runtime_write
from .retry import run_with_sqlite_lock_retry
from .validation import digest_payload, validate_nonempty


def update_session_binding(
    context,
    attempt_id: UUID,
    lease_token: str,
    cloud_conversation_ref: str,
    expected_session_id: str | None,
    effective_session_id: str,
) -> ConversationBinding:
    """Authorize a session CAS through Workspace -> Profile -> Attempt -> Lease."""

    from .leases import digest_lease_token
    from .runtime_auth import RuntimeContext

    if not isinstance(context, RuntimeContext):
        raise RuntimeValidationError("runtime context is required")
    validate_nonempty(cloud_conversation_ref, "cloud_conversation_ref", max_length=255)
    validate_nonempty(effective_session_id, "effective_session_id", max_length=255)
    if expected_session_id is not None:
        validate_nonempty(expected_session_id, "expected_session_id", max_length=255)
    try:
        attempt_uuid = UUID(str(attempt_id))
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError("attempt_id must be a UUID") from exc
    token_digest = digest_lease_token(lease_token)
    request_digest = digest_payload(
        {
            "cloud_conversation_ref": cloud_conversation_ref,
            "expected_session_id": expected_session_id,
            "effective_session_id": effective_session_id,
        }
    )

    @transaction.atomic
    def update_once() -> ConversationBinding:
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
        lease = Lease.objects.select_for_update().filter(attempt=attempt).first()
        if lease is None or lease.token_digest != token_digest:
            raise RuntimeLeaseConflictError("lease token does not authorize attempt")
        if attempt.session_request_digest is not None:
            if (
                attempt.session_request_digest != request_digest
                or attempt.session_lease_digest != token_digest
            ):
                raise RuntimeIdempotencyConflictError(
                    "session binding request conflicts with its stored receipt"
                )
            binding = (
                ConversationBinding.objects.select_for_update()
                .filter(profile_id=profile.id)
                .first()
            )
            stored_receipt = attempt.session_receipt or {}
            stored_session_id = stored_receipt.get("session_id")
            if binding is None or not isinstance(stored_session_id, str):
                raise RuntimeLeaseConflictError(
                    "session binding receipt is unavailable"
                )
            # Return the value committed by this attempt, not the profile's
            # later current value.  A delayed response replay must be stable.
            return ConversationBinding(
                profile_id=profile.id,
                cloud_conversation_ref=binding.cloud_conversation_ref,
                hermes_session_id=stored_session_id,
            )
        if lease.machine_generation != workspace.machine_generation:
            raise RuntimeFencedError("lease belongs to a retired generation")
        if lease.state != LeaseState.ACTIVE:
            raise RuntimeLeaseConflictError("lease is no longer active")
        if lease.expires_at <= timezone.now():
            raise RuntimeLeaseConflictError("lease has expired")
        binding = (
            ConversationBinding.objects.select_for_update()
            .filter(profile_id=profile.id)
            .first()
        )
        if binding is None:
            if expected_session_id is not None:
                raise RuntimeLeaseConflictError("session binding does not exist")
            try:
                binding = ConversationBinding.objects.create(
                    profile=profile,
                    cloud_conversation_ref=cloud_conversation_ref,
                    hermes_session_id=effective_session_id,
                )
                _store_session_receipt(
                    attempt, request_digest, token_digest, effective_session_id
                )
                return binding
            except IntegrityError as exc:
                raise RuntimeLeaseConflictError(
                    "conversation binding conflicts with existing state"
                ) from exc
        if binding.cloud_conversation_ref != cloud_conversation_ref:
            raise RuntimeLeaseConflictError("profile is bound to another conversation")
        if binding.hermes_session_id == effective_session_id:
            _store_session_receipt(
                attempt, request_digest, token_digest, effective_session_id
            )
            return binding
        if expected_session_id != binding.hermes_session_id:
            raise RuntimeLeaseConflictError("session binding is stale")
        binding.hermes_session_id = effective_session_id
        binding.save(update_fields=["hermes_session_id", "updated_at"])
        _store_session_receipt(
            attempt, request_digest, token_digest, effective_session_id
        )
        return binding

    return run_with_sqlite_lock_retry(update_once)


def _store_session_receipt(
    attempt: Attempt,
    request_digest: str,
    lease_digest: str,
    session_id: str,
) -> None:
    attempt.session_request_digest = request_digest
    attempt.session_lease_digest = lease_digest
    attempt.session_receipt = {"session_id": session_id}
    attempt.save(
        update_fields=[
            "session_request_digest",
            "session_lease_digest",
            "session_receipt",
            "updated_at",
        ]
    )


def compare_and_set_session(
    profile_id: UUID,
    expected_session_id: str | None,
    new_session_id: str,
    *,
    cloud_conversation_ref: str | None = None,
) -> ConversationBinding:
    """Bind or rotate a profile session using an optimistic compare-and-set."""

    validate_nonempty(new_session_id, "new_session_id", max_length=255)
    if expected_session_id is not None:
        validate_nonempty(expected_session_id, "expected_session_id", max_length=255)
    if cloud_conversation_ref is not None:
        validate_nonempty(
            cloud_conversation_ref,
            "cloud_conversation_ref",
            max_length=255,
        )
    return run_with_sqlite_lock_retry(
        lambda: _compare_and_set_session_once(
            profile_id,
            expected_session_id,
            new_session_id,
            cloud_conversation_ref=cloud_conversation_ref,
        )
    )


@transaction.atomic
def _compare_and_set_session_once(
    profile_id: UUID,
    expected_session_id: str | None,
    new_session_id: str,
    *,
    cloud_conversation_ref: str | None,
) -> ConversationBinding:

    try:
        profile = RuntimeProfile.objects.select_for_update().get(pk=profile_id)
    except RuntimeProfile.DoesNotExist as exc:
        raise RuntimeValidationError("profile does not exist") from exc
    if not profile_allows_runtime_write(profile):
        raise RuntimeConflictError("profile lifecycle is not active")

    binding = (
        ConversationBinding.objects.select_for_update()
        .filter(profile_id=profile_id)
        .first()
    )
    if binding is None:
        if expected_session_id is not None:
            raise RuntimeConflictError("session binding does not exist")
        if cloud_conversation_ref is None:
            raise RuntimeValidationError(
                "cloud_conversation_ref is required for the first bind"
            )
        try:
            with transaction.atomic():
                return ConversationBinding.objects.create(
                    profile_id=profile_id,
                    cloud_conversation_ref=cloud_conversation_ref,
                    hermes_session_id=new_session_id,
                )
        except IntegrityError as exc:
            # A conversation reference may already belong to another profile.
            raise RuntimeConflictError(
                "conversation binding conflicts with existing state"
            ) from exc

    if (
        cloud_conversation_ref is not None
        and binding.cloud_conversation_ref != cloud_conversation_ref
    ):
        raise RuntimeConflictError("profile is bound to another conversation")
    if binding.hermes_session_id == new_session_id:
        return binding
    if expected_session_id is None:
        if binding.hermes_session_id:
            raise RuntimeConflictError("session binding is already initialized")
    elif binding.hermes_session_id != expected_session_id:
        raise RuntimeConflictError("session binding is stale")
    if binding.hermes_session_id == new_session_id:
        return binding

    binding.hermes_session_id = new_session_id
    binding.save(update_fields=["hermes_session_id", "updated_at"])
    return binding


def bind_conversation(
    profile_id: UUID,
    cloud_conversation_ref: str,
    hermes_session_id: str,
) -> ConversationBinding:
    """Create the initial one-to-one conversation/session binding."""

    return compare_and_set_session(
        profile_id,
        None,
        hermes_session_id,
        cloud_conversation_ref=cloud_conversation_ref,
    )
