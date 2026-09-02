import pytest
from allies.models import Ally
from auths.models import User
from django.db import IntegrityError, transaction
from workspaces.models import Membership, Workspace

from chat.models import (
    Conversation,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessageSender,
)


@pytest.fixture
def account(db):
    user = User.objects.create_user()
    workspace = Workspace.objects.create(owner=user, name="Personal Workspace")
    Membership.objects.create(
        workspace=workspace, user=user, role="owner", status="active"
    )
    ally = Ally.objects.create(
        workspace=workspace,
        name="Mira",
        job="Study partner",
        personality="Calm",
        appearance_catalog_version="v1",
        appearance_key="sunrise",
    )
    return user, workspace, ally


@pytest.mark.django_db
def test_default_and_sequence_constraints(account):
    _, _, ally = account
    conversation = Conversation.objects.create(ally=ally)
    with pytest.raises(IntegrityError), transaction.atomic():
        Conversation.objects.create(ally=ally)
    Message.objects.create(
        conversation=conversation,
        sequence=1,
        sender=MessageSender.ASSISTANT,
        origin=MessageOrigin.ONBOARDING,
        content="Hello",
        status=MessageLifecycle.COMPLETED,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Message.objects.create(
            conversation=conversation,
            sequence=1,
            sender=MessageSender.USER,
            origin=MessageOrigin.ONBOARDING,
            content="Reply",
            status=MessageLifecycle.COMPLETED,
        )
    assistant = Message.objects.create(
        conversation=conversation,
        sequence=2,
        sender=MessageSender.ASSISTANT,
        origin=MessageOrigin.SEND,
        content="A later assistant response",
        status=MessageLifecycle.COMPLETED,
    )
    assert assistant.send_key_digest == ""


@pytest.mark.django_db
def test_message_origin_and_active_turn_constraints(account):
    _, _, ally = account
    conversation = Conversation.objects.create(ally=ally)
    with pytest.raises(IntegrityError), transaction.atomic():
        Message.objects.create(
            conversation=conversation,
            sequence=1,
            sender=MessageSender.USER,
            origin=MessageOrigin.ONBOARDING,
            content="Wrong role",
            status=MessageLifecycle.COMPLETED,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        Message.objects.create(
            conversation=conversation,
            sequence=3,
            sender=MessageSender.ASSISTANT,
            origin=MessageOrigin.SEND,
            content="Queued assistant",
            status=MessageLifecycle.QUEUED,
        )
    first = Message.objects.create(
        conversation=conversation,
        sequence=3,
        sender=MessageSender.USER,
        origin=MessageOrigin.SEND,
        content="First",
        status=MessageLifecycle.IN_PROGRESS,
        send_key_digest="a" * 64,
        content_fingerprint="b" * 64,
    )
    assert first.status == MessageLifecycle.IN_PROGRESS
    with pytest.raises(IntegrityError), transaction.atomic():
        Message.objects.create(
            conversation=conversation,
            sequence=4,
            sender=MessageSender.USER,
            origin=MessageOrigin.SEND,
            content="Second",
            status=MessageLifecycle.IN_PROGRESS,
            send_key_digest="c" * 64,
            content_fingerprint="d" * 64,
        )
