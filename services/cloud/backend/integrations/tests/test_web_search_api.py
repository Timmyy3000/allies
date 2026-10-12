"""Web search connection API: connect, replace, grant, and disconnect.

Provider contracts the fake HTTP layer asserts (checked 2026-10-12):
- Parallel beta search: POST https://api.parallel.ai/v1beta/search with an
  x-api-key header and a parallel-beta header
  (https://docs.parallel.ai/search/search-migration-guide). Parallel's
  current guidance is /v1/search for new integrations; this slice keeps the
  beta endpoint that the Hermes plugin already uses.
- Tavily search: POST https://api.tavily.com/search with
  Authorization: Bearer <key> (https://docs.tavily.com/documentation/api-reference/endpoint/search).
- Exa search: POST https://api.exa.ai/search with an x-api-key header and a
  numResults body field (https://exa.ai/docs/reference/search).

No test reaches the network. ``urlopen`` in the provider module is replaced.
"""

import io
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest
from cryptography.fernet import Fernet
from django.db import IntegrityError, connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from allies.models import Ally, AllyBinding
from auths.config import cookie_name
from auths.models import User
from auths.services.sessions import issue_session
from common.vault import unseal_secret
from integrations.models import PROVIDER_WEB_SEARCH, IntegrationSecret
from integrations.services import web_search_backends
from workspaces.models import Membership, Workspace

KEY = "sk-test-KEY-abcdefgh9876"  # gitleaks:allow
OTHER_KEY = "sk-other-KEY-zyxwvu5432"  # gitleaks:allow
EXPECTED_PROVIDER_CALLS = {
    "parallel": {
        "url": "https://api.parallel.ai/v1beta/search",
        "header": "x-api-key",
        "value": KEY,
        "limit_field": "max_results",
    },
    "tavily": {
        "url": "https://api.tavily.com/search",
        "header": "authorization",
        "value": f"Bearer {KEY}",
        "limit_field": "max_results",
    },
    "exa": {
        "url": "https://api.exa.ai/search",
        "header": "x-api-key",
        "value": KEY,
        "limit_field": "numResults",
    },
}
DEFAULT_PAYLOADS = {
    "https://api.parallel.ai/v1beta/search": {
        "search_id": "s-1",
        "results": [
            {"url": "https://example.com/a", "title": "A", "excerpts": ["Excerpt"]}
        ],
    },
    "https://api.tavily.com/search": {
        "query": "allies connection test",
        "results": [
            {"title": "A", "url": "https://example.com/a", "content": "Content"}
        ],
    },
    "https://api.exa.ai/search": {
        "requestId": "r-1",
        "results": [
            {"title": "A", "url": "https://example.com/a", "highlights": ["Highlight"]}
        ],
    },
}
BACKENDS = list(EXPECTED_PROVIDER_CALLS)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self, limit=-1):
        return self._body if limit < 0 else self._body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeProvider:
    def __init__(self) -> None:
        self.calls = []
        self.status = None
        self.error = None
        self.body = None

    def open(self, request, timeout=None):
        self.calls.append((request, timeout))
        if self.error is not None:
            raise self.error
        if self.status is not None:
            raise HTTPError(
                request.full_url, self.status, "provider", None, io.BytesIO()
            )
        if self.body is not None:
            return FakeResponse(self.body)
        return FakeResponse(json.dumps(DEFAULT_PAYLOADS[request.full_url]).encode())


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(web_search_backends, "_OPENER", fake)
    return fake


@pytest.fixture
def api_settings(settings):
    settings.ALLOWED_HOSTS = ["testserver"]
    settings.CSRF_TRUSTED_ORIGINS = ["http://localhost:3000"]
    settings.ALLIES_AUTH_DIGEST_KEY = "d" * 32
    settings.ALLIES_AUTH_JWT_KEY = "j" * 32
    settings.ALLIES_VAULT_KEYS = Fernet.generate_key().decode()
    return settings


