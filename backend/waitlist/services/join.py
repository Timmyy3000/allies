"""Join persistence and privacy-safe email masking."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..exceptions import (
    DraftStale,
    DraftUnavailable,
    InvalidDraftState,
    WaitlistUnavailable,
    WaitlistValidationError,
)
from ..idempotency import acknowledgement, mark_succeeded, reserve_operation
from ..models import DraftLifecycle, OperationKind, WaitlistDraft
from .drafts import ensure_active
from .email import normalize_email


def mask_email(value: str) -> str:
    normalized = normalize_email(value)
    local, domain = normalized.split("@", 1)
    if len(local) <= 1:
        masked_local = "*"
    elif len(local) == 2:
        masked_local = local[0] + "*"
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}"


def join_waitlist(
    *,
    capability_digest: str,
    revision: int,
    email: str,
    consent_version: str,
    raw_key: str,
):
    normalized_email = normalize_email(email)
    payload = {
        "revision": revision,
        "email": normalized_email,
        "consent_version": consent_version,
    }
    with transaction.atomic():
        try:
            draft = WaitlistDraft.objects.select_for_update().get(
                capability_digest=capability_digest
            )
        except WaitlistDraft.DoesNotExist as exc:
            raise DraftUnavailable("waitlist draft unavailable") from exc
        ensure_active(draft)
        operation, replay = reserve_operation(
            draft=draft,
            kind=OperationKind.JOIN.value,
            raw_key=raw_key,
            payload=payload,
        )
        if replay:
            return acknowledgement(operation)
        active_consent = str(getattr(settings, "ALLIES_WAITLIST_CONSENT_VERSION", ""))
        joined_retention = getattr(
            settings, "ALLIES_WAITLIST_JOINED_RETENTION_SECONDS", None
        )
        if not active_consent or joined_retention is None:
            raise WaitlistUnavailable("waitlist release policy is unavailable")
        if consent_version != active_consent:
            # The surrounding transaction rolls back the fresh receipt so a
            # corrected new request can use the key safely.
            raise WaitlistValidationError(
                "consent version is invalid", field="consent_version"
            )
        if draft.revision != revision:
            operation.delete()
            raise DraftStale("draft revision is stale")
        if draft.lifecycle != DraftLifecycle.REPLY_PENDING:
            operation.delete()
            raise InvalidDraftState("draft cannot join yet")
        now = timezone.now()
        draft.email_normalized = normalized_email
        draft.consent_version = consent_version
        draft.joined_at = now
        draft.lifecycle = DraftLifecycle.PENDING_CLAIM
        draft.expires_at = now + timedelta(seconds=int(joined_retention))
        draft.revision += 1
        draft.save()
        return mark_succeeded(
            operation, revision=draft.revision, lifecycle=draft.lifecycle
        )
