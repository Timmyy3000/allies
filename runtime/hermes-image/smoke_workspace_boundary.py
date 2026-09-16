"""Exercise the profile namespace policy with disposable UID-10000 fixtures."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from allies_profile_sandbox import (
    ALL_PROFILE_ROUTES,
    PROFILE_CHILD_ROUTES,
    PROFILE_DENIED_ROUTES,
    PROFILE_MANAGED_FILES,
    PROFILE_PARENT_ROUTES,
    ProfileSandboxManager,
    ProfileSandboxUnavailable,
    _validate_profile_hardlinks,
    route_owner,
)

PROFILE_WRITE_DIRECTORIES = (
    "workspace",
    "memories",
    "sessions",
    "skills",
    "skins",
    "logs",
    "plans",
    "cron",
    "home",
    "cache",
    "mnemosyne",
)

BOUNDARY_PAYLOAD = r"""
import os
import json
import socket
import sqlite3
import subprocess
from pathlib import Path

KEY = "__TARGET__"
SIBLING = "__SIBLING__"
RUNTIME_SECRET = Path("__RUNTIME_SECRET__")
home = Path("/opt/data/profiles") / KEY
workspace = home / "workspace"

assert os.geteuid() == 10000
assert os.getpid() > 1
assert (
    Path("/proc/1/cmdline")
    .read_bytes()
    .split(b"\0", 1)[0]
    .rsplit(b"/", 1)[-1]
    == b"bwrap"
)
status = {
    line.split(":", 1)[0]: line.split(":", 1)[1].strip()
    for line in Path("/proc/self/status").read_text().splitlines()
    if ":" in line
}
assert status["NoNewPrivs"] == "1"
assert Path.cwd() == workspace
assert os.environ["HERMES_PROFILE"] == KEY
assert os.environ["HERMES_HOME"] == str(home)
assert os.environ["HOME"] == str(home / "home")
assert os.environ["TERMINAL_CWD"] == str(workspace)
assert os.environ.get("PARENT_SECRET") is None

# Exercise the initial terminal cwd and the first model-directed file write.
first = subprocess.run(
    ["/bin/sh", "-ceu", "test \"$PWD\" = \"$1\"; pwd; printf first > first-write.txt", "sh", str(workspace)],
    cwd=workspace,
    capture_output=True,
    text=True,
    check=False,
)
assert first.returncode == 0
assert first.stdout.strip() == str(workspace)
assert (workspace / "first-write.txt").read_text() == "first"

from tools.file_tools import write_file_tool

file_tool_result = json.loads(
    write_file_tool("file-tool-first-write.txt", "file-tool", task_id="smoke")
)
assert not file_tool_result.get("error"), file_tool_result
assert Path(file_tool_result["resolved_path"]) == workspace / "file-tool-first-write.txt"
assert (workspace / "file-tool-first-write.txt").read_text() == "file-tool"

(workspace / "own.txt").write_text("workspace", encoding="utf-8")
(home / "skills" / "generated.py").write_text("value = 1\n", encoding="utf-8")
(home / "memories" / "note.txt").write_text("private", encoding="utf-8")
(home / "sessions" / "session.txt").write_text("session", encoding="utf-8")
(home / "cache" / "cache.txt").write_text("cache", encoding="utf-8")
(home / "mnemosyne" / "data" / "beam.sqlite").write_bytes(b"sqlite")

database = sqlite3.connect(home / "state.db")
database.execute("CREATE TABLE IF NOT EXISTS smoke (value TEXT)")
database.execute("INSERT INTO smoke VALUES ('owned')")
database.commit()
assert database.execute("SELECT value FROM smoke").fetchone() == ("owned",)
database.close()

shared = Path("/opt/allies/skills/LICENSE")
assert shared.is_file()
assert shared.read_text(encoding="utf-8")
try:
    shared.write_text("must remain immutable", encoding="utf-8")
except OSError:
    pass
else:
    raise AssertionError("shared catalog was writable")

for hidden in (
    RUNTIME_SECRET,
    Path("/opt/data/profiles") / SIBLING / "secret.txt",
):
    assert not hidden.exists(), hidden

escape = Path("/opt/data") / ".allies-smoke-escape"
try:
    escape.write_text("escape", encoding="utf-8")
except OSError:
    pass
else:
    raise AssertionError("masked tenant root was writable")

