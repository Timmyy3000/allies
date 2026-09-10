from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import allies_runtime.publication_bridge as bridge_module
from allies_runtime import files
from allies_runtime.composition import run_worker
from allies_runtime.errors import IncomingFileError
from allies_runtime.files import (
    freeze_publication,
    prepare_publication_files,
    publication_spool_path,
)
from allies_runtime.foundry import FoundryClaim, FoundryError
from allies_runtime.profile_store import ProfileStoreError
from allies_runtime.publication_bridge import (
    MAX_RESPONSE_BYTES,
    PublicationBridge,
    _cloud_file_rows,
    _generation,
    _ready_view,
    _uuid,
)


def _claim(profile_key: str = "ally") -> FoundryClaim:
    return FoundryClaim(
        attempt_id=str(uuid4()),
        execution_id=str(uuid4()),
        profile_id=str(uuid4()),
        hermes_profile_key=profile_key,
        model="test-model",
        conversation_id="conversation",
        session_id="session",
        stream_id="stream",
        lease_id=str(uuid4()),
        lease_token="lease-token",
        expires_at=None,
        payload={"message": ""},
        claim_id=str(uuid4()),
    )


class _Store:
    def __init__(self, workspace):
        self.workspace = workspace

    def workspace_path(self, _profile_key):
        return self.workspace


class _Writer:
    def __init__(self):
        self.value = bytearray()
        self.closed = False

    def write(self, value):
        self.value.extend(value)

    async def drain(self):
        return None

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


async def _handle(bridge, value: bytes) -> tuple[dict[str, object], _Writer]:
    reader = asyncio.StreamReader()
    reader.feed_data(value)
    reader.feed_eof()
    writer = _Writer()
    await bridge._handle(reader, writer)
    return json.loads(writer.value), writer


def _protected_state_root(root):
    path = root / files._PUBLICATION_STATE_DIRECTORY
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.asyncio
async def test_bridge_rejects_invalid_tool_values_without_using_a_session(tmp_path):
    bridge = PublicationBridge(object(), object(), tmp_path)

    assert await bridge.publish("not-a-nonce", "call", []) == {
        "state": "failed",
        "retryable": True,
        "error_code": "publication_context_invalid",
    }
    assert await bridge.publish("a" * 64, "call", "result.csv") == {
        "state": "failed",
        "retryable": True,
        "error_code": "publication_request_invalid",
    }


@pytest.mark.asyncio
async def test_bridge_rejects_invalid_call_id_from_an_active_session(tmp_path):
    bridge = PublicationBridge(object(), object(), tmp_path)
    context = bridge.activate(_claim())

    assert await bridge.publish(context, "bad call", []) == {
        "state": "failed",
        "retryable": True,
        "error_code": "publication_request_invalid",
    }


@pytest.mark.asyncio
async def test_removed_profile_does_not_break_recovery_or_tool_response(tmp_path):
    class RemovedStore:
        def workspace_path(self, _profile_key):
            raise ProfileStoreError("profile removed")

    bridge = PublicationBridge(object(), RemovedStore(), tmp_path)
    await bridge.recover(str(uuid4()), "removed")
    context = bridge.activate(_claim("removed"))
    assert await bridge.publish(context, "call-1", ["result.csv"]) == {
        "state": "failed",
        "retryable": True,
        "error_code": "publication_unavailable",
    }


@pytest.mark.asyncio
async def test_bridge_private_protocol_bounds_bad_and_large_responses(tmp_path):
    bridge = PublicationBridge(object(), object(), tmp_path)
    invalid, invalid_writer = await _handle(bridge, b"not-json\n")
    unterminated, _writer = await _handle(bridge, b"not-json")

    assert invalid == {
        "state": "failed",
        "retryable": True,
        "error_code": "publication_request_invalid",
    }
    assert invalid_writer.closed
    assert unterminated["error_code"] == "publication_request_invalid"

    async def large_response(_context, _tool_call_id, _paths):
        return {
            "state": "ready",
            "files": [{"name": "x" * MAX_RESPONSE_BYTES, "open_path": "/open"}],
        }

    bridge.publish = large_response
    response, writer = await _handle(
        bridge,
        json.dumps(
            {"context": "a" * 64, "tool_call_id": "call-1", "paths": ["result.csv"]}
        ).encode()
        + b"\n",
    )

    assert response == {
        "state": "failed",
        "retryable": True,
        "error_code": "publication_response_invalid",
    }
    assert writer.closed


