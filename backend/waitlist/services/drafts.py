"""Create, restore, and compare-and-set configuration services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from ..admission import admit_global_creation
from ..exceptions import (
    DraftStale,
    DraftUnavailable,
    InvalidDraftState,
    WaitlistValidationError,
)
from ..idempotency import (
    Acknowledgement,
    acknowledgement,
    mark_succeeded,
    reserve_operation,
)
from ..models import DraftLifecycle, OperationKind, OperationStatus, WaitlistDraft

MAX_NAME = 80
MAX_JOB = 1_200
MAX_PERSONALITY = 1_200
MAX_APPEARANCE_VERSION = 32
MAX_APPEARANCE_KEY = 128


@dataclass(frozen=True)
class DraftSnapshot:
    id: str
    revision: int
    lifecycle: str
    configuration: dict[str, str]
    greeting: dict[str, Any] | None
    reply: dict[str, Any] | None
    join: dict[str, Any] | None
    timestamps: dict[str, Any]


def _clean_text(value: Any, *, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise WaitlistValidationError(f"{field} is invalid", field=field)
    value = value.strip()
    if len(value) > max_length or "\x00" in value:
        raise WaitlistValidationError(f"{field} is invalid", field=field)
    return value


def validate_configuration(changes: dict[str, Any]) -> dict[str, str]:
    if not isinstance(changes, dict) or not changes:
        raise WaitlistValidationError("configuration is empty", field="configuration")
    allowed = {
        "name": (MAX_NAME, False),
        "appearance_catalog_version": (MAX_APPEARANCE_VERSION, False),
        "appearance_key": (MAX_APPEARANCE_KEY, False),
        "job": (MAX_JOB, False),
        "personality": (MAX_PERSONALITY, False),
    }
    unknown = set(changes) - set(allowed)
    if unknown:
        raise WaitlistValidationError(
            "configuration field is invalid", field="configuration"
        )
    cleaned: dict[str, str] = {}
    for field, raw in changes.items():
        cleaned[field] = _clean_text(raw, field=field, max_length=allowed[field][0])
    if ("appearance_catalog_version" in cleaned) != ("appearance_key" in cleaned):
        raise WaitlistValidationError(
            "appearance selection is incomplete", field="appearance"
        )
    return cleaned


def configuration_complete(draft: WaitlistDraft) -> bool:
    # Personality is intentionally editable but optional; the provider can
    # truthfully personalize from name and job alone.
    return bool(
        draft.name
        and draft.job
        and draft.appearance_catalog_version
        and draft.appearance_key
    )


def abandoned_expiry(*, now=None):
    now = now or timezone.now()
    return now + timedelta(
        seconds=int(
            getattr(
                settings,
                "ALLIES_WAITLIST_ABANDONED_RETENTION_SECONDS",
                7 * 24 * 60 * 60,
            )
        )
    )


def ensure_active(draft: WaitlistDraft) -> None:
    if draft.lifecycle == DraftLifecycle.EXPIRED or (
        draft.expires_at is not None and draft.expires_at <= timezone.now()
    ):
        raise DraftUnavailable("waitlist draft unavailable")


def _clear_greeting(draft: WaitlistDraft) -> None:
    draft.generation_input_digest = ""
    draft.greeting_text = ""
    draft.greeting_policy_version = ""
    draft.greeting_generated_at = None


def _ack(draft: WaitlistDraft, operation) -> Acknowledgement:
    return mark_succeeded(operation, revision=draft.revision, lifecycle=draft.lifecycle)


def create_or_resume_draft(*, capability_digest: str, raw_key: str) -> Acknowledgement:
    """Create one capability-bound draft or replay its immutable receipt."""

    if not capability_digest:
        raise DraftUnavailable("waitlist draft unavailable")
    payload: dict[str, Any] = {}
    with transaction.atomic():
        draft = (
            WaitlistDraft.objects.select_for_update()
            .filter(capability_digest=capability_digest)
            .first()
        )
        if draft is None:
            try:
                # Keep the uniqueness race inside a savepoint so a losing
                # concurrent insert does not poison the surrounding
                # transaction on PostgreSQL.
                with transaction.atomic():
                    draft = WaitlistDraft.objects.create(
                        capability_digest=capability_digest,
                        expires_at=abandoned_expiry(),
                    )
                    # Admit only the transaction that actually inserted the
                    # draft.  A concurrent loser rolls back at the unique
                    # constraint and must not burn a global token for a row
                    # that it did not create.
                    admit_global_creation()
            except IntegrityError:
                draft = WaitlistDraft.objects.select_for_update().get(
                    capability_digest=capability_digest
                )
        ensure_active(draft)
        # A capability has one immutable create acknowledgement.  Returning
        # that receipt for later keys keeps an existing draft resumable without
        # allowing unbounded create-operation rows to accumulate.
        canonical_create = (
            draft.operations.filter(
                kind=OperationKind.CREATE.value,
                status=OperationStatus.SUCCEEDED.value,
            )
            .order_by("id")
            .first()
        )
        if canonical_create is not None:
            return acknowledgement(canonical_create)
        operation, replay = reserve_operation(
            draft=draft,
            kind=OperationKind.CREATE.value,
            raw_key=raw_key,
            payload=payload,
        )
        if replay:
            if operation.status == "failed":
                raise DraftUnavailable("waitlist draft unavailable")
            return acknowledgement(operation)
        return _ack(draft, operation)


def get_draft(*, capability_digest: str) -> WaitlistDraft:
    if not capability_digest:
        raise DraftUnavailable("waitlist draft unavailable")
    draft = WaitlistDraft.objects.filter(capability_digest=capability_digest).first()
    if draft is None:
        raise DraftUnavailable("waitlist draft unavailable")
    ensure_active(draft)
    return draft


def revoke_expired_capability(*, capability_digest: str, force: bool = False) -> bool:
    """Revoke an expired browser binding before issuing a replacement cookie.

    A joined draft keeps its pending-claim lifecycle and retention deadline;
    only the stale browser binding is removed.  Unjoined drafts become
    expired because replacing their only browser credential makes them
    unreachable by design.
    """

    if not capability_digest:
        return False
    with transaction.atomic():
        draft = (
            WaitlistDraft.objects.select_for_update()
            .filter(capability_digest=capability_digest)
            .first()
        )
        if draft is None:
            return False
        if not force and not (
            draft.lifecycle == DraftLifecycle.EXPIRED
            or (draft.expires_at is not None and draft.expires_at <= timezone.now())
        ):
            return False
        update_fields = ["capability_digest", "updated_at"]
        if draft.joined_at is None:
            draft.lifecycle = DraftLifecycle.EXPIRED
            update_fields.insert(0, "lifecycle")
        draft.capability_digest = None
        draft.save(update_fields=update_fields)
        return True


def update_configuration(
    *, capability_digest: str, revision: int, changes: dict[str, Any], raw_key: str
) -> Acknowledgement:
    cleaned = validate_configuration(changes)
    payload = {"revision": revision, **cleaned}
    with transaction.atomic():
        try:
            draft = WaitlistDraft.objects.select_for_update().get(
                capability_digest=capability_digest
            )
        except WaitlistDraft.DoesNotExist as exc:
            raise DraftUnavailable("waitlist draft unavailable") from exc
        ensure_active(draft)
        if draft.lifecycle in {
            DraftLifecycle.REPLY_PENDING,
            DraftLifecycle.PENDING_CLAIM,
            DraftLifecycle.CLAIMED,
            DraftLifecycle.EXPIRED,
        }:
            raise InvalidDraftState("configuration is closed")
        operation, replay = reserve_operation(
            draft=draft,
            kind=OperationKind.CONFIGURE.value,
            raw_key=raw_key,
            payload=payload,
        )
        if replay:
            return acknowledgement(operation)
        if draft.revision != revision:
            # Do not consume a key for stale input: the caller can safely retry
            # with a new revision and the same intent.
            operation.delete()
            raise DraftStale("draft revision is stale")
        prior_generation_input = (
            draft.name,
            draft.job,
            draft.personality,
        )
        prior_appearance = (draft.appearance_catalog_version, draft.appearance_key)
        for field, value in cleaned.items():
            setattr(draft, field, value)
        new_generation_input = (draft.name, draft.job, draft.personality)
        if new_generation_input != prior_generation_input:
            _clear_greeting(draft)
        if prior_appearance != (
            draft.appearance_catalog_version,
            draft.appearance_key,
        ) and not configuration_complete(draft):
            _clear_greeting(draft)
        if draft.greeting_text and configuration_complete(draft):
            draft.lifecycle = DraftLifecycle.GREETING_READY
        else:
            draft.lifecycle = (
                DraftLifecycle.READY_FOR_GREETING
                if configuration_complete(draft)
                else DraftLifecycle.CONFIGURING
            )
        draft.revision += 1
        draft.expires_at = abandoned_expiry()
        draft.save()
        return _ack(draft, operation)


def snapshot_for(draft: WaitlistDraft) -> DraftSnapshot:
    greeting = None
    if draft.greeting_text:
        greeting = {
            "text": draft.greeting_text,
            "policy_version": draft.greeting_policy_version,
            "generated_at": draft.greeting_generated_at,
        }
    reply = None
    if draft.reply_text:
        reply = {
            "text": draft.reply_text,
            "status": "pending",
            "recorded_at": draft.reply_recorded_at,
        }
    joined = None
    if draft.joined_at and draft.email_normalized:
        from .join import mask_email

        joined = {
            "email": mask_email(draft.email_normalized),
            "joined_at": draft.joined_at,
        }
    return DraftSnapshot(
        id=draft.public_id,
        revision=draft.revision,
        lifecycle=draft.lifecycle,
        configuration={
            "name": draft.name,
            "appearance_catalog_version": draft.appearance_catalog_version,
            "appearance_key": draft.appearance_key,
            "job": draft.job,
            "personality": draft.personality,
        },
        greeting=greeting,
        reply=reply,
        join=joined,
        timestamps={
            "created_at": draft.created_at,
            "updated_at": draft.updated_at,
            "generated_at": draft.greeting_generated_at,
            "replied_at": draft.reply_recorded_at,
            "joined_at": draft.joined_at,
            "expires_at": draft.expires_at,
        },
    )