runtime_code = Path("/opt/hermes/run_agent.py")
assert runtime_code.is_file()
try:
    runtime_code.write_text("must remain immutable", encoding="utf-8")
except OSError:
    pass
else:
    raise AssertionError("runtime code was writable")

control = home / ".env"
original_control = control.read_text(encoding="utf-8")
alias_control = home / "workspace" / ".." / ".env"
try:
    alias_control.write_text("API_SERVER_KEY=alias-bypass\n", encoding="utf-8")
except OSError:
    pass
else:
    raise AssertionError("managed control alias was writable")
try:
    control.write_text("API_SERVER_KEY=changed\n", encoding="utf-8")
except OSError:
    pass
else:
    raise AssertionError("managed control file was writable")
try:
    control.unlink()
except OSError:
    pass
else:
    raise AssertionError("managed control file could be unlinked")
replacement = home / ".env.replaced"
replacement.write_text("replacement", encoding="utf-8")
try:
    os.replace(replacement, control)
except OSError:
    pass
else:
    raise AssertionError("managed control file could be replaced")
finally:
    replacement.unlink(missing_ok=True)
assert control.read_text(encoding="utf-8") == original_control

shell = subprocess.run(
    [
        "/bin/sh",
        "-ceu",
        "printf shell > own-shell.txt; "
        "(printf descendant > own-descendant.txt) & child=$!; wait $child; "
        "if printf escape > /opt/data/.allies-shell-escape; then exit 41; fi",
    ],
    cwd=workspace,
    check=False,
)
assert shell.returncode == 0
assert (workspace / "own-shell.txt").read_text() == "shell"
assert (workspace / "own-descendant.txt").read_text() == "descendant"

pids = {int(path.name) for path in Path("/proc").iterdir() if path.name.isdigit()}
assert 1 in pids and max(pids) < 16, pids

publication = Path("/opt/data/.allies-publication-bridge/socket")
assert publication.is_socket()
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
    connection.connect(str(publication))
    connection.sendall(b"publication")

if os.environ.get("SMOKE_TRANSPORT") == "1":
    descriptor = int(os.environ["ALLIES_PROFILE_SANDBOX_LISTENER_FD"])
    with socket.socket(fileno=descriptor) as connection:
        connection.sendall(b"private")
"""

LIFECYCLE_PAYLOAD = r"""
import subprocess
import sys
import time
from pathlib import Path