@pytest.mark.asyncio
async def test_bridge_start_is_safe_without_unix_socket_support(tmp_path, monkeypatch):
    bridge = PublicationBridge(object(), object(), tmp_path)
    context = bridge.activate(_claim())
    monkeypatch.setattr(bridge_module, "os", SimpleNamespace(name="nt"))

    await bridge.start()
    await bridge.close()

    assert bridge._server is None
    assert context not in bridge._sessions


@pytest.mark.asyncio
async def test_unprivileged_bridge_start_leaves_no_shared_state(tmp_path, monkeypatch):
    bridge = PublicationBridge(object(), object(), tmp_path)
    monkeypatch.setattr(
        bridge_module, "os", SimpleNamespace(name="posix", geteuid=lambda: 10000)
    )
    assert await bridge.start() is False
    assert list(tmp_path.iterdir()) == []
    assert bridge.activate(_claim()) is None


@pytest.mark.asyncio
async def test_bridge_sets_the_root_owned_unix_socket_boundary(tmp_path, monkeypatch):
    actions = []

    class Server:
        def close(self):
            actions.append("close")

        async def wait_closed(self):
            actions.append("wait_closed")

    async def start_server(handler, path, *, limit):
        actions.append((handler, path, limit))
        return Server()

    fake_os = SimpleNamespace(
        name="posix",
        geteuid=lambda: 0,
        chown=lambda *args: actions.append(args),
        chmod=lambda *args: actions.append(args),
    )
    monkeypatch.setattr(bridge_module, "os", fake_os)
    monkeypatch.setattr(bridge_module, "grp", None)
    unavailable = PublicationBridge(object(), object(), tmp_path)
    assert await unavailable.start() is False
    assert unavailable._server is None

    monkeypatch.setattr(
        bridge_module,
        "grp",
        SimpleNamespace(getgrnam=lambda name: SimpleNamespace(gr_gid=10001)),
    )
    monkeypatch.setattr(
        bridge_module, "_validate_publication_volume_root", lambda _root: None
    )
    monkeypatch.setattr(bridge_module, "reconcile_publication_spools", lambda _root: 0)
    monkeypatch.setattr(
        bridge_module, "cleanup_stale_publication_copies", lambda _root: 0
    )
    monkeypatch.setattr(
        bridge_module.asyncio, "start_unix_server", start_server, raising=False
    )
    bridge = PublicationBridge(object(), object(), tmp_path)

    await bridge.start()
    await bridge.close()

    assert any(isinstance(action, tuple) and action[-1] == 0o660 for action in actions)
    assert "close" in actions
    assert "wait_closed" in actions


@pytest.mark.asyncio
@pytest.mark.usefixtures("root_owned_publication_spool")
async def test_bridge_disables_publication_for_an_invalid_journal_without_stopping_worker(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "result.csv").write_bytes(b"content")
    manifest = freeze_publication(workspace, str(uuid4()), ["result.csv"])
    journal = files._ledger_path(tmp_path)
    journal.write_text("{", encoding="utf-8")
    monkeypatch.setattr(
        files,
        "_publication_state_root",
        _protected_state_root,
    )
    monkeypatch.setattr(
        bridge_module,
        "os",
        SimpleNamespace(
            name="posix",
            geteuid=lambda: 0,
            chown=lambda *_args: None,
            chmod=lambda *_args: None,
        ),
    )
    monkeypatch.setattr(
        bridge_module, "_validate_publication_volume_root", lambda _root: None
    )
    calls = []

    class Worker:
        async def run(self, **_kwargs):
            calls.append("claim")
            return ("claim",)

    bridge = PublicationBridge(object(), object(), tmp_path)
    composition = SimpleNamespace(worker=Worker(), publication_bridge=bridge)

    assert await run_worker(composition) == ("claim",)
    assert calls == ["claim"]
    assert journal.read_text(encoding="utf-8") == "{"
    assert (
        tmp_path / ".allies-publications" / "ally" / manifest.publication_id
    ).is_dir()
    assert bridge.activate(_claim()) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, owner", [(0o1777, 10000), (0o755, 0)])
