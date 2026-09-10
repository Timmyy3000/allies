from django.test import RequestFactory

from config.api import api
from files.api.controllers import _error
from files.exceptions import FileScopeUnavailable, FileUnavailable


def test_file_admission_openapi_publishes_bounded_manifest_and_raw_upload():
    schema = api.get_openapi_schema()
    components = schema["components"]["schemas"]
    manifest = components["FileManifestRequest"]["properties"]
    assert manifest["name"]["minLength"] == 1
    assert manifest["name"]["maxLength"] == 255
    assert {key: manifest["size"][key] for key in ("type", "maximum", "minimum")} == {
        "type": "integer",
        "maximum": 25000000,
        "minimum": 1,
    }
    assert manifest["sha256"]["pattern"] == "^[0-9a-f]{64}$"

    upload = schema["paths"][
        "/api/v1/workspaces/{workspace_id}/allies/{ally_id}/files/{file_id}/content"
    ]["put"]
    raw = upload["requestBody"]
    assert raw["required"] is True
    assert raw["content"]["application/octet-stream"]["schema"] == {
        "type": "string",
        "format": "binary",
        "maxLength": 25000000,
    }
    content_length = next(
        item for item in upload["parameters"] if item["name"] == "Content-Length"
    )
    assert content_length["required"] is True
    assert content_length["schema"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 25000000,
    }
    accepted = schema["paths"]["/api/v1/internal/v1/accepted-files/{file_id}/content"][
        "get"
    ]
    accepted_parameters = {item["name"] for item in accepted["parameters"]}
    assert {"file_id", "binding_id", "message_id"} <= accepted_parameters


def test_file_api_keeps_scope_denial_distinct_from_storage_failure():
    request = RequestFactory().put("/api/v1/test")
    assert _error(FileScopeUnavailable(), request).status_code == 404
    assert _error(FileUnavailable(), request).status_code == 503
