"""Private file metadata and immutable execution-manifest references."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from files.types import MAX_FILE_BYTES

# Django model metaclasses intentionally consume mutable Meta collections.
# ruff: noqa: RUF012

DIGEST_LENGTH = 64


class FileDirection(models.TextChoices):
    INBOUND = "inbound", "Inbound"
    OUTBOUND = "outbound", "Outbound"


class FileState(models.TextChoices):
    PENDING = "pending", "Pending"
    RECEIVING = "receiving", "Receiving"
    VALIDATING = "validating", "Validating"
    READY = "ready", "Ready"
    RETAINED = "retained", "Retained"
    FAILED = "failed", "Failed"
    REJECTED = "rejected", "Rejected"
    CLEANUP_PENDING = "cleanup_pending", "Cleanup pending"
    DELETED = "deleted", "Deleted"


class FileObjectKind(models.TextChoices):
    STAGING = "staging", "Staging"
    PROMOTION = "promotion", "Promotion"
    OBJECT = "object", "Object"


class PublicationState(models.TextChoices):
    UPLOADING = "uploading", "Uploading"
    VALIDATING = "validating", "Validating"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"
    RETRY_PENDING = "retry_pending", "Retry pending"
    CANCELLED = "cancelled", "Cancelled"


class FileVersion(models.Model):
    """One immutable private version; byte staging is intentionally later work."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.PROTECT, related_name="file_versions"
    )
    ally = models.ForeignKey(
        "allies.Ally", on_delete=models.PROTECT, related_name="file_versions"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="file_versions"
    )
    source_message = models.ForeignKey(
        "chat.Message",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_file_versions",
    )
    direction = models.CharField(max_length=16, choices=FileDirection.choices)
    original_name = models.CharField(max_length=255)
    media_type = models.CharField(max_length=127)
    expected_size = models.PositiveBigIntegerField()
    actual_size = models.PositiveBigIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=DIGEST_LENGTH)
    object_key = models.CharField(
        max_length=500, blank=True, default="", editable=False
    )
    state = models.CharField(
        max_length=24, choices=FileState.choices, default=FileState.PENDING
    )
    generation = models.PositiveIntegerField(default=1)
    write_fence = models.UUIDField(default=uuid.uuid4, editable=False)
    source_version_id = models.UUIDField(null=True, blank=True, editable=False)
    publication = models.ForeignKey(
        "FilePublication",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="files",
    )
    reserved_accounted = models.BooleanField(default=False, editable=False)
    retained_accounted = models.BooleanField(default=False, editable=False)
    inspection_attempts = models.PositiveSmallIntegerField(default=0)
    inspection_due_at = models.DateTimeField(null=True, blank=True)
    inspection_lease_until = models.DateTimeField(null=True, blank=True)
    inspection_lease_token = models.UUIDField(null=True, blank=True, editable=False)
    safe_error_code = models.CharField(max_length=64, blank=True, default="")
    lease_until = models.DateTimeField(null=True, blank=True)
    cleanup_after = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(expected_size__gt=0) & Q(expected_size__lte=MAX_FILE_BYTES),
                name="files_version_expected_size_bound",
            ),
            models.CheckConstraint(
                condition=Q(actual_size__isnull=True)
                | (Q(actual_size__gt=0) & Q(actual_size__lte=MAX_FILE_BYTES)),
                name="files_version_actual_size_bound",
            ),
            models.CheckConstraint(
                condition=Q(sha256__regex=r"^[0-9a-f]{64}$"),
                name="files_version_sha256_valid",
            ),
            models.CheckConstraint(
                condition=Q(generation__gt=0), name="files_version_generation_positive"
            ),
        ]
        indexes = [
            models.Index(
                fields=("workspace", "ally", "state"),
                name="files_version_scope_state_idx",
            ),
            models.Index(
                fields=("state", "cleanup_after"), name="files_version_cleanup_idx"
            ),
        ]


