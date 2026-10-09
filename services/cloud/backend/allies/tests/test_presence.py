from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from allies.models import Ally, AllyBinding, ProvisioningOperation
from allies.services.presence import ally_ids_with_recent_activity
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
from integrations.models import BrowserSession
from routines.models import (
    Routine,
    RoutineOccurrence,
    RoutineOccurrenceDisposition,
    RoutineRunOutcome,
    RoutineRunSnapshot,
    RoutineState,
)
from workspaces.models import Membership, Workspace

LONG_AGO = timedelta(hours=1)
STALE = timedelta(hours=3)


@pytest.fixture
def workspace_setup(db):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Presence workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    return user, workspace


def _ally(workspace, user, name):
    ally = Ally.objects.create(
        workspace=workspace,
        name=name,
        job="Study partner",
        personality="Calm and specific.",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    binding = AllyBinding.objects.create(ally=ally)
    digest = str(ally.id).replace("-", "")
    ProvisioningOperation.objects.create(
        binding=binding,
        workspace=workspace,
        user=user,
        api_idempotency_key_digest=(digest * 2)[:64],
        content_fingerprint=(digest[::-1] * 2)[:64],
    )
    return ally


def _message(ally, *, status, age):
    conversation, _ = Conversation.objects.get_or_create(ally=ally)
    next_sequence = Message.objects.filter(conversation=conversation).count() + 1
    message = Message.objects.create(
        conversation=conversation,
        sequence=next_sequence,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="fixture",
        status=status,
        send_key_digest="a" * 64,
        content_fingerprint="c" * 64,
    )
    Message.objects.filter(pk=message.pk).update(updated_at=timezone.now() - age)
    return message


def _routine_run(ally, workspace, user, *, outcome, age):
    binding = ally.binding
    source = _message(ally, status=MessageLifecycle.COMPLETED, age=LONG_AGO)
    routine = Routine.objects.create(
        workspace=workspace,
        owner=user,
        ally=ally,
        binding=binding,
        main_conversation_id=source.conversation_id,
        source_message=source,
        title="Presence fixture",
        execution_prompt="Check the fixture.",
        schedule={
            "kind": "recurring",
            "frequency": "daily",
            "local_time": "09:00:00",
            "timezone": "UTC",
        },
        state=RoutineState.ACTIVE,
    )
    scheduled_at = timezone.now() - age
    occurrence = RoutineOccurrence.objects.create(
        routine=routine,
        workspace=workspace,
        owner=user,
        ally=ally,
        binding=binding,
        scheduled_at=scheduled_at,
        observed_revision=1,
        observed_schedule_generation=1,
        disposition=RoutineOccurrenceDisposition.ADMITTED,
    )
    run = RoutineRunSnapshot.objects.create(
        occurrence=occurrence,
        routine=routine,
        workspace=workspace,
        owner=user,
        ally=ally,
        binding=binding,
        routine_revision=1,
        schedule_generation=1,
        title_snapshot="Presence fixture",
        execution_prompt="Check the fixture.",
        schedule_snapshot=routine.schedule,
        timezone="UTC",
        scheduled_at=scheduled_at,
        occurrence_disposition=RoutineOccurrenceDisposition.ADMITTED,
        main_conversation_id=source.conversation_id,
        run_conversation_id=uuid4(),
        outcome=outcome,
    )
    RoutineRunSnapshot.objects.filter(pk=run.pk).update(updated_at=timezone.now() - age)
    return run


def _browser_session(
    ally, workspace, *, ended_age=None, expires_in=timedelta(minutes=10)
):
    now = timezone.now()
    session = BrowserSession.objects.create(
        workspace=workspace,
        ally=ally,
        expires_at=now + expires_in,
        ended_at=None if ended_age is None else now - ended_age,
    )
    return session


@pytest.mark.django_db
@pytest.mark.parametrize("age", [timedelta(seconds=30), timedelta(hours=1)])
@pytest.mark.parametrize(
    "status",
    [
        MessageLifecycle.QUEUED,
        MessageLifecycle.IN_PROGRESS,
        MessageLifecycle.AWAITING_ACTION,
    ],
)
def test_turn_in_flight_keeps_its_ally_awake(workspace_setup, status, age):
    user, workspace = workspace_setup
    ally = _ally(workspace, user, "Mira")
    _message(ally, status=status, age=age)

    assert ally.id in ally_ids_with_recent_activity([ally.id])


@pytest.mark.django_db
def test_turn_that_finished_recently_keeps_its_ally_awake(workspace_setup):
    user, workspace = workspace_setup
    ally = _ally(workspace, user, "Mira")
    _message(ally, status=MessageLifecycle.COMPLETED, age=timedelta(minutes=5))

    assert ally.id in ally_ids_with_recent_activity([ally.id])


@pytest.mark.django_db
def test_old_finished_turn_lets_its_ally_sleep(workspace_setup):
    user, workspace = workspace_setup
    ally = _ally(workspace, user, "Mira")
    _message(ally, status=MessageLifecycle.COMPLETED, age=LONG_AGO)

    assert ally.id not in ally_ids_with_recent_activity([ally.id])


@pytest.mark.django_db
def test_turn_stuck_in_flight_for_hours_does_not_keep_its_ally_awake(workspace_setup):
    user, workspace = workspace_setup
    ally = _ally(workspace, user, "Mira")
    _message(ally, status=MessageLifecycle.IN_PROGRESS, age=STALE)

    assert ally.id not in ally_ids_with_recent_activity([ally.id])


@pytest.mark.django_db
@pytest.mark.parametrize("age", [timedelta(minutes=2), timedelta(hours=1)])
@pytest.mark.parametrize(
    "outcome",
    [
        RoutineRunOutcome.QUEUED,
        RoutineRunOutcome.WORKING,
        RoutineRunOutcome.APPROVAL_WAITING,
    ],
)
def test_routine_run_in_flight_keeps_its_ally_awake(workspace_setup, outcome, age):
    user, workspace = workspace_setup
    ally = _ally(workspace, user, "Mira")
    _routine_run(ally, workspace, user, outcome=outcome, age=age)

    assert ally.id in ally_ids_with_recent_activity([ally.id])


@pytest.mark.django_db
def test_routine_run_stuck_in_flight_for_hours_does_not_keep_its_ally_awake(
    workspace_setup,
):
    user, workspace = workspace_setup
    ally = _ally(workspace, user, "Mira")
    _routine_run(ally, workspace, user, outcome=RoutineRunOutcome.WORKING, age=STALE)

    assert ally.id not in ally_ids_with_recent_activity([ally.id])


@pytest.mark.django_db
def test_routine_run_that_finished_recently_keeps_its_ally_awake(workspace_setup):
    user, workspace = workspace_setup
    ally = _ally(workspace, user, "Mira")
    _routine_run(
        ally,
        workspace,
        user,
        outcome=RoutineRunOutcome.SUCCEEDED,
        age=timedelta(minutes=5),
    )

    assert ally.id in ally_ids_with_recent_activity([ally.id])


@pytest.mark.django_db
def test_old_routine_run_lets_its_ally_sleep(workspace_setup):
    user, workspace = workspace_setup
    ally = _ally(workspace, user, "Mira")
    _routine_run(
        ally,
        workspace,
        user,
        outcome=RoutineRunOutcome.SUCCEEDED,
        age=LONG_AGO,
    )

    assert ally.id not in ally_ids_with_recent_activity([ally.id])


@pytest.mark.django_db
def test_open_browser_session_keeps_its_ally_awake(workspace_setup):
    user, workspace = workspace_setup
    ally = _ally(workspace, user, "Mira")
    _browser_session(ally, workspace)

    assert ally.id in ally_ids_with_recent_activity([ally.id])


@pytest.mark.django_db
def test_browser_session_closed_recently_keeps_its_ally_awake(workspace_setup):
    user, workspace = workspace_setup
    ally = _ally(workspace, user, "Mira")
    _browser_session(ally, workspace, ended_age=timedelta(minutes=5))

    assert ally.id in ally_ids_with_recent_activity([ally.id])


@pytest.mark.django_db
def test_unended_browser_session_past_its_expiry_does_not_keep_its_ally_awake(
    workspace_setup,
):
    user, workspace = workspace_setup
    ally = _ally(workspace, user, "Mira")
    _browser_session(ally, workspace, expires_in=-timedelta(minutes=1))

    assert ally.id not in ally_ids_with_recent_activity([ally.id])


@pytest.mark.django_db
def test_activity_is_reported_only_for_the_ally_that_has_it(workspace_setup):
    user, workspace = workspace_setup
    busy = _ally(workspace, user, "Mira")
    quiet = _ally(workspace, user, "Nova")
    _browser_session(busy, workspace)

    assert ally_ids_with_recent_activity([busy.id, quiet.id]) == {busy.id}


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["testserver"],
    ALLIES_AUTH_DIGEST_KEY="d" * 32,
    ALLIES_AUTH_JWT_KEY="j" * 32,
)
def test_list_reports_recent_activity_per_ally(workspace_setup):
    user, workspace = workspace_setup
    busy = _ally(workspace, user, "Mira")
    quiet = _ally(workspace, user, "Nova")
    _browser_session(busy, workspace)

    client = Client()
    client.cookies[cookie_name("access")] = issue_session(user).access_token
    response = client.get(
        f"/api/v1/workspaces/{workspace.id}/allies",
        HTTP_HOST="testserver",
    )

    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.json()["data"]["allies"]}
    assert by_id[str(busy.id)]["recent_activity"] is True
    assert by_id[str(quiet.id)]["recent_activity"] is False
