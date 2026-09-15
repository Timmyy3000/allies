"""Private-file worker entrypoints."""

from __future__ import annotations

import logging
from uuid import UUID

from celery import current_app, shared_task
from kombu import Producer

from files.services.cleanup import cleanup_files
from files.services.inspection import inspect_due_files, inspect_file

logger = logging.getLogger(__name__)


def enqueue_file_inspection(file_id, *, countdown: int = 0) -> None:
    """Best-effort notification; the due-file sweep owns recovery."""
    transport_options = dict(current_app.conf.broker_transport_options or {})
    transport_options.update(
        socket_connect_timeout=1,
        socket_timeout=1,
        retry_on_timeout=False,
    )
    try:
        with (
            current_app.connection_for_write(
                connect_timeout=1, transport_options=transport_options
            ) as connection,
            Producer(connection) as producer,
        ):
            inspect_file_task.apply_async(
                args=(str(file_id),),
                countdown=countdown,
                producer=producer,
                retry=False,
            )
    except Exception as exc:  # noqa: BLE001 - the database sweep is durable recovery
        logger.warning(
            "file inspection notification failed",
            extra={
                "outcome": "broker_unavailable",
                "error_type": type(exc).__name__,
            },
        )


@shared_task(name="files.inspect_file", bind=True, max_retries=0)
def inspect_file_task(self, file_id: str) -> int:
    if not isinstance(file_id, str):
        raise TypeError("file id must be a canonical UUID")
    parsed = UUID(file_id)
    if file_id != str(parsed):
        raise ValueError("file id must be a canonical UUID")
    return inspect_file(file_id=parsed)


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
