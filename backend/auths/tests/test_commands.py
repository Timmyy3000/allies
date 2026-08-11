from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from auths.models import RefreshToken, SessionFamily
from auths.providers.base import VerifiedIdentity
from auths.services.accounts import resolve_or_create_actor
from auths.services.sessions import issue_session


@pytest.mark.django_db
def test_revoke_command_prints_count_only(capsys):
    actor = resolve_or_create_actor(
        VerifiedIdentity(provider="fake", subject="operator")
    ).actor
    issued = issue_session(actor)
    call_command("revoke_auth_sessions", actor_id=actor.public_id, reason="incident")
    output = capsys.readouterr().out
    assert output.strip() == "revoked=1"
    assert SessionFamily.objects.get(pk=issued.family.pk).revoked_at is not None
    assert actor.public_id not in output


@pytest.mark.django_db
def test_cleanup_retains_refresh_reuse_history_until_family_absolute_expiry(capsys):
    actor = resolve_or_create_actor(
        VerifiedIdentity(provider="fake", subject="cleanup")
    ).actor
    issued = issue_session(actor)
    token = issued.family.refresh_tokens.get()
    token.expires_at = timezone.now() - timedelta(days=1)
    token.save(update_fields=("expires_at",))
    call_command("cleanup_auth_artifacts", batch_size=1)
    assert RefreshToken.objects.filter(pk=token.pk).exists()
    issued.family.absolute_expires_at = timezone.now() - timedelta(days=1)
    issued.family.save(update_fields=("absolute_expires_at",))
    call_command("cleanup_auth_artifacts", batch_size=1)
    assert not RefreshToken.objects.filter(pk=token.pk).exists()
