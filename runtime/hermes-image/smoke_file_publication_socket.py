"""Prove the Hermes user can use, but cannot replace, the publication socket."""

from __future__ import annotations

import argparse
import os
import socket
import stat
from pathlib import Path

ROOT = Path("/opt/data/.allies-publication-bridge")
SOCKET = ROOT / "socket"
UID = 10000
GID = 10001


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _server() -> None:
    assert os.geteuid() == 0
    ROOT.mkdir(parents=True, exist_ok=True)
    os.chown(ROOT, 0, GID)
    os.chmod(ROOT, 0o750)
    SOCKET.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(SOCKET))
        os.chown(SOCKET, 0, GID)
        os.chmod(SOCKET, 0o660)
        listener.listen(1)
        assert ROOT.stat().st_uid == 0 and ROOT.stat().st_gid == GID
        assert _mode(ROOT) == 0o750
        assert SOCKET.stat().st_uid == 0 and SOCKET.stat().st_gid == GID
        assert _mode(SOCKET) == 0o660
        print("ready", flush=True)
        connection, _ = listener.accept()
        with connection:
            assert connection.recv(16) == b"ping"
            connection.sendall(b"ready\n")


def _denied(operation) -> None:
    try:
        operation()
    except OSError:
        return
    raise AssertionError("Hermes user changed the root-owned bridge")


def _rebind() -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as candidate:
        candidate.bind(str(ROOT / "replacement"))


def _client() -> None:
    assert os.geteuid() == UID
    assert GID in os.getgroups()
    assert ROOT.stat().st_uid == 0 and ROOT.stat().st_gid == GID
    assert _mode(ROOT) == 0o750
    assert SOCKET.stat().st_uid == 0 and SOCKET.stat().st_gid == GID
    assert _mode(SOCKET) == 0o660
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(SOCKET))
        client.sendall(b"ping")
        assert client.recv(16) == b"ready\n"
    _denied(SOCKET.unlink)
    _denied(_rebind)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("server", "client"))
    role = parser.parse_args().role
    if role == "server":
        _server()
    else:
        _client()


if __name__ == "__main__":
    main()
