"""Cloud-owned, bounded execution activity projections and receipts."""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q

from chat.models import Conversation, Message

# Django model metaclasses intentionally consume mutable Meta collections.
# ruff: noqa: RUF012


class ProjectionState(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    AWAITING_ACTION = "awaiting_action", "Awaiting action"
    COMPLETED = "completed", "Completed"
    STOPPED = "stopped", "Stopped"
    FAILED = "failed", "Failed"
    RECONCILIATION_NEEDED = "reconciliation_needed", "Reconciliation needed"


class Activity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="activities"
    )
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="activities"
    )
    sequence = models.PositiveIntegerField()
    conversation_turn_ordinal = models.PositiveIntegerField()
    generation = models.PositiveIntegerField()
    attempt_id = models.UUIDField()
    attempt_sequence = models.PositiveIntegerField()
    event_id = models.UUIDField()
    event_type = models.CharField(max_length=64)
    kind = models.CharField(max_length=64)
    text = models.TextField(max_length=16_000, blank=True, default="")
    state = models.CharField(max_length=32, choices=ProjectionState.choices)
    event_fingerprint = models.CharField(max_length=90)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("sequence", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("conversation", "sequence"),
                name="activities_conversation_sequence_uniq",
            ),
            models.UniqueConstraint(
                fields=("message", "attempt_id", "event_id"),
                name="activities_event_identity_uniq",
            ),
            models.UniqueConstraint(
                fields=("message", "attempt_id", "attempt_sequence"),
                name="activities_attempt_sequence_uniq",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gt=0)
                & Q(conversation_turn_ordinal__gt=0)
                & Q(generation__gte=0)
                & Q(attempt_sequence__gt=0),
                name="activities_sequence_positive",
            ),
            models.CheckConstraint(
                condition=Q(
                    event_fingerprint__regex=r"^canonical-json-sha256:v1:[0-9a-f]{64}$"
                ),
                name="activities_fingerprint_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=("conversation", "conversation_turn_ordinal", "sequence"),
                name="activities_conv_turn_idx",
            ),
            models.Index(
                fields=("message", "generation", "attempt_sequence"),
                name="activities_message_attempt_idx",
            ),
        ]

    @property
    def stable_event_id(self):
        return self.event_id


class FoundryEventReceipt(models.Model):
    """Immutable identity/fingerprint receipt for accepted event envelopes."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="foundry_event_receipts"
    )
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="foundry_event_receipts"
    )
    event_id = models.UUIDField()
    execution_id = models.UUIDField(default=uuid.uuid4, editable=False)
    event_dedupe_key = models.CharField(max_length=255)
    attempt_id = models.UUIDField()
    generation = models.PositiveIntegerField()
    attempt_sequence = models.PositiveIntegerField()
    event_fingerprint = models.CharField(max_length=90)
    result = models.CharField(max_length=16, choices=(("applied", "Applied"),))
    product_sequence = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("message", "attempt_id", "event_id"),
                name="activities_receipt_event_identity_uniq",
            ),
            models.UniqueConstraint(
                fields=("message", "attempt_id", "attempt_sequence"),
                name="activities_receipt_attempt_sequence_uniq",
            ),
            models.CheckConstraint(
                condition=Q(generation__gte=0) & Q(attempt_sequence__gt=0),
                name="activities_receipt_sequence_positive",
            ),
            models.CheckConstraint(
                condition=Q(
                    event_fingerprint__regex=r"^canonical-json-sha256:v1:[0-9a-f]{64}$"
                ),
                name="activities_receipt_fingerprint_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=("message", "generation", "attempt_sequence"),
                name="activities_receipt_order_idx",
            ),
            models.Index(
                fields=("conversation", "created_at"),
                name="activities_receipt_conv_idx",
            ),
        ]
