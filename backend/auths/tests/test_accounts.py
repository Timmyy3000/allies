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
