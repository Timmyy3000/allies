"""Cloud-owned saved routine intent and scheduling state."""

from __future__ import annotations

import uuid
from datetime import UTC

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from allies.models import Ally, AllyBinding

from .services.schedule import ScheduleValidationError, validate_schedule

# Django model metaclasses intentionally consume mutable Meta collections.
# ruff: noqa: RUF012

ROUTINE_TITLE_MAX_LENGTH = 120
ROUTINE_PROMPT_MAX_BYTES = 16 * 1024
ROUTINE_DISPATCH_MAX_ATTEMPTS = 5
ROUTINE_APPROVAL_MAX_ATTEMPTS = 5
ROUTINE_APPROVAL_EXPIRY_SECONDS = 24 * 60 * 60


class RoutineState(models.TextChoices):
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    DELETED = "deleted", "Deleted"
    EXHAUSTED = "exhausted", "Exhausted"


class RoutineDeletionConfirmationState(models.TextChoices):
    UNCONSUMED = "unconsumed", "Unconsumed"
    CONSUMED = "consumed", "Consumed"


IMMUTABLE_ANCESTRY_FIELDS = (
    "workspace_id",
    "owner_id",
    "ally_id",
    "binding_id",
    "main_conversation_id",
)


class Routine(models.Model):
    """An owner-scoped saved intent whose row remains after deletion."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.PROTECT,
        related_name="routines",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="routines",
    )
    ally = models.ForeignKey(
        Ally,
        on_delete=models.PROTECT,
        related_name="routines",
    )
    binding = models.ForeignKey(
        AllyBinding,
        on_delete=models.PROTECT,
        related_name="routines",
    )
    main_conversation_id = models.UUIDField()
    title = models.CharField(max_length=ROUTINE_TITLE_MAX_LENGTH)
    execution_prompt = models.TextField(max_length=ROUTINE_PROMPT_MAX_BYTES)
    schedule = models.JSONField()
    revision = models.PositiveIntegerField(default=1)
    schedule_generation = models.PositiveIntegerField(default=1)
    state = models.CharField(
        max_length=16,
        choices=RoutineState.choices,
        default=RoutineState.ACTIVE,
    )
    next_run_at = models.DateTimeField(null=True, blank=True)
    resume_boundary = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(
                fields=("workspace", "owner", "state", "created_at"),
                name="routine_owner_state_idx",
            ),
            models.Index(
                fields=("state", "next_run_at"),
                name="routine_state_next_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(revision__gt=0),
                name="routine_revision_positive_chk",
            ),
            models.CheckConstraint(
                condition=Q(schedule_generation__gt=0),
                name="routine_generation_positive_chk",
            ),
            models.CheckConstraint(
                condition=(
                    Q(state=RoutineState.DELETED, deleted_at__isnull=False)
                    | (~Q(state=RoutineState.DELETED) & Q(deleted_at__isnull=True))
                ),
                name="routine_deleted_state_coherent_chk",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)

    @property
    def schedule_kind(self) -> str:
        return validate_schedule(self.schedule).kind.value

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if not isinstance(self.title, str) or not self.title.strip():
            errors["title"] = "title is required"
        elif len(self.title) > ROUTINE_TITLE_MAX_LENGTH:
            errors["title"] = "title is too long"

        if (
            not isinstance(self.execution_prompt, str)
            or not self.execution_prompt.strip()
        ):
            errors["execution_prompt"] = "execution prompt is required"
        elif len(self.execution_prompt.encode("utf-8")) > ROUTINE_PROMPT_MAX_BYTES:
            errors["execution_prompt"] = "execution prompt exceeds the byte limit"

        try:
            validate_schedule(self.schedule)
        except ScheduleValidationError as exc:
            errors["schedule"] = str(exc)

        if (
            self.workspace_id
            and self.ally_id
            and not Ally.objects.filter(
                pk=self.ally_id, workspace_id=self.workspace_id
            ).exists()
        ):
            errors["ally"] = "ally must belong to the routine workspace"
        if (
            self.ally_id
            and self.binding_id
            and not AllyBinding.objects.filter(
                pk=self.binding_id, ally_id=self.ally_id
            ).exists()
        ):
            errors["binding"] = "binding must belong to the routine ally"
        if self.state == RoutineState.DELETED and self.deleted_at is None:
            errors["deleted_at"] = "deleted routines require deleted_at"
        if self.state != RoutineState.DELETED and self.deleted_at is not None:
            errors["state"] = "only deleted routines may have deleted_at"

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = (
                type(self)
                .objects.filter(pk=self.pk)
                .values(*IMMUTABLE_ANCESTRY_FIELDS)
                .first()
            )
            if previous is not None:
                changed = [
                    field
                    for field in IMMUTABLE_ANCESTRY_FIELDS
                    if previous[field] != getattr(self, field)
                ]
                if changed:
                    raise ValidationError(
                        {
                            field.removesuffix("_id"): "owner ancestry is immutable"
                            for field in changed
                        }
                    )
        return super().save(*args, **kwargs)


class RoutineDeletionConfirmation(models.Model):
    """A one-shot, Cloud-only deletion capability bound to one routine revision."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference_digest = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
    )
    routine = models.ForeignKey(
        Routine,
        on_delete=models.PROTECT,
        related_name="deletion_confirmations",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.PROTECT,
        related_name="routine_deletion_confirmations",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="routine_deletion_confirmations",
    )
    ally = models.ForeignKey(
        Ally,
        on_delete=models.PROTECT,
        related_name="routine_deletion_confirmations",
    )
    binding = models.ForeignKey(
        AllyBinding,
        on_delete=models.PROTECT,
        related_name="routine_deletion_confirmations",
    )
    main_conversation_id = models.UUIDField()
    expected_revision = models.PositiveIntegerField()
    state = models.CharField(
        max_length=16,
        choices=RoutineDeletionConfirmationState.choices,
        default=RoutineDeletionConfirmationState.UNCONSUMED,
    )
    issued_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("routine", "state"),
                name="routine_delete_confirm_idx",
            ),
            models.Index(
                fields=("workspace", "owner", "state"),
                name="routine_confirm_scope_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        state=RoutineDeletionConfirmationState.CONSUMED,
                        consumed_at__isnull=False,
                    )
                    | (
                        ~Q(state=RoutineDeletionConfirmationState.CONSUMED)
                        & Q(consumed_at__isnull=True)
                    )
                ),
                name="routine_confirm_state_coherent_chk",
            ),
            models.CheckConstraint(
                condition=Q(expected_revision__gt=0),
                name="routine_confirm_revision_positive_chk",
            ),
        ]


