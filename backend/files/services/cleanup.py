"""Bounded private-file cleanup and the deletion-owner hook."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from allies.models import Ally
from files.models import (
    FileAllyTombstone,
    FileDraftFile,
    FileObjectKind,
    FilePublication,
    FileStagingObject,
    FileState,
    FileStorageAccount,
    FileVersion,
    MessageFile,
    PublicationState,
)
from files.storage import get_file_store


@dataclass(frozen=True, slots=True)
class CleanupReport:
    claimed: int
    deleted: int
    failures: int
    alerts: int


def _protected(file: FileVersion) -> bool:
    return (
        file.publication_id is not None
        or MessageFile.objects.filter(
            file=file,
            removed_at__isnull=True,
            message__deleted_at__isnull=True,
        ).exists()
        or FileDraftFile.objects.filter(
            file=file, draft__discarded_at__isnull=True
        ).exists()
    )


def _account_locked(workspace_id) -> FileStorageAccount:
    FileStorageAccount.objects.get_or_create(workspace_id=workspace_id)
    return FileStorageAccount.objects.select_for_update().get(workspace_id=workspace_id)


def _candidate(*, file: FileVersion, key: str, now) -> FileStagingObject:
    candidate, created = FileStagingObject.objects.get_or_create(
        key=key,
        defaults={
            "file": file,
            "generation": file.generation,
            "write_fence": file.write_fence,
            "kind": FileObjectKind.OBJECT,
            "cleanup_after": now,
        },
    )
    if not created and candidate.deleted_at is None:
        candidate.generation = file.generation
        candidate.write_fence = file.write_fence
        candidate.cleanup_after = now
        candidate.cleanup_lease_until = None
        candidate.save(
            update_fields=(
                "generation",
                "write_fence",
                "cleanup_after",
                "cleanup_lease_until",
            )
        )
    return candidate


def _reconcile_staging_candidate(candidate: FileStagingObject) -> None:
    if candidate.kind != FileObjectKind.STAGING:
        return
    file = FileVersion.objects.only("publication_id", "source_message_id").get(
        pk=candidate.file_id
    )
    if file.publication_id is not None:
        from files.services.publication import reconcile_publication

        reconcile_publication(publication_id=file.publication_id)
    elif file.source_message_id is not None:
        from files.services.preparation import reconcile_file_message

        reconcile_file_message(message_id=file.source_message_id)


def schedule_file_cleanup(*, file_id, force: bool = False, now=None) -> bool:
    """Record one immutable object for deletion after its last protection ends."""
    now = now or timezone.now()
    with transaction.atomic():
        workspace_id = FileVersion.objects.values_list("workspace_id", flat=True).get(
            pk=file_id
        )
        account = _account_locked(workspace_id)
        file = FileVersion.objects.select_for_update().get(pk=file_id)
        tombstoned = FileAllyTombstone.objects.filter(ally_id=file.ally_id).exists()
        if not (force or tombstoned) and _protected(file):
            return False
        if not file.object_key:
            if (
                file.state != FileState.PENDING
                or FileStagingObject.objects.filter(
                    file=file, deleted_at__isnull=True
                ).exists()
            ):
                return False
            if file.reserved_accounted:
                account.reserved_bytes -= file.expected_size
                account.save(update_fields=("reserved_bytes", "updated_at"))
                file.reserved_accounted = False
            file.state = FileState.DELETED
            file.write_fence = uuid.uuid4()
            file.save(
                update_fields=(
                    "state",
                    "write_fence",
                    "reserved_accounted",
                    "updated_at",
                )
            )
            return True
        if file.state != FileState.READY and not force:
            return False
        file.state = FileState.CLEANUP_PENDING
        file.write_fence = uuid.uuid4()
        file.lease_until = None
        file.inspection_lease_until = None
        file.inspection_lease_token = None
        file.save(
            update_fields=(
                "state",
                "write_fence",
                "lease_until",
                "inspection_lease_until",
                "inspection_lease_token",
                "updated_at",
            )
        )
        _candidate(file=file, key=file.object_key, now=now)
    return True


def tombstone_ally_files(*, ally_id, now=None) -> FileAllyTombstone:
    """Deny file operations immediately; the deletion owner supplies the receipt later."""
    now = now or timezone.now()
    with transaction.atomic():
        workspace_id = Ally.objects.only("workspace_id").get(pk=ally_id).workspace_id
        account = _account_locked(workspace_id)
        ally = Ally.objects.select_for_update().get(
            pk=ally_id, workspace_id=workspace_id
        )
        from chat.models import Conversation

        list(
            Conversation.objects.select_for_update()
            .filter(ally=ally)
            .order_by("id")
            .values_list("id", flat=True)
        )
        tombstone, _ = FileAllyTombstone.objects.get_or_create(
            ally=ally, defaults={"tombstoned_at": now}
        )
        released = False
        files = (
            FileVersion.objects.select_for_update()
            .filter(ally=ally)
            .exclude(state__in=(FileState.READY, FileState.DELETED))
        )
        for file in files:
            file.write_fence = uuid.uuid4()
            file.lease_until = None
            file.inspection_lease_until = None
            file.inspection_lease_token = None
            if file.state == FileState.PENDING and not file.object_key:
                if file.reserved_accounted:
                    account.reserved_bytes -= file.expected_size
                    file.reserved_accounted = False
                    released = True
                file.state = FileState.DELETED
                file.safe_error_code = "ally_deleted"
            file.save(
                update_fields=(
                    "state",
                    "safe_error_code",
                    "write_fence",
                    "lease_until",
                    "inspection_lease_until",
                    "inspection_lease_token",
                    "reserved_accounted",
                    "updated_at",
                )
            )
        if released:
            account.save(update_fields=("reserved_bytes", "updated_at"))
        FilePublication.objects.filter(
            binding__ally=ally,
            state__in=(
                PublicationState.UPLOADING,
                PublicationState.VALIDATING,
                PublicationState.RETRY_PENDING,
                PublicationState.FAILED,
            ),
        ).update(
            state=PublicationState.CANCELLED,
            retry_due_at=None,
            lease_until=None,
            lease_token=None,
            safe_error_code="ally_deleted",
        )
    return tombstone


def record_foundry_cleanup_receipt(*, ally_id, receipt: str) -> FileAllyTombstone:
    if not isinstance(receipt, str) or not 1 <= len(receipt) <= 128:
        raise ValueError("invalid cleanup receipt")
    with transaction.atomic():
        tombstone = FileAllyTombstone.objects.select_for_update().get(ally_id=ally_id)
        if not tombstone.foundry_cleanup_receipt:
            tombstone.foundry_cleanup_receipt = receipt
            tombstone.save(update_fields=("foundry_cleanup_receipt", "updated_at"))
    return tombstone


def _schedule_tombstoned(*, limit: int, now) -> None:
    ids = list(
        FileVersion.objects.filter(
            ally__file_tombstone__isnull=False,
            object_key__gt="",
            state__in=(
                FileState.READY,
                FileState.RECEIVING,
                FileState.VALIDATING,
                FileState.FAILED,
                FileState.REJECTED,
            ),
        )
        .order_by("id")
        .values_list("id", flat=True)[:limit]
    )
    for file_id in ids:
        schedule_file_cleanup(file_id=file_id, force=True, now=now)


def _claim(*, candidate_id, now):
    with transaction.atomic():
        workspace_id = (
            FileStagingObject.objects.filter(pk=candidate_id)
            .values_list("file__workspace_id", flat=True)
            .first()
        )
        if workspace_id is None:
            return None
        _account_locked(workspace_id)
        candidate = (
            FileStagingObject.objects.select_for_update(skip_locked=True)
            .filter(
                pk=candidate_id,
                deleted_at__isnull=True,
                cleanup_after__lte=now,
                cleanup_attempts__lt=5,
            )
            .filter(
                Q(cleanup_lease_until__isnull=True) | Q(cleanup_lease_until__lte=now)
            )
            .first()
        )
        if candidate is None:
            return None
        file = FileVersion.objects.select_for_update().get(pk=candidate.file_id)
        tombstoned = FileAllyTombstone.objects.filter(ally_id=file.ally_id).exists()
        current_staging = (
            candidate.kind == FileObjectKind.STAGING
            and file.generation == candidate.generation
            and file.object_key == candidate.key
        )
        current_object = (
            candidate.kind == FileObjectKind.OBJECT and file.object_key == candidate.key
        )
        if current_object and not tombstoned and _protected(file):
            candidate.cleanup_after = now + timedelta(seconds=60)
            candidate.save(update_fields=("cleanup_after",))
            return None
        if current_staging:
            file.write_fence = uuid.uuid4()
            file.state = FileState.FAILED
            file.safe_error_code = "upload_interrupted"
            file.object_key = ""
            file.lease_until = None
            file.inspection_lease_until = None
            file.inspection_lease_token = None
            file.save(
                update_fields=(
                    "write_fence",
                    "state",
                    "safe_error_code",
                    "object_key",
                    "lease_until",
                    "inspection_lease_until",
                    "inspection_lease_token",
                    "updated_at",
                )
            )
        elif current_object:
            file.state = FileState.CLEANUP_PENDING
            file.save(update_fields=("state", "updated_at"))
        candidate.cleanup_lease_until = now + timedelta(seconds=60)
        candidate.save(update_fields=("cleanup_lease_until",))
        return candidate


def _complete(*, candidate_id, now) -> None:
    with transaction.atomic():
        workspace_id = (
            FileStagingObject.objects.filter(pk=candidate_id)
            .values_list("file__workspace_id", flat=True)
            .first()
        )
        if workspace_id is None:
            return
        account = _account_locked(workspace_id)
        candidate = (
            FileStagingObject.objects.select_for_update()
            .filter(pk=candidate_id, deleted_at__isnull=True)
            .first()
        )
        if candidate is None:
            return
        file = FileVersion.objects.select_for_update().get(pk=candidate.file_id)
        current_object = (
            candidate.kind == FileObjectKind.OBJECT
            and file.state == FileState.CLEANUP_PENDING
            and file.object_key == candidate.key
            and file.generation == candidate.generation
            and file.write_fence == candidate.write_fence
        )
        current_staging = (
            candidate.kind == FileObjectKind.STAGING
            and file.generation == candidate.generation
            and file.state == FileState.FAILED
            and file.object_key == ""
        )
        if current_object or current_staging:
            if file.reserved_accounted:
                account.reserved_bytes -= file.expected_size
                file.reserved_accounted = False
            elif file.retained_accounted:
                account.retained_bytes -= file.actual_size or file.expected_size
                file.retained_accounted = False
            account.save(
                update_fields=("reserved_bytes", "retained_bytes", "updated_at")
            )
            if current_object:
                file.state = FileState.DELETED
                file.object_key = ""
            file.save(
                update_fields=(
                    "state",
                    "object_key",
                    "reserved_accounted",
                    "retained_accounted",
                    "updated_at",
                )
            )
        candidate.deleted_at = now
        candidate.cleanup_lease_until = None
        candidate.save(update_fields=("deleted_at", "cleanup_lease_until"))


def _failed(*, candidate_id, now, error: str = "storage_unavailable") -> bool:
    with transaction.atomic():
        candidate = (
            FileStagingObject.objects.select_for_update()
            .filter(pk=candidate_id, deleted_at__isnull=True)
            .first()
        )
        if candidate is None:
            return False
        candidate.cleanup_attempts += 1
        candidate.cleanup_lease_until = None
        candidate.cleanup_last_error = error
        candidate.cleanup_after = now + timedelta(seconds=60)
        candidate.save(
            update_fields=(
                "cleanup_attempts",
                "cleanup_lease_until",
                "cleanup_last_error",
                "cleanup_after",
            )
        )
        return candidate.cleanup_attempts >= 5


def cleanup_files(
    *, now=None, limit: int = 100, duration_seconds: float = 60.0
) -> CleanupReport:
    if not 1 <= limit <= 100 or not 0 < duration_seconds <= 60:
        raise ValueError("invalid cleanup limit")
    now = now or timezone.now()
    _schedule_tombstoned(limit=limit, now=now)
    deadline = time.monotonic() + duration_seconds
    ids = list(
        FileStagingObject.objects.filter(
            deleted_at__isnull=True,
            cleanup_after__lte=now,
            cleanup_attempts__lt=5,
        )
        .filter(Q(cleanup_lease_until__isnull=True) | Q(cleanup_lease_until__lte=now))
        .order_by("cleanup_after", "id")
        .values_list("id", flat=True)[:limit]
    )
    claimed = deleted = failures = alerts = 0
    for candidate_id in ids:
        if time.monotonic() >= deadline:
            break
        candidate = _claim(candidate_id=candidate_id, now=now)
        if candidate is None:
            continue
        claimed += 1
        try:
            _reconcile_staging_candidate(candidate)
        except Exception:  # noqa: BLE001 - retry durable reconciliation before receipt
            failures += 1
            alerts += int(
                _failed(
                    candidate_id=candidate.id,
                    now=now,
                    error="reconcile_unavailable",
                )
            )
            continue
        try:
            get_file_store().delete(key=candidate.key)
        except Exception:  # noqa: BLE001 - cleanup records external store uncertainty
            failures += 1
            alerts += int(_failed(candidate_id=candidate.id, now=now))
        else:
            _complete(candidate_id=candidate.id, now=now)
            deleted += 1
    return CleanupReport(
        claimed=claimed, deleted=deleted, failures=failures, alerts=alerts
    )


__all__ = [
    "CleanupReport",
    "cleanup_files",
    "record_foundry_cleanup_receipt",
    "schedule_file_cleanup",
    "tombstone_ally_files",
]
