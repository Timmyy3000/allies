"""Exercise deletion against the pinned adapter, real threads and SQLite stores."""

from __future__ import annotations

import asyncio
import gc
import json
import os
import shutil
import sqlite3
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import allies_profile_deletion as deletion
from agent.memory_manager import MemoryManager
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from allies_mnemosyne import AlliesMnemosyneProvider
from gateway.config import GatewayConfig, PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from hermes_state import SessionDB
from run_agent import AIAgent

TARGET = "ally-v1-" + "1" * 32
SIBLING = "ally-v1-" + "2" * 32
CONTROL = "synthetic-process-control-secret"


def seed(root, key):
    home = root / "profiles" / key
    home.mkdir(parents=True)
    (home / ".env").write_text("API_SERVER_KEY=synthetic-profile-secret\n")
    database = SessionDB(home / "state.db")
    database.create_session(key, "api_server")
    database.append_message(key, "user", "synthetic private history")
    database.close()
    return home


def adapter_app():
    adapter = APIServerAdapter(PlatformConfig(extra={"key": CONTROL}))
    adapter.gateway_runner = SimpleNamespace(
        config=GatewayConfig(multiplex_profiles=True)
    )
    app = web.Application(middlewares=[adapter._make_profile_prefix_middleware()])
    for method, path, handler in adapter._http_route_table():
        app.router.add_route(method, path, handler)
        app.router.add_route(method, f"/p/{{profile}}{path}", handler)
    return adapter, app


def check_agent_closure(adapter, target):
    """Use the real agent/manager/provider close path without making an LLM call."""
    memory = sqlite3.connect(target / "memory-smoke.db", check_same_thread=False)
    memory.execute("CREATE TABLE private_memory (value TEXT)")
    memory.execute("INSERT INTO private_memory VALUES ('synthetic')")
    memory.commit()
    provider = AlliesMnemosyneProvider()
    provider._db_path = target / "memory-smoke.db"
    provider._delegate = SimpleNamespace(shutdown=memory.close)
    agent = AIAgent.__new__(AIAgent)
    agent.session_id = TARGET
    agent._active_children_lock = threading.RLock()
    agent._active_children = []
    agent._memory_manager = MemoryManager()
    agent._memory_manager._providers.append(provider)
    agent.client = sqlite3.connect(":memory:")
    client = agent.client
    release = threading.Event()
    thread = threading.Thread(target=release.wait, args=(10,), daemon=True)
    agent._allies_background_threads = [thread]
    thread.start()
    with adapter._profile_scope(TARGET):
        adapter._allies_deletion.track_agent(agent)
    try:
        adapter._allies_deletion.retire_agent(agent)
        assert id(agent) in adapter._allies_deletion.agents[TARGET]
        assert memory.execute("SELECT count(*) FROM private_memory").fetchone()[0] == 1
    finally:
        release.set()
        thread.join()

    # Checked provider errors must retain both provider and agent for retry.
    def failed_close():
        raise RuntimeError("synthetic close failure")

    provider._delegate.shutdown = failed_close
    adapter._allies_deletion.retire_agent(agent)
    assert id(agent) in adapter._allies_deletion.agents[TARGET]
    assert provider._delegate is not None
    provider._delegate.shutdown = memory.close
    adapter._allies_deletion.retire_agent(agent)
    assert id(agent) not in adapter._allies_deletion.agents[TARGET]
    for connection in (memory, client):
        try:
            connection.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            pass
        else:
            raise AssertionError("checked close retained an open connection")


