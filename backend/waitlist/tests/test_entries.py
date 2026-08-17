import json

import pytest
from django.core.cache import cache
from django.test import Client, override_settings

from waitlist.exceptions import GenerationUnavailable
from waitlist.models import WaitlistEntry
from waitlist.providers.base import ProviderUnavailableError
from waitlist.services.entries import create_entry

SETTINGS = {
    "ALLIES_WAITLIST_ENABLED": True,
    "ALLIES_WAITLIST_PROVIDER_ENABLED": True,
    "ALLIES_WAITLIST_PROVIDER": "fake",
    "ALLIES_WAITLIST_TOKEN_KEY": "k" * 32,
    "ALLIES_WAITLIST_CONSENT_VERSION": "consent-v1",
    "ALLIES_WAITLIST_JOINED_RETENTION_SECONDS": 30 * 24 * 60 * 60,
}


def _headers():
    return {"HTTP_HOST": "testserver", "HTTP_ORIGIN": "http://localhost:3000"}


def _entry(attempt_id: str = "attempt-0000000000000001"):
    return {
        "attempt_id": attempt_id,
        "name": "Ari",
        "appearance_catalog_version": "v1",
        "appearance_key": "ghosty:fd304f",
        "job": "Planning",
        "personality": "Warm",
    }


@pytest.mark.django_db
@override_settings(**SETTINGS)
def test_create_and_complete_entry_without_browser_session():
    cache.clear()
    client = Client(enforce_csrf_checks=True)
    created = client.post(
        "/api/v1/waitlist/entries",
        data=json.dumps(_entry()),
        content_type="application/json",
        **_headers(),
    )
    assert created.status_code == 200
    token = created.json()["data"]["attempt_token"]
    assert created.json()["data"]["greeting"]
    assert "csrftoken" not in created.cookies

    completed = client.post(
        "/api/v1/waitlist/entries/complete",
        data=json.dumps(
            {
                "attempt_token": token,
                "reply": "Help me plan this week.",
                "email": "Person@Example.com",
                "consent_version": "consent-v1",
            }
        ),
        content_type="application/json",
        **_headers(),
    )
    assert completed.status_code == 200
    assert completed.json()["data"]["email"] == "p****n@example.com"
    entry = WaitlistEntry.objects.get()
    assert entry.reply_text == "Help me plan this week."
    assert entry.email_normalized == "person@example.com"


@pytest.mark.django_db
@override_settings(**SETTINGS)
def test_duplicate_create_and_complete_are_idempotent():
    cache.clear()
    client = Client(enforce_csrf_checks=True)
    first = client.post(
        "/api/v1/waitlist/entries",
        data=json.dumps(_entry()),
        content_type="application/json",
        **_headers(),
    )
    second = client.post(
        "/api/v1/waitlist/entries",
        data=json.dumps(_entry()),
        content_type="application/json",
        **_headers(),
    )
    assert second.status_code == 200
    assert second.json() == first.json()
    assert WaitlistEntry.objects.count() == 1

    payload = {
        "attempt_token": first.json()["data"]["attempt_token"],
        "reply": "Hello",
        "email": "person@example.com",
        "consent_version": "consent-v1",
    }
    completed = client.post(
        "/api/v1/waitlist/entries/complete",
        data=json.dumps(payload),
        content_type="application/json",
        **_headers(),
    )
    replayed = client.post(
        "/api/v1/waitlist/entries/complete",
        data=json.dumps(payload),
        content_type="application/json",
        **_headers(),
    )
    assert replayed.status_code == 200
    assert replayed.json() == completed.json()


@pytest.mark.django_db
@override_settings(**SETTINGS)
def test_public_entry_endpoints_require_a_trusted_origin():
    cache.clear()
    client = Client(enforce_csrf_checks=True)
    response = client.post(
        "/api/v1/waitlist/entries",
        data=json.dumps(_entry()),
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="https://evil.example",
    )
    assert response.status_code == 403


@pytest.mark.django_db
@override_settings(**SETTINGS)
def test_duplicate_attempt_generates_only_once_and_excludes_appearance():
    cache.clear()

    class CountingProvider:
        def __init__(self):
            self.requests = []

        def generate(self, request):
            self.requests.append(request)
            return "Hello from your Ally."

    provider = CountingProvider()
    values = _entry()
    first = create_entry(**values, generation_identity="test", provider=provider)
    second = create_entry(**values, generation_identity="test", provider=provider)

    assert second == first
    assert len(provider.requests) == 1
    assert vars(provider.requests[0]) == {
        "name": "Ari",
        "job": "Planning",
        "personality": "Warm",
    }


@pytest.mark.django_db
@override_settings(**SETTINGS)
def test_known_provider_failure_can_retry_immediately():
    cache.clear()

    class UnavailableProvider:
        def generate(self, request):
            raise ProviderUnavailableError

    with pytest.raises(GenerationUnavailable, match="generation unavailable"):
        create_entry(
            **_entry(),
            generation_identity="test",
            provider=UnavailableProvider(),
        )

    retried = create_entry(
        **_entry(),
        generation_identity="test",
        provider=type(
            "AvailableProvider",
            (),
            {"generate": lambda self, request: "Ready to help."},
        )(),
    )
    assert retried.greeting == "Ready to help."


@pytest.mark.django_db
@override_settings(
    **SETTINGS,
    CSRF_TRUSTED_ORIGINS=["https://*.up.railway.app"],
)
def test_public_entry_accepts_a_configured_wildcard_origin():
    cache.clear()
    response = Client().post(
        "/api/v1/waitlist/entries",
        data=json.dumps(_entry()),
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="https://preview.up.railway.app",
    )
    assert response.status_code == 200
