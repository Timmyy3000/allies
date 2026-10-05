"""Entrypoint for one namespace-confined profile API worker."""

from __future__ import annotations

import asyncio
import os
import signal

from allies_profile_sandbox import ProfileSandboxManager, enforce_child_workspace


async def _serve() -> int:
    connected = False
    try:
        # Hermes imports can override cwd, so reassert the workspace afterward.
        enforce_child_workspace()
        from gateway.config import PlatformConfig
        from gateway.platforms.api_server import APIServerAdapter

        enforce_child_workspace()
        api_key = os.environ.get("API_SERVER_KEY", "")
        adapter = APIServerAdapter(
            PlatformConfig(
                enabled=True,
                extra={"host": "127.0.0.1", "port": 0, "key": api_key},
            )
        )
        connected = await adapter.connect()
        if not connected:
            ProfileSandboxManager.notify_child_ready(False)
            return 78
        ProfileSandboxManager.notify_child_ready(True)
        stopped = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(signum, stopped.set)
            except (NotImplementedError, RuntimeError):
                pass
        await stopped.wait()
        return 0
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - any startup fault must fail closed.
        ProfileSandboxManager.notify_child_ready(False)
        return 78
    finally:
        if connected:
            await adapter.disconnect()


def main() -> int:
    return asyncio.run(_serve())


if __name__ == "__main__":
    raise SystemExit(main())
