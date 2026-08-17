"""Disposable two-request waitlist entry flow."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..admission import acquire_generation, release_generation
from ..exceptions import (
    AdmissionUnavailable,
    EntryUnavailable,
    GenerationUnavailable,
    InvalidEntryState,
    Throttled,
    WaitlistUnavailable,
    WaitlistValidationError,
)
from ..models import WaitlistEntry
from ..providers.base import (
    GreetingRequest,
    ProviderUnavailableError,
    ProviderUnknownError,
)
from ..providers.openai import POLICY_VERSION
from .email import mask_email, normalize_email
from .generation import get_provider, validate_output

GENERATION_LEASE = timedelta(seconds=45)


@dataclass(frozen=True)
class CreatedEntry:
    attempt_token: str
    greeting: str


def _key() -> bytes:
    value = str(getattr(settings, "ALLIES_WAITLIST_TOKEN_KEY", ""))
    if not value:
        raise WaitlistUnavailable("waitlist release policy is unavailable")
    return value.encode()


def _digest(value: str) -> str:
    return hmac.new(_key(), value.encode(), hashlib.sha256).hexdigest()


def _attempt_token(attempt_id: str) -> str:
    return hmac.new(
        _key(), f"attempt-token:{attempt_id}".encode(), hashlib.sha256
    ).hexdigest()


def _completion_digest(*, reply: str, email: str, consent_version: str) -> str:
    payload = json.dumps(
        {"reply": reply, "email": email, "consent_version": consent_version},
        sort_keys=True,
        separators=(",", ":"),
    )
    return _digest(payload)


def create_entry(
    *,
    attempt_id: str,
    name: str,
    appearance_catalog_version: str,
    appearance_key: str,
    job: str,
    personality: str,
    generation_identity: str,
    provider=None,
) -> CreatedEntry:
    attempt_digest = _digest(attempt_id)
    token = _attempt_token(attempt_id)
    now = timezone.now()
    with transaction.atomic():
        entry, created = WaitlistEntry.objects.select_for_update().get_or_create(
            attempt_id_digest=attempt_digest,
            defaults={
                "attempt_token_digest": _digest(token),
                "name": name.strip(),
                "appearance_catalog_version": appearance_catalog_version.strip(),
                "appearance_key": appearance_key.strip(),
                "job": job.strip(),
                "personality": personality.strip(),
                "generation_claimed_at": now,
                "expires_at": now
                + timedelta(
                    seconds=int(
                        getattr(
                            settings,
                            "ALLIES_WAITLIST_ABANDONED_RETENTION_SECONDS",
                            7 * 24 * 60 * 60,
                        )
                    )
                ),
            },
        )
        if not created:
            expected = (
                name.strip(),
                appearance_catalog_version.strip(),
                appearance_key.strip(),
                job.strip(),
                personality.strip(),
            )
            actual = (
                entry.name,
                entry.appearance_catalog_version,
                entry.appearance_key,
                entry.job,
                entry.personality,
            )
            if actual != expected:
                raise WaitlistValidationError(
                    "attempt id was reused", field="attempt_id"
                )
            if entry.greeting_text:
                return CreatedEntry(attempt_token=token, greeting=entry.greeting_text)
            if (
                entry.generation_claimed_at
                and entry.generation_claimed_at > now - GENERATION_LEASE
            ):
                raise InvalidEntryState("waitlist entry is still being prepared")
            entry.generation_claimed_at = now
            entry.save(update_fields=["generation_claimed_at", "updated_at"])

    lease = None
    try:
        lease = acquire_generation(generation_identity)
        output = (provider or get_provider()).generate(
            GreetingRequest(job=job.strip(), personality=personality.strip())
        )
        greeting = validate_output(output, ally_name=name.strip())
    except (AdmissionUnavailable, GenerationUnavailable, Throttled):
        with transaction.atomic():
            WaitlistEntry.objects.filter(attempt_id_digest=attempt_digest).update(
                generation_claimed_at=None
            )
        raise
    except ProviderUnknownError as exc:
        raise GenerationUnavailable("generation outcome unknown") from exc
    except (ProviderUnavailableError, WaitlistValidationError) as exc:
        with transaction.atomic():
            WaitlistEntry.objects.filter(attempt_id_digest=attempt_digest).update(
                generation_claimed_at=None
            )
        raise GenerationUnavailable("generation unavailable") from exc
    finally:
        if lease is not None:
            release_generation(lease)

    with transaction.atomic():
        entry = WaitlistEntry.objects.select_for_update().get(
            attempt_id_digest=attempt_digest
        )
        if entry.greeting_text:
            greeting = entry.greeting_text
        else:
            entry.greeting_text = greeting
            entry.greeting_policy_version = POLICY_VERSION
            entry.greeting_generated_at = timezone.now()
            entry.generation_claimed_at = None
            entry.save()
        if created:
            entry.attempt_token_digest = _digest(token)
            entry.save(update_fields=["attempt_token_digest", "updated_at"])
        return CreatedEntry(attempt_token=token, greeting=greeting)


def complete_entry(
    *, attempt_token: str, reply: str, email: str, consent_version: str
) -> str:
    normalized_email = normalize_email(email)
    normalized_reply = reply.strip()
    if not normalized_reply:
        raise WaitlistValidationError("reply is required", field="reply")
    active_consent = str(getattr(settings, "ALLIES_WAITLIST_CONSENT_VERSION", ""))
    if not active_consent or consent_version != active_consent:
        raise WaitlistValidationError(
            "consent version is invalid", field="consent_version"
        )
    digest = _completion_digest(
        reply=normalized_reply,
        email=normalized_email,
        consent_version=consent_version,
    )
    with transaction.atomic():
        try:
            entry = WaitlistEntry.objects.select_for_update().get(
                attempt_token_digest=_digest(attempt_token)
            )
        except WaitlistEntry.DoesNotExist as exc:
            raise EntryUnavailable("waitlist entry unavailable") from exc
        if entry.joined_at:
            if entry.completion_digest != digest:
                raise InvalidEntryState("waitlist entry is already complete")
            return mask_email(entry.email_normalized)
        if not entry.greeting_text:
            raise InvalidEntryState("waitlist entry is not ready")
        now = timezone.now()
        entry.reply_text = normalized_reply
        entry.reply_recorded_at = now
        entry.email_normalized = normalized_email
        entry.consent_version = consent_version
        entry.joined_at = now
        entry.completion_digest = digest
        entry.expires_at = now + timedelta(
            seconds=int(
                getattr(settings, "ALLIES_WAITLIST_JOINED_RETENTION_SECONDS", 0)
            )
        )
        entry.save()
    return mask_email(normalized_email)
