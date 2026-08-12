from datetime import timedelta

import pytest
from django.utils import timezone

from auths.exceptions import SessionInvalid
from auths.models import RefreshToken, SessionFamily
from auths.providers.base import VerifiedIdentity
from auths.services.accounts import resolve_or_create_user
from auths.services.sessions import (
    _decode_jwt,
    _encode_jwt,
    authenticate_access,
    issue_session,
    logout_session,
    refresh_family_public_id,
    revoke_family,
    rotate_refresh,
)


@pytest.mark.django_db
def test_refresh_rotation_is_one_time_and_reuse_revokes_family():
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="session")
    ).user
    issued = issue_session(user)
    rotated = rotate_refresh(issued.refresh_token)

    assert authenticate_access(issued.access_token).user.id == user.id
    assert rotated.family.public_id == issued.family.public_id
    assert refresh_family_public_id(rotated.refresh_token) == issued.family.public_id
    with pytest.raises(SessionInvalid):
        rotate_refresh(issued.refresh_token)
    family = SessionFamily.objects.get(pk=issued.family.pk)
    assert family.revoked_at is not None
    with pytest.raises(SessionInvalid):
        authenticate_access(issued.access_token)


@pytest.mark.django_db
def test_access_jwt_rejects_malformed_headers_signatures_and_claims():
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="jwt-boundaries")
    ).user
    issued = issue_session(user)
    claims = _decode_jwt(issued.access_token)

    malformed = ["not-a-jwt", "a.b.c", "a." * 5000]
    for raw in malformed:
        with pytest.raises(SessionInvalid):
            _decode_jwt(raw)

    # A validly encoded but malformed header, signature, or claim set must not
    # be accepted merely because the payload is otherwise well formed.
    variants = [
        {"header": {"alg": "none", "typ": "JWT"}},
        {"signature": "bad"},
        {"claims": {**claims, "extra": "reject"}},
        {"claims": {**claims, "iss": "wrong"}},
        {"claims": {**claims, "aud": "wrong"}},
        {"claims": {**claims, "exp": int(timezone.now().timestamp()) - 1}},
        {"claims": {**claims, "iat": int(timezone.now().timestamp()) + 120}},
        {"claims": {**claims, "exp": "not-an-int"}},
        {"claims": {**claims, "sub": ""}},
    ]
    for variant in variants:
        candidate_claims = variant.get("claims", claims)
        if "header" in variant:
            import base64
            import json

            header = (
                base64.urlsafe_b64encode(json.dumps(variant["header"]).encode())
                .rstrip(b"=")
                .decode()
            )
            valid_parts = issued.access_token.split(".")
            raw = f"{header}.{valid_parts[1]}.{valid_parts[2]}"
        elif "signature" in variant:
            raw = ".".join(issued.access_token.split(".")[:2] + [variant["signature"]])
        else:
            raw = _encode_jwt(candidate_claims)
        with pytest.raises(SessionInvalid):
            _decode_jwt(raw)


@pytest.mark.django_db
def test_session_lifecycle_rejects_inactive_unknown_and_expired_records():
    user = resolve_or_create_user(
        VerifiedIdentity(provider="fake", subject="session-boundaries")
    ).user
    user.is_active = False
    user.save(update_fields=("is_active",))
    with pytest.raises(SessionInvalid):
        issue_session(user)

    user.is_active = True
    user.save(update_fields=("is_active",))
    issued = issue_session(user)
    claims = _decode_jwt(issued.access_token)
    claims["sid"] = "ses_missing"
    with pytest.raises(SessionInvalid):
        authenticate_access(_encode_jwt(claims))

    with pytest.raises(SessionInvalid):
        rotate_refresh(None)
    with pytest.raises(SessionInvalid):
        rotate_refresh("x" * 513)
    token = RefreshToken.objects.get(family=issued.family, used_at__isnull=True)
    token.expires_at = timezone.now() - timedelta(seconds=1)
    token.save(update_fields=("expires_at",))
    with pytest.raises(SessionInvalid):
        rotate_refresh(issued.refresh_token)

    # Logout is intentionally idempotent for unknown refresh tokens and for a
    # request with no credentials; operator revocation is likewise idempotent.
    logout_session(refresh="does-not-exist")
    logout_session()
    assert revoke_family(issued.family, reason="operator-test") is True
    assert revoke_family(issued.family, reason="second-call") is False
