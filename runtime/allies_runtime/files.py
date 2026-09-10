"""Verified, profile-local staging for one immutable incoming file manifest."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import threading
import time
import unicodedata
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from .errors import IncomingFileError

try:  # pragma: no cover - runtime images use Linux advisory locks
    import fcntl
except ImportError:  # pragma: no cover - Windows uses the in-process fallback
    fcntl = None

MAX_FILES = 10
MAX_FILE_BYTES = 25_000_000
MAX_TOTAL_BYTES = 50_000_000
MAX_CHUNK_BYTES = 64 * 1024
MAX_FILE_SECONDS = 120.0
MAX_SET_SECONDS = 300.0
MAX_PUBLICATION_MANIFESTS = 20
MAX_PUBLICATION_INCOMPLETE = 2
MAX_PUBLICATION_FILE_BYTES = 25_000_000
MAX_PUBLICATION_BYTES = 50_000_000
MAX_PROFILE_PUBLICATION_BYTES = 100_000_000
MAX_VOLUME_PUBLICATION_BYTES = 250_000_000
MIN_VOLUME_FREE_BYTES = 250_000_000
MAX_PARTIAL_PUBLICATION_CLEANUP = 100
PARTIAL_PUBLICATION_STALE_SECONDS = 24 * 60 * 60
_PUBLICATION_SCHEMA = "allies.publication.v1"
_RECEIPT_SCHEMA = "allies.incoming-files.v1"
_PUBLICATION_STATE_DIRECTORY = ".allies-publication-state"
_publication_locks: dict[str, threading.Lock] = {}
_publication_locks_guard = threading.Lock()
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)


@dataclass(frozen=True, slots=True)
class IncomingFile:
    file_id: str
    name: str
    media_type: str
    size: int
    sha256: str

    def manifest_value(self) -> dict[str, object]:
        return {
            "file_id": self.file_id,
            "name": self.name,
            "media_type": self.media_type,
            "size": self.size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class StagedFile:
    descriptor: IncomingFile
    path: str

    def hermes_value(self) -> dict[str, object]:
        return {**self.descriptor.manifest_value(), "path": self.path}


@dataclass(frozen=True, slots=True)
class StagedManifest:
    command_id: str
    manifest_sha256: str
    files: tuple[StagedFile, ...]

    def hermes_context(self) -> dict[str, object]:
        return {
            "schema_version": "v1",
            "kind": "allies_incoming_files",
            "files": [item.hermes_value() for item in self.files],
        }


@dataclass(frozen=True, slots=True)
class PublicationFile:
    source_version_id: str
    name: str
    size: int
    sha256: str
    spool_path: str

    def frozen_value(self) -> dict[str, object]:
        return {
            "source_version_id": self.source_version_id,
            "name": self.name,
            "size": self.size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class PublicationManifest:
    publication_id: str
    manifest_sha256: str
    files: tuple[PublicationFile, ...]

    def frozen_files(self) -> list[dict[str, object]]:
        return [item.frozen_value() for item in self.files]


FileFetcher = Callable[[IncomingFile], AsyncIterator[bytes]]


def prepare_publication_files(
    workspace: Path, paths: Sequence[str]
) -> list[dict[str, object]]:
    """Read bounded descriptors before the publication intent is persisted."""

    workspace = _workspace(workspace)
    source_paths = _publication_paths(paths)
    prepared: list[dict[str, object]] = []
    total = 0
    for relative in source_paths:
        try:
            _source, metadata = _publication_source(workspace, relative)
        except IncomingFileError:
            raise
        except OSError:
            raise IncomingFileError("publication source was unavailable") from None
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or not 1 <= metadata.st_size <= MAX_PUBLICATION_FILE_BYTES
        ):
            raise IncomingFileError("publication source was unsafe")
        total += metadata.st_size
        if total > MAX_PUBLICATION_BYTES:
            raise IncomingFileError("publication file set exceeds 50 MB")
        prepared.append({"name": relative.name, "size": metadata.st_size})
    return prepared


def freeze_publication(
    workspace: Path,
    publication_id: str,
    paths: Sequence[str],
) -> PublicationManifest:
    """Copy an immutable, verified snapshot outside Hermes' workspace."""

    workspace = _workspace(workspace)
    publication_id = _command_id(publication_id)
    source_paths = _publication_paths(paths)
    prepared = prepare_publication_files(workspace, paths)
    profile = workspace.parent
    volume_root = profile.parent.parent
    spool_root = _publication_spool_root(volume_root, profile.name)
    manifest_path = spool_root / f"{publication_id}.json"
    existing = _read_publication_manifest(manifest_path, publication_id, source_paths)
    if existing is not None:
        return existing
    total = sum(int(item["size"]) for item in prepared)
    _reserve_publication(volume_root, profile.name, publication_id, total)
    temporary = spool_root / f".{publication_id}.{os.urandom(8).hex()}.copy"
    final = spool_root / publication_id
    try:
        if final.exists() or temporary.exists():
            raise IncomingFileError("publication spool state was invalid")
        temporary.mkdir(mode=0o700)
        files = tuple(
            _copy_publication_file(workspace, source, temporary, index)
            for index, source in enumerate(source_paths, start=1)
        )
        manifest = PublicationManifest(
            publication_id=publication_id,
            manifest_sha256=_publication_digest(files),
            files=files,
        )
        os.replace(temporary, final)
        _sync_directory(spool_root)
        _write_publication_manifest(manifest_path, manifest, source_paths)
        _mark_publication_frozen(volume_root, publication_id)
        return manifest
    except IncomingFileError:
        _remove_tree(temporary)
        _remove_tree(final)
        _release_publication(volume_root, publication_id)
        raise
    except OSError:
        _remove_tree(temporary)
        _remove_tree(final)
        _release_publication(volume_root, publication_id)
        raise IncomingFileError("publication snapshot could not be committed") from None