def _ally(workspace, name):
    ally = Ally.objects.create(
        workspace=workspace,
        name=name,
        job="Researcher",
        personality="Calm and specific.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    AllyBinding.objects.create(ally=ally)
    return ally


class Api:
    def __init__(self, user, workspace) -> None:
        self.client = Client(enforce_csrf_checks=True)
        self.csrf = self.client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")[
            "X-CSRFToken"
        ]
        self.client.cookies[cookie_name("access")] = issue_session(user).access_token
        self.base = f"/api/v1/workspaces/{workspace.id}/integrations/web-search"

    def _headers(self):
        return {
            "HTTP_HOST": "testserver",
            "HTTP_ORIGIN": "http://localhost:3000",
            "HTTP_X_CSRFTOKEN": self.csrf,
        }

    def get(self):
        return self.client.get(self.base, **self._headers())

    def connect(self, backend="parallel", api_key=KEY):
        return self.client.put(
            self.base,
            json.dumps({"backend": backend, "api_key": api_key}),
            content_type="application/json",
            **self._headers(),
        )

    def grant(self, ally_id, level="use"):
        return self.client.post(
            f"{self.base}/grants",
            json.dumps({"ally_id": str(ally_id), "level": level}),
            content_type="application/json",
            **self._headers(),
        )

    def disconnect(self, confirm=True):
        return self.client.delete(
            self.base,
            json.dumps({"confirm": confirm}),
            content_type="application/json",
            **self._headers(),
        )


@pytest.fixture
def account(db, api_settings):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Search workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    return user, workspace, _ally(workspace, "Mira")


def _live_rows(workspace):
    return IntegrationSecret.objects.filter(
        workspace=workspace, provider_key=PROVIDER_WEB_SEARCH, revoked_at=None
    )


@pytest.mark.django_db
@pytest.mark.parametrize("backend", BACKENDS)
def test_connect_checks_the_key_live_and_stores_only_ciphertext_and_hint(
    account, provider, backend
):
    user, workspace, _ = account
    response = Api(user, workspace).connect(backend)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["backend"] == backend
    assert data["key_hint"] == "9876"
    assert data["ally_grants"] == []
    assert KEY not in response.content.decode()
    assert len(provider.calls) == 1

    secret = _live_rows(workspace).get()
    assert secret.backend == backend
    assert KEY.encode() not in bytes(secret.ciphertext)
    assert unseal_secret(bytes(secret.ciphertext)) == KEY


@pytest.mark.django_db
@pytest.mark.parametrize("backend", BACKENDS)
def test_key_leaves_only_in_the_provider_auth_header(
    account, provider, backend, caplog
):
    user, workspace, _ = account
    expected = EXPECTED_PROVIDER_CALLS[backend]
    with caplog.at_level(logging.DEBUG):
        response = Api(user, workspace).connect(backend)

    assert response.status_code == 200
    request, timeout = provider.calls[0]
    assert request.get_method() == "POST"
    assert request.full_url == expected["url"]
    headers = {name.lower(): value for name, value in request.headers.items()}
    assert headers[expected["header"]] == expected["value"]
    assert json.loads(request.data)[expected["limit_field"]] == 1
    assert timeout == 8
    assert KEY not in request.full_url
    assert KEY.encode() not in request.data
    assert KEY not in response.content.decode()
    assert KEY not in caplog.text


@pytest.mark.django_db
@pytest.mark.parametrize("status", [401, 403])
def test_rejected_key_is_refused_and_not_stored(account, provider, status):
    user, workspace, _ = account
    provider.status = status
    response = Api(user, workspace).connect("tavily")

    assert response.status_code == 422
    assert response.json()["data"]["code"] == "web_search_key_rejected"
    assert (
        response.json()["message"]
        == "Tavily rejected this key. Check it and paste it again."
    )
    assert KEY not in response.content.decode()
    assert not IntegrationSecret.objects.exists()


@pytest.mark.django_db
def test_rejected_replacement_leaves_the_existing_connection_unchanged(
    account, provider
):
    user, workspace, _ = account
    api = Api(user, workspace)
    api.connect("parallel")
    before = _live_rows(workspace).get()
    snapshot = (bytes(before.ciphertext), before.backend, before.key_hint)

    provider.status = 401
    response = api.connect("exa", api_key=OTHER_KEY)

    assert response.status_code == 422
    after = _live_rows(workspace).get()
    assert (bytes(after.ciphertext), after.backend, after.key_hint) == snapshot


