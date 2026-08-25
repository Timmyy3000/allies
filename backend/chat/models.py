"""Durable, product-facing conversation and message records."""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from common.identifiers import new_public_id

# Django model metaclasses intentionally consume mutable Meta collections.
# ruff: noqa: RUF012

PUBLIC_ID_MAX_LENGTH = 40
MESSAGE_CONTENT_MAX_LENGTH = 16_000
DIGEST_LENGTH = 64


class MessageLifecycle(models.TextChoices):
    QUEUED = "queued", "Queued"
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    STOPPED = "stopped", "Stopped"


class MessageSender(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"


class MessageOrigin(models.TextChoices):
    SEND = "send", "Send"
    ONBOARDING = "onboarding", "Onboarding"


def new_conversation_public_id() -> str:
    return new_public_id("conv")


def new_message_public_id() -> str:
    return new_public_id("msg")


class Conversation(models.Model):
    public_id = models.CharField(
        max_length=PUBLIC_ID_MAX_LENGTH,
        unique=True,
        editable=False,
        default=new_conversation_public_id,
    )
    ally = models.ForeignKey(
        "allies.Ally", on_delete=models.CASCADE, related_name="conversations"
    )
    is_default = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("ally_id", "public_id")
        constraints = [
            models.UniqueConstraint(
                fields=("ally",),
                condition=Q(is_default=True),
                name="chat_conversation_default_uniq",
            )
        ]

    def __str__(self) -> str:
        return self.public_id


class Message(models.Model):
    public_id = models.CharField(
        max_length=PUBLIC_ID_MAX_LENGTH,
        unique=True,
        editable=False,
        default=new_message_public_id,
    )
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sequence = models.PositiveIntegerField()
    sender = models.CharField(max_length=16, choices=MessageSender.choices)
    origin = models.CharField(max_length=16, choices=MessageOrigin.choices)
    content = models.TextField(max_length=MESSAGE_CONTENT_MAX_LENGTH)
    status = models.CharField(
        max_length=16,
        choices=MessageLifecycle.choices,
        default=MessageLifecycle.QUEUED,
    )
    send_key_digest = models.CharField(
        max_length=DIGEST_LENGTH, blank=True, default="", editable=False
    )
    content_fingerprint = models.CharField(
        max_length=DIGEST_LENGTH, blank=True, default="", editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("sequence", "public_id")
        constraints = [
            models.UniqueConstraint(
                fields=("conversation", "sequence"),
                name="chat_message_sequence_uniq",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gt=0),
                name="chat_message_sequence_positive_chk",
            ),
            models.UniqueConstraint(
                fields=("conversation", "send_key_digest"),
                condition=Q(
                    origin=MessageOrigin.SEND,
                    sender=MessageSender.USER,
                    send_key_digest__gt="",
                ),
                name="chat_message_send_key_uniq",
            ),
            models.UniqueConstraint(
                fields=("conversation",),
                condition=Q(
                    origin=MessageOrigin.SEND,
                    sender=MessageSender.USER,
                    status=MessageLifecycle.IN_PROGRESS,
                ),
                name="chat_message_active_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        origin=MessageOrigin.SEND,
                        sender=MessageSender.USER,
                        send_key_digest__regex=r"^[0-9a-fA-F]{64}$",
                        content_fingerprint__regex=r"^[0-9a-fA-F]{64}$",
                    )
                    | Q(
                        origin=MessageOrigin.SEND,
                        sender=MessageSender.ASSISTANT,
                        send_key_digest="",
                        content_fingerprint="",
                        status__in=(
                            MessageLifecycle.IN_PROGRESS,
                            MessageLifecycle.COMPLETED,
                            MessageLifecycle.FAILED,
                            MessageLifecycle.STOPPED,
                        ),
                    )
                    | Q(
                        origin=MessageOrigin.ONBOARDING,
                        sender=MessageSender.ASSISTANT,
                        sequence=1,
                        send_key_digest="",
                        content_fingerprint="",
                        status=MessageLifecycle.COMPLETED,
                    )
                    | Q(
                        origin=MessageOrigin.ONBOARDING,
                        sender=MessageSender.USER,
                        sequence=2,
                        send_key_digest="",
                        content_fingerprint="",
                        status=MessageLifecycle.COMPLETED,
                    )
                ),
                name="chat_message_origin_coherent",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        sender__in=(MessageSender.USER, MessageSender.ASSISTANT),
                        origin__in=(MessageOrigin.SEND, MessageOrigin.ONBOARDING),
                    )
                ),
                name="chat_message_role_origin_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=("conversation", "status"), name="chat_message_status_idx"
            ),
        ]

    def __str__(self) -> str:
        return self.public_id
