"""Exercise the deployed startup identity and shared-volume boundary in Docker."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


async def check_inside() -> None:
    from allies_runtime import files
    from allies_runtime.errors import IncomingFileError
    from allies_runtime.files import freeze_publication, stage_incoming_files
    from allies_runtime.profile_store import ProfileSeed, ProfileStore
    from allies_runtime.publication_bridge import PublicationBridge

    assert os.geteuid() == 0
    root = Path("/opt/data")
    store = ProfileStore(root, api_key_factory=lambda: "identity-probe-key-0123456789")
    seed = ProfileSeed(
        foundry_profile_id=str(uuid4()),
        ally_name="Probe",
        personality="Probe",
        provider="openai",
        model="probe",
        first_chat_instruction="Probe",
        credential_refs={},
        first_chat_version=1,
        lifecycle_epoch=1,
        materialized_generation="probe",
        operation_id="probe",
    )
    store.materialize(seed)
    profile = root / "profiles" / seed.hermes_profile_key
    content = b"verified input"

    async def chunks(_descriptor):
        yield content

    staged = await stage_incoming_files(
        profile / "workspace",
        str(uuid4()),
        [
            {
                "file_id": str(uuid4()),
                "name": "probe.txt",
                "media_type": "text/plain",
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
        chunks,
    )
    bridge = PublicationBridge(None, store, root)
    assert await bridge.start()
    freeze_publication(profile / "workspace", str(uuid4()), [staged.files[0].path])
    assert (root / ".allies-publication-state").is_dir()
    try:
        await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "-c",
                """
import os, sys
from pathlib import Path
p = Path(sys.argv[1])
assert os.geteuid() == 10000
assert 'API_SERVER_KEY=' in (p / '.env').read_text()
(p / 'workspace' / 'output.txt').write_text('Hermes output')
(p / 'sessions' / 'probe').write_text('session')
assert (p / 'workspace' / sys.argv[2]).read_bytes() == b'verified input'
assert not os.access('/run/secrets/foundry-runtime-token', os.R_OK)
assert not os.access('/opt/data/.allies-publication-bridge', os.W_OK)
assert not os.access('/opt/data/.allies-publication-state', os.R_OK)
""",
                str(profile),
                staged.files[0].path,
            ],
            user=10000,
            group=10000,
            extra_groups=[10001],
            check=True,
        )
    finally:
        await bridge.close()
    parent = profile / "workspace" / "race"
    parent.mkdir()
    (parent / "file.txt").write_text("safe")
    private = root / "private-probe"
    private.mkdir(mode=0o700)
    (private / "file.txt").write_text("private")
    original = files._publication_source

    def swapped_source(workspace, relative):
        parent.rename(parent.with_name("original"))
        parent.symlink_to(private, target_is_directory=True)
        return workspace / relative, (private / "file.txt").stat()

    files._publication_source = swapped_source
    try:
        try:
            files._copy_publication_file(
                profile / "workspace", Path("race/file.txt"), root, 1
            )
        except IncomingFileError:
            pass
        else:
            raise AssertionError("publication followed a replaced source ancestor")
    finally:
        files._publication_source = original
    print("Runtime identity, Hermes working files, and publication isolation passed.")


def check_image(image: str) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from runtime.services.continuity_proof import _runtime_proof_command

    command = _runtime_proof_command(
        SimpleNamespace(secret_name="PROBE_RUNTIME"),
        SimpleNamespace(
            hermes_key_secret_name="PROBE_HERMES",
            provider_key_secret_name="PROBE_PROVIDER",
        ),
    )[2]
    command = (
        command.removesuffix("python -m allies_runtime") + "python /probe.py --inside"
    )
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--tmpfs",
            "/opt/data",
            "--entrypoint",
            "sh",
            "-e",
            "PYTHONPATH=/app",
            "-e",
            "PROBE_RUNTIME=cHJvYmU=",
            "-e",
            "PROBE_HERMES=cHJvYmU=",
            "-e",
            "PROBE_PROVIDER=cHJvYmU=",
            "-v",
            f"{Path(__file__).resolve()}:/probe.py:ro",
            image,
            "-ec",
            "chown 0:0 /opt/data; chmod 1777 /opt/data; " + command,
        ],
        check=True,
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["--inside"]:
        asyncio.run(check_inside())
    else:
        check_image(sys.argv[1])
