"""Truthful pending-reply persistence with no downstream side effect."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from ..exceptions import (
    DraftStale,
    DraftUnavailable,
    InvalidDraftState,
    WaitlistValidationError,
)
from ..idempotency import acknowledgement, mark_succeeded, reserve_operation
from ..models import DraftLifecycle, OperationKind, WaitlistDraft
from .drafts import abandoned_expiry, ensure_active

MAX_REPLY = 4_000


def record_reply(*, capability_digest: str, revision: int, text: str, raw_key: str):
    if not isinstance(text, str) or not text or len(text) > MAX_REPLY or "\x00" in text:
        raise WaitlistValidationError("reply is invalid", field="text")
    payload = {"revision": revision, "text": text}
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
            kind=OperationKind.REPLY.value,
            raw_key=raw_key,
            payload=payload,
        )
        if replay:
            return acknowledgement(operation)
        if draft.revision != revision:
            operation.delete()
            raise DraftStale("draft revision is stale")
        if draft.lifecycle != DraftLifecycle.GREETING_READY:
            operation.delete()
            raise InvalidDraftState("reply is not currently available")
        draft.reply_text = text
        draft.reply_recorded_at = timezone.now()
        draft.lifecycle = DraftLifecycle.REPLY_PENDING
        draft.expires_at = abandoned_expiry()
        draft.revision += 1
        draft.save()
        return mark_succeeded(
            operation, revision=draft.revision, lifecycle=draft.lifecycle
        )
