"""Private synchronous bridge for the Hermes publication tool."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

try:  # pragma: no cover - Windows has no Unix group database
    import grp
except ImportError:  # pragma: no cover - exercised by Windows test imports
    grp = None

from .errors import IncomingFileError
from .files import (
    _validate_publication_volume_root,
    cleanup_stale_publication_copies,
    freeze_publication,
    prepare_publication_files,
    publication_spool_path,
    reconcile_publication_spools,
    recover_publication_manifests,
    release_publication_spool,
)
from .foundry import FoundryError
from .profile_store import ProfileStoreError

BRIDGE_DIRECTORY = ".allies-publication-bridge"
BRIDGE_SOCKET_NAME = "socket"
MAX_REQUEST_BYTES = 8 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
BRIDGE_TIMEOUT_SECONDS = 305
BRIDGE_GROUP = "allies-publication"
PUBLICATION_READY_TIMEOUT_SECONDS = 300
PUBLICATION_POLL_SECONDS = 5
_CONTEXT = re.compile(r"^[0-9a-f]{64}$")
_TOOL_CALL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class _Session:
    attempt_id: str
    execution_id: str
    profile_id: str
    profile_key: str
    lease_token: str
    cancelled: Callable[[], bool] | None


class PublicationBridge:
    """Keep tool authority in the active runtime claim, outside model input."""

    def __init__(
        self, foundry: Any, profile_store: Any, volume_root: str | Path
    ) -> None:
        self._foundry = foundry
        self._profile_store = profile_store
        self._volume_root = Path(volume_root)
        self._root = self._volume_root / BRIDGE_DIRECTORY
        self._sessions: dict[str, _Session] = {}
        self._server: asyncio.AbstractServer | None = None
        self._last_partial_cleanup: float | None = None
        self._available = True

    @property
    def socket_path(self) -> Path:
        return self._root / BRIDGE_SOCKET_NAME

    def activate(
        self, claim: Any, *, cancelled: Callable[[], bool] | None = None
    ) -> str | None:
        if not self._available:
            return None
        nonce = os.urandom(32).hex()
        self._sessions[nonce] = _Session(
            attempt_id=str(claim.attempt_id),
            execution_id=str(claim.execution_id),
            profile_id=str(claim.profile_id),
            profile_key=str(claim.hermes_profile_key),
            lease_token=str(claim.lease_token),
            cancelled=cancelled,
        )
        return nonce

    def deactivate(self, nonce: str) -> None:
        self._sessions.pop(nonce, None)

    async def start(self) -> bool:
        self._available = False
        if os.name == "nt" or os.geteuid() != 0:
            return False
        try:
            await asyncio.to_thread(
                _validate_publication_volume_root, self._volume_root
            )
            await asyncio.to_thread(reconcile_publication_spools, self._volume_root)
            await asyncio.to_thread(cleanup_stale_publication_copies, self._volume_root)
            self._last_partial_cleanup = asyncio.get_running_loop().time()
            if grp is None:
                raise KeyError(BRIDGE_GROUP)
            group_id = grp.getgrnam(BRIDGE_GROUP).gr_gid
            try:
                root_metadata = self._root.lstat()
            except FileNotFoundError:
                self._root.mkdir(mode=0o750)
                os.chown(self._root, 0, group_id)
                os.chmod(self._root, 0o750)
            else:
                if (
                    stat.S_ISLNK(root_metadata.st_mode)
                    or not stat.S_ISDIR(root_metadata.st_mode)
                    or root_metadata.st_uid != 0
                    or root_metadata.st_gid != group_id
                    or stat.S_IMODE(root_metadata.st_mode) != 0o750
                ):
                    raise IncomingFileError("publication bridge was unavailable")
            self.socket_path.unlink(missing_ok=True)
            self._server = await asyncio.start_unix_server(
                self._handle, self.socket_path, limit=MAX_REQUEST_BYTES
            )
            os.chown(self.socket_path, 0, group_id)
            os.chmod(self.socket_path, 0o660)
        except (IncomingFileError, KeyError, OSError):
            await self._stop_server()
            self._sessions.clear()
            return False
        self._available = True
        return True

    async def close(self) -> None:
        self._available = False
        await self._stop_server()
        if self._root.exists() and not self._root.is_symlink() and self._root.is_dir():
            self.socket_path.unlink(missing_ok=True)
        self._sessions.clear()

    async def _stop_server(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def publish(
        self, context: str, tool_call_id: str, paths: Sequence[str]
    ) -> dict[str, object]:
        if not isinstance(context, str) or _CONTEXT.fullmatch(context) is None:
            return _failed("publication_context_invalid")
        if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes)):
            return _failed("publication_request_invalid")
        session = self._sessions.get(context)
        if session is None or not _session_active(self._sessions, context, session):
            return _failed("publication_context_invalid")
        if (
            not isinstance(tool_call_id, str)
            or _TOOL_CALL.fullmatch(tool_call_id) is None
        ):
            return _failed("publication_request_invalid")
        deadline = asyncio.get_running_loop().time() + PUBLICATION_READY_TIMEOUT_SECONDS
        publication_id: str | None = None
        try:
            workspace = self._profile_store.workspace_path(session.profile_key)
            prepared = await asyncio.to_thread(
                prepare_publication_files, workspace, paths
            )
            if not _session_active(self._sessions, context, session):
                return _failed("publication_context_invalid")
            intent = await self._foundry.create_publication_intent(
                session.attempt_id, session.lease_token, tool_call_id, prepared
            )
            publication_id = _uuid(intent.get("publication_id"))
            if not _session_active(self._sessions, context, session):
                return _failed("publication_context_invalid", publication_id)
            manifest = await asyncio.to_thread(
                freeze_publication, workspace, publication_id, paths
            )
            frozen = manifest.frozen_files()
            if not _session_active(self._sessions, context, session):
                return _failed("publication_context_invalid", publication_id)
            await self._foundry.freeze_publication_intent(
                session.profile_id, publication_id, frozen
            )
            if not _session_active(self._sessions, context, session):
                return _failed("publication_context_invalid", publication_id)
            reservation = await self._foundry.register_publication(
                session.attempt_id, session.lease_token, publication_id, frozen
            )
            revision = reservation.get("revision")
            rows = reservation.get("files")
            if not isinstance(revision, int) or isinstance(revision, bool):
                return _failed("publication_response_invalid", publication_id)
            rows_by_source = _cloud_file_rows(rows, manifest)
            for frozen_file in manifest.files:
                if not _session_active(self._sessions, context, session):
                    return _failed("publication_context_invalid", publication_id)
                row = rows_by_source[frozen_file.source_version_id]
                file_id = _uuid(row.get("id"))
                generation = _generation(row.get("generation"))
                spool = await asyncio.to_thread(
                    publication_spool_path,
                    workspace,
                    publication_id,
                    frozen_file.source_version_id,
                )
                content = await asyncio.to_thread(spool.read_bytes)
                if not _session_active(self._sessions, context, session):
                    return _failed("publication_context_invalid", publication_id)
                await self._foundry.upload_publication_file(
                    session.profile_id,
                    publication_id,
                    file_id,
                    generation,
                    content,
                    revision,
                )
            result = await self._wait_for_ready(
                context, session, publication_id, deadline
            )
        except (
            FoundryError,
            IncomingFileError,
            ProfileStoreError,
            OSError,
            TypeError,
            ValueError,
        ):
            return _failed("publication_unavailable", publication_id)
        if result.get("state") == "ready":
            try:
                await asyncio.to_thread(
                    release_publication_spool, workspace, publication_id
                )
            except (IncomingFileError, OSError):
                pass
        return result

    async def _wait_for_ready(
        self,
        context: str,
        session: _Session,
        publication_id: str,
        deadline: float,
    ) -> dict[str, object]:
        while _session_active(self._sessions, context, session):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return _failed("publication_pending", publication_id)
            try:
                view = await asyncio.wait_for(
                    self._foundry.get_publication(session.profile_id, publication_id),
                    remaining,
                )
            except TimeoutError:
                return _failed("publication_pending", publication_id)
            if not isinstance(view, Mapping):
                raise TypeError("publication response was invalid")
            state = view.get("state")
            if state == "failed":
                return _failed("publication_failed", publication_id)
            result = _ready_view(view, publication_id)
            if state == "ready":
                return result
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return _failed("publication_pending", publication_id)
            await asyncio.sleep(min(PUBLICATION_POLL_SECONDS, remaining))
        return _failed("publication_context_invalid", publication_id)

    async def recover(self, profile_id: str, profile_key: str, limit: int = 20) -> None:
        """Resume frozen work from the original intent without a model call."""

        if not self._available:
            return
        now = asyncio.get_running_loop().time()
        if self._last_partial_cleanup is None or now - self._last_partial_cleanup >= 60:
            await asyncio.to_thread(cleanup_stale_publication_copies, self._volume_root)
            self._last_partial_cleanup = now
        try:
            workspace = self._profile_store.workspace_path(profile_key)
        except ProfileStoreError:
            return
        try:
            manifests = await asyncio.to_thread(
                recover_publication_manifests, workspace, limit
            )
        except (IncomingFileError, OSError):
            manifests = ()
        released = set()
        for manifest in manifests:
            try:
                await self._foundry.freeze_publication_intent(
                    profile_id, manifest.publication_id, manifest.frozen_files()
                )
                view = await self._foundry.get_publication(
                    profile_id, manifest.publication_id
                )
                if _ready_view(view, manifest.publication_id).get("state") == "ready":
                    await asyncio.to_thread(
                        release_publication_spool, workspace, manifest.publication_id
                    )
                    released.add(manifest.publication_id)
                elif view.get("revision") == 1 and view.get("state") in {
                    "uploading",
                    "validating",
                }:
                    await self._upload_frozen_files(
                        profile_id, workspace, manifest, view.get("files"), 1
                    )
            except (FoundryError, IncomingFileError, OSError, TypeError, ValueError):
                continue
        try:
            claims = await self._foundry.claim_publication_retries(profile_id, limit)
        except FoundryError:
            return
        by_id = {item.publication_id: item for item in manifests}
        for claim in claims:
            if not isinstance(claim, Mapping):
                continue
            try:
                publication_id = _uuid(claim.get("publication_id"))
                if publication_id in released:
                    continue
                revision = claim.get("revision")
                lease_token = _uuid(claim.get("lease_token"))
                rows = claim.get("files")
                if (
                    not isinstance(revision, int)
                    or isinstance(revision, bool)
                    or revision < 1
                ):
                    continue
                manifest = by_id.get(publication_id)
                if manifest is None:
                    await self._report_source_unavailable(
                        profile_id, publication_id, revision, lease_token
                    )
                    continue
                try:
                    await self._upload_frozen_files(
                        profile_id, workspace, manifest, rows, revision, lease_token
                    )
                except (IncomingFileError, OSError):
                    await self._report_source_unavailable(
                        profile_id, publication_id, revision, lease_token
                    )
                    continue
                await self._foundry.publication_retry_result(
                    profile_id, publication_id, revision, lease_token, "submitted"
                )
                view = await self._foundry.get_publication(profile_id, publication_id)
                if _ready_view(view, publication_id).get("state") == "ready":
                    await asyncio.to_thread(
                        release_publication_spool, workspace, publication_id
                    )
            except (FoundryError, IncomingFileError, KeyError, TypeError, ValueError):
                continue

    async def _upload_frozen_files(
        self, profile_id, workspace, manifest, rows, revision, lease_token=None
    ) -> None:
        rows_by_source = _cloud_file_rows(rows, manifest)
        for local_file in manifest.files:
            row = rows_by_source[local_file.source_version_id]
            if row.get("state") in {"ready", "validating"}:
                continue
            content_path = await asyncio.to_thread(
                publication_spool_path,
                workspace,
                manifest.publication_id,
                local_file.source_version_id,
            )
            content = await asyncio.to_thread(content_path.read_bytes)
            if hashlib.sha256(content).hexdigest() != local_file.sha256:
                raise IncomingFileError("publication source digest changed")
            await self._foundry.upload_publication_file(
                profile_id,
                manifest.publication_id,
                _uuid(row.get("id")),
                _generation(row.get("generation")),
                content,
                revision,
                lease_token,
            )

    async def _report_source_unavailable(
        self, profile_id: str, publication_id: str, revision: int, lease_token: str
    ) -> None:
        try:
            await self._foundry.publication_retry_result(
                profile_id,
                publication_id,
                revision,
                lease_token,
                "failed",
                "source_unavailable",
            )
        except (AttributeError, FoundryError, OSError, TypeError, ValueError):
            return

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            try:
                raw = await asyncio.wait_for(reader.readline(), BRIDGE_TIMEOUT_SECONDS)
            except ValueError:
                raw = b""
            if not raw or len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
                result = _failed("publication_request_invalid")
            else:
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError:
                    value = None
                if not isinstance(value, Mapping) or set(value) != {
                    "context",
                    "tool_call_id",
                    "paths",
                }:
                    result = _failed("publication_request_invalid")
                else:
                    result = await self.publish(
                        value.get("context"),
                        value.get("tool_call_id"),
                        value.get("paths"),
                    )
            encoded = json.dumps(
                result, ensure_ascii=False, separators=(",", ":")
            ).encode()
            if len(encoded) > MAX_RESPONSE_BYTES:
                encoded = (
                    b'{"state":"failed","retryable":true,'
                    b'"error_code":"publication_response_invalid"}'
                )
            writer.write(encoded + b"\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()


def _session_active(
    sessions: Mapping[str, _Session], context: str, session: _Session
) -> bool:
    if sessions.get(context) is not session:
        return False
    return session.cancelled is None or not session.cancelled()


def _uuid(value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError("publication identity was invalid") from exc


def _failed(code: str, publication_id: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "state": "failed",
        "retryable": True,
        "error_code": code,
    }
    if publication_id is not None:
        result["publication_id"] = publication_id
    return result


def _cloud_file_rows(rows: object, manifest: Any) -> dict[str, Mapping[str, object]]:
    if not isinstance(rows, list) or len(rows) != len(manifest.files):
        raise ValueError("publication response was invalid")
    expected = {item.source_version_id: item for item in manifest.files}
    resolved: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("publication response was invalid")
        source_version_id = _uuid(row.get("source_version_id"))
        expected_file = expected.get(source_version_id)
        if (
            expected_file is None
            or row.get("sha256") != expected_file.sha256
            or row.get("size") != expected_file.size
            or source_version_id in resolved
        ):
            raise ValueError("publication response was invalid")
        resolved[source_version_id] = row
    if len(resolved) != len(expected):
        raise ValueError("publication response was invalid")
    return resolved


def _generation(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("publication generation was invalid")
    return value


def _ready_view(value: Mapping[str, object], publication_id: str) -> dict[str, object]:
    files = value.get("files")
    if value.get("state") != "ready" or not isinstance(files, list):
        return _failed("publication_pending", publication_id)
    links = []
    for item in files:
        if not isinstance(item, Mapping):
            return _failed("publication_response_invalid", publication_id)
        name = item.get("name")
        path = item.get("open_path")
        if not isinstance(name, str) or not isinstance(path, str):
            return _failed("publication_response_invalid", publication_id)
        links.append({"name": name, "open_path": path})
    return {"publication_id": publication_id, "state": "ready", "files": links}


__all__ = ["BRIDGE_DIRECTORY", "BRIDGE_SOCKET_NAME", "PublicationBridge"]
