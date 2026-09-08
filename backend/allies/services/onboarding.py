from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from unicodedata import category

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from allies.exceptions import OnboardingInvalid, OnboardingUnavailable
from allies.models import OnboardingAttempt
from auths.config import digest_key
from waitlist.admission import acquire_generation, release_generation
from waitlist.exceptions import (
    AdmissionUnavailable,
    GenerationUnavailable,
    WaitlistValidationError,
)
from waitlist.providers.base import (
    GreetingRequest,
    ProviderUnavailableError,
    ProviderUnknownError,
)
from waitlist.services.generation import get_provider, validate_output


@dataclass(frozen=True, slots=True)
class OnboardingStart:
    attempt_token: str
    greeting: str


def normalize_multiline_field(
    value: object, *, max_length: int, canonicalize: bool = True
) -> str:
    if not isinstance(value, str):
        raise ValueError("value is invalid")  # noqa: TRY004
    if canonicalize:
        if len(value) > max_length * 2:
            raise ValueError("value is invalid")
        value = value.replace("\r\n", "\n")
    if len(value) > max_length or "\r" in value:
        raise ValueError("value is invalid")
    if any(
        char != "\n" and category(char) in {"Cc", "Cf", "Zl", "Zp"} for char in value
    ):
        raise ValueError("value is invalid")
    return value


def _required(
    value: object,
    *,
    field: str,
    max_length: int,
    preserve_whitespace: bool = False,
    multiline: bool = False,
) -> str:
    if multiline:
        try:
            value = normalize_multiline_field(value, max_length=max_length)
        except ValueError as exc:
            raise OnboardingInvalid(f"{field} is invalid") from exc
    if not isinstance(value, str):
        raise OnboardingInvalid(f"{field} is invalid")
    if not value.strip() or len(value) > max_length:
        raise OnboardingInvalid(f"{field} is invalid")
    return value if preserve_whitespace else value.strip()


def normalize_seed(
    *,
    name: str,
    job: str,
    personality: str,
    appearance_catalog_version: str,
    appearance_key: str,
) -> dict[str, str]:
    return {
        "name": _required(name, field="name", max_length=80),
        "job": _required(job, field="job", max_length=200, multiline=True),
        "personality": _required(
            personality,
            field="personality",
            max_length=4000,
            preserve_whitespace=True,
            multiline=True,
        ),
        "appearance_catalog_version": _required(
            appearance_catalog_version,
            field="appearance_catalog_version",
            max_length=32,
        ),
        "appearance_key": _required(
            appearance_key, field="appearance_key", max_length=128
        ),
    }


def digest_value(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode()
    return hmac.new(digest_key(), raw, hashlib.sha256).hexdigest()


def _native_attempt_binding(attempt_token: str) -> bytes:
    return f"native:{attempt_token}".encode()


def begin_onboarding(
    *,
    name: str,
    job: str,
    personality: str,
    appearance_catalog_version: str,
    appearance_key: str,
    browser_binding: bytes | None,
    generation_identity: str,
    provider=None,
) -> OnboardingStart:
    if browser_binding is not None and (
        not isinstance(browser_binding, bytes) or not browser_binding
    ):
        raise OnboardingInvalid("browser binding is required")
    values = normalize_seed(
        name=name,
        job=job,
        personality=personality,
        appearance_catalog_version=appearance_catalog_version,
        appearance_key=appearance_key,
    )
    lease = None
    try:
        lease = acquire_generation(generation_identity)
        greeting = (provider or get_provider()).generate(
            GreetingRequest(
                name=values["name"],
                job=values["job"],
                personality=values["personality"],
            )
        )
        greeting = validate_output(greeting, ally_name=values["name"])
    except (
        AdmissionUnavailable,
        GenerationUnavailable,
        ProviderUnavailableError,
        ProviderUnknownError,
        WaitlistValidationError,
    ) as exc:
        raise OnboardingUnavailable("onboarding unavailable") from exc
    finally:
        if lease is not None:
            release_generation(lease)

    token = secrets.token_urlsafe(32)
    binding = (
        browser_binding
        if browser_binding is not None
        else _native_attempt_binding(token)
    )
    OnboardingAttempt.objects.create(
        attempt_token_digest=digest_value(token),
        browser_binding_digest=digest_value(binding),
        **values,
        greeting=greeting,
        expires_at=timezone.now()
        + timedelta(
            seconds=int(
                getattr(settings, "ALLIES_ONBOARDING_ATTEMPT_TTL_SECONDS", 1800)
            )
        ),
    )
    return OnboardingStart(attempt_token=token, greeting=greeting)


def cleanup_expired_onboarding_attempts(*, now=None, limit: int = 500) -> int:
    now = now or timezone.now()
    limit = max(1, min(limit, 2000))
    with transaction.atomic():
        query = OnboardingAttempt.objects.filter(
            consumed_at__isnull=True,
            expires_at__lte=now,
        ).order_by("expires_at", "id")
        query = query.select_for_update(
            skip_locked=connection.features.has_select_for_update_skip_locked
        )
        attempt_ids = list(query.values_list("id", flat=True)[:limit])
        if not attempt_ids:
            return 0
        deleted, _ = OnboardingAttempt.objects.filter(id__in=attempt_ids).delete()
        return deleted
