"""Exercise native skill tools and learning with a local scripted model."""

import argparse
import asyncio
import importlib.util
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace


def content(name):
    return f"---\nname: {name}\ndescription: Reusable smoke procedure\n---\n\nKeep the learned marker.\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--phase", choices=("create", "verify"), required=True)
    args = parser.parse_args()
    assert os.getuid() == 10000
    subprocess.run(["xurl", "--help"], check=True, capture_output=True, timeout=10)
    os.environ["HERMES_HOME"] = str(args.root)
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from tools.skill_manager_tool import skill_manage
    from tools.skills_tool import skill_view, skills_list

    profiles = [args.root / "profiles" / name for name in ("alpha", "beta")]
    if args.phase == "create":
        for profile in profiles:
            (profile / "skills").mkdir(parents=True)
            (profile / "config.yaml").write_text(
                "skills:\n  external_dirs: [/opt/allies/skills]\n", encoding="utf-8"
            )
            (profile / ".env").write_text(
                f"API_SERVER_KEY=skills-smoke-{profile.name}-key\n", encoding="utf-8"
            )
    token = set_hermes_home_override(profiles[0])
    try:
        names = {row["name"] for row in json.loads(skills_list())["skills"]}
        representatives = {
            "xurl",
            "himalaya",
            "github-issues",
            "allies-skill-discovery",
            "grounded-citations",
            "arxiv",
            "humanizer",
            "architecture-diagram",
            "youtube-content",
            "maps",
            "ocr-and-documents",
        }
        assert representatives <= names, representatives - names
        assert not {"docx", "xlsx", "pdf", "powerpoint"} & names
        for name in representatives:
            assert json.loads(skill_view(name))["success"]
        assert importlib.util.find_spec("pymupdf") is None
        assert importlib.util.find_spec("marker") is None
        ocr = json.loads(skill_view("ocr-and-documents"))
        for script in ("extract_pymupdf.py", "extract_marker.py"):
            assert (Path(ocr["skill_dir"]) / "scripts" / script).is_file()
        catalog = Path("/opt/allies/skills")
        assert not (catalog / "index-cache").exists()
        shared = catalog / "allies-skill-discovery" / "SKILL.md"
        try:
            with shared.open("a"):
                raise AssertionError("catalog writable by runtime user")
        except PermissionError:
            pass
        if args.phase == "create":
            assert json.loads(
                skill_manage(
                    "create", "private-smoke", content=content("private-smoke")
                )
            )["success"]
            assert json.loads(
                skill_manage(
                    "patch",
                    "private-smoke",
                    old_string="learned marker",
                    new_string="updated marker",
                )
            )["success"]
            learning(profiles[0])
        assert (
            "updated marker"
            in (profiles[0] / "skills/private-smoke/SKILL.md").read_text()
        )
        assert (
            "learned marker"
            in (profiles[0] / "skills/review-smoke/SKILL.md").read_text()
        )
    finally:
        reset_hermes_home_override(token)
    token = set_hermes_home_override(profiles[1])
    try:
        assert not json.loads(skill_view("private-smoke"))["success"]
        assert not json.loads(
            skill_manage(
                "patch", "private-smoke", old_string="updated", new_string="bad"
            )
        )["success"]
        assert not (profiles[1] / "skills/review-smoke").exists()
    finally:
        reset_hermes_home_override(token)
    asyncio.run(api_check())
    print(
        f"Native skills {args.phase} passed: discovery, private state, profile isolation."
    )


async def api_check():
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from gateway.config import GatewayConfig, PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    adapter = APIServerAdapter(PlatformConfig(extra={"key": "skills-smoke-global-key"}))
    adapter.gateway_runner = SimpleNamespace(
        config=GatewayConfig(multiplex_profiles=True)
    )
    app = web.Application(middlewares=[adapter._make_profile_prefix_middleware()])
    app.router.add_get("/p/{profile}/v1/skills", adapter._handle_skills)
    async with TestClient(TestServer(app)) as client:
        for headers in ({}, {"Authorization": "Bearer skills-smoke-beta-key"}):
            rejected = await client.get("/p/alpha/v1/skills", headers=headers)
            assert rejected.status == 401
        for profile in ("alpha", "beta"):
            response = await client.get(
                f"/p/{profile}/v1/skills",
                headers={"Authorization": f"Bearer skills-smoke-{profile}-key"},
            )
            assert response.status == 200, await response.text()
            names = {row["name"] for row in (await response.json())["data"]}
            assert "xurl" in names
            assert ("private-smoke" in names) == (profile == "alpha")


def learning(profile):
    from run_agent import AIAgent

    class Model(BaseHTTPRequestHandler):
        calls = 0
        last_tool_result = None

        def log_message(self, *_args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            for row in request.get("messages", []):
                if row.get("role") == "tool":
                    Model.last_tool_result = row.get("content")
            if request.get("messages"):
                Model.calls += 1
            number = Model.calls
            message = {"role": "assistant", "content": "Done."}
            if request.get("messages") and (number <= 10 or number == 12):
                name = "skills_list" if number <= 10 else "skill_manage"
                arguments = (
                    {"category": f"smoke-{number}"}
                    if number <= 10
                    else {
                        "action": "create",
                        "name": "review-smoke",
                        "content": content("review-smoke"),
                    }
                )
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call-{number}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                }
            body = json.dumps(
                {
                    "id": f"smoke-{number}",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "skills-smoke",
                    "choices": [
                        {
                            "index": 0,
                            "message": message,
                            "finish_reason": "tool_calls"
                            if "tool_calls" in message
                            else "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 10,
                        "total_tokens": 20,
                    },
                }
            ).encode()
            streaming = request.get("stream", False)
            if streaming:
                chunk = json.loads(body)
                chunk["object"] = "chat.completion.chunk"
                chunk["choices"][0]["delta"] = chunk["choices"][0].pop("message")
                if "tool_calls" in message:
                    message["tool_calls"][0]["index"] = 0
                    chunk["choices"][0]["delta"] = message
                body = ("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header(
                "Content-Type", "text/event-stream" if streaming else "application/json"
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    agent = AIAgent(
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        api_key="smoke-only",
        provider="openai",
        api_mode="chat_completions",
        model="skills-smoke",
        enabled_toolsets=["skills"],
        max_iterations=15,
        quiet_mode=True,
        skip_memory=True,
    )
    try:
        assert agent._skill_nudge_interval == 10
        result = agent.run_conversation(
            "Learn the reusable smoke procedure after inspecting ten categories."
        )
        assert result.get("final_response"), result
        deadline = time.monotonic() + 30
        while (
            not (profile / "skills/review-smoke/SKILL.md").exists()
            and time.monotonic() < deadline
        ):
            time.sleep(0.1)
        assert (profile / "skills/review-smoke/SKILL.md").exists(), (
            f"Native review did not save skill; model calls={Model.calls}; result={Model.last_tool_result}"
        )
    finally:
        agent.close()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