def publication_spool_path(
    workspace: Path, publication_id: str, source_version_id: str
) -> Path:
    """Return one journal-owned frozen spool without exposing arbitrary paths."""

    workspace = _workspace(workspace)
    publication_id = _command_id(publication_id)
    source_version_id = _command_id(source_version_id)
    volume_root = workspace.parent.parent.parent
    root = volume_root / ".allies-publications"
    spool_root = root / workspace.parent.name
    if not _publication_directory(root, create=False) or not _publication_directory(
        spool_root, create=False
    ):
        raise IncomingFileError("publication snapshot was unavailable")
    manifest_path = spool_root / f"{publication_id}.json"
    if _publication_file_metadata(manifest_path) is None:
        raise IncomingFileError("publication snapshot was unavailable")
    manifest = _read_publication_manifest(manifest_path, publication_id, None)
    if manifest is None:
        raise IncomingFileError("publication snapshot was unavailable")
    for item in manifest.files:
        if item.source_version_id == source_version_id:
            path = spool_root / publication_id / item.spool_path
            metadata = _publication_file_metadata(path)
            if metadata is None or metadata.st_size != item.size:
                raise IncomingFileError("publication snapshot was unavailable")
            return path
    raise IncomingFileError("publication file was unavailable")


def release_publication_spool(workspace: Path, publication_id: str) -> None:
    """Release a frozen spool only after Cloud has a durable ready receipt."""

    workspace = _workspace(workspace)
    publication_id = _command_id(publication_id)
    profile = workspace.parent
    volume_root = profile.parent.parent
    root = volume_root / ".allies-publications"
    spool_root = root / profile.name
    manifest_path = spool_root / f"{publication_id}.json"
    directory = spool_root / publication_id
    if _publication_directory(root, create=False):
        _publication_directory(spool_root, create=False)
        _publication_file_metadata(manifest_path)
        _publication_directory(directory, create=False)
    if not _mark_publication_releasing(volume_root, profile.name, publication_id):
        return
    _complete_publication_release(spool_root, publication_id)
    _release_publication(volume_root, publication_id)


def recover_publication_manifests(
    workspace: Path, limit: int = MAX_PUBLICATION_MANIFESTS
) -> tuple[PublicationManifest, ...]:
    """Read only the bounded, journal-owned snapshots for one profile."""

    workspace = _workspace(workspace)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise IncomingFileError("publication recovery limit was invalid")
    volume_root = workspace.parent.parent.parent
    root = volume_root / ".allies-publications"
    if not _publication_directory(root, create=False):
        return ()
    spool_root = root / workspace.parent.name
    if not _publication_directory(spool_root, create=False):
        return ()
    manifests: list[PublicationManifest] = []
    for path in sorted(spool_root.glob("*.json")):
        try:
            publication_id = _command_id(path.stem)
        except IncomingFileError:
            continue
        if _publication_file_metadata(path) is None:
            continue
        try:
            manifest = _read_publication_manifest(path, publication_id, None)
        except IncomingFileError:
            continue
        if manifest is not None and _publication_snapshot_exists(spool_root, manifest):
            manifests.append(manifest)
        if len(manifests) == limit:
            break
    return tuple(manifests)


def cleanup_profile_publication_spools(volume_root: Path, profile_key: str) -> None:
    """Remove one root-owned profile spool namespace under its cleanup fence."""

    if not isinstance(profile_key, str) or not profile_key or "/" in profile_key:
        raise IncomingFileError("publication profile identity was invalid")
    root = volume_root / ".allies-publications"
    target = root / profile_key
    root_exists = _publication_directory(root, create=False)
    if not root_exists and not (volume_root / _PUBLICATION_STATE_DIRECTORY).exists():
        return
    if root_exists and _publication_directory(target, create=False):
        shutil.rmtree(target)
        _sync_directory(root)
    with _ledger_lock(volume_root):
        records = _read_ledger(volume_root)
        changed = False
        for publication_id, record in list(records.items()):
            if record["profile"] == profile_key:
                del records[publication_id]
                changed = True
        if changed:
            _write_ledger(volume_root, records)