async def test_bridge_rejects_an_empty_untrusted_volume_without_stopping_worker(
    tmp_path, monkeypatch, mode, owner
):
    original_lstat = Path.lstat
    monkeypatch.setattr(files, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(
        bridge_module, "os", SimpleNamespace(name="posix", geteuid=lambda: 0)
    )
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda path: (
            SimpleNamespace(
                st_mode=bridge_module.stat.S_IFDIR | mode,
                st_uid=owner,
                st_gid=owner,
            )
            if path == tmp_path
            else original_lstat(path)
        ),
    )
    calls = []

    class Worker:
        async def run(self, **_kwargs):
            calls.append("claim")
            return ("claim",)

    bridge = PublicationBridge(object(), object(), tmp_path)
    composition = SimpleNamespace(worker=Worker(), publication_bridge=bridge)

    assert await run_worker(composition) == ("claim",)
    assert calls == ["claim"]
    assert bridge.activate(_claim()) is None
    assert not (tmp_path / files._PUBLICATION_STATE_DIRECTORY).exists()
    assert not bridge.socket_path.exists()


@pytest.mark.asyncio
@pytest.mark.usefixtures("root_owned_publication_spool")
@pytest.mark.parametrize("kind", ["file", "symlink"])
async def test_bridge_disables_publication_for_an_untrusted_root(
    tmp_path, monkeypatch, kind
):
    root = tmp_path / bridge_module.BRIDGE_DIRECTORY
    if kind == "file":
        root.write_text("hostile", encoding="utf-8")
    else:
        root.write_text("hostile", encoding="utf-8")
        original_lstat = Path.lstat
        monkeypatch.setattr(
            Path,
            "lstat",
            lambda path: (
                SimpleNamespace(st_mode=bridge_module.stat.S_IFLNK | 0o777)
                if path == root
                else original_lstat(path)
            ),
        )
    monkeypatch.setattr(
        bridge_module,
        "grp",
        SimpleNamespace(getgrnam=lambda _name: SimpleNamespace(gr_gid=10001)),
    )
    monkeypatch.setattr(
        files,
        "_publication_state_root",
        _protected_state_root,
    )
    monkeypatch.setattr(
        bridge_module,
        "os",
        SimpleNamespace(
            name="posix",
            geteuid=lambda: 0,
            chown=lambda *_args: None,
            chmod=lambda *_args: None,
        ),
    )
    monkeypatch.setattr(
        bridge_module, "_validate_publication_volume_root", lambda _root: None
    )
    bridge = PublicationBridge(object(), object(), tmp_path)

    assert await bridge.start() is False
    assert bridge._server is None
    assert root.exists()


