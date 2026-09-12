"""Profile-owned closure for the pinned Hermes API adapter."""

from __future__ import annotations

import asyncio
import gc
import hmac
import json
import math
import os
import re
import shutil
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from uuid import UUID, uuid4

from aiohttp import web

KEY = re.compile(r"ally-v1-[0-9a-f]{32}")
IDENTITY = {
    "version",
    "operation_id",
    "attempt_id",
    "lifecycle_epoch",
    "request_digest",
    "machine_generation",
    "runtime_start_epoch",
    "hermes_instance_id",
}
DRAIN_SECONDS = 20


def profiles_root():
    from hermes_cli.profiles import _get_profiles_root

    root = _get_profiles_root()
    if root.is_symlink():
        raise ValueError("unsafe_profiles_root")
    return root.resolve()


def current_profile_key():
    from hermes_constants import get_hermes_home

    home = get_hermes_home().resolve()
    return home.name if home.parent == profiles_root() else ""


class ClosurePending(RuntimeError):
    pass


class ProfileDeletionManager:
    def __init__(self, adapter):
        self.adapter = adapter
        self.instance_id = str(uuid4())
        self.lock = threading.RLock()
        self.runs = Counter()
        self.requests = defaultdict(set)
        self.agents = defaultdict(dict)
        self.task_ids = defaultdict(set)
        self.run_owners = {}
        self.jobs = {}

    def marker(self, key):
        if not KEY.fullmatch(key):
            raise ValueError("invalid_profile_key")
        path = profiles_root() / ".allies-profile-tombstones" / f"{key}.json"
        if (
            path.is_symlink()
            or path.parent.is_symlink()
            or profiles_root().is_symlink()
        ):
            raise ValueError("unsafe_profile_fence")
        if not path.exists():
            return None
        if not path.is_file() or path.stat().st_size > 16384:
            raise ValueError("invalid_profile_fence")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("profile_key") != key:
            raise ValueError("invalid_profile_fence")
        return value

    def admit(self, key):
        if key and KEY.fullmatch(key) and self.marker(key) is not None:
            raise ClosurePending("profile_deletion_pending")

    def check_home(self, home):
        resolved = Path(home).resolve()
        if resolved.parent == profiles_root():
            self.admit(resolved.name)

    def check_current_home(self):
        self.admit(current_profile_key())

    def start(self, key, coroutine):
        key = key or current_profile_key()
        try:
            self.admit(key)
        except BaseException:
            coroutine.close()
            raise
        task = asyncio.create_task(coroutine)
        self.requests[key].add(task)

        def completed(finished):
            self.requests[key].discard(finished)
            if not finished.cancelled():
                finished.exception()

        task.add_done_callback(completed)

        async def observe():
            return await asyncio.shield(task)

        return asyncio.create_task(observe())

    async def handle(self, key, request, handler):
        if not request.match_info.get("profile") and (
            request.match_info.get("profile_key") or request.path == "/v1/capabilities"
        ):
            return await handler(request)
        key = key or current_profile_key()
        run_id = request.match_info.get("run_id")
        if run_id and run_id in self.run_owners and self.run_owners[run_id] != key:
            return web.json_response({"error": {"code": "run_not_found"}}, status=404)
        if not key:
            return await handler(request)
        try:
            task = self.start(key, handler(request))
        except (ClosurePending, ValueError, OSError, json.JSONDecodeError):
            return web.json_response(
                {"error": {"code": "profile_deletion_pending"}}, status=409
            )
        return await asyncio.shield(task)

    async def run_sync(self, key, callback):
        key = key or current_profile_key()
        self.admit(key)
        with self.lock:
            self.runs[key] += 1

        def execute():
            try:
                return callback()
            finally:
                with self.lock:
                    self.runs[key] -= 1

        try:
            future = asyncio.get_running_loop().run_in_executor(None, execute)
        except BaseException:
            with self.lock:
                self.runs[key] -= 1
            raise
        return await asyncio.shield(future)

    def track_agent(self, agent):
        key = current_profile_key()
        if not key:
            return
        with self.lock:
            self.agents[key][id(agent)] = agent
            agent._allies_profile_key = key

    def track_run(self, run_id):
        self.run_owners[run_id] = current_profile_key()

    def erase_runs(self, key):
        owned = [run_id for run_id, owner in self.run_owners.items() if owner == key]
        for run_id in owned:
            task = self.adapter._active_run_tasks.get(run_id)
            if (
                (task is not None and not task.done())
                or run_id in self.adapter._run_stream_subscribers
                or run_id in self.adapter._active_run_agents
            ):
                raise ClosurePending("run_transport_pending")
        for run_id in owned:
            for name in (
                "_run_streams",
                "_run_streams_created",
                "_run_statuses",
                "_run_approval_sessions",
                "_active_run_tasks",
                "_active_run_agents",
            ):
                getattr(self.adapter, name).pop(run_id, None)
            self.adapter._stopping_run_ids.discard(run_id)
            self.run_owners.pop(run_id, None)

    def retire_agent(self, agent):
        key = getattr(agent, "_allies_profile_key", "")
        if not key:
            return
        task_id = getattr(agent, "_gateway_turn_process_task_id", None) or getattr(
            agent, "session_id", None
        )
        with self.lock:
            if task_id:
                self.task_ids[key].add(task_id)
        try:
            if any(
                thread.is_alive()
                for thread in getattr(agent, "_allies_background_threads", ())
            ):
                return
            if (getattr(agent, "_request_client_cache", None) or {}).get("in_use"):
                return
            with agent._active_children_lock:
                if agent._active_children:
                    return
            for reaper in getattr(agent, "_allies_reapers", ()):
                reaper.join(timeout=0.1)
                if reaper.is_alive():
                    return
            manager = getattr(agent, "_memory_manager", None)
            if manager is not None:
                manager.shutdown_all(checked=True)
            compressor = getattr(agent, "context_compressor", None)
            if compressor is not None:
                compressor.on_session_end(getattr(agent, "session_id", "") or "", [])
            agent.close(checked=True, preserve_task_resources=True)
        except Exception:  # noqa: BLE001 -- retain ownership on any provider failure.
            return
        with self.lock:
            self.agents[key].pop(id(agent), None)

    def _validate_request(self, key, body):
        if (
            set(body) != IDENTITY
            or type(body["version"]) is not int
            or body["version"] != 1
        ):
            raise ValueError("invalid_quiescence_request")
        for name in ("operation_id", "attempt_id", "hermes_instance_id"):
            if not isinstance(body[name], str) or str(UUID(body[name])) != body[name]:
                raise TypeError("invalid_quiescence_request")
        for name in ("lifecycle_epoch", "machine_generation", "runtime_start_epoch"):
            if type(body[name]) is not int or body[name] < (
                1 if name == "machine_generation" else 0
            ):
                raise ValueError("invalid_quiescence_request")
        if not isinstance(body["request_digest"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", body["request_digest"]
        ):
            raise ValueError("invalid_quiescence_request")
        if body["hermes_instance_id"] != self.instance_id:
            raise ClosurePending("stale_hermes_instance")
        marker = self.marker(key)
        if marker is None:
            raise ClosurePending("profile_fence_missing")
        if (
            marker.get("schema") != "allies.profile"
            or marker.get("schema_version") != 2
        ):
            raise ClosurePending("invalid_profile_fence")
        if marker.get("deleted") is True:
            if (
                set(marker)
                != {"schema", "schema_version", "profile_key", "status", "deleted"}
                or marker.get("status") != "DEPROVISIONED"
            ):
                raise ClosurePending("invalid_terminal_fence")
            if (profiles_root() / key).exists():
                raise ClosurePending("terminal_profile_reappeared")
            return
        if marker.get("status") != "CLEANUP_PENDING":
            raise ClosurePending("cleanup_attempt_not_pending")
        for name in ("operation_id", "attempt_id", "lifecycle_epoch", "request_digest"):
            if marker.get(name) != body[name]:
                raise ClosurePending("stale_cleanup_attempt")
        expires = marker["expires_at"]
        if (
            type(expires) not in (int, float)
            or not math.isfinite(expires)
            or expires <= time.time()
        ):
            raise ClosurePending("cleanup_attempt_expired")

    async def endpoint(self, request):
        token = request.headers.get("Authorization", "")
        expected = self.adapter._api_key
        if (
            request.match_info.get("profile")
            or not expected
            or not hmac.compare_digest(token.encode(), f"Bearer {expected}".encode())
        ):
            return web.json_response(
                {"error": {"code": "invalid_control_credential"}}, status=401
            )
        key = request.match_info.get("profile_key", "")
        try:
            if request.content_length is not None and request.content_length > 2048:
                raise ValueError("invalid_quiescence_request")
            body = await request.json()
            if not isinstance(body, dict):
                raise TypeError("invalid_quiescence_request")
            self._validate_request(key, body)
        except ClosurePending:
            return web.json_response(
                {"error": {"code": "stale_cleanup_attempt"}}, status=409
            )
        except (ValueError, KeyError, TypeError, OSError):
            return web.json_response(
                {"error": {"code": "invalid_quiescence_request"}}, status=422
            )
        identity = (body["attempt_id"], body["lifecycle_epoch"], body["request_digest"])
        previous = self.jobs.get(key)
        if previous is None or previous[0] != identity:
            if previous is not None and not previous[1].done():
                return web.json_response(
                    self._proof(key, body, "quiescing", "previous_cleanup_pending"),
                    status=202,
                )
            job = asyncio.create_task(self._close(key))
            self.jobs[key] = (identity, job)
        else:
            job = previous[1]
        try:
            state, code = await asyncio.wait_for(asyncio.shield(job), 25.0)
        except TimeoutError:
            state, code = "quiescing", "profile_cleanup_pending"
        if state == "quiescing" and job.done():
            self.jobs.pop(key, None)
        return web.json_response(
            self._proof(key, body, state, code),
            status=200 if state == "quiesced" else 202,
        )

    def _proof(self, key, body, state, code):
        with self.lock:
            runs = self.runs[key]
            agents = len(self.agents[key])
        return {
            **body,
            "profile_key": key,
            "state": state,
            "safe_error_code": code,
            "active_runs": runs,
            "active_profile_io": len(self.requests[key]),
            "open_profile_stores": 0 if state == "quiesced" else agents,
            "owned_children": 0 if state == "quiesced" else agents,
        }

    async def _close(self, key):
        with self.lock:
            agents = list(self.agents[key].values())
        for agent in agents:
            try:
                agent.interrupt("profile deletion")
            except Exception:  # noqa: BLE001 -- failed interruption cannot prove closure.
                return "repair_required", "agent_interrupt_failed"
        deadline = time.monotonic() + DRAIN_SECONDS
        while self.runs[key] or self.requests[key]:
            if time.monotonic() >= deadline:
                return "quiescing", "profile_work_pending"
            await asyncio.sleep(0.05)
        while self.agents[key]:
            for agent in list(self.agents[key].values()):
                await asyncio.to_thread(self.retire_agent, agent)
            if not self.agents[key]:
                break
            if time.monotonic() >= deadline:
                return "quiescing", "agent_resources_unclosed"
            await asyncio.sleep(0.05)
        try:
            task_ids = await asyncio.to_thread(self._owned_task_ids, key)
            for task_id in task_ids:
                await asyncio.to_thread(_close_task, task_id)
            self._erase_responses(key, task_ids)
            self.erase_runs(key)
            home = profiles_root() / key
            for cached_home, database in list(
                getattr(self.adapter, "_session_dbs", {}).items()
            ):
                if Path(cached_home).resolve() == home:
                    await asyncio.to_thread(_close_session_database, database)
                    self.adapter._session_dbs.pop(cached_home, None)
            with self.lock:
                self.task_ids.pop(key, None)
            # SQLite extension cycles can retain already-unreferenced connections.
            gc.collect()
            for descriptor in Path("/proc/self/fd").iterdir():
                try:
                    destination = os.readlink(descriptor)
                except FileNotFoundError:
                    continue
                if destination == str(home) or destination.startswith(str(home) + "/"):
                    raise ClosurePending("profile_descriptor_unclosed")
            return "quiesced", ""
        except Exception:  # noqa: BLE001 -- unknown resource errors fail closed.
            return "repair_required", "profile_resources_unclosed"

    def _owned_task_ids(self, key):
        with self.lock:
            task_ids = set(self.task_ids[key])
            sibling_ids = set()
            for owner, identifiers in self.task_ids.items():
                if owner != key:
                    sibling_ids.update(identifiers)
            for owner, agents in self.agents.items():
                if owner != key:
                    for agent in agents.values():
                        sibling_ids.add(
                            getattr(agent, "_gateway_turn_process_task_id", None)
                            or getattr(agent, "session_id", None)
                        )
        target = profiles_root() / key / "state.db"
        if target.parent.is_symlink():
            raise ClosurePending("unsafe_profile_directory")
        task_ids.update(_session_ids(target))
        if task_ids.intersection(sibling_ids):
            raise ClosurePending("shared_task_ownership")
        siblings = list(profiles_root().iterdir())
        if len(siblings) > 1024 or len(task_ids) > 10000:
            raise ClosurePending("profile_inventory_limit")
        for sibling in siblings:
            if (
                sibling.name != key
                and sibling.is_dir()
                and not sibling.name.startswith(".")
            ):
                identifiers = _session_ids(sibling / "state.db")
                if task_ids.intersection(identifiers):
                    raise ClosurePending("shared_task_ownership")
                sibling_ids.update(identifiers)
        from tools.process_registry import process_registry

        with process_registry._lock:
            for session in (
                *process_registry._running.values(),
                *process_registry._finished.values(),
            ):
                if session.task_id not in task_ids | sibling_ids:
                    raise ClosurePending("process_ownership_unverified")
        return task_ids

    def _erase_responses(self, key, task_ids):
        store = self.adapter._response_store
        rows = store._conn.execute("SELECT response_id, data FROM responses").fetchmany(
            10001
        )
        if len(rows) > 10000:
            raise ClosurePending("response_inventory_limit")
        owned = []
        for response_id, encoded in rows:
            data = json.loads(encoded)
            owner = data.get("allies_profile_key")
            if owner == key or (owner is None and data.get("session_id") in task_ids):
                owned.append(response_id)
            elif owner is None and not data.get("session_id"):
                raise ClosurePending("legacy_response_ownership")
        for response_id in owned:
            store.delete(response_id)


def _close_session_database(database):
    database._stop_token_writer(join_timeout=1)
    with database._token_queue_cond:
        thread = database._token_writer_thread
        if (
            (thread is not None and thread.is_alive())
            or database._token_writer_busy
            or database._token_queue
        ):
            raise ClosurePending("session_writer_pending")
    with database._read_conns_lock:
        database._read_conns_closed = True
        for connection in list(database._read_conns):
            connection.close()
            database._read_conns.remove(connection)
    database.close()
    if database._conn is not None:
        raise ClosurePending("session_store_unclosed")


def _session_ids(path):
    if path.is_symlink():
        raise ClosurePending("unsafe_session_store")
    if not path.exists():
        return set()
    database = sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1
    )
    try:
        rows = database.execute("SELECT id FROM sessions LIMIT 10001").fetchall()
        if len(rows) > 10000:
            raise ClosurePending("session_inventory_limit")
        return {row[0] for row in rows}
    finally:
        database.close()


