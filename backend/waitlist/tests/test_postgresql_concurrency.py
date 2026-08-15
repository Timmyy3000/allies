from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from django.core.cache import cache
from django.db import close_old_connections, connection
from django.test import override_settings
from django.utils import timezone

from auths.models import ExternalIdentity, User
from waitlist.capabilities import capability_digest
from waitlist.exceptions import ClaimRejected, OperationInProgress
from waitlist.models import DraftLifecycle, WaitlistDraft
from waitlist.services.claim import claim_waitlist_draft
from waitlist.services.drafts import create_or_resume_draft, update_configuration
from waitlist.services.generation import generate_greeting


def _require_postgresql() -> None:
    if connection.vendor != "postgresql":
        pytest.skip("row-lock race requires PostgreSQL")


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
@override_settings(ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32)
def test_same_capability_create_converges_under_postgresql_race():
    _require_postgresql()
    digest = capability_digest("postgres-create-race")

    def create_once(key: str):
        close_old_connections()
        try:
            return create_or_resume_draft(
                capability_digest=digest, raw_key=key
            ).result_revision
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        revisions = list(pool.map(create_once, ("create-a", "create-b")))

    assert revisions == [1, 1]
    assert WaitlistDraft.objects.filter(capability_digest=digest).count() == 1


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
@override_settings(
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_PROVIDER_ENABLED=True,
)
def test_generation_has_one_live_provider_call_per_draft_under_postgresql_race():
    _require_postgresql()
    cache.clear()
    digest = capability_digest("postgres-generation-race")
    create_or_resume_draft(capability_digest=digest, raw_key="create")
    update_configuration(
        capability_digest=digest,
        revision=1,
        changes={
            "name": "Ari",
            "job": "Planning",
            "appearance_catalog_version": "v1",
            "appearance_key": "calm",
        },
        raw_key="configure",
    )
    draft = WaitlistDraft.objects.get(capability_digest=digest)
    provider_started = Event()
    release_provider = Event()

    class BlockingProvider:
        def generate(self, request):
            provider_started.set()
            assert release_provider.wait(timeout=10)
            return "Safe greeting"

    def generate_first():
        close_old_connections()
        try:
            return generate_greeting(
                capability_digest=digest,
                revision=draft.revision,
                raw_key="generate-a",
                provider=BlockingProvider(),
            )
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(generate_first)
        assert provider_started.wait(timeout=10)
        try:
            with pytest.raises(OperationInProgress):
                generate_greeting(
                    capability_digest=digest,
                    revision=draft.revision,
                    raw_key="generate-b",
                    provider=BlockingProvider(),
                )
        finally:
            release_provider.set()
        assert first.result(timeout=15).result_lifecycle == "greeting_ready"


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
def test_claim_has_one_winner_under_postgresql_race():
    _require_postgresql()
    now = timezone.now()
    draft = WaitlistDraft.objects.create(
        lifecycle=DraftLifecycle.PENDING_CLAIM,
        email_normalized="person@example.com",
        consent_version="v1",
        joined_at=now,
        expires_at=now + timedelta(hours=1),
    )
    users = [User.objects.create_user(), User.objects.create_user()]
    for index, user in enumerate(users):
        ExternalIdentity.objects.create(
            user=user,
            provider="google",
            subject=f"postgres-claim-{index}",
            email_snapshot="person@example.com",
            email_verified=True,
            email_verified_at=now,
            email_verification_source="google",
        )

    def claim_once(user: User) -> str:
        close_old_connections()
        try:
            try:
                claim_waitlist_draft(user=user, draft=draft, confirmed=True)
                return "claimed"
            except ClaimRejected:
                return "rejected"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim_once, users))

    assert sorted(results) == ["claimed", "rejected"]
    draft.refresh_from_db()
    assert draft.lifecycle == DraftLifecycle.CLAIMED
    assert draft.claimed_by_id in {user.pk for user in users}
