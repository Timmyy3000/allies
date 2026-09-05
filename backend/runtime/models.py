from __future__ import annotations

import re
import uuid
from typing import ClassVar

from django.db import models, transaction
from django.db.models import Q

from runtime.contracts import MAX_TERMINAL_SEQUENCE
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


class EventDeliveryState(models.TextChoices):
    PENDING = "pending", "Pending"
    DELIVERING = "delivering", "Delivering"
    DELIVERED = "delivered", "Delivered"
    EXHAUSTED = "exhausted", "Exhausted"


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


class RuntimeProfileLifecycleState(models.TextChoices):
    PENDING = "pending", "Pending"
    ACTIVE = "active", "Active"
    CLEANUP_PENDING = "cleanup_pending", "Cleanup pending"
    DEPROVISIONED = "deprovisioned", "Deprovisioned"
    REPAIR_REQUIRED = "repair_required", "Repair required"


class WorkspaceProvisioningKind(models.TextChoices):
    ENSURE = "ensure", "Ensure"
    REPLACE = "replace", "Replace"


class WorkspaceProvisioningPhase(models.TextChoices):
    IDLE = "idle", "Idle"
    APP_READY = "app_ready", "App ready"
    VOLUME_READY = "volume_ready", "Volume ready"
    OLD_MACHINE_STOPPED = "old_machine_stopped", "Old Machine stopped"
    OLD_MACHINE_DESTROYED = "old_machine_destroyed", "Old Machine destroyed"
    MACHINE_CREATED = "machine_created", "Machine created"
    MACHINE_STARTED = "machine_started", "Machine started"
    HEALTHY = "healthy", "Healthy"
    FAILED = "failed", "Failed"


IN_FLIGHT_PROVISIONING_PHASES = (
    WorkspaceProvisioningPhase.APP_READY,
    WorkspaceProvisioningPhase.VOLUME_READY,
    WorkspaceProvisioningPhase.OLD_MACHINE_STOPPED,
    WorkspaceProvisioningPhase.OLD_MACHINE_DESTROYED,
    WorkspaceProvisioningPhase.MACHINE_CREATED,
    WorkspaceProvisioningPhase.MACHINE_STARTED,
    WorkspaceProvisioningPhase.HEALTHY,
)


class RuntimeOperationState(models.TextChoices):
    IDLE = "idle", "Idle"
    REQUESTED = "requested", "Requested"
    STARTING = "starting", "Starting"
    AWAITING_READINESS = "awaiting_readiness", "Awaiting readiness"
    STOPPING = "stopping", "Stopping"


class RuntimeOperationTrigger(models.TextChoices):
    SPECULATIVE = "speculative", "Speculative"
    EXECUTION = "execution", "Execution"


class RuntimeIntentType(models.TextChoices):
    COMPOSING_STARTED = "composing_started", "Composing started"


class RuntimeIntentOutcome(models.TextChoices):
    ALREADY_READY = "already_ready", "Already ready"
    WAKING = "waking", "Waking"
    READY = "ready", "Ready"
    FIRST_PROVISION_REQUIRED = "first_provision_required", "First provision required"
    RATE_LIMITED = "rate_limited", "Rate limited"
    FAILED = "failed", "Failed"


