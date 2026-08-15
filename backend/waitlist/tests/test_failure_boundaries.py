"""Risk-focused waitlist coverage for failure, retention, and privacy seams."""

from datetime import timedelta

import pytest
from django.core import management
from django.core.cache import cache
from django.core.management.base import CommandError
from django.http import HttpResponse
from django.test import Client, override_settings
from django.utils import timezone

from auths.models import ExternalIdentity, User
from waitlist.admission import AdmissionUnavailable
from waitlist.capabilities import capability_digest, clear_capability_cookie
from waitlist.exceptions import (
    ClaimRejected,
    DraftStale,
    GenerationUnavailable,
    GenerationUnknown,
    OperationInProgress,
    Throttled,
    WaitlistValidationError,
)
from waitlist.idempotency import reserve_operation
from waitlist.models import (
    DraftLifecycle,
    OperationKind,
    OperationStatus,
    WaitlistDraft,
    WaitlistOperation,
)
from waitlist.providers.base import (
    GreetingRequest,
    ProviderBilledError,
    ProviderUnavailableError,
    ProviderUnknownError,
)
from waitlist.providers.fake import FakeGreetingProvider
from waitlist.services.claim import claim_waitlist_draft
from waitlist.services.cleanup import cleanup_waitlist_drafts
from waitlist.services.drafts import create_or_resume_draft, update_configuration
from waitlist.services.email import emails_match, normalize_email
from waitlist.services.generation import generate_greeting, validate_output
from waitlist.services.join import mask_email
from waitlist.tasks import cleanup_waitlist_drafts_task


def _configured_draft(suffix: str):
    cap = capability_digest(f"failure-{suffix}")
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
@override_settings(ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32)
def test_generation_replays_unknown_and_failed_receipts():
    cache.clear()
    cap, draft = _configured_draft("replays")
    with pytest.raises(GenerationUnknown):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="unknown",
            provider=FakeGreetingProvider(error=ProviderUnknownError()),
        )
    with pytest.raises(GenerationUnknown):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="unknown",
            provider=FakeGreetingProvider(response="ignored"),
        )

    cap, draft = _configured_draft("failed-replay")
    with pytest.raises(GenerationUnavailable):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="failed",
            provider=FakeGreetingProvider(error=ProviderUnavailableError()),
        )
    with pytest.raises(GenerationUnavailable):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="failed",
            provider=FakeGreetingProvider(response="ignored"),
        )


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_GENERATION_CAPABILITY_BUDGET_PER_MINUTE=1,
)
def test_provider_unavailable_does_not_burn_generation_budget():
    cache.clear()
    cap, draft = _configured_draft("budget-refund")
    with pytest.raises(GenerationUnavailable):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="provider-failure",
            provider=FakeGreetingProvider(error=ProviderUnavailableError()),
        )

    acknowledgement = generate_greeting(
        capability_digest=cap,
        revision=draft.revision,
        raw_key="provider-retry",
        provider=FakeGreetingProvider(response="safe greeting"),
    )
    assert acknowledgement.operation == OperationKind.GENERATE


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_GENERATION_CAPABILITY_BUDGET_PER_MINUTE=1,
)
def test_billed_provider_response_keeps_generation_budget_reserved():
    cache.clear()
    cap, draft = _configured_draft("billed-budget")
    with pytest.raises(GenerationUnavailable):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="billed-failure",
            provider=FakeGreetingProvider(
                error=ProviderBilledError("provider response malformed")
            ),
        )

    with pytest.raises(Throttled, match="capability budget"):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="billed-retry",
            provider=FakeGreetingProvider(response="must not run"),
        )


@pytest.mark.django_db
@override_settings(ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32)
def test_generation_allows_only_one_live_operation_per_draft():
    cache.clear()
    cap, draft = _configured_draft("single-live")
    operation, replay = reserve_operation(
        draft=draft,
        kind=OperationKind.GENERATE,
        raw_key="first-live",
        payload={"revision": draft.revision},
    )
    assert replay is False

    with pytest.raises(OperationInProgress):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="second-live",
            provider=FakeGreetingProvider(response="must not run"),
        )

    operation.lease_expires_at = timezone.now() - timedelta(seconds=1)
    operation.save(update_fields=("lease_expires_at",))
    with pytest.raises(Throttled, match="cooldown"):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="after-expiry",
            provider=FakeGreetingProvider(response="must not run"),
        )
    operation.refresh_from_db()
    assert operation.status == OperationStatus.OUTCOME_UNKNOWN


