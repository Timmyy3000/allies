from __future__ import annotations

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest

from allies_runtime import files
from allies_runtime.errors import IncomingFileError
from allies_runtime.files import (
    cleanup_profile_publication_spools,
    cleanup_stale_publication_copies,
    freeze_publication,
    parse_incoming_files,
    publication_spool_path,
    reconcile_publication_spools,
    recover_publication_manifests,
    release_publication_spool,
    stage_incoming_files,
    validate_hermes_file_context,
)
from allies_runtime.foundry import (
    FoundryClaim,
    FoundryWorker,
    InvalidRequestError,
    LeaseConflictError,
    ResponseLossError,
    TerminalReceipt,
)
from allies_runtime.hermes import HermesEvent, _stream_request_body
from allies_runtime.profile_store import ProfileStoreError
from allies_runtime.publication_bridge import PublicationBridge


def _descriptor(content: bytes) -> dict[str, object]:
    return {
        "file_id": str(uuid4()),
        "name": "notes.txt",
        "media_type": "text/plain",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


async def _chunks(content: bytes):
    yield content


@pytest.mark.asyncio
async def test_stage_replays_receipt_and_preserves_an_edited_working_copy(tmp_path):
    workspace = tmp_path / "profile" / "workspace"
    workspace.mkdir(parents=True)
    content = b"verified attachment"
    descriptor = _descriptor(content)
    downloads = 0

    def fetch(_descriptor):
        nonlocal downloads
        downloads += 1
        return _chunks(content)

    command_id = str(uuid4())
    first = await stage_incoming_files(workspace, command_id, [descriptor], fetch)
    first_path = workspace / first.files[0].path
    assert first_path.read_bytes() == content
    repeated = await stage_incoming_files(workspace, command_id, [descriptor], fetch)
    assert repeated == first
    assert downloads == 1

    first_path.write_bytes(b"edited working copy")
    recovered = await stage_incoming_files(workspace, command_id, [descriptor], fetch)
    assert downloads == 2
    assert first_path.read_bytes() == b"edited working copy"
    assert recovered.files[0].path != first.files[0].path
    assert (workspace / recovered.files[0].path).read_bytes() == content


@pytest.mark.asyncio
async def test_stage_rejects_a_bad_digest_before_the_manifest_becomes_visible(tmp_path):
    workspace = tmp_path / "profile" / "workspace"
    workspace.mkdir(parents=True)
    descriptor = _descriptor(b"expected")

    with pytest.raises(IncomingFileError, match="digest"):
        await stage_incoming_files(
            workspace,
            str(uuid4()),
            [descriptor],
            lambda _descriptor: _chunks(b"wrong"),
        )

    attachments = workspace / "attachments"
    assert not attachments.exists() or not list(attachments.iterdir())


@pytest.mark.asyncio
async def test_stage_cancellation_never_commits_a_replacement_or_receipt(tmp_path):
    workspace = tmp_path / "profile" / "workspace"
    workspace.mkdir(parents=True)
    descriptor = _descriptor(b"one")
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks >= 8

    with pytest.raises(IncomingFileError, match="lease was lost"):
        await stage_incoming_files(
            workspace,
            str(uuid4()),
            [descriptor],
            lambda _descriptor: _chunks(b"one"),
            cancelled=cancelled,
        )

    attachments = workspace / "attachments"
    assert not attachments.exists() or not list(attachments.iterdir())
    assert not (workspace.parent / ".allies-incoming-receipts").exists()


def test_hermes_context_is_bounded_and_content_free():
    descriptor = _descriptor(b"one")
    context = {
        "schema_version": "v1",
        "kind": "allies_incoming_files",
        "files": [{**descriptor, "path": "attachments/turn/file-notes.txt"}],
    }

    assert validate_hermes_file_context(context) == context
    context["files"][0]["content"] = "must not pass"
    with pytest.raises(IncomingFileError):
        validate_hermes_file_context(context)


def test_manifest_rejects_a_windows_reserved_file_name():
    descriptor = _descriptor(b"one")
    descriptor["name"] = "CON.txt"

    with pytest.raises(IncomingFileError):
        parse_incoming_files([descriptor])


@pytest.mark.parametrize(
    "media_type",
    ["text/中文", "text/pläin", "text/plain\r\nX-Test: yes", "text/plain\x7f"],
)
def test_manifest_rejects_unsafe_media_types(media_type):
    descriptor = _descriptor(b"one")
    descriptor["media_type"] = media_type
    with pytest.raises(IncomingFileError):
        parse_incoming_files([descriptor])


@pytest.mark.asyncio
async def test_stage_accepts_character_bounded_names_without_using_them_as_paths(
    tmp_path,
):
    workspace = tmp_path / "profile" / "workspace"
    workspace.mkdir(parents=True)
    descriptor = _descriptor(b"one")
    descriptor["name"] = "a" * 255

    receipt = await stage_incoming_files(
        workspace,
        str(uuid4()),
        [descriptor],
        lambda _descriptor: _chunks(b"one"),
    )

    path = workspace / receipt.files[0].path
    assert path.name == descriptor["file_id"]
    assert path.read_bytes() == b"one"


def test_incoming_name_is_bounded_by_characters_not_utf8_bytes():
    descriptor = _descriptor(b"one")
    descriptor["name"] = "😀" * 255

    assert parse_incoming_files([descriptor])[0].name == descriptor["name"]

    descriptor["name"] = "a" * 256
    with pytest.raises(IncomingFileError):
        parse_incoming_files([descriptor])


def test_hermes_request_uses_a_structured_file_context():
    descriptor = _descriptor(b"one")
    context = {
        "schema_version": "v1",
        "kind": "allies_incoming_files",
        "files": [{**descriptor, "path": "attachments/turn/file-notes.txt"}],
    }

    body = json.loads(_stream_request_body("", None, context))
    assert body == {"message": "", "allies_file_context": context}


def test_hermes_context_uses_utf8_without_ascii_escape_expansion():
    files = []
    for _ in range(10):
        descriptor = _descriptor(b"one")
        descriptor["name"] = "😀" * 255
        files.append(
            {
                **descriptor,
                "path": f"attachments/turn/{descriptor['file_id']}",
            }
        )

    encoded = _stream_request_body(
        "",
        None,
        {"schema_version": "v1", "kind": "allies_incoming_files", "files": files},
    )

    assert b"\\ud83d" not in encoded
    assert len(encoded) < 16 * 1024


@pytest.mark.usefixtures("root_owned_publication_spool")
def test_publication_freezes_once_outside_the_model_workspace(tmp_path):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    result = workspace / "result.csv"
    result.write_bytes(b"name,value\nanswer,42\n")
    publication_id = str(uuid4())

    first = freeze_publication(workspace, publication_id, ["result.csv"])
    result.write_bytes(b"edited working copy")
    replay = freeze_publication(workspace, publication_id, ["result.csv"])
    spool = publication_spool_path(
        workspace, publication_id, first.files[0].source_version_id
    )

    assert replay == first
    assert replay.manifest_sha256 == first.manifest_sha256
    assert spool.read_bytes() == b"name,value\nanswer,42\n"
    assert spool.is_relative_to(tmp_path / ".allies-publications" / "ally")
    assert not spool.is_relative_to(workspace)

    release_publication_spool(workspace, publication_id)
    assert not spool.exists()
    ledger = json.loads(files._ledger_path(tmp_path).read_text())
    assert ledger["records"] == {}


@pytest.mark.usefixtures("root_owned_publication_spool")
def test_publication_rejects_links_and_profile_cleanup_is_scoped(tmp_path):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    source = workspace / "result.csv"
    source.write_bytes(b"ok")
    sibling = tmp_path / "profiles" / "other" / "workspace"
    sibling.mkdir(parents=True)
    other_source = sibling / "keep.txt"
    other_source.write_bytes(b"keep")
    try:
        (workspace / "linked.csv").symlink_to(source)
        (workspace / "linked-dir").symlink_to(sibling)
        hard_source = workspace / "hard-source.csv"
        hard_source.write_bytes(b"hard link")
        (workspace / "hard-linked.csv").hardlink_to(hard_source)
    except (OSError, NotImplementedError):
        pytest.skip("links are unavailable")

    with pytest.raises(IncomingFileError, match="unsafe"):
        freeze_publication(workspace, str(uuid4()), ["linked.csv"])
    with pytest.raises(IncomingFileError, match="unsafe"):
        freeze_publication(workspace, str(uuid4()), ["linked-dir/keep.txt"])
    with pytest.raises(IncomingFileError, match="unsafe"):
        freeze_publication(workspace, str(uuid4()), ["hard-linked.csv"])

    publication_id = str(uuid4())
    freeze_publication(workspace, publication_id, ["result.csv"])
    other_publication_id = str(uuid4())
    freeze_publication(sibling, other_publication_id, ["keep.txt"])
    cleanup_profile_publication_spools(tmp_path, "ally")

    assert not (tmp_path / ".allies-publications" / "ally").exists()
    assert other_source.read_bytes() == b"keep"
    assert (
        publication_spool_path(
            sibling,
            other_publication_id,
            recover_publication_manifests(sibling)[0].files[0].source_version_id,
        ).read_bytes()
        == b"keep"
    )


@pytest.mark.usefixtures("root_owned_publication_spool")
def test_publication_ledger_serializes_two_profile_admissions(tmp_path):
    workspaces = []
    for profile in ("ally-a", "ally-b"):
        workspace = tmp_path / "profiles" / profile / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "result.csv").write_bytes(profile.encode())
        workspaces.append(workspace)

    with ThreadPoolExecutor(max_workers=2) as executor:
        manifests = list(
            executor.map(
                lambda workspace: freeze_publication(
                    workspace, str(uuid4()), ["result.csv"]
                ),
                workspaces,
            )
        )

    assert len(manifests) == 2
    ledger = json.loads(files._ledger_path(tmp_path).read_text())
    assert len(ledger["records"]) == 2


