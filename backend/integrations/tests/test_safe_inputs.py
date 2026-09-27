import json
from datetime import timedelta
from typing import ClassVar
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from django.test import override_settings
from django.utils import timezone

from allies.models import Ally
from auths.models import User
from chat.tests.test_dispatch import dispatch_records  # noqa: F401
from common.vault import seal_secret
from integrations.exceptions import IntegrationInvalid
from integrations.models import (
    AllyBrowser,
    BrowserSession,
    SafeInput,
    SafeInputGrant,
    SafeInputRequest,
)
from integrations.services import browser, safe_inputs
from integrations.tests.test_api import _client, _headers
from integrations.tests.test_gmail_tool import _turn
from workspaces.models import Membership, Workspace

SECRETS = ("me@example.com", "hunter2-secret")


@pytest.fixture(autouse=True)
def vault_key(settings):
    settings.ALLIES_VAULT_KEYS = Fernet.generate_key().decode()


@pytest.fixture
def turn(dispatch_records):  # noqa: F811
    workspace, binding, _, message = dispatch_records
    return workspace, binding.ally, _turn(message, binding)


def _tool(turn, **arguments):
    status, result = safe_inputs.execute_safe_input_tool(
        **turn[2], call_id=uuid4(), arguments=arguments
    )
    assert not any(secret in json.dumps(result) for secret in SECRETS)
    return status, result


def _other_ally(workspace):
    return Ally.objects.create(
        workspace=workspace,
        name="Nova",
        job="Shopper",
        personality="Brisk",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )


def _login(workspace, website="amazon.com"):
    return SafeInput.objects.create(
        workspace=workspace,
        name="Amazon",
        website=website,
        sealed=seal_secret(json.dumps(dict(zip(("username", "password"), SECRETS)))),
    )


def test_new_login_saved_by_user_grants_only_the_requester(turn):
    workspace, ally, _ = turn
    _, requested = _tool(
        turn, action="request_new", name="Amazon", website="https://www.Amazon.com/ap"
    )
    request_id = requested["request_id"]
    assert _tool(turn, action="status", request_id=request_id)[1]["status"] == "pending"

    safe_inputs.resolve_request(
        workspace.id,
        request_id,
        allow=True,
        user=None,
        fields={"username": SECRETS[0], "password": SECRETS[1]},
    )

    status = _tool(turn, action="status", request_id=request_id)[1]
    assert status["status"] == "saved"
    assert status["website"] == "amazon.com"
    item = SafeInput.objects.get()
    assert SECRETS[1].encode() not in bytes(item.sealed)
    assert list(SafeInputGrant.objects.values_list("ally_id", flat=True)) == [ally.id]
    listed = _tool(turn, action="list")[1]["safe_inputs"]
    assert listed == [
        {
            "id": str(item.id),
            "name": "Amazon",
            "website": "amazon.com",
            "has_access": True,
        }
    ]


def test_access_request_needs_the_user_and_deny_is_final(turn):
    workspace, _, _ = turn
    item = _login(workspace)
    assert _tool(turn, action="fill", safe_input_id=str(item.id))[1] == {
        "status": "no_access"
    }
    request_id = _tool(turn, action="request_access", safe_input_id=str(item.id))[1][
        "request_id"
    ]
    safe_inputs.resolve_request(
        workspace.id, request_id, allow=False, user=None, fields={}
    )
    assert _tool(turn, action="status", request_id=request_id)[1]["status"] == "denied"
    with pytest.raises(IntegrationInvalid):
        safe_inputs.resolve_request(
            workspace.id, request_id, allow=True, user=None, fields={}
        )
    assert not SafeInputGrant.objects.exists()


def test_repeated_request_reuses_the_pending_one(turn):
    first = _tool(turn, action="request_new", name="Amazon", website="amazon.com")
    again = _tool(turn, action="request_new", name="Amazon", website="amazon.com")
    assert first[1]["request_id"] == again[1]["request_id"]
    assert SafeInputRequest.objects.count() == 1


def test_close_with_a_bad_session_id_is_invalid(turn):
    assert browser.close_browser(turn[1], "not-a-uuid") == {"error": "invalid_request"}


def test_pending_requests_expire(turn):
    workspace, _, _ = turn
    request_id = _tool(turn, action="request_new", website="example.com")[1][
        "request_id"
    ]
    SafeInputRequest.objects.update(created_at=timezone.now() - timedelta(minutes=11))
    assert _tool(turn, action="status", request_id=request_id)[1]["status"] == "expired"
    assert safe_inputs.pending_requests(workspace.id) == []


