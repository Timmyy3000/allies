from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event, Lock

import pytest
from django.core.cache import cache
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from allies.models import Ally, AllyBinding, BindingStatus
from auths.models import User
from chat.exceptions import MessageNotDeletable
from chat.models import (
    DispatchOutbox,
    DispatchState,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessageSender,
)
from chat.services.conversations import ensure_default_conversation
from chat.services.dispatch import (
    _claim_due,
    _mark_pre_call_failure,
    dispatch_accepted_message,
)
from chat.services.messages import (
    accept_message,
    claim_next_turn,
    delete_queued_message,
)
from workspaces.models import Membership, Workspace

pytestmark = [
    pytest.mark.postgresql,
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="requires PostgreSQL row-lock semantics",
    ),
]


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


@pytest.mark.django_db(transaction=True)
def test_concurrent_claim_and_delete_have_one_durable_winner():
    user, workspace, conversation = _account("claim-delete")
    conversation.is_default = False
    conversation.save(update_fields=("is_default", "updated_at"))
    AllyBinding.objects.create(
        ally=conversation.ally,
        status=BindingStatus.BOUND,
        receipt_digest="b" * 64,
    )
    message = Message.objects.create(
        conversation=conversation,
        sequence=3,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="Race me",
        status=MessageLifecycle.QUEUED,
        send_key_digest="a" * 64,
        content_fingerprint="c" * 64,
    )
    gate = Barrier(2)

    def claim_once():
        close_old_connections()
        gate.wait()
        try:
            claimed = claim_next_turn(conversation_id=conversation.id)
            return "claimed" if claimed is not None else "idle"
        finally:
            close_old_connections()

    def delete_once():
        close_old_connections()
        gate.wait()
        try:
            delete_queued_message(
                user=user,
                workspace_id=workspace.id,
                conversation_id=conversation.id,
                message_id=message.id,
            )
            return "deleted"
        except MessageNotDeletable:
            return "not_deletable"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        claim_result, delete_result = list(
            executor.map(lambda fn: fn(), (claim_once, delete_once))
        )

    message.refresh_from_db()
    assert {claim_result, delete_result} in (
        {"claimed", "not_deletable"},
        {"idle", "deleted"},
    )
    if delete_result == "deleted":
        assert message.status == MessageLifecycle.STOPPED
        assert message.deleted_at is not None
        assert message.execution_claimed_at is None
        assert not DispatchOutbox.objects.filter(message=message).exists()
    else:
        assert message.deleted_at is None
        assert message.execution_claimed_at is not None
        assert message.status == MessageLifecycle.QUEUED
        assert (
            DispatchOutbox.objects.get(message=message).status == DispatchState.PENDING
        )


@pytest.mark.django_db(transaction=True)
def test_stale_worker_cannot_release_after_newer_fence_claims_post_lease():
    _user, _workspace, conversation = _account("stale-fence")
    conversation.is_default = False
    conversation.save(update_fields=("is_default", "updated_at"))
    AllyBinding.objects.create(
        ally=conversation.ally,
        status=BindingStatus.BOUND,
        receipt_digest="b" * 64,
    )
    head = Message.objects.create(
        conversation=conversation,
        sequence=3,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="Old worker may still be running",
        status=MessageLifecycle.QUEUED,
        send_key_digest="a" * 64,
        content_fingerprint="c" * 64,
    )
    tail = Message.objects.create(
        conversation=conversation,
        sequence=4,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="Must remain queued",
        status=MessageLifecycle.QUEUED,
        send_key_digest="d" * 64,
        content_fingerprint="e" * 64,
    )
    dispatch_accepted_message(head)
    dispatch_accepted_message(tail)
    now = timezone.now()
    head_outbox = DispatchOutbox.objects.get(message=head)
    head_outbox.status = DispatchState.IN_PROGRESS
    head_outbox.attempt_count = 1
    head_outbox.next_attempt_at = now - timedelta(seconds=1)
    head_outbox.lease_expires_at = now - timedelta(seconds=1)
    head_outbox.save(
        update_fields=(
            "status",
            "attempt_count",
            "next_attempt_at",
            "lease_expires_at",
            "updated_at",
        )
    )

    old_locked = Event()
    new_started = Event()
    release_old = Event()
    newer_done = Event()
    stale_result: list[bool] = []
    newer_claims: list[tuple] = []

    def old_worker():
        close_old_connections()
        try:
            with transaction.atomic():
                DispatchOutbox.objects.select_for_update().get(pk=head_outbox.pk)
                old_locked.set()
                if not release_old.wait(timeout=20):
                    raise RuntimeError("newer worker did not start")
            if not newer_done.wait(timeout=20):
                raise RuntimeError("newer worker did not finish")
            stale_result.append(
                _mark_pre_call_failure(
                    head_outbox.pk,
                    1,
                    "binding_unavailable",
                    now=timezone.now(),
                )
            )
        finally:
            close_old_connections()

    def newer_worker():
        close_old_connections()
        try:
            if not old_locked.wait(timeout=20):
                raise RuntimeError("old worker did not lock outbox")
            new_started.set()
            newer_claims.extend(_claim_due(now=now, limit=1))
        finally:
            newer_done.set()
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        old_future = executor.submit(old_worker)
        assert old_locked.wait(timeout=20)
        newer_future = executor.submit(newer_worker)
        assert new_started.wait(timeout=20)
        release_old.set()
        old_future.result()
        newer_future.result()

    assert newer_claims == [(head_outbox.pk, 2, True)]
    assert stale_result == [False]
    head.refresh_from_db()
    tail.refresh_from_db()
    head_outbox.refresh_from_db()
    assert head.execution_claimed_at is not None
    assert head.status == MessageLifecycle.QUEUED
    assert head_outbox.status == DispatchState.IN_PROGRESS
    assert head_outbox.attempt_count == 2
    assert tail.execution_claimed_at is None
    assert not DispatchOutbox.objects.filter(
        message=tail, status=DispatchState.FAILED
    ).exists()