@pytest.mark.asyncio
@pytest.mark.usefixtures("root_owned_publication_spool")
async def test_bridge_cancellation_fences_preparation_and_freeze(tmp_path, monkeypatch):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    publication_id = str(uuid4())
    bridge = None
    context = None
    calls = []

    class Foundry:
        async def create_publication_intent(self, *_args):
            calls.append("intent")
            return {"publication_id": publication_id}

        async def freeze_publication_intent(self, *_args):
            calls.append("frozen")
            bridge.deactivate(context)
            return {}

    bridge = PublicationBridge(Foundry(), _Store(workspace), tmp_path)
    context = bridge.activate(_claim())

    def revoke_during_prepare(_workspace, _paths):
        bridge.deactivate(context)
        return []

    monkeypatch.setattr(
        bridge_module, "prepare_publication_files", revoke_during_prepare
    )
    assert await bridge.publish(context, "call-1", []) == {
        "state": "failed",
        "retryable": True,
        "error_code": "publication_context_invalid",
    }
    assert calls == []

    (workspace / "result.csv").write_bytes(b"frozen bytes")
    context = bridge.activate(_claim())
    monkeypatch.setattr(
        bridge_module, "prepare_publication_files", prepare_publication_files
    )
    assert await bridge.publish(context, "call-2", ["result.csv"]) == {
        "publication_id": publication_id,
        "state": "failed",
        "retryable": True,
        "error_code": "publication_context_invalid",
    }
    assert calls == ["intent", "frozen"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("root_owned_publication_spool")
async def test_bridge_rejects_invalid_reservations_and_cloud_poll_responses(tmp_path):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "result.csv").write_bytes(b"frozen bytes")
    publication_id = str(uuid4())

    class Foundry:
        async def create_publication_intent(self, *_args):
            return {"publication_id": publication_id}

        async def freeze_publication_intent(self, *_args):
            return {}

        async def register_publication(self, *_args):
            return {"revision": False, "files": []}

        async def get_publication(self, *_args):
            return None

    bridge = PublicationBridge(Foundry(), _Store(workspace), tmp_path)
    context = bridge.activate(_claim())
    assert await bridge.publish(context, "call-1", ["result.csv"]) == {
        "publication_id": publication_id,
        "state": "failed",
        "retryable": True,
        "error_code": "publication_response_invalid",
    }

    session = bridge._sessions[context]
    with pytest.raises(TypeError, match="response was invalid"):
        await bridge._wait_for_ready(
            context, session, publication_id, asyncio.get_running_loop().time() + 1
        )


@pytest.mark.asyncio
@pytest.mark.usefixtures("root_owned_publication_spool")
async def test_bridge_fences_claim_loss_after_intent_and_spool_reads(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "result.csv").write_bytes(b"frozen bytes")
    publication_id = str(uuid4())
    cloud_file_id = str(uuid4())
    bridge = None
    context = None

    class Foundry:
        async def create_publication_intent(self, *_args):
            bridge.deactivate(context)
            return {"publication_id": publication_id}

    bridge = PublicationBridge(Foundry(), _Store(workspace), tmp_path)
    context = bridge.activate(_claim())
    assert await bridge.publish(context, "call-1", ["result.csv"]) == {
        "publication_id": publication_id,
        "state": "failed",
        "retryable": True,
        "error_code": "publication_context_invalid",
    }

    class ReadFenceFoundry:
        async def create_publication_intent(self, *_args):
            return {"publication_id": publication_id}

        async def freeze_publication_intent(self, *_args):
            return {}

        async def register_publication(self, _attempt, _lease, _publication, frozen):
            local = frozen[0]
            return {
                "revision": 1,
                "files": [
                    {
                        "id": cloud_file_id,
                        "source_version_id": local["source_version_id"],
                        "sha256": local["sha256"],
                        "size": local["size"],
                        "generation": 1,
                    }
                ],
            }

    bridge = PublicationBridge(ReadFenceFoundry(), _Store(workspace), tmp_path)
    context = bridge.activate(_claim())

    class Spool:
        def read_bytes(self):
            bridge.deactivate(context)
            return b"frozen bytes"

    monkeypatch.setattr(bridge_module, "publication_spool_path", lambda *_args: Spool())
    assert await bridge.publish(context, "call-2", ["result.csv"]) == {
        "publication_id": publication_id,
        "state": "failed",
        "retryable": True,
        "error_code": "publication_context_invalid",
    }


