import hashlib
import hmac
from datetime import timedelta

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from auths.config import digest_key
from auths.services.sessions import authenticate_access, rotate_refresh


@pytest.mark.django_db(transaction=True)
def test_auth_002_forward_upgrade_preserves_browser_refresh():
    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        old_state = executor.migrate(
            [("auths", "0002_externalidentity_email_verification")]
        )
        old_apps = old_state.apps
        User = old_apps.get_model("auths", "User")
        SessionFamily = old_apps.get_model("auths", "SessionFamily")
        RefreshToken = old_apps.get_model("auths", "RefreshToken")

        now = timezone.now()
        user = User.objects.create(
            public_id="usr_auth002_migration",
            password="!",
            is_active=True,
        )
        family = SessionFamily.objects.create(
            user=user,
            public_id="ses_auth002_migration",
            last_used_at=now,
            idle_expires_at=now + timedelta(days=14),
            absolute_expires_at=now + timedelta(days=30),
        )
        raw_refresh = "auth002-known-browser-refresh"
        digest = hmac.new(
            digest_key(), raw_refresh.encode(), hashlib.sha256
        ).hexdigest()
        RefreshToken.objects.create(
            family=family,
            token_digest=digest,
            expires_at=now + timedelta(days=14),
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("auths", "0003_native_session_contract")])
        current_state = executor.loader.project_state(
            [("auths", "0003_native_session_contract")]
        )
        current_apps = current_state.apps
        current_family = current_apps.get_model("auths", "SessionFamily")

        assert current_family.objects.get(pk=family.pk).client_kind == "browser"
        assert current_apps.get_model("auths", "NativeAuthorizationTransaction")
        assert current_apps.get_model("auths", "NativeExchangeCode")

        issued = rotate_refresh(raw_refresh, expected_client_kind="browser")
        assert issued.family.pk == family.pk
        assert issued.family.client_kind == "browser"
        assert (
            authenticate_access(
                issued.access_token, expected_client_kind="browser"
            ).user.public_id
            == user.public_id
        )
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
