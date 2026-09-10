"""Run file parsing without the application environment or database access."""

from __future__ import annotations

import json
import sys


def main() -> None:
    import resource

    request = json.loads(sys.stdin.buffer.read(4097))
    preview = request["operation"] == "preview"
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (65, 65))
    resource.setrlimit(
        resource.RLIMIT_FSIZE, ((16 * 1024 * 1024 if preview else 4096),) * 2
    )
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    from dataclasses import asdict
    from datetime import datetime, timedelta

    from files.inspection import ClamAvClient, ScannerConfig, inspect_file

    if preview:
        import base64

        from files.previews import build_preview

        with open(request["source"], "rb") as source:
            result = build_preview(
                media_type=request["media_type"], stream=source, size=request["size"]
            )
        payload = asdict(result)
        if isinstance(result.content, bytes):
            payload["content"] = base64.b64encode(result.content).decode("ascii")
            payload["base64"] = True
        sys.stdout.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
        return
    with open(request["source"], "rb") as source:
        result = inspect_file(
            name=request["name"],
            source=source,
            size=request["size"],
            scanner=ClamAvClient(
                ScannerConfig(
                    host=request["scanner_host"],
                    port=request["scanner_port"],
                    deadline_seconds=request["scanner_deadline"],
                    max_definition_age=timedelta(seconds=request["definition_age"]),
                )
            ),
            now=datetime.fromisoformat(request["now"]),
        )
    payload = asdict(result)
    if result.definitions_updated_at is not None:
        payload["definitions_updated_at"] = result.definitions_updated_at.isoformat()
    sys.stdout.write(json.dumps(payload, separators=(",", ":")))


if __name__ == "__main__":
    main()
