"""Commit-visible wake signals for already-running runtime workers."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from runtime.exceptions import (
    ActivityWaitSaturated,
    ActivityWaitUnavailable,
    RuntimeFencedError,
    RuntimeValidationError,
)
from runtime.models import Workspace

from .runtime_auth import RuntimeContext

MAX_ACTIVITY_WAIT_SECONDS = 5.0
DEFAULT_ACTIVITY_WAIT_MAX_WAITERS = 8

_waiter_state_lock = threading.Lock()
_active_waiters = 0
_workspace_waits: set[UUID] = set()


@dataclass(frozen=True, slots=True)
class ActivityWaitResult:
    revision: int
    reason: str


def workspace_activity_channel(workspace_id: UUID | str) -> str:
    try:
        workspace_uuid = (
            workspace_id if isinstance(workspace_id, UUID) else UUID(str(workspace_id))
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError("workspace_id must be a UUID") from exc
    return f"allies_activity_{workspace_uuid.hex}"


def advance_workspace_activity(workspace: Workspace) -> int:
    """Increment and notify while participating in the caller's transaction."""

    if workspace.pk is None:
        raise RuntimeValidationError(
            "workspace must be persisted before activity advances"
        )
    if connection.get_autocommit():
        with transaction.atomic():
            return _advance_workspace_activity(workspace)
    return _advance_workspace_activity(workspace)


def _advance_workspace_activity(workspace: Workspace) -> int:
    updated = Workspace.objects.filter(pk=workspace.pk).update(
        activity_revision=F("activity_revision") + 1,
        updated_at=timezone.now(),
    )
    if updated != 1:
        raise RuntimeValidationError("workspace does not exist")
    workspace.refresh_from_db(fields=["activity_revision"])
    revision = int(workspace.activity_revision)
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_notify(%s, %s)",
                [workspace_activity_channel(workspace.id), str(revision)],
            )
    return revision


def wait_for_workspace_activity(
    context: RuntimeContext,
    after_revision: int,
    wait_seconds: float,
) -> ActivityWaitResult:
    """Wait for a committed revision change without taking a row lock."""

    _validate_context(context)
    if isinstance(after_revision, bool) or not isinstance(after_revision, int):
        raise RuntimeValidationError("after_revision must be a non-negative integer")
    if after_revision < 0:
        raise RuntimeValidationError("after_revision must be a non-negative integer")
    if isinstance(wait_seconds, bool):
        raise RuntimeValidationError("wait_seconds must be a positive number")
    try:
        requested_seconds = float(wait_seconds)
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError("wait_seconds must be a positive number") from exc
    configured_seconds = float(
        getattr(
            settings, "ALLIES_RUNTIME_ACTIVITY_WAIT_SECONDS", MAX_ACTIVITY_WAIT_SECONDS
        )
    )
    max_seconds = min(MAX_ACTIVITY_WAIT_SECONDS, configured_seconds)
    if not 0 < requested_seconds <= max_seconds:
        raise RuntimeValidationError(
            f"wait_seconds must be greater than 0 and at most {max_seconds:g}"
        )
    if not getattr(settings, "ALLIES_RUNTIME_ACTIVITY_WAIT_ENABLED", False):
        raise ActivityWaitUnavailable("activity wait is disabled")
    if connection.vendor != "postgresql":
        raise ActivityWaitUnavailable("activity wait requires PostgreSQL")

    _reserve_waiter(context.workspace_id)
    try:
        return _wait_postgres(context, after_revision, requested_seconds)
    finally:
        _release_waiter(context.workspace_id)


def _wait_postgres(
    context: RuntimeContext,
    after_revision: int,
    wait_seconds: float,
) -> ActivityWaitResult:
    try:
        import psycopg
        from psycopg import sql
    except ImportError as exc:  # pragma: no cover - deployment dependency
        raise ActivityWaitUnavailable("PostgreSQL driver is unavailable") from exc

    params = dict(connection.get_connection_params())
    # Django's backend may include adapter-only values that psycopg.connect
    # does not understand when opening the independent LISTEN connection.
    params.pop("cursor_factory", None)
    params.pop("connection_factory", None)
    params["connect_timeout"] = 2
    channel = workspace_activity_channel(context.workspace_id)
    table = Workspace._meta.db_table
    try:
        with psycopg.connect(**params) as listener:
            listener.autocommit = True
            listener.execute(
                "SELECT set_config('statement_timeout', %s, false)", ["6000ms"]
            )
            listener.execute("SELECT set_config('lock_timeout', %s, false)", ["1000ms"])
            listener.execute(sql.SQL("LISTEN {}").format(sql.Identifier(channel)))
            locked = listener.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
                [channel],
            ).fetchone()[0]
            if not locked:
                raise ActivityWaitSaturated("workspace already has an activity waiter")
            try:
                current = _read_revision(listener, sql, table, context)
                if current > after_revision:
                    return ActivityWaitResult(current, "changed")
                for _notification in listener.notifies(
                    timeout=wait_seconds,
                    stop_after=1,
                ):
                    break
                current = _read_revision(listener, sql, table, context)
                return ActivityWaitResult(
                    current,
                    "changed" if current > after_revision else "timeout",
                )
            finally:
                # PostgreSQL releases the advisory lock with this connection;
                # explicitly unlocking keeps the ownership intent clear.
                listener.execute(
                    "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                    [channel],
                )
    except (RuntimeFencedError, ActivityWaitSaturated):
        raise
    except Exception as exc:
        raise ActivityWaitUnavailable("activity wait connection failed") from exc


def _read_revision(listener: Any, sql: Any, table: str, context: RuntimeContext) -> int:
    row = listener.execute(
        sql.SQL(
            "SELECT activity_revision, machine_generation FROM {} WHERE id = %s"
        ).format(sql.Identifier(table)),
        [context.workspace_id],
    ).fetchone()
    if row is None:
        raise RuntimeFencedError("runtime workspace does not exist")
    if int(row[1]) != context.machine_generation:
        raise RuntimeFencedError("runtime credential belongs to a retired generation")
    return int(row[0])


def _reserve_waiter(workspace_id: UUID) -> None:
    global _active_waiters
    maximum = int(
        getattr(
            settings,
            "ALLIES_RUNTIME_ACTIVITY_WAIT_MAX_WAITERS",
            DEFAULT_ACTIVITY_WAIT_MAX_WAITERS,
        )
    )
    with _waiter_state_lock:
        if _active_waiters >= maximum or workspace_id in _workspace_waits:
            raise ActivityWaitSaturated("activity wait capacity is full")
        _active_waiters += 1
        _workspace_waits.add(workspace_id)


def _release_waiter(workspace_id: UUID) -> None:
    global _active_waiters
    with _waiter_state_lock:
        _active_waiters = max(0, _active_waiters - 1)
        _workspace_waits.discard(workspace_id)


def _validate_context(context: RuntimeContext) -> None:
    if not isinstance(context, RuntimeContext):
        raise RuntimeValidationError("runtime context is required")
    if not isinstance(context.workspace_id, UUID):
        raise RuntimeValidationError("runtime context workspace_id is invalid")
    if (
        isinstance(context.machine_generation, bool)
        or not isinstance(context.machine_generation, int)
        or context.machine_generation < 0
    ):
        raise RuntimeValidationError("runtime context generation is invalid")


__all__ = [
    "DEFAULT_ACTIVITY_WAIT_MAX_WAITERS",
    "MAX_ACTIVITY_WAIT_SECONDS",
    "ActivityWaitResult",
    "advance_workspace_activity",
    "wait_for_workspace_activity",
    "workspace_activity_channel",
]
