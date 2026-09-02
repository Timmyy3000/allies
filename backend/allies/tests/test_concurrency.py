from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from threading import Barrier

import pytest
from auths.models import User
from django.db import close_old_connections, connection
from django.utils import timezone
from workspaces.models import Membership, Workspace

from allies.models import (
    Ally,
    AllyBinding,
    OnboardingAttempt,
    ProvisioningOperation,
)
from allies.services.creation import create_ally
from allies.services.onboarding import begin_onboarding
from allies.services.provisioning import _claim_due

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="requires PostgreSQL row-lock and skip-locked semantics",
)


@dataclass
class GreetingProvider:
    def generate(self, _request):
        return "Hi, I can help you plan a focused study session. What comes first?"


def seed():
    return {
        "name": "Mira",
        "job": "Study partner",
        "personality": "Calm, curious, and specific.",
        "appearance_catalog_version": "v1",
        "appearance_key": "sunrise",
    }


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_key_create_converges_on_one_ally(settings, monkeypatch):
    settings.ALLIES_AUTH_DIGEST_KEY = "d" * 32
    monkeypatch.setattr("allies.services.creation._enqueue_dispatch", lambda: None)
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Personal Workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    start = begin_onboarding(
        **seed(),
        browser_binding=b"race-browser",
        generation_identity="test:create-race",
        provider=GreetingProvider(),
    )
    gate = Barrier(2)

    def create_once():
        close_old_connections()
        gate.wait()
        try:
            return create_ally(
                **seed(),
                user=user,
                workspace_id=workspace.id,
                onboarding_attempt=start.attempt_token,
                reply="Help me plan tomorrow.",
                browser_binding=b"race-browser",
                idempotency_key="stable-concurrent-key-1",
            ).ally.id
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        ally_ids = list(executor.map(lambda _index: create_once(), range(2)))

    assert ally_ids[0] == ally_ids[1]
    assert Ally.objects.count() == 1
    assert AllyBinding.objects.count() == 1
    assert ProvisioningOperation.objects.count() == 1
    assert OnboardingAttempt.objects.get().consumed_at is not None


@pytest.mark.django_db(transaction=True)
def test_duplicate_dispatch_claims_are_fenced_by_one_live_lease():
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Dispatch")
    ally = Ally.objects.create(workspace=workspace, **seed())
    binding = AllyBinding.objects.create(ally=ally)
    operation = ProvisioningOperation.objects.create(
        binding=binding,
        workspace=workspace,
        user=user,
        api_idempotency_key_digest="a" * 64,
        content_fingerprint="b" * 64,
        expires_at=timezone.now() + timedelta(hours=1),
    )
    now = timezone.now()
    gate = Barrier(2)

    def claim_once():
        close_old_connections()
        gate.wait()
        try:
            return _claim_due(now=now, limit=1)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _index: claim_once(), range(2)))

    assert sum(len(batch) for batch in claims) == 1
    operation.refresh_from_db()
    assert operation.attempt_count == 1
    assert operation.lease_expires_at is not None