class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_ref = models.CharField(max_length=255, unique=True)
    fly_app_ref = models.CharField(max_length=255, null=True, blank=True)
    volume_ref = models.CharField(max_length=255, null=True, blank=True)
    machine_ref = models.CharField(max_length=255, null=True, blank=True)
    machine_generation = models.PositiveIntegerField(default=0)
    runtime_operation_id = models.UUIDField(null=True, blank=True)
    runtime_operation_state = models.CharField(
        max_length=24,
        choices=RuntimeOperationState,
        default=RuntimeOperationState.IDLE,
    )
    runtime_operation_trigger = models.CharField(
        max_length=16,
        choices=RuntimeOperationTrigger,
        null=True,
        blank=True,
    )
    runtime_operation_requested_at = models.DateTimeField(null=True, blank=True)
    runtime_operation_retry_count = models.PositiveSmallIntegerField(default=0)
    runtime_start_epoch = models.PositiveBigIntegerField(default=0)
    ready_generation = models.PositiveIntegerField(null=True, blank=True)
    ready_start_epoch = models.PositiveBigIntegerField(null=True, blank=True)
    ready_boot_id = models.UUIDField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    runtime_last_seen_at = models.DateTimeField(null=True, blank=True)
    speculative_keep_warm_until = models.DateTimeField(null=True, blank=True)
    last_speculative_start_at = models.DateTimeField(null=True, blank=True)
    # The operation ID is retained after a successful operation as a small
    # audit/idempotency anchor.  The remaining fields describe the operation
    # while a phase is in flight and are cleared by the lifecycle service.
    provisioning_id = models.UUIDField(null=True, blank=True)
    provisioning_kind = models.CharField(
        max_length=16,
        choices=WorkspaceProvisioningKind,
        null=True,
        blank=True,
    )
    provisioning_phase = models.CharField(
        max_length=32,
        choices=WorkspaceProvisioningPhase,
        default=WorkspaceProvisioningPhase.IDLE,
    )
    provisioning_source_generation = models.PositiveIntegerField(
        null=True,
        blank=True,
    )
    provisioning_target_generation = models.PositiveIntegerField(
        null=True,
        blank=True,
    )
    provisioning_previous_machine_ref = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )
    provisioning_machine_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )
    provisioning_claim_token = models.CharField(
        max_length=128,
        null=True,
        blank=True,
    )
    provisioning_claim_expires_at = models.DateTimeField(null=True, blank=True)
    activation_claim_token = models.CharField(
        max_length=128,
        null=True,
        blank=True,
    )
    activation_claim_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar = ["tenant_ref"]
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=(
                    (Q(fly_app_ref__isnull=True) | ~Q(fly_app_ref=""))
                    & (Q(volume_ref__isnull=True) | ~Q(volume_ref=""))
                    & (Q(machine_ref__isnull=True) | ~Q(machine_ref=""))
                ),
                name="runtime_workspace_fly_refs_nonempty",
            ),
            models.CheckConstraint(
                condition=Q(provisioning_phase__in=WorkspaceProvisioningPhase.values),
                name="runtime_workspace_provisioning_phase_valid",
            ),
            models.CheckConstraint(
                condition=Q(runtime_operation_state__in=RuntimeOperationState.values),
                name="runtime_workspace_operation_state_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(runtime_operation_trigger__isnull=True)
                    | Q(runtime_operation_trigger__in=RuntimeOperationTrigger.values)
                ),
                name="runtime_workspace_operation_trigger_valid",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(provisioning_phase=WorkspaceProvisioningPhase.IDLE)
                    | (
                        Q(machine_generation=0)
                        & Q(fly_app_ref__isnull=True)
                        & Q(volume_ref__isnull=True)
                        & Q(machine_ref__isnull=True)
                    )
                    | (
                        Q(machine_generation__gt=0)
                        & Q(fly_app_ref__isnull=False)
                        & Q(volume_ref__isnull=False)
                        & Q(machine_ref__isnull=False)
                    )
                ),
                name="runtime_workspace_idle_binding_contract",
            ),
        ]
        indexes: ClassVar = [
            models.Index(
                fields=["runtime_operation_state", "runtime_operation_requested_at"],
                name="rt_ws_power_requested_idx",
            ),
            models.Index(
                fields=["runtime_operation_state", "speculative_keep_warm_until"],
                name="rt_ws_power_idle_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.tenant_ref


class RuntimeIntent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="runtime_intents",
    )
    idempotency_key = models.UUIDField()
    intent_type = models.CharField(
        max_length=32,
        choices=RuntimeIntentType,
    )
    received_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    delete_after = models.DateTimeField()
    outcome = models.CharField(
        max_length=32,
        choices=RuntimeIntentOutcome,
    )
    coalesced_operation_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["workspace", "idempotency_key"],
                name="runtime_intent_workspace_key_unique",
            ),
            models.CheckConstraint(
                condition=Q(intent_type__in=RuntimeIntentType.values),
                name="runtime_intent_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(outcome__in=RuntimeIntentOutcome.values),
                name="runtime_intent_outcome_valid",
            ),
            models.CheckConstraint(
                condition=Q(received_at__lt=models.F("expires_at")),
                name="runtime_intent_expiry_after_received",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__lte=models.F("delete_after")),
                name="runtime_intent_cleanup_after_expiry",
            ),
        ]
        indexes: ClassVar = [
            models.Index(
                fields=["workspace", "received_at"],
                name="rt_intent_ws_received_idx",
            ),
            models.Index(fields=["delete_after"], name="rt_intent_delete_after_idx"),
        ]


