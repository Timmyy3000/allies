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
