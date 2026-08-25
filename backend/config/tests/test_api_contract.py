import json
import logging

from django.test import RequestFactory

from config.api import _unhandled_error, api
from config.openapi import GENERIC_ERROR_RESPONSE_EXAMPLE, STANDARD_RESPONSE_EXAMPLES

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


def test_waitlist_openapi_declares_two_public_origin_checked_mutations():
    schema = api.get_openapi_schema()
    waitlist_paths = {path for path in schema["paths"] if "/waitlist/" in path}
    assert waitlist_paths == {
        "/api/v1/waitlist/entries",
        "/api/v1/waitlist/entries/complete",
    }
    for path in waitlist_paths:
        operation = schema["paths"][path]["post"]
        assert operation["security"] == []
        assert {parameter["name"] for parameter in operation["parameters"]} == {
            "Origin",
            "Referer",
        }
        assert "trusted frontend origin" in operation["description"]


def test_unhandled_error_logs_only_safe_metadata_and_returns_generic_envelope(caplog):
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
    assert "private failure detail" not in caplog.text
    assert "/api/v1/test" not in caplog.text
    record = caplog.records[-1]
    assert record.request_method == "GET"
    assert record.route_template == "unknown_route"
    assert record.error_type == "RuntimeError"
    assert not hasattr(record, "request_path")
