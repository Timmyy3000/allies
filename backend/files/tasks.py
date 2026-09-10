"""Private-file worker entrypoints."""

from __future__ import annotations

from celery import shared_task

from files.services.cleanup import cleanup_files
from files.services.inspection import inspect_due_files


@shared_task(name="files.inspect_due_files", bind=True, max_retries=0)
def inspect_due_files_task(self, limit: int = 20) -> int:
    return inspect_due_files(limit=min(max(int(limit), 1), 100))


@shared_task(name="files.cleanup_files", bind=True, max_retries=0)
def cleanup_files_task(self, limit: int = 100) -> dict[str, int]:
    result = cleanup_files(limit=min(max(int(limit), 1), 100))
    return {
        "claimed": result.claimed,
        "deleted": result.deleted,
        "failures": result.failures,
        "alerts": result.alerts,
    }
