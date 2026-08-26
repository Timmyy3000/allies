import pytest
from django.apps import apps
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.db import connection, models

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="requires PostgreSQL schema introspection"
)


PRODUCT_MODELS = (
    ("auths", "User"),
    ("auths", "ExternalIdentity"),
    ("auths", "UserProfile"),
    ("auths", "AuthFlow"),
    ("auths", "NativeAuthorizationTransaction"),
    ("auths", "NativeExchangeCode"),
    ("auths", "SessionFamily"),
    ("auths", "RefreshToken"),
    ("auths", "AvatarAsset"),
    ("workspaces", "Workspace"),
    ("workspaces", "Membership"),
    ("allies", "Ally"),
    ("allies", "AllyBinding"),
    ("allies", "OnboardingAttempt"),
    ("allies", "ProvisioningOperation"),
    ("chat", "Conversation"),
    ("chat", "Message"),
    ("waitlist", "WaitlistEntry"),
)

PRODUCT_RELATIONS = (
    ("auths", "ExternalIdentity", "user"),
    ("auths", "UserProfile", "user"),
    ("auths", "UserProfile", "current_avatar"),
    ("auths", "AuthFlow", "user"),
    ("auths", "AuthFlow", "session_family"),
    ("auths", "NativeExchangeCode", "transaction"),
    ("auths", "NativeExchangeCode", "user"),
    ("auths", "SessionFamily", "user"),
    ("auths", "RefreshToken", "family"),
    ("auths", "AvatarAsset", "user"),
    ("workspaces", "Workspace", "owner"),
    ("workspaces", "Membership", "workspace"),
    ("workspaces", "Membership", "user"),
    ("allies", "Ally", "workspace"),
    ("allies", "AllyBinding", "ally"),
    ("allies", "OnboardingAttempt", "user"),
    ("allies", "OnboardingAttempt", "ally"),
    ("allies", "ProvisioningOperation", "binding"),
    ("allies", "ProvisioningOperation", "workspace"),
    ("allies", "ProvisioningOperation", "user"),
    ("chat", "Conversation", "ally"),
    ("chat", "Message", "conversation"),
)


def _assert_postgresql_uuid_column(table: str, column: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = %s
              AND column_name = %s
            """,
            [table, column],
        )
        row = cursor.fetchone()
    assert row == ("uuid",), f"{table}.{column} is not a PostgreSQL UUID column"


def _assert_database_foreign_key(model, field_name: str) -> None:
    field = model._meta.get_field(field_name)
    target = field.target_field
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(
            cursor, model._meta.db_table
        )
    assert any(
        constraint["foreign_key"] == (target.model._meta.db_table, target.column)
        and field.column in constraint["columns"]
        for constraint in constraints.values()
    ), f"{model._meta.label}.{field_name} has no matching database foreign key"


@pytest.mark.postgresql
@pytest.mark.django_db
def test_product_primary_and_foreign_keys_are_postgresql_uuid_columns():
    assert connection.vendor == "postgresql"

    for app_label, model_name in PRODUCT_MODELS:
        model = apps.get_model(app_label, model_name)
        assert isinstance(model._meta.pk, models.UUIDField)
        _assert_postgresql_uuid_column(model._meta.db_table, model._meta.pk.column)

    for app_label, model_name, field_name in PRODUCT_RELATIONS:
        model = apps.get_model(app_label, model_name)
        field = model._meta.get_field(field_name)
        _assert_postgresql_uuid_column(model._meta.db_table, field.column)
        _assert_database_foreign_key(model, field_name)


@pytest.mark.postgresql
@pytest.mark.django_db
def test_framework_relations_target_the_uuid_user_primary_key():
    user_model = get_user_model()
    for field_name in ("groups", "user_permissions"):
        relation = user_model._meta.get_field(field_name)
        through = relation.remote_field.through
        user_field = next(
            field
            for field in through._meta.fields
            if getattr(field.remote_field, "model", None) is user_model
        )
        _assert_postgresql_uuid_column(through._meta.db_table, user_field.column)
        _assert_database_foreign_key(through, user_field.name)

    _assert_postgresql_uuid_column(
        LogEntry._meta.db_table, LogEntry._meta.get_field("user").column
    )
    _assert_database_foreign_key(LogEntry, "user")