@pytest.mark.parametrize("value", ["com", "localhost", "", "a..b"])
def test_website_must_be_a_site(value):
    with pytest.raises(ValueError):
        browser.normalize_website(value)


@pytest.mark.parametrize(
    ("host", "matches"),
    [
        ("amazon.com", True),
        ("signin.amazon.com", True),
        ("amazon.co.uk", False),
        ("amazon-login.com", False),
        ("evilamazon.com", False),
    ],
)
def test_host_matching(host, matches):
    assert browser.host_matches(host, "amazon.com") is matches


def _fake_browser_use(monkeypatch):
    calls = []

    def api(method, path, body=None):
        calls.append((method, path))
        if path == "/profiles":
            return {"id": "profile-1"}
        if path == "/browsers":
            return {
                "id": f"b{len(calls)}",
                "cdpUrl": "wss://cdp",
                "liveUrl": "https://live",
            }
        return {}

    monkeypatch.setattr(browser, "_api", api)
    return calls


def test_browser_open_reuses_profile_and_closes_previous(turn, monkeypatch):
    _, ally, _ = turn
    calls = _fake_browser_use(monkeypatch)
    first = browser.open_browser(ally)
    second = browser.open_browser(ally)
    assert first["cdp_url"] == second["cdp_url"] == "wss://cdp"
    assert [c for c in calls if c[1] == "/profiles"] == [("POST", "/profiles")]
    assert ("PATCH", "/browsers/b2") in calls
    assert browser.open_sessions(ally=ally).count() == 1


def test_browser_uses_the_configured_proxy_country(turn, monkeypatch, settings):
    _, ally, _ = turn
    bodies = []

    def api(method, path, body=None):
        bodies.append((path, body))
        return {"id": "p", "cdpUrl": "wss://cdp"}

    monkeypatch.setattr(browser, "_api", api)
    settings.BROWSER_USE_PROXY_COUNTRY = "de"
    browser.open_browser(ally)
    settings.BROWSER_USE_PROXY_COUNTRY = ""
    browser.open_browser(ally)
    created = [body for path, body in bodies if path == "/browsers"]
    assert [b["proxyCountryCode"] for b in created] == ["de", None]


def test_failed_open_keeps_the_working_browser(turn, monkeypatch):
    _, ally, _ = turn
    _fake_browser_use(monkeypatch)
    working = browser.open_browser(ally)

    def down(method, path, body=None):
        raise browser.BrowserUnavailable("down")

    monkeypatch.setattr(browser, "_api", down)
    assert browser.open_browser(ally) == {"error": "browser_unavailable"}
    assert [str(s.id) for s in browser.open_sessions(ally=ally)] == [
        working["session_id"]
    ]


def test_open_without_a_page_releases_the_slot(turn, monkeypatch):
    _, ally, _ = turn
    _fake_browser_use(monkeypatch)
    AllyBrowser.objects.create(ally=ally, pending_clear_sites=["amazon.com"])

    class NoPage(FakeCdp):
        def clear_site(self, site):
            raise StopIteration

    monkeypatch.setattr(browser, "Cdp", NoPage)
    assert browser.open_browser(ally) == {"error": "browser_unavailable"}
    assert not BrowserSession.objects.exists()


def test_workspace_holds_at_most_two_browsers(turn, monkeypatch):
    workspace, ally, _ = turn
    _fake_browser_use(monkeypatch)
    later = timezone.now() + timedelta(minutes=5)
    for _ in range(2):
        BrowserSession.objects.create(
            workspace=workspace, ally=_other_ally(workspace), expires_at=later
        )
    assert browser.open_browser(ally) == {"error": "browser_limit_reached"}
    BrowserSession.objects.update(expires_at=timezone.now())
    assert "session_id" in browser.open_browser(ally)


def test_revoke_signs_the_ally_out(turn, monkeypatch):
    workspace, ally, _ = turn
    calls = _fake_browser_use(monkeypatch)
    item = _login(workspace)
    SafeInputGrant.objects.create(safe_input=item, ally=ally)
    browser.open_browser(ally)

    safe_inputs.revoke_grant(workspace.id, item.id, ally.id)

    assert not SafeInputGrant.objects.exists()
    assert browser.open_sessions(ally=ally).count() == 0
    assert any(method == "PATCH" for method, _ in calls)
    assert AllyBrowser.objects.get(ally=ally).pending_clear_sites == ["amazon.com"]