def reconcile_publication_spools(volume_root: Path, limit: int = 100) -> int:
    """Charge committed local snapshots that survived a ledger write failure."""

    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise IncomingFileError("publication reconciliation limit was invalid")
    root = volume_root / ".allies-publications"
    root_exists = _publication_directory(root, create=False)
    if not root_exists and not (volume_root / _PUBLICATION_STATE_DIRECTORY).exists():
        return 0
    _complete_releasing_publications(volume_root, root, limit)
    if not root_exists:
        return 0
    discovered: list[tuple[str, Path, str]] = []
    try:
        profiles = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError:
        raise IncomingFileError("publication spool was unavailable") from None
    for profile in profiles:
        if len(discovered) >= limit:
            break
        if profile.is_symlink():
            raise IncomingFileError("publication spool was unsafe")
        if not profile.is_dir():
            continue
        _publication_directory(profile, create=False)
        try:
            journals = sorted(profile.glob("*.json"), key=lambda item: item.name)
        except OSError:
            continue
        for journal in journals:
            if len(discovered) >= limit:
                break
            try:
                publication_id = _command_id(journal.stem)
            except IncomingFileError:
                continue
            if _publication_file_metadata(journal) is None:
                continue
            try:
                manifest = _read_publication_manifest(journal, publication_id, None)
            except IncomingFileError:
                continue
            if manifest is not None and _publication_snapshot_exists(profile, manifest):
                discovered.append((profile.name, journal, publication_id))
    with _ledger_lock(volume_root):
        records = _read_ledger(volume_root)
        changed = False
        for profile_key, journal, publication_id in discovered:
            spool_root = root / profile_key
            if not _publication_directory(spool_root, create=False):
                continue
            if _publication_file_metadata(journal) is None:
                continue
            manifest = _read_publication_manifest(journal, publication_id, None)
            if manifest is None or not _publication_snapshot_exists(
                spool_root, manifest
            ):
                continue
            size = sum(item.size for item in manifest.files)
            current = records.get(manifest.publication_id)
            if current is None:
                records[manifest.publication_id] = {
                    "profile": profile_key,
                    "size": size,
                    "state": "frozen",
                    "updated_at": int(time.time()),
                }
                changed = True
            elif current["state"] == "releasing":
                continue
            elif (
                current["profile"] != profile_key
                or current["size"] != size
                or current["state"] != "frozen"
            ):
                current.update(
                    profile=profile_key,
                    size=size,
                    state="frozen",
                    updated_at=int(time.time()),
                )
                changed = True
        if changed:
            _write_ledger(volume_root, records)
    return len(discovered)


def _complete_releasing_publications(volume_root: Path, root: Path, limit: int) -> None:
    with _ledger_lock(volume_root):
        records = _read_ledger(volume_root)
        releasing = [
            (publication_id, str(record["profile"]))
            for publication_id, record in records.items()
            if record["state"] == "releasing"
        ][:limit]
    completed: list[tuple[str, str]] = []
    for publication_id, profile_key in releasing:
        if profile_key in {"", ".", ".."} or "/" in profile_key or "\\" in profile_key:
            raise IncomingFileError("publication reservation journal was invalid")
        spool_root = root / profile_key
        if spool_root.parent != root:
            raise IncomingFileError("publication reservation journal was invalid")
        _publication_directory(spool_root, create=False)
        _complete_publication_release(spool_root, publication_id)
        completed.append((publication_id, profile_key))
    if not completed:
        return
    with _ledger_lock(volume_root):
        records = _read_ledger(volume_root)
        changed = False
        for publication_id, profile_key in completed:
            record = records.get(publication_id)
            if (
                record is not None
                and record["state"] == "releasing"
                and record["profile"] == profile_key
            ):
                del records[publication_id]
                changed = True
        if changed:
            _write_ledger(volume_root, records)


def _complete_publication_release(spool_root: Path, publication_id: str) -> None:
    _publication_directory(spool_root, create=False)
    directory = spool_root / publication_id
    manifest_path = spool_root / f"{publication_id}.json"
    if _publication_directory(directory, create=False):
        shutil.rmtree(directory)
    if _publication_file_metadata(manifest_path) is not None:
        manifest_path.unlink()
    if _publication_directory(spool_root, create=False):
        _sync_directory(spool_root)


def cleanup_stale_publication_copies(
    volume_root: Path,
    *,
    now: float | None = None,
    limit: int = MAX_PARTIAL_PUBLICATION_CLEANUP,
) -> int:
    """Delete only expired incomplete snapshots and their reservation charge."""

    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise IncomingFileError("publication cleanup limit was invalid")
    observed = time.time() if now is None else now
    if not isinstance(observed, (int, float)) or isinstance(observed, bool):
        raise IncomingFileError("publication cleanup time was invalid")
    root = volume_root / ".allies-publications"
    root_exists = _publication_directory(root, create=False)
    if not root_exists and not (volume_root / _PUBLICATION_STATE_DIRECTORY).exists():
        return 0
    removed = 0
    with _ledger_lock(volume_root):
        records = _read_ledger(volume_root)
        for publication_id, record in sorted(records.items()):
            if removed >= limit:
                break
            if (
                record["state"] != "copying"
                or observed - float(record["updated_at"])
                < PARTIAL_PUBLICATION_STALE_SECONDS
            ):
                continue
            profile_root = root / str(record["profile"])
            if root_exists:
                _publication_directory(profile_root, create=False)
            manifest_path = profile_root / f"{publication_id}.json"
            if _publication_file_metadata(manifest_path) is not None:
                continue
            final = profile_root / publication_id
            candidates = [final, *profile_root.glob(f".{publication_id}.*.copy")]
            for candidate in candidates:
                if _publication_directory(candidate, create=False):
                    shutil.rmtree(candidate)
            if any(candidate.exists() for candidate in candidates):
                continue
            del records[publication_id]
            removed += 1
        if removed:
            _write_ledger(volume_root, records)
    return removed


