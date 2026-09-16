"""Exercise safe proxy handling for abrupt and truncated Unix child responses."""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from uuid import uuid4

from aiohttp import ClientError, ClientSession, ClientTimeout, web
from allies_profile_sandbox import ProfileSandboxManager

PROFILE_KEY = f"ally-v1-{uuid4().hex}"


class _Request:
    method = "GET"
    path = f"/p/{PROFILE_KEY}/api/sessions"
    query_string = ""
    headers: ClassVar[dict[str, str]] = {
        "Authorization": "Bearer smoke-key",
        "X-Allies-Profile-Forwarded": "smoke-marker",
    }
    transport = None

    async def read(self) -> bytes:
        return b""


async def _child_handler(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    mode: str,
    accepted: asyncio.Event,
) -> None:
    try:
        await reader.readuntil(b"\r\n\r\n")
        accepted.set()
        if mode == "before_headers":
            return
        if mode == "truncated":
            body = b'{"partial"'
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: 20\r\n"
                b"Connection: close\r\n\r\n" + body
            )
            await writer.drain()
            return
        if mode == "partial_sse":
            body = b"data: partial\n\n"
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/event-stream\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n"
                + f"{len(body):X}".encode()
                + b"\r\n"
                + body
                + b"\r\n"
            )
            await writer.drain()
            return
        if mode == "stall":
            await reader.read()
            return
        raise AssertionError(f"unknown child mode: {mode}")
    except (asyncio.IncompleteReadError, ConnectionError, OSError):
        pass
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()


async def _child_case(
    manager: ProfileSandboxManager,
    mode: str,
    callback,
) -> None:
    with tempfile.TemporaryDirectory(prefix="allies-proxy-smoke-") as directory:
        socket_path = Path(directory) / "child.sock"
        accepted = asyncio.Event()
        server = await asyncio.start_unix_server(
            lambda reader, writer: _child_handler(reader, writer, mode, accepted),
            path=str(socket_path),
        )
        state = SimpleNamespace(
            listener_path=socket_path,
            marker="smoke-marker",
            active_requests=0,
            last_used=0.0,
        )

        async def ensure(_profile_key: str):
            return state

        manager.ensure = ensure
        try:
            await callback(state, accepted)
        finally:
            server.close()
            await server.wait_closed()


async def _expect_unavailable(
    manager: ProfileSandboxManager, url: str, mode: str
) -> None:
    async def check(_state, _accepted) -> None:
        async with (
            ClientSession(timeout=ClientTimeout(total=5)) as client,
            client.get(url) as response,
        ):
            payload = await response.json()
            assert response.status == 503, payload
            assert response.headers["Retry-After"] == "1"
            assert payload["error"]["code"] == "profile_sandbox_unavailable"

    await _child_case(manager, mode, check)


async def _expect_partial_sse(manager: ProfileSandboxManager, url: str) -> None:
    async def check(_state, _accepted) -> None:
        chunks: list[bytes] = []
        interrupted = False
        async with ClientSession(timeout=ClientTimeout(total=5)) as client:
            try:
                async with client.get(url) as response:
                    assert response.status == 200
                    async for chunk in response.content.iter_chunked(1024):
                        chunks.append(chunk)
            except ClientError:
                interrupted = True
        assert interrupted, "partial SSE unexpectedly ended successfully"
        assert b"data: partial" in b"".join(chunks)

    await _child_case(manager, "partial_sse", check)


async def _expect_cancellation(manager: ProfileSandboxManager) -> None:
    async def check(_state, accepted) -> None:
        request = _Request()
        task = asyncio.create_task(manager.proxy(PROFILE_KEY, request))
        await asyncio.wait_for(accepted.wait(), timeout=5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return
        raise AssertionError("proxy cancellation was converted to a response")

    await _child_case(manager, "stall", check)


async def _run() -> None:
    manager = ProfileSandboxManager(SimpleNamespace())
    app = web.Application()

    async def proxy_handler(request):
        return await manager.proxy(PROFILE_KEY, request)

    app.router.add_route("*", f"/p/{PROFILE_KEY}/{{tail:.*}}", proxy_handler)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}/p/{PROFILE_KEY}/api/sessions"
    try:
        await _expect_unavailable(manager, url, "before_headers")
        await _expect_unavailable(manager, url, "truncated")
        await _expect_partial_sse(manager, url)
        await _expect_cancellation(manager)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(_run())
    print(
        "Proxy failure handling: pre-header 503, truncation, partial SSE abort, and cancellation passed"
    )