def _close_task(task_id):
    if not isinstance(task_id, str) or not task_id:
        raise ClosurePending("unknown_task_owner")
    from tools.process_registry import CHECKPOINT_PATH, process_registry

    process_registry.kill_all(task_id=task_id, source="profile_deletion")
    if process_registry.snapshot_running_ids(task_id=task_id):
        raise ClosurePending("owned_processes_pending")
    from tools.environments.local import LocalEnvironment
    from tools.terminal_tool import cleanup_vm, get_active_env

    with process_registry._lock:
        sessions = [
            session
            for session in process_registry._finished.values()
            if session.task_id == task_id
        ]
    for session in sessions:
        if session._reader_thread is not None:
            session._reader_thread.join(timeout=1)
            if session._reader_thread.is_alive():
                raise ClosurePending("process_reader_pending")
        if session.env_ref is not None:
            if not isinstance(session.env_ref, LocalEnvironment) or not re.fullmatch(
                r"proc_[0-9a-f]{12}", session.id
            ):
                raise ClosurePending("process_spool_unverified")
            spool = Path(process_registry._env_temp_dir(session.env_ref))
            if spool.is_symlink():
                raise ClosurePending("unsafe_process_spool")
            for suffix in ("log", "pid", "exit"):
                (spool / f"hermes_bg_{session.id}.{suffix}").unlink(missing_ok=True)

    env = get_active_env(task_id)
    if env is not None and not isinstance(env, LocalEnvironment):
        raise ClosurePending("environment_cleanup_unverified")
    paths = [] if env is None else [Path(env._snapshot_path), Path(env._cwd_file)]
    cleanup_vm(task_id)
    if get_active_env(task_id) is not None or any(path.exists() for path in paths):
        raise ClosurePending("terminal_cleanup_unverified")
    _close_browser(task_id)
    from tools.computer_use import release_computer_use_session

    release_computer_use_session(task_id, checked=True)
    owned_ids = {session.id for session in sessions}
    queue = process_registry.completion_queue
    with queue.mutex:
        retained = [
            item for item in queue.queue if item.get("session_id") not in owned_ids
        ]
        queue.queue.clear()
        queue.queue.extend(retained)
    with process_registry._lock:
        process_registry.pending_watchers[:] = [
            item
            for item in process_registry.pending_watchers
            if item.get("session_id") not in owned_ids
        ]
        for session_id, session in list(process_registry._finished.items()):
            if session.task_id == task_id:
                process_registry._finished.pop(session_id)
                process_registry._completion_consumed.discard(session_id)
                process_registry._poll_observed.discard(session_id)
    process_registry._write_checkpoint()
    if CHECKPOINT_PATH.is_symlink():
        raise ClosurePending("unsafe_process_checkpoint")
    if CHECKPOINT_PATH.exists():
        entries = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
        if not isinstance(entries, list) or any(
            not isinstance(entry, dict) or entry.get("task_id") == task_id
            for entry in entries
        ):
            raise ClosurePending("process_checkpoint_unclosed")


