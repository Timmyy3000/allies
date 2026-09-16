"""Prove cancelled profile launches remain owned until verified cleanup."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import threading
from pathlib import Path

import allies_profile_sandbox as sandbox

PROFILE_KEY = "ally-v1-" + ("a" * 32)


def _drop_instance_override(instance: object, name: str) -> None:
    if name in getattr(instance, "__dict__", {}):
        delattr(instance, name)


async def _check_cancellation_boundary() -> None:
    profile_root = Path(tempfile.mkdtemp(prefix="allies-sandbox-cancel-profile-"))
    home = profile_root / "home"
    workspace = home / "workspace"
    home.mkdir()
    workspace.mkdir()

    manager = sandbox.ProfileSandboxManager(object())
    original_home = sandbox._safe_profile_home
    original_scan = sandbox._validate_profile_hardlinks
    original_terminate = sandbox._terminate_process
    readiness_gate = threading.Event()
    readiness_started = threading.Event()
    loop = asyncio.get_running_loop()

    def wait_ready(_fd: int, _process: object) -> bool:
        loop.call_soon_threadsafe(readiness_started.set)
        readiness_gate.wait(5)
        return False

    sandbox._safe_profile_home = lambda _key: home
    sandbox._validate_profile_hardlinks = lambda *args, **kwargs: None
    sandbox._terminate_process = lambda _process, _timeout: False
    manager.preflight = lambda: True
    manager._validate_profile = lambda _home: workspace
    manager._managed_signature = lambda _home: ("synthetic",)
    manager._validate_bridge = lambda: Path("/tmp/synthetic-publication.sock")
    manager._command = lambda *args: (
        ["/bin/sleep", "300"],
        {"PATH": "/usr/bin:/bin"},
    )
    manager._wait_ready = wait_ready

    task: asyncio.Task | None = None
    state = None
    try:
        task = asyncio.create_task(manager.ensure(PROFILE_KEY))
        assert await asyncio.to_thread(readiness_started.wait, 5), (
            "worker readiness did not start"
        )
        task.cancel()
        readiness_gate.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("ensure cancellation was swallowed")

        state = manager._processes.get(PROFILE_KEY)
        assert state is not None, "cancelled launch lost process ownership"
        assert not getattr(state, "ready", False), "cancelled launch became ready"
        assert manager.profile_process_count(PROFILE_KEY) == 1
        assert manager.profile_process_count() == 1
        assert state.process.poll() is None, "failed stop unexpectedly reaped worker"

        assert not await manager.stop_profile(PROFILE_KEY, timeout=0.2), (
            "injected failed stop reported success"
        )
        assert manager.profile_process_count(PROFILE_KEY) == 1, (
            "failed stop dropped process ownership"
        )

        sandbox._terminate_process = original_terminate
        assert await manager.stop_profile(PROFILE_KEY, timeout=2), (
            "verified worker stop failed"
        )
        assert manager.profile_process_count(PROFILE_KEY) == 0
        assert state.process.poll() is not None, "worker remained alive after stop"
        assert not state.listener_path.exists(), "listener path was orphaned"
        assert not state.temp_dir.exists(), "sandbox temp directory was orphaned"
    finally:
        readiness_gate.set()
        sandbox._terminate_process = original_terminate
        sandbox._safe_profile_home = original_home
        sandbox._validate_profile_hardlinks = original_scan
        if manager.profile_process_count(PROFILE_KEY):
            await manager.stop_profile(PROFILE_KEY, timeout=2)
        _drop_instance_override(manager, "preflight")
        _drop_instance_override(manager, "_validate_profile")
        _drop_instance_override(manager, "_managed_signature")
        _drop_instance_override(manager, "_validate_bridge")
        _drop_instance_override(manager, "_command")
        _drop_instance_override(manager, "_wait_ready")
        if task is not None and not task.done():
            task.cancel()
        shutil.rmtree(profile_root, ignore_errors=True)


def main() -> None:
    asyncio.run(_check_cancellation_boundary())
    print("Sandbox cancellation ownership and verified cleanup passed.")


if __name__ == "__main__":
    main()