@pytest.mark.usefixtures("root_owned_publication_spool")
def test_publication_startup_reconciliation_and_stale_copy_cleanup(tmp_path):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    source = workspace / "result.csv"
    source.write_bytes(b"reconcile")
    frozen = freeze_publication(workspace, str(uuid4()), ["result.csv"])
    ledger_path = files._ledger_path(tmp_path)
    ledger = json.loads(ledger_path.read_text())
    del ledger["records"][frozen.publication_id]
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    assert reconcile_publication_spools(tmp_path) == 1
    reconciled = json.loads(ledger_path.read_text())
    assert reconciled["records"][frozen.publication_id]["state"] == "frozen"

    partial_id = str(uuid4())
    partial = tmp_path / ".allies-publications" / "ally" / f".{partial_id}.old.copy"
    partial.mkdir()
    partial.joinpath("part.bin").write_bytes(b"partial")
    reconciled["records"][partial_id] = {
        "profile": "ally",
        "size": 7,
        "state": "copying",
        "updated_at": 0,
    }
    ledger_path.write_text(json.dumps(reconciled), encoding="utf-8")

    assert cleanup_stale_publication_copies(tmp_path, now=24 * 60 * 60 + 1) == 1
    assert not partial.exists()
    assert partial_id not in json.loads(ledger_path.read_text())["records"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("root_owned_publication_spool")
@pytest.mark.parametrize("cleanup_error", [None, OSError, IncomingFileError])
async def test_publication_bridge_waits_for_cloud_ready_without_a_model_call(
    tmp_path, monkeypatch, cleanup_error
):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    source = workspace / "result.csv"
    source.write_bytes(b"stable result")
    second_source = workspace / "second.csv"
    second_source.write_bytes(b"second result")
    publication_id = str(uuid4())
    cloud_file_id = str(uuid4())
    second_cloud_file_id = str(uuid4())
    calls = []
    get_calls = 0

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("allies_runtime.publication_bridge.asyncio.sleep", no_sleep)
    if cleanup_error is not None:

        def fail_release(*_args):
            raise cleanup_error("cleanup unavailable")

        monkeypatch.setattr(
            "allies_runtime.publication_bridge.release_publication_spool", fail_release
        )

    class ProfileStore:
        def workspace_path(self, profile_key):
            assert profile_key == "ally"
            return workspace

    class Foundry:
        async def create_publication_intent(self, *args):
            calls.append(("intent", args))
            return {"publication_id": publication_id, "state": "preparing"}

        async def freeze_publication_intent(self, *args):
            calls.append(("frozen", args))
            return {"publication_id": publication_id, "state": "frozen"}

        async def register_publication(self, *args):
            calls.append(("register", args))
            frozen = args[3]
            return {
                "publication_id": publication_id,
                "state": "uploading",
                "revision": 1,
                "files": [
                    {
                        "id": second_cloud_file_id,
                        "source_version_id": frozen[1]["source_version_id"],
                        "sha256": frozen[1]["sha256"],
                        "size": frozen[1]["size"],
                        "generation": 1,
                        "state": "pending",
                    },
                    {
                        "id": cloud_file_id,
                        "source_version_id": frozen[0]["source_version_id"],
                        "sha256": frozen[0]["sha256"],
                        "size": frozen[0]["size"],
                        "generation": 1,
                        "state": "pending",
                    },
                ],
            }

        async def upload_publication_file(self, *args):
            calls.append(("upload", args))
            return {"id": cloud_file_id, "generation": 1, "state": "validating"}

        async def get_publication(self, *args):
            nonlocal get_calls
            calls.append(("get", args))
            get_calls += 1
            if get_calls == 1:
                return {
                    "publication_id": publication_id,
                    "state": "validating",
                    "files": [],
                }
            return {
                "publication_id": publication_id,
                "state": "ready",
                "files": [
                    {"name": "result.csv", "open_path": "/files/ready"},
                    {"name": "second.csv", "open_path": "/files/second"},
                ],
            }

    claim = FoundryClaim(
        attempt_id=str(uuid4()),
        execution_id=str(uuid4()),
        profile_id=str(uuid4()),
        hermes_profile_key="ally",
        model="gpt-test",
        conversation_id="conversation",
        session_id="session",
        stream_id="stream",
        lease_id=str(uuid4()),
        lease_token="lease",
        expires_at=None,
        payload={"message": ""},
        claim_id=str(uuid4()),
    )
    bridge = PublicationBridge(Foundry(), ProfileStore(), tmp_path)
    context = bridge.activate(claim)

    result = await bridge.publish(context, "publish-1", ["result.csv", "second.csv"])
    source.write_bytes(b"edited after freeze")

    assert result == {
        "publication_id": publication_id,
        "state": "ready",
        "files": [
            {"name": "result.csv", "open_path": "/files/ready"},
            {"name": "second.csv", "open_path": "/files/second"},
        ],
    }
    assert [name for name, _args in calls] == [
        "intent",
        "frozen",
        "register",
        "upload",
        "upload",
        "get",
        "get",
    ]
    upload = calls[3][1]
    assert upload[4] == b"stable result"
    assert calls[4][1][4] == b"second result"

    bridge.deactivate(context)
    assert await bridge.publish(context, "publish-1", ["result.csv"]) == {
        "state": "failed",
        "retryable": True,
        "error_code": "publication_context_invalid",
    }


@pytest.mark.asyncio
@pytest.mark.usefixtures("root_owned_publication_spool")
async def test_publication_bridge_stops_polling_when_lease_is_lost(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "result.csv").write_bytes(b"stable result")
    publication_id = str(uuid4())
    cloud_file_id = str(uuid4())
    cancelled = asyncio.Event()
    calls = []

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("allies_runtime.publication_bridge.asyncio.sleep", no_sleep)

    class ProfileStore:
        def workspace_path(self, _profile_key):
            return workspace

    class Foundry:
        async def create_publication_intent(self, *_args):
            return {"publication_id": publication_id}

        async def freeze_publication_intent(self, *_args):
            return {}

        async def register_publication(self, _attempt, _lease, _publication, frozen):
            return {
                "revision": 1,
                "files": [
                    {
                        "id": cloud_file_id,
                        "source_version_id": frozen[0]["source_version_id"],
                        "sha256": frozen[0]["sha256"],
                        "size": frozen[0]["size"],
                        "generation": 1,
                    }
                ],
            }

        async def upload_publication_file(self, *_args):
            calls.append("upload")
            return {}

        async def get_publication(self, *_args):
            calls.append("get")
            cancelled.set()
            return {
                "publication_id": publication_id,
                "state": "validating",
                "files": [],
            }

    claim = FoundryClaim(
        attempt_id=str(uuid4()),
        execution_id=str(uuid4()),
        profile_id=str(uuid4()),
        hermes_profile_key="ally",
        model="gpt-test",
        conversation_id="conversation",
        session_id="session",
        stream_id="stream",
        lease_id=str(uuid4()),
        lease_token="lease",
        expires_at=None,
        payload={"message": ""},
        claim_id=str(uuid4()),
    )
    bridge = PublicationBridge(Foundry(), ProfileStore(), tmp_path)
    context = bridge.activate(claim, cancelled=cancelled.is_set)

    assert await bridge.publish(context, "publish-lost", ["result.csv"]) == {
        "publication_id": publication_id,
        "state": "failed",
        "retryable": True,
        "error_code": "publication_context_invalid",
    }
    assert calls == ["upload", "get"]
    assert recover_publication_manifests(workspace)[0].publication_id == publication_id


@pytest.mark.asyncio
async def test_lost_intent_acknowledgement_cannot_create_a_spool(tmp_path):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "result.csv").write_bytes(b"result")

    class ProfileStore:
        def workspace_path(self, _profile_key):
            return workspace

    class Foundry:
        async def create_publication_intent(self, *_args):
            raise ResponseLossError("response was lost")

    claim = FoundryClaim(
        attempt_id=str(uuid4()),
        execution_id=str(uuid4()),
        profile_id=str(uuid4()),
        hermes_profile_key="ally",
        model="gpt-test",
        conversation_id="conversation",
        session_id="session",
        stream_id="stream",
        lease_id=str(uuid4()),
        lease_token="lease",
        expires_at=None,
        payload={"message": ""},
        claim_id=str(uuid4()),
    )
    bridge = PublicationBridge(Foundry(), ProfileStore(), tmp_path)
    context = bridge.activate(claim)

    assert await bridge.publish(context, "publish-lost", ["result.csv"]) == {
        "state": "failed",
        "retryable": True,
        "error_code": "publication_unavailable",
    }
    assert not (tmp_path / ".allies-publications").exists()