@pytest.mark.asyncio
async def test_bridge_bounds_pending_cloud_polls_and_invalid_recovery_claims(tmp_path):
    class Foundry:
        async def get_publication(self, *_args):
            return {"state": "validating", "files": []}

        async def freeze_publication_intent(self, *_args):
            return {}

        async def claim_publication_retries(self, *_args):
            return [
                None,
                {
                    "publication_id": str(uuid4()),
                    "revision": False,
                    "lease_token": str(uuid4()),
                },
                {
                    "publication_id": str(uuid4()),
                    "revision": 1,
                    "lease_token": str(uuid4()),
                    "files": [],
                },
            ]

    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    bridge = PublicationBridge(Foundry(), _Store(workspace), tmp_path)
    context = bridge.activate(_claim())
    session = bridge._sessions[context]
    publication_id = str(uuid4())

    assert await bridge._wait_for_ready(
        context, session, publication_id, asyncio.get_running_loop().time() + 0.001
    ) == {
        "publication_id": publication_id,
        "state": "failed",
        "retryable": True,
        "error_code": "publication_pending",
    }

    await bridge.recover(str(uuid4()), "ally")


@pytest.mark.asyncio
@pytest.mark.usefixtures("root_owned_publication_spool")
async def test_bridge_fences_snapshot_completion_and_bounds_cloud_timeouts(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "result.csv").write_bytes(b"frozen bytes")
    publication_id = str(uuid4())
    bridge = None
    context = None
    actual_freeze = bridge_module.freeze_publication

    class Foundry:
        async def create_publication_intent(self, *_args):
            return {"publication_id": publication_id}

    bridge = PublicationBridge(Foundry(), _Store(workspace), tmp_path)
    context = bridge.activate(_claim())

    def revoke_during_freeze(*args):
        bridge.deactivate(context)
        return actual_freeze(*args)

    monkeypatch.setattr(bridge_module, "freeze_publication", revoke_during_freeze)
    assert await bridge.publish(context, "call-1", ["result.csv"]) == {
        "publication_id": publication_id,
        "state": "failed",
        "retryable": True,
        "error_code": "publication_context_invalid",
    }

    class SlowFoundry:
        async def get_publication(self, *_args):
            await asyncio.Event().wait()

    bridge = PublicationBridge(SlowFoundry(), _Store(workspace), tmp_path)
    context = bridge.activate(_claim())
    session = bridge._sessions[context]
    assert await bridge._wait_for_ready(
        context, session, publication_id, asyncio.get_running_loop().time() + 0.001
    ) == {
        "publication_id": publication_id,
        "state": "failed",
        "retryable": True,
        "error_code": "publication_pending",
    }


@pytest.mark.asyncio
async def test_bridge_rejects_reader_overflow_before_dispatch(tmp_path):
    class Reader:
        async def readline(self):
            raise ValueError("line too long")

    bridge = PublicationBridge(object(), object(), tmp_path)
    writer = _Writer()
    await bridge._handle(Reader(), writer)

    assert json.loads(writer.value)["error_code"] == "publication_request_invalid"


@pytest.mark.asyncio
async def test_bridge_stops_after_a_validating_poll_reaches_its_deadline(
    tmp_path, monkeypatch
):
    class Foundry:
        async def get_publication(self, *_args):
            return {"state": "validating", "files": []}

    times = iter((0.0, 1.0))
    loop = SimpleNamespace(time=lambda: next(times))
    monkeypatch.setattr(bridge_module.asyncio, "get_running_loop", lambda: loop)
    bridge = PublicationBridge(Foundry(), object(), tmp_path)
    context = bridge.activate(_claim())
    publication_id = str(uuid4())

    assert await bridge._wait_for_ready(
        context, bridge._sessions[context], publication_id, 1.0
    ) == {
        "publication_id": publication_id,
        "state": "failed",
        "retryable": True,
        "error_code": "publication_pending",
    }