class RuntimeCredential(models.Model):
    """A hashed, generation-scoped bearer capability for a runtime worker."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="runtime_credentials",
    )
    token_digest = models.CharField(max_length=64, unique=True)
    machine_generation = models.PositiveIntegerField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes: ClassVar = [
            models.Index(
                fields=["workspace", "machine_generation", "revoked_at"],
                name="rt_cred_ws_generation_idx",
            )
        ]

    def save(self, *args, **kwargs):
        if not re.fullmatch(r"[0-9a-f]{64}", self.token_digest):
            raise RuntimeValidationError(
                "token_digest must be a lowercase SHA-256 hex digest"
            )
        if self.machine_generation < 0:
            raise RuntimeValidationError("machine_generation cannot be negative")
        return super().save(*args, **kwargs)


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
    hermes_profile_key_version = models.PositiveSmallIntegerField(default=1)
    lifecycle_state = models.CharField(
        max_length=24,
        choices=RuntimeProfileLifecycleState,
        default=RuntimeProfileLifecycleState.PENDING,
    )
    lifecycle_epoch = models.PositiveIntegerField(default=0)
    seed_version = models.PositiveSmallIntegerField(default=1)
    # Desired state is deliberately limited to non-secret profile inputs.  In
    # particular, credential_refs contains opaque resolver references, never
    # resolved provider values.
    seed_payload = models.JSONField(default=dict, blank=True)
    seed_fingerprint = models.CharField(max_length=64, default="", blank=True)
    materialized_generation = models.PositiveIntegerField(default=0)
    materialization_operation_id = models.UUIDField(null=True, blank=True)
    materialization_request_digest = models.CharField(
        max_length=64,
        default="",
        blank=True,
    )
    materialization_receipt_id = models.UUIDField(null=True, blank=True)
    materialization_result_code = models.CharField(
        max_length=64,
        default="",
        blank=True,
    )
    cleanup_operation_id = models.UUIDField(null=True, blank=True)
    cleanup_context_digest = models.CharField(max_length=64, default="", blank=True)
    cleanup_request_digest = models.CharField(max_length=64, default="", blank=True)
    cleanup_expires_at = models.DateTimeField(null=True, blank=True)
    cleanup_receipt_id = models.UUIDField(null=True, blank=True)
    cleanup_result_code = models.CharField(max_length=64, default="", blank=True)
    cleanup_retry_after = models.DateTimeField(null=True, blank=True)
    cleanup_completed_at = models.DateTimeField(null=True, blank=True)
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
            models.CheckConstraint(
                condition=Q(lifecycle_state__in=RuntimeProfileLifecycleState.values),
                name="runtime_profile_lifecycle_state_valid",
            ),
            models.CheckConstraint(
                condition=Q(hermes_profile_key_version__in=[0, 1]),
                name="runtime_profile_key_version_valid",
            ),
            models.CheckConstraint(
                condition=Q(seed_version__gt=0),
                name="runtime_profile_seed_version_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(seed_fingerprint="")
                    | Q(seed_fingerprint__regex=r"^[0-9a-f]{64}$")
                ),
                name="runtime_profile_seed_fingerprint_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(cleanup_context_digest="")
                    | Q(cleanup_context_digest__regex=r"^[0-9a-f]{64}$")
                ),
                name="runtime_profile_cleanup_context_digest_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(cleanup_request_digest="")
                    | Q(cleanup_request_digest__regex=r"^[0-9a-f]{64}$")
                ),
                name="runtime_profile_cleanup_request_digest_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(materialization_request_digest="")
                    | Q(materialization_request_digest__regex=r"^[0-9a-f]{64}$")
                ),
                name="runtime_profile_materialization_digest_valid",
            ),
        ]
        ordering: ClassVar = ["workspace_id", "ally_ref"]

    def __str__(self) -> str:
        return self.hermes_profile_key

    def save(self, *args, **kwargs):
        validate_hermes_profile_key(self.hermes_profile_key)
        if self.hermes_profile_key_version not in (0, 1):
            raise RuntimeValidationError("unsupported Hermes profile key version")
        if self.seed_version <= 0:
            raise RuntimeValidationError("seed_version must be positive")
        if self.lifecycle_epoch < 0 or self.materialized_generation < 0:
            raise RuntimeValidationError(
                "profile lifecycle counters cannot be negative"
            )
        for field_name in (
            "seed_fingerprint",
            "cleanup_context_digest",
            "cleanup_request_digest",
            "materialization_request_digest",
        ):
            value = getattr(self, field_name)
            if value and not re.fullmatch(r"[0-9a-f]{64}", value):
                raise RuntimeValidationError(
                    f"{field_name} must be a SHA-256 hex digest"
                )
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
    hermes_session_id = models.CharField(max_length=255, null=True, blank=True)
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
    command_id = models.UUIDField(null=True, blank=True, unique=True)
    command_fingerprint = models.CharField(max_length=100, default="", blank=True)
    cloud_workspace_id = models.UUIDField(null=True, blank=True)
    cloud_ally_id = models.UUIDField(null=True, blank=True)
    cloud_conversation_id = models.UUIDField(null=True, blank=True)
    cloud_message_id = models.UUIDField(null=True, blank=True)
    cloud_binding_id = models.UUIDField(null=True, blank=True)
    conversation_turn_ordinal = models.PositiveIntegerField(null=True, blank=True)
    source_kind = models.CharField(max_length=64, default="", blank=True)
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
            models.CheckConstraint(
                condition=(
                    Q(command_fingerprint="")
                    | Q(
                        command_fingerprint__regex=r"^canonical-json-sha256:v1:[0-9a-f]{64}$"
                    )
                ),
                name="runtime_execution_command_fingerprint_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(command_id__isnull=True)
                    | (
                        Q(cloud_workspace_id__isnull=False)
                        & Q(cloud_ally_id__isnull=False)
                        & Q(cloud_conversation_id__isnull=False)
                        & Q(cloud_message_id__isnull=False)
                        & Q(cloud_binding_id__isnull=False)
                        & Q(conversation_turn_ordinal__gt=0)
                        & ~Q(command_fingerprint="")
                    )
                ),
                name="runtime_execution_command_contract",
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
    claim_id = models.UUIDField(null=True, blank=True, unique=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    terminal_request_digest = models.CharField(max_length=64, null=True, blank=True)
    terminal_lease_digest = models.CharField(max_length=64, null=True, blank=True)
    terminal_receipt = models.JSONField(null=True, blank=True)
    terminal_receipt_id = models.UUIDField(null=True, blank=True)
    stopped_request_digest = models.CharField(max_length=64, null=True, blank=True)
    stopped_lease_digest = models.CharField(max_length=64, null=True, blank=True)
    stopped_receipt = models.JSONField(null=True, blank=True)
    session_request_digest = models.CharField(max_length=64, null=True, blank=True)
    session_lease_digest = models.CharField(max_length=64, null=True, blank=True)
    session_receipt = models.JSONField(null=True, blank=True)
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
    claim_id = models.UUIDField(null=True, blank=True)
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
    stream_id = models.CharField(max_length=255, default="")
    sequence = models.PositiveIntegerField()
    event_type = models.CharField(max_length=64)
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
                condition=Q(sequence__gt=0) & Q(sequence__lte=MAX_TERMINAL_SEQUENCE),
                name="runtime_event_sequence_positive",
            ),
        ]


class ExecutionEventDelivery(models.Model):
    """Bounded wire envelope erased after delivery reaches a terminal state."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.OneToOneField(
        ExecutionEvent,
        on_delete=models.CASCADE,
        related_name="delivery",
    )
    envelope_bytes = models.BinaryField(max_length=64 * 1024)
    byte_length = models.PositiveIntegerField()
    fingerprint = models.CharField(max_length=100)
    state = models.CharField(
        max_length=16,
        choices=EventDeliveryState,
        default=EventDeliveryState.PENDING,
    )
    # Repair cycles fence callbacks from an older exhausted delivery while
    # reusing the existing PENDING/DELIVERING state machine.
    repair_cycle = models.PositiveIntegerField(default=0)
    delivery_attempts = models.PositiveSmallIntegerField(default=0)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField()
    safe_error_code = models.CharField(max_length=64, default="", blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["event", "fingerprint"],
                name="runtime_delivery_event_fingerprint_unique",
            ),
            models.CheckConstraint(
                condition=Q(state__in=EventDeliveryState.values),
                name="runtime_delivery_state_valid",
            ),
            models.CheckConstraint(
                condition=Q(delivery_attempts__gte=0) & Q(delivery_attempts__lte=8),
                name="runtime_delivery_attempts_bounded",
            ),
            models.CheckConstraint(
                condition=Q(repair_cycle__gte=0),
                name="runtime_delivery_repair_cycle_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(
                    state__in=[
                        EventDeliveryState.DELIVERED,
                        EventDeliveryState.EXHAUSTED,
                    ],
                    byte_length=0,
                )
                | (Q(byte_length__gt=0) & Q(byte_length__lte=64 * 1024)),
                name="runtime_delivery_bytes_bounded",
            ),
            models.CheckConstraint(
                condition=(
                    Q(fingerprint__regex=r"^canonical-json-sha256:v1:[0-9a-f]{64}$")
                ),
                name="runtime_delivery_fingerprint_valid",
            ),
        ]
        indexes: ClassVar = [
            models.Index(
                fields=["state", "next_attempt_at", "lease_expires_at"],
                name="rt_delivery_due_idx",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = (
                type(self)
                .objects.only(
                    "event_id", "envelope_bytes", "byte_length", "fingerprint",
                    "state", "repair_cycle"
                )
                .get(pk=self.pk)
            )
            identity_changed = (
                previous.event_id != self.event_id
                or previous.fingerprint != self.fingerprint
            )
            payload_changed = (
                previous.envelope_bytes != self.envelope_bytes
                or previous.byte_length != self.byte_length
            )
            terminal_erasure = (
                self.state
                in {EventDeliveryState.DELIVERED, EventDeliveryState.EXHAUSTED}
                and self.envelope_bytes == b""
                and self.byte_length == 0
            )
            repair_rehydration = (
                previous.state == EventDeliveryState.EXHAUSTED
                and self.state == EventDeliveryState.PENDING
                and previous.byte_length == 0
                and self.byte_length > 0
                and self.repair_cycle > previous.repair_cycle
            )
            if identity_changed or payload_changed and not (
                terminal_erasure or repair_rehydration
            ):
                raise RuntimeConflictError("event delivery envelope is immutable")
        if not isinstance(self.envelope_bytes, bytes):
            raise RuntimeValidationError("delivery envelope must be UTF-8 bytes")
        terminal_erasure = (
            self.state in {EventDeliveryState.DELIVERED, EventDeliveryState.EXHAUSTED}
            and self.envelope_bytes == b""
        )
        if not terminal_erasure and not 0 < len(self.envelope_bytes) <= 64 * 1024:
            raise RuntimeValidationError("delivery envelope is too large")
        if self.byte_length != len(self.envelope_bytes):
            raise RuntimeValidationError("delivery byte length is invalid")
        if not re.fullmatch(r"canonical-json-sha256:v1:[0-9a-f]{64}", self.fingerprint):
            raise RuntimeValidationError("delivery fingerprint is invalid")
        if not 0 <= self.delivery_attempts <= 8:
            raise RuntimeValidationError("delivery attempts exceed the bounded budget")
        if self.repair_cycle < 0:
            raise RuntimeValidationError("delivery repair cycle is invalid")
        if self.safe_error_code and not re.fullmatch(
            r"[a-z][a-z0-9_-]{0,63}", self.safe_error_code
        ):
            raise RuntimeValidationError("delivery error code is invalid")
        return super().save(*args, **kwargs)
