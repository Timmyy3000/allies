"""Exercise plugin discovery and Hermes dispatch using a local HTTP receipt."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from hermes_cli.plugins import discover_plugins
from model_tools import get_tool_definitions, handle_function_call
from tools.allies_routines import context, turn_context
from tools.registry import registry


def main():
    discover_plugins(force=True)
    assert registry.get_entry("allies_routines") is not None
    definitions = get_tool_definitions(
        enabled_toolsets=["allies-routines", "cronjob"],
        disabled_toolsets=["cronjob"],
        quiet_mode=True,
        skip_tool_search_assembly=True,
    )
    names = {item["function"]["name"] for item in definitions}
    assert "allies_routines" in names and "cronjob" not in names, names
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert self.path == "/api/v1/runtime/routines/tool"
            assert self.headers["Authorization"] == "Bearer smoke-capability"
            observed.append(body)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"saved"}')

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token = context.set(
        turn_context("smoke-capability", f"http://127.0.0.1:{server.server_port}")
    )
    try:
        for _ in range(2):
            result = handle_function_call(
                "tool_call",
                {"name": "allies_routines", "arguments": {"action": "list"}},
                task_id="smoke",
                tool_call_id="call_smoke",
                enabled_tools=["tool_call", "tool_search", "tool_describe"],
                enabled_toolsets=["allies-routines"],
                disabled_toolsets=["cronjob"],
            )
            assert json.loads(result)["status"] == "saved", result
        assert observed[0]["call_id"] == observed[1]["call_id"]
    finally:
        context.reset(token)
        server.shutdown()
        server.server_close()
        thread.join()
    assert "unavailable" in registry.dispatch("allies_routines", {"action": "list"})
    print("Hermes routine management discovery, dispatch and isolation: PASS")


if __name__ == "__main__":
    main()