def parse_incoming_files(value: object) -> tuple[IncomingFile, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_FILES:
        raise IncomingFileError("incoming file manifest was invalid")
    files: list[IncomingFile] = []
    identifiers: set[str] = set()
    total = 0
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {
            "file_id",
            "name",
            "media_type",
            "size",
            "sha256",
        }:
            raise IncomingFileError("incoming file manifest was invalid")
        try:
            file_id = str(UUID(str(item["file_id"])))
        except (TypeError, ValueError):
            raise IncomingFileError("incoming file manifest was invalid") from None
        name = item["name"]
        media_type = item["media_type"]
        size = item["size"]
        sha256 = item["sha256"]
        if (
            not _safe_name(name)
            or not _safe_media_type(media_type)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or not 1 <= size <= MAX_FILE_BYTES
            or not isinstance(sha256, str)
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
            or file_id in identifiers
        ):
            raise IncomingFileError("incoming file manifest was invalid")
        identifiers.add(file_id)
        total += size
        if total > MAX_TOTAL_BYTES:
            raise IncomingFileError("incoming file manifest was invalid")
        files.append(
            IncomingFile(
                file_id=file_id,
                name=name,
                media_type=media_type,
                size=size,
                sha256=sha256,
            )
        )
    return tuple(files)


def validate_hermes_file_context(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "kind",
        "files",
    }:
        raise IncomingFileError("incoming file context was invalid")
    if (
        value.get("schema_version") != "v1"
        or value.get("kind") != "allies_incoming_files"
    ):
        raise IncomingFileError("incoming file context was invalid")
    rows = value.get("files")
    if not isinstance(rows, list):
        raise IncomingFileError("incoming file context was invalid")
    manifest = []
    paths = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "file_id",
            "name",
            "media_type",
            "size",
            "sha256",
            "path",
        }:
            raise IncomingFileError("incoming file context was invalid")
        manifest.append({key: row.get(key) for key in row if key != "path"})
        paths.append(row.get("path"))
    descriptors = parse_incoming_files(manifest)
    if len(paths) != len(descriptors) or not all(
        isinstance(path, str) and _safe_relative_path(path) for path in paths
    ):
        raise IncomingFileError("incoming file context was invalid")
    return {
        "schema_version": "v1",
        "kind": "allies_incoming_files",
        "files": [
            {**descriptor.manifest_value(), "path": path}
            for descriptor, path in zip(descriptors, paths, strict=True)
        ],
    }


async def stage_incoming_files(
    workspace: Path,
    command_id: str,
    value: object,
    fetch: FileFetcher,
    *,
    clock: Callable[[], float] = time.monotonic,
    cancelled: Callable[[], bool] | None = None,
) -> StagedManifest:
    """Stage the complete manifest before the model can see any path.

    A receipt identifies exact replay. If an old working copy has changed, a
    replay writes a new isolated directory. It never replaces the old copy.
    """

    _check_cancelled(cancelled)
    descriptors = parse_incoming_files(value)
    command_id = _command_id(command_id)
    manifest_sha256 = _manifest_sha256(descriptors)
    workspace = _workspace(workspace)
    receipt_path = workspace.parent / ".allies-incoming-receipts" / f"{command_id}.json"
    previous = _read_receipt(receipt_path)
    if previous is not None:
        staged = _receipt_manifest(previous, command_id, manifest_sha256, descriptors)
        if staged is not None and _staged_files_match(workspace, staged):
            _check_cancelled(cancelled)
            return StagedManifest(command_id, manifest_sha256, staged)

    started = clock()
    staging_root = workspace.parent / ".allies-incoming-staging"
    _directory(staging_root)
    temporary = staging_root / f"{command_id}.{os.urandom(8).hex()}"
    final_root = _next_target(
        workspace / "attachments", command_id, previous is not None
    )
    files: list[StagedFile] = []
    committed = False
    try:
        _check_cancelled(cancelled)
        temporary.mkdir(mode=0o700)
        for descriptor in descriptors:
            _check_cancelled(cancelled)
            _check_deadline(started, clock, MAX_SET_SECONDS)
            target_name = descriptor.file_id
            target = temporary / target_name
            await _download_file(
                descriptor, target, fetch, clock, started, cancelled=cancelled
            )
            _check_cancelled(cancelled)
            files.append(
                StagedFile(
                    descriptor=descriptor,
                    path=(
                        Path("attachments") / final_root.name / target_name
                    ).as_posix(),
                )
            )
        _check_cancelled(cancelled)
        _directory(final_root.parent)
        if os.name != "nt" and os.geteuid() == 0:
            for item in files:
                os.chown(
                    temporary / item.descriptor.file_id,
                    10000,
                    10000,
                    follow_symlinks=False,
                )
            os.chown(temporary, 10000, 10000, follow_symlinks=False)
            os.chown(final_root.parent, 10000, 10000, follow_symlinks=False)
        _check_cancelled(cancelled)
        os.replace(temporary, final_root)
        committed = True
        _sync_directory(final_root.parent)
        staged = tuple(files)
        _check_cancelled(cancelled)
        _write_receipt(
            receipt_path,
            {
                "schema": _RECEIPT_SCHEMA,
                "command_id": command_id,
                "manifest_sha256": manifest_sha256,
                "files": [item.hermes_value() for item in staged],
            },
        )
        return StagedManifest(command_id, manifest_sha256, staged)
    except IncomingFileError:
        _remove_tree(temporary)
        if committed:
            _remove_tree(final_root)
        raise
    except (OSError, UnicodeError):
        _remove_tree(temporary)
        if committed:
            _remove_tree(final_root)
        raise IncomingFileError("incoming file staging failed") from None