@pytest.mark.django_db
@pytest.mark.parametrize(
    "failure",
    [
        {"status": 429},
        {"status": 500},
        {"status": 503},
        {"status": 307},
        {"error": TimeoutError("timed out")},
        {"error": URLError("unreachable")},
        {"body": b"<html>not json</html>"},
        {"body": json.dumps({"unexpected": True}).encode()},
        {
            "body": json.dumps(
                {"results": [], "pad": "x" * web_search_backends.MAX_RESPONSE_BYTES}
            ).encode()
        },
    ],
    ids=[
        "rate-limited",
        "server-error",
        "unavailable",
        "redirect",
        "timeout",
        "transport",
        "not-json",
        "wrong-shape",
        "oversized",
    ],
)
def test_provider_outage_or_bad_reply_is_retryable_and_stores_nothing(
    account, provider, failure
):
    user, workspace, _ = account
    provider.status = failure.get("status")
    provider.error = failure.get("error")
    provider.body = failure.get("body")
    response = Api(user, workspace).connect("parallel")

    assert response.status_code == 503
    assert response.json()["data"]["code"] == "web_search_check_failed"
    assert KEY not in response.content.decode()
    assert not IntegrationSecret.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("debug", [True, False])
def test_connect_refuses_without_vault_keys_and_never_calls_the_provider(
    account, provider, settings, debug
):
    user, workspace, _ = account
    settings.ALLIES_VAULT_KEYS = ""
    settings.DEBUG = debug
    response = Api(user, workspace).connect("parallel")

    assert response.status_code == 503
    assert response.json()["data"]["code"] == "vault_unavailable"
    assert provider.calls == []
    assert not IntegrationSecret.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "api_key",
    [
        "short-key-123",
        "has space in the key 12",
        "ключ-ключ-ключ-ключ-1",
        "k" * 513,
    ],
    ids=["too-short", "contains-space", "non-ascii", "too-long"],
)
def test_connect_rejects_malformed_keys_before_calling_the_provider(
    account, provider, api_key
):
    user, workspace, _ = account
    response = Api(user, workspace).connect("parallel", api_key=api_key)

    assert response.status_code == 422
    assert provider.calls == []
    assert not IntegrationSecret.objects.exists()


@pytest.mark.django_db
def test_connect_rejects_unknown_backend_and_extra_fields(account, provider):
    user, workspace, _ = account
    api = Api(user, workspace)
    unknown = api.client.put(
        api.base,
        json.dumps({"backend": "brave", "api_key": KEY}),
        content_type="application/json",
        **api._headers(),
    )
    extra = api.client.put(
        api.base,
        json.dumps({"backend": "exa", "api_key": KEY, "sealed": "x"}),
        content_type="application/json",
        **api._headers(),
    )

    assert unknown.status_code == 422
    assert extra.status_code == 422
    assert provider.calls == []


@pytest.mark.django_db
def test_replacing_key_or_provider_keeps_ally_grants(account, provider):
    user, workspace, ally = account
    api = Api(user, workspace)
    first = api.connect("parallel").json()["data"]
    assert api.grant(ally.id, "use").status_code == 200

    second = api.connect("exa", api_key=OTHER_KEY)

    assert second.status_code == 200
    data = second.json()["data"]
    assert data["connection_id"] == first["connection_id"]
    assert data["backend"] == "exa"
    assert data["key_hint"] == OTHER_KEY[-4:]
    assert [grant["ally_id"] for grant in data["ally_grants"]] == [str(ally.id)]
    assert IntegrationSecret.objects.count() == 1


@pytest.mark.django_db
def test_grant_turns_an_ally_on_and_off(account, provider):
    user, workspace, ally = account
    api = Api(user, workspace)
    api.connect()

    on = api.grant(ally.id, "use")
    assert on.status_code == 200
    assert on.json()["data"]["level"] == "use"
    assert [g["ally_id"] for g in api.get().json()["data"]["ally_grants"]] == [
        str(ally.id)
    ]

    off = api.grant(ally.id, "none")
    assert off.status_code == 200
    assert off.json()["data"]["level"] == "none"
    assert api.get().json()["data"]["ally_grants"] == []


@pytest.mark.django_db
def test_grant_rejects_gmail_levels_and_unknown_allies(account, provider):
    user, workspace, _ = account
    api = Api(user, workspace)
    api.connect()
    other_owner = User.objects.create_user()
    other_workspace = Workspace.objects.create(owner=other_owner, name="Other")
    stranger = _ally(other_workspace, "Stranger")

    assert api.grant(stranger.id, "use").status_code == 422
    assert api.grant(stranger.id, "send").status_code == 422


