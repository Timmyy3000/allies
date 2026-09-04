"""Exercise the patched Hermes bootstrap route against the built image."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from aiohttp import ClientResponse, web
from aiohttp.test_utils import TestClient, TestServer
from gateway.config import GatewayConfig, PlatformConfig
from gateway.platforms.api_server import APIServerAdapter, _api_request_profile
from hermes_state import SessionDB

PROFILE = "ally-smoke"
OTHER_PROFILE = "ally-other"
SESSION_ID = "first-turn-smoke"
MESSAGE_ID = "8ef84387-581e-4e6f-a31d-6fbca75d95f4"
API_KEY = "allies-bootstrap-smoke-key-000001"
PROFILE_KEY = "allies-bootstrap-profile-key-0001"
OTHER_PROFILE_KEY = "allies-bootstrap-profile-key-0002"


class _RemoteRequest:
    remote = "203.0.113.10"
    transport = None

    def __init__(self) -> None:
        self.match_info = {"profile": PROFILE, "session_id": SESSION_ID}
        self.headers = {"Authorization": f"Bearer {PROFILE_KEY}"}

    async def json(self) -> dict[str, str]:
        return _payload("Hello from Allies")


def _payload(text: str) -> dict[str, str]:
    return {
        "schema_version": "v1",
        "kind": "assistant_transcript_bootstrap",
        "message_id": MESSAGE_ID,
        "text": text,
    }


def _seed_profile(root: Path, name: str, key: str, *, history: bool = False) -> Path:
    profile = root / "profiles" / name
    profile.mkdir(parents=True)
    (profile / ".env").write_text(f"API_SERVER_KEY={key}\n", encoding="utf-8")
    database = SessionDB(profile / "state.db")
    try:
        database.create_session(SESSION_ID, "api_server")
        if history:
            database.append_message(SESSION_ID, "user", "Existing other-profile row")
    finally:
        database.close()
    return profile


def _app(adapter: APIServerAdapter) -> web.Application:
    app = web.Application(middlewares=[adapter._make_profile_prefix_middleware()])
    method, path, handler = next(
        row
        for row in adapter._http_route_table()
        if row[:2] == ("PUT", "/api/sessions/{session_id}/bootstrap")
    )
    app.router.add_route(method, path, handler)
    app.router.add_route(method, f"/p/{{profile}}{path}", handler)
    return app


async def _request(
    client: TestClient,
    path: str,
    key: str,
    text: str = "Hello from Allies",
) -> ClientResponse:
    return await client.put(
        path,
        headers={"Authorization": f"Bearer {key}"},
        json=_payload(text),
    )


async def _run() -> None:
    previous_home = os.environ.get("HERMES_HOME")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        os.environ["HERMES_HOME"] = str(root)
        profile = _seed_profile(root, PROFILE, PROFILE_KEY)
        other_profile = _seed_profile(
            root, OTHER_PROFILE, OTHER_PROFILE_KEY, history=True
        )
        adapter = APIServerAdapter(PlatformConfig(extra={"key": API_KEY}))
        adapter.gateway_runner = SimpleNamespace(
            config=GatewayConfig(multiplex_profiles=True)
        )
        try:
            async with TestClient(TestServer(_app(adapter))) as client:
                path = f"/p/{PROFILE}/api/sessions/{SESSION_ID}/bootstrap"
                created = await _request(client, path, PROFILE_KEY)
                duplicate = await _request(client, path, PROFILE_KEY)
                conflict = await _request(
                    client, path, PROFILE_KEY, "Different greeting"
                )
                wrong_key = await _request(client, path, OTHER_PROFILE_KEY)
                default = await _request(
                    client, f"/api/sessions/{SESSION_ID}/bootstrap", API_KEY
                )
                unknown = await _request(
                    client,
                    f"/p/unknown/api/sessions/{SESSION_ID}/bootstrap",
                    PROFILE_KEY,
                )
                other = await _request(
                    client,
                    f"/p/{OTHER_PROFILE}/api/sessions/{SESSION_ID}/bootstrap",
                    OTHER_PROFILE_KEY,
                )

                assert created.status == 201
                assert (await created.json())["status"] == "created"
                assert duplicate.status == 200
                assert (await duplicate.json())["status"] == "duplicate"
                assert conflict.status == 409
                assert wrong_key.status == 401
                assert default.status == 403
                assert unknown.status == 404
                assert other.status == 409

            expected_key = adapter._expected_api_key
            adapter._expected_api_key = lambda: PROFILE_KEY
            token = _api_request_profile.set(PROFILE)
            try:
                remote = await adapter._handle_session_bootstrap(_RemoteRequest())
            finally:
                _api_request_profile.reset(token)
                adapter._expected_api_key = expected_key
            assert remote.status == 403
        finally:
            for database in getattr(adapter, "_session_dbs", {}).values():
                database.close()
            await adapter.disconnect()

        database = SessionDB(profile / "state.db")
        other_database = SessionDB(other_profile / "state.db")
        try:
            rows = database.get_messages(SESSION_ID, include_inactive=True)
            assert len(rows) == 1
            assert rows[0]["role"] == "assistant"
            assert rows[0]["content"] == "Hello from Allies"
            assert rows[0]["platform_message_id"] == MESSAGE_ID
            other_rows = other_database.get_messages(SESSION_ID, include_inactive=True)
            assert len(other_rows) == 1
            assert other_rows[0]["role"] == "user"
            assert other_rows[0]["content"] == "Existing other-profile row"
        finally:
            database.close()
            other_database.close()
            if previous_home is None:
                os.environ.pop("HERMES_HOME", None)
            else:
                os.environ["HERMES_HOME"] = previous_home


asyncio.run(_run())