async def _download_file(
    descriptor: IncomingFile,
    target: Path,
    fetch: FileFetcher,
    clock: Callable[[], float],
    set_started: float,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    started = clock()
    received = 0
    digest = hashlib.sha256()
    source = fetch(descriptor)
    if not hasattr(source, "__aiter__"):
        raise IncomingFileError("incoming file transport was invalid")
    try:
        with target.open("xb") as handle:
            async for chunk in source:
                _check_cancelled(cancelled)
                _check_deadline(started, clock, MAX_FILE_SECONDS)
                _check_deadline(set_started, clock, MAX_SET_SECONDS)
                if (
                    not isinstance(chunk, bytes)
                    or not chunk
                    or len(chunk) > MAX_CHUNK_BYTES
                ):
                    raise IncomingFileError("incoming file transport was invalid")
                received += len(chunk)
                if received > descriptor.size:
                    raise IncomingFileError("incoming file size did not match manifest")
                digest.update(chunk)
                _check_cancelled(cancelled)
                handle.write(chunk)
            _check_cancelled(cancelled)
            handle.flush()
            os.fsync(handle.fileno())
    except IncomingFileError:
        raise
    except (OSError, TypeError):
        raise IncomingFileError("incoming file transport failed") from None
    if received != descriptor.size or digest.hexdigest() != descriptor.sha256:
        raise IncomingFileError("incoming file digest did not match manifest")


def _receipt_manifest(
    value: object,
    command_id: str,
    manifest_sha256: str,
    descriptors: Sequence[IncomingFile],
) -> tuple[StagedFile, ...] | None:
    if not isinstance(value, Mapping) or value.get("schema") != _RECEIPT_SCHEMA:
        return None
    if (
        value.get("command_id") != command_id
        or value.get("manifest_sha256") != manifest_sha256
    ):
        raise IncomingFileError("incoming file replay conflicted with its receipt")
    rows = value.get("files")
    if not isinstance(rows, list) or len(rows) != len(descriptors):
        return None
    staged: list[StagedFile] = []
    for descriptor, row in zip(descriptors, rows, strict=True):
        if not isinstance(row, Mapping) or set(row) != {
            "file_id",
            "name",
            "media_type",
            "size",
            "sha256",
            "path",
        }:
            return None
        if any(
            row.get(key) != value for key, value in descriptor.manifest_value().items()
        ):
            raise IncomingFileError("incoming file replay conflicted with its receipt")
        path = row.get("path")
        if not isinstance(path, str) or not _safe_relative_path(path):
            return None
        staged.append(StagedFile(descriptor=descriptor, path=path))
    return tuple(staged)


def _staged_files_match(workspace: Path, files: Sequence[StagedFile]) -> bool:
    for staged in files:
        path = workspace / staged.path
        try:
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size != staged.descriptor.size
            ):
                return False
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(MAX_CHUNK_BYTES), b""):
                    digest.update(chunk)
            if digest.hexdigest() != staged.descriptor.sha256:
                return False
        except OSError:
            return False
    return True


def _manifest_sha256(files: Sequence[IncomingFile]) -> str:
    payload = [item.manifest_value() for item in files]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _read_receipt(path: Path) -> object | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise IncomingFileError("incoming file receipt was invalid")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise IncomingFileError("incoming file receipt was invalid") from None


def _write_receipt(path: Path, value: Mapping[str, object]) -> None:
    _directory(path.parent)
    temporary = path.with_name(f".{path.name}.{os.urandom(8).hex()}.tmp")
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise IncomingFileError(
            "incoming file receipt could not be committed"
        ) from None


def _workspace(path: Path) -> Path:
    if path.is_symlink() or not path.is_dir() or path.name != "workspace":
        raise IncomingFileError("profile workspace was unavailable")
    return path


def _directory(path: Path) -> None:
    if path.is_symlink():
        raise IncomingFileError("incoming file path was unsafe")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise IncomingFileError("incoming file path was unsafe")


def _publication_directory(path: Path, *, create: bool) -> bool:
    if os.name == "nt":
        if not path.exists():
            if not create:
                return False
            _directory(path)
            return True
        if path.is_symlink() or not path.is_dir():
            raise IncomingFileError("publication spool was unsafe")
        return True
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if not create:
            return False
        try:
            path.mkdir(mode=0o700)
            os.chown(path, 0, 0)
            os.chmod(path, 0o700)
        except OSError:
            raise IncomingFileError("publication spool was unavailable") from None
        return True
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise IncomingFileError("publication spool was unsafe")
    return True


def _publication_file_metadata(path: Path):
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or os.name != "nt"
        and (metadata.st_uid != 0 or metadata.st_gid != 0)
    ):
        raise IncomingFileError("publication spool was unsafe")
    return metadata