@pytest.mark.django_db
@override_settings(ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32)
def test_transient_generation_admission_does_not_persist_fresh_receipt(monkeypatch):
    cache.clear()
    cap, draft = _configured_draft("transient-admission")
    monkeypatch.setattr(
        "waitlist.services.generation.acquire_generation",
        lambda _digest: (_ for _ in ()).throw(
            Throttled("generation concurrency limit reached")
        ),
    )
    with pytest.raises(Throttled, match="concurrency"):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="retryable-admission",
            provider=FakeGreetingProvider(response="must not run"),
        )
    assert not WaitlistOperation.objects.filter(
        draft=draft, kind=OperationKind.GENERATE
    ).exists()

    # No provider call occurred, so the same key can safely retry once
    # admission recovers instead of replaying a permanently failed receipt.
    monkeypatch.undo()
    acknowledgement = generate_greeting(
        capability_digest=cap,
        revision=draft.revision,
        raw_key="retryable-admission",
        provider=FakeGreetingProvider(response="safe greeting"),
    )
    assert acknowledgement.operation == OperationKind.GENERATE


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_GENERATION_ATTEMPT_COOLDOWN_SECONDS=60,
)
def test_generation_cooldown_throttle_does_not_consume_receipt_quota():
    cache.clear()
    cap, draft = _configured_draft("cooldown-receipt")
    with pytest.raises(GenerationUnknown):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="unknown-first",
            provider=FakeGreetingProvider(error=ProviderUnknownError()),
        )

    with pytest.raises(Throttled, match="cooldown"):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="cooldown-fresh",
            provider=FakeGreetingProvider(response="must not run"),
        )
    assert (
        WaitlistOperation.objects.filter(
            draft=draft, kind=OperationKind.GENERATE
        ).count()
        == 1
    )


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_GENERATION_ATTEMPT_COOLDOWN_SECONDS=0,
)
def test_expired_generation_lease_recovers_with_policy_permitted_fresh_key():
    cache.clear()
    cap, draft = _configured_draft("expired-recovery")
    stale, replay = reserve_operation(
        draft=draft,
        kind=OperationKind.GENERATE,
        raw_key="stale-provider-lease",
        payload={"revision": draft.revision},
    )
    assert replay is False
    stale.lease_expires_at = timezone.now() - timedelta(seconds=1)
    stale.save(update_fields=("lease_expires_at",))

    result = generate_greeting(
        capability_digest=cap,
        revision=draft.revision,
        raw_key="explicit-recovery-retry",
        provider=FakeGreetingProvider(response="safe greeting"),
    )
    stale.refresh_from_db()
    assert result.operation == OperationKind.GENERATE
    assert stale.status == OperationStatus.OUTCOME_UNKNOWN


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_PROVIDER_ENABLED=False,
)
def test_generation_provider_disabled_unexpected_and_stale_results(monkeypatch):
    cache.clear()
    cap, draft = _configured_draft("disabled")
    with pytest.raises(GenerationUnavailable):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="disabled",
        )

    # A provider crash is deliberately persisted as an unknown outcome.
    cap, draft = _configured_draft("unexpected")

    class UnexpectedProvider:
        def generate(self, request):
            raise RuntimeError("connection reset")

    with pytest.raises(GenerationUnknown):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="unexpected",
            provider=UnexpectedProvider(),
        )
    assert (
        WaitlistDraft.objects.get(capability_digest=cap)
        .operations.filter(status=OperationStatus.OUTCOME_UNKNOWN)
        .exists()
    )

    class RevisionChangingProvider:
        def __init__(self, target):
            self.target = target

        def generate(self, request):
            WaitlistDraft.objects.filter(pk=self.target.pk).update(
                revision=self.target.revision + 1
            )
            return "safe greeting"

    cap, draft = _configured_draft("stale")
    # Rebind the provider's target after creating the draft used above.
    provider = RevisionChangingProvider(draft)
    with pytest.raises(DraftStale):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="stale",
            provider=provider,
        )
    with pytest.raises(DraftStale):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="stale",
            provider=FakeGreetingProvider(response="must not run"),
        )


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_PROVIDER_ENABLED=True,
    ALLIES_WAITLIST_PROVIDER="fake",
)
def test_generation_reuses_current_greeting_and_marks_admission_failure(monkeypatch):
    cache.clear()
    cap, draft = _configured_draft("current")
    first_revision = draft.revision
    first = generate_greeting(
        capability_digest=cap,
        revision=draft.revision,
        raw_key="first",
        provider=FakeGreetingProvider(response="safe greeting"),
    )
    draft.refresh_from_db()
    second = generate_greeting(
        capability_digest=cap,
        revision=draft.revision,
        raw_key="second",
        provider=FakeGreetingProvider(error=RuntimeError("must not call")),
    )
    assert first.result_lifecycle == second.result_lifecycle == "greeting_ready"
    crashed, _ = reserve_operation(
        draft=draft,
        kind=OperationKind.GENERATE,
        raw_key="later-crash",
        payload={"revision": draft.revision},
    )
    crashed.lease_expires_at = timezone.now() - timedelta(seconds=1)
    crashed.save(update_fields=("lease_expires_at",))
    replayed_first = generate_greeting(
        capability_digest=cap,
        revision=first_revision,
        raw_key="first",
        provider=FakeGreetingProvider(error=RuntimeError("must not run")),
    )
    assert replayed_first == first

    cap, draft = _configured_draft("admission-failure")
    monkeypatch.setattr(
        "waitlist.services.generation.acquire_generation",
        lambda _digest: (_ for _ in ()).throw(AdmissionUnavailable("cache down")),
    )
    with pytest.raises(GenerationUnavailable):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="admission-failure",
            provider=FakeGreetingProvider(response="safe"),
        )


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_PROVIDER_ENABLED=True,
    ALLIES_WAITLIST_PROVIDER="fake",
    ALLIES_WAITLIST_OPERATION_RECEIPT_CAPS={
        "create": 1,
        "configure": 16,
        "generate": 1,
        "reply": 15,
        "join": 16,
    },
)
def test_current_greeting_retrieval_does_not_consume_generate_receipts():
    cap, draft = _configured_draft("current-receipt-cap")
    first = generate_greeting(
        capability_digest=cap,
        revision=draft.revision,
        raw_key="first-current",
        provider=FakeGreetingProvider(response="safe greeting"),
    )
    draft.refresh_from_db()

    for index in range(20):
        assert (
            generate_greeting(
                capability_digest=cap,
                revision=draft.revision,
                raw_key=f"retrieve-current-{index}",
                provider=FakeGreetingProvider(error=RuntimeError("must not call")),
            )
            == first
        )

    assert (
        WaitlistOperation.objects.filter(
            draft=draft, kind=OperationKind.GENERATE
        ).count()
        == 1
    )


