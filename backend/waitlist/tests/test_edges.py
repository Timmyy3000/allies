import json
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse
from django.test import Client, override_settings
from django.utils import timezone

from waitlist.api.controllers import _refresh_capability_response, _waitlist_error
from waitlist.capabilities import (
    capability_digest,
    new_capability,
    refresh_capability,
    resolve_capability,
    set_capability_cookie,
)
from waitlist.exceptions import (
    DraftStale,
    DraftUnavailable,
    GenerationUnavailable,
    IdempotencyConflict,
    InvalidDraftState,
    OperationInProgress,
    Throttled,
    WaitlistValidationError,
)
from waitlist.idempotency import mark_succeeded, reserve_operation
from waitlist.models import (
    DraftLifecycle,
    OperationKind,
    WaitlistDraft,
    WaitlistOperation,
)
from waitlist.providers.base import ProviderUnavailableError
from waitlist.providers.fake import FakeGreetingProvider
from waitlist.services.drafts import (
    create_or_resume_draft,
    revoke_expired_capability,
    update_configuration,
)
from waitlist.services.email import emails_match, normalize_email
from waitlist.services.generation import generate_greeting, validate_output
from waitlist.services.join import mask_email


@override_settings(ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32)
def test_capability_helpers_never_return_digest_for_missing_cookie(rf):
    request = rf.get("/api/v1/waitlist/session")
    resolution = resolve_capability(request)
    assert resolution.digest is None
    raw = new_capability()
    assert raw not in capability_digest(raw)
    response = Client().get("/", HTTP_HOST="testserver")
    set_capability_cookie(response, raw)
    assert raw in response.cookies["allies_waitlist_capability"].value

    malformed = rf.get("/api/v1/waitlist/session")
    malformed.COOKIES["allies_waitlist_capability"] = "x" * 513
    rotated = resolve_capability(malformed)
    assert rotated.digest is None
    assert rotated.rotate_cookie is True
    assert rotated.issue_cookie


@override_settings(ALLIES_WAITLIST_ENABLED=True, ALLIES_WAITLIST_CAPABILITY_KEY="")
def test_enabled_waitlist_without_explicit_capability_key_fails_closed():
    with pytest.raises(DraftUnavailable):
        new_capability()
    with pytest.raises(DraftUnavailable):
        capability_digest("raw-capability")


@override_settings(
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_CAPABILITY_TTL_SECONDS=1,
)
def test_capability_rejects_forged_and_expired_cookies(rf, monkeypatch):
    forged = rf.get("/api/v1/waitlist/session")
    forged.COOKIES["allies_waitlist_capability"] = "attacker-chosen"
    forged_resolution = resolve_capability(forged)
    assert forged_resolution.digest is None
    assert forged_resolution.rotate_cookie is True

    monkeypatch.setattr("waitlist.capabilities.time.time", lambda: 100)
    raw = new_capability()
    monkeypatch.setattr("waitlist.capabilities.time.time", lambda: 102)
    expired = rf.get("/api/v1/waitlist/session")
    expired.COOKIES["allies_waitlist_capability"] = raw
    expired_resolution = resolve_capability(expired)
    assert expired_resolution.digest is None
    assert expired_resolution.rotate_cookie is True
    assert expired_resolution.expired_digest == capability_digest(raw)


@override_settings(
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_CAPABILITY_TTL_SECONDS=2,
)
def test_capability_accepts_small_cross_instance_clock_skew(rf, monkeypatch):
    monkeypatch.setattr("waitlist.capabilities.time.time", lambda: 100)
    raw = new_capability()
    digest = capability_digest(raw)

    monkeypatch.setattr("waitlist.capabilities.time.time", lambda: 99.5)
    request = rf.get("/api/v1/waitlist/session")
    request.COOKIES["allies_waitlist_capability"] = raw

    assert resolve_capability(request).digest == digest


@override_settings(
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_CAPABILITY_TTL_SECONDS=2,
)
def test_capability_refresh_preserves_digest_and_extends_validity(rf, monkeypatch):
    monkeypatch.setattr("waitlist.capabilities.time.time", lambda: 100)
    raw = new_capability()
    digest = capability_digest(raw)

    monkeypatch.setattr("waitlist.capabilities.time.time", lambda: 101)
    refreshed = refresh_capability(raw)
    assert refreshed != raw
    assert capability_digest(refreshed) == digest

    monkeypatch.setattr("waitlist.capabilities.time.time", lambda: 102.5)
    old_request = rf.get("/api/v1/waitlist/session")
    old_request.COOKIES["allies_waitlist_capability"] = raw
    assert resolve_capability(old_request).digest is None
    refreshed_request = rf.get("/api/v1/waitlist/session")
    refreshed_request.COOKIES["allies_waitlist_capability"] = refreshed
    assert resolve_capability(refreshed_request).digest == digest


