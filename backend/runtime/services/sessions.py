from __future__ import annotations

from uuid import UUID

from django.db import IntegrityError, transaction

from runtime.exceptions import RuntimeConflictError, RuntimeValidationError
from runtime.models import ConversationBinding, RuntimeProfile

from .retry import run_with_sqlite_lock_retry
from .validation import validate_nonempty


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
        RuntimeProfile.objects.select_for_update().get(pk=profile_id)
    except RuntimeProfile.DoesNotExist as exc:
        raise RuntimeValidationError("profile does not exist") from exc

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
