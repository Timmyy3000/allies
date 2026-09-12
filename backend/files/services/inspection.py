"""Run bounded private-file inspection through the isolated parser."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from allies.models import Ally, AllyDeletionState
from files.inspection import FileInspection, ScannerConfig
from files.isolated_inspection import inspect_isolated
from files.models import FileState, FileVersion
from files.services.intake import InspectionResult, promote_inspected_file
from files.services.preparation import reconcile_file_message
from files.services.publication import reconcile_publication
from files.storage import get_file_store

_RETRY_DELAYS = (5, 30)
_LEASE_SECONDS = 240
InspectionRunner = Callable[..., FileInspection]


def _scanner_config() -> ScannerConfig:
    return ScannerConfig(
        host=str(getattr(settings, "ALLIES_FILE_SCANNER_HOST", "")),
        port=int(getattr(settings, "ALLIES_FILE_SCANNER_PORT", 3310)),
    )


def _claim(*, file_id, now):
    with transaction.atomic():
        ally_id = (
            FileVersion.objects.filter(pk=file_id)
            .values_list("ally_id", flat=True)
            .first()
        )
        if (
            not Ally.objects.select_for_update(skip_locked=True)
            .filter(pk=ally_id, deletion_state=AllyDeletionState.ACTIVE)
            .first()
        ):
            return None
        file = (
            FileVersion.objects.select_for_update(skip_locked=True, of=("self",))
            .filter(
                pk=file_id,
                state=FileState.VALIDATING,
                ally__deletion_state=AllyDeletionState.ACTIVE,
            )
            .filter(
                Q(inspection_due_at__isnull=True) | Q(inspection_due_at__lte=now),
                Q(inspection_lease_until__isnull=True)
                | Q(inspection_lease_until__lte=now),
            )
            .first()
        )
        if file is None:
            return None
        file.inspection_lease_token = uuid.uuid4()
        file.inspection_lease_until = now + timedelta(seconds=_LEASE_SECONDS)
        file.save(
            update_fields=(
                "inspection_lease_token",
                "inspection_lease_until",
                "updated_at",
            )
        )
        return file


def _current(*, file: FileVersion, now):
    if (
        not Ally.objects.select_for_update()
        .filter(pk=file.ally_id, deletion_state=AllyDeletionState.ACTIVE)
        .first()
    ):
        return None
    return (
        FileVersion.objects.select_for_update(of=("self",))
        .filter(
            pk=file.id,
            generation=file.generation,
            state=FileState.VALIDATING,
            inspection_lease_token=file.inspection_lease_token,
            inspection_lease_until__gt=now,
            ally__deletion_state=AllyDeletionState.ACTIVE,
        )
        .first()
    )


def _reject(*, file: FileVersion, code: str) -> None:
    with transaction.atomic():
        current = _current(file=file, now=timezone.now())
        if current is None:
            return
        current.state = FileState.REJECTED
        current.safe_error_code = code
        current.inspection_due_at = None
        current.inspection_lease_until = None
        current.inspection_lease_token = None
        current.cleanup_after = timezone.now() + timedelta(hours=24)
        current.save(
            update_fields=(
                "state",
                "safe_error_code",
                "inspection_due_at",
                "inspection_lease_until",
                "inspection_lease_token",
                "cleanup_after",
                "updated_at",
            )
        )
        if current.publication_id:
            transaction.on_commit(
                lambda: reconcile_publication(publication_id=current.publication_id)
            )
        elif current.source_message_id:
            transaction.on_commit(
                lambda: reconcile_file_message(message_id=current.source_message_id)
            )


def _retry(*, file: FileVersion, code: str) -> None:
    with transaction.atomic():
        current = _current(file=file, now=timezone.now())
        if current is None:
            return
        attempts = current.inspection_attempts + 1
        if attempts >= 3:
            current.state = FileState.REJECTED
            current.cleanup_after = timezone.now() + timedelta(hours=24)
            current.inspection_due_at = None
        else:
            current.inspection_due_at = timezone.now() + timedelta(
                seconds=_RETRY_DELAYS[attempts - 1]
            )
        current.inspection_attempts = attempts
        current.inspection_lease_until = None
        current.inspection_lease_token = None
        current.safe_error_code = code
        current.save(
            update_fields=(
                "state",
                "cleanup_after",
                "inspection_attempts",
                "inspection_due_at",
                "inspection_lease_until",
                "inspection_lease_token",
                "safe_error_code",
                "updated_at",
            )
        )
        if current.state == FileState.REJECTED:
            if current.publication_id:
                transaction.on_commit(
                    lambda: reconcile_publication(publication_id=current.publication_id)
                )
            elif current.source_message_id:
                transaction.on_commit(
                    lambda: reconcile_file_message(message_id=current.source_message_id)
                )


def inspect_due_files(
    *, limit: int = 20, inspector: InspectionRunner = inspect_isolated
) -> int:
    """Inspect one bounded page; tests can inject an isolated-parser result."""
    if not 1 <= limit <= 100:
        raise ValueError("inspection limit is invalid")
    now = timezone.now()
    ids = list(
        FileVersion.objects.filter(
            state=FileState.VALIDATING,
            ally__deletion_state=AllyDeletionState.ACTIVE,
        )
        .filter(Q(inspection_due_at__isnull=True) | Q(inspection_due_at__lte=now))
        .filter(
            Q(inspection_lease_until__isnull=True) | Q(inspection_lease_until__lte=now)
        )
        .order_by("inspection_due_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    completed = 0
    for file_id in ids:
        file = _claim(file_id=file_id, now=timezone.now())
        if file is None:
            continue
        try:
            with get_file_store().open_stream(key=file.object_key) as stream:
                result = inspector(
                    name=file.original_name,
                    source=stream,
                    size=file.expected_size,
                    scanner_config=_scanner_config(),
                )
        except Exception:  # noqa: BLE001 - private storage and parser fail closed
            _retry(file=file, code="inspection_unavailable")
            completed += 1
            continue
        if not result.accepted:
            if result.safe_error_code in {
                "scanner_unavailable",
                "scanner_timeout",
                "scanner_definitions_stale",
                "inspection_unavailable",
                "inspection_timeout",
                "inspection_isolation_unavailable",
            }:
                _retry(file=file, code=result.safe_error_code)
            else:
                _reject(file=file, code=result.safe_error_code or "inspection_rejected")
            completed += 1
            continue
        try:
            promote_inspected_file(
                file_id=file.id,
                generation=file.generation,
                inspection_lease_token=file.inspection_lease_token,
                result=InspectionResult(
                    size=result.actual_size or 0,
                    sha256=result.sha256 or "",
                    media_type=result.media_type or "",
                    clean=True,
                ),
            )
        except Exception:  # noqa: BLE001 - promotion failures are retryable
            _retry(file=file, code="inspection_unavailable")
        completed += 1
    return completed


__all__ = ["inspect_due_files"]