@pytest.mark.django_db
def test_grant_without_a_connection_is_a_conflict(account):
    user, workspace, ally = account
    response = Api(user, workspace).grant(ally.id, "use")

    assert response.status_code == 409
    assert response.json()["data"]["code"] == "web_search_not_connected"


@pytest.mark.django_db
def test_disconnect_wipes_key_and_grants_and_reconnect_starts_a_new_row(
    account, provider
):
    user, workspace, ally = account
    api = Api(user, workspace)
    old_id = api.connect().json()["data"]["connection_id"]
    api.grant(ally.id, "use")

    gone = api.disconnect()
    assert gone.status_code == 202
    assert gone.json()["data"]["status"] == "deprovisioned"
    revoked = IntegrationSecret.objects.get(id=old_id)
    assert revoked.revoked_at is not None
    assert bytes(revoked.ciphertext) == b""
    assert revoked.ally_grants.count() == 0
    assert api.get().json()["data"] is None

    assert api.disconnect().json()["data"]["status"] == "already_cleaned"

    reconnected = api.connect().json()["data"]
    assert reconnected["connection_id"] != old_id
    assert IntegrationSecret.objects.count() == 2
    assert _live_rows(workspace).get().id != old_id


@pytest.mark.django_db
def test_disconnect_requires_confirmation(account, provider):
    user, workspace, _ = account
    api = Api(user, workspace)
    api.connect()

    response = api.disconnect(confirm=False)

    assert response.status_code == 422
    assert _live_rows(workspace).exists()


@pytest.mark.django_db
def test_repeated_connect_with_the_same_input_leaves_one_live_connection(
    account, provider
):
    user, workspace, _ = account
    api = Api(user, workspace)
    first = api.connect()
    second = api.connect()

    assert first.status_code == second.status_code == 200
    assert (
        first.json()["data"]["connection_id"] == second.json()["data"]["connection_id"]
    )
    assert _live_rows(workspace).count() == 1


@pytest.mark.django_db
def test_losing_a_first_connect_race_is_a_conflict(account, provider, monkeypatch):
    user, workspace, _ = account

    def lose(**kwargs):
        raise IntegrityError("one live web search connection per workspace")

    monkeypatch.setattr(IntegrationSecret.objects, "create", lose)
    response = Api(user, workspace).connect()

    assert response.status_code == 409
    assert response.json()["data"]["code"] == "integration_conflict"
    assert not IntegrationSecret.objects.exists()


@pytest.mark.django_db
def test_status_query_count_does_not_grow_with_grants(account, provider):
    user, workspace, _ = account
    api = Api(user, workspace)
    api.connect()

    def status_queries():
        with CaptureQueriesContext(connection) as queries:
            assert api.get().status_code == 200
        return len(queries.captured_queries)

    before = status_queries()
    for name in ("Second", "Third", "Fourth"):
        assert api.grant(_ally(workspace, name).id, "use").status_code == 200

    assert status_queries() == before


@pytest.mark.django_db
def test_non_member_cannot_read_or_change_the_connection(account, provider):
    user, workspace, ally = account
    Api(user, workspace).connect()
    outsider = User.objects.create_user()
    api = Api(outsider, workspace)

    assert api.get().status_code == 404
    assert api.connect().status_code == 404
    assert api.grant(ally.id).status_code == 404
    assert api.disconnect().status_code == 404
    assert _live_rows(workspace).get().backend == "parallel"


@pytest.mark.django_db
def test_web_search_works_while_the_gmail_flag_is_off(account, provider, settings):
    user, workspace, ally = account
    settings.ALLIES_GMAIL_ENABLED = False
    api = Api(user, workspace)

    assert api.connect().status_code == 200
    assert api.grant(ally.id, "use").status_code == 200


def test_provider_redirects_are_refused_so_the_key_stays_with_the_provider():
    handler = web_search_backends._RefuseRedirects()
    request = Request("https://api.tavily.com/search", method="POST")

    followed = handler.redirect_request(
        request, None, 307, "Temporary Redirect", {}, "https://elsewhere.example/"
    )

    assert followed is None