@pytest.mark.asyncio
@pytest.mark.usefixtures("root_owned_publication_spool")
async def test_bridge_keeps_the_frozen_spool_when_context_is_revoked_after_register(
    tmp_path,
):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "result.csv").write_bytes(b"frozen bytes")
    publication_id = str(uuid4())
    cloud_file_id = str(uuid4())
    bridge = None
    context = None
    uploads = []

    class Foundry:
        async def create_publication_intent(self, *_args):
            return {"publication_id": publication_id}

        async def freeze_publication_intent(self, *_args):
            return {}

        async def register_publication(self, _attempt, _lease, _publication, files):
            bridge.deactivate(context)
            frozen = files[0]
            return {
                "revision": 1,
                "files": [
                    {
                        "id": cloud_file_id,
                        "source_version_id": frozen["source_version_id"],
                        "sha256": frozen["sha256"],
                        "size": frozen["size"],
                        "generation": 1,
                    }
                ],
            }

        async def upload_publication_file(self, *_args):
            uploads.append(True)

    bridge = PublicationBridge(Foundry(), _Store(workspace), tmp_path)
    context = bridge.activate(_claim())

    assert await bridge.publish(context, "call-1", ["result.csv"]) == {
        "publication_id": publication_id,
        "state": "failed",
        "retryable": True,
        "error_code": "publication_context_invalid",
    }
    assert uploads == []
    assert (
        publication_spool_path(
            workspace,
            publication_id,
            freeze_publication(workspace, publication_id, ["result.csv"])
            .files[0]
            .source_version_id,
        ).read_bytes()
        == b"frozen bytes"
    )


@pytest.mark.asyncio
async def test_bridge_reports_a_failed_or_expired_cloud_publication(tmp_path):
    class Foundry:
        async def get_publication(self, *_args):
            return {"state": "failed", "files": []}

    bridge = PublicationBridge(Foundry(), object(), tmp_path)
    context = bridge.activate(_claim())
    session = bridge._sessions[context]
    deadline = asyncio.get_running_loop().time() + 1
    failed_id = str(uuid4())

    assert await bridge._wait_for_ready(context, session, failed_id, deadline) == {
        "publication_id": failed_id,
        "state": "failed",
        "retryable": True,
        "error_code": "publication_failed",
    }
    pending_id = str(uuid4())
    assert await bridge._wait_for_ready(
        context, session, pending_id, asyncio.get_running_loop().time()
    ) == {
        "publication_id": pending_id,
        "state": "failed",
        "retryable": True,
        "error_code": "publication_pending",
    }


