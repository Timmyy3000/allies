"""Check the staged-file context boundary in the built Hermes image."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gateway.platforms.api_server import _allies_incoming_file_context_prompt
from tools.image_source import ResolveContext, resolve_image_source


def main() -> None:
    descriptor = {
        "file_id": "12345678-1234-1234-1234-123456789abc",
        "name": "notes.txt",
        "media_type": "text/plain",
        "size": 4,
        "sha256": "a" * 64,
        "path": "attachments/command/notes.txt",
    }
    context = {
        "schema_version": "v1",
        "kind": "allies_incoming_files",
        "files": [descriptor],
    }
    assert _allies_incoming_file_context_prompt(None) is None
    assert "attachments/command/notes.txt" in _allies_incoming_file_context_prompt(
        context
    )
    assert _allies_incoming_file_context_prompt(
        {**context, "files": [{**descriptor, "name": "界" * 255}]}
    )
    assert _allies_incoming_file_context_prompt(
        {**context, "files": [{**descriptor, "name": "😀" * 255}] * 10}
    )
    for invalid in (
        {**context, "files": []},
        {**context, "files": [{**descriptor, "path": "../other/notes.txt"}]},
        {**context, "files": [{**descriptor, "size": 25_000_001}]},
        {**context, "files": [{**descriptor, "contents": "secret"}]},
    ):
        try:
            _allies_incoming_file_context_prompt(invalid)
        except ValueError:
            continue
        raise AssertionError("invalid file context was accepted")

    with TemporaryDirectory() as directory:
        for profile in ("first", "second"):
            home = Path(directory) / profile
            image = home / "workspace" / descriptor["path"]
            image.parent.mkdir(parents=True)
            image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
            with patch("hermes_constants.get_hermes_home", return_value=home):
                prompt = _allies_incoming_file_context_prompt(context)
            manifest = json.loads(prompt.split("\n", 1)[1])
            image_path = manifest[0]["path"]
            assert Path(image_path) == image
            with patch.dict("os.environ", {"TERMINAL_ENV": "local"}):
                resolved = asyncio.run(
                    resolve_image_source(image_path, ResolveContext())
                )
            assert resolved.data == image.read_bytes()
            assert resolved.mime == "image/png"
    print("incoming file context: PASS")


if __name__ == "__main__":
    main()
