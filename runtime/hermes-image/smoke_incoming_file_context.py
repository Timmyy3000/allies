"""Check the staged-file context boundary in the built Hermes image."""

from gateway.platforms.api_server import _allies_incoming_file_context_prompt


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
    print("incoming file context: PASS")


if __name__ == "__main__":
    main()
