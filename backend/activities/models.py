"""Cloud-owned, bounded execution activity projections and receipts."""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import BooleanField, Q, Value
from django.db.models.expressions import CombinedExpression
from django.db.models.functions import Length

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


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DECISION_RECORDED = "decision_recorded", "Decision recorded"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"
    OUTCOME_UNKNOWN = "outcome_unknown", "Outcome unknown"


class ApprovalDeliveryState(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In progress"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class Approval(models.Model):
    """Cloud-owned approval truth and its bounded Foundry delivery lease."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="approvals"
    )
    ally = models.ForeignKey(
        "allies.Ally", on_delete=models.CASCADE, related_name="approvals"
    )
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="approvals"
    )
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="approvals"
    )
    approval_request_id = models.UUIDField(unique=True, editable=False)
    cloud_binding_id = models.UUIDField(editable=False)
    execution_id = models.UUIDField(editable=False)
    attempt_id = models.UUIDField(editable=False)
    generation = models.PositiveIntegerField()
    attempt_sequence = models.PositiveIntegerField()
    action_kind = models.CharField(max_length=64)
    action_label = models.CharField(max_length=120)
    action_preview = models.TextField(max_length=16_384)
    requested_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    status = models.CharField(
        max_length=24,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )
    decision = models.CharField(max_length=7, blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)
    acknowledgement_deadline_at = models.DateTimeField(null=True, blank=True)
    deciding_user = models.ForeignKey(
        "auths.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decided_approvals",
    )
    decision_idempotency_key = models.UUIDField(null=True, blank=True, editable=False)
    decision_idempotency_key_digest = models.CharField(
        max_length=64, blank=True, default="", editable=False
    )
    decision_fingerprint = models.CharField(
        max_length=90, blank=True, default="", editable=False
    )
    delivery_state = models.CharField(
        max_length=16,
        choices=ApprovalDeliveryState.choices,
        default=ApprovalDeliveryState.PENDING,
    )
    delivery_attempt_count = models.PositiveSmallIntegerField(default=0)
    delivery_next_attempt_at = models.DateTimeField(null=True, blank=True)
    delivery_lease_expires_at = models.DateTimeField(null=True, blank=True)
    delivery_last_attempt_at = models.DateTimeField(null=True, blank=True)
    delivery_completed_at = models.DateTimeField(null=True, blank=True)
    delivery_safe_error_code = models.CharField(max_length=64, blank=True, default="")
    delivery_receipt_digest = models.CharField(
        max_length=64, blank=True, default="", editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(generation__gte=0)
                    & Q(attempt_sequence__gt=0)
                    & Q(delivery_attempt_count__gte=0)
                    & Q(delivery_attempt_count__lte=5)
                ),
                name="activities_approval_sequence_bounded",
            ),
            models.CheckConstraint(
                condition=(
                    Q(action_label__regex=r"^[^\x00]*$")
                    & ~Q(action_label="")
                    & Q(action_preview__regex=r"^[^\x00]*$")
                    & ~Q(action_preview="")
                    & CombinedExpression(
                        Length("action_preview"),
                        "<=",
                        Value(16_384),
                        output_field=BooleanField(),
                    )
                ),
                name="activities_approval_material_bounded",
            ),
            models.CheckConstraint(
                condition=Q(decision_fingerprint="")
                | Q(
                    decision_fingerprint__regex=r"^canonical-json-sha256:v1:[0-9a-f]{64}$"
                ),
                name="activities_approval_decision_fingerprint_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=("conversation", "status", "expires_at"),
                name="activities_appr_conv_idx",
            ),
            models.Index(
                fields=(
                    "delivery_state",
                    "delivery_next_attempt_at",
                    "delivery_lease_expires_at",
                ),
                name="activities_appr_delivery_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"approval:{self.id}"


class Activity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="activities"
    )
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="activities"
    )
    approval = models.ForeignKey(
        Approval,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
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
    activity_id = models.CharField(max_length=41, null=True, blank=True)
    activity_kind = models.CharField(max_length=32, null=True, blank=True)
    outcome = models.CharField(max_length=16, null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
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
    activity_id = models.CharField(max_length=41, null=True, blank=True)
    activity_kind = models.CharField(max_length=32, null=True, blank=True)
    outcome = models.CharField(max_length=16, null=True, blank=True)
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
