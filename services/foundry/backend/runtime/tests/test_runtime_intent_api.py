from uuid import uuid4

import pytest
from django.test import override_settings
from django.utils import timezone

from runtime.models import RuntimeIntent, Workspace


@pytest.mark.django_db
@override_settings(ALLIES_CLOUD_SERVICE_TOKEN="test-cloud-service-token")
@pytest.mark.parametrize("intent", ["composing_started", "ally_creation_started"])
def test_control_intent_resolves_cloud_identity_without_rebinding(client, intent):
    cloud_id = uuid4()
    workspace = Workspace.objects.create(tenant_ref=str(cloud_id))
    response = client.post(
        f"/api/v1/control/workspaces/{cloud_id}/runtime-intents",
        {"intent": intent, "received_at": timezone.now().isoformat()},
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer test-cloud-service-token",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "first_provision_required"
    assert RuntimeIntent.objects.get().workspace_id == workspace.id
    workspace.refresh_from_db()
    assert workspace.tenant_ref == str(cloud_id)


@pytest.mark.django_db
@override_settings(ALLIES_CLOUD_SERVICE_TOKEN="test-cloud-service-token")
def test_unknown_cloud_identity_does_not_create_or_address_internal_workspace(client):
    workspace = Workspace.objects.create(tenant_ref=str(uuid4()))
    response = client.post(
        f"/api/v1/control/workspaces/{workspace.id}/runtime-intents",
        {"intent": "ally_creation_started", "received_at": timezone.now().isoformat()},
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer test-cloud-service-token",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "first_provision_required"
    assert Workspace.objects.count() == 1
    assert not RuntimeIntent.objects.exists()


@pytest.mark.django_db
@override_settings(ALLIES_CLOUD_SERVICE_TOKEN="test-cloud-service-token")
def test_unknown_workspace_intent_still_requires_service_authentication(client):
    response = client.post(
        f"/api/v1/control/workspaces/{uuid4()}/runtime-intents",
        {"intent": "ally_creation_started", "received_at": timezone.now().isoformat()},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert response.status_code in (401, 403)
    assert not Workspace.objects.exists()