async def check_real_mnemosyne(target, sibling):
    provider = AlliesMnemosyneProvider()
    provider.initialize(
        "smoke-memory",
        hermes_home=str(target),
        profile_root=str(target),
        agent_identity=TARGET,
        agent_context="conversation",
        memory_mode="context_only",
        tools=[],
    )
    assert provider.status()["available"] is True, provider.status()
    beam_connection = provider._delegate._beam.conn
    audit_connection = provider._delegate._audit._conn
    sibling_provider = AlliesMnemosyneProvider()
    sibling_provider.initialize(
        "smoke-sibling-memory",
        hermes_home=str(sibling),
        profile_root=str(sibling),
        agent_identity=SIBLING,
        agent_context="conversation",
        memory_mode="context_only",
        tools=[],
    )
    assert sibling_provider.status()["available"] is True
    from mnemosyne.core.llm_backends import get_host_llm_backend
    from mnemosyne_hermes.hermes_llm_adapter import register_hermes_host_llm

    assert register_hermes_host_llm()
    shared_backend = get_host_llm_backend()
    assert beam_connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    await asyncio.to_thread(provider.shutdown_checked)
    assert get_host_llm_backend() is shared_backend, (
        "closing one profile removed its sibling's model routing"
    )
    assert sibling_provider._delegate._beam.conn.execute("SELECT 1").fetchone()[0] == 1
    for connection in (beam_connection, audit_connection):
        try:
            connection.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            pass
        else:
            raise AssertionError("installed Mnemosyne retained an open store")
    gc.collect()
    for descriptor in Path("/proc/self/fd").iterdir():
        try:
            destination = os.readlink(descriptor)
        except FileNotFoundError:
            continue
        assert not destination.startswith(str(target) + "/"), (
            f"installed memory retained a profile file descriptor: {Path(destination).name}"
        )
    await asyncio.to_thread(sibling_provider.shutdown_checked)
    assert get_host_llm_backend() is None