class RoutineManagementReceipt(models.Model):
    """Durable success receipt for a Cloud-owned routine mutation."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    confirmation = models.OneToOneField(
        RoutineDeletionConfirmation,
        on_delete=models.PROTECT,
        related_name="management_receipt",
        null=True,
        blank=True,
    )
    command_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    idempotency_key = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    routine = models.ForeignKey(
        Routine,
        on_delete=models.PROTECT,
        related_name="management_receipts",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.PROTECT,
        related_name="routine_management_receipts",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="routine_management_receipts",
    )
    ally = models.ForeignKey(
        Ally,
        on_delete=models.PROTECT,
        related_name="routine_management_receipts",
    )
    binding = models.ForeignKey(
        AllyBinding,
        on_delete=models.PROTECT,
        related_name="routine_management_receipts",
    )
    operation = models.CharField(max_length=16)
    outcome = models.CharField(max_length=16, default="saved")
    result_code = models.CharField(max_length=64)
    revision = models.PositiveIntegerField()
    schedule_generation = models.PositiveIntegerField(default=1)
    schedule_state = models.CharField(max_length=16)
    next_run_at = models.DateTimeField(null=True, blank=True)
    resume_effective_at = models.DateTimeField(null=True, blank=True)
    issued_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("routine", "created_at"),
                name="routine_receipt_history_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(revision__gt=0),
                name="routine_receipt_revision_positive_chk",
            ),
            models.CheckConstraint(
                condition=Q(schedule_generation__gt=0),
                name="routine_receipt_generation_positive_chk",
            ),
        ]


class RoutineOccurrenceDisposition(models.TextChoices):
    ADMITTED = "admitted", "Admitted"
    REPLAY = "replay", "Replay"
    SKIPPED_ACTIVE = "skipped_active", "Skipped active"
    DELAYED = "delayed", "Delayed"
    RECOVERED = "recovered", "Recovered"
    CANCELLED = "cancelled", "Cancelled"


class RoutineRunOutcome(models.TextChoices):
    QUEUED = "queued", "Queued"
    WORKING = "working", "Working"
    APPROVAL_WAITING = "approval_waiting", "Approval waiting"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"


class RoutineDispatchState(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In progress"
    ACCEPTED = "accepted", "Accepted"
    RECONCILIATION_NEEDED = "reconciliation_needed", "Reconciliation needed"
    FAILED = "failed", "Failed"


class RoutineApprovalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DECISION_RECORDED = "decision_recorded", "Decision recorded"
    AUTHORIZING = "authorizing", "Authorizing"
    REJECTED = "rejected", "Rejected"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"
    OUTCOME_UNKNOWN = "outcome_unknown", "Outcome unknown"


class RoutineApprovalDeliveryState(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In progress"
    ACCEPTED = "accepted", "Accepted"
    RECONCILIATION_NEEDED = "reconciliation_needed", "Reconciliation needed"
    FAILED = "failed", "Failed"


class RoutineApprovalCommandKind(models.TextChoices):
    DECISION = "routine.approval_decision", "Approval decision"
    CANCEL_WAIT = "routine.cancel_wait", "Cancel wait"


ROUTINE_ACTIVE_RUN_OUTCOMES = (
    RoutineRunOutcome.QUEUED,
    RoutineRunOutcome.WORKING,
    RoutineRunOutcome.APPROVAL_WAITING,
)


class RoutineOccurrence(models.Model):
    """One durable scheduled opportunity, including an intentional skip."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    routine = models.ForeignKey(
        Routine,
        on_delete=models.PROTECT,
        related_name="occurrences",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.PROTECT,
        related_name="routine_occurrences",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="routine_occurrences",
    )
    ally = models.ForeignKey(
        Ally,
        on_delete=models.PROTECT,
        related_name="routine_occurrences",
    )
    binding = models.ForeignKey(
        AllyBinding,
        on_delete=models.PROTECT,
        related_name="routine_occurrences",
    )
    scheduled_at = models.DateTimeField()
    observed_revision = models.PositiveIntegerField()
    observed_schedule_generation = models.PositiveIntegerField()
    disposition = models.CharField(
        max_length=24,
        choices=RoutineOccurrenceDisposition.choices,
    )
    delayed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("scheduled_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("routine", "scheduled_at"),
                name="routine_occurrence_schedule_uniq",
            ),
            models.CheckConstraint(
                condition=Q(observed_revision__gt=0),
                name="routine_occ_revision_positive_chk",
            ),
            models.CheckConstraint(
                condition=Q(observed_schedule_generation__gt=0),
                name="routine_occ_generation_positive_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=("routine", "scheduled_at"),
                name="routine_occurrence_due_idx",
            ),
            models.Index(
                fields=("workspace", "owner", "created_at"),
                name="routine_occurrence_scope_idx",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            previous = (
                type(self)
                .objects.filter(pk=self.pk)
                .values(
                    "routine_id",
                    "workspace_id",
                    "owner_id",
                    "ally_id",
                    "binding_id",
                    "scheduled_at",
                    "observed_revision",
                    "observed_schedule_generation",
                    "disposition",
                    "delayed",
                )
                .first()
            )
            if previous is not None:
                changed = [
                    field
                    for field in previous
                    if previous[field] != getattr(self, field)
                ]
                if changed:
                    raise ValidationError(
                        {field: "occurrence identity is immutable" for field in changed}
                    )
        return super().save(*args, **kwargs)

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.routine_id:
            routine = self.routine
            expected = {
                "workspace_id": routine.workspace_id,
                "owner_id": routine.owner_id,
                "ally_id": routine.ally_id,
                "binding_id": routine.binding_id,
            }
            for field, value in expected.items():
                if getattr(self, field) != value:
                    errors[field.removesuffix("_id")] = "routine ancestry is immutable"
        if self.scheduled_at.tzinfo is None:
            errors["scheduled_at"] = "scheduled_at must be timezone-aware"
        if self.scheduled_at.tzinfo is not None:
            self.scheduled_at = self.scheduled_at.astimezone(UTC).replace(microsecond=0)
        if errors:
            raise ValidationError(errors)


class RoutineRunSnapshot(models.Model):
    """Immutable Cloud snapshot used to build one routine dispatch."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    occurrence = models.OneToOneField(
        RoutineOccurrence,
        on_delete=models.PROTECT,
        related_name="run_snapshot",
    )
    routine = models.ForeignKey(
        Routine,
        on_delete=models.PROTECT,
        related_name="run_snapshots",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.PROTECT,
        related_name="routine_run_snapshots",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="routine_run_snapshots",
    )
    ally = models.ForeignKey(
        Ally,
        on_delete=models.PROTECT,
        related_name="routine_run_snapshots",
    )
    binding = models.ForeignKey(
        AllyBinding,
        on_delete=models.PROTECT,
        related_name="routine_run_snapshots",
    )
    routine_revision = models.PositiveIntegerField()
    schedule_generation = models.PositiveIntegerField()
    title_snapshot = models.CharField(max_length=ROUTINE_TITLE_MAX_LENGTH)
    execution_prompt = models.TextField(max_length=ROUTINE_PROMPT_MAX_BYTES)
    schedule_snapshot = models.JSONField()
    timezone = models.CharField(max_length=64)
    scheduled_at = models.DateTimeField()
    occurrence_disposition = models.CharField(
        max_length=24,
        choices=RoutineOccurrenceDisposition.choices,
    )
    delayed = models.BooleanField(default=False)
    main_conversation_id = models.UUIDField()
    run_conversation_id = models.UUIDField(unique=True)
    outcome = models.CharField(
        max_length=24,
        choices=RoutineRunOutcome.choices,
        default=RoutineRunOutcome.QUEUED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("routine",),
                condition=Q(outcome__in=ROUTINE_ACTIVE_RUN_OUTCOMES),
                name="routine_active_run_uniq",
            ),
            models.CheckConstraint(
                condition=Q(routine_revision__gt=0),
                name="routine_run_revision_positive_chk",
            ),
            models.CheckConstraint(
                condition=Q(schedule_generation__gt=0),
                name="routine_run_generation_positive_chk",
            ),
            models.CheckConstraint(
                condition=~Q(run_conversation_id=F("main_conversation_id")),
                name="routine_run_conversation_distinct_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=("routine", "outcome", "created_at"),
                name="routine_run_active_idx",
            ),
            models.Index(
                fields=("workspace", "owner", "created_at"),
                name="routine_run_scope_idx",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)

    @property
    def run_id(self):
        return self.id

    @property
    def execution_prompt_snapshot(self) -> str:
        return self.execution_prompt

    def save(self, *args, **kwargs):
        immutable_fields = (
            "occurrence_id",
            "routine_id",
            "workspace_id",
            "owner_id",
            "ally_id",
            "binding_id",
            "routine_revision",
            "schedule_generation",
            "title_snapshot",
            "execution_prompt",
            "schedule_snapshot",
            "timezone",
            "scheduled_at",
            "occurrence_disposition",
            "delayed",
            "main_conversation_id",
            "run_conversation_id",
        )
        if not self._state.adding:
            previous = (
                type(self).objects.filter(pk=self.pk).values(*immutable_fields).first()
            )
            if previous is not None:
                changed = [
                    field
                    for field in immutable_fields
                    if previous[field] != getattr(self, field)
                ]
                if changed:
                    raise ValidationError(
                        {field: "run snapshot is immutable" for field in changed}
                    )
        return super().save(*args, **kwargs)

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.routine_id:
            routine = self.routine
            expected = {
                "workspace_id": routine.workspace_id,
                "owner_id": routine.owner_id,
                "ally_id": routine.ally_id,
                "binding_id": routine.binding_id,
            }
            for field, value in expected.items():
                if getattr(self, field) != value:
                    errors[field.removesuffix("_id")] = "routine ancestry is immutable"
        if self.occurrence_id:
            occurrence = self.occurrence
            if occurrence.routine_id != self.routine_id:
                errors["occurrence"] = "occurrence routine is inconsistent"
        if self.run_conversation_id == self.main_conversation_id:
            errors["run_conversation_id"] = "run conversation must be fresh"
        if len(self.execution_prompt.encode("utf-8")) > ROUTINE_PROMPT_MAX_BYTES:
            errors["execution_prompt"] = "execution prompt exceeds the byte limit"
        try:
            validate_schedule(self.schedule_snapshot)
        except ScheduleValidationError as exc:
            errors["schedule_snapshot"] = str(exc)
        if self.scheduled_at.tzinfo is None:
            errors["scheduled_at"] = "scheduled_at must be timezone-aware"
        if errors:
            raise ValidationError(errors)


class RoutineDispatchOutbox(models.Model):
    """One immutable routine command with bounded Cloud delivery state."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    routine = models.ForeignKey(
        Routine,
        on_delete=models.PROTECT,
        related_name="dispatch_outboxes",
    )
    occurrence = models.OneToOneField(
        RoutineOccurrence,
        on_delete=models.PROTECT,
        related_name="dispatch_outbox",
    )
    run = models.OneToOneField(
        RoutineRunSnapshot,
        on_delete=models.PROTECT,
        related_name="dispatch_outbox",
    )
    command_id = models.UUIDField(unique=True)
    idempotency_key = models.UUIDField(unique=True)
    command_bytes = models.BinaryField(default=bytes, editable=False)
    command_byte_length = models.PositiveIntegerField(default=0, editable=False)
    command_sha256 = models.CharField(
        max_length=64,
        blank=True,
        default="",
        editable=False,
    )
    command_fingerprint = models.CharField(
        max_length=90,
        blank=True,
        default="",
        editable=False,
    )
    execution_id = models.UUIDField(null=True, blank=True, editable=False)
    attempt_id = models.UUIDField(null=True, blank=True, editable=False)
    generation = models.PositiveIntegerField(null=True, blank=True, editable=False)
    status = models.CharField(
        max_length=32,
        choices=RoutineDispatchState.choices,
        default=RoutineDispatchState.PENDING,
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    safe_error_code = models.CharField(max_length=64, blank=True, default="")
    receipt_digest = models.CharField(
        max_length=64,
        blank=True,
        default="",
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(
                fields=("status", "next_attempt_at", "lease_expires_at"),
                name="routine_dispatch_due_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(command_byte_length__gte=0),
                name="routine_dispatch_length_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    Q(command_sha256="") | Q(command_sha256__regex=r"^[0-9a-fA-F]{64}$")
                ),
                name="routine_dispatch_command_sha_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(command_fingerprint="")
                    | Q(
                        command_fingerprint__regex=(
                            r"^canonical-json-sha256:v1:[0-9a-fA-F]{64}$"
                        )
                    )
                ),
                name="routine_dispatch_fingerprint_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(receipt_digest="") | Q(receipt_digest__regex=r"^[0-9a-fA-F]{64}$")
                ),
                name="routine_dispatch_receipt_digest_valid",
            ),
            models.CheckConstraint(
                condition=Q(attempt_count__gte=0)
                & Q(attempt_count__lte=ROUTINE_DISPATCH_MAX_ATTEMPTS),
                name="routine_dispatch_attempt_bounded",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(status=RoutineDispatchState.ACCEPTED)
                    | (
                        Q(execution_id__isnull=False)
                        & Q(attempt_id__isnull=False)
                        & Q(generation__isnull=False)
                    )
                ),
                name="routine_dispatch_accept_identity_chk",
            ),
        ]

    def __str__(self) -> str:
        return f"routine-dispatch:{self.id}"

    def save(self, *args, **kwargs):
        immutable_fields = (
            "routine_id",
            "occurrence_id",
            "run_id",
            "command_id",
            "idempotency_key",
            "command_bytes",
            "command_byte_length",
            "command_sha256",
            "command_fingerprint",
            "execution_id",
            "attempt_id",
            "generation",
        )
        if not self._state.adding:
            previous = (
                type(self).objects.filter(pk=self.pk).values(*immutable_fields).first()
            )
            if previous is not None:
                changed = [
                    field
                    for field in immutable_fields
                    if previous[field] != getattr(self, field)
                    and not (
                        field in {"execution_id", "attempt_id", "generation"}
                        and previous[field] is None
                    )
                ]
                if changed:
                    raise ValidationError(
                        {field: "dispatch command is immutable" for field in changed}
                    )
        return super().save(*args, **kwargs)

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if (
            self.run_id
            and self.occurrence_id
            and self.run.occurrence_id != self.occurrence_id
        ):
            errors["run"] = "dispatch run does not match occurrence"
        if self.routine_id:
            if self.occurrence.routine_id != self.routine_id:
                errors["routine"] = "dispatch routine does not match occurrence"
            if self.run.routine_id != self.routine_id:
                errors["routine"] = "dispatch routine does not match run"
        if self.command_bytes and self.command_byte_length != len(self.command_bytes):
            errors["command_byte_length"] = "command byte length is inconsistent"
        if self.command_byte_length > 64 * 1024:
            errors["command_bytes"] = "command is too large"
        if self.status == RoutineDispatchState.ACCEPTED and (
            self.execution_id is None
            or self.attempt_id is None
            or self.generation is None
        ):
            errors["status"] = "accepted dispatch requires Foundry identity"
        if errors:
            raise ValidationError(errors)


