import logging

from django.conf import settings
from django.contrib import admin
from django.urls import resolve
from unfold.admin import ModelAdmin

from auths.models import AvatarAsset, ExternalIdentity, User, UserProfile
from waitlist.models import WaitlistEntry
from workspaces.models import Membership, Workspace


def test_unfold_configures_every_repository_admin():
    assert settings.INSTALLED_APPS.index("unfold") < settings.INSTALLED_APPS.index(
        "django.contrib.admin"
    )

    registered_models = (
        User,
        ExternalIdentity,
        UserProfile,
        AvatarAsset,
        Workspace,
        Membership,
        WaitlistEntry,
    )
    assert all(
        isinstance(admin.site.get_model_admin(model), ModelAdmin)
        for model in registered_models
    )


def test_admin_keeps_its_existing_url():
    match = resolve("/admin/")

    assert match.namespace == "admin"


def test_allies_audit_loggers_are_enabled_at_runtime():
    for name in ("allies.auth", "allies.waitlist"):
        logger = logging.getLogger(name)
        assert logger.isEnabledFor(logging.INFO)
        assert logger.propagate is False
        handler = next(
            handler for handler in logger.handlers if handler.name == "allies_console"
        )
        record = logging.LogRecord(
            name=name,
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="audit test",
            args=(),
            exc_info=None,
        )
        assert handler.format(record) == f"INFO {name} audit test"


def test_waitlist_logger_preserves_django_framework_logging():
    django_logger = logging.getLogger("django")
    server_logger = logging.getLogger("django.server")

    assert {handler.name for handler in django_logger.handlers} == {
        "console",
        "mail_admins",
    }
    assert {handler.name for handler in server_logger.handlers} == {"django.server"}