def _publication_snapshot_exists(
    spool_root: Path, manifest: PublicationManifest
) -> bool:
    snapshot = spool_root / manifest.publication_id
    if not _publication_directory(snapshot, create=False):
        return False
    for file in manifest.files:
        metadata = _publication_file_metadata(snapshot / file.spool_path)
        if metadata is None or metadata.st_size != file.size:
            return False
    return True


def _publication_spool_root(volume_root: Path, profile_key: str) -> Path:
    _publication_state_root(volume_root)
    root = volume_root / ".allies-publications"
    _publication_directory(root, create=True)
    spool_root = root / profile_key
    _publication_directory(spool_root, create=True)
    return spool_root


def _next_target(root: Path, command_id: str, replay: bool) -> Path:
    _directory(root)
    first = root / command_id
    if not replay and not first.exists():
        return first
    for ordinal in range(1, 1000):
        candidate = root / f"{command_id}-recovery-{ordinal}"
        if not candidate.exists():
            return candidate
    raise IncomingFileError("incoming file recovery namespace was exhausted")


def _safe_name(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > 255:
        return False
    normalized = unicodedata.normalize("NFC", value)
    base_name = value.split(".", 1)[0].upper()
    return (
        normalized == value
        and value not in {".", ".."}
        and "/" not in value
        and "\\" not in value
        and not any(character in '<>:"|?*' for character in value)
        and value.rstrip(". ") == value
        and not any(
            ord(character) < 0x20 or ord(character) == 0x7F for character in value
        )
        and base_name not in _WINDOWS_RESERVED_NAMES
    )


def _safe_media_type(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value.encode("utf-8")) <= 127
        and "/" in value
        and not any(not 0x20 <= ord(character) <= 0x7E for character in value)
    )


def _safe_relative_path(value: str) -> bool:
    path = Path(value)
    return (
        path.as_posix() == value
        and not path.is_absolute()
        and ".." not in path.parts
        and len(path.parts) == 3
        and path.parts[0] == "attachments"
    )


def _command_id(value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        raise IncomingFileError("incoming file command identity was invalid") from None


def _check_deadline(started: float, clock: Callable[[], float], limit: float) -> None:
    if clock() - started > limit:
        raise IncomingFileError("incoming file transfer timed out")


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise IncomingFileError("incoming file staging lease was lost")


def _sync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_tree(path: Path) -> None:
    if path.exists() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)


def _publication_paths(value: Sequence[str]) -> tuple[Path, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise IncomingFileError("publication paths were invalid")
    if not 1 <= len(value) <= MAX_FILES:
        raise IncomingFileError("publication must contain from 1 to 10 files")
    result: list[Path] = []
    for relative in value:
        if not isinstance(relative, str):
            raise IncomingFileError("publication paths were invalid")
        candidate = Path(relative)
        if (
            not relative
            or candidate.is_absolute()
            or not candidate.parts
            or ".." in candidate.parts
            or any(part.startswith(".") for part in candidate.parts)
        ):
            raise IncomingFileError("publication path was unsafe")
        result.append(candidate)
    if len(set(result)) != len(result):
        raise IncomingFileError("publication paths were duplicated")
    return tuple(result)


def _copy_publication_file(
    workspace: Path, relative: Path, destination: Path, ordinal: int
) -> PublicationFile:
    try:
        source, before = _publication_source(workspace, relative)
    except OSError:
        raise IncomingFileError("publication source was unavailable") from None
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_size > MAX_PUBLICATION_FILE_BYTES
    ):
        raise IncomingFileError("publication source was unsafe")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = _open_publication_source(source, flags)
    except OSError:
        raise IncomingFileError("publication source was unavailable") from None
    output_name = f"{ordinal:02d}-{uuid4().hex}.bin"
    output = destination / output_name
    digest = hashlib.sha256()
    copied = 0
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not os.path.samestat(before, opened)
        ):
            raise IncomingFileError("publication source was unsafe")
        with output.open("xb") as handle:
            while True:
                chunk = os.read(descriptor, MAX_CHUNK_BYTES)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > MAX_PUBLICATION_FILE_BYTES:
                    raise IncomingFileError("publication source exceeds 25 MB")
                digest.update(chunk)
                handle.write(chunk)
                if shutil.disk_usage(destination).free < MIN_VOLUME_FREE_BYTES:
                    raise IncomingFileError("local storage capacity is unavailable")
            handle.flush()
            os.fsync(handle.fileno())
        after = source.lstat()
        if not os.path.samestat(before, after) or (
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_size, after.st_mtime_ns):
            raise IncomingFileError("publication source changed during copy")
    except IncomingFileError:
        output.unlink(missing_ok=True)
        raise
    except OSError:
        output.unlink(missing_ok=True)
        raise IncomingFileError("publication snapshot copy failed") from None
    finally:
        os.close(descriptor)
    return PublicationFile(
        source_version_id=str(uuid4()),
        name=relative.name,
        size=copied,
        sha256=digest.hexdigest(),
        spool_path=output_name,
    )


