from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest
from django.core.cache import cache
from django.db import close_old_connections, connection

from allies.models import Ally
from auths.models import User
from chat.models import Message
from chat.services.conversations import ensure_default_conversation
from chat.services.messages import accept_message
from workspaces.models import Membership, Workspace

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="requires PostgreSQL row-lock semantics",
)


def _account(suffix: str):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(
        owner=user,
        name="Race Workspace",
    )
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
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    conversation = ensure_default_conversation(
        ally=ally,
        greeting="Hello",
        reply="Ready",
    )
    return user, workspace, conversation


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_key_creates_one_message_and_one_rate_reservation(
    monkeypatch,
):
    cache.clear()
    user, workspace, conversation = _account("same")
    gate = Barrier(2)
    calls = 0
    calls_lock = Lock()

    from chat.services import messages as message_service

    original = message_service.enforce_send_rate_limit

    def counted_rate_limit(**kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        return original(**kwargs)

    monkeypatch.setattr(message_service, "enforce_send_rate_limit", counted_rate_limit)

    def send_once():
        close_old_connections()
        gate.wait()
        try:
            result = accept_message(
                user=user,
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                content="Same request",
                idempotency_key="chat-race-same-key-0001",
            )
            return result.message.id
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        message_ids = list(executor.map(lambda _index: send_once(), range(2)))

    assert message_ids[0] == message_ids[1]
    assert calls == 1
    assert Message.objects.filter(conversation=conversation).count() == 3


@pytest.mark.django_db(transaction=True)
def test_concurrent_distinct_sends_receive_unique_order():
    cache.clear()
    user, workspace, conversation = _account("order")
    gate = Barrier(2)

    def send_once(index: int):
        close_old_connections()
        gate.wait()
        try:
            result = accept_message(
                user=user,
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                content=f"Request {index}",
                idempotency_key=f"chat-race-order-key-{index:04d}",
            )
            return result.message.sequence
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        sequences = list(executor.map(send_once, range(2)))

    assert sorted(sequences) == [3, 4]
    assert list(
        Message.objects.filter(conversation=conversation)
        .order_by("sequence")
        .values_list("sequence", flat=True)
    ) == [1, 2, 3, 4]