@override_settings(
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_CAPABILITY_TTL_SECONDS=2,
)
def test_refresh_response_preserves_validated_capability_across_ttl_boundary(
    rf, monkeypatch
):
    monkeypatch.setattr("waitlist.capabilities.time.time", lambda: 100)
    raw = new_capability()
    digest = capability_digest(raw)
    request = rf.post("/api/v1/waitlist/draft")
    request.COOKIES["allies_waitlist_capability"] = raw

    # The request was accepted before expiry, but its response is produced
    # after a slow mutation crosses the cookie TTL.
    monkeypatch.setattr("waitlist.capabilities.time.time", lambda: 102.5)
    response = _refresh_capability_response(HttpResponse(), request)
    refreshed = response.cookies["allies_waitlist_capability"].value

    assert capability_digest(refreshed) == digest


def test_email_normalization_and_masking():
    assert normalize_email(" Person@Example.com ") == "person@example.com"
    assert emails_match("Person@example.com", "person@EXAMPLE.COM")
    assert mask_email("person@example.com") == "p****n@example.com"
    with pytest.raises(WaitlistValidationError):
        normalize_email("not-an-email")


@pytest.mark.django_db
@override_settings(ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32)
def test_idempotency_conflicts_and_expired_leases_are_safe():
    cap = capability_digest("operation")
    create_or_resume_draft(capability_digest=cap, raw_key="create")
    draft = WaitlistDraft.objects.get(capability_digest=cap)
    op, replay = reserve_operation(
        draft=draft,
        kind=OperationKind.CONFIGURE,
        raw_key="key",
        payload={"value": 1},
    )
    assert replay is False
    with pytest.raises(IdempotencyConflict):
        reserve_operation(
            draft=draft,
            kind=OperationKind.CONFIGURE,
            raw_key="key",
            payload={"value": 2},
        )
    with pytest.raises(OperationInProgress):
        reserve_operation(
            draft=draft,
            kind=OperationKind.CONFIGURE,
            raw_key="key",
            payload={"value": 1},
        )
    op.lease_expires_at = timezone.now() - timedelta(seconds=1)
    op.save(update_fields=("lease_expires_at",))
    reopened, replay = reserve_operation(
        draft=draft,
        kind=OperationKind.CONFIGURE,
        raw_key="key",
        payload={"value": 1},
    )
    assert replay is False and reopened.pk == op.pk


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_OPERATION_RECEIPT_CAP=2,
)
def test_operation_receipt_cap_preserves_replay_at_limit():
    cap = capability_digest("receipt-cap")
    create_or_resume_draft(capability_digest=cap, raw_key="create")
    draft = WaitlistDraft.objects.get(capability_digest=cap)

    with transaction.atomic():
        locked = WaitlistDraft.objects.select_for_update().get(pk=draft.pk)
        operation, replay = reserve_operation(
            draft=locked,
            kind=OperationKind.CONFIGURE,
            raw_key="configure-1",
            payload={"name": "Ari"},
        )
        assert replay is False
        mark_succeeded(
            operation,
            revision=locked.revision,
            lifecycle=locked.lifecycle,
        )

        replayed, replay = reserve_operation(
            draft=locked,
            kind=OperationKind.CONFIGURE,
            raw_key="configure-1",
            payload={"name": "Ari"},
        )
        assert replay is True
        assert replayed.pk == operation.pk

        with pytest.raises(Throttled, match="receipt limit"):
            reserve_operation(
                draft=locked,
                kind=OperationKind.REPLY,
                raw_key="reply-new",
                payload={"reply": "hello"},
            )

    assert draft.operations.count() == 2


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_OPERATION_RECEIPT_CAP=5,
    ALLIES_WAITLIST_OPERATION_RECEIPT_CAPS={
        "create": 1,
        "configure": 1,
        "generate": 1,
        "reply": 1,
        "join": 1,
    },
)
def test_operation_kind_quotas_keep_reply_and_join_available():
    cap = capability_digest("receipt-kind-quotas")
    create_or_resume_draft(capability_digest=cap, raw_key="create")
    draft = WaitlistDraft.objects.get(capability_digest=cap)

    with transaction.atomic():
        locked = WaitlistDraft.objects.select_for_update().get(pk=draft.pk)
        for kind, raw_key in (
            (OperationKind.CONFIGURE, "configure-1"),
            (OperationKind.GENERATE, "generate-1"),
        ):
            operation, replay = reserve_operation(
                draft=locked,
                kind=kind,
                raw_key=raw_key,
                payload={"revision": locked.revision},
            )
            assert replay is False
            mark_succeeded(
                operation,
                revision=locked.revision,
                lifecycle=locked.lifecycle,
            )

        # Exhausting the configuration and generation quotas does not consume
        # the reserved reply/join quotas.
        for kind, raw_key in (
            (OperationKind.REPLY, "reply-1"),
            (OperationKind.JOIN, "join-1"),
        ):
            operation, replay = reserve_operation(
                draft=locked,
                kind=kind,
                raw_key=raw_key,
                payload={"value": raw_key},
            )
            assert replay is False
            mark_succeeded(
                operation,
                revision=locked.revision,
                lifecycle=locked.lifecycle,
            )

        replayed, replay = reserve_operation(
            draft=locked,
            kind=OperationKind.JOIN,
            raw_key="join-1",
            payload={"value": "join-1"},
        )
        assert replay is True
        assert replayed.id is not None

    assert draft.operations.count() == 5


