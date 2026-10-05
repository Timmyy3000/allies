import pytest

from auths.models import ExternalIdentity, User, UserProfile
from auths.providers.base import VerifiedIdentity
from auths.services.accounts import resolve_or_create_user
from workspaces.models import Membership, Workspace


@pytest.mark.django_db
def test_subject_resolution_is_idempotent_and_never_merges_email():
    first = resolve_or_create_user(
        VerifiedIdentity(
            provider="fake",
            subject="subject-a",
            email="same@example.com",
            display_name="Ada",
        )
    )
    repeat = resolve_or_create_user(
        VerifiedIdentity(
            provider="fake",
            subject="subject-a",
            email="other@example.com",
            display_name="Changed",
        )
    )
    other = resolve_or_create_user(
        VerifiedIdentity(
            provider="fake",
            subject="subject-b",
            email="same@example.com",
            display_name="Bob",
        )
    )

    assert repeat.user.id == first.user.id
    assert other.user.id != first.user.id
    assert User.objects.count() == 2
    assert ExternalIdentity.objects.count() == 2
    assert str(ExternalIdentity.objects.get(subject="subject-a")) == "fake:subject-a"
    assert UserProfile.objects.count() == 2
    assert Workspace.objects.count() == 2
    assert Membership.objects.count() == 2
    assert first.profile.display_name == "Ada"
    assert first.user.has_usable_password() is False
    assert other.user.has_usable_password() is False


@pytest.mark.django_db
def test_allowlisted_verified_email_signs_up_without_an_invite(settings):
    from auths.exceptions import InviteRequired

    settings.ALLIES_BETA_INVITES_REQUIRED = True
    settings.ALLIES_SIGNUP_ALLOWED_EMAILS = ["owner@example.com", "@team.example"]

    def identity(subject, email, verified=True):
        return VerifiedIdentity(
            provider="google",
            subject=subject,
            email=email,
            display_name="Owner",
            email_verified=verified,
            email_verification_source="google" if verified else "",
        )

    assert resolve_or_create_user(identity("a", "Owner@example.com")).created
    assert resolve_or_create_user(identity("b", "bo@team.example")).created
    for subject, email, verified in (
        ("c", "stranger@example.com", True),
        ("d", "owner@example.com", False),
    ):
        with pytest.raises(InviteRequired):
            resolve_or_create_user(identity(subject, email, verified))