marker = Path("__MARKER__")
started = Path("__STARTED__")
child = subprocess.Popen(
    [
        sys.executable,
        "-c",
        "import time; from pathlib import Path; time.sleep(1.0); "
        f"Path({str(marker)!r}).write_text('orphan', encoding='utf-8')",
    ]
)
started.write_text(str(child.pid), encoding="utf-8")
time.sleep(30)
"""


@dataclass
class Fixture:
    target: str
    sibling: str
    home: Path
    sibling_home: Path
    runtime_secret: Path
    bridge_dir: Path
    bridge: Path
    server: socket.socket


def _sample_path(template: str) -> str:
    return "/".join(
        "fixture" if part.startswith("{") and part.endswith("}") else part
        for part in template.split("/")
    )


def _check_routes(manager: ProfileSandboxManager, target: str) -> None:
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    adapter = APIServerAdapter(
        PlatformConfig(enabled=True, extra={"key": "synthetic-route-check"})
    )
    registered = [(row[0], row[1]) for row in adapter._http_route_table()]
    assert len(registered) == len(set(registered))
    assert set(registered) == ALL_PROFILE_ROUTES
    assert manager.validate_routes(registered) is None
    asyncio.run(adapter.disconnect())

    assert PROFILE_CHILD_ROUTES.isdisjoint(PROFILE_PARENT_ROUTES)
    assert PROFILE_CHILD_ROUTES.isdisjoint(PROFILE_DENIED_ROUTES)
    assert PROFILE_PARENT_ROUTES.isdisjoint(PROFILE_DENIED_ROUTES)
    assert ALL_PROFILE_ROUTES == (
        PROFILE_CHILD_ROUTES | PROFILE_PARENT_ROUTES | PROFILE_DENIED_ROUTES
    )
    assert manager.validate_routes(sorted(ALL_PROFILE_ROUTES)) is None
    assert (
        manager.validate_routes(
            [*sorted(ALL_PROFILE_ROUTES), ("POST", "/v1/unclassified")]
        )
        == "unclassified_route"
    )

    for method, template in sorted(ALL_PROFILE_ROUTES):
        path = _sample_path(template)
        expected = (
            "child"
            if (method, template) in PROFILE_CHILD_ROUTES
            else "parent"
            if (method, template) in PROFILE_PARENT_ROUTES
            else "denied"
        )
        assert route_owner(method, path) == (expected, template, False)
        assert route_owner(method, f"/p/{target}{path}?smoke=1") == (
            expected,
            template,
            True,
        )

    assert route_owner("POST", "/v1/unclassified") == ("denied", "", False)

    class Request:
        def __init__(self, method: str, path: str):
            self.method = method
            self.path = path

    async def handler(_request):
        return "handled"

    async def check_dispatch() -> None:
        prefixed_quiesce = await manager.dispatch(
            target,
            Request("POST", f"/p/{target}/v1/profiles/{target}/quiesce"),
            handler,
        )
        assert prefixed_quiesce.status == 404
        direct_child = await manager.dispatch(
            None, Request("POST", "/v1/runs"), handler
        )
        assert direct_child.status == 404
        assert (
            await manager.dispatch(
                None, Request("POST", f"/v1/profiles/{target}/quiesce"), handler
            )
            == "handled"
        )

    asyncio.run(check_dispatch())


def _set_owner(path: Path, uid: int, gid: int, mode: int) -> None:
    os.chown(path, uid, gid)
    path.chmod(mode)


def _seed_profile(home: Path) -> None:
    home.mkdir(mode=0o700)
    for directory in PROFILE_WRITE_DIRECTORIES:
        (home / directory).mkdir(mode=0o700)
    (home / "mnemosyne" / "data").mkdir(mode=0o700)
    for name, contents in (
        (".env", "API_SERVER_KEY=synthetic-profile-secret\n"),
        ("config.yaml", "profile: smoke\n"),
        ("SOUL.md", "smoke profile\n"),
        (".allies-profile.json", "{}\n"),
    ):
        path = home / name
        path.write_text(contents, encoding="utf-8")
        path.chmod(0o600)
    (home / "state.db").touch()


def _create_fixture(*, root_owned: bool) -> Fixture:
    root = Path("/opt/data")
    profiles = root / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    target = f"ally-v1-{uuid4().hex}"
    sibling = f"ally-v1-{uuid4().hex}"
    home = profiles / target
    sibling_home = profiles / sibling
    _seed_profile(home)
    _seed_profile(sibling_home)
    (sibling_home / "secret.txt").write_text("sibling-secret", encoding="utf-8")
    runtime_secret = root / f".allies-sandbox-runtime-{uuid4().hex}"
    runtime_secret.write_text("runtime-secret", encoding="utf-8")
    bridge_dir = root / f".allies-publication-smoke-{uuid4().hex}"
    bridge_dir.mkdir(mode=0o700)
    bridge = bridge_dir / "socket"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(bridge))
    server.listen(1)
    if root_owned:
        for profile_home in (home, sibling_home):
            _set_owner(profile_home, 10000, 10001, 0o770)
            for directory in PROFILE_WRITE_DIRECTORIES:
                _set_owner(profile_home / directory, 10000, 10001, 0o700)
            _set_owner(profile_home / "mnemosyne" / "data", 10000, 10001, 0o700)
            _set_owner(profile_home / "state.db", 10000, 10001, 0o600)
            for filename in (".env", "config.yaml", "SOUL.md", ".allies-profile.json"):
                _set_owner(profile_home / filename, 0, 10001, 0o640)
        _set_owner(sibling_home / "secret.txt", 0, 10001, 0o640)
        _set_owner(runtime_secret, 0, 10001, 0o640)
        _set_owner(bridge_dir, 0, 10001, 0o750)
        _set_owner(bridge, 0, 10001, 0o660)
    return Fixture(
        target,
        sibling,
        home,
        sibling_home,
        runtime_secret,
        bridge_dir,
        bridge,
        server,
    )


def _drop_to_profile_user() -> None:
    os.setgroups([10000, 10001])
    os.setgid(10000)
    os.setuid(10000)


def _payload(template: str, fixture: Fixture) -> str:
    return (
        template.replace("__TARGET__", fixture.target)
        .replace("__SIBLING__", fixture.sibling)
        .replace("__RUNTIME_SECRET__", str(fixture.runtime_secret))
    )


def _command(
    manager: ProfileSandboxManager,
    fixture: Fixture,
    payload: str,
    *,
    listener_fd: int,
    marker: str,
) -> tuple[list[str], dict[str, str]]:
    previous_secret = os.environ.get("PARENT_SECRET")
    os.environ["PARENT_SECRET"] = "must-not-cross-boundary"
    try:
        command, environment = manager._command(
            fixture.home,
            fixture.target,
            listener_fd,
            listener_fd,
            marker,
            fixture.bridge,
        )
    finally:
        if previous_secret is None:
            os.environ.pop("PARENT_SECRET", None)
        else:
            os.environ["PARENT_SECRET"] = previous_secret
    command[command.index("--") + 1 :] = [sys.executable, "-c", payload]
    environment["SMOKE_TRANSPORT"] = "1" if listener_fd >= 0 else "0"
    return command, environment


def _run(command: list[str], environment: dict[str, str], *, pass_fds=()) -> None:
    result = subprocess.run(
        command,
        cwd=environment["PWD"],
        env=environment,
        pass_fds=pass_fds,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"sandbox payload failed ({result.returncode}): {result.stderr[-1000:]}"
        )


def _run_lifecycle(
    manager: ProfileSandboxManager, fixture: Fixture, marker: Path, started: Path
) -> None:
    payload = LIFECYCLE_PAYLOAD.replace("__MARKER__", str(marker)).replace(
        "__STARTED__", str(started)
    )
    command, environment = _command(
        manager,
        fixture,
        payload,
        listener_fd=-1,
        marker=uuid4().hex,
    )
    process = subprocess.Popen(
        command,
        cwd=environment["PWD"],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 8
        while not started.exists() and process.poll() is None:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        assert started.exists(), "namespace child did not start"
        process.kill()
        process.wait(timeout=8)
        time.sleep(1.5)
        assert not marker.exists(), "namespace descendant survived parent death"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=8)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def _run_http_lifecycle(fixture: Fixture) -> None:
    from aiohttp import ClientSession, ClientTimeout, UnixConnector
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    previous_bridge = os.environ.get("ALLIES_PUBLICATION_SOCKET")
    os.environ["ALLIES_PUBLICATION_SOCKET"] = str(fixture.bridge)
    adapter = APIServerAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "host": "127.0.0.1",
                "port": 0,
                "key": "synthetic-profile-secret",
            },
        )
    )

    async def exercise() -> None:
        manager = adapter._allies_profile_sandbox
        target_state = await manager.ensure(fixture.target)
        sibling_state = await manager.ensure(fixture.sibling)
        assert target_state.process.pid != sibling_state.process.pid
        assert manager.profile_process_count() == 2

        async def check_sessions(state) -> None:
            connector = UnixConnector(path=str(state.listener_path))
            headers = {
                "Authorization": "Bearer synthetic-profile-secret",
                "X-Allies-Profile-Forwarded": state.marker,
            }
            async with (
                ClientSession(
                    connector=connector,
                    timeout=ClientTimeout(total=10),
                ) as client,
                client.get(
                    "http://profile-worker/api/sessions", headers=headers
                ) as response,
            ):
                body = await response.text()
                assert response.status == 200, body
                assert (await response.json())["object"] == "list"

        try:
            await check_sessions(target_state)
            await check_sessions(sibling_state)
            assert await manager._child_is_idle(target_state)
            target_state.active_requests = 1
            assert not await manager._child_is_idle(target_state)
            target_state.active_requests = 0

            headers = {
                "Authorization": "Bearer synthetic-profile-secret",
                "X-Allies-Profile-Forwarded": target_state.marker,
            }
            connector = UnixConnector(path=str(target_state.listener_path))
            async with ClientSession(
                connector=connector,
                timeout=ClientTimeout(total=10),
            ) as client:
                async with client.get(
                    "http://profile-worker/health", headers=headers
                ) as response:
                    assert response.status == 404
                bad_headers = {
                    **headers,
                    "X-Allies-Profile-Forwarded": "wrong-marker",
                }
                async with client.get(
                    "http://profile-worker/api/sessions", headers=bad_headers
                ) as response:
                    assert response.status == 404
            with patch("allies_profile_sandbox.MAX_ACTIVE_PROFILE_PROCESSES", 1):
                expired = time.monotonic() - manager._idle_reap_seconds() - 1
                target_state.last_used = sibling_state.last_used = expired
                target_state.active_requests = sibling_state.active_requests = 1
                await manager._reap_idle_locked()
                assert manager.profile_process_count() == 2
                target_state.active_requests = 0
                await manager._reap_idle_locked()
                assert manager.profile_process_count() == 1
                sibling_state.active_requests = 0
            assert await manager.stop_profile(fixture.target)
            assert target_state.process.poll() is not None
            assert not target_state.listener_path.exists()
            assert manager.profile_process_count() == 1
            await check_sessions(sibling_state)
        finally:
            assert await manager.stop_profile(fixture.target)
            assert await manager.stop_profile(fixture.sibling)
            assert sibling_state.process.poll() is not None
            assert not sibling_state.listener_path.exists()
            await adapter.disconnect()

    try:
        asyncio.run(exercise())
    finally:
        if previous_bridge is None:
            os.environ.pop("ALLIES_PUBLICATION_SOCKET", None)
        else:
            os.environ["ALLIES_PUBLICATION_SOCKET"] = previous_bridge


def _cleanup(fixture: Fixture) -> None:
    fixture.server.close()
    for path in (
        fixture.home,
        fixture.sibling_home,
        fixture.runtime_secret,
        fixture.bridge_dir,
    ):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)


def _check_legacy_links(fixture: Fixture) -> None:
    alias = fixture.home / "workspace" / "legacy-link"
    for filename in PROFILE_MANAGED_FILES:
        os.link(fixture.home / filename, alias)
        try:
            try:
                _validate_profile_hardlinks(fixture.home)
            except ProfileSandboxUnavailable as error:
                assert str(error) == "profile_managed_file_alias"
            else:
                raise AssertionError("managed hardlink passed startup validation")
        finally:
            alias.unlink()
    os.link(fixture.runtime_secret, alias)
    try:
        try:
            _validate_profile_hardlinks(fixture.home)
        except ProfileSandboxUnavailable as error:
            assert str(error) == "profile_external_hardlink"
        else:
            raise AssertionError("external hardlink passed startup validation")
    finally:
        alias.unlink()
    own_file = fixture.home / "workspace" / "ordinary-file"
    own_file.write_text("private")
    os.link(own_file, alias)
    try:
        _validate_profile_hardlinks(fixture.home)
    finally:
        alias.unlink()
        own_file.unlink()


def main() -> None:
    root_fixture = os.geteuid() == 0
    if not root_fixture:
        assert os.geteuid() == 10000, os.geteuid()
        assert 10001 in os.getgroups(), os.getgroups()
    fixture = _create_fixture(root_owned=root_fixture)
    _check_legacy_links(fixture)
    if root_fixture:
        _drop_to_profile_user()
    assert os.geteuid() == 10000, os.geteuid()
    assert 10001 in os.getgroups(), os.getgroups()
    manager = ProfileSandboxManager(SimpleNamespace())
    if not manager.preflight():
        for diagnostic in (
            "/proc/self/attr/current",
            "/proc/sys/kernel/unprivileged_userns_clone",
            "/proc/sys/kernel/apparmor_restrict_unprivileged_userns",
            "/proc/sys/user/max_user_namespaces",
        ):
            try:
                print(f"{diagnostic}: {Path(diagnostic).read_text().strip()}", flush=True)
            except OSError:
                pass
        raise AssertionError(manager.readiness())
    assert manager.readiness()["status"] == "ready"
    try:
        _check_routes(manager, fixture.target)
        payload = _payload(BOUNDARY_PAYLOAD, fixture)
        left, right = socket.socketpair()
        try:
            os.set_inheritable(right.fileno(), True)
            command, environment = _command(
                manager,
                fixture,
                payload,
                listener_fd=right.fileno(),
                marker=uuid4().hex,
            )
            _run(command, environment, pass_fds=(right.fileno(),))
            left.settimeout(5)
            assert left.recv(64) == b"private"
        finally:
            left.close()
            right.close()
        publication_connection, _ = fixture.server.accept()
        with publication_connection:
            publication_connection.settimeout(5)
            assert publication_connection.recv(64) == b"publication"
        _run_http_lifecycle(fixture)
        _run_lifecycle(
            manager,
            fixture,
            fixture.home / "orphan.txt",
            fixture.home / "orphan-started.txt",
        )
    finally:
        _cleanup(fixture)
    print(
        "Workspace namespace boundary: UID10000 mounts, routes, transport, and reap passed"
    )


if __name__ == "__main__":
    main()