@pytest.mark.django_db
@override_settings(ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32)
def test_draft_validation_stale_and_invalid_state():
    cap = capability_digest("draft-edge")
    create_or_resume_draft(capability_digest=cap, raw_key="create")
    with pytest.raises(DraftStale):
        update_configuration(
            capability_digest=cap,
            revision=99,
            changes={"name": "A"},
            raw_key="stale",
        )
    with pytest.raises(WaitlistValidationError):
        update_configuration(
            capability_digest=cap,
            revision=1,
            changes={"appearance_key": "only"},
            raw_key="invalid",
        )
    with pytest.raises(WaitlistValidationError):
        update_configuration(
            capability_digest=cap,
            revision=1,
            changes={"name": "unsafe\x00name"},
            raw_key="nul",
        )
    with pytest.raises(WaitlistValidationError, match="configuration is empty"):
        update_configuration(
            capability_digest=cap,
            revision=1,
            changes={},
            raw_key="empty",
        )
    draft = WaitlistDraft.objects.get(capability_digest=cap)
    assert draft.revision == 1
    assert not draft.operations.filter(kind="configure").exists()
    draft.lifecycle = DraftLifecycle.EXPIRED
    draft.save(update_fields=("lifecycle",))
    with pytest.raises(DraftUnavailable):
        update_configuration(
            capability_digest=cap,
            revision=1,
            changes={"name": "A"},
            raw_key="expired",
        )


@pytest.mark.django_db
@override_settings(ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32)
def test_create_resume_reuses_one_canonical_receipt_for_new_keys(monkeypatch):
    admitted = []

    def record_admission():
        admitted.append(
            WaitlistDraft.objects.filter(
                capability_digest=capability_digest("create-boundary")
            ).exists()
        )

    monkeypatch.setattr(
        "waitlist.services.drafts.admit_global_creation", record_admission
    )
    cap = capability_digest("create-boundary")
    first = create_or_resume_draft(capability_digest=cap, raw_key="create-1")

    for raw_key in ("create-2", "create-3", "create-4"):
        assert create_or_resume_draft(capability_digest=cap, raw_key=raw_key) == first

    draft = WaitlistDraft.objects.get(capability_digest=cap)
    assert draft.operations.filter(kind="create").count() == 1
    assert admitted == [True]


@pytest.mark.django_db
@override_settings(ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32)
def test_expired_capability_unbinds_joined_draft_without_expiring_claim():
    cap = capability_digest("joined-capability")
    create_or_resume_draft(capability_digest=cap, raw_key="create")
    draft = WaitlistDraft.objects.get(capability_digest=cap)
    draft.lifecycle = DraftLifecycle.PENDING_CLAIM
    draft.email_normalized = "person@example.com"
    draft.consent_version = "consent-v1"
    draft.joined_at = timezone.now()
    draft.expires_at = timezone.now() + timedelta(days=1)
    draft.save()

    assert revoke_expired_capability(capability_digest=cap, force=True)

    draft.refresh_from_db()
    assert draft.lifecycle == DraftLifecycle.PENDING_CLAIM
    assert draft.capability_digest is None
    assert draft.email_normalized == "person@example.com"