class RoutineApprovalProjection(models.Model):
    """Cloud's immutable projection of one Foundry approval request."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    routine = models.ForeignKey(
        Routine,
        on_delete=models.PROTECT,
        related_name="approval_projections",
    )
    occurrence = models.ForeignKey(
        RoutineOccurrence,
        on_delete=models.PROTECT,
        related_name="approval_projections",
    )
    run = models.ForeignKey(
        RoutineRunSnapshot,
        on_delete=models.PROTECT,
        related_name="approval_projections",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.PROTECT,
        related_name="routine_approval_projections",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="routine_approval_projections",
    )
    ally = models.ForeignKey(
        Ally,
        on_delete=models.PROTECT,
        related_name="routine_approval_projections",
    )
    binding = models.ForeignKey(
        AllyBinding,
        on_delete=models.PROTECT,
        related_name="routine_approval_projections",
    )
    approval_request_id = models.UUIDField(unique=True, editable=False)
    action_attempt_id = models.UUIDField(unique=True, editable=False)
    execution_id = models.UUIDField(editable=False)
    attempt_id = models.UUIDField(editable=False)
    generation = models.PositiveIntegerField(editable=False)
    event_id = models.UUIDField(unique=True, editable=False)
    event_sequence = models.PositiveIntegerField(editable=False)
    event_fingerprint = models.CharField(max_length=90, editable=False)
    action_digest = models.CharField(max_length=64, editable=False)
    provider_idempotency_key = models.CharField(max_length=255, editable=False)
    created_at = models.DateTimeField(editable=False)
    expires_at = models.DateTimeField(editable=False)
    status = models.CharField(
        max_length=24,
        choices=RoutineApprovalStatus.choices,
        default=RoutineApprovalStatus.PENDING,
    )
    decision = models.CharField(max_length=6, blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)
    deciding_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="routine_approval_decisions",
        null=True,
        blank=True,
    )
    decision_command_id = models.UUIDField(
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )
    decision_idempotency_key = models.UUIDField(
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )
    decision_fingerprint = models.CharField(
        max_length=90,
        blank=True,
        default="",
        editable=False,
    )
    permission_consumed = models.BooleanField(null=True, blank=True)
    action_attempt_state = models.CharField(max_length=32, blank=True, default="")
    last_result_code = models.CharField(max_length=64, blank=True, default="")
    local_expired_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_projection_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(
                fields=("workspace", "owner", "status", "created_at"),
                name="routine_appr_scope_status_idx",
            ),
            models.Index(
                fields=("status", "expires_at", "id"),
                name="routine_appr_expiry_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("attempt_id", "event_sequence"),
                name="routine_appr_attempt_seq_uniq",
            ),
            models.CheckConstraint(
                condition=Q(event_sequence__gt=0),
                name="routine_appr_event_sequence_positive_chk",
            ),
            models.CheckConstraint(
                condition=Q(generation__gte=0),
                name="routine_appr_generation_nonnegative_chk",
            ),
            models.CheckConstraint(
                condition=Q(action_digest__regex=r"^[0-9a-f]{64}$"),
                name="routine_appr_action_digest_valid_chk",
            ),
            models.CheckConstraint(
                condition=Q(
                    event_fingerprint__regex=r"^canonical-json-sha256:v1:[0-9a-f]{64}$"
                ),
                name="routine_appr_event_fingerprint_valid_chk",
            ),
            models.CheckConstraint(
                condition=(Q(decision="") | Q(decision__in=("approve", "reject"))),
                name="routine_appr_decision_valid_chk",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("created_at")),
                name="routine_appr_expiry_after_created_chk",
            ),
        ]

    def __str__(self) -> str:
        return f"routine-approval:{self.id}"

    def save(self, *args, **kwargs):
        immutable_fields = (
            "routine_id",
            "occurrence_id",
            "run_id",
            "workspace_id",
            "owner_id",
            "ally_id",
            "binding_id",
            "approval_request_id",
            "action_attempt_id",
            "execution_id",
            "attempt_id",
            "generation",
            "event_id",
            "event_sequence",
            "event_fingerprint",
            "action_digest",
            "provider_idempotency_key",
            "created_at",
            "expires_at",
        )
        decision_fields = (
            "decision",
            "decided_at",
            "deciding_user_id",
            "decision_command_id",
            "decision_idempotency_key",
            "decision_fingerprint",
        )
        if not self._state.adding:
            previous = (
                type(self)
                .objects.filter(pk=self.pk)
                .values(*immutable_fields, *decision_fields)
                .first()
            )
            if previous is not None:
                changed = [
                    field
                    for field in immutable_fields
                    if previous[field] != getattr(self, field)
                ]
                changed.extend(
                    field
                    for field in decision_fields
                    if previous[field] is not None
                    and previous[field] != getattr(self, field)
                    and not (
                        field in {"decision", "decision_fingerprint"}
                        and previous[field] == ""
                    )
                )
                if changed:
                    raise ValidationError(
                        {
                            field: "routine approval identity is immutable"
                            for field in changed
                        }
                    )
        return super().save(*args, **kwargs)

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.routine_id:
            routine = self.routine
            expected = {
                "workspace_id": routine.workspace_id,
                "owner_id": routine.owner_id,
                "ally_id": routine.ally_id,
                "binding_id": routine.binding_id,
            }
            for field, value in expected.items():
                if getattr(self, field) != value:
                    errors[field.removesuffix("_id")] = "routine ancestry is immutable"
        if (
            self.occurrence_id
            and self.routine_id
            and self.occurrence.routine_id != self.routine_id
        ):
            errors["occurrence"] = "approval occurrence does not match routine"
        if (
            self.run_id
            and self.occurrence_id
            and self.routine_id
            and (
                self.run.occurrence_id != self.occurrence_id
                or self.run.routine_id != self.routine_id
            )
        ):
            errors["run"] = "approval run does not match occurrence"
        if self.created_at and self.created_at.tzinfo is None:
            errors["created_at"] = "created_at must be timezone-aware"
        if self.expires_at and self.expires_at.tzinfo is None:
            errors["expires_at"] = "expires_at must be timezone-aware"
        if (
            self.created_at
            and self.expires_at
            and self.created_at.tzinfo is not None
            and self.expires_at.tzinfo is not None
            and (self.expires_at - self.created_at).total_seconds()
            != ROUTINE_APPROVAL_EXPIRY_SECONDS
        ):
            errors["expires_at"] = "approval expiry must be exactly 24 hours"
        if errors:
            raise ValidationError(errors)


class RoutineApprovalCommand(models.Model):
    """One immutable approval/cancel command with a recoverable lease."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    approval = models.ForeignKey(
        RoutineApprovalProjection,
        on_delete=models.PROTECT,
        related_name="commands",
    )
    kind = models.CharField(max_length=32, choices=RoutineApprovalCommandKind.choices)
    command_id = models.UUIDField(unique=True, editable=False)
    idempotency_key = models.UUIDField(unique=True, editable=False)
    command_bytes = models.BinaryField(default=bytes, editable=False)
    command_byte_length = models.PositiveIntegerField(default=0, editable=False)
    command_sha256 = models.CharField(
        max_length=64,
        blank=True,
        default="",
        editable=False,
    )
    command_fingerprint = models.CharField(
        max_length=90,
        blank=True,
        default="",
        editable=False,
    )
    replacing_occurrence = models.ForeignKey(
        RoutineOccurrence,
        on_delete=models.PROTECT,
        related_name="routine_approval_cancel_commands",
        null=True,
        blank=True,
    )
    reason = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=32,
        choices=RoutineApprovalDeliveryState.choices,
        default=RoutineApprovalDeliveryState.PENDING,
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    safe_error_code = models.CharField(max_length=64, blank=True, default="")
    receipt_bytes = models.BinaryField(default=bytes, editable=False)
    receipt_digest = models.CharField(
        max_length=64,
        blank=True,
        default="",
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("approval", "kind"),
                name="routine_appr_command_kind_uniq",
            ),
            models.CheckConstraint(
                condition=Q(command_byte_length__gte=0),
                name="routine_appr_cmd_length_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(command_sha256__regex=r"^[0-9a-f]{64}$"),
                name="routine_appr_cmd_sha_valid",
            ),
            models.CheckConstraint(
                condition=Q(
                    command_fingerprint__regex=r"^canonical-json-sha256:v1:[0-9a-f]{64}$"
                ),
                name="routine_appr_cmd_fingerprint_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(receipt_digest="") | Q(receipt_digest__regex=r"^[0-9a-f]{64}$")
                ),
                name="routine_appr_receipt_digest_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(attempt_count__gte=0)
                    & Q(attempt_count__lte=ROUTINE_APPROVAL_MAX_ATTEMPTS)
                ),
                name="routine_appr_cmd_attempt_bounded",
            ),
        ]
        indexes = [
            models.Index(
                fields=("status", "next_attempt_at", "lease_expires_at"),
                name="routine_appr_cmd_due_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"routine-approval-command:{self.id}"

    def save(self, *args, **kwargs):
        immutable_fields = (
            "approval_id",
            "kind",
            "command_id",
            "idempotency_key",
            "command_bytes",
            "command_byte_length",
            "command_sha256",
            "command_fingerprint",
            "replacing_occurrence_id",
            "reason",
        )
        if not self._state.adding:
            previous = (
                type(self).objects.filter(pk=self.pk).values(*immutable_fields).first()
            )
            if previous is not None:
                changed = [
                    field
                    for field in immutable_fields
                    if previous[field] != getattr(self, field)
                ]
                if changed:
                    raise ValidationError(
                        {field: "approval command is immutable" for field in changed}
                    )
        return super().save(*args, **kwargs)

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.command_bytes and self.command_byte_length != len(self.command_bytes):
            errors["command_byte_length"] = "command byte length is inconsistent"
        if self.command_byte_length > 64 * 1024:
            errors["command_bytes"] = "command is too large"
        if self.kind == RoutineApprovalCommandKind.CANCEL_WAIT:
            if self.replacing_occurrence_id is None or not self.reason:
                errors["kind"] = "cancel-wait command requires replacement intent"
        elif self.kind == RoutineApprovalCommandKind.DECISION and (
            self.replacing_occurrence_id is not None or self.reason
        ):
            errors["kind"] = "decision command cannot carry cancel intent"
        if errors:
            raise ValidationError(errors)