def test_fill_refuses_without_browser_and_logs_no_values(turn, caplog):
    workspace, ally, _ = turn
    item = _login(workspace)
    SafeInputGrant.objects.create(safe_input=item, ally=ally)
    assert _tool(turn, action="fill", safe_input_id=str(item.id))[1] == {
        "status": "no_browser"
    }
    assert not any(secret in caplog.text for secret in SECRETS)


class FakeCdp:
    outcome = "filled"
    sent: ClassVar[list] = []

    def __init__(self, url):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def page(self):
        return "page-1"

    def call(self, method, params=None, session=None):
        FakeCdp.sent.append((method, params))
        if method == "Runtime.evaluate":
            if params["expression"] == "document.readyState":
                return {"result": {"value": "complete"}}
            return {"result": {"objectId": "window-1"}}
        if method == "Runtime.callFunctionOn":
            return {"result": {"value": FakeCdp.outcome}}
        return {}


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ("filled", {"status": "filled"}),
        (
            "domain_mismatch:amazon.co.uk",
            {
                "status": "domain_mismatch",
                "page_host": "amazon.co.uk",
                "website": "amazon.com",
            },
        ),
    ],
)
def test_fill_passes_values_as_arguments(turn, monkeypatch, outcome, expected):
    workspace, ally, _ = turn
    _fake_browser_use(monkeypatch)
    monkeypatch.setattr(browser, "Cdp", FakeCdp)
    FakeCdp.outcome, FakeCdp.sent = outcome, []
    item = _login(workspace)
    SafeInputGrant.objects.create(safe_input=item, ally=ally)
    browser.open_browser(ally)

    assert _tool(turn, action="fill", safe_input_id=str(item.id))[1] == expected
    fill_call = next(p for m, p in FakeCdp.sent if m == "Runtime.callFunctionOn")
    assert SECRETS[1] not in fill_call["functionDeclaration"]
    assert fill_call["arguments"][1:] == [{"value": s} for s in SECRETS]
    # No reload (closes pop-ups) and no clearing (empties later login steps).
    assert all(m != "Page.reload" for m, _ in FakeCdp.sent)
    assert sum(m == "Runtime.callFunctionOn" for m, _ in FakeCdp.sent) == 1


@pytest.mark.parametrize(("field", "value"), [("username", 0), ("password", 1)])
def test_fill_types_one_value_into_the_focused_field(turn, monkeypatch, field, value):
    workspace, ally, _ = turn
    _fake_browser_use(monkeypatch)
    monkeypatch.setattr(browser, "Cdp", FakeCdp)
    FakeCdp.outcome, FakeCdp.sent = "filled", []
    item = _login(workspace)
    SafeInputGrant.objects.create(safe_input=item, ally=ally)
    browser.open_browser(ally)

    result = _tool(turn, action="fill", safe_input_id=str(item.id), field=field)
    assert result[1] == {"status": "filled"}
    fill_call = next(p for m, p in FakeCdp.sent if m == "Runtime.callFunctionOn")
    assert fill_call["arguments"] == [
        {"value": "amazon.com"},
        {"value": field},
        {"value": SECRETS[value]},
    ]
    # Only the requested value leaves the vault for this call.
    assert SECRETS[1 - value] not in json.dumps(fill_call)
    keys = [p["type"] for m, p in FakeCdp.sent if m == "Input.dispatchKeyEvent"]
    assert keys == ["keyDown", "keyUp"]
    # The value must stay for later steps: exactly one page call, no clearing.
    assert sum(m == "Runtime.callFunctionOn" for m, _ in FakeCdp.sent) == 1
    assert SECRETS[value] not in json.dumps(result)


