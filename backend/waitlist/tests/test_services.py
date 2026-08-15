from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from auths.models import ExternalIdentity, User
from waitlist.capabilities import capability_digest
from waitlist.exceptions import (
    ClaimRejected,
    GenerationUnknown,
    Throttled,
    WaitlistUnavailable,
    WaitlistValidationError,
)
from waitlist.models import DraftLifecycle, OperationStatus, WaitlistDraft
from waitlist.providers.base import ProviderUnknownError
from waitlist.providers.fake import FakeGreetingProvider
from waitlist.services.claim import claim_waitlist_draft
from waitlist.services.cleanup import cleanup_waitlist_drafts
from waitlist.services.drafts import create_or_resume_draft, update_configuration
from waitlist.services.generation import generate_greeting, validate_output
from waitlist.services.join import join_waitlist
from waitlist.services.reply import record_reply


def _configured_draft(suffix: str = ""):
    cap = capability_digest(f"cap-{suffix}")
    create_or_resume_draft(capability_digest=cap, raw_key=f"create-{suffix}")
    update_configuration(
        capability_digest=cap,
        revision=1,
        changes={
            "name": "Ari",
            "appearance_catalog_version": "v1",
            "appearance_key": "calm",
            "job": "Planning",
        },
        raw_key=f"config-{suffix}",
    )
    return cap, WaitlistDraft.objects.get(capability_digest=cap)


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_PROVIDER_ENABLED=True,
    ALLIES_WAITLIST_PROVIDER="fake",
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
)
def test_generation_output_policy_and_unknown_recovery():
    cap, draft = _configured_draft("unknown")
    with pytest.raises(GenerationUnknown) as error:
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="unknown-1",
            provider=FakeGreetingProvider(error=ProviderUnknownError()),
        )
    assert error.value.code == "generation_outcome_unknown"
    draft.refresh_from_db()
    assert draft.greeting_text == ""
    assert draft.operations.filter(status=OperationStatus.OUTCOME_UNKNOWN).exists()
    with pytest.raises(Throttled) as error:
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="unknown-2",
            provider=FakeGreetingProvider(response="safe"),
        )
    assert error.value.code == "throttled"
    with pytest.raises(Throttled):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="unknown-2",
            provider=FakeGreetingProvider(response="must not run"),
        )
    with pytest.raises(WaitlistValidationError):
        validate_output("I created your account and sent a file")


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_PROVIDER_ENABLED=True,
    ALLIES_WAITLIST_PROVIDER="fake",
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_CONSENT_VERSION="v1",
    ALLIES_WAITLIST_JOINED_RETENTION_SECONDS=30 * 24 * 60 * 60,
)
def test_reply_join_claim_and_cleanup_boundaries():
    cap, draft = _configured_draft("claim")
    generate_greeting(
        capability_digest=cap,
        revision=draft.revision,
        raw_key="generate-claim",
        provider=FakeGreetingProvider(response="Hello"),
    )
    draft.refresh_from_db()
    with pytest.raises(WaitlistValidationError):
        record_reply(
            capability_digest=cap,
            revision=draft.revision,
            text="unsafe\x00reply",
            raw_key="reply-nul",
        )
    record_reply(
        capability_digest=cap,
        revision=draft.revision,
        text="reply",
        raw_key="reply-claim",
    )
    draft.refresh_from_db()
    assert draft.expires_at > timezone.now() + timedelta(days=6)
    with (
        override_settings(ALLIES_WAITLIST_JOINED_RETENTION_SECONDS=None),
        pytest.raises(WaitlistUnavailable),
    ):
        join_waitlist(
            capability_digest=cap,
            revision=draft.revision,
            email="person@example.com",
            consent_version="v1",
            raw_key="join-claim",
        )
    join_waitlist(
        capability_digest=cap,
        revision=draft.revision,
        email="person@example.com",
        consent_version="v1",
        raw_key="join-claim",
    )
    draft.refresh_from_db()
    user = User.objects.create_user()
    with pytest.raises(ClaimRejected):
        claim_waitlist_draft(user=user, draft=draft, confirmed=True)
    ExternalIdentity.objects.create(
        user=user,
        provider="google",
        subject="verified",
        email_snapshot="person@example.com",
        email_verified=True,
        email_verified_at=timezone.now(),
        email_verification_source="google",
    )
    claimed = claim_waitlist_draft(user=user, draft=draft, confirmed=True)
    assert claimed.lifecycle == DraftLifecycle.CLAIMED
    assert claimed.capability_digest is None
    # An abandoned draft is deleted while the claimed draft is protected.
    abandoned = WaitlistDraft.objects.create(
        capability_digest=capability_digest("abandoned"),
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    assert cleanup_waitlist_drafts().abandoned == 1
    assert not WaitlistDraft.objects.filter(pk=abandoned.pk).exists()
    assert WaitlistDraft.objects.filter(pk=claimed.pk).exists()