@pytest.mark.asyncio
@pytest.mark.usefixtures("root_owned_publication_spool")
async def test_recovery_reuses_frozen_bytes_after_the_workspace_changes(tmp_path):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    source = workspace / "result.csv"
    source.write_bytes(b"frozen result")
    manifest = freeze_publication(workspace, str(uuid4()), ["result.csv"])
    source.write_bytes(b"later edit")
    acknowledgements = []

    class ProfileStore:
        def workspace_path(self, _profile_key):
            return workspace

    class Foundry:
        async def freeze_publication_intent(self, _profile, _publication, files):
            acknowledgements.append(files)

        async def claim_publication_retries(self, _profile, _limit):
            return []

        async def get_publication(self, *_args):
            return {"state": "failed"}

    bridge = PublicationBridge(Foundry(), ProfileStore(), tmp_path)
    await bridge.recover(str(uuid4()), "ally")

    assert acknowledgements == [manifest.frozen_files()]
    assert (
        publication_spool_path(
            workspace, manifest.publication_id, manifest.files[0].source_version_id
        ).read_bytes()
        == b"frozen result"
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("root_owned_publication_spool")
async def test_publication_recovery_skips_cloud_ready_rows(tmp_path):
    workspace = tmp_path / "profiles" / "ally" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "first.csv").write_bytes(b"first")
    (workspace / "second.csv").write_bytes(b"second")
    manifest = freeze_publication(workspace, str(uuid4()), ["first.csv", "second.csv"])
    uploaded = []

    class ProfileStore:
        def workspace_path(self, _profile_key):
            return workspace

    class Foundry:
        async def freeze_publication_intent(self, *_args):
            return {}

        async def claim_publication_retries(self, _profile, _limit):
            return [
                {
                    "publication_id": manifest.publication_id,
                    "revision": 2,
                    "lease_token": str(uuid4()),
                    "files": [
                        {
                            "id": str(uuid4()),
                            "source_version_id": manifest.files[1].source_version_id,
                            "sha256": manifest.files[1].sha256,
                            "size": manifest.files[1].size,
                            "generation": 1,
                            "state": "pending",
                        },
                        {
                            "id": str(uuid4()),
                            "source_version_id": manifest.files[0].source_version_id,
                            "sha256": manifest.files[0].sha256,
                            "size": manifest.files[0].size,
                            "generation": 1,
                            "state": "ready",
                        },
                    ],
                }
            ]

        async def upload_publication_file(self, *_args):
            uploaded.append(_args[4])
            return {}

        async def publication_retry_result(self, *_args):
            return {}

        async def get_publication(self, *_args):
            return {"state": "validating", "files": []}

    bridge = PublicationBridge(Foundry(), ProfileStore(), tmp_path)
    await bridge.recover(str(uuid4()), "ally")

    assert uploaded == [b"second"]
    assert recover_publication_manifests(workspace)[0] == manifest


