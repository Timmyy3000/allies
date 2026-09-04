"""Durable Cloud product records for Workspace-owned Allies."""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

# Django model metaclasses intentionally consume mutable Meta collections.
# ruff: noqa: RUF012

ALLY_NAME_MAX_LENGTH = 80
ALLY_JOB_MAX_LENGTH = 200
ALLY_PERSONALITY_MAX_LENGTH = 4000
APPEARANCE_CATALOG_VERSION_MAX_LENGTH = 32
APPEARANCE_KEY_MAX_LENGTH = 128
ONBOARDING_TEXT_MAX_LENGTH = 4000
DIGEST_LENGTH = 64


class BindingStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    BOUND = "bound", "Bound"
    INCOMPATIBLE = "incompatible", "Incompatible"


class ProvisioningStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In progress"
    SUCCEEDED = "succeeded", "Succeeded"
    RETRYABLE = "retryable", "Retryable"
    FAILED = "failed", "Failed"
    REPAIR_REQUIRED = "repair_required", "Repair required"
    EXPIRED = "expired", "Expired"


class Ally(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="allies",
    )
    name = models.CharField(max_length=ALLY_NAME_MAX_LENGTH)
    job = models.CharField(max_length=ALLY_JOB_MAX_LENGTH)
    personality = models.TextField(max_length=ALLY_PERSONALITY_MAX_LENGTH)
    appearance_catalog_version = models.CharField(
        max_length=APPEARANCE_CATALOG_VERSION_MAX_LENGTH
    )
    appearance_key = models.CharField(max_length=APPEARANCE_KEY_MAX_LENGTH)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("workspace_id", "created_at", "id")
        indexes = [
            models.Index(
                fields=("workspace", "created_at"),
                name="ally_workspace_created_idx",
            )
        ]

    def __str__(self) -> str:
        return str(self.id)

    @property
    def provisioning_state(self) -> str:
        """Derive the public state from the binding and operation rows."""

        try:
            binding = self.binding
        except AllyBinding.DoesNotExist:
            return BindingStatus.PENDING

        try:
            operation = binding.provisioning_operation
        except ProvisioningOperation.DoesNotExist:
            operation = None

        if operation is not None and operation.status in {
            ProvisioningStatus.REPAIR_REQUIRED,
            ProvisioningStatus.EXPIRED,
        }:
            return ProvisioningStatus.REPAIR_REQUIRED

        if binding.status == BindingStatus.BOUND:
            return BindingStatus.BOUND
        if binding.status == BindingStatus.INCOMPATIBLE:
            return BindingStatus.INCOMPATIBLE

        if operation is None:
            return binding.status

        return {
            ProvisioningStatus.SUCCEEDED: BindingStatus.BOUND,
            ProvisioningStatus.RETRYABLE: ProvisioningStatus.RETRYABLE,
            ProvisioningStatus.FAILED: ProvisioningStatus.FAILED,
            ProvisioningStatus.REPAIR_REQUIRED: ProvisioningStatus.REPAIR_REQUIRED,
            ProvisioningStatus.EXPIRED: ProvisioningStatus.REPAIR_REQUIRED,
        }.get(operation.status, "pending")


class AllyBinding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ally = models.OneToOneField(
        Ally,
        on_delete=models.CASCADE,
        related_name="binding",
    )
    version = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(
        max_length=24,
        choices=BindingStatus.choices,
        default=BindingStatus.PENDING,
    )
    receipt_digest = models.CharField(
        max_length=DIGEST_LENGTH,
        blank=True,
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.CheckConstraint(
                condition=Q(version__gt=0),
                name="allies_binding_version_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(receipt_digest="") | Q(receipt_digest__regex=r"^[0-9a-fA-F]{64}$")
                ),
                name="allies_binding_receipt_digest_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status=BindingStatus.BOUND, receipt_digest__gt="")
                    | ~Q(status=BindingStatus.BOUND)
                ),
                name="allies_binding_bound_receipt_required",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)


