from datetime import UTC, datetime

import pytest

from allies.models import Ally, AllyBinding
from auths.models import User
from chat.models import Conversation
from routines.services.management import (
    RoutineCursorInvalid,
    create_routine_intent,
    owner_routine_page,
)
from workspaces.models import Membership, Workspace


@pytest.fixture
def discovery_account(db):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Routine discovery")
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
    return user, workspace, ally, conversation


def _create(account, *, title):
    user, workspace, ally, conversation = account
    return create_routine_intent(
        user=user,
        workspace_id=workspace.id,
        ally_id=ally.id,
        main_conversation_id=conversation.id,
        title=title,
        execution_prompt=f"Prompt for {title}",
        schedule={
            "kind": "recurring",
            "frequency": "daily",
            "local_time": "09:00:00",
            "timezone": "Europe/Berlin",
        },
        now=datetime(2026, 9, 10, 6, tzinfo=UTC),
    )


@pytest.mark.django_db
def test_discovery_is_keyset_paged_and_omits_full_prompt(discovery_account):
    first = _create(discovery_account, title="First")
    second = _create(discovery_account, title="Second")
    user, workspace, _, _ = discovery_account

    page = owner_routine_page(user=user, workspace_id=workspace.id, limit=1)
    assert page.items == (first,)
    assert page.next_cursor
    assert not hasattr(page.items[0], "prompt")

    next_page = owner_routine_page(
        user=user,
        workspace_id=workspace.id,
        limit=1,
        cursor=page.next_cursor,
    )
    assert next_page.items == (second,)
    assert next_page.next_cursor is None


@pytest.mark.django_db
def test_discovery_cursor_is_bound_to_owner_and_filter(discovery_account):
    routine = _create(discovery_account, title="Cursor")
    _create(discovery_account, title="Cursor two")
    user, workspace, ally, _ = discovery_account
    page = owner_routine_page(user=user, workspace_id=workspace.id, limit=1)

    with pytest.raises(RoutineCursorInvalid):
        owner_routine_page(
            user=user,
            workspace_id=workspace.id,
            cursor=page.next_cursor[:-1]
            + ("0" if page.next_cursor[-1] != "0" else "1"),
        )

    with pytest.raises(RoutineCursorInvalid):
        owner_routine_page(
            user=user,
            workspace_id=workspace.id,
            ally_id=ally.id,
            cursor=page.next_cursor,
        )

    assert routine.execution_prompt == "Prompt for Cursor"