@pytest.mark.django_db
@override_settings(ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32)
def test_claim_rejects_unauthenticated_expired_and_unverified_claims():
    now = timezone.now()
    draft = WaitlistDraft.objects.create(
        capability_digest=capability_digest("claim-boundary"),
        lifecycle=DraftLifecycle.PENDING_CLAIM,
        email_normalized="person@example.com",
        consent_version="v1",
        joined_at=now,
        expires_at=now + timedelta(hours=1),
    )
    with pytest.raises(ClaimRejected):
        claim_waitlist_draft(user=None, draft=draft, confirmed=True)

    inactive = User.objects.create_user(is_active=False)
    with pytest.raises(ClaimRejected):
        claim_waitlist_draft(user=inactive, draft=draft, confirmed=True)
    active = User.objects.create_user()
    with pytest.raises(ClaimRejected):
        claim_waitlist_draft(user=active, draft=draft, confirmed=False)
    with pytest.raises(ClaimRejected):
        claim_waitlist_draft(user=active, draft="missing", confirmed=True)

    draft.lifecycle = DraftLifecycle.CONFIGURING
    draft.save(update_fields=("lifecycle",))
    with pytest.raises(ClaimRejected):
        claim_waitlist_draft(user=active, draft=draft, confirmed=True)

    draft.lifecycle = DraftLifecycle.PENDING_CLAIM
    draft.expires_at = now - timedelta(seconds=1)
    draft.save(update_fields=("lifecycle", "expires_at"))
    with pytest.raises(ClaimRejected):
        claim_waitlist_draft(user=active, draft=draft, confirmed=True)

    draft.expires_at = now + timedelta(hours=1)
    draft.save(update_fields=("expires_at",))
    ExternalIdentity.objects.create(
        user=active,
        provider="google",
        subject="wrong-email",
        email_snapshot="other@example.com",
        email_verified=True,
        email_verified_at=now,
        email_verification_source="google",
    )
    with pytest.raises(ClaimRejected):
        claim_waitlist_draft(user=active, draft=draft, confirmed=True)


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_JOINED_RETENTION_SECONDS=3600,
)
def test_cleanup_retention_task_and_command_are_bounded():
    with pytest.raises(ValueError):
        cleanup_waitlist_drafts(batch_size=0)
    now = timezone.now()
    abandoned = WaitlistDraft.objects.create(
        capability_digest=capability_digest("cleanup-abandoned"),
        expires_at=now - timedelta(seconds=1),
    )
    joined = WaitlistDraft.objects.create(
        capability_digest=capability_digest("cleanup-joined"),
        lifecycle=DraftLifecycle.PENDING_CLAIM,
        email_normalized="person@example.com",
        consent_version="v1",
        joined_at=now - timedelta(hours=2),
        expires_at=now - timedelta(seconds=1),
    )
    result = cleanup_waitlist_drafts(batch_size=1)
    assert result.deleted == result.abandoned == 1
    assert WaitlistDraft.objects.filter(pk=joined.pk).exists()
    assert not WaitlistDraft.objects.filter(pk=abandoned.pk).exists()

    result = cleanup_waitlist_drafts_task.run(batch_size=100)
    assert result == {"deleted": 1, "abandoned": 0, "joined": 1}
    assert not WaitlistDraft.objects.filter(pk=joined.pk).exists()

    with pytest.raises(CommandError):
        management.call_command("cleanup_waitlist_drafts", batch_size=0)