class FileStorageAccount(models.Model):
    """Workspace-scoped private-file accounting row locked during admission."""

    workspace = models.OneToOneField(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="file_storage_account",
    )
    reserved_bytes = models.PositiveBigIntegerField(default=0)
    retained_bytes = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class FileStagingObject(models.Model):
    """A recorded private key with durable, fenced cleanup evidence."""

    file = models.ForeignKey(
        FileVersion, on_delete=models.CASCADE, related_name="staging_objects"
    )
    key = models.CharField(max_length=500, unique=True)
    generation = models.PositiveIntegerField()
    write_fence = models.UUIDField(editable=False)
    kind = models.CharField(
        max_length=16, choices=FileObjectKind.choices, default=FileObjectKind.STAGING
    )
    cleanup_attempts = models.PositiveSmallIntegerField(default=0)
    cleanup_lease_until = models.DateTimeField(null=True, blank=True)
    cleanup_last_error = models.CharField(max_length=64, blank=True, default="")
    deleted_at = models.DateTimeField(null=True, blank=True)
    cleanup_after = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("cleanup_after", "id"), name="files_staging_cleanup_idx"
            ),
            models.Index(
                fields=("deleted_at", "cleanup_after", "id"),
                name="files_object_due_idx",
            ),
        ]


class MessageFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        "chat.Message", on_delete=models.CASCADE, related_name="file_links"
    )
    file = models.ForeignKey(
        FileVersion, on_delete=models.PROTECT, related_name="message_links"
    )
    position = models.PositiveSmallIntegerField()
    removed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("message", "position"), name="files_message_position_uniq"
            ),
            models.UniqueConstraint(
                fields=("message", "file"), name="files_message_file_uniq"
            ),
        ]


class FileDraftRecovery(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.OneToOneField(
        "chat.Message", on_delete=models.CASCADE, related_name="file_draft_recovery"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="file_drafts"
    )
    ally = models.ForeignKey(
        "allies.Ally", on_delete=models.PROTECT, related_name="file_drafts"
    )
    content = models.TextField(max_length=16_000)
    discarded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("owner", "ally", "discarded_at"),
                name="files_draft_scope_idx",
            )
        ]


class FileDraftFile(models.Model):
    draft = models.ForeignKey(
        FileDraftRecovery, on_delete=models.CASCADE, related_name="file_links"
    )
    file = models.ForeignKey(
        FileVersion, on_delete=models.PROTECT, related_name="draft_links"
    )
    position = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("draft", "file"), name="files_draft_file_uniq"
            ),
            models.UniqueConstraint(
                fields=("draft", "position"), name="files_draft_position_uniq"
            ),
        ]


class FilePublication(models.Model):
    """Fenced return-file state for one immutable Foundry publication."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    binding = models.ForeignKey(
        "allies.AllyBinding", on_delete=models.PROTECT, related_name="file_publications"
    )
    source_message = models.ForeignKey(
        "chat.Message", on_delete=models.PROTECT, related_name="file_publications"
    )
    request_digest = models.CharField(max_length=DIGEST_LENGTH, blank=True, default="")
    revision = models.PositiveIntegerField(default=1)
    state = models.CharField(
        max_length=24,
        choices=PublicationState.choices,
        default=PublicationState.UPLOADING,
    )
    safe_error_code = models.CharField(max_length=64, blank=True, default="")
    retry_due_at = models.DateTimeField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True, editable=False)
    retry_attempts = models.PositiveSmallIntegerField(default=0)
    result_revision = models.PositiveIntegerField(null=True, blank=True)
    result_lease_token = models.UUIDField(null=True, blank=True, editable=False)
    result_outcome = models.CharField(max_length=16, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(request_digest="")
                | Q(request_digest__regex=r"^[0-9a-f]{64}$"),
                name="files_publication_request_digest_valid",
            ),
            models.CheckConstraint(
                condition=Q(revision__gt=0), name="files_publication_revision_positive"
            ),
            models.CheckConstraint(
                condition=Q(retry_attempts__lte=5),
                name="files_publication_retry_attempts_bound",
            ),
        ]
        indexes = [
            models.Index(
                fields=("state", "retry_due_at", "lease_until"),
                name="files_publication_due_idx",
            ),
        ]


class FileAllyTombstone(models.Model):
    """The deletion owner calls this narrow boundary before remote cleanup."""

    ally = models.OneToOneField(
        "allies.Ally", on_delete=models.PROTECT, related_name="file_tombstone"
    )
    tombstoned_at = models.DateTimeField()
    foundry_cleanup_receipt = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
