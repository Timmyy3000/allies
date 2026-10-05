from uuid import UUID

import pytest
from django.test import Client
from pydantic import TypeAdapter, ValidationError

from common.uuids import CanonicalUUID


@pytest.mark.parametrize(
    "value",
    (
        "018F77D8-6E61-7CA0-8C36-1BA4F1FD9D72",
        "018f77d86e617ca08c361ba4f1fd9d72",
        "wsp_018f77d8-6e61-7ca0-8c36-1ba4f1fd9d72",
        "not-a-uuid",
        "",
    ),
)
def test_canonical_uuid_rejects_alternate_and_malformed_strings(value):
    with pytest.raises(ValidationError):
        TypeAdapter(CanonicalUUID).validate_python(value)


def test_canonical_uuid_accepts_lowercase_hyphenated_values_and_uuid_objects():
    raw = "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d72"
    parsed = UUID(raw)

    assert TypeAdapter(CanonicalUUID).validate_python(raw) == parsed
    assert TypeAdapter(CanonicalUUID).validate_python(parsed) == parsed


@pytest.mark.parametrize(
    "value",
    (
        "018F77D8-6E61-7CA0-8C36-1BA4F1FD9D72",
        "018f77d86e617ca08c361ba4f1fd9d72",
        "wsp_018f77d8-6e61-7ca0-8c36-1ba4f1fd9d72",
        "not-a-uuid",
    ),
)
def test_workspace_route_rejects_noncanonical_uuid_paths(value):
    response = Client().get(f"/api/v1/workspaces/{value}")

    assert response.status_code == 422


def test_workspace_route_accepts_canonical_uuid_before_authentication():
    response = Client().get("/api/v1/workspaces/018f77d8-6e61-7ca0-8c36-1ba4f1fd9d72")

    assert response.status_code == 401
