"""Check the staged-file context boundary in the built Hermes image."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from gateway.config import GatewayConfig, PlatformConfig
from gateway.platforms.api_server import (
    APIServerAdapter,
    _allies_incoming_file_context_prompt,
)
from hermes_state import SessionDB
from tools.image_source import ResolveContext, resolve_image_source


async def check_stream(context):
    with (
        TemporaryDirectory() as directory,
        patch.dict("os.environ", {"HERMES_HOME": directory}),
    ):
        profile = Path(directory) / "profiles" / "ally-file-smoke"
        profile.mkdir(parents=True)
        key = "file-smoke-profile-key-0000001"
        (profile / ".env").write_text(f"API_SERVER_KEY={key}\n")
        database = SessionDB(profile / "state.db")
        database.create_session("file-smoke", "api_server")
        database.close()
        adapter = APIServerAdapter(PlatformConfig(extra={"key": key}))
        adapter.gateway_runner = SimpleNamespace(
            config=GatewayConfig(multiplex_profiles=True)
        )
        observed = []

        async def run_agent(**kwargs):
            observed.append(kwargs)
            return {
                "session_id": "file-smoke",
                "final_response": "done",
                "messages": [
                    {"role": "user", "content": kwargs["user_message"]},
                    {"role": "assistant", "content": "done"},
                ],
            }, {}

        adapter._run_agent = run_agent
        app = web.Application(middlewares=[adapter._make_profile_prefix_middleware()])
        method, path, handler = next(
            row
            for row in adapter._http_route_table()
            if row[:2] == ("POST", "/api/sessions/{session_id}/chat/stream")
        )
        app.router.add_route(method, f"/p/{{profile}}{path}", handler)
        try:
            async with TestClient(TestServer(app)) as client:
                for message, files in (
                    ("Look at this", context),
                    ("", context),
                    ("Hello", None),
                ):
                    payload = {"message": message}
                    if files:
                        payload["allies_file_context"] = files
                    response = await client.post(
                        "/p/ally-file-smoke/api/sessions/file-smoke/chat/stream",
                        headers={"Authorization": f"Bearer {key}"},
                        json=payload,
                    )
                    body = await response.text()
                    assert response.status == 200, body
                    assert str(profile) not in body
                    delivered = observed[-1]["user_message"]
                    if files:
                        assert (
                            str(profile / "workspace" / context["files"][0]["path"])
                            in delivered
                        )
                        assert delivered.startswith(message + "\n\n")
                        assert "file manifest" not in (
                            observed[-1]["ephemeral_system_prompt"] or ""
                        )
                    else:
                        assert delivered == message
                calls = len(observed)
                for payload in (
                    {"message": ""},
                    {"message": "", "allies_file_context": {**context, "files": []}},
                ):
                    response = await client.post(
                        "/p/ally-file-smoke/api/sessions/file-smoke/chat/stream",
                        headers={"Authorization": f"Bearer {key}"},
                        json=payload,
                    )
                    await response.read()
                    assert response.status == 400
                assert len(observed) == calls
        finally:
            for database in getattr(adapter, "_session_dbs", {}).values():
                database.close()


def main() -> None:
    descriptor = {
        "file_id": "12345678-1234-1234-1234-123456789abc",
        "name": "notes.txt",
        "media_type": "text/plain",
        "size": 4,
        "sha256": "a" * 64,
        "path": "attachments/command/notes.txt",
    }
    context = {
        "schema_version": "v1",
        "kind": "allies_incoming_files",
        "files": [descriptor],
    }
    assert _allies_incoming_file_context_prompt(None) is None
    assert "attachments/command/notes.txt" in _allies_incoming_file_context_prompt(
        context
    )
    assert _allies_incoming_file_context_prompt(
        {**context, "files": [{**descriptor, "name": "界" * 255}]}
    )
    assert _allies_incoming_file_context_prompt(
        {**context, "files": [{**descriptor, "name": "😀" * 255}] * 10}
    )
    for invalid in (
        {**context, "files": []},
        {**context, "files": [{**descriptor, "path": "../other/notes.txt"}]},
        {**context, "files": [{**descriptor, "size": 25_000_001}]},
        {**context, "files": [{**descriptor, "contents": "secret"}]},
    ):
        try:
            _allies_incoming_file_context_prompt(invalid)
        except ValueError:
            continue
        raise AssertionError("invalid file context was accepted")

    with TemporaryDirectory() as directory:
        for profile in ("first", "second"):
            home = Path(directory) / profile
            image = home / "workspace" / descriptor["path"]
            image.parent.mkdir(parents=True)
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
            with patch("hermes_constants.get_hermes_home", return_value=home):
                prompt = _allies_incoming_file_context_prompt(context)
            manifest = json.loads(prompt.split("\n", 1)[1])
            image_path = manifest[0]["path"]
            assert Path(image_path) == image
            with patch.dict("os.environ", {"TERMINAL_ENV": "local"}):
                resolved = asyncio.run(
                    resolve_image_source(image_path, ResolveContext())
                )
            assert resolved.data == image.read_bytes()
            assert resolved.mime == "image/png"
    asyncio.run(check_stream(context))
    print("incoming file context: PASS")


if __name__ == "__main__":
    main()
