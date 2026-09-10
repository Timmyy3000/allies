from __future__ import annotations

import hashlib
import json
import socketserver
import struct
import subprocess
import threading
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace

import pytest

from files import isolated_inspection
from files.inspection import CHUNK_BYTES, ScannerConfig


def run_inspection(data=b"safe", size=4):
    return isolated_inspection.inspect_isolated(
        name="notes.txt",
        source=BytesIO(data),
        size=size,
        scanner_config=ScannerConfig(host="scanner.internal"),
    )


def test_missing_process_limits_fail_closed(monkeypatch):
    monkeypatch.setattr(isolated_inspection, "ISOLATION_SUPPORTED", False)
    assert run_inspection().safe_error_code == "inspection_isolation_unavailable"


def test_process_environment_and_output_are_bounded(monkeypatch):
    monkeypatch.setattr(isolated_inspection, "ISOLATION_SUPPORTED", True)
    monkeypatch.setenv("DATABASE_URL", "must-not-reach-child")

    def complete(command, **kwargs):
        assert command[-1] == "files.inspection_worker"
        assert set(kwargs["env"]) == {"PATH", "PYTHONPATH"}
        assert kwargs["timeout"] == 90
        assert kwargs["close_fds"] is True
        assert kwargs["stderr"] == subprocess.DEVNULL
        payload = {
            "accepted": True,
            "media_type": "text/plain",
            "preview_kind": "text",
            "safe_error_code": None,
            "scanner_clean": True,
            "actual_size": 4,
            "sha256": hashlib.sha256(b"safe").hexdigest(),
        }
        kwargs["stdout"].write(json.dumps(payload).encode())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(isolated_inspection.subprocess, "run", complete)
    assert run_inspection().accepted is True


@pytest.mark.parametrize("kind", ["timeout", "failed", "oversized", "invalid_hash"])
def test_process_failures_do_not_promote(monkeypatch, kind):
    monkeypatch.setattr(isolated_inspection, "ISOLATION_SUPPORTED", True)

    def complete(command, **kwargs):
        if kind == "timeout":
            raise subprocess.TimeoutExpired(command, 90)
        if kind == "oversized":
            kwargs["stdout"].write(b"a" * 4097)
        if kind == "invalid_hash":
            kwargs["stdout"].write(
                json.dumps(
                    {
                        "accepted": True,
                        "media_type": "text/plain",
                        "preview_kind": "text",
                        "safe_error_code": None,
                        "scanner_clean": True,
                        "actual_size": 4,
                        "sha256": "0" * 64,
                    }
                ).encode()
            )
        return SimpleNamespace(returncode=1 if kind == "failed" else 0)

    monkeypatch.setattr(isolated_inspection.subprocess, "run", complete)
    assert not run_inspection().accepted


def test_staging_stops_at_declared_size(monkeypatch):
    monkeypatch.setattr(isolated_inspection, "ISOLATION_SUPPORTED", True)
    monkeypatch.setattr(
        isolated_inspection.subprocess,
        "run",
        lambda *a, **kw: pytest.fail("parser started"),
    )
    stream = BytesIO(b"a" * CHUNK_BYTES * 10)
    result = isolated_inspection.inspect_isolated(
        name="notes.txt",
        source=stream,
        size=1,
        scanner_config=ScannerConfig(host="scanner.internal"),
    )
    assert result.safe_error_code == "size_mismatch"
    assert stream.tell() <= CHUNK_BYTES


@pytest.mark.skipif(
    not isolated_inspection.ISOLATION_SUPPORTED, reason="POSIX resource limits required"
)
def test_real_parser_process_with_private_scanner_protocol():
    class ScannerHandler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(5)
            with self.request.makefile("rb") as stream:
                command = bytearray()
                while (char := stream.read(1)) != b"\0":
                    if not char:
                        raise AssertionError("scanner request ended")
                    command.extend(char)
                if command == b"zVERSION":
                    version = datetime.now(UTC).strftime("%a %b %d %H:%M:%S %Y")
                    self.request.sendall(f"ClamAV 1.4/123/{version}\0".encode())
                else:
                    assert command == b"zINSTREAM"
                    data = bytearray()
                    while length := struct.unpack(">I", stream.read(4))[0]:
                        data.extend(stream.read(length))
                    assert data == b"safe"
                    self.request.sendall(b"stream: OK\0")

    with socketserver.TCPServer(("127.0.0.1", 0), ScannerHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = isolated_inspection.inspect_isolated(
                name="notes.txt",
                source=BytesIO(b"safe"),
                size=4,
                scanner_config=ScannerConfig(
                    host="127.0.0.1", port=server.server_address[1]
                ),
            )
            assert result.accepted
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.mark.parametrize(
    "media_type,expected",
    [("text/html; charset=utf-8", "text"), ("image/svg+xml", "none")],
)
def test_preview_response_has_an_inert_type(monkeypatch, media_type, expected):
    monkeypatch.setattr(isolated_inspection, "ISOLATION_SUPPORTED", True)

    def complete(command, **kwargs):
        assert json.loads(kwargs["input"])["operation"] == "preview"
        kwargs["stdout"].write(
            json.dumps(
                {
                    "kind": "text",
                    "media_type": media_type,
                    "content": "&lt;safe&gt;",
                }
            ).encode()
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(isolated_inspection.subprocess, "run", complete)
    result = isolated_inspection.preview_isolated(
        media_type="text/html", source=BytesIO(b"safe"), size=4
    )
    assert result.kind == expected


@pytest.mark.skipif(
    not isolated_inspection.ISOLATION_SUPPORTED, reason="POSIX resource limits required"
)
def test_real_preview_process_reencodes_an_image():
    from PIL import Image

    source = BytesIO()
    Image.new("RGB", (10, 10), "red").save(source, format="JPEG")
    source.seek(0)
    result = isolated_inspection.preview_isolated(
        media_type="image/jpeg", source=source, size=len(source.getvalue())
    )
    assert result.kind == "image"
    assert result.content.startswith(b"\x89PNG\r\n\x1a\n")
