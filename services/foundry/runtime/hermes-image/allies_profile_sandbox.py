"""Process and mount boundary for profile-local Hermes API workers."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import select
import shutil
import socket
import stat
import subprocess
import tempfile
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from aiohttp import ClientError, ClientSession, ClientTimeout, UnixConnector, web
except ImportError:  # pragma: no cover - aiohttp is in the Hermes image.
    ClientError = OSError
    ClientSession = ClientTimeout = UnixConnector = web = None


logger = logging.getLogger(__name__)

PROFILE_KEY_RE = re.compile(r"ally-v1-[0-9a-f]{32}\Z")
ENV_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
SANDBOX_EXECUTABLE = "bwrap"
SANDBOX_STARTUP_SECONDS = 15.0
SANDBOX_STOP_SECONDS = 5.0
MAX_FORWARD_BODY_BYTES = 10_000_000
MAX_FORWARD_RESPONSE_BYTES = 10_000_000
MAX_FORWARD_CHUNK_BYTES = 64 * 1024
MAX_HEALTH_RESPONSE_BYTES = 64 * 1024
MAX_ACTIVE_PROFILE_PROCESSES = 16
MAX_PROFILE_SCAN_ENTRIES = 100_000
MAX_PROFILE_SCAN_SECONDS = 5.0
PROFILE_IDLE_REAP_SECONDS = 300.0

PROFILE_MANAGED_FILES = (".env", "config.yaml", "SOUL.md", ".allies-profile.json")
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

PROFILE_CHILD_ROUTES = frozenset(
    {
        ("GET", "/api/sessions"),
        ("POST", "/api/sessions"),
        ("GET", "/api/sessions/{session_id}"),
        ("PATCH", "/api/sessions/{session_id}"),
        ("DELETE", "/api/sessions/{session_id}"),
        ("GET", "/api/sessions/{session_id}/messages"),
        ("POST", "/api/sessions/{session_id}/fork"),
        ("PUT", "/api/sessions/{session_id}/bootstrap"),
        ("POST", "/api/sessions/{session_id}/chat"),
        ("POST", "/api/sessions/{session_id}/chat/stream"),
        ("POST", "/api/sessions/{session_id}/approval"),
        ("GET", "/api/sessions/{session_id}/approval/{hermes_approval_id}"),
        ("POST", "/api/sessions/{session_id}/model"),
        ("POST", "/v1/chat/completions"),
        ("POST", "/v1/responses"),
        ("GET", "/v1/responses/{response_id}"),
        ("DELETE", "/v1/responses/{response_id}"),
        ("GET", "/api/jobs"),
        ("POST", "/api/jobs"),
        ("GET", "/api/jobs/{job_id}"),
        ("PATCH", "/api/jobs/{job_id}"),
        ("DELETE", "/api/jobs/{job_id}"),
        ("POST", "/api/jobs/{job_id}/pause"),
        ("POST", "/api/jobs/{job_id}/resume"),
        ("POST", "/api/jobs/{job_id}/run"),
        ("POST", "/api/cron/fire"),
        ("POST", "/v1/runs"),
        ("GET", "/v1/runs/{run_id}"),
        ("GET", "/v1/runs/{run_id}/events"),
        ("POST", "/v1/runs/{run_id}/approval"),
        ("POST", "/v1/runs/{run_id}/stop"),
    }
)
PROFILE_PARENT_ROUTES = frozenset(
    {
        ("GET", "/health"),
        ("GET", "/health/detailed"),
        ("GET", "/v1/health"),
        ("GET", "/v1/models"),
        ("GET", "/api/model/options"),
        ("GET", "/v1/capabilities"),
        ("GET", "/v1/skills"),
        ("GET", "/v1/toolsets"),
        ("POST", "/v1/profiles/{profile_key}/quiesce"),
    }
)
PROFILE_DENIED_ROUTES = frozenset(
    {
        ("POST", "/api/platforms/{platform}/events"),
    }
)
ALL_PROFILE_ROUTES = (
    PROFILE_CHILD_ROUTES | PROFILE_PARENT_ROUTES | PROFILE_DENIED_ROUTES
)
_QUIESCE_ROUTE = ("POST", "/v1/profiles/{profile_key}/quiesce")

_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_FORWARD_HEADER_PREFIXES = ("x-hermes-", "x-allies-")
_FORWARD_HEADERS = frozenset(
    {
        "accept",
        "accept-encoding",
        "authorization",
        "cache-control",
        "content-type",
        "if-match",
        "if-none-match",
        "idempotency-key",
        "last-event-id",
        "origin",
        "user-agent",
    }
)
_CONTROL_ENV_NAMES = frozenset(
    {
        "ALLIES_PROFILE_SANDBOX_CHILD",
        "ALLIES_PROFILE_SANDBOX_LISTENER_FD",
        "ALLIES_PROFILE_SANDBOX_READY_FD",
        "ALLIES_PROFILE_SANDBOX_MARKER",
        "ALLIES_PROFILE_SANDBOX_PROFILE",
        "API_SERVER_CORS_ORIGINS",
        "API_SERVER_ENABLED",
        "API_SERVER_HOST",
        "API_SERVER_PORT",
        "HOME",
        "HERMES_HOME",
        "HERMES_PROFILE",
        "ALLIES_PROFILE_WORKSPACE",
        "ALLIES_PROFILE_PUBLICATION_BASE",
        "PATH",
        "PWD",
        "PYTHONPATH",
        "TMPDIR",
        "TERMINAL_CWD",
        "XDG_CACHE_HOME",
    }
)


class ProfileSandboxUnavailable(RuntimeError):
    """A profile worker cannot be admitted safely."""


@dataclass
class ProfileSandboxProcess:
    profile_key: str
    home: Path
    workspace: Path
    listener_path: Path
    temp_dir: Path
    marker: str
    process: subprocess.Popen
    started_at: float
    managed_signature: tuple
    last_used: float = 0.0
    active_requests: int = 0
    ready: bool = False


def is_profile_sandbox_child() -> bool:
    return os.environ.get("ALLIES_PROFILE_SANDBOX_CHILD") == "1"


def child_profile_key() -> str:
    if not is_profile_sandbox_child():
        raise ProfileSandboxUnavailable("child_profile_unavailable")
    profile_key = os.environ.get("ALLIES_PROFILE_SANDBOX_PROFILE", "")
    if not PROFILE_KEY_RE.fullmatch(profile_key):
        raise ProfileSandboxUnavailable("child_profile_unavailable")
    return profile_key


def profile_scope_matches(
    route_profile: str | None, scoped_profile: str | None
) -> bool:
    if not scoped_profile or scoped_profile == "default":
        logger.warning(
            "event=profile_scope_rejected child=%s has_scope=%s default_scope=%s has_route=%s",
            is_profile_sandbox_child(),
            bool(scoped_profile),
            scoped_profile == "default",
            bool(route_profile),
        )
        return False
    if is_profile_sandbox_child():
        matched = not route_profile and child_profile_key() == scoped_profile
    else:
        matched = route_profile == scoped_profile
    if not matched:
        logger.warning(
            "event=profile_scope_rejected child=%s has_scope=true default_scope=false has_route=%s",
            is_profile_sandbox_child(),
            bool(route_profile),
        )
    return matched


def _route_regex(template: str) -> re.Pattern[str]:
    parts = []
    for part in template.split("/"):
        parts.append(
            "[^/]+" if part.startswith("{") and part.endswith("}") else re.escape(part)
        )
    return re.compile("^" + "/".join(parts) + "$")


_ROUTE_PATTERNS = tuple(
    (method, path, _route_regex(path)) for method, path in sorted(ALL_PROFILE_ROUTES)
)


def route_owner(method: str, path: str) -> tuple[str, str, bool]:
    """Return ``(owner, route_template, prefixed)`` for an API request."""

    method = str(method or "").upper()
    path = str(path or "").split("?", 1)[0] or "/"
    prefixed = False
    prefix = re.match(r"^/p/[^/]+(?=/|$)", path)
    if prefix:
        prefixed = True
        path = path[prefix.end() :] or "/"
    for route_method, template, pattern in _ROUTE_PATTERNS:
        if route_method == method and pattern.fullmatch(path):
            if (method, template) in PROFILE_CHILD_ROUTES:
                return "child", template, prefixed
            if (method, template) in PROFILE_PARENT_ROUTES:
                return "parent", template, prefixed
            return "denied", template, prefixed
    return "denied", "", prefixed


def _profile_root() -> Path:
    from hermes_cli.profiles import _get_profiles_root

    root = Path(_get_profiles_root())
    if root.is_symlink():
        raise ProfileSandboxUnavailable("unsafe_profiles_root")
    try:
        return root.resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise ProfileSandboxUnavailable("profiles_root_unavailable") from None


def _safe_profile_home(profile_key: str) -> Path:
    if not PROFILE_KEY_RE.fullmatch(profile_key or ""):
        raise ProfileSandboxUnavailable("invalid_profile_key")
    root = _profile_root()
    candidate = root / profile_key
    if candidate.is_symlink() or candidate.parent.is_symlink():
        raise ProfileSandboxUnavailable("unsafe_profile_directory")
    try:
        home = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise ProfileSandboxUnavailable("profile_unavailable") from None
    if home.parent != root or not home.is_dir():
        raise ProfileSandboxUnavailable("unsafe_profile_directory")
    return home


def _safe_regular(path: Path) -> bool:
    try:
        return not path.is_symlink() and stat.S_ISREG(
            path.stat(follow_symlinks=False).st_mode
        )
    except OSError:
        return False


def _safe_directory(path: Path) -> bool:
    try:
        return not path.is_symlink() and stat.S_ISDIR(
            path.stat(follow_symlinks=False).st_mode
        )
    except OSError:
        return False


def _validate_profile_hardlinks(home: Path, *, deadline: float | None = None) -> None:
    """Reject regular-file aliases that leave the selected profile.

    The profile bind mount hides sibling names, but it cannot revoke an
    existing hardlink to an inode that is also reachable from the host volume.
    Walk only real directories (never symlinks), count every regular-file name
    in the profile, and compare that count with the inode's link count. Any
    mismatch or scan-budget exhaustion fails closed before a worker starts.
    """

    # Managed inodes must have no writable aliases beneath their read-only mounts.
    for filename in PROFILE_MANAGED_FILES:
        try:
            info = (home / filename).stat(follow_symlinks=False)
        except OSError:
            raise ProfileSandboxUnavailable("profile_link_scan_failed") from None
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ProfileSandboxUnavailable("profile_managed_file_alias")

    links: dict[tuple[int, int], tuple[int, int]] = {}
    pending = [home]
    visited = 0
    while pending:
        directory = pending.pop()
        try:
            entries = os.scandir(directory)
        except OSError:
            raise ProfileSandboxUnavailable("profile_link_scan_failed") from None
        try:
            for entry in entries:
                visited += 1
                if visited > MAX_PROFILE_SCAN_ENTRIES or (
                    deadline is not None and time.monotonic() > deadline
                ):
                    raise ProfileSandboxUnavailable(
                        "profile_link_scan_budget_exhausted"
                    )
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    raise ProfileSandboxUnavailable(
                        "profile_link_scan_failed"
                    ) from None
                mode = info.st_mode
                if stat.S_ISLNK(mode):
                    continue
                if stat.S_ISDIR(mode):
                    pending.append(Path(entry.path))
                    continue
                if not stat.S_ISREG(mode):
                    continue
                inode = (int(info.st_dev), int(info.st_ino))
                count, nlink = links.get(inode, (0, int(info.st_nlink)))
                count += 1
                if count > nlink:
                    raise ProfileSandboxUnavailable("profile_link_scan_changed")
                links[inode] = (count, nlink)
        finally:
            entries.close()
    if any(count != nlink for count, nlink in links.values()):
        raise ProfileSandboxUnavailable("profile_external_hardlink")


def _profile_secrets(home: Path) -> dict[str, str]:
    try:
        from agent.secret_scope import load_env_file

        values = load_env_file(home / ".env")
    except (ImportError, OSError, TypeError, UnicodeError, ValueError):
        return {}
    return {
        str(key): value
        for key, value in values.items()
        if ENV_KEY_RE.fullmatch(str(key) or "") and isinstance(value, str)
    }


def _base_environment(
    home: Path, profile_key: str, marker: str, listener_fd: int, ready_fd: int
) -> dict[str, str]:
    """Build a child environment without inheriting the parent's secrets."""

    env: dict[str, str] = {
        "PATH": os.environ.get(
            "PATH", "/opt/hermes/bin:/opt/hermes/.venv/bin:/usr/local/bin:/usr/bin:/bin"
        ),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "TZ": os.environ.get("TZ", "UTC"),
        "SSL_CERT_FILE": os.environ.get(
            "SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt"
        ),
        "PYTHONUNBUFFERED": "1",
        "HERMES_HOME": f"/opt/data/profiles/{profile_key}",
        "HERMES_PROFILE": profile_key,
        "HOME": f"/opt/data/profiles/{profile_key}/home",
        "PWD": f"/opt/data/profiles/{profile_key}/workspace",
        "TERMINAL_CWD": f"/opt/data/profiles/{profile_key}/workspace",
        "ALLIES_PROFILE_WORKSPACE": f"/opt/data/profiles/{profile_key}/workspace",
        "ALLIES_PROFILE_PUBLICATION_BASE": f"/opt/data/profiles/{profile_key}/workspace",
        "TMPDIR": "/tmp",
        "XDG_CACHE_HOME": f"/opt/data/profiles/{profile_key}/cache",
        "PYTHONPATH": "/opt/hermes",
        "API_SERVER_ENABLED": "1",
        "API_SERVER_HOST": "127.0.0.1",
        "API_SERVER_PORT": "0",
        "ALLIES_PROFILE_SANDBOX_CHILD": "1",
        "ALLIES_PROFILE_SANDBOX_PROFILE": profile_key,
        "ALLIES_PROFILE_SANDBOX_MARKER": marker,
        "ALLIES_PROFILE_SANDBOX_LISTENER_FD": str(listener_fd),
        "ALLIES_PROFILE_SANDBOX_READY_FD": str(ready_fd),
    }
    secrets = _profile_secrets(home)
    for key, value in secrets.items():
        if key not in _CONTROL_ENV_NAMES and not key.startswith("LD_"):
            env[key] = value
    if secrets.get("API_SERVER_KEY"):
        env["API_SERVER_KEY"] = secrets["API_SERVER_KEY"]
    return env


