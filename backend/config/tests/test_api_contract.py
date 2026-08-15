import json
import logging
from copy import deepcopy

from django.test import RequestFactory

from config.api import _unhandled_error, api
from config.openapi import (
    GENERIC_ERROR_RESPONSE_EXAMPLE,
    STANDARD_RESPONSE_EXAMPLES,
    add_standard_response_examples,
)

PROTECTED_OPERATIONS = {
    ("/api/v1/auths/sign-in/{provider}", "post"),
    ("/api/v1/auths/refresh", "post"),
    ("/api/v1/auths/logout", "post"),
    ("/api/v1/auths/identities/{provider}/link", "post"),
    ("/api/v1/auths/me/profile", "patch"),
    ("/api/v1/auths/me/avatar/uploads", "post"),
    ("/api/v1/auths/me/avatar/{asset_id}/complete", "post"),
    ("/api/v1/auths/me/avatar", "delete"),
}


def test_every_origin_protected_operation_declares_403():
    schema = api.get_openapi_schema()

    for path, method in PROTECTED_OPERATIONS:
        assert 403 in schema["paths"][path][method]["responses"]


def test_health_declares_rate_limit_response():
    schema = api.get_openapi_schema()

    assert 429 in schema["paths"]["/api/v1/health"]["get"]["responses"]


def test_every_json_envelope_has_an_approved_complete_example():
    schema = api.get_openapi_schema()
    components = schema["components"]["schemas"]
    referenced_envelopes = set()
    for path_item in schema["paths"].values():
        for operation in path_item.values():
            for response in operation["responses"].values():
                content = response.get("content", {}).get("application/json")
                if not content:
                    continue
                name = content["schema"]["$ref"].rsplit("/", 1)[-1]
                referenced_envelopes.add(name)

    assert referenced_envelopes == set(STANDARD_RESPONSE_EXAMPLES)
    for name in referenced_envelopes:
        example = components[name]["example"]
        assert example == STANDARD_RESPONSE_EXAMPLES[name]
        assert set(example) == {"status", "message", "data"}


def test_error_responses_publish_safe_route_examples():
    schema = api.get_openapi_schema()

    for path, path_item in schema["paths"].items():
        for operation in path_item.values():
            for response in operation["responses"].values():
                content = response.get("content", {}).get("application/json")
                if not content:
                    continue
                if content["schema"]["$ref"].endswith("/ErrorResponse_ErrorData_"):
                    if path.startswith("/api/v1/waitlist/"):
                        examples = content["examples"]
                        assert examples
                        for code, example in examples.items():
                            data = example["value"]["data"]
                            if code == "validation_error":
                                assert data == {
                                    "code": code,
                                    "details": {
                                        "errors": [
                                            {
                                                "field": "body.payload.name",
                                                "code": "string_type",
                                            }
                                        ]
                                    },
                                }
                            else:
                                assert data == {"code": code}
                                if code == "waitlist_unavailable":
                                    assert (
                                        example["value"]["message"]
                                        == "waitlist unavailable"
                                    )
                    else:
                        assert content["example"] == GENERIC_ERROR_RESPONSE_EXAMPLE


def test_waitlist_openapi_declares_cookie_security_and_retry_headers():
    schema = api.get_openapi_schema()
    capability = schema["components"]["securitySchemes"]["WaitlistCapability"]
    assert capability == {
        "type": "apiKey",
        "in": "cookie",
        "name": "allies_waitlist_capability",
        "description": "HttpOnly browser capability issued by GET /waitlist/session.",
    }
    session = schema["paths"]["/api/v1/waitlist/session"]["get"]
    assert session["security"] == []
    assert {parameter["name"] for parameter in session["parameters"]} == {
        "Origin",
        "Referer",
    }
    assert "trusted frontend origin" in session["description"]
    restore = schema["paths"]["/api/v1/waitlist/draft"]["get"]
    assert restore["security"] == [{"WaitlistCapability": []}]
    assert 403 in restore["responses"]
    assert {parameter["name"] for parameter in restore["parameters"]} == {
        "Origin",
        "Referer",
    }
    renamed_schema = deepcopy(schema)
    renamed_restore = renamed_schema["paths"]["/api/v1/waitlist/draft"]["get"]
    renamed_restore["operationId"] = "get_waitlist_draft"
    renamed_restore.pop("parameters", None)
    add_standard_response_examples(renamed_schema)
    assert {parameter["name"] for parameter in renamed_restore["parameters"]} == {
        "Origin",
        "Referer",
    }
    configure = schema["paths"]["/api/v1/waitlist/draft/configuration"]["patch"]
    assert configure["security"] == [{"WaitlistCapability": []}]
    assert {parameter["name"] for parameter in configure["parameters"]} == {
        "Idempotency-Key",
        "Origin",
        "Referer",
        "X-CSRFToken",
    }
    greeting_errors = schema["paths"]["/api/v1/waitlist/draft/greeting"]["post"][
        "responses"
    ][503]["content"]["application/json"]["examples"]
    assert set(greeting_errors) == {
        "generation_outcome_unknown",
        "generation_unavailable",
        "waitlist_unavailable",
    }


def test_unhandled_error_logs_traceback_and_returns_generic_envelope(caplog):
    request = RequestFactory().get("/api/v1/test")
    error = RuntimeError("private failure detail")

    with caplog.at_level(logging.ERROR, logger="config.api"):
        response = _unhandled_error(request, error)

    assert response.status_code == 500
    assert json.loads(response.content) == {
        "status": "error",
        "message": "internal server error",
        "data": {"code": "internal_error"},
    }
    assert "private failure detail" in caplog.text
    record = caplog.records[-1]
    assert record.request_method == "GET"
    assert record.request_path == "/api/v1/test"
