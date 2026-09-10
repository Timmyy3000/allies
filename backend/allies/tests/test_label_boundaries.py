import json
from uuid import UUID, uuid4

import pytest
from django.test import Client, override_settings

from allies.models import LabelGenerationState
from allies.services import labels
from allies.tests.test_labels import (
    account as account,  # noqa: PLC0414 - shared pytest fixture.
)
from allies.tests.test_labels import make_ally
from auths.config import cookie_name
from auths.models import SessionClientKind, User
from auths.services.sessions import issue_session
from workspaces.models import Membership, Workspace


@pytest.mark.parametrize(
    "text",
    [
        '{"label":"manager"}',
        '{"label":"chief\\nof staff"}',
        '{"label":"chief of staff","extra":true}',
        '{"label":null}',
        "not json",
    ],
)
def test_provider_rejects_malformed_label_content(text):
    with pytest.raises(labels.LabelGenerationFailure) as error:
        labels._validated_label(text)
    assert error.value.reason == "invalid_output"


def test_provider_read_enforces_deadline_between_partial_reads(monkeypatch):
    clock = iter([0, 7])
    monkeypatch.setattr(labels.time, "monotonic", lambda: next(clock))

    class Response:
        fp = None

        def read1(self, size):
            return b"partial"

    with pytest.raises(labels.LabelGenerationFailure) as error:
        labels._read_response(Response(), deadline=6)
    assert error.value.reason == "timeout"


def test_provider_read_rejects_oversized_response():
    class Response:
        fp = None

        def read1(self, size):
            return b"x" * size

    with pytest.raises(labels.LabelGenerationFailure) as error:
        labels._read_response(Response(), deadline=labels.time.monotonic() + 6)
    assert error.value.reason == "invalid_output"


@override_settings(ALLIES_AUTH_DIGEST_KEY="d" * 32, CACHE_URL="redis://test")
def test_global_provider_slots_bound_distinct_workspaces(monkeypatch):
    claimed = set()
    monkeypatch.setattr(labels, "check_rate_limit", lambda **kwargs: None)

    def reserve(key, value, timeout):
        if key in claimed:
            return False
        claimed.add(key)
        return True

    monkeypatch.setattr(labels.cache, "add", reserve)
    results = [
        labels._provider_allowed(workspace_id=UUID(int=index + 1)) for index in range(5)
    ]
    assert results == [None, None, None, None, "budget_exhausted"]


@pytest.mark.parametrize(
    "failure,reason",
    [
        (labels.ThrottleExceeded, "budget_exhausted"),
        (labels.ThrottleUnavailable, "budget_unavailable"),
        (RuntimeError, "budget_unavailable"),
    ],
)
def test_capacity_failure_is_closed_and_content_free(monkeypatch, failure, reason):
    def unavailable(**kwargs):
        raise failure("private cache details")

    monkeypatch.setattr(labels, "check_rate_limit", unavailable)
    assert labels._provider_allowed(workspace_id=uuid4()) == reason


@pytest.mark.django_db
@override_settings(ALLIES_WAITLIST_OPENAI_API_KEY="key")
def test_unexpected_provider_failure_does_not_log_job_or_exception(
    account, monkeypatch
):
    ally = make_ally(account, state=LabelGenerationState.PENDING)
    events = []

    def unavailable(job):
        raise RuntimeError("private provider details: " + job)

    monkeypatch.setattr(labels, "_provider_allowed", lambda **kwargs: None)
    monkeypatch.setattr(labels, "generate_label", unavailable)
    monkeypatch.setattr(
        labels, "emit_event", lambda kind, **fields: events.append((kind, fields))
    )
    assert labels.generate_label_for_ally(ally.id) is False
    ally.refresh_from_db()
    assert ally.label_generation_state == LabelGenerationState.UNAVAILABLE
    assert len(events) == 1
    assert events[0][1]["reason"] == "provider_error"
    assert "private" not in str(events)
    assert ally.job not in str(events)


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
)
@pytest.mark.parametrize(
    "case,expected",
    [
        ("signed_out", 401),
        ("missing_csrf", 403),
        ("foreign_origin", 403),
        ("removed_membership", 404),
        ("wrong_ancestry", 404),
        ("missing_ally", 404),
    ],
)
def test_settings_patch_enforces_security_boundaries(account, case, expected):
    user, workspace = account
    ally = make_ally(account)
    client = Client(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")["X-CSRFToken"]
    if case != "signed_out":
        client.cookies[cookie_name("access")] = issue_session(user).access_token
    headers = {"HTTP_HOST": "testserver", "HTTP_ORIGIN": "http://localhost:3000"}
    if case != "missing_csrf":
        headers["HTTP_X_CSRFTOKEN"] = csrf
    if case == "foreign_origin":
        headers["HTTP_ORIGIN"] = "https://untrusted.example"
    if case == "removed_membership":
        Membership.objects.filter(user=user, workspace=workspace).delete()
    if case == "wrong_ancestry":
        other_user = User.objects.create_user()
        other_workspace = Workspace.objects.create(
            owner=other_user, name="Other workspace"
        )
        ally = make_ally((other_user, other_workspace))
    target = uuid4() if case == "missing_ally" else ally.id
    response = client.patch(
        f"/api/v1/workspaces/{workspace.id}/allies/{target}/settings",
        json.dumps(
            {"label": "calendar manager", "show_label": True, "settings_revision": 0}
        ),
        content_type="application/json",
        **headers,
    )
    assert response.status_code == expected
    ally.refresh_from_db()
    assert (ally.label, ally.show_label, ally.settings_revision) == ("", False, 0)


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_AUTH_NATIVE_ENABLED=True,
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
    CSRF_TRUSTED_ORIGINS=["http://localhost:3000"],
)
@pytest.mark.parametrize("browser_signal", [None, "cookie", "origin", "csrf"])
def test_native_settings_require_unambiguous_bearer_transport(account, browser_signal):
    user, workspace = account
    ally = make_ally(account)
    client = Client(enforce_csrf_checks=True)
    token = issue_session(user, client_kind=SessionClientKind.NATIVE).access_token
    headers = {"HTTP_HOST": "testserver", "HTTP_AUTHORIZATION": f"Bearer {token}"}
    if browser_signal == "cookie":
        client.cookies[cookie_name("access")] = issue_session(user).access_token
    elif browser_signal == "origin":
        headers["HTTP_ORIGIN"] = "http://localhost:3000"
    elif browser_signal == "csrf":
        headers["HTTP_X_CSRFTOKEN"] = "a" * 32
    response = client.patch(
        f"/api/v1/workspaces/{workspace.id}/allies/{ally.id}/settings",
        json.dumps(
            {"label": "calendar manager", "show_label": True, "settings_revision": 0}
        ),
        content_type="application/json",
        **headers,
    )
    ally.refresh_from_db()
    if browser_signal is None:
        assert response.status_code == 200
        assert (ally.label, ally.show_label, ally.settings_revision) == (
            "calendar manager",
            True,
            1,
        )
    else:
        assert response.status_code in {401, 403}
        assert (ally.label, ally.show_label, ally.settings_revision) == ("", False, 0)
