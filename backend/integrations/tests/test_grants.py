import hashlib
import logging

import pytest
from cryptography.fernet import Fernet

from allies.models import Ally, AllyBinding
from auths.models import User
from integrations.exceptions import GrantDenied, IntegrationInvalid
from integrations.models import PROVIDER_GMAIL, AllyIntegrationGrant, IntegrationSecret
from integrations.services import google_oauth
from integrations.services.google_oauth import MintedAccess
from integrations.services.grants import (
    READ_ALLOWLIST,
    SEND_ALLOWLIST,
    check_gmail_grant,
    disconnect_gmail_account,
    mint_execution_credential,
    resolve_credential_ref,
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
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        ],
    )
    return user, workspace, ally_reader, ally_sender, secret


def test_grant_matrix_and_generation(rig):
    user, _, reader, sender, secret = rig
    set_ally_grant(secret=secret, ally=reader, level="read", created_by=user)
    set_ally_grant(secret=secret, ally=sender, level="send", created_by=user)

    read_decision = check_gmail_grant(secret=secret, ally=reader)
    assert read_decision.allowed is True
    assert read_decision.tool_allowlist == READ_ALLOWLIST
    assert "gmail send" not in read_decision.tool_allowlist

    send_decision = check_gmail_grant(secret=secret, ally=sender)
    assert send_decision.allowed is True
    assert send_decision.tool_allowlist == SEND_ALLOWLIST

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
    decision = check_gmail_grant(secret=secret, ally=reader)
    assert decision.allowed is False
    assert decision.reason_code == "grant_missing"
    with pytest.raises(GrantDenied):
        mint_execution_credential(secret=secret, ally=reader, command_id="cmd-1")


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
    decision = check_gmail_grant(secret=secret, ally=reader)
    assert decision.allowed is False
    assert revoke_ally_grant(secret=secret, ally=reader) == 0


def test_mint_registers_resolvable_ref(rig, monkeypatch):
    from django.utils import timezone

    _, _, _, sender, secret = rig
    set_ally_grant(secret=secret, ally=sender, level="send")
    minted = MintedAccess(
        access_token="ya29.exec",
        expires_at=timezone.now() + timezone.timedelta(seconds=600),
    )
    credential = mint_execution_credential(
        secret=secret, ally=sender, command_id="cmd-9", minted=minted
    )
    assert credential.ref.startswith(f"gmail:{secret.id}:cmd-9:")
    assert credential.tool_allowlist == SEND_ALLOWLIST
    assert credential.grant_generation == 1
    assert resolve_credential_ref(credential.ref, command_id="cmd-9") == "ya29.exec"
    with pytest.raises(GrantDenied):
        resolve_credential_ref(credential.ref, command_id="cmd-other")
    with pytest.raises(GrantDenied):
        resolve_credential_ref("gmail:missing:cmd:nope", command_id="cmd")


def test_mint_audit_never_logs_tokens(rig, monkeypatch, caplog):
    from django.utils import timezone

    _, _, _, sender, secret = rig
    set_ally_grant(secret=secret, ally=sender, level="read")
    minted = MintedAccess(
        access_token="ya29.super-secret-token",
        expires_at=timezone.now() + timezone.timedelta(seconds=600),
    )
    with caplog.at_level(logging.INFO, logger="integrations.services.grants"):
        mint_execution_credential(
            secret=secret, ally=sender, command_id="cmd-10", minted=minted
        )
    assert "ya29.super-secret-token" not in caplog.text
    assert "refresh.live" not in caplog.text


def test_disconnect_scrubs_and_revokes(rig, monkeypatch):
    _, _, reader, _, secret = rig
    set_ally_grant(secret=secret, ally=reader, level="read")
    from django.utils import timezone

    minted = MintedAccess(
        access_token="ya29.exec",
        expires_at=timezone.now() + timezone.timedelta(seconds=600),
    )
    credential = mint_execution_credential(
        secret=secret, ally=reader, command_id="cmd-11", minted=minted
    )
    monkeypatch.setattr(google_oauth, "revoke_at_google", lambda token: True)
    result = disconnect_gmail_account(secret=secret)
    assert result.status == "deprovisioned"
    assert result.scrubbed_refs == 1
    secret.refresh_from_db()
    assert secret.revoked_at is not None
    assert bytes(secret.ciphertext) == b""
    assert AllyIntegrationGrant.objects.count() == 0
    with pytest.raises(GrantDenied):
        resolve_credential_ref(credential.ref, command_id="cmd-11")
    again = disconnect_gmail_account(secret=secret)
    assert again.status == "already_cleaned"


def test_disconnect_google_failure_is_repair(rig, monkeypatch):
    _, _, _, _, secret = rig
    monkeypatch.setattr(google_oauth, "revoke_at_google", lambda token: False)
    result = disconnect_gmail_account(secret=secret)
    assert result.status == "repair_required"
    secret.refresh_from_db()
    assert secret.revoked_at is not None
    assert bytes(secret.ciphertext) != b""
    monkeypatch.setattr(google_oauth, "revoke_at_google", lambda token: True)
    retry = disconnect_gmail_account(secret=secret)
    assert retry.status == "deprovisioned"
    secret.refresh_from_db()
    assert bytes(secret.ciphertext) == b""


def test_disconnect_wipe_skips_reconnected_secret(rig, monkeypatch):
    from django.utils import timezone

    _, _, reader, _, secret = rig
    set_ally_grant(secret=secret, ally=reader, level="read")
    minted = MintedAccess(
        access_token="ya29.exec",
        expires_at=timezone.now() + timezone.timedelta(seconds=600),
    )
    credential = mint_execution_credential(
        secret=secret, ally=reader, command_id="cmd-12", minted=minted
    )

    def _revoke_with_racing_reconnect(token):
        fresh_ciphertext, _ = seal_refresh_token("refresh.reconnected")
        IntegrationSecret.objects.filter(pk=secret.pk).update(
            ciphertext=bytes(fresh_ciphertext), revoked_at=None
        )
        return True

    monkeypatch.setattr(google_oauth, "revoke_at_google", _revoke_with_racing_reconnect)
    result = disconnect_gmail_account(secret=secret)
    assert result.status == "repair_required"
    secret.refresh_from_db()
    assert secret.revoked_at is None
    assert bytes(secret.ciphertext) != b""
    with pytest.raises(GrantDenied):
        resolve_credential_ref(credential.ref, command_id="cmd-12")


def test_resolve_revalidates_live_grant(rig):
    from django.utils import timezone

    _, _, reader, sender, secret = rig
    set_ally_grant(secret=secret, ally=reader, level="read")
    set_ally_grant(secret=secret, ally=sender, level="send")
    minted = MintedAccess(
        access_token="ya29.exec",
        expires_at=timezone.now() + timezone.timedelta(seconds=600),
    )
    read_cred = mint_execution_credential(
        secret=secret, ally=reader, command_id="cmd-13", minted=minted
    )
    send_cred = mint_execution_credential(
        secret=secret, ally=sender, command_id="cmd-14", minted=minted
    )
    assert resolve_credential_ref(read_cred.ref, command_id="cmd-13") == "ya29.exec"
    revoke_ally_grant(secret=secret, ally=reader)
    with pytest.raises(GrantDenied):
        resolve_credential_ref(read_cred.ref, command_id="cmd-13")
    set_ally_grant(secret=secret, ally=sender, level="read")
    with pytest.raises(GrantDenied):
        resolve_credential_ref(send_cred.ref, command_id="cmd-14")


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
