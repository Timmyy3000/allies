"""Bound the parser process and omit application credentials from its environment."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from files.inspection import CHUNK_BYTES, FileInspection, ScannerConfig
from files.previews import Preview
from files.types import MAX_FILE_BYTES

ISOLATION_SUPPORTED = os.name == "posix"


def inspect_isolated(
    *, name: str, source: BinaryIO, size: int, scanner_config: ScannerConfig | None
) -> FileInspection:
    try:
        payload, total, digest = _run_parser(
            source=source,
            size=size,
            output_limit=4096,
            parameters={
                "operation": "inspection",
                "name": name,
                "scanner": None
                if scanner_config is None
                else {
                    "host": scanner_config.host,
                    "port": scanner_config.port,
                    "deadline": scanner_config.deadline_seconds,
                    "definition_age": (
                        scanner_config.max_definition_age.total_seconds()
                    ),
                },
                "now": datetime.now(UTC).isoformat(),
            },
        )
        if payload.get("definitions_updated_at") is not None:
            payload["definitions_updated_at"] = datetime.fromisoformat(
                payload["definitions_updated_at"]
            )
        result = FileInspection(**payload)
        if not isinstance(result.accepted, bool) or not isinstance(
            result.scanner_clean, bool
        ):
            return _failed("inspection_invalid")
        if result.accepted and (
            result.actual_size != total
            or result.sha256 != digest
            or result.scanner_clean is not True
            or result.safe_error_code is not None
        ):
            return _failed("inspection_invalid")
        return result
    except _ParserFailure as exc:
        return _failed(exc.code)
    except (ValueError, TypeError, AttributeError):
        return _failed("inspection_unavailable")


def preview_isolated(*, media_type: str, source: BinaryIO, size: int) -> Preview:
    try:
        payload, _, _ = _run_parser(
            source=source,
            size=size,
            output_limit=16 * 1024 * 1024,
            parameters={"operation": "preview", "media_type": media_type},
        )
        if payload.pop("base64", False):
            payload["content"] = base64.b64decode(payload["content"], validate=True)
        result = Preview(**payload)
        if result.kind == "image" and (
            result.media_type != "image/png"
            or not isinstance(result.content, bytes)
            or len(result.content) > 10_000_000
            or not result.content.startswith(b"\x89PNG\r\n\x1a\n")
        ):
            raise ValueError("invalid image preview")
        if result.kind == "text" and (
            result.media_type != "text/html; charset=utf-8"
            or not isinstance(result.content, str)
        ):
            raise ValueError("invalid text preview")
        if result.kind not in {"none", "image", "text"}:
            raise ValueError("invalid preview kind")
        return result
    except _ParserFailure as exc:
        return Preview("none", None, None, safe_error_code=exc.code)
    except (ValueError, TypeError, AttributeError, KeyError):
        return Preview("none", None, None, safe_error_code="preview_unavailable")


def _run_parser(
    *, source: BinaryIO, size: int, output_limit: int, parameters: dict
) -> tuple[dict, int, str]:
    if not ISOLATION_SUPPORTED:
        raise _ParserFailure("inspection_isolation_unavailable")
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or not 1 <= size <= MAX_FILE_BYTES
    ):
        raise _ParserFailure("size_mismatch")
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="allies-inspection-") as directory:
            source_path = Path(directory) / "source"
            digest = hashlib.sha256()
            total = 0
            with source_path.open("xb") as output:
                while chunk := source.read(CHUNK_BYTES):
                    if not isinstance(chunk, bytes) or len(chunk) > CHUNK_BYTES:
                        raise _ParserFailure("inspection_unavailable")
                    total += len(chunk)
                    if total > size:
                        raise _ParserFailure("size_mismatch")
                    if time.monotonic() - started > 120:
                        raise _ParserFailure("inspection_timeout")
                    digest.update(chunk)
                    output.write(chunk)
            if total != size:
                raise _ParserFailure("size_mismatch")
            request = json.dumps(
                {
                    "source": str(source_path),
                    "size": size,
                    **parameters,
                },
                ensure_ascii=False,
            ).encode()
            if len(request) > 4096:
                raise _ParserFailure("inspection_unavailable")
            with (Path(directory) / "result").open("w+b") as result_file:
                completed = subprocess.run(
                    [sys.executable, "-B", "-m", "files.inspection_worker"],
                    input=request,
                    stdout=result_file,
                    stderr=subprocess.DEVNULL,
                    cwd=directory,
                    env={
                        "PATH": os.defpath,
                        "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
                    },
                    timeout=90,
                    check=False,
                    close_fds=True,
                )
                if completed.returncode != 0:
                    raise _ParserFailure("inspection_unavailable")
                result_file.seek(0)
                raw = result_file.read(output_limit + 1)
            if len(raw) > output_limit:
                raise _ParserFailure("inspection_unavailable")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise _ParserFailure("inspection_unavailable")
            return payload, total, digest.hexdigest()
    except subprocess.TimeoutExpired as exc:
        raise _ParserFailure("inspection_timeout") from exc
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise _ParserFailure("inspection_unavailable") from exc


def _failed(code: str) -> FileInspection:
    return FileInspection(False, None, "none", code, False)


class _ParserFailure(Exception):
    def __init__(self, code: str):
        self.code = code
