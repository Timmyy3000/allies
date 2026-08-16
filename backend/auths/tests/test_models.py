import pytest

from auths.models import User


@pytest.mark.django_db
def test_create_superuser_persists_a_usable_password():
    user = User.objects.create_superuser(
        public_id="admin@example.test",
        password="test-admin-password",
    )

    assert user.is_staff is True
    assert user.is_superuser is True
    assert user.has_usable_password() is True
    assert user.check_password("test-admin-password") is True


@pytest.mark.django_db
def test_product_users_remain_passwordless_without_a_password():
    user = User.objects.create_user(public_id="oauth-user")

    assert user.has_usable_password() is False