@pytest.mark.asyncio
@pytest.mark.parametrize("removed_profile", [False, True])
async def test_publication_recovery_rotates_one_bounded_profile_without_a_model_call(
    removed_profile,
):
    calls = []
    now = 0.0
    active = asyncio.Event()

    class Bridge:
        async def recover(self, profile_id, profile_key, *, limit):
            calls.append((profile_id, profile_key, limit))
            if removed_profile and profile_key == "a":
                raise ProfileStoreError("profile removed")

    def clock():
        return now

    worker = FoundryWorker(object(), object(), publication_bridge=Bridge(), clock=clock)
    active_task = asyncio.create_task(active.wait())
    worker._active.add(active_task)
    snapshot = SimpleNamespace(
        profiles=(
            SimpleNamespace(profile_id="profile-b", hermes_profile_key="b"),
            SimpleNamespace(profile_id="profile-a", hermes_profile_key="a"),
        )
    )

    try:
        await worker._recover_publications(snapshot)
        now = 30.0
        await worker._recover_publications(snapshot)
    finally:
        active_task.cancel()
        await asyncio.gather(active_task, return_exceptions=True)

    assert calls == [("profile-a", "a", 20), ("profile-b", "b", 20)]


@pytest.mark.asyncio
async def test_worker_stages_files_before_it_invokes_hermes(tmp_path):
    workspace = tmp_path / "profile" / "workspace"
    workspace.mkdir(parents=True)
    content = b"verified attachment"
    descriptor = _descriptor(content)
    calls: list[str] = []

    class ProfileStore:
        def workspace_path(self, _profile_key):
            return workspace

    class Foundry:
        async def incoming_file_chunks(self, _attempt, _file, _lease):
            calls.append("fetch")
            yield content

        async def renew(self, _attempt, _lease):
            return None

        async def event(self, *_args, **_kwargs):
            calls.append("event")

        async def bind(self, *_args, **_kwargs):
            return "session"

        async def complete(self, *_args, **_kwargs):
            return TerminalReceipt("attempt", "succeeded", "receipt")

        async def fail(self, *_args, **_kwargs):
            pytest.fail("worker must not invoke the model after staging failed")

    class Hermes:
        async def stream_profile_incremental(self, *_args, **kwargs):
            calls.append("hermes")
            assert (
                kwargs["file_context"]["files"][0]["file_id"] == descriptor["file_id"]
            )

            async def events():
                yield HermesEvent(
                    "execution.completed",
                    "ally",
                    "session",
                    "run",
                    1,
                    {"run_id": "run", "status": "completed"},
                )

            return events()

    claim = FoundryClaim(
        attempt_id=str(uuid4()),
        execution_id=str(uuid4()),
        profile_id=str(uuid4()),
        hermes_profile_key="ally",
        model="gpt-test",
        conversation_id="conversation",
        session_id="session",
        stream_id="stream",
        lease_id=str(uuid4()),
        lease_token="lease",
        expires_at=None,
        payload={"message": "", "files": [descriptor]},
        claim_id=str(uuid4()),
    )
    worker = FoundryWorker(
        Foundry(),
        Hermes(),
        profile_store=ProfileStore(),
        file_input_enabled=True,
    )

    receipt = await worker.run_claim(claim)
    assert receipt.status == "succeeded"
    assert calls == ["fetch", "event", "hermes"]


