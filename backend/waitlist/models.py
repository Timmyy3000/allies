"""Durable state for the browser-bound waitlist preview.

The app intentionally owns exactly two models.  ``WaitlistDraft`` is the
current product snapshot and ``WaitlistOperation`` is the small retry receipt
needed to make duplicate and lost-response handling deterministic.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from common.identifiers import new_public_id

# Django model metaclasses intentionally consume mutable Meta collections.
# ruff: noqa: RUF012


class DraftLifecycle(models.TextChoices):
    CONFIGURING = "configuring", "Configuring"
    READY_FOR_GREETING = "ready_for_greeting", "Ready for greeting"
    GREETING_READY = "greeting_ready", "Greeting ready"
    REPLY_PENDING = "reply_pending", "Reply pending"
    PENDING_CLAIM = "pending_claim", "Pending claim"
    CLAIMED = "claimed", "Claimed"
    EXPIRED = "expired", "Expired"


class OperationKind(models.TextChoices):
    CREATE = "create", "Create"
    CONFIGURE = "configure", "Configure"
    GENERATE = "generate", "Generate"
    REPLY = "reply", "Reply"
    JOIN = "join", "Join"


class OperationStatus(models.TextChoices):
    IN_PROGRESS = "in_progress", "In progress"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    OUTCOME_UNKNOWN = "outcome_unknown", "Outcome unknown"


def new_draft_public_id() -> str:
    return new_public_id("wld")


class WaitlistDraft(models.Model):
    public_id = models.CharField(
        max_length=40, unique=True, editable=False, default=new_draft_public_id
    )
    capability_digest = models.CharField(
        max_length=64, unique=True, null=True, blank=True, editable=False
    )
    lifecycle = models.CharField(
        max_length=24,
        choices=DraftLifecycle.choices,
        default=DraftLifecycle.CONFIGURING,
    )
    revision = models.PositiveBigIntegerField(default=1)

    name = models.CharField(max_length=80, blank=True)
    appearance_catalog_version = models.CharField(max_length=32, blank=True)
    appearance_key = models.CharField(max_length=128, blank=True)
    job = models.TextField(blank=True)
    personality = models.TextField(blank=True)

    generation_input_digest = models.CharField(max_length=64, blank=True)
    greeting_text = models.TextField(blank=True)
    greeting_policy_version = models.CharField(max_length=32, blank=True)
    greeting_generated_at = models.DateTimeField(null=True, blank=True)

    reply_text = models.TextField(blank=True)
    reply_recorded_at = models.DateTimeField(null=True, blank=True)

    email_normalized = models.EmailField(blank=True)
    consent_version = models.CharField(max_length=64, blank=True)
    joined_at = models.DateTimeField(null=True, blank=True)

    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="claimed_waitlist_drafts",
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("lifecycle", "expires_at", "id"),
                name="waitlist_draft_retention_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(revision__gt=0), name="waitlist_draft_revision_positive"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        email_normalized="",
                        consent_version="",
                        joined_at__isnull=True,
                    )
                    | Q(
                        email_normalized__gt="",
                        consent_version__gt="",
                        joined_at__isnull=False,
                    )
                ),
                name="waitlist_draft_join_fields_coherent",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        lifecycle=DraftLifecycle.CLAIMED,
                        claimed_by__isnull=False,
                        claimed_at__isnull=False,
                        capability_digest__isnull=True,
                        expires_at__isnull=True,
                    )
                    | ~Q(lifecycle=DraftLifecycle.CLAIMED)
                ),
                name="waitlist_draft_claim_fields_coherent",
            ),
            models.CheckConstraint(
                condition=(
                    Q(greeting_text="", greeting_generated_at__isnull=True)
                    | Q(greeting_text__gt="", greeting_generated_at__isnull=False)
                ),
                name="waitlist_draft_greeting_fields_coherent",
            ),
            models.CheckConstraint(
                condition=(
                    Q(reply_text="", reply_recorded_at__isnull=True)
                    | Q(reply_text__gt="", reply_recorded_at__isnull=False)
                ),
                name="waitlist_draft_reply_fields_coherent",
            ),
        ]

    def __str__(self) -> str:
        return self.public_id


class WaitlistOperation(models.Model):
    draft = models.ForeignKey(
        WaitlistDraft, on_delete=models.CASCADE, related_name="operations"
    )
    kind = models.CharField(max_length=24, choices=OperationKind.choices)
    idempotency_digest = models.CharField(max_length=64, editable=False)
    request_digest = models.CharField(max_length=64, editable=False)
    status = models.CharField(
        max_length=24,
        choices=OperationStatus.choices,
        default=OperationStatus.IN_PROGRESS,
    )
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    result_revision = models.PositiveBigIntegerField(null=True, blank=True)
    result_lifecycle = models.CharField(max_length=24, blank=True)
    failure_code = models.CharField(max_length=64, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("draft", "kind", "idempotency_digest"),
                name="waitlist_operation_retry_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status=OperationStatus.IN_PROGRESS,
                        lease_expires_at__isnull=False,
                        completed_at__isnull=True,
                        result_revision__isnull=True,
                        result_lifecycle="",
                        failure_code="",
                    )
                    | Q(
                        status=OperationStatus.SUCCEEDED,
                        lease_expires_at__isnull=True,
                        completed_at__isnull=False,
                        result_revision__isnull=False,
                        result_lifecycle__gt="",
                        failure_code="",
                    )
                    | Q(
                        status=OperationStatus.FAILED,
                        lease_expires_at__isnull=True,
                        completed_at__isnull=False,
                        result_revision__isnull=True,
                        result_lifecycle="",
                        failure_code__gt="",
                    )
                    | Q(
                        status=OperationStatus.OUTCOME_UNKNOWN,
                        lease_expires_at__isnull=True,
                        completed_at__isnull=False,
                        result_revision__isnull=True,
                        result_lifecycle="",
                    )
                ),
                name="waitlist_operation_state_coherent",
            ),
        ]
        indexes = [
            models.Index(
                fields=("draft", "kind", "status"),
                name="waitlist_operation_lookup_idx",
            )
        ]

    def __str__(self) -> str:
        return f"{self.draft.public_id}:{self.kind}"
