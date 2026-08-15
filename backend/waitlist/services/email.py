"""One canonical waitlist email normalization/comparison routine."""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email

from ..exceptions import WaitlistValidationError


def normalize_email(value: str) -> str:
    if not isinstance(value, str):
        raise WaitlistValidationError("email is invalid", field="email")
    normalized = value.strip().casefold()
    if len(normalized) > 254:
        raise WaitlistValidationError("email is invalid", field="email")
    try:
        validate_email(normalized)
    except DjangoValidationError as exc:
        raise WaitlistValidationError("email is invalid", field="email") from exc
    return normalized


def emails_match(left: str, right: str) -> bool:
    try:
        return normalize_email(left) == normalize_email(right)
    except WaitlistValidationError:
        return False