@pytest.mark.asyncio
async def test_worker_lease_loss_during_download_cannot_commit_or_call_hermes(tmp_path):
    workspace = tmp_path / "profile" / "workspace"
    workspace.mkdir(parents=True)
    content = b"two chunks"
    descriptor = _descriptor(content)
    calls: list[str] = []

    class ProfileStore:
        def workspace_path(self, _profile_key):
            return workspace

    class Foundry:
        async def incoming_file_chunks(self, _attempt, _file, _lease):
            calls.append("fetch")
            yield content[:3]
            await asyncio.sleep(0.03)
            yield content[3:]

        async def renew(self, _attempt, _lease):
            raise LeaseConflictError("lease expired")

        async def stopped(self, *_args, **_kwargs):
            calls.append("stopped")
            return TerminalReceipt("attempt", "stopped", "receipt")

        async def fail(self, *_args, **_kwargs):
            pytest.fail("worker must not fail or requeue a stale staged file")

    class Hermes:
        async def stream_profile_incremental(self, *_args, **_kwargs):
            pytest.fail("worker must not invoke Hermes after lease loss")

    claim = FoundryClaim(
        attempt_id=str(uuid4()),
        execution_id=str(uuid4()),
        profile_id=str(uuid4()),
        hermes_profile_key="ally",
        model="gpt-test",
        conversation_id="conversation",
        session_id="session",
        stream_id="stream",
        lease_id=str(uuid4()),
        lease_token="lease",
        expires_at=None,
        payload={"message": "", "files": [descriptor]},
        claim_id=str(uuid4()),
    )
    worker = FoundryWorker(
        Foundry(),
        Hermes(),
        profile_store=ProfileStore(),
        file_input_enabled=True,
        renew_interval=0.01,
        lease_seconds=1,
        stop_safety_margin=0.1,
    )

    receipt = await worker.run_claim(claim)

    assert receipt.status == "stopped"
    assert calls == ["fetch", "stopped"]
    attachments = workspace / "attachments"
    assert not attachments.exists() or not list(attachments.iterdir())
    assert not (workspace.parent / ".allies-incoming-receipts").exists()


