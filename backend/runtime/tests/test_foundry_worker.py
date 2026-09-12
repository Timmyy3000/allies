from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command


@pytest.fixture
def quiet_worker(monkeypatch):
    from runtime.services import foundry_worker

    monkeypatch.setattr(foundry_worker, "close_old_connections", lambda: None)
    monkeypatch.setattr(foundry_worker.connection, "close", lambda: None)
    return foundry_worker


def test_finite_run_executes_each_fixed_loop_once(quiet_worker, monkeypatch):
    calls = []
    monkeypatch.setattr(
        quiet_worker,
        "publish_pending_event_deliveries",
        lambda **kwargs: calls.append("event"),
    )
    monkeypatch.setattr(
        quiet_worker,
        "publish_due_profile_readiness_hints",
        lambda **kwargs: calls.append("hints"),
    )
    monkeypatch.setattr(
        quiet_worker,
        "_power_publication_pass",
        lambda cursor=None: calls.append("power-publication") or cursor,
    )
    monkeypatch.setattr(
        quiet_worker, "maintain_ready_pool_once", lambda **kwargs: calls.append("pool")
    )

    quiet_worker.run_foundry_worker(max_runs=1, shutdown_grace_seconds=1)

    assert sorted(calls) == ["event", "hints", "pool", "power-publication"]


@pytest.mark.django_db(transaction=True, databases="__all__")
def test_next_pass_reopens_closed_django_connection(
    monkeypatch, tmp_path, django_db_blocker
):
    from django.db import connections
    from django.utils.connection import ConnectionProxy

    from runtime.services import foundry_worker

    database = connections.databases["default"].copy()
    database.update(
        {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(tmp_path / "worker.sqlite3"),
            "OPTIONS": {},
            "USER": "",
            "PASSWORD": "",
            "HOST": "",
            "PORT": "",
        }
    )
    monkeypatch.setitem(connections.databases, "worker_probe", database)
    raw_connections = []
    closed_connections = []

    worker_connection = ConnectionProxy(connections, "worker_probe")
    monkeypatch.setattr(foundry_worker, "connection", worker_connection)
    for constant in (
        "EVENT_INTERVAL_SECONDS",
        "HINT_INTERVAL_SECONDS",
        "POWER_INTERVAL_SECONDS",
        "POOL_INTERVAL_SECONDS",
    ):
        monkeypatch.setattr(foundry_worker, constant, 0.01)

    def read_connection(**kwargs):
        wrapper = connections["worker_probe"]
        with worker_connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone()[0] == 1
        raw_connections.append(wrapper.connection)
        if len(raw_connections) == 1:
            wrapper.close()
            closed_connections.append(wrapper.connection)

    monkeypatch.setattr(
        foundry_worker,
        "publish_pending_event_deliveries",
        read_connection,
    )
    monkeypatch.setattr(
        foundry_worker,
        "publish_due_profile_readiness_hints",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        foundry_worker,
        "_power_publication_pass",
        lambda cursor=None: cursor,
    )
    monkeypatch.setattr(
        foundry_worker,
        "maintain_ready_pool_once",
        lambda **kwargs: None,
    )

    with django_db_blocker.unblock():
        foundry_worker.run_foundry_worker(
            max_runs=2,
            shutdown_grace_seconds=1,
        )

    assert closed_connections == [None]
    assert len(raw_connections) == 2
    assert raw_connections[0] is not raw_connections[1]


def test_power_steps_are_independent(quiet_worker, monkeypatch, caplog):
    calls = []

    def fail_publication(*, limit, cursor):
        calls.append(("publication", limit, cursor))
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(quiet_worker, "wake_due_publications", fail_publication)
    monkeypatch.setattr(
        quiet_worker,
        "process_runtime_wakes",
        lambda *, limit: calls.append(("wake", limit)),
    )
    monkeypatch.setattr(
        quiet_worker,
        "cleanup_runtime_intents",
        lambda: calls.append(("cleanup", None)),
    )
    monkeypatch.setattr(
        quiet_worker,
        "stop_idle_workspaces",
        lambda *, limit: calls.append(("idle", limit)),
    )

    assert quiet_worker._power_publication_pass("saved-cursor") == "saved-cursor"

    assert calls == [
        ("publication", 20, "saved-cursor"),
        ("wake", 1),
        ("cleanup", None),
        ("idle", 1),
    ]
    assert "RuntimeError" in caplog.text


def test_one_pass_error_is_retried_without_killing_loop(quiet_worker, monkeypatch):
    calls = []

    def event_pass():
        calls.append("event")
        if len(calls) == 1:
            raise RuntimeError("temporary")

    monkeypatch.setattr(
        quiet_worker, "publish_pending_event_deliveries", lambda **kwargs: event_pass()
    )
    monkeypatch.setattr(
        quiet_worker, "publish_due_profile_readiness_hints", lambda **kwargs: None
    )
    monkeypatch.setattr(
        quiet_worker,
        "_power_publication_pass",
        lambda cursor=None: cursor,
    )
    monkeypatch.setattr(quiet_worker, "maintain_ready_pool_once", lambda **kwargs: None)

    quiet_worker.run_foundry_worker(max_runs=2, shutdown_grace_seconds=1)

    assert calls == ["event", "event"]