def _close_browser(task_id):
    from tools import browser_camofox as camofox
    from tools import browser_tool as browser

    with camofox._sessions_lock:
        if task_id in camofox._sessions or browser._is_camofox_mode():
            raise ClosurePending("external_browser_cleanup_unverified")
    # A restart loses ownership; an orphan PID file cannot restore it.
    with browser._cleanup_lock:
        known = {
            f"agent-browser-{info.get('session_name', '')}"
            for info in browser._active_sessions.values()
        }
    for directory in Path(browser._socket_safe_tmpdir()).glob("agent-browser-*"):
        if directory.name not in known:
            raise ClosurePending("browser_ownership_unverified")

    for session_key in (task_id, f"{task_id}::local"):
        with browser._cleanup_lock:
            info = browser._active_sessions.get(session_key)
        if info is None:
            continue
        name = info.get("session_name", "")
        if not info.get("features", {}).get("local") or not re.fullmatch(
            r"h_[0-9a-f]{10}", name
        ):
            raise ClosurePending("browser_cleanup_unverified")
        result = browser._run_browser_command(session_key, "close", [], timeout=10)
        if not isinstance(result, dict) or result.get("success") is not True:
            raise ClosurePending("browser_close_failed")
        directory = Path(browser._socket_safe_tmpdir()) / f"agent-browser-{name}"
        if directory.is_symlink():
            raise ClosurePending("unsafe_browser_directory")
        pid_file = directory / f"{name}.pid"
        if pid_file.exists():
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise ClosurePending("browser_daemon_pending")
        if directory.exists():
            shutil.rmtree(directory)
        with browser._cleanup_lock:
            browser._active_sessions.pop(session_key, None)
            browser._session_last_activity.pop(session_key, None)
        browser._last_active_session_key.pop(task_id, None)