async def run():
    previous = os.environ.get("HERMES_HOME")
    deletion.DRAIN_SECONDS = 0.15
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        os.environ["HERMES_HOME"] = str(root)
        target = seed(root, TARGET)
        sibling = seed(root, SIBLING)
        adapter, app = adapter_app()
        manager = adapter._allies_deletion
        await check_real_mnemosyne(target, sibling)
        check_agent_closure(adapter, target)
        manager.task_ids[SIBLING].add(TARGET)
        try:
            manager._owned_task_ids(TARGET)
        except deletion.ClosurePending:
            pass
        else:
            raise AssertionError("an unpersisted sibling task collision was accepted")
        manager.task_ids[SIBLING].remove(TARGET)
        from tools import browser_tool

        orphan = Path(browser_tool._socket_safe_tmpdir()) / "agent-browser-h_0123456789"
        orphan.mkdir()
        try:
            try:
                deletion._close_browser(TARGET)
            except deletion.ClosurePending:
                pass
            else:
                raise AssertionError("unknown browser ownership was accepted")
        finally:
            orphan.rmdir()
        from tools.process_registry import process_registry

        target_process = process_registry.spawn_local(
            "sleep 30", cwd=str(target), task_id=TARGET
        )
        sibling_process = process_registry.spawn_local(
            "sleep 30", cwd=str(sibling), task_id=SIBLING
        )
        with process_registry._lock:
            target_process.task_id = "synthetic-lost-owner"
        try:
            manager._owned_task_ids(TARGET)
        except deletion.ClosurePending:
            pass
        else:
            raise AssertionError("a process with lost ownership was accepted")
        finally:
            with process_registry._lock:
                target_process.task_id = TARGET
        target_db = adapter._open_and_cache_session_db(target)
        target_connection = target_db._conn
        sibling_db = adapter._open_and_cache_session_db(sibling)
        for key in (TARGET, SIBLING):
            with adapter._profile_scope(key):
                adapter._response_store.put(
                    key, {"session_id": key, "output": "synthetic"}
                )
                manager.track_run(key)
                adapter._run_statuses[key] = {"output": "synthetic run history"}
                adapter._run_streams[key] = asyncio.Queue()
                adapter._run_streams[key].put_nowait(
                    {"output": "synthetic queued delta"}
                )
        body = {
            "version": 1,
            "operation_id": str(uuid4()),
            "attempt_id": str(uuid4()),
            "lifecycle_epoch": 2,
            "request_digest": "a" * 64,
            "machine_generation": 1,
            "runtime_start_epoch": 1,
            "hermes_instance_id": manager.instance_id,
        }
        release = threading.Event()
        started = threading.Event()

        def actual_worker():
            started.set()
            release.wait(10)

        with adapter._profile_scope(TARGET):
            wrapper = asyncio.create_task(manager.run_sync(None, actual_worker))
        while not started.is_set():
            await asyncio.sleep(0.01)
        wrapper.cancel()
        try:
            await wrapper
        except asyncio.CancelledError:
            pass
        assert manager.runs[TARGET] == 1, "cancelled wrapper hid a live worker"
        marker_dir = root / "profiles" / ".allies-profile-tombstones"
        marker_dir.mkdir()
        marker_path = marker_dir / f"{TARGET}.json"
        marker = {
            name: body[name]
            for name in (
                "operation_id",
                "attempt_id",
                "lifecycle_epoch",
                "request_digest",
            )
        }
        marker.update(
            schema="allies.profile",
            schema_version=2,
            profile_key=TARGET,
            status="CLEANUP_PENDING",
            receipt_id="cr-smoke",
            expires_at=(datetime.now(UTC) + timedelta(hours=1)).timestamp(),
        )
        marker_path.write_text(json.dumps(marker))
        path = f"/v1/profiles/{TARGET}/quiesce"
        headers = {"Authorization": f"Bearer {CONTROL}"}
        try:
            async with TestClient(TestServer(app)) as client:
                capabilities = await client.get("/v1/capabilities", headers=headers)
                advertised = await capabilities.json()
                assert advertised["profile_quiescence_v1"] is True
                assert advertised["hermes_instance_id"] == manager.instance_id
                wrong = await client.post(
                    path,
                    json=body,
                    headers={"Authorization": "Bearer synthetic-profile-secret"},
                )
                assert wrong.status == 401
                stale = await client.post(
                    path,
                    json={**body, "hermes_instance_id": str(uuid4())},
                    headers=headers,
                )
                assert stale.status == 409
                malformed = await client.post(
                    path, json={**body, "extra": True}, headers=headers
                )
                assert malformed.status == 422
                pending = await client.post(path, json=body, headers=headers)
                proof = await pending.json()
                assert pending.status == 202 and proof["state"] == "quiescing", proof
                assert proof["active_runs"] == 1, proof
                blocked = await client.get(f"/p/{TARGET}/health")
                assert blocked.status == 409
                alive = await client.get(f"/p/{SIBLING}/health")
                assert alive.status == 200, await alive.text()
                release.set()
                while manager.runs[TARGET]:
                    await asyncio.sleep(0.01)
                completed = await client.post(path, json=body, headers=headers)
                proof = await completed.json()
                assert completed.status == 200 and proof["state"] == "quiesced", proof
                assert all(
                    proof[name] == 0
                    for name in (
                        "active_runs",
                        "active_profile_io",
                        "open_profile_stores",
                        "owned_children",
                    )
                ), proof
                assert str(target) not in adapter._session_dbs
                assert str(sibling) in adapter._session_dbs
                assert adapter._response_store.get(TARGET) is None
                assert adapter._response_store.get(SIBLING) is not None
                assert TARGET not in adapter._run_statuses
                assert TARGET not in adapter._run_streams
                assert SIBLING in adapter._run_statuses
                assert SIBLING in adapter._run_streams
                assert process_registry.get(target_process.id) is None
                assert sibling_process.id in process_registry.snapshot_running_ids(
                    SIBLING
                )
                assert sibling_db.get_session(SIBLING) is not None
                try:
                    target_connection.execute("SELECT 1")
                except sqlite3.ProgrammingError:
                    pass
                else:
                    raise AssertionError("target SQLite handle remained open")
            shutil.rmtree(target)
            marker_path.write_text(
                json.dumps(
                    {
                        "schema": "allies.profile",
                        "schema_version": 2,
                        "profile_key": TARGET,
                        "status": "DEPROVISIONED",
                        "deleted": True,
                    }
                )
            )
            restarted, restarted_app = adapter_app()
            async with TestClient(TestServer(restarted_app)) as client:
                stale = await client.post(path, json=body, headers=headers)
                assert stale.status == 409
                fresh = await client.post(
                    path,
                    json={
                        **body,
                        "hermes_instance_id": restarted._allies_deletion.instance_id,
                    },
                    headers=headers,
                )
                assert fresh.status == 200, await fresh.text()
            restarted._response_store.close()
        finally:
            release.set()
            process_registry.kill_all(task_id=SIBLING, source="synthetic_smoke_cleanup")
            sibling_db.close()
            adapter._response_store.close()
    if previous is None:
        os.environ.pop("HERMES_HOME", None)
    else:
        os.environ["HERMES_HOME"] = previous
    print(
        "Profile quiescence: real worker cancellation, stores, fences, sibling and restart passed"
    )


if __name__ == "__main__":
    asyncio.run(run())
