"""Durable, product-facing conversation and message records."""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

# Django model metaclasses intentionally consume mutable Meta collections.
# ruff: noqa: RUF012

MESSAGE_CONTENT_MAX_LENGTH = 16_000
ASSISTANT_REPLY_MAX_BYTES = 4 * 1024 * 1024
DIGEST_LENGTH = 64


class MessageLifecycle(models.TextChoices):
    QUEUED = "queued", "Queued"
    IN_PROGRESS = "in_progress", "In progress"
    AWAITING_ACTION = "awaiting_action", "Awaiting action"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    STOPPED = "stopped", "Stopped"


NONTERMINAL_MESSAGE_STATUSES = (
    MessageLifecycle.QUEUED,
    MessageLifecycle.IN_PROGRESS,
    MessageLifecycle.AWAITING_ACTION,
)
TERMINAL_MESSAGE_STATUSES = (
    MessageLifecycle.COMPLETED,
    MessageLifecycle.FAILED,
    MessageLifecycle.STOPPED,
)


class MessageSender(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"


class MessageOrigin(models.TextChoices):
    SEND = "send", "Send"
    ONBOARDING = "onboarding", "Onboarding"


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ally = models.ForeignKey(
        "allies.Ally", on_delete=models.CASCADE, related_name="conversations"
    )
    is_default = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("ally_id", "created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("ally",),
                condition=Q(is_default=True),
                name="chat_conversation_default_uniq",
            )
        ]

    def __str__(self) -> str:
        return str(self.id)


class Message(models.Model):
    client_timezone = models.CharField(max_length=64, blank=True, default="")
    routine_action = models.JSONField(null=True, blank=True, default=None)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
    execution_claimed_at = models.DateTimeField(null=True, blank=True, editable=False)
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)
    send_key_digest = models.CharField(
        max_length=DIGEST_LENGTH, blank=True, default="", editable=False
    )
    content_fingerprint = models.CharField(
        max_length=DIGEST_LENGTH, blank=True, default="", editable=False
    )
    retry_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="retries",
    )
    retry_allowed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("conversation", "sequence"),
                name="chat_message_sequence_uniq",
            ),
            models.CheckConstraint(
                condition=Q(retry_allowed=False)
                | Q(
                    sender=MessageSender.USER,
                    origin=MessageOrigin.SEND,
                    status=MessageLifecycle.FAILED,
                ),
                name="chat_message_retry_safe_chk",
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
                            MessageLifecycle.AWAITING_ACTION,
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
            models.CheckConstraint(
                condition=(
                    Q(execution_claimed_at__isnull=True)
                    | Q(sender=MessageSender.USER, origin=MessageOrigin.SEND)
                ),
                name="chat_message_claim_scope_chk",
            ),
            models.CheckConstraint(
                condition=(
                    Q(deleted_at__isnull=True)
                    | Q(
                        sender=MessageSender.USER,
                        origin=MessageOrigin.SEND,
                        status=MessageLifecycle.STOPPED,
                        execution_claimed_at__isnull=True,
                        content="",
                    )
                ),
                name="chat_message_tombstone_coherent_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=("conversation", "status"), name="chat_message_status_idx"
            ),
            models.Index(
                fields=("conversation", "sequence"),
                condition=Q(
                    sender=MessageSender.USER,
                    origin=MessageOrigin.SEND,
                    status__in=NONTERMINAL_MESSAGE_STATUSES,
                    deleted_at__isnull=True,
                ),
                name="chat_message_queue_idx",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)


class AssistantReply(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.OneToOneField(
        Message, on_delete=models.CASCADE, related_name="assistant_reply"
    )
    content = models.TextField(blank=True, default="")
    has_full_prefix = models.BooleanField(default=False)
    is_truncated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if (
            self.message.sender != MessageSender.USER
            or self.message.origin != MessageOrigin.SEND
        ):
            raise ValidationError("assistant reply requires a sent user message")
        if len(self.content.encode("utf-8")) > ASSISTANT_REPLY_MAX_BYTES:
            raise ValidationError("assistant reply text limit reached")


class DispatchState(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In progress"
    ACCEPTED = "accepted", "Accepted"
    RECONCILIATION_NEEDED = "reconciliation_needed", "Reconciliation needed"
    FAILED = "failed", "Failed"


class DispatchOutbox(models.Model):
    """One exact, retryable Foundry command owned by an accepted message."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.OneToOneField(
        Message,
        on_delete=models.CASCADE,
        related_name="dispatch_outbox",
    )
    command_bytes = models.BinaryField(default=bytes, editable=False)
    command_byte_length = models.PositiveIntegerField(default=0, editable=False)
    command_sha256 = models.CharField(
        max_length=DIGEST_LENGTH, blank=True, default="", editable=False
    )
    command_fingerprint = models.CharField(
        max_length=90, blank=True, default="", editable=False
    )
    status = models.CharField(
        max_length=32,
        choices=DispatchState.choices,
        default=DispatchState.PENDING,
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    safe_error_code = models.CharField(max_length=64, blank=True, default="")
    receipt_digest = models.CharField(
        max_length=DIGEST_LENGTH, blank=True, default="", editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(command_byte_length__gte=0),
                name="chat_dispatch_command_length_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    Q(command_sha256="") | Q(command_sha256__regex=r"^[0-9a-fA-F]{64}$")
                ),
                name="chat_dispatch_command_sha_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(receipt_digest="") | Q(receipt_digest__regex=r"^[0-9a-fA-F]{64}$")
                ),
                name="chat_dispatch_receipt_digest_valid",
            ),
            models.CheckConstraint(
                condition=Q(attempt_count__gte=0) & Q(attempt_count__lte=5),
                name="chat_dispatch_attempt_count_bounded",
            ),
        ]
        indexes = [
            models.Index(
                fields=("status", "next_attempt_at", "lease_expires_at"),
                name="chat_dispatch_due_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"dispatch:{self.message_id}"
