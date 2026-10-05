import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.test import Client, override_settings

from allies.gateways.contracts import canonical_fingerprint
from allies.models import Ally, AllyBinding
from auths.config import cookie_name
from auths.models import User
from auths.services.sessions import issue_session
from chat.models import (
    Conversation,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessageSender,
)
from routines.services.management import create_routine_intent
from workspaces.models import Membership, Workspace


def _routine_result_payload():
    routine_id = uuid4()
    occurrence_id = uuid4()
    run_id = uuid4()
    main_conversation_id = uuid4()
    run_conversation_id = uuid4()
    workspace_id = uuid4()
    owner_id = uuid4()
    ally_id = uuid4()
    binding_id = uuid4()
    issued_at = datetime(2026, 9, 10, 7, tzinfo=UTC)
    payload = {
        "schema_version": "v1",
        "kind": "routine.result",
        "producer": "foundry",
        "service_identity": "foundry-service",
        "event_id": str(uuid4()),
        "event_sequence": 1,
        "routine_id": str(routine_id),
        "occurrence_id": str(occurrence_id),
        "run_id": str(run_id),
        "routine_revision": 1,
        "title_snapshot": "API routine",
        "execution_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "generation": 1,
        "main_conversation_id": str(main_conversation_id),
        "run_conversation_id": str(run_conversation_id),
        "outcome": "unchanged",
        "text": "No changes.",
        "references": [],
        "delayed": False,
        "scope": {
            "kind": "workspace",
            "workspace_id": str(workspace_id),
            "owner_user_id": str(owner_id),
            "ally_id": str(ally_id),
            "cloud_binding_id": str(binding_id),
        },
        "issued_at": issued_at.isoformat().replace("+00:00", "Z"),
        "deadline_at": (issued_at + timedelta(seconds=30))
        .isoformat()
        .replace("+00:00", "Z"),
    }
    payload["fingerprint"] = canonical_fingerprint(payload)
    return payload


@pytest.fixture
def api_account(db):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Routine API")
    Membership.objects.create(
        workspace=workspace,
        user=user,
        role="owner",
        status="active",
    )
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study partner",
        personality="Calm and specific.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    AllyBinding.objects.create(ally=ally)
    conversation = Conversation.objects.create(ally=ally)
    routine = create_routine_intent(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        main_conversation_id=conversation.id,
        title="API routine",
        execution_prompt="Review my inbox",
        schedule={
            "kind": "recurring",
            "frequency": "daily",
            "local_time": "09:00:00",
            "timezone": "Europe/Berlin",
        },
    )
    return user, workspace, routine


@pytest.mark.django_db
@override_settings(ALLOWED_HOSTS=["testserver"])
def test_routine_discovery_api_returns_summary_and_detail(api_account):
    user, workspace, routine = api_account
    client = Client()
    issued = issue_session(user)
    client.cookies[cookie_name("access")] = issued.access_token

    page = client.get(f"/api/v1/workspaces/{workspace.id}/routines")
    assert page.status_code == 200
    item = page.json()["data"]["items"][0]
    assert item["id"] == str(routine.id)
    assert item["responsible_ally_id"] == str(routine.ally_id)
    assert "execution_prompt" not in item

    detail = client.get(f"/api/v1/workspaces/{workspace.id}/routines/{routine.id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["execution_prompt"] == "Review my inbox"

    Message.objects.bulk_create(
        [
            Message(
                conversation_id=routine.main_conversation_id,
                sequence=1,
                sender=MessageSender.ASSISTANT,
                origin=MessageOrigin.ONBOARDING,
                content="Welcome.",
                status=MessageLifecycle.COMPLETED,
            ),
            Message(
                conversation_id=routine.main_conversation_id,
                sequence=2,
                sender=MessageSender.USER,
                origin=MessageOrigin.ONBOARDING,
                content="Hello.",
                status=MessageLifecycle.COMPLETED,
            ),
        ]
    )

    conversation = client.get(
        f"/api/v1/workspaces/{workspace.id}/conversations/"
        f"{routine.main_conversation_id}"
    )
    assert conversation.status_code == 200
    assert conversation.json()["data"]["routine_items"][0]["kind"] == "created"
    assert conversation.json()["data"]["routine_items"][0]["routine_id"] == str(
        routine.id
    )


@pytest.mark.django_db
@override_settings(ALLOWED_HOSTS=["testserver"])
def test_routine_discovery_api_hides_foreign_workspace(api_account):
    user, _, routine = api_account
    other_user = User.objects.create_user()
    other_workspace = Workspace.objects.create(owner=other_user, name="Other")
    Membership.objects.create(
        workspace=other_workspace,
        user=other_user,
        role="owner",
        status="active",
    )
    client = Client()
    issued = issue_session(user)
    client.cookies[cookie_name("access")] = issued.access_token

    response = client.get(
        f"/api/v1/workspaces/{other_workspace.id}/routines/{routine.id}"
    )
    assert response.status_code == 404
    assert response.json()["data"] == {"code": "routine_unavailable"}


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN="event-secret",
    ALLIES_ROUTINE_RESULT_INGESTION_ENABLED=False,
)
def test_routine_result_ingestion_requires_token_and_fails_closed():
    payload = _routine_result_payload()
    client = Client()
    path = "/api/v1/internal/foundry/routines/results"

    unauthorized = client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert unauthorized.status_code == 401

    disabled = client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer event-secret",
    )
    assert disabled.status_code == 503
    assert disabled.json() == {"event_id": payload["event_id"], "status": "disabled"}
