import hashlib

import pytest
from cryptography.fernet import Fernet

from allies.models import Ally, AllyBinding
from auths.models import User
from integrations.exceptions import IntegrationInvalid
from integrations.models import PROVIDER_GMAIL, AllyIntegrationGrant, IntegrationSecret
from integrations.services import google_oauth
from integrations.services.grants import (
    ALLOWLISTS,
    check_grant,
    disconnect_account,
    revoke_ally_grant,
    set_ally_grant,
)
from integrations.services.vault import seal_refresh_token
from workspaces.models import Membership, Workspace


def _test_vault_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def gmail_settings(settings):
    settings.ALLIES_GMAIL_ENABLED = True
    settings.ALLIES_INTEGRATIONS_VAULT_KEY = _test_vault_key()
    return settings


@pytest.fixture
def rig(db, gmail_settings):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Grant workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )

    def _ally(name):
        ally = Ally.objects.create(
            workspace=workspace,
            name=name,
            job="Inbox helper",
            personality="Calm and specific.",
            appearance_catalog_version="v1",
            appearance_key="sunrise",
        )
        AllyBinding.objects.create(ally=ally)
        return ally

    ally_reader = _ally("Reader")
    ally_sender = _ally("Sender")
    ciphertext, version = seal_refresh_token("refresh.live")
    secret = IntegrationSecret.objects.create(
        workspace=workspace,
        provider_key=PROVIDER_GMAIL,
        account_ref_hash=hashlib.sha256(b"google-sub-1").hexdigest(),
        account_email="user@gmail.com",
        ciphertext=bytes(ciphertext),
        key_version=version,
        scope_set=[
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
        ],
    )
    return user, workspace, ally_reader, ally_sender, secret


def test_grant_matrix_and_generation(rig):
    user, _, reader, sender, secret = rig
    set_ally_grant(secret=secret, ally=reader, level="read", created_by=user)
    set_ally_grant(secret=secret, ally=sender, level="send", created_by=user)

    read_decision = check_grant(secret=secret, ally=reader)
    assert read_decision.allowed is True
    assert read_decision.tool_allowlist == ALLOWLISTS[("gmail", "read")]
    assert "gmail send" not in read_decision.tool_allowlist

    send_decision = check_grant(secret=secret, ally=sender)
    assert send_decision.allowed is True
    assert send_decision.tool_allowlist == ALLOWLISTS[("gmail", "send")]

    upgraded = set_ally_grant(secret=secret, ally=reader, level="send")
    assert upgraded.grant_generation == read_decision.grant_generation


def test_regrant_after_revoke_gets_fresh_generation(rig):
    _, _, reader, _, secret = rig
    first = set_ally_grant(secret=secret, ally=reader, level="send")
    revoke_ally_grant(secret=secret, ally=reader)
    second = set_ally_grant(secret=secret, ally=reader, level="send")
    assert second.grant_generation == first.grant_generation + 1


def test_ungranted_ally_denied(rig):
    _, _, reader, _, secret = rig
    decision = check_grant(secret=secret, ally=reader)
    assert decision.allowed is False
    assert decision.reason_code == "grant_missing"


def test_cross_workspace_ally_rejected(db, rig):
    _, _, _, _, secret = rig
    outsider_user = User.objects.create_user()
    outsider_workspace = Workspace.objects.create(owner=outsider_user, name="Other")
    Membership.objects.create(
        workspace=outsider_workspace, user=outsider_user, role="owner", status="active"
    )
    outsider = Ally.objects.create(
        workspace=outsider_workspace,
        name="Outsider",
        job="None",
        personality="None.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    with pytest.raises(IntegrationInvalid):
        set_ally_grant(secret=secret, ally=outsider, level="read")
    with pytest.raises(IntegrationInvalid):
        set_ally_grant(secret=secret, ally=outsider, level="bogus")


def test_revoked_secret_denies_and_revoke_fences(rig):
    _, _, reader, _, secret = rig
    set_ally_grant(secret=secret, ally=reader, level="send")
    generation = revoke_ally_grant(secret=secret, ally=reader)
    assert generation == 1
    assert AllyIntegrationGrant.objects.count() == 0
    decision = check_grant(secret=secret, ally=reader)
    assert decision.allowed is False
    assert revoke_ally_grant(secret=secret, ally=reader) == 0


def test_disconnect_scrubs_and_revokes(rig, monkeypatch):
    _, _, reader, _, secret = rig
    set_ally_grant(secret=secret, ally=reader, level="read")
    monkeypatch.setattr(google_oauth, "revoke_at_google", lambda token: True)
    result = disconnect_account(secret=secret)
    assert result.status == "deprovisioned"
    secret.refresh_from_db()
    assert secret.revoked_at is not None
    assert bytes(secret.ciphertext) == b""
    assert AllyIntegrationGrant.objects.count() == 0
    assert check_grant(secret=secret, ally=reader).allowed is False
    again = disconnect_account(secret=secret)
    assert again.status == "already_cleaned"


def test_disconnect_google_failure_is_repair(rig, monkeypatch):
    _, _, _, _, secret = rig
    monkeypatch.setattr(google_oauth, "revoke_at_google", lambda token: False)
    result = disconnect_account(secret=secret)
    assert result.status == "repair_required"
    secret.refresh_from_db()
    assert secret.revoked_at is not None
    assert bytes(secret.ciphertext) != b""
    monkeypatch.setattr(google_oauth, "revoke_at_google", lambda token: True)
    retry = disconnect_account(secret=secret)
    assert retry.status == "deprovisioned"
    secret.refresh_from_db()
    assert bytes(secret.ciphertext) == b""


def test_disconnect_wipe_skips_reconnected_secret(rig, monkeypatch):
    _, _, reader, _, secret = rig
    set_ally_grant(secret=secret, ally=reader, level="read")

    def _revoke_with_racing_reconnect(token):
        fresh_ciphertext, _ = seal_refresh_token("refresh.reconnected")
        IntegrationSecret.objects.filter(pk=secret.pk).update(
            ciphertext=bytes(fresh_ciphertext), revoked_at=None
        )
        return True

    monkeypatch.setattr(google_oauth, "revoke_at_google", _revoke_with_racing_reconnect)
    result = disconnect_account(secret=secret)
    assert result.status == "repair_required"
    secret.refresh_from_db()
    assert secret.revoked_at is None
    assert bytes(secret.ciphertext) != b""
    assert AllyIntegrationGrant.objects.filter(secret=secret).count() == 0


def test_single_active_connection_per_workspace(rig):
    import hashlib

    from django.db import IntegrityError, transaction

    _, workspace, _, _, secret = rig
    from integrations.services.vault import seal_refresh_token

    ciphertext, version = seal_refresh_token("refresh.other")
    with (
        transaction.atomic(),
        pytest.raises(IntegrityError),
    ):
        IntegrationSecret.objects.create(
            workspace=workspace,
            provider_key=PROVIDER_GMAIL,
            account_ref_hash=hashlib.sha256(b"other").hexdigest(),
            account_email="other@gmail.com",
            ciphertext=bytes(ciphertext),
            key_version=version,
            scope_set=[],
        )
    assert (
        IntegrationSecret.objects.filter(
            workspace=workspace, provider_key=PROVIDER_GMAIL, revoked_at=None
        ).count()
        == 1
    )
    assert secret.generation_epoch == 1