def test_dead_loop_fails_supervision(quiet_worker, monkeypatch):
    class LoopDied(BaseException):
        pass

    monkeypatch.setattr(
        quiet_worker,
        "publish_pending_event_deliveries",
        lambda **kwargs: (_ for _ in ()).throw(LoopDied()),
    )
    monkeypatch.setattr(
        quiet_worker, "publish_due_profile_readiness_hints", lambda **kwargs: None
    )
    monkeypatch.setattr(
        quiet_worker,
        "_power_publication_pass",
        lambda cursor=None: cursor,
    )
    monkeypatch.setattr(quiet_worker, "maintain_ready_pool_once", lambda **kwargs: None)

    with pytest.raises(quiet_worker.FoundryWorkerError, match="event"):
        quiet_worker.run_foundry_worker(shutdown_grace_seconds=1)


@pytest.mark.parametrize("blocked_loop", ["pool", "power-publication"])
def test_blocked_loop_does_not_block_sibling_progress(
    quiet_worker, monkeypatch, blocked_loop
):
    for constant in (
        "EVENT_INTERVAL_SECONDS",
        "HINT_INTERVAL_SECONDS",
        "POWER_INTERVAL_SECONDS",
        "POOL_INTERVAL_SECONDS",
    ):
        monkeypatch.setattr(quiet_worker, constant, 0.01)

    counts = {"event": 0, "hints": 0, "power-publication": 0, "pool": 0}
    blocker_started = threading.Event()
    release = threading.Event()
    stop_event = threading.Event()
    errors = []

    def event_pass(**kwargs):
        counts["event"] += 1

    def hints_pass(**kwargs):
        counts["hints"] += 1

    def normal_power(cursor=None):
        counts["power-publication"] += 1
        return cursor

    def normal_pool(**kwargs):
        counts["pool"] += 1

    def blocked_pool(**kwargs):
        blocker_started.set()
        release.wait(2)

    def blocked_power(cursor=None):
        blocker_started.set()
        release.wait(2)
        return cursor

    monkeypatch.setattr(quiet_worker, "publish_pending_event_deliveries", event_pass)
    monkeypatch.setattr(quiet_worker, "publish_due_profile_readiness_hints", hints_pass)
    monkeypatch.setattr(
        quiet_worker,
        "maintain_ready_pool_once",
        blocked_pool if blocked_loop == "pool" else normal_pool,
    )
    monkeypatch.setattr(
        quiet_worker,
        "_power_publication_pass",
        blocked_power if blocked_loop == "power-publication" else normal_power,
    )

    def run_worker():
        try:
            quiet_worker.run_foundry_worker(
                stop_event=stop_event,
                shutdown_grace_seconds=1,
            )
        except BaseException as exc:  # noqa: BLE001 - report worker failure below
            errors.append(exc)

    runner = threading.Thread(target=run_worker)
    runner.start()
    try:
        assert blocker_started.wait(1)
        siblings = [name for name in counts if name != blocked_loop]
        deadline = time.monotonic() + 1
        while any(counts[name] < 2 for name in siblings):
            if time.monotonic() >= deadline:
                pytest.fail(f"sibling progress stalled: {counts}")
            time.sleep(0.01)
        assert runner.is_alive()
    finally:
        stop_event.set()
        release.set()
        runner.join(2)

    assert not runner.is_alive()
    assert not errors


def test_command_passes_bounded_finite_options(monkeypatch):
    from runtime.management.commands import run_foundry_worker as command

    calls = []
    previous_sigint = signal.getsignal(signal.SIGINT)
    monkeypatch.setattr(
        command,
        "run_foundry_worker",
        lambda **kwargs: calls.append(kwargs),
    )

    call_command(
        "run_foundry_worker",
        "--max-runs",
        "2",
        "--shutdown-grace",
        "0",
        stdout=StringIO(),
    )

    assert len(calls) == 1
    assert calls[0]["max_runs"] == 2
    assert calls[0]["shutdown_grace_seconds"] == 0.0
    assert isinstance(calls[0]["stop_event"], threading.Event)
    assert signal.getsignal(signal.SIGINT) == previous_sigint


def test_nonreturning_pass_makes_management_command_fail_within_grace():
    worktree = Path(__file__).parents[3]
    script = """
import django
import signal
import threading
import time

django.setup()
from django.core.management import call_command
from runtime.services import foundry_worker

foundry_worker.publish_pending_event_deliveries = lambda **kwargs: None
foundry_worker.publish_due_profile_readiness_hints = lambda **kwargs: None
foundry_worker.wake_due_publications = lambda **kwargs: type('Page', (), {'next_cursor': None})()
foundry_worker.cleanup_runtime_intents = lambda: None
foundry_worker.stop_idle_workspaces = lambda **kwargs: None
foundry_worker.maintain_ready_pool_once = lambda **kwargs: None
started = threading.Event()

def block(**kwargs):
    started.set()
    time.sleep(30)

foundry_worker.process_runtime_wakes = block

def stop_when_blocked():
    if started.wait(2):
        print(f'BLOCKING_IO_STARTED {time.monotonic()}', flush=True)
    else:
        print('BLOCKING_IO_NOT_STARTED', flush=True)
    signal.raise_signal(signal.SIGINT)

trigger = threading.Thread(target=stop_when_blocked, daemon=True)
trigger.start()

call_command('run_foundry_worker', '--shutdown-grace', '0.05')
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=worktree / "backend",
        env={
            **os.environ,
            "DJANGO_DEBUG": "true",
            "DJANGO_SETTINGS_MODULE": "config.settings",
        },
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 1, result.stderr.decode()
    marker = next(
        line
        for line in result.stdout.splitlines()
        if line.startswith(b"BLOCKING_IO_STARTED ")
    )
    assert time.monotonic() - float(marker.split()[1]) < 2