def test_bridge_rejects_malformed_cloud_rows_and_ready_links():
    source_id = str(uuid4())
    manifest = SimpleNamespace(
        files=(SimpleNamespace(source_version_id=source_id, sha256="a" * 64, size=3),)
    )
    row = {"source_version_id": source_id, "sha256": "a" * 64, "size": 3}

    assert _cloud_file_rows([row], manifest)[source_id] == row
    for rows in ([], ["bad"], [{**row, "sha256": "b" * 64}]):
        with pytest.raises((TypeError, ValueError)):
            _cloud_file_rows(rows, manifest)
    for value in (None, "not-a-uuid"):
        with pytest.raises(ValueError):
            _uuid(value)
    with pytest.raises(ValueError):
        _generation(False)
    assert (
        _ready_view({"state": "ready", "files": ["bad"]}, source_id)["error_code"]
        == "publication_response_invalid"
    )
    assert (
        _ready_view(
            {"state": "ready", "files": [{"name": "name", "open_path": None}]},
            source_id,
        )["error_code"]
        == "publication_response_invalid"
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("root_owned_publication_spool")
async def test_recovery_retains_spools_for_failed_acknowledgements_and_claims(tmp_path):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "result.csv").write_bytes(b"frozen bytes")
    manifest = freeze_publication(workspace, str(uuid4()), ["result.csv"])

    class Foundry:
        async def freeze_publication_intent(self, *_args):
            raise FoundryError("frozen acknowledgement failed")

        async def claim_publication_retries(self, *_args):
            raise FoundryError("claim failed")

        async def get_publication(self, *_args):
            return {"state": "failed"}

    bridge = PublicationBridge(Foundry(), _Store(workspace), tmp_path)
    await bridge.recover(str(uuid4()), "ally")

    assert (
        publication_spool_path(
            workspace, manifest.publication_id, manifest.files[0].source_version_id
        ).read_bytes()
        == b"frozen bytes"
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("root_owned_publication_spool")
async def test_recovery_releases_a_spool_only_after_a_ready_cloud_receipt(tmp_path):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "result.csv").write_bytes(b"frozen bytes")
    manifest = freeze_publication(workspace, str(uuid4()), ["result.csv"])
    cloud_file_id = str(uuid4())
    lease_token = str(uuid4())
    uploads = []

    class Foundry:
        async def freeze_publication_intent(self, *_args):
            return {}

        async def claim_publication_retries(self, *_args):
            local = manifest.files[0]
            return [
                {
                    "publication_id": manifest.publication_id,
                    "revision": 2,
                    "lease_token": lease_token,
                    "files": [
                        {
                            "id": cloud_file_id,
                            "source_version_id": local.source_version_id,
                            "sha256": local.sha256,
                            "size": local.size,
                            "generation": 2,
                            "state": "pending",
                        }
                    ],
                }
            ]

        async def upload_publication_file(self, *_args):
            uploads.append(_args[4])
            return {}

        async def publication_retry_result(self, *_args):
            return {}

        async def get_publication(self, *_args):
            if not uploads:
                return {"state": "retry_pending", "revision": 2}
            return {
                "state": "ready",
                "files": [{"name": "result.csv", "open_path": "/ready/result.csv"}],
            }

    bridge = PublicationBridge(Foundry(), _Store(workspace), tmp_path)
    await bridge.recover(str(uuid4()), "ally")

    assert uploads == [b"frozen bytes"]
    with pytest.raises(IncomingFileError, match="snapshot was unavailable"):
        publication_spool_path(
            workspace, manifest.publication_id, manifest.files[0].source_version_id
        )