class OnboardingAttempt(models.Model):
    """One expiring, transport-bound official onboarding handoff."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt_token_digest = models.CharField(
        max_length=DIGEST_LENGTH,
        unique=True,
        editable=False,
    )
    browser_binding_digest = models.CharField(
        max_length=DIGEST_LENGTH,
        editable=False,
    )
    name = models.CharField(max_length=ALLY_NAME_MAX_LENGTH)
    job = models.CharField(max_length=ALLY_JOB_MAX_LENGTH)
    personality = models.TextField(max_length=ALLY_PERSONALITY_MAX_LENGTH)
    appearance_catalog_version = models.CharField(
        max_length=APPEARANCE_CATALOG_VERSION_MAX_LENGTH
    )
    appearance_key = models.CharField(max_length=APPEARANCE_KEY_MAX_LENGTH)
    greeting = models.TextField(max_length=ONBOARDING_TEXT_MAX_LENGTH)
    reply = models.TextField(
        max_length=ONBOARDING_TEXT_MAX_LENGTH,
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="onboarding_attempts",
    )
    ally = models.OneToOneField(
        Ally,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="onboarding_attempt",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("expires_at", "consumed_at"),
                name="attempt_expiry_consumed_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        ally__isnull=True,
                        consumed_at__isnull=True,
                        reply__isnull=True,
                        user__isnull=True,
                    )
                    | Q(
                        ally__isnull=False,
                        consumed_at__isnull=False,
                        reply__gt="",
                        user__isnull=False,
                    )
                ),
                name="allies_attempt_consumption_coherent",
            )
        ]

    def __str__(self) -> str:
        return f"onboarding-attempt:{self.pk}"

    def is_expired(self, now=None) -> bool:
        return self.expires_at <= (now or timezone.now())

    def is_usable(self, now=None) -> bool:
        return self.consumed_at is None and not self.is_expired(now)

    def consume(self, *, user, ally, reply: str, now=None):
        now = now or timezone.now()
        if self.consumed_at is not None:
            raise ValueError("onboarding attempt is already consumed")
        if self.expires_at <= now:
            raise ValueError("onboarding attempt is expired")
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("onboarding reply is required")
        if len(reply) > ONBOARDING_TEXT_MAX_LENGTH:
            raise ValueError("onboarding reply is too long")
        self.user = user
        self.ally = ally
        self.reply = reply
        self.consumed_at = now
        self.save(update_fields=("user", "ally", "reply", "consumed_at", "updated_at"))


def default_operation_expiry():
    return timezone.now() + timedelta(hours=24)


class ProvisioningOperation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    binding = models.OneToOneField(
        AllyBinding,
        on_delete=models.CASCADE,
        related_name="provisioning_operation",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="provisioning_operations",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="provisioning_operations",
    )
    api_idempotency_key_digest = models.CharField(
        max_length=DIGEST_LENGTH,
        editable=False,
    )
    content_fingerprint = models.CharField(
        max_length=DIGEST_LENGTH,
        editable=False,
    )
    status = models.CharField(
        max_length=24,
        choices=ProvisioningStatus.choices,
        default=ProvisioningStatus.PENDING,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(default=default_operation_expiry)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    safe_error_code = models.CharField(max_length=64, blank=True)
    receipt_digest = models.CharField(
        max_length=DIGEST_LENGTH,
        blank=True,
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "user", "api_idempotency_key_digest"),
                name="allies_operation_identity_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(api_idempotency_key_digest__regex=r"^[0-9a-fA-F]{64}$")
                    & Q(content_fingerprint__regex=r"^[0-9a-fA-F]{64}$")
                ),
                name="allies_operation_digests_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(receipt_digest="") | Q(receipt_digest__regex=r"^[0-9a-fA-F]{64}$")
                ),
                name="allies_operation_receipt_digest_valid",
            ),
            models.CheckConstraint(
                condition=Q(attempt_count__gte=0),
                name="allies_operation_attempt_count_nonnegative",
            ),
        ]
        indexes = [
            models.Index(
                fields=("status", "next_attempt_at", "lease_expires_at"),
                name="allies_operation_due_idx",
            ),
            models.Index(
                fields=("workspace", "user", "created_at"),
                name="allies_operation_scope_idx",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)
