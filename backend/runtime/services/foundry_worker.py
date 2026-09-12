"""The bounded, single-process Foundry background worker."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from time import monotonic

from django.db import close_old_connections, connection

from .event_delivery import publish_pending_event_deliveries
from .provisioning_hints import publish_due_profile_readiness_hints
from .publications import wake_due_publications
from .ready_pool_maintenance import maintain_ready_pool_once
from .runtime_intents import cleanup_runtime_intents
from .runtime_power import process_runtime_wakes, stop_idle_workspaces

logger = logging.getLogger(__name__)

EVENT_INTERVAL_SECONDS = 1.0
HINT_INTERVAL_SECONDS = 1.0
POWER_INTERVAL_SECONDS = 1.0
POOL_INTERVAL_SECONDS = 5.0
DEFAULT_SHUTDOWN_GRACE_SECONDS = 30.0
MAX_WORKER_RUNS = 1440
SUPERVISOR_POLL_SECONDS = 0.1


class FoundryWorkerError(RuntimeError):
    """Worker supervision failed or shutdown exceeded its shared grace."""


def _power_publication_pass(cursor: str | None = None) -> str | None:
    """Run every power/publication task even when one external call fails."""

    try:
        page = wake_due_publications(limit=20, cursor=cursor)
    except Exception as exc:  # noqa: BLE001 - the next bounded pass retries
        _report_error("power-publication", "publication", exc)
    else:
        cursor = page.next_cursor

    try:
        process_runtime_wakes(limit=1)
    except Exception as exc:  # noqa: BLE001 - cleanup and idle stop still run
        _report_error("power-publication", "runtime-wake", exc)

    try:
        cleanup_runtime_intents()
    except Exception as exc:  # noqa: BLE001 - the next pass retries cleanup
        _report_error("power-publication", "intent-cleanup", exc)

    try:
        stop_idle_workspaces(limit=1)
    except Exception as exc:  # noqa: BLE001 - a failed stop must not halt wakes
        _report_error("power-publication", "idle-stop", exc)
    return cursor


def _loop_specs() -> tuple[tuple[str, float, Callable[[], object]], ...]:
    cursor: str | None = None

    def power_pass() -> None:
        nonlocal cursor
        cursor = _power_publication_pass(cursor)

    return (
        (
            "event",
            EVENT_INTERVAL_SECONDS,
            lambda: publish_pending_event_deliveries(limit=1),
        ),
        (
            "hints",
            HINT_INTERVAL_SECONDS,
            lambda: publish_due_profile_readiness_hints(limit=1),
        ),
        ("power-publication", POWER_INTERVAL_SECONDS, power_pass),
        ("pool", POOL_INTERVAL_SECONDS, lambda: maintain_ready_pool_once(limit=1)),
    )


def _report_error(loop_name: str, step_name: str, exc: BaseException) -> None:
    error_type = type(exc).__name__[:64]
    logger.warning(
        "foundry_worker_error code=%s_%s_failed type=%s",
        loop_name.replace("-", "_"),
        step_name.replace("-", "_"),
        error_type,
    )


def _run_loop(
    name: str,
    interval: float,
    callback: Callable[[], object],
    stop_event: threading.Event,
    max_runs: int | None,
) -> None:
    runs = 0
    try:
        while not stop_event.is_set():
            try:
                close_old_connections()
                if stop_event.is_set():
                    break
                callback()
            except Exception as exc:  # noqa: BLE001 - one pass cannot kill a loop
                _report_error(name, "pass", exc)
            finally:
                try:
                    close_old_connections()
                except Exception as exc:  # noqa: BLE001 - retry next pass
                    _report_error(name, "connection-close", exc)
            runs += 1
            if max_runs is not None and runs >= max_runs:
                break
            if stop_event.wait(interval):
                break
    finally:
        try:
            connection.close()
        except Exception as exc:  # noqa: BLE001 - keep supervision informed
            _report_error(name, "thread-close", exc)


def _thread_target(
    name: str,
    interval: float,
    callback: Callable[[], object],
    stop_event: threading.Event,
    max_runs: int | None,
    statuses: dict[str, str],
    statuses_lock: threading.Lock,
) -> None:
    try:
        _run_loop(name, interval, callback, stop_event, max_runs)
    except BaseException as exc:  # noqa: BLE001 - supervision must see dead loops
        with statuses_lock:
            statuses[name] = "failed"
        _report_error(name, "thread", exc)
        return
    with statuses_lock:
        statuses[name] = "completed"


def _join_until(threads: tuple[threading.Thread, ...], grace: float) -> bool:
    deadline = monotonic() + grace
    for thread in threads:
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        thread.join(remaining)
    return all(not thread.is_alive() for thread in threads)


def _validate_options(max_runs: int | None, shutdown_grace_seconds: float) -> None:
    if max_runs is not None and (
        isinstance(max_runs, bool)
        or not isinstance(max_runs, int)
        or not 1 <= max_runs <= MAX_WORKER_RUNS
    ):
        raise ValueError("max_runs must be between 1 and 1440")
    if isinstance(shutdown_grace_seconds, bool) or not isinstance(
        shutdown_grace_seconds, (int, float)
    ):
        raise TypeError("shutdown grace must be a number")
    if not 0 <= shutdown_grace_seconds <= DEFAULT_SHUTDOWN_GRACE_SECONDS:
        raise ValueError("shutdown grace must be between 0 and 30 seconds")


def run_foundry_worker(
    *,
    stop_event: threading.Event | None = None,
    max_runs: int | None = None,
    shutdown_grace_seconds: float = DEFAULT_SHUTDOWN_GRACE_SECONDS,
) -> None:
    """Run four fixed background loops until stopped or supervision fails."""

    _validate_options(max_runs, shutdown_grace_seconds)
    stop_event = stop_event or threading.Event()
    specs = _loop_specs()
    statuses = {name: "starting" for name, _, _ in specs}
    statuses_lock = threading.Lock()
    threads = tuple(
        threading.Thread(
            name=f"foundry-worker-{name}",
            target=_thread_target,
            args=(
                name,
                interval,
                callback,
                stop_event,
                max_runs,
                statuses,
                statuses_lock,
            ),
            daemon=True,
        )
        for name, interval, callback in specs
    )
    failure: FoundryWorkerError | None = None
    started_threads: list[threading.Thread] = []
    try:
        for thread in threads:
            thread.start()
            started_threads.append(thread)
        while True:
            with statuses_lock:
                failed = [
                    name for name, status in statuses.items() if status == "failed"
                ]
                completed = all(status == "completed" for status in statuses.values())
            if failed:
                failure = FoundryWorkerError(f"worker loop exited: {', '.join(failed)}")
                stop_event.set()
                break
            if completed:
                break
            if stop_event.is_set():
                break
            stop_event.wait(SUPERVISOR_POLL_SECONDS)
    except BaseException:
        stop_event.set()
        raise
    finally:
        if failure is not None or stop_event.is_set():
            stop_event.set()
            if not _join_until(tuple(started_threads), float(shutdown_grace_seconds)):
                if failure is None:
                    failure = FoundryWorkerError(
                        "worker shutdown exceeded the shared grace period"
                    )
                else:
                    failure = FoundryWorkerError(
                        f"{failure}; shutdown exceeded the shared grace period"
                    )
    if failure is not None:
        raise failure