def _open_publication_source(source: Path, flags: int) -> int:
    if os.name == "nt":
        return os.open(source, flags)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent = os.open(source.anchor, directory_flags)
    try:
        for part in source.parts[1:-1]:
            child = os.open(part, directory_flags, dir_fd=parent)
            os.close(parent)
            parent = child
        return os.open(source.name, flags | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)


def _publication_source(workspace: Path, relative: Path) -> tuple[Path, os.stat_result]:
    current = workspace
    for index, part in enumerate(relative.parts):
        current = current / part
        metadata = current.lstat()
        if current.is_symlink() or (
            index < len(relative.parts) - 1 and not stat.S_ISDIR(metadata.st_mode)
        ):
            raise IncomingFileError("publication source was unsafe")
    return current, metadata


def _publication_digest(files: Sequence[PublicationFile]) -> str:
    return hashlib.sha256(
        json.dumps(
            [item.frozen_value() for item in files],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _read_publication_manifest(
    path: Path,
    publication_id: str,
    expected_paths: Sequence[Path] | None,
) -> PublicationManifest | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise IncomingFileError("publication journal was invalid")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise IncomingFileError("publication journal was invalid") from None
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "publication_id",
        "source_paths",
        "manifest_sha256",
        "files",
    }:
        raise IncomingFileError("publication journal was invalid")
    source_paths = value.get("source_paths")
    if (
        value.get("schema") != _PUBLICATION_SCHEMA
        or value.get("publication_id") != publication_id
    ):
        raise IncomingFileError("publication journal was invalid")
    if not isinstance(source_paths, list) or any(
        not isinstance(item, str) for item in source_paths
    ):
        raise IncomingFileError("publication journal was invalid")
    if expected_paths is not None and source_paths != [
        item.as_posix() for item in expected_paths
    ]:
        raise IncomingFileError("publication paths changed after freeze")
    rows = value.get("files")
    digest = value.get("manifest_sha256")
    if (
        not isinstance(rows, list)
        or not isinstance(digest, str)
        or len(rows) > MAX_FILES
    ):
        raise IncomingFileError("publication journal was invalid")
    files: list[PublicationFile] = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "source_version_id",
            "name",
            "size",
            "sha256",
            "spool_path",
        }:
            raise IncomingFileError("publication journal was invalid")
        try:
            source_version_id = str(UUID(str(row["source_version_id"])))
        except (TypeError, ValueError):
            raise IncomingFileError("publication journal was invalid") from None
        name = row["name"]
        size = row["size"]
        sha256 = row["sha256"]
        spool_path = row["spool_path"]
        if (
            not _safe_name(name)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not 1 <= size <= MAX_PUBLICATION_FILE_BYTES
            or not isinstance(sha256, str)
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
            or not isinstance(spool_path, str)
            or Path(spool_path).name != spool_path
        ):
            raise IncomingFileError("publication journal was invalid")
        files.append(PublicationFile(source_version_id, name, size, sha256, spool_path))
    manifest = PublicationManifest(publication_id, digest, tuple(files))
    if _publication_digest(manifest.files) != digest:
        raise IncomingFileError("publication journal was invalid")
    return manifest


def _write_publication_manifest(
    path: Path, manifest: PublicationManifest, source_paths: Sequence[Path]
) -> None:
    value = {
        "schema": _PUBLICATION_SCHEMA,
        "publication_id": manifest.publication_id,
        "source_paths": [item.as_posix() for item in source_paths],
        "manifest_sha256": manifest.manifest_sha256,
        "files": [
            {**item.frozen_value(), "spool_path": item.spool_path}
            for item in manifest.files
        ],
    }
    _write_receipt(path, value)


def _validate_publication_volume_root(volume_root: Path) -> None:
    if os.name == "nt":
        return
    try:
        metadata = volume_root.lstat()
    except OSError:
        raise IncomingFileError(
            "publication reservation journal was unavailable"
        ) from None
    if (
        volume_root.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o1777
    ):
        raise IncomingFileError("publication reservation journal was unavailable")