@pytest.mark.parametrize(
    ("text", "allowed"),
    [
        ("Let's discuss your workspace goals.", True),
        ("Workspace access settings are configurable.", True),
        ("I can't access your files.", True),
        ("I haven't created an account.", True),
        ("I have not created an account.", True),
        ("No account was created.", True),
        ("Your account was not created.", True),
        ("We can plan your Ally launch.", True),
        ("I created your account.", False),
        ("I've created your account.", False),
        ("We’ve created your workspace.", False),
        ("I'm your assistant.", False),
        ("I'm an assistant.", False),
        ("I'm a helpful assistant.", False),
        ("I'm your personal assistant.", False),
        ("I'm not your assistant.", True),
        ("I’m not an assistant.", True),
        ("Your workspace is ready.", False),
        ("Your account is waiting.", False),
        ("Your workspace is not ready.", True),
        ("I accessed your workspace.", False),
        ("I can access your files.", False),
        ("I used a tool to send a message.", False),
        ("An account was created.", False),
        ("I can create your account.", False),
        ("I will set up your workspace.", False),
        ("I'll send your message.", False),
        ("I've gone ahead and created your account.", False),
        ("I successfully created your workspace.", False),
        ("I can go ahead and create your account.", False),
        ("<img src=x onerror=alert(1)>", False),
        ("<a href='https://evil.example'>click</a>", False),
    ],
)
def test_output_policy_rejects_action_claims_but_allows_noun_discussion(text, allowed):
    if allowed:
        assert validate_output(text) == text
    else:
        with pytest.raises(WaitlistValidationError):
            validate_output(text)


@pytest.mark.parametrize("field", ["configuration", "email", "consent_version", "text"])
def test_service_validation_errors_publish_field_details(field):
    response = _waitlist_error(WaitlistValidationError("invalid input", field=field))

    assert response.status_code == 422
    assert json.loads(response.content)["data"] == {
        "code": "validation_error",
        "details": {"errors": [{"field": field, "code": "value_error"}]},
    }


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32,
    ALLIES_WAITLIST_PROVIDER_ENABLED=True,
    ALLIES_WAITLIST_PROVIDER="fake",
)
def test_generation_rejects_provider_output_and_invalid_lifecycle():
    cap = capability_digest("generation-edge")
    create_or_resume_draft(capability_digest=cap, raw_key="create")
    draft = WaitlistDraft.objects.get(capability_digest=cap)
    with pytest.raises(InvalidDraftState):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="invalid",
            provider=FakeGreetingProvider(response="safe"),
        )
    assert not WaitlistOperation.objects.filter(
        draft=draft, kind=OperationKind.GENERATE
    ).exists()
    update_configuration(
        capability_digest=cap,
        revision=1,
        changes={
            "name": "A",
            "job": "J",
            "appearance_catalog_version": "v",
            "appearance_key": "k",
        },
        raw_key="config",
    )
    draft.refresh_from_db()
    # A pre-provider rejection does not consume the key or a receipt, so the
    # same key can retry after the draft becomes generation-ready.
    with pytest.raises(GenerationUnavailable):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="invalid",
            provider=FakeGreetingProvider(response="I created an account"),
        )
    with pytest.raises(GenerationUnavailable):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="unsafe",
            provider=FakeGreetingProvider(response="I created an account"),
        )
    draft.refresh_from_db()
    assert draft.greeting_text == ""
    with pytest.raises(GenerationUnavailable):
        generate_greeting(
            capability_digest=cap,
            revision=draft.revision,
            raw_key="down",
            provider=FakeGreetingProvider(error=ProviderUnavailableError()),
        )


@pytest.mark.django_db
@override_settings(
    ALLIES_WAITLIST_ENABLED=True, ALLIES_WAITLIST_CAPABILITY_KEY="k" * 32
)
def test_api_validation_and_missing_origin():
    cache.clear()
    client = Client(enforce_csrf_checks=True)
    client.get(
        "/api/v1/waitlist/session",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    csrf = client.cookies["csrftoken"].value
    payload = {"revision": 1, "name": "A"}
    response = client.patch(
        "/api/v1/waitlist/draft/configuration",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY="config",
    )
    assert response.status_code == 403
