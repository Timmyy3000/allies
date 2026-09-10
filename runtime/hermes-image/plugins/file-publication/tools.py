"""Bridge the marked Hermes publication call to the local runtime."""

from __future__ import annotations

import json
import socket
from typing import Any

from allies_file_publication_context import get_current_allies_file_publication_context

_SOCKET_PATH = "/opt/data/.allies-publication-bridge/socket"
_MAX_REQUEST_BYTES = 8 * 1024
_MAX_RESPONSE_BYTES = 64 * 1024
_TIMEOUT_SECONDS = 305
_FAILURE = {
    "state": "failed",
    "retryable": True,
    "error_code": "publication_unavailable",
}

PUBLISH_FILES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "publish_files",
        "description": "Publish one to ten files from the current workspace.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "paths": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10,
                    "items": {"type": "string", "minLength": 1, "maxLength": 1024},
                }
            },
            "required": ["paths"],
        },
    },
}


def _failure() -> str:
    return json.dumps(_FAILURE, separators=(",", ":"))


def _valid_paths(args: Any) -> list[str] | None:
    if not isinstance(args, dict) or set(args) != {"paths"}:
        return None
    paths = args.get("paths")
    if not isinstance(paths, list) or not 1 <= len(paths) <= 10:
        return None
    valid: list[str] = []
    for path in paths:
        try:
            path_bytes = path.encode("utf-8") if isinstance(path, str) else b""
        except UnicodeError:
            return None
        if (
            not isinstance(path, str)
            or not 1 <= len(path_bytes) <= 1024
            or path.startswith(("/", "~"))
            or "\\" in path
            or ":" in path
            or "://" in path
            or any(character in path for character in "*?[]")
        ):
            return None
        parts = path.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            return None
        valid.append(path)
    return valid if len(set(valid)) == len(valid) else None


def _read_response(connection: socket.socket) -> dict[str, Any] | None:
    received = bytearray()
    while len(received) <= _MAX_RESPONSE_BYTES:
        chunk = connection.recv(min(4096, _MAX_RESPONSE_BYTES + 1 - len(received)))
        if not chunk:
            return None
        received.extend(chunk)
        if b"\n" in chunk:
            line, tail = bytes(received).split(b"\n", 1)
            if tail or not line or len(line) > _MAX_RESPONSE_BYTES:
                return None
            try:
                value = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            return value if isinstance(value, dict) else None
    return None


def _ready(value: dict[str, Any], context: str) -> str | None:
    if value.get("state") != "ready":
        return None
    files = value.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 10:
        return None
    safe_files = []
    for item in files:
        if not isinstance(item, dict) or set(item) != {"name", "open_path"}:
            return None
        name = item.get("name")
        open_path = item.get("open_path")
        try:
            if isinstance(name, str):
                name.encode("utf-8")
            open_path_bytes = (
                open_path.encode("utf-8") if isinstance(open_path, str) else b""
            )
        except UnicodeError:
            return None
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 255
            or "/" in name
            or "\\" in name
            or "\x00" in name
            or not isinstance(open_path, str)
            or not open_path.startswith("/files/")
            or len(open_path_bytes) > 2048
            or "\x00" in open_path
            or context in name
            or context in open_path
        ):
            return None
        safe_files.append({"name": name, "open_path": open_path})
    return json.dumps(
        {"state": "ready", "files": safe_files},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def handle_publish_files(
    args: dict, *, tool_call_id: str | None = None, **_kwargs: Any
) -> str:
    """Publish only through the current request's runtime-owned context."""

    context = get_current_allies_file_publication_context()
    paths = _valid_paths(args)
    if (
        context is None
        or paths is None
        or not isinstance(tool_call_id, str)
        or not tool_call_id
    ):
        return _failure()
    try:
        request = json.dumps(
            {"context": context, "tool_call_id": tool_call_id, "paths": paths},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, UnicodeError):
        return _failure()
    if len(request) + 1 > _MAX_REQUEST_BYTES:
        return _failure()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(_TIMEOUT_SECONDS)
            connection.connect(_SOCKET_PATH)
            connection.sendall(request + b"\n")
            response = _read_response(connection)
    except OSError:
        return _failure()
    ready = _ready(response, context) if response is not None else None
    return ready or _failure()