@pytest.mark.django_db
@override_settings(ALLIES_WAITLIST_JOINED_RETENTION_SECONDS=None)
def test_expired_joined_draft_respects_disabled_joined_cleanup():
    now = timezone.now()
    joined = WaitlistDraft.objects.create(
        lifecycle=DraftLifecycle.EXPIRED,
        email_normalized="person@example.com",
        consent_version="v1",
        joined_at=now - timedelta(days=1),
        expires_at=now - timedelta(seconds=1),
    )

    assert cleanup_waitlist_drafts().deleted == 0
    assert WaitlistDraft.objects.filter(pk=joined.pk).exists()


def _waitlist_client():
    cache.clear()
    client = Client(enforce_csrf_checks=True)
    client.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    return client


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_ENABLED=True, ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32
)
def test_api_mutation_guards_and_admission_errors(monkeypatch):
    client = _waitlist_client()
    csrf = client.cookies["csrftoken"].value
    common = {
        "HTTP_HOST": "testserver",
        "HTTP_ORIGIN": "http://localhost:3000",
        "HTTP_X_CSRFTOKEN": csrf,
    }
    payloads = {
        "/api/v1/waitlist/draft/configuration": '{"revision":1,"name":"A"}',
        "/api/v1/waitlist/draft/greeting": '{"revision":1}',
        "/api/v1/waitlist/draft/reply": '{"revision":1,"text":"reply"}',
        "/api/v1/waitlist/draft/join": '{"revision":1,"email":"a@example.com","consent_version":"v1"}',
    }
    for path, body in payloads.items():
        response = (
            client.patch(path, data=body, content_type="application/json", **common)
            if "configuration" in path
            else client.post(path, data=body, content_type="application/json", **common)
        )
        assert response.status_code == 422

    client.cookies.pop("allies_waitlist_capability")
    for path, body in payloads.items():
        response = (
            client.patch(
                path,
                data=body,
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="missing-cap",
                **common,
            )
            if "configuration" in path
            else client.post(
                path,
                data=body,
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="missing-cap",
                **common,
            )
        )
        assert response.status_code == 404

    monkeypatch.setattr(
        "waitlist.api.controllers.admit_bootstrap",
        lambda _identity: (_ for _ in ()).throw(Throttled("slow down")),
    )
    assert (
        client.get(
            "/api/v1/waitlist/session",
            HTTP_HOST="testserver",
            HTTP_ORIGIN="http://localhost:3000",
        ).status_code
        == 429
    )


def test_validation_privacy_and_string_boundaries():
    """Exercise the small boundary helpers that protect persisted output."""

    for invalid in (None, "x" * 255):
        with pytest.raises(WaitlistValidationError):
            normalize_email(invalid)
    assert emails_match("not-an-email", "person@example.com") is False
    assert mask_email("a@example.com") == "*@example.com"
    assert mask_email("ab@example.com") == "a*@example.com"

    for invalid in (None, "", "safe\x00text"):
        with pytest.raises(WaitlistValidationError):
            validate_output(invalid)
    with pytest.raises(ProviderUnavailableError):
        FakeGreetingProvider(error=RuntimeError("boom")).generate(
            GreetingRequest("Ari", "Planning", "")
        )

    draft = WaitlistDraft(public_id="wld-boundary")
    assert str(draft) == "wld-boundary"
    operation = WaitlistOperation(draft=draft, kind=OperationKind.GENERATE)
    assert str(operation) == "wld-boundary:generate"
    response = HttpResponse()
    clear_capability_cookie(response)
    assert response.cookies["allies_waitlist_capability"]["max-age"] == 0