def _publication_state_root(volume_root: Path) -> Path:
    root = volume_root / _PUBLICATION_STATE_DIRECTORY
    if os.name == "nt":
        _directory(root)
        return root
    try:
        _validate_publication_volume_root(volume_root)
        try:
            metadata = root.lstat()
        except FileNotFoundError:
            root.mkdir(mode=0o700)
            os.chown(root, 0, 0)
            os.chmod(root, 0o700)
            metadata = root.lstat()
        if (
            root.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise IncomingFileError("publication reservation journal was unavailable")
    except OSError:
        raise IncomingFileError(
            "publication reservation journal was unavailable"
        ) from None
    return root


def _ledger_path(volume_root: Path) -> Path:
    return _publication_state_root(volume_root) / "ledger.json"


def _ledger_lock_path(volume_root: Path) -> Path:
    return _publication_state_root(volume_root) / "ledger.lock"


@contextmanager
def _ledger_lock(volume_root: Path):
    """Serialize the short shared-volume ledger updates."""

    key = str(volume_root)
    with _publication_locks_guard:
        local_lock = _publication_locks.setdefault(key, threading.Lock())
    with local_lock:
        path = _ledger_lock_path(volume_root)
        if path.is_symlink():
            raise IncomingFileError("publication reservation journal was invalid")
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError:
            raise IncomingFileError(
                "publication reservation journal was unavailable"
            ) from None
        try:
            if fcntl is not None:
                # ponytail: global volume lock; split only if measured contention requires it.
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _read_ledger(volume_root: Path) -> dict[str, dict[str, object]]:
    path = _ledger_path(volume_root)
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise IncomingFileError("publication reservation journal was invalid")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise IncomingFileError("publication reservation journal was invalid") from None
    if not isinstance(value, Mapping) or value.get("schema") != _PUBLICATION_SCHEMA:
        raise IncomingFileError("publication reservation journal was invalid")
    records = value.get("records")
    if not isinstance(records, Mapping):
        raise IncomingFileError("publication reservation journal was invalid")
    result: dict[str, dict[str, object]] = {}
    for key, record in records.items():
        if not isinstance(key, str) or not isinstance(record, Mapping):
            raise IncomingFileError("publication reservation journal was invalid")
        try:
            if str(UUID(key)) != key:
                raise ValueError
        except ValueError:
            raise IncomingFileError(
                "publication reservation journal was invalid"
            ) from None
        profile = record.get("profile")
        size = record.get("size")
        state = record.get("state")
        updated_at = record.get("updated_at", 0)
        if (
            not isinstance(profile, str)
            or profile in {"", ".", ".."}
            or any(character in profile for character in "/\\:\x00")
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or state not in {"copying", "frozen", "releasing"}
            or not isinstance(updated_at, int)
            or isinstance(updated_at, bool)
            or updated_at < 0
        ):
            raise IncomingFileError("publication reservation journal was invalid")
        result[key] = {
            "profile": profile,
            "size": size,
            "state": state,
            "updated_at": updated_at,
        }
    return result


def _write_ledger(
    volume_root: Path, records: Mapping[str, Mapping[str, object]]
) -> None:
    path = _ledger_path(volume_root)
    _write_receipt(path, {"schema": _PUBLICATION_SCHEMA, "records": dict(records)})


def _reserve_publication(
    volume_root: Path, profile_key: str, publication_id: str, size: int
) -> None:
    _directory(volume_root)
    reconcile_publication_spools(volume_root)
    with _ledger_lock(volume_root):
        records = _read_ledger(volume_root)
        current = records.get(publication_id)
        if current is not None:
            if current.get("profile") == profile_key and current.get("size") == size:
                return
            raise IncomingFileError("publication reservation conflicted")
        profile_records = [
            record for record in records.values() if record["profile"] == profile_key
        ]
        if len(profile_records) >= MAX_PUBLICATION_MANIFESTS:
            raise IncomingFileError("local storage capacity is unavailable")
        if (
            sum(record["state"] == "copying" for record in profile_records)
            >= MAX_PUBLICATION_INCOMPLETE
        ):
            raise IncomingFileError("local storage capacity is unavailable")
        if (
            sum(int(record["size"]) for record in profile_records) + size
            > MAX_PROFILE_PUBLICATION_BYTES
        ):
            raise IncomingFileError("local storage capacity is unavailable")
        if (
            sum(int(record["size"]) for record in records.values()) + size
            > MAX_VOLUME_PUBLICATION_BYTES
        ):
            raise IncomingFileError("local storage capacity is unavailable")
        if shutil.disk_usage(volume_root).free - size < MIN_VOLUME_FREE_BYTES:
            raise IncomingFileError("local storage capacity is unavailable")
        records[publication_id] = {
            "profile": profile_key,
            "size": size,
            "state": "copying",
            "updated_at": int(time.time()),
        }
        _write_ledger(volume_root, records)


def _mark_publication_frozen(volume_root: Path, publication_id: str) -> None:
    with _ledger_lock(volume_root):
        records = _read_ledger(volume_root)
        record = records.get(publication_id)
        if record is None:
            raise IncomingFileError("publication reservation was unavailable")
        record["state"] = "frozen"
        record["updated_at"] = int(time.time())
        _write_ledger(volume_root, records)


def _mark_publication_releasing(
    volume_root: Path, profile_key: str, publication_id: str
) -> bool:
    with _ledger_lock(volume_root):
        records = _read_ledger(volume_root)
        record = records.get(publication_id)
        if record is None:
            return False
        if record["profile"] != profile_key or record["state"] not in {
            "frozen",
            "releasing",
        }:
            raise IncomingFileError("publication reservation was unavailable")
        if record["state"] == "releasing":
            return True
        record["state"] = "releasing"
        record["updated_at"] = int(time.time())
        _write_ledger(volume_root, records)
    return True


def _release_publication(volume_root: Path, publication_id: str) -> None:
    with _ledger_lock(volume_root):
        records = _read_ledger(volume_root)
        if publication_id not in records:
            return
        del records[publication_id]
        _write_ledger(volume_root, records)


__all__ = [
    "MAX_CHUNK_BYTES",
    "IncomingFile",
    "PublicationFile",
    "PublicationManifest",
    "StagedFile",
    "StagedManifest",
    "cleanup_profile_publication_spools",
    "cleanup_stale_publication_copies",
    "freeze_publication",
    "parse_incoming_files",
    "prepare_publication_files",
    "publication_spool_path",
    "reconcile_publication_spools",
    "recover_publication_manifests",
    "release_publication_spool",
    "stage_incoming_files",
    "validate_hermes_file_context",
]
