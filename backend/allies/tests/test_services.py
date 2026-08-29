from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import pytest
from django.utils import timezone

from allies.api.controllers import _response
from allies.exceptions import IdempotencyConflict, OnboardingInvalid
from allies.models import Ally, AllyBinding, OnboardingAttempt, ProvisioningOperation
from allies.services.creation import create_ally, list_allies, retrieve_ally
from allies.services.onboarding import (
    begin_onboarding,
    cleanup_expired_onboarding_attempts,
    digest_value,
)
from auths.exceptions import WorkspaceAccessDenied
from auths.models import User
from workspaces.models import Membership, Workspace


@dataclass
class GreetingProvider:
    greeting: str = "Hi, I can help you plan a focused study session. What comes first?"

    def generate(self, request):
        return self.greeting


@pytest.fixture
def account(db, settings):
    settings.ALLIES_AUTH_DIGEST_KEY = "d" * 32
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Personal Workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    return user, workspace


def payload():
    return {
        "name": "Mira",
        "job": "Study partner",
        "personality": "Calm, curious, and specific.",
        "appearance_catalog_version": "v1",
        "appearance_key": "sunrise",
    }


def seed_ally(*, workspace, user, ally_id: str) -> Ally:
    ally = Ally.objects.create(
        id=UUID(ally_id),
        workspace=workspace,
        name="Mira",
        job="Study partner",
        personality="Calm, curious, and specific.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    binding = AllyBinding.objects.create(ally=ally)
    digest = ally_id.replace("-", "")
    ProvisioningOperation.objects.create(
        binding=binding,
        workspace=workspace,
        user=user,
        api_idempotency_key_digest=(digest * 2)[:64],
        content_fingerprint=(digest[::-1] * 2)[:64],
    )
    return ally


@pytest.mark.django_db
def test_official_attempt_creates_no_waitlist_or_production_ally(account):
    from waitlist.models import WaitlistEntry

    start = begin_onboarding(
        **payload(),
        browser_binding=b"browser",
        generation_identity="test:onboarding",
        provider=GreetingProvider(),
    )

    assert (
        start.attempt_token not in OnboardingAttempt.objects.get().attempt_token_digest
    )
    assert OnboardingAttempt.objects.get().greeting == start.greeting
    assert Ally.objects.count() == 0
    assert WaitlistEntry.objects.count() == 0


@pytest.mark.django_db
def test_create_replays_same_intent_and_conflicts_on_changed_content(account):
    user, workspace = account
    start = begin_onboarding(
        **payload(),
        browser_binding=b"browser",
        generation_identity="test:create",
        provider=GreetingProvider(),
    )
    values = {
        **payload(),
        "user": user,
        "workspace_id": workspace.id,
        "onboarding_attempt": start.attempt_token,
        "reply": "Help me plan tomorrow.",
        "browser_binding": b"browser",
        "idempotency_key": "stable-create-key-1",
    }

    first = create_ally(**values)
    replay = create_ally(**values)

    assert not first.replayed
    assert replay.replayed
    assert replay.ally.pk == first.ally.pk
    assert Ally.objects.count() == 1
    attempt = OnboardingAttempt.objects.get()
    assert attempt.reply == "Help me plan tomorrow."
    assert attempt.ally == first.ally
    with pytest.raises(IdempotencyConflict):
        create_ally(**{**values, "reply": "Different reply."})


@pytest.mark.django_db
def test_create_rejects_browser_or_seed_tampering(account):
    user, workspace = account
    start = begin_onboarding(
        **payload(),
        browser_binding=b"browser",
        generation_identity="test:tampering",
        provider=GreetingProvider(),
    )
    values = {
        **payload(),
        "user": user,
        "workspace_id": workspace.id,
        "onboarding_attempt": start.attempt_token,
        "reply": "Help me plan tomorrow.",
        "browser_binding": b"other-browser",
        "idempotency_key": "stable-create-key-2",
    }
    with pytest.raises(OnboardingInvalid):
        create_ally(**values)
    with pytest.raises(OnboardingInvalid):
        create_ally(**{**values, "browser_binding": b"browser", "job": "Changed job"})
    assert Ally.objects.count() == 0


@pytest.mark.django_db
def test_retrieve_is_workspace_scoped(account):
    from auths.exceptions import WorkspaceAccessDenied

    user, workspace = account
    start = begin_onboarding(
        **payload(),
        browser_binding=b"browser",
        generation_identity="test:retrieve",
        provider=GreetingProvider(),
    )
    result = create_ally(
        **payload(),
        user=user,
        workspace_id=workspace.id,
        onboarding_attempt=start.attempt_token,
        reply="Help me plan tomorrow.",
        browser_binding=b"browser",
        idempotency_key="stable-create-key-3",
    )
    assert (
        retrieve_ally(user=user, workspace_id=workspace.id, ally_id=result.ally.id).pk
        == result.ally.pk
    )
    stranger = User.objects.create_user()
    with pytest.raises(WorkspaceAccessDenied):
        retrieve_ally(
            user=stranger,
            workspace_id=workspace.id,
            ally_id=result.ally.id,
        )


@pytest.mark.django_db
def test_list_is_workspace_scoped_ordered_and_relation_loaded(
    account, django_assert_num_queries
):
    user, workspace = account
    oldest = seed_ally(
        workspace=workspace,
        user=user,
        ally_id="00000000-0000-4000-8000-000000000001",
    )
    tie_low = seed_ally(
        workspace=workspace,
        user=user,
        ally_id="00000000-0000-4000-8000-000000000002",
    )
    tie_high = seed_ally(
        workspace=workspace,
        user=user,
        ally_id="00000000-0000-4000-8000-000000000003",
    )
    stamp = timezone.now()
    Ally.objects.filter(pk=oldest.pk).update(created_at=stamp - timedelta(seconds=1))
    Ally.objects.filter(pk__in=[tie_low.pk, tie_high.pk]).update(created_at=stamp)

    with django_assert_num_queries(2):
        rows = list_allies(user=user, workspace_id=workspace.id)
        serialized = [_response(ally) for ally in rows]

    assert [item.id for item in serialized] == [
        tie_high.id,
        tie_low.id,
        oldest.id,
    ]
    stranger = User.objects.create_user()
    with pytest.raises(WorkspaceAccessDenied):
        list_allies(user=stranger, workspace_id=workspace.id)


@pytest.mark.django_db
def test_cleanup_deletes_only_expired_unconsumed_attempts(account):
    user, workspace = account
    expired = begin_onboarding(
        **payload(),
        browser_binding=b"expired-browser",
        generation_identity="test:expired-cleanup",
        provider=GreetingProvider(),
    )
    retained = begin_onboarding(
        **payload(),
        browser_binding=b"retained-browser",
        generation_identity="test:retained-cleanup",
        provider=GreetingProvider(),
    )
    consumed = begin_onboarding(
        **payload(),
        browser_binding=b"consumed-browser",
        generation_identity="test:consumed-cleanup",
        provider=GreetingProvider(),
    )
    create_ally(
        **payload(),
        user=user,
        workspace_id=workspace.id,
        onboarding_attempt=consumed.attempt_token,
        reply="Retain this exchange for handoff.",
        browser_binding=b"consumed-browser",
        idempotency_key="stable-cleanup-key-1",
    )
    OnboardingAttempt.objects.filter(
        attempt_token_digest=digest_value(expired.attempt_token)
    ).update(expires_at=timezone.now() - timedelta(seconds=1))
    OnboardingAttempt.objects.filter(
        attempt_token_digest=digest_value(consumed.attempt_token)
    ).update(expires_at=timezone.now() - timedelta(seconds=1))

    assert cleanup_expired_onboarding_attempts() == 1
    assert not OnboardingAttempt.objects.filter(
        attempt_token_digest=digest_value(expired.attempt_token)
    ).exists()
    assert OnboardingAttempt.objects.filter(
        attempt_token_digest=digest_value(retained.attempt_token)
    ).exists()
    assert OnboardingAttempt.objects.filter(
        attempt_token_digest=digest_value(consumed.attempt_token)
    ).exists()
