"""Prove request reasoning overrides stored Hermes configuration."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter

captured = {}
PROFILE_KEY = f"ally-v1-{uuid4().hex}"


class FakeAgent:
    def __init__(self, **kwargs):
        captured.update(kwargs)


def _run() -> None:
    profile = Path("/opt/data/profiles") / PROFILE_KEY
    workspace = profile / "workspace"
    workspace.mkdir(parents=True)
    (profile / "state.db").touch()
    previous_cwd = os.getcwd()
    os.environ["HERMES_HOME"] = str(profile)
    os.environ["ALLIES_PROFILE_SANDBOX_CHILD"] = "1"
    os.environ["ALLIES_PROFILE_SANDBOX_PROFILE"] = PROFILE_KEY
    os.environ["ALLIES_PROFILE_WORKSPACE"] = str(workspace)
    adapter = APIServerAdapter(PlatformConfig(enabled=True))
    try:
        with (
            patch("run_agent.AIAgent", FakeAgent),
            patch(
                "gateway.run._resolve_runtime_agent_kwargs",
                return_value={
                    "provider": "openai-api",
                    "base_url": "https://example.test/v1",
                },
            ),
            patch("gateway.run._resolve_gateway_model", return_value="gpt-5.6-luna"),
            patch("gateway.run._load_gateway_config", return_value={}),
            patch(
                "gateway.run.GatewayRunner._load_reasoning_config",
                return_value={"enabled": True, "effort": "medium"},
            ),
            patch("gateway.run.GatewayRunner._load_fallback_model", return_value=None),
            patch("hermes_cli.tools_config._get_platform_tools", return_value=set()),
            patch.object(adapter, "_ensure_session_db", return_value=None),
        ):
            adapter._create_agent(
                session_id="allies-session",
                model_options={"reasoning": {"enabled": True, "effort": "xhigh"}},
            )
    finally:
        asyncio.run(adapter.disconnect())
        os.chdir(previous_cwd)
        shutil.rmtree(profile, ignore_errors=True)


with patch.dict(os.environ):
    _run()

assert captured["model"] == "gpt-5.6-luna"
assert captured["reasoning_config"] == {"enabled": True, "effort": "xhigh"}