@pytest.mark.asyncio
async def test_worker_terminalizes_a_cloud_file_error_before_model_dispatch(tmp_path):
    workspace = tmp_path / "profile" / "workspace"
    workspace.mkdir(parents=True)
    descriptor = _descriptor(b"unavailable")
    calls: list[str] = []

    class ProfileStore:
        def workspace_path(self, _profile_key):
            return workspace

    class Foundry:
        async def incoming_file_chunks(self, *_args):
            raise InvalidRequestError("accepted file is unavailable")
            yield b""  # pragma: no cover - keeps this an async generator

        async def fail(self, *_args, **kwargs):
            calls.append(kwargs["code"])
            return TerminalReceipt("attempt", "failed", "receipt")

    class Hermes:
        async def stream_profile_incremental(self, *_args, **_kwargs):
            pytest.fail("worker must not invoke Hermes after a Cloud file error")

    claim = FoundryClaim(
        attempt_id=str(uuid4()),
        execution_id=str(uuid4()),
        profile_id=str(uuid4()),
        hermes_profile_key="ally",
        model="gpt-test",
        conversation_id="conversation",
        session_id="session",
        stream_id="stream",
        lease_id=str(uuid4()),
        lease_token="lease",
        expires_at=None,
        payload={"message": "", "files": [descriptor]},
        claim_id=str(uuid4()),
    )

    receipt = await FoundryWorker(
        Foundry(), Hermes(), profile_store=ProfileStore(), file_input_enabled=True
    ).run_claim(claim)

    assert receipt.status == "failed"
    assert calls == ["INVALID_REQUEST"]


@pytest.mark.asyncio
async def test_worker_rejects_files_for_a_routine_before_staging():
    descriptor = _descriptor(b"routine attachment")
    failures = []

    class Foundry:
        async def routine_result(self, *_args, **kwargs):
            failures.append(kwargs["outcome"])
            return TerminalReceipt("attempt", "failed", "receipt")

    claim = FoundryClaim(
        attempt_id=str(uuid4()),
        execution_id=str(uuid4()),
        profile_id=str(uuid4()),
        hermes_profile_key="ally",
        model="gpt-test",
        conversation_id="routine-conversation",
        session_id="session",
        stream_id="stream",
        lease_id=str(uuid4()),
        lease_token="lease",
        expires_at=None,
        payload={"execution_prompt": "run", "files": [descriptor]},
        claim_id=str(uuid4()),
        routine_id=str(uuid4()),
    )
    worker = FoundryWorker(
        Foundry(),
        object(),
        profile_store=object(),
        file_input_enabled=True,
    )

    receipt = await worker.run_claim(claim)
    assert receipt.status == "failed"
    assert failures == ["failed"]
