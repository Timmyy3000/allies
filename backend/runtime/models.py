from __future__ import annotations

import re
import uuid
from typing import ClassVar

from django.db import models, transaction
from django.db.models import Q

from runtime.exceptions import RuntimeConflictError, RuntimeValidationError
from runtime.profile_keys import (
    PROFILE_KEY_REGEX,
    RESERVED_PROFILE_KEYS,
    validate_hermes_profile_key,
)


class ExecutionStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    UNKNOWN = "unknown", "Unknown"


class AttemptStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    LEASED = "leased", "Leased"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    UNKNOWN = "unknown", "Unknown"


class LeaseState(models.TextChoices):
    ACTIVE = "active", "Active"
    STOPPING = "stopping", "Stopping"
    RELEASED = "released", "Released"
    FENCED = "fenced", "Fenced"


class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_ref = models.CharField(max_length=255, unique=True)
    fly_app_ref = models.CharField(max_length=255)
    volume_ref = models.CharField(max_length=255)
    machine_ref = models.CharField(max_length=255)
    machine_generation = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar = ["tenant_ref"]

    def __str__(self) -> str:
        return self.tenant_ref


class RuntimeProfileQuerySet(models.QuerySet):
    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        if update_conflicts and update_fields and "hermes_profile_key" in update_fields:
            raise RuntimeConflictError("Hermes profile key is immutable")
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )

    def update(self, **kwargs):
        if "hermes_profile_key" in kwargs:
            raise RuntimeConflictError("Hermes profile key is immutable")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if "hermes_profile_key" in fields:
            raise RuntimeConflictError("Hermes profile key is immutable")
        return super().bulk_update(objs, fields, batch_size=batch_size)


class RuntimeProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="profiles",
    )
    ally_ref = models.CharField(max_length=255)
    hermes_profile_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = RuntimeProfileQuerySet.as_manager()

    class Meta:
        base_manager_name = "objects"
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["workspace", "ally_ref"],
                name="runtime_profile_workspace_ally_unique",
            ),
            models.UniqueConstraint(
                fields=["workspace", "hermes_profile_key"],
                name="runtime_profile_workspace_hermes_unique",
            ),
            models.CheckConstraint(
                condition=(
                    Q(hermes_profile_key__regex=PROFILE_KEY_REGEX)
                    & ~Q(hermes_profile_key__contains="\n")
                    & ~Q(hermes_profile_key__contains="\r")
                    & ~Q(hermes_profile_key__in=RESERVED_PROFILE_KEYS)
                ),
                name="runtime_profile_hermes_key_contract",
            ),
        ]
        ordering: ClassVar = ["workspace_id", "ally_ref"]

    def __str__(self) -> str:
        return self.hermes_profile_key

    def save(self, *args, **kwargs):
        validate_hermes_profile_key(self.hermes_profile_key)
        if not self._state.adding:
            with transaction.atomic():
                try:
                    previous_key = (
                        type(self)
                        .objects.select_for_update()
                        .only("hermes_profile_key")
                        .get(pk=self.pk)
                        .hermes_profile_key
                    )
                except type(self).DoesNotExist:
                    previous_key = self.hermes_profile_key
                if previous_key != self.hermes_profile_key:
                    raise RuntimeConflictError("Hermes profile key is immutable")
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)


class ConversationBinding(models.Model):
    profile = models.OneToOneField(
        RuntimeProfile,
        on_delete=models.CASCADE,
        related_name="conversation_binding",
        primary_key=True,
    )
    cloud_conversation_ref = models.CharField(max_length=255, unique=True)
    hermes_session_id = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.cloud_conversation_ref


class Execution(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="executions",
    )
    profile = models.ForeignKey(
        RuntimeProfile,
        on_delete=models.CASCADE,
        related_name="executions",
    )
    idempotency_key = models.CharField(max_length=255)
    input_payload = models.JSONField(default=dict)
    payload_digest = models.CharField(max_length=64, default="", editable=False)
    status = models.CharField(
        max_length=16,
        choices=ExecutionStatus,
        default=ExecutionStatus.QUEUED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["workspace", "idempotency_key"],
                name="runtime_execution_workspace_idempotency_unique",
            ),
        ]
        indexes: ClassVar = [
            models.Index(
                fields=["profile", "status", "created_at"],
                name="rt_exec_prof_status_idx",
            ),
        ]


class Attempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    execution = models.ForeignKey(
        Execution,
        on_delete=models.CASCADE,
        related_name="attempts",
    )
    number = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16,
        choices=AttemptStatus,
        default=AttemptStatus.QUEUED,
    )
    machine_generation = models.PositiveIntegerField()
    claimed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["execution", "number"],
                name="runtime_attempt_execution_number_unique",
            ),
            models.CheckConstraint(
                condition=Q(number__gt=0),
                name="runtime_attempt_number_positive",
            ),
        ]
        indexes: ClassVar = [
            models.Index(
                fields=["status", "claimed_at"],
                name="rt_attempt_status_claimed_idx",
            ),
        ]


class Lease(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.OneToOneField(
        Attempt,
        on_delete=models.CASCADE,
        related_name="lease",
    )
    profile = models.ForeignKey(
        RuntimeProfile,
        on_delete=models.CASCADE,
        related_name="leases",
    )
    token_digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    machine_generation = models.PositiveIntegerField()
    state = models.CharField(
        max_length=16,
        choices=LeaseState,
        default=LeaseState.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["profile"],
                condition=Q(state__in=[LeaseState.ACTIVE, LeaseState.STOPPING]),
                name="runtime_lease_profile_unresolved_unique",
            ),
            models.CheckConstraint(
                condition=Q(state__in=LeaseState.values),
                name="runtime_lease_state_valid",
            ),
        ]
        indexes: ClassVar = [
            models.Index(
                fields=["profile", "state", "expires_at"],
                name="rt_lease_profile_state_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        if not re.fullmatch(r"[0-9a-f]{64}", self.token_digest):
            raise RuntimeValidationError(
                "lease token_digest must be a SHA-256 hex digest"
            )
        return super().save(*args, **kwargs)


class ExecutionEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(
        Attempt,
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_id = models.UUIDField()
    sequence = models.PositiveIntegerField()
    event_type = models.CharField(max_length=128)
    payload = models.JSONField(default=dict)
    payload_digest = models.CharField(max_length=64, default="", editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["attempt", "event_id"],
                name="runtime_event_attempt_event_id_unique",
            ),
            models.UniqueConstraint(
                fields=["attempt", "sequence"],
                name="runtime_event_attempt_sequence_unique",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gt=0),
                name="runtime_event_sequence_positive",
            ),
        ]