def child_workspace_path() -> str:
    """Return the canonical workspace path for the current child profile.

    ``terminal.cwd`` is a user-configurable value and Hermes' config bridge
    intentionally gives it precedence over ``TERMINAL_CWD``.  A child worker
    must not inherit that process-wide override: the namespace's only writable
    project root is its own profile workspace.  Keep this check in one helper
    so both prompt construction and session ContextVar binding use the same
    invariant.
    """

    profile_key = child_profile_key()
    expected = f"/opt/data/profiles/{profile_key}/workspace"
    workspace = os.environ.get("ALLIES_PROFILE_WORKSPACE", expected)
    if workspace != expected or not _safe_directory(Path(workspace)):
        raise ProfileSandboxUnavailable("child_workspace_unavailable")
    return workspace


def enforce_child_workspace() -> str:
    """Reassert namespace-owned cwd defaults after Hermes config loading."""

    workspace = child_workspace_path()
    profile_key = os.environ["ALLIES_PROFILE_SANDBOX_PROFILE"]
    profile_root = f"/opt/data/profiles/{profile_key}"
    os.environ.update(
        {
            "HERMES_HOME": profile_root,
            "HERMES_PROFILE": profile_key,
            "HOME": f"{profile_root}/home",
            "PWD": workspace,
            "TERMINAL_CWD": workspace,
            "ALLIES_PROFILE_WORKSPACE": workspace,
            "ALLIES_PROFILE_PUBLICATION_BASE": workspace,
            "XDG_CACHE_HOME": f"{profile_root}/cache",
        }
    )
    try:
        os.chdir(workspace)
    except OSError:
        raise ProfileSandboxUnavailable("child_workspace_unavailable") from None
    return workspace