def test_fill_rejects_unknown_field(turn, monkeypatch):
    workspace, ally, _ = turn
    _fake_browser_use(monkeypatch)
    item = _login(workspace)
    SafeInputGrant.objects.create(safe_input=item, ally=ally)
    browser.open_browser(ally)
    status, body = _tool(turn, action="fill", safe_input_id=str(item.id), field="otp")
    assert status == 422 and body["error"] == "invalid_request"


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
)
def test_other_workspace_sees_and_changes_nothing(turn):
    workspace, ally, _ = turn
    item = _login(workspace)
    SafeInputGrant.objects.create(safe_input=item, ally=ally)
    request = SafeInputRequest.objects.create(
        workspace=workspace, ally=ally, name="Shop", website="shop.com"
    )
    BrowserSession.objects.create(
        workspace=workspace,
        ally=ally,
        live_url="https://live",
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    outsider = User.objects.create_user()
    own = Workspace.objects.create(owner=outsider, name="Other")
    Membership.objects.create(
        workspace=own, user=outsider, role="owner", status="active"
    )
    client, csrf = _client(outsider)
    headers = _headers(csrf)

    theirs = f"/api/v1/workspaces/{workspace.id}"
    for path in (
        "/safe-inputs",
        "/safe-input-requests",
        f"/allies/{ally.id}/browser-session",
    ):
        assert client.get(theirs + path, **headers).status_code == 404

    mine = f"/api/v1/workspaces/{own.id}"
    assert client.get(mine + "/safe-inputs", **headers).json()["data"] == []
    assert client.get(mine + "/safe-input-requests", **headers).json()["data"] == []
    assert (
        client.get(mine + f"/allies/{ally.id}/browser-session", **headers).status_code
        == 404
    )
    resolved = client.post(
        mine + f"/safe-input-requests/{request.id}",
        json.dumps({"decision": "deny"}),
        content_type="application/json",
        **headers,
    )
    assert resolved.status_code == 404
    patched = client.patch(
        mine + f"/safe-inputs/{item.id}",
        json.dumps({"name": "Hijacked"}),
        content_type="application/json",
        **headers,
    )
    assert patched.status_code == 404
    assert client.delete(mine + f"/safe-inputs/{item.id}", **headers).status_code == 404
    assert (
        client.delete(
            mine + f"/safe-inputs/{item.id}/grants/{ally.id}", **headers
        ).status_code
        == 404
    )
    item.refresh_from_db()
    request.refresh_from_db()
    assert item.name == "Amazon" and request.status == SafeInputRequest.PENDING
    assert SafeInputGrant.objects.filter(safe_input=item, ally=ally).exists()
    granted = client.post(
        mine + f"/safe-inputs/{item.id}/grants",
        json.dumps({"ally_id": str(ally.id)}),
        content_type="application/json",
        **headers,
    )
    assert granted.status_code == 404


def test_settings_grant_is_scoped_to_the_workspace(turn):
    workspace, ally, _ = turn
    item = _login(workspace)
    request_id = _tool(turn, action="request_access", safe_input_id=str(item.id))[1][
        "request_id"
    ]
    safe_inputs.grant_access(workspace.id, item.id, ally.id)
    safe_inputs.grant_access(workspace.id, item.id, ally.id)
    assert _tool(turn, action="status", request_id=request_id)[1]["status"] == "allowed"
    with pytest.raises(IntegrationInvalid):
        safe_inputs.resolve_request(
            workspace.id, request_id, allow=False, user=None, fields={}
        )
    assert SafeInputGrant.objects.filter(safe_input=item, ally=ally).count() == 1
    stranger = Ally.objects.create(
        workspace=Workspace.objects.create(owner=User.objects.create_user(), name="X"),
        name="Rex",
        job="-",
        personality="-",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    with pytest.raises(Ally.DoesNotExist):
        safe_inputs.grant_access(workspace.id, item.id, stranger.id)


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
)
def test_reads_need_a_session_but_not_csrf(turn):
    workspace, ally, _ = turn
    _login(workspace)
    SafeInputRequest.objects.create(
        workspace=workspace, ally=ally, name="Shop", website="shop.com"
    )
    BrowserSession.objects.create(
        workspace=workspace,
        ally=ally,
        live_url="https://live",
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    owner = Membership.objects.filter(workspace=workspace).first().user
    client, _ = _client(owner)
    listed = client.get(
        f"/api/v1/workspaces/{workspace.id}/safe-inputs",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    assert listed.status_code == 200
    assert [row["name"] for row in listed.json()["data"]] == ["Amazon"]
    for path in ("/safe-input-requests", f"/allies/{ally.id}/browser-session"):
        read = client.get(
            f"/api/v1/workspaces/{workspace.id}{path}",
            HTTP_HOST="testserver",
            HTTP_ORIGIN="http://localhost:3000",
        )
        assert read.status_code == 200, (path, read.json())
    changed = client.patch(
        f"/api/v1/workspaces/{workspace.id}/safe-inputs/{SafeInput.objects.get().id}",
        json.dumps({"name": "X"}),
        content_type="application/json",
        HTTP_HOST="testserver",
        HTTP_ORIGIN="http://localhost:3000",
    )
    assert changed.json()["data"]["code"] == "csrf_rejected"