@pytest.mark.asyncio
@pytest.mark.usefixtures("root_owned_publication_spool")
async def test_recovery_keeps_a_spool_when_a_reclaimed_upload_fails(tmp_path):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "result.csv").write_bytes(b"frozen bytes")
    manifest = freeze_publication(workspace, str(uuid4()), ["result.csv"])
    local = manifest.files[0]

    class Foundry:
        async def freeze_publication_intent(self, *_args):
            return {}

        async def claim_publication_retries(self, *_args):
            return [
                {
                    "publication_id": manifest.publication_id,
                    "revision": 2,
                    "lease_token": str(uuid4()),
                    "files": [
                        {
                            "id": str(uuid4()),
                            "source_version_id": local.source_version_id,
                            "sha256": local.sha256,
                            "size": local.size,
                            "generation": 1,
                            "state": "pending",
                        }
                    ],
                }
            ]

        async def upload_publication_file(self, *_args):
            raise FoundryError("retry upload failed")

        async def get_publication(self, *_args):
            return {"state": "failed"}

    bridge = PublicationBridge(Foundry(), _Store(workspace), tmp_path)
    await bridge.recover(str(uuid4()), "ally")

    assert (
        publication_spool_path(
            workspace, manifest.publication_id, local.source_version_id
        ).read_bytes()
        == b"frozen bytes"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "spool_state", ["missing", "corrupt", "unreadable", "changed_bytes"]
)
@pytest.mark.usefixtures("root_owned_publication_spool")
async def test_recovery_reports_unavailable_spools_with_the_claim_fence(
    tmp_path, monkeypatch, spool_state
):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "result.csv").write_bytes(b"frozen bytes")
    manifest = freeze_publication(workspace, str(uuid4()), ["result.csv"])
    revision = 7
    lease_token = str(uuid4())
    reported = []
    journal = (
        tmp_path / ".allies-publications" / "ally" / f"{manifest.publication_id}.json"
    )
    if spool_state == "corrupt":
        journal.write_text("{", encoding="utf-8")
    elif spool_state == "changed_bytes":
        source = publication_spool_path(
            workspace, manifest.publication_id, manifest.files[0].source_version_id
        )
        source.write_bytes(b"changed data")
        assert source.stat().st_size == manifest.files[0].size
    elif spool_state == "unreadable":

        def unreadable_manifest_scan(*_args, **_kwargs):
            raise OSError("spool unavailable")

        monkeypatch.setattr(
            bridge_module, "recover_publication_manifests", unreadable_manifest_scan
        )
    else:
        shutil.rmtree(
            tmp_path / ".allies-publications" / "ally" / manifest.publication_id
        )

    class Foundry:
        async def freeze_publication_intent(self, *_args):
            return {}

        async def claim_publication_retries(self, *_args):
            return [
                {
                    "publication_id": manifest.publication_id,
                    "revision": revision,
                    "lease_token": lease_token,
                    "files": [
                        {
                            "id": str(uuid4()),
                            "source_version_id": manifest.files[0].source_version_id,
                            "sha256": manifest.files[0].sha256,
                            "size": manifest.files[0].size,
                            "generation": 1,
                            "state": "pending",
                        }
                    ],
                }
            ]

        async def publication_retry_result(self, *args):
            reported.append(args)
            return {}

        async def upload_publication_file(self, *_args):
            pytest.fail("unavailable source bytes must not be uploaded")

        async def get_publication(self, *_args):
            return {"state": "failed"}

    bridge = PublicationBridge(Foundry(), _Store(workspace), tmp_path)
    await bridge.recover(str(uuid4()), "ally")

    assert len(reported) == 1
    profile_id, publication_id, sent_revision, sent_lease, outcome, error_code = (
        reported[0]
    )
    assert profile_id and publication_id == manifest.publication_id
    assert (sent_revision, sent_lease, outcome, error_code) == (
        revision,
        lease_token,
        "failed",
        "source_unavailable",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_state", ["uploading", "ready"])
@pytest.mark.usefixtures("root_owned_publication_spool")
async def test_restart_reconciles_registered_publication_without_retry_claim(
    tmp_path, initial_state
):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "result.csv").write_bytes(b"frozen bytes")
    manifest = freeze_publication(workspace, str(uuid4()), ["result.csv"])
    (workspace / "result.csv").write_bytes(b"changed work")
    local = manifest.files[0]
    uploads = []

    class Foundry:
        state = initial_state

        async def freeze_publication_intent(self, *_args):
            return {}

        async def claim_publication_retries(self, *_args):
            return []

        async def get_publication(self, *_args):
            return {
                "state": self.state,
                "revision": 1,
                "files": [
                    {
                        "id": str(uuid4()),
                        "source_version_id": local.source_version_id,
                        "name": "result.csv",
                        "size": local.size,
                        "sha256": local.sha256,
                        "generation": 1,
                        "state": "ready" if self.state == "ready" else "pending",
                        "open_path": "/files/result",
                    }
                ],
            }

        async def upload_publication_file(self, *args):
            uploads.append(args[4])
            assert args[5:] == (1, None)
            self.state = "ready"
            return {}

    bridge = PublicationBridge(Foundry(), _Store(workspace), tmp_path)
    await bridge.recover(str(uuid4()), "ally")
    await bridge.recover(str(uuid4()), "ally")
    assert uploads == ([b"frozen bytes"] if initial_state == "uploading" else [])
    with pytest.raises(IncomingFileError, match="snapshot was unavailable"):
        publication_spool_path(
            workspace, manifest.publication_id, local.source_version_id
        )