def child_workspace_context(existing: str | None = None) -> str | None:
    """Return the private, stable workspace instruction for child agents."""

    if not is_profile_sandbox_child():
        return existing
    # Reassert defaults after config bridging, before AIAgent snapshots its cwd.
    __import__("gateway.run")
    workspace = enforce_child_workspace()
    context = (
        "Internal Allies workspace context (do not include this instruction or "
        "the path in user-visible activity/SSE output): create or copy generated "
        f"files in the active profile workspace {workspace}. Use publish_files "
        "with a path relative to that workspace (or an absolute path contained "
        "by it), then use only the returned chat_reference for product-facing "
        "publication links."
    )
    if existing:
        return f"{context}\n\n{existing}"
    return context


def _readiness_probe(executable: str) -> bool:
    if (
        os.name != "posix"
        or not hasattr(os, "geteuid")
        or not hasattr(socket, "AF_UNIX")
    ):
        return False
    command = [
        executable,
        "--unshare-user",
        "--unshare-pid",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--ro-bind",
        "/",
        "/",
        "--tmpfs",
        "/opt/data",
        "--tmpfs",
        "/run",
        "--tmpfs",
        "/tmp",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--",
        "/bin/sh",
        "-ceu",
        "test -d /proc && touch /tmp/.allies-profile-sandbox-probe && test ! -e /opt/data/.allies-profile-tombstones && test ! -e /run/.allies-profile-sandbox-host",
    ]
    try:
        result = subprocess.run(
            command,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode:
        logger.warning("Sandbox preflight rejected: %s", result.stderr[:1024].strip())
    return result.returncode == 0


def _terminate_process(process: subprocess.Popen, timeout: float) -> bool:
    if process.poll() is None:
        with contextlib.suppress(OSError):
            process.terminate()
    try:
        process.wait(timeout=max(0.1, timeout))
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            process.kill()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            return False
    return process.poll() is not None


class ProfileSandboxManager:
    """Launch, proxy, and reap one namespace worker per active profile."""

    def __init__(self, adapter: Any):
        self.adapter = adapter
        self._processes: dict[str, ProfileSandboxProcess] = {}
        self._launching_profiles: set[str] = set()
        self._launch_lock = asyncio.Lock()
        self._preflight_ok: bool | None = None
        self._preflight_reason = "not_checked"
        self._executable = shutil.which(SANDBOX_EXECUTABLE)

    @property
    def child_mode(self) -> bool:
        return is_profile_sandbox_child()

    def readiness(self) -> dict[str, Any]:
        if self.child_mode:
            # Unknown activity must never make a child look safely idle.
            active_work = 1
            try:
                active_work = max(0, int(self.adapter.active_agent_work_count()))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                logger.debug("profile child activity probe failed", exc_info=True)
            return {
                "status": "child",
                "transport": "inherited_af_unix",
                "active_agent_work": active_work,
            }
        return {
            "status": "ready" if self._preflight_ok else "unavailable",
            "transport": "private_inherited_af_unix",
            "executable": bool(self._executable),
            "reason": "" if self._preflight_ok else self._preflight_reason,
            "active_profiles": len(self._processes),
            "max_active_profiles": MAX_ACTIVE_PROFILE_PROCESSES,
            "idle_reap_seconds": self._idle_reap_seconds(),
        }

    def profile_process_count(self, profile_key: str | None = None) -> int:
        """Return a conservative count for deletion/quiescence proofing."""

        if profile_key is not None:
            return int(
                profile_key in self._processes
                or profile_key in self._launching_profiles
            )
        return len(set(self._processes) | self._launching_profiles)

    @staticmethod
    def _idle_reap_seconds() -> float:
        raw = os.environ.get("ALLIES_PROFILE_SANDBOX_IDLE_SECONDS", "")
        try:
            value = float(raw) if raw else PROFILE_IDLE_REAP_SECONDS
        except ValueError:
            value = PROFILE_IDLE_REAP_SECONDS
        return max(1.0, min(value, 3600.0))

    def preflight(self, *, force: bool = False) -> bool:
        if self.child_mode:
            return True
        if self._preflight_ok is not None and not force:
            return self._preflight_ok
        self._executable = shutil.which(SANDBOX_EXECUTABLE)
        if not self._executable:
            self._preflight_reason = "sandbox_executable_unavailable"
            self._preflight_ok = False
            return False
        if not _readiness_probe(self._executable):
            self._preflight_reason = "sandbox_namespace_unavailable"
            self._preflight_ok = False
            return False
        self._preflight_reason = ""
        self._preflight_ok = True
        return True

    @staticmethod
    def validate_routes(routes: Iterable[tuple]) -> str | None:
        seen = set()
        for row in routes:
            if len(row) < 2:
                return "invalid_route_row"
            method, path = str(row[0]).upper(), str(row[1])
            key = (method, path)
            if key in seen:
                return "duplicate_route"
            seen.add(key)
            if key not in ALL_PROFILE_ROUTES:
                return "unclassified_route"
        return None

    @staticmethod
    def child_listener_socket() -> socket.socket:
        try:
            fd = int(os.environ["ALLIES_PROFILE_SANDBOX_LISTENER_FD"])
            child_socket = socket.socket(fileno=fd)
            child_socket.setblocking(False)
            return child_socket
        except (KeyError, TypeError, ValueError, OSError):
            raise ProfileSandboxUnavailable("child_listener_unavailable") from None

    @staticmethod
    def notify_child_ready(success: bool) -> None:
        try:
            fd = int(os.environ.get("ALLIES_PROFILE_SANDBOX_READY_FD", ""))
        except ValueError:
            return
        try:
            os.write(fd, b"ready\n" if success else b"error\n")
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                os.close(fd)

    @staticmethod
    def _validate_profile(home: Path) -> Path:
        for filename in PROFILE_MANAGED_FILES:
            if not _safe_regular(home / filename):
                raise ProfileSandboxUnavailable("profile_control_unavailable")
        for directory in PROFILE_WRITE_DIRECTORIES:
            path = home / directory
            if path.exists() and not _safe_directory(path):
                raise ProfileSandboxUnavailable("unsafe_profile_state")
            if not path.exists():
                try:
                    path.mkdir(mode=0o700)
                except OSError:
                    raise ProfileSandboxUnavailable(
                        "profile_state_unavailable"
                    ) from None
            if not _safe_directory(path):
                raise ProfileSandboxUnavailable("unsafe_profile_state")
        data_dir = home / "mnemosyne" / "data"
        if not data_dir.exists():
            try:
                data_dir.mkdir(mode=0o700)
            except OSError:
                raise ProfileSandboxUnavailable("profile_state_unavailable") from None
        if not _safe_directory(data_dir):
            raise ProfileSandboxUnavailable("unsafe_profile_state")
        workspace = home / "workspace"
        try:
            workspace_resolved = workspace.resolve(strict=True)
        except (FileNotFoundError, OSError):
            raise ProfileSandboxUnavailable("workspace_unavailable") from None
        if workspace_resolved.parent != home or not _safe_directory(workspace):
            raise ProfileSandboxUnavailable("unsafe_workspace")
        try:
            with tempfile.NamedTemporaryFile(
                prefix=".allies-sandbox-", dir=home, delete=True
            ):
                pass
        except OSError:
            raise ProfileSandboxUnavailable("profile_state_unwritable") from None
        return workspace_resolved

    @staticmethod
    def _publication_bridge() -> Path | None:
        raw = os.environ.get(
            "ALLIES_PUBLICATION_SOCKET", "/opt/data/.allies-publication-bridge/socket"
        )
        if not raw.startswith("/") or ".." in Path(raw).parts:
            return None
        return Path(raw)

    def _validate_bridge(self) -> Path:
        bridge = self._publication_bridge()
        if bridge is None or bridge.is_symlink() or not bridge.exists():
            raise ProfileSandboxUnavailable("publication_bridge_unavailable")
        try:
            mode = bridge.stat(follow_symlinks=False).st_mode
            parent_mode = bridge.parent.stat(follow_symlinks=False).st_mode
            entries = {entry.name for entry in bridge.parent.iterdir()}
        except OSError:
            raise ProfileSandboxUnavailable("publication_bridge_unavailable") from None
        if (
            not stat.S_ISSOCK(mode)
            or not stat.S_ISDIR(parent_mode)
            or bridge.parent.is_symlink()
            or entries != {bridge.name}
        ):
            raise ProfileSandboxUnavailable("publication_bridge_unavailable")
        return bridge

    def _command(
        self,
        home: Path,
        profile_key: str,
        listener_fd: int,
        ready_fd: int,
        marker: str,
        bridge: Path,
    ) -> tuple[list[str], dict[str, str]]:
        guest_home = f"/opt/data/profiles/{profile_key}"
        command = [
            self._executable or SANDBOX_EXECUTABLE,
            "--unshare-user",
            "--unshare-pid",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            "--ro-bind",
            "/",
            "/",
            "--tmpfs",
            "/opt/data",
            "--dir",
            "/opt/data/profiles",
            "--bind",
            str(home),
            guest_home,
        ]
        for filename in PROFILE_MANAGED_FILES:
            command.extend(
                ["--ro-bind", str(home / filename), f"{guest_home}/{filename}"]
            )
        command.extend(
            [
                "--tmpfs",
                "/run",
                "--tmpfs",
                "/tmp",
                "--tmpfs",
                "/var/tmp",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                # Socket connections need no writable mount or host permission change.
                "--ro-bind",
                str(bridge.parent),
                "/opt/data/.allies-publication-bridge",
                "--remount-ro",
                "/opt/data",
                "--chdir",
                f"{guest_home}/workspace",
                "--",
                "/opt/hermes/.venv/bin/python",
                "/opt/hermes/allies_profile_sandbox_launcher.py",
            ]
        )
        return command, _base_environment(
            home, profile_key, marker, listener_fd, ready_fd
        )

    async def ensure(self, profile_key: str) -> ProfileSandboxProcess:
        if self.child_mode:
            raise ProfileSandboxUnavailable("child_cannot_launch_worker")
        if not self.preflight():
            raise ProfileSandboxUnavailable(self._preflight_reason)
        async with self._launch_lock:
            home = _safe_profile_home(profile_key)
            workspace = self._validate_profile(home)
            managed_signature = self._managed_signature(home)
            existing = self._processes.get(profile_key)
            if existing is not None and existing.process.poll() is None:
                if not existing.ready:
                    raise ProfileSandboxUnavailable("profile_worker_stop_pending")
                if existing.managed_signature == managed_signature:
                    self._touch(existing)
                    return existing
                if not await self._child_is_idle(existing):
                    raise ProfileSandboxUnavailable("profile_worker_busy")
                if not await asyncio.to_thread(
                    _terminate_process, existing.process, SANDBOX_STOP_SECONDS
                ):
                    raise ProfileSandboxUnavailable("profile_worker_stop_failed")
                self._processes.pop(profile_key, None)
                await self._discard(existing)
            if existing is not None:
                await self._discard(existing)
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        _validate_profile_hardlinks,
                        home,
                        deadline=time.monotonic() + MAX_PROFILE_SCAN_SECONDS,
                    ),
                    timeout=MAX_PROFILE_SCAN_SECONDS + 1.0,
                )
            except TimeoutError:
                raise ProfileSandboxUnavailable("profile_link_scan_timeout") from None
            bridge = self._validate_bridge()
            if len(self._processes) >= MAX_ACTIVE_PROFILE_PROCESSES:
                await self._reap_idle_locked()
            if len(self._processes) >= MAX_ACTIVE_PROFILE_PROCESSES:
                raise ProfileSandboxUnavailable("profile_sandbox_capacity")
            temp_dir = Path(
                tempfile.mkdtemp(prefix="allies-profile-sandbox-", dir="/tmp")
            )
            listener_path = temp_dir / "listener.sock"
            listener: socket.socket | None = None
            ready_read: int | None = None
            ready_write: int | None = None
            process: subprocess.Popen | None = None
            marker = os.urandom(16).hex()
            self._launching_profiles.add(profile_key)
            try:
                listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                listener.bind(str(listener_path))
                os.chmod(listener_path, 0o600)
                listener.listen(64)
                ready_read, ready_write = os.pipe()
                os.set_inheritable(listener.fileno(), True)
                os.set_inheritable(ready_write, True)
                command, env = self._command(
                    home, profile_key, listener.fileno(), ready_write, marker, bridge
                )
                # Spawn and register atomically so cancellation cannot lose ownership.
                process = subprocess.Popen(  # noqa: ASYNC220
                    command,
                    cwd=str(workspace),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    pass_fds=(listener.fileno(), ready_write),
                    start_new_session=True,
                )
                state = ProfileSandboxProcess(
                    profile_key,
                    home,
                    workspace,
                    listener_path,
                    temp_dir,
                    marker,
                    process,
                    time.monotonic(),
                    managed_signature,
                )
                self._processes[profile_key] = state
                os.close(ready_write)
                ready_write = None
                listener.close()
                listener = None
                ready = await asyncio.to_thread(self._wait_ready, ready_read, process)
                os.close(ready_read)
                ready_read = None
                if not ready or process.poll() is not None:
                    raise ProfileSandboxUnavailable("profile_worker_start_failed")
                state.ready = True
                self._touch(state)
                return state
            except ProfileSandboxUnavailable:
                raise
            except (OSError, subprocess.SubprocessError):
                raise ProfileSandboxUnavailable("profile_worker_start_failed") from None
            finally:
                self._launching_profiles.discard(profile_key)
                if listener is not None:
                    with contextlib.suppress(OSError):
                        listener.close()
                for fd in (ready_read, ready_write):
                    if fd is not None:
                        with contextlib.suppress(OSError):
                            os.close(fd)
                state = self._processes.get(profile_key)
                if state is not None and not state.ready:
                    # A failed stop stays owned and visible to deletion proofs.
                    await self._stop_state_locked(state, timeout=SANDBOX_STOP_SECONDS)
                if profile_key not in self._processes:
                    with contextlib.suppress(OSError):
                        listener_path.unlink()
                    with contextlib.suppress(OSError):
                        temp_dir.rmdir()

    @staticmethod
    def _wait_ready(fd: int, process: subprocess.Popen) -> bool:
        try:
            readable, _, _ = select.select([fd], [], [], SANDBOX_STARTUP_SECONDS)
            if not readable:
                return False
            return os.read(fd, 64).startswith(b"ready") and process.poll() is None
        except (OSError, ValueError):
            return False

    async def _discard(self, state: ProfileSandboxProcess) -> None:
        with contextlib.suppress(OSError):
            state.listener_path.unlink()
        with contextlib.suppress(OSError):
            state.temp_dir.rmdir()

    @staticmethod
    def _touch(state: ProfileSandboxProcess) -> None:
        state.last_used = time.monotonic()

    def _mark_request_started(self, state: ProfileSandboxProcess) -> None:
        state.active_requests += 1
        self._touch(state)
        task = asyncio.current_task()
        if task is not None:
            task.add_done_callback(lambda _: self._mark_request_finished(state))

    @staticmethod
    def _mark_request_finished(state: ProfileSandboxProcess) -> None:
        state.active_requests = max(0, state.active_requests - 1)

    async def _child_is_idle(self, state: ProfileSandboxProcess) -> bool:
        """Ask the child adapter for real work counts before reaping it."""

        if state.active_requests or state.process.poll() is not None:
            return False
        if ClientSession is None or ClientTimeout is None or UnixConnector is None:
            return False
        api_key = _profile_secrets(state.home).get("API_SERVER_KEY")
        if not api_key:
            return False
        try:
            connector = UnixConnector(path=str(state.listener_path), force_close=True)
            timeout = ClientTimeout(total=2, sock_connect=1, sock_read=1)
            headers = {
                "Authorization": f"Bearer {api_key}",
                "X-Allies-Profile-Forwarded": state.marker,
                "X-Allies-Profile-Internal-Status": state.marker,
            }
            async with (
                ClientSession(
                    connector=connector, timeout=timeout, auto_decompress=False
                ) as session,
                session.get(
                    "http://profile-worker/health/detailed", headers=headers
                ) as response,
            ):
                if response.status != 200:
                    return False
                body = await response.content.read(MAX_HEALTH_RESPONSE_BYTES + 1)
                if len(body) > MAX_HEALTH_RESPONSE_BYTES:
                    return False
                payload = json.loads(body)
        except (ClientError, TimeoutError, OSError, RuntimeError, ValueError):
            return False
        if not isinstance(payload, dict):
            return False
        try:
            readiness = payload.get("readiness", {})
            sandbox = readiness.get("profile_sandbox", {})
            checks = readiness.get("checks", {})
            queues = checks.get("background_queues", {})
            return all(
                (
                    int(sandbox.get("active_agent_work", 1)) == 0,
                    int(queues.get("active_api_runs", 0)) == 0,
                    int(queues.get("process_completions", 0)) == 0,
                    int(queues.get("active_delegations", 0)) == 0,
                )
            )
        except (AttributeError, TypeError, ValueError):
            return False

    async def _stop_state_locked(
        self, state: ProfileSandboxProcess, *, timeout: float
    ) -> bool:
        stopped = await asyncio.to_thread(_terminate_process, state.process, timeout)
        if not stopped:
            return False
        if self._processes.get(state.profile_key) is state:
            self._processes.pop(state.profile_key, None)
        await self._discard(state)
        return True

    async def _reap_idle_locked(self) -> None:
        """Free capacity only for workers proven inactive by their adapter."""

        if len(self._processes) < MAX_ACTIVE_PROFILE_PROCESSES:
            return
        now = time.monotonic()
        candidates = sorted(self._processes.values(), key=lambda state: state.last_used)
        for state in candidates:
            if len(self._processes) < MAX_ACTIVE_PROFILE_PROCESSES:
                return
            if (
                state.active_requests
                or now - state.last_used < self._idle_reap_seconds()
            ):
                continue
            if state.process.poll() is not None:
                self._processes.pop(state.profile_key, None)
                await self._discard(state)
                continue
            if not await self._child_is_idle(state):
                continue
            await self._stop_state_locked(state, timeout=SANDBOX_STOP_SECONDS)

    @staticmethod
    def _managed_signature(home: Path) -> tuple:
        values = []
        for filename in PROFILE_MANAGED_FILES:
            path = home / filename
            try:
                info = path.stat(follow_symlinks=False)
            except OSError:
                raise ProfileSandboxUnavailable("profile_control_unavailable") from None
            values.append(
                (filename, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            )
        return tuple(values)

    async def stop_profile(
        self, profile_key: str, *, timeout: float = SANDBOX_STOP_SECONDS
    ) -> bool:
        async with self._launch_lock:
            state = self._processes.get(profile_key)
            if state is None:
                return True
            return await self._stop_state_locked(state, timeout=timeout)

    async def close_all(self) -> bool:
        ok = True
        for profile_key in list(self._processes):
            if not await self.stop_profile(profile_key):
                ok = False
        return ok

    @staticmethod
    def _deny(code: str = "profile_sandbox_required"):
        return web.json_response({"error": {"code": code}}, status=404)

    async def dispatch(
        self,
        profile: str | None,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ):
        owner, template, prefixed = route_owner(request.method, request.path)
        if owner == "parent":
            if template == _QUIESCE_ROUTE[1] and prefixed:
                return self._deny("profile_control_parent_only")
            return await handler(request)
        if owner != "child" or not profile:
            return self._deny()
        auth_error = self.adapter._check_auth(request)
        if auth_error is not None:
            return auth_error
        return await self.proxy(profile, request)

    async def handle_child_request(
        self, request: Any, handler: Callable[[Any], Awaitable[Any]]
    ):
        if request.path.startswith("/p/"):
            return self._deny("sandbox_child_prefix_forbidden")
        marker = os.environ.get("ALLIES_PROFILE_SANDBOX_MARKER", "")
        if not marker or request.headers.get("X-Allies-Profile-Forwarded") != marker:
            return self._deny("sandbox_forward_only")
        owner, template, _ = route_owner(request.method, request.path)
        if owner != "child":
            if (
                owner == "parent"
                and request.method == "GET"
                and template == "/health/detailed"
                and request.headers.get("X-Allies-Profile-Internal-Status") == marker
            ):
                return await handler(request)
            return self._deny("sandbox_child_route_forbidden")
        return await handler(request)

    @staticmethod
    def _forward_headers(request: Any, marker: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        for name, value in request.headers.items():
            lower = name.lower()
            if lower in _HOP_BY_HOP_HEADERS:
                continue
            if (
                lower in _FORWARD_HEADERS or lower.startswith(_FORWARD_HEADER_PREFIXES)
            ) and lower != "x-allies-profile-forwarded":
                headers[name] = value
        headers["X-Allies-Profile-Forwarded"] = marker
        return headers

    @staticmethod
    def _response_headers(response: Any, *, streaming: bool) -> dict[str, str]:
        headers: dict[str, str] = {}
        for name, value in response.headers.items():
            lower = name.lower()
            if lower in _HOP_BY_HOP_HEADERS or lower == "content-length":
                continue
            if lower in {
                "cache-control",
                "content-encoding",
                "content-type",
                "etag",
                "last-modified",
                "location",
                "retry-after",
                "vary",
            } or lower.startswith("x-"):
                headers[name] = value
        if streaming:
            headers.setdefault("Cache-Control", "no-cache")
        return headers

    @staticmethod
    def _abort_stream(request: Any) -> None:
        transport = getattr(request, "transport", None)
        if transport is not None:
            transport.close()

    async def proxy(self, profile_key: str, request: Any):
        stream_started = False
        stream_response = None
        try:
            state = await self.ensure(profile_key)
            self._mark_request_started(state)
            body = await request.read()
            if len(body) > MAX_FORWARD_BODY_BYTES:
                return web.json_response(
                    {"error": {"code": "request_too_large"}}, status=413
                )
            path = request.path
            prefix = f"/p/{profile_key}"
            if path == prefix:
                path = "/"
            elif path.startswith(prefix + "/"):
                path = path[len(prefix) :]
            if request.query_string:
                path = f"{path}?{request.query_string}"
            connector = UnixConnector(path=str(state.listener_path), force_close=True)
            timeout = ClientTimeout(total=None, sock_connect=5, sock_read=None)
            async with (
                ClientSession(
                    connector=connector, timeout=timeout, auto_decompress=False
                ) as session,
                session.request(
                    request.method,
                    f"http://profile-worker{path}",
                    headers=self._forward_headers(request, state.marker),
                    data=body if body else None,
                ) as response,
            ):
                content_type = (
                    response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                )
                streaming = content_type == "text/event-stream" or path.endswith(
                    ("/stream", "/events")
                )
                headers = self._response_headers(response, streaming=streaming)
                if streaming:
                    stream_response = web.StreamResponse(
                        status=response.status, headers=headers
                    )
                    await stream_response.prepare(request)
                    stream_started = True
                    async for chunk in response.content.iter_chunked(
                        MAX_FORWARD_CHUNK_BYTES
                    ):
                        await stream_response.write(chunk)
                    await stream_response.write_eof()
                    return stream_response
                payload_parts = []
                payload_size = 0
                while True:
                    chunk = await response.content.read(
                        min(
                            MAX_FORWARD_CHUNK_BYTES,
                            MAX_FORWARD_RESPONSE_BYTES + 1 - payload_size,
                        )
                    )
                    if not chunk:
                        break
                    payload_parts.append(chunk)
                    payload_size += len(chunk)
                    if payload_size > MAX_FORWARD_RESPONSE_BYTES:
                        break
                payload = b"".join(payload_parts)
                if len(payload) > MAX_FORWARD_RESPONSE_BYTES:
                    return web.json_response(
                        {"error": {"code": "profile_response_too_large"}}, status=502
                    )
                return web.Response(
                    status=response.status, body=payload, headers=headers
                )
        except asyncio.CancelledError:
            if stream_started:
                self._abort_stream(request)
            raise
        except ProfileSandboxUnavailable:
            return web.json_response(
                {"error": {"code": "profile_sandbox_unavailable"}},
                status=503,
                headers={"Retry-After": "1"},
            )
        except (ClientError, OSError, RuntimeError, ValueError):
            if stream_started:
                self._abort_stream(request)
                return stream_response
            logger.warning("Profile sandbox request failed safely", exc_info=False)
            return web.json_response(
                {"error": {"code": "profile_sandbox_unavailable"}},
                status=503,
                headers={"Retry-After": "1"},
            )


__all__ = [
    "ALL_PROFILE_ROUTES",
    "PROFILE_CHILD_ROUTES",
    "PROFILE_DENIED_ROUTES",
    "PROFILE_PARENT_ROUTES",
    "ProfileSandboxManager",
    "ProfileSandboxProcess",
    "ProfileSandboxUnavailable",
    "child_profile_key",
    "child_workspace_context",
    "child_workspace_path",
    "enforce_child_workspace",
    "is_profile_sandbox_child",
    "profile_scope_matches",
    "route_owner",
]
