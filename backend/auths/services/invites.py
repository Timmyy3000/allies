"""Single-use beta invite issuance, claims, and consumption."""

from __future__ import annotations

import hashlib
import secrets

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone

from auths.audit import emit_auth_event
from auths.exceptions import (
    InviteConsumed,
    InviteRequired,
    InviteUnavailable,
    InviteValidation,
)
from auths.models import BetaInvite

_INVITE_CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_INVITE_CODE_LENGTH = 8


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def normalize_invite_email(value: str) -> str:
    if not isinstance(value, str):
        raise InviteValidation("email is invalid")
    normalized = value.strip().lower()
    if not normalized or len(normalized) > 254:
        raise InviteValidation("email is invalid")
    try:
        validate_email(normalized)
    except DjangoValidationError as exc:
        raise InviteValidation("email is invalid") from exc
    return normalized


def _validate_code(code: str) -> str:
    if not isinstance(code, str):
        raise InviteValidation("code is invalid")
    normalized = code.strip().upper()
    if len(normalized) != _INVITE_CODE_LENGTH or any(
        char not in _INVITE_CODE_ALPHABET for char in normalized
    ):
        raise InviteValidation("code is invalid")
    return normalized


def _new_code() -> tuple[str, str]:
    raw = "".join(
        secrets.choice(_INVITE_CODE_ALPHABET) for _ in range(_INVITE_CODE_LENGTH)
    )
    return raw, _digest(raw)


def issue_invite() -> tuple[BetaInvite, str]:
    for _ in range(3):
        raw_code, code_digest = _new_code()
        try:
            with transaction.atomic():
                invite = BetaInvite.objects.create(code_digest=code_digest)
        except IntegrityError:
            continue
        emit_auth_event(
            "auth.invite.issued", outcome="accepted", correlation_id=str(invite.id)
        )
        return invite, raw_code
    raise InviteUnavailable("invite issuance unavailable")


def claim_invite(*, code: str, email: str) -> None:
    code = _validate_code(code)
    normalized_email = normalize_invite_email(email)
    try:
        with transaction.atomic():
            invite = BetaInvite.objects.select_for_update().get(
                code_digest=_digest(code)
            )
            if invite.revoked_at is not None or invite.consumed_at is not None:
                raise InviteUnavailable("invite is unavailable")
            if invite.claimed_email is not None:
                if invite.claimed_email == normalized_email:
                    return
                raise InviteUnavailable("invite is unavailable")
            invite.claimed_email = normalized_email
            invite.claimed_at = timezone.now()
            try:
                invite.save(update_fields=("claimed_email", "claimed_at", "updated_at"))
            except IntegrityError as exc:
                # A different code may have claimed this email concurrently.
                raise InviteUnavailable("invite is unavailable") from exc
    except BetaInvite.DoesNotExist as exc:
        raise InviteUnavailable("invite is unavailable") from exc
    emit_auth_event(
        "auth.invite.claimed", outcome="accepted", correlation_id=str(invite.id)
    )


def lock_invite_for_signup(*, email: str) -> BetaInvite:
    normalized_email = normalize_invite_email(email)
    try:
        invite = BetaInvite.objects.select_for_update().get(
            claimed_email=normalized_email
        )
    except BetaInvite.DoesNotExist as exc:
        raise InviteRequired("a beta invite is required") from exc
    return invite


def consume_invite(invite: BetaInvite) -> None:
    if invite.revoked_at is not None or invite.consumed_at is not None:
        raise InviteRequired("a beta invite is required")
    invite.consumed_at = timezone.now()
    invite.save(update_fields=("consumed_at", "updated_at"))
    invite_id = str(invite.id)
    transaction.on_commit(
        lambda: emit_auth_event(
            "auth.invite.consumed", outcome="accepted", correlation_id=invite_id
        )
    )


def revoke_invite(invite_id) -> None:
    try:
        with transaction.atomic():
            invite = BetaInvite.objects.select_for_update().get(pk=invite_id)
            if invite.revoked_at is None:
                invite.revoked_at = timezone.now()
                invite.save(update_fields=("revoked_at", "updated_at"))
    except BetaInvite.DoesNotExist as exc:
        raise InviteUnavailable("invite is unavailable") from exc
    emit_auth_event(
        "auth.invite.revoked", outcome="accepted", correlation_id=str(invite.id)
    )


def reset_invite(invite_id) -> str:
    try:
        with transaction.atomic():
            invite = BetaInvite.objects.select_for_update().get(pk=invite_id)
            if invite.consumed_at is not None:
                raise InviteConsumed("consumed invites cannot be reset")
            raw_code, code_digest = _new_code()
            invite.code_digest = code_digest
            invite.claimed_email = None
            invite.claimed_at = None
            invite.revoked_at = None
            invite.save(
                update_fields=(
                    "code_digest",
                    "claimed_email",
                    "claimed_at",
                    "revoked_at",
                    "updated_at",
                )
            )
    except BetaInvite.DoesNotExist as exc:
        raise InviteUnavailable("invite is unavailable") from exc
    emit_auth_event(
        "auth.invite.reset", outcome="accepted", correlation_id=str(invite.id)
    )
    return raw_code
