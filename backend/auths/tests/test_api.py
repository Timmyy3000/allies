from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client, override_settings


@pytest.mark.django_db
@override_settings(ALLIES_AUTH_FAKE_PROVIDER_ENABLED=True, ALLOWED_HOSTS=["testserver"])
def test_fake_sign_in_callback_and_me_are_cookie_bound():
    client = Client(enforce_csrf_checks=True)
    assert (
        client.post(
            "/api/v1/auths/sign-in/fake",
            {"redirect_to": "/"},
            content_type="application/json",
            HTTP_HOST="testserver",
        ).status_code
        == 403
    )

    csrf_response = client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")
    csrf = csrf_response["X-CSRFToken"]
    assert (
        client.post(
            "/api/v1/auths/sign-in/fake",
            {"redirect_to": "/"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN="malformed",
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_HOST="testserver",
        ).status_code
        == 403
    )
    start = client.post(
        "/api/v1/auths/sign-in/fake",
        {"redirect_to": "/"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )
    assert start.status_code == 200
    assert start.json()["status"] == "success"
    query = parse_qs(urlparse(start.json()["data"]["redirect_url"]).query)
    callback = client.get(
        "/api/v1/auths/callback/fake",
        {"state": query["state"][0], "code": "fake:api-test|Test User"},
        HTTP_HOST="testserver",
    )
    assert callback.status_code == 303
    me = client.get("/api/v1/auths/me", HTTP_HOST="testserver")
    assert me.status_code == 200
    assert me.json()["status"] == "success"
    assert me.json()["data"]["user"]["id"].startswith("usr_")
    assert "provider" not in me.json()["data"]


@pytest.mark.django_db
@override_settings(ALLIES_AUTH_FAKE_PROVIDER_ENABLED=True, ALLOWED_HOSTS=["testserver"])
def test_framework_validation_errors_use_the_standard_envelope():
    client = Client(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")["X-CSRFToken"]

    response = client.post(
        "/api/v1/auths/sign-in/fake",
        {"redirect_to": 123},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )

    assert response.status_code == 422
    assert response.json() == {
        "status": "error",
        "message": "request validation failed",
        "data": {
            "code": "validation_error",
            "details": {
                "errors": [
                    {
                        "field": "body.payload.redirect_to",
                        "code": "string_type",
                    }
                ]
            },
        },
    }


@pytest.mark.django_db
@override_settings(ALLIES_AUTH_FAKE_PROVIDER_ENABLED=True, ALLOWED_HOSTS=["testserver"])
def test_unhandled_errors_use_the_standard_envelope(monkeypatch):
    client = Client(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auths/csrf", HTTP_HOST="testserver")["X-CSRFToken"]
    monkeypatch.setattr(
        "auths.api.authentication.begin_auth_flow",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )

    response = client.post(
        "/api/v1/auths/sign-in/fake",
        {"redirect_to": "/"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_HOST="testserver",
    )

    assert response.status_code == 500
    assert response.json() == {
        "status": "error",
        "message": "internal server error",
        "data": {"code": "internal_error"},
    }
