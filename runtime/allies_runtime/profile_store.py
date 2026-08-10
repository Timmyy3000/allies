"""Dependency-free, secret-safe materialization of one Hermes profile.

The profile store owns only the files below ``<volume>/profiles/<key>``.  The
Foundry lifecycle service remains the authority for the profile's lifecycle;
the epoch and the small tombstone written here are the runtime-side fence that
prevents a stale reconciler from resurrecting deleted state.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import shutil
import stat
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

MANIFEST_NAME = ".allies-profile.json"
MANIFEST_SCHEMA = "allies.profile"
MANIFEST_VERSION = 1
PROFILE_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
RESERVED_PROFILE_KEYS = frozenset({"hermes", "default", "test", "tmp", "root", "sudo"})
HERMES_PROFILE_DIRECTORIES = (
    "memories",
    "sessions",
    "skills",
    "skins",
    "logs",
    "plans",
    "workspace",
    "cron",
    "home",
)

MAX_PROFILE_ID_BYTES = 128
MAX_PROFILE_TEXT_BYTES = 131_072
MAX_INSTRUCTION_BYTES = 65_536
MAX_FIELD_BYTES = 4_096
MAX_OPERATION_ID_BYTES = 256
MAX_CREDENTIALS = 32
MAX_CLEANUP_ENTRIES = 8_192
DEFAULT_LOCK_TIMEOUT_SECONDS = 5.0
DEFAULT_STALE_LOCK_SECONDS = 60.0
DEFAULT_CLEANUP_TIMEOUT_SECONDS = 30.0
_RECEIPT_ID_PATTERN = re.compile(r"^(?:pr|cr)-[0-9a-f]{32}$")
_SAFE_REPAIR_CODES = frozenset(
    {
        "cleanup_bound_exceeded",
        "cleanup_expired",
        "invalid_cleanup_tombstone",
        "invalid_manifest_metadata",
        "incomplete_layout",
        "incomplete_manifest",
        "incomplete_profile",
        "lifecycle_epoch_mismatch",
        "lock_timeout",
        "manifest_update_failed",
        "materialization_failed",
        "profile_appeared_during_publish",
        "profile_cleanup_failed",
        "profile_deprovisioned",
        "profile_is_not_directory",
        "profile_publish_failed",
        "profile_store_unavailable",
        "secret_file_permissions",
        "seed_fingerprint_conflict",
        "stale_cleanup_epoch",
        "stale_lifecycle_epoch",
        "symlinked_profile",
        "symlinked_temporary_state",
        "temporary_state_unreadable",
        "unknown_temporary_state",
        "unsupported_manifest",
    }
)


class ProfileStoreError(RuntimeError):
    """Base error with deliberately non-sensitive messages."""


class ProfileInputError(ValueError, ProfileStoreError):
    """Raised when a profile request cannot safely be represented."""


class ProfileProvisionStatus(StrEnum):
    CREATED = "CREATED"
    EXISTING = "EXISTING"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    CONFLICT = "CONFLICT"
    FENCED = "FENCED"


class ProfileCleanupStatus(StrEnum):
    DEPROVISIONED = "DEPROVISIONED"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    FENCED = "FENCED"


def derive_profile_key(foundry_profile_id: str | uuid.UUID) -> str:
    """Derive the immutable Hermes key used for a Foundry profile UUID."""

    try:
        parsed = (
            foundry_profile_id
            if isinstance(foundry_profile_id, uuid.UUID)
            else uuid.UUID(str(foundry_profile_id))
        )
    except (AttributeError, TypeError, ValueError):
        raise ProfileInputError("Foundry profile ID must be a UUID") from None
    return f"ally-v1-{parsed.hex}"


def validate_profile_key(profile_key: str) -> str:
    """Validate a profile key before it is used as a filesystem component."""

    if not isinstance(profile_key, str) or not PROFILE_KEY_PATTERN.fullmatch(
        profile_key
    ):
        raise ProfileInputError("Hermes profile key is invalid")
    if profile_key in RESERVED_PROFILE_KEYS:
        raise ProfileInputError("Hermes profile key is reserved")
    return profile_key


def _bounded_text(
    value: Any, *, field_name: str, maximum: int, empty: bool = False
) -> str:
    if not isinstance(value, str) or (not empty and not value):
        raise ProfileInputError(f"{field_name} is invalid")
    if len(value.encode("utf-8")) > maximum or "\x00" in value:
        raise ProfileInputError(f"{field_name} is too large")
    return value


def _safe_operation_id(value: Any) -> str:
    if isinstance(value, uuid.UUID):
        value = str(value)
    value = _bounded_text(
        value, field_name="operation ID", maximum=MAX_OPERATION_ID_BYTES
    )
    if any(character in value for character in "/\\\r\n"):
        raise ProfileInputError("operation ID is invalid")
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _string_generation(value: str | int) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ProfileInputError("materialized generation is invalid")
    return _bounded_text(str(value), field_name="materialized generation", maximum=128)


def _validate_credentials(value: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or len(value) > MAX_CREDENTIALS:
        raise ProfileInputError("credential references are invalid")
    result: dict[str, str] = {}
    for name, reference in value.items():
        if not isinstance(name, str):
            raise ProfileInputError("credential environment name is invalid")
        if re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
            name = name.upper().replace("-", "_")
        elif not ENV_NAME_PATTERN.fullmatch(name):
            raise ProfileInputError("credential environment name is invalid")
        if name == "API_SERVER_KEY":
            raise ProfileInputError("credential environment name is reserved")
        reference = _bounded_text(
            reference, field_name="credential reference", maximum=MAX_FIELD_BYTES
        )
        if any(
            character in reference for character in "\x00\r\n"
        ) or reference.lower().startswith(
            ("bearer ", "token=", "key=", "sk-", "api_key=")
        ):
            raise ProfileInputError("credential reference is invalid")
        if name in result:
            raise ProfileInputError("credential environment names collide")
        result[name] = reference
    return MappingProxyType(dict(sorted(result.items())))


def _validate_identity(value: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or len(value) > 16:
        raise ProfileInputError("profile identity is invalid")
    result: dict[str, str] = {}
    for name, item in value.items():
        name = _bounded_text(name, field_name="identity field", maximum=64)
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
            raise ProfileInputError("identity field is invalid")
        result[name] = _bounded_text(
            item, field_name="identity value", maximum=MAX_FIELD_BYTES
        )
    return MappingProxyType(dict(sorted(result.items())))


@dataclass(frozen=True, slots=True)
class ProfileSeed:
    """The non-secret desired state used to materialize a Hermes profile.

    ``credential_refs`` contains opaque references and never resolved values.
    ``provider``/``model`` are aliases for the manifest's
    ``model.provider``/``model.default`` shape; the explicit alias fields are
    accepted to keep the runtime boundary easy to call from reconciliation
    adapters.
    """

    foundry_profile_id: str | uuid.UUID
    ally_name: str = ""
    personality: str = ""
    provider: str = ""
    model: str = ""
    first_chat_instruction: str = ""
    credential_refs: Mapping[str, str] = field(default_factory=dict)
    seed_version: int = 1
    first_chat_version: int = 1
    base_url: str | None = None
    hermes_profile_key: str | None = None
    lifecycle_epoch: int = 0
    materialized_generation: str | int = "initial"
    operation_id: str = "op-default"
    ally_id: str | None = None
    identity: Mapping[str, str] = field(default_factory=dict)
    model_provider: str | None = None
    model_default: str | None = None
    system_instruction: str | None = None
    version: int | None = None
    first_chat_instruction_version: int | None = None

    def __post_init__(self) -> None:
        try:
            parsed_id = (
                self.foundry_profile_id
                if isinstance(self.foundry_profile_id, uuid.UUID)
                else uuid.UUID(str(self.foundry_profile_id))
            )
        except (AttributeError, TypeError, ValueError):
            raise ProfileInputError("Foundry profile ID must be a UUID") from None
        canonical_id = str(parsed_id)
        object.__setattr__(self, "foundry_profile_id", canonical_id)

        expected_key = derive_profile_key(parsed_id)
        if self.hermes_profile_key is not None:
            supplied_key = validate_profile_key(self.hermes_profile_key)
            if supplied_key != expected_key:
                raise ProfileInputError("Hermes profile key does not match profile ID")
        object.__setattr__(self, "hermes_profile_key", expected_key)

        object.__setattr__(
            self,
            "ally_name",
            _bounded_text(
                self.ally_name, field_name="Ally name", maximum=MAX_FIELD_BYTES
            ),
        )
        object.__setattr__(
            self,
            "personality",
            _bounded_text(
                self.personality,
                field_name="personality",
                maximum=MAX_PROFILE_TEXT_BYTES,
            ),
        )

        provider = (
            self.model_provider if self.model_provider is not None else self.provider
        )
        model = self.model_default if self.model_default is not None else self.model
        if (
            self.provider
            and self.model_provider
            and self.provider != self.model_provider
        ):
            raise ProfileInputError("model provider aliases conflict")
        if self.model and self.model_default and self.model != self.model_default:
            raise ProfileInputError("model aliases conflict")
        object.__setattr__(
            self,
            "provider",
            _bounded_text(provider, field_name="model provider", maximum=256),
        )
        object.__setattr__(
            self, "model", _bounded_text(model, field_name="model", maximum=256)
        )

        instruction = (
            self.system_instruction
            if self.system_instruction is not None
            else self.first_chat_instruction
        )
        if (
            self.first_chat_instruction
            and self.system_instruction is not None
            and self.first_chat_instruction != self.system_instruction
        ):
            raise ProfileInputError("system instruction aliases conflict")
        object.__setattr__(
            self,
            "first_chat_instruction",
            _bounded_text(
                instruction,
                field_name="first-chat instruction",
                maximum=MAX_INSTRUCTION_BYTES,
            ),
        )

        if self.version is not None:
            if self.seed_version != 1 and self.seed_version != self.version:
                raise ProfileInputError("seed version aliases conflict")
            object.__setattr__(self, "seed_version", self.version)
        if self.first_chat_instruction_version is not None:
            if (
                self.first_chat_version != 1
                and self.first_chat_version != self.first_chat_instruction_version
            ):
                raise ProfileInputError("first-chat version aliases conflict")
            object.__setattr__(
                self, "first_chat_version", self.first_chat_instruction_version
            )
        if (
            isinstance(self.seed_version, bool)
            or not isinstance(self.seed_version, int)
            or not 0 < self.seed_version <= 32
        ):
            raise ProfileInputError("seed version is invalid")
        if (
            isinstance(self.first_chat_version, bool)
            or not isinstance(self.first_chat_version, int)
            or not 0 < self.first_chat_version <= 32
        ):
            raise ProfileInputError("first-chat version is invalid")
        if (
            isinstance(self.lifecycle_epoch, bool)
            or not isinstance(self.lifecycle_epoch, int)
            or self.lifecycle_epoch < 0
        ):
            raise ProfileInputError("lifecycle epoch is invalid")
        object.__setattr__(
            self,
            "materialized_generation",
            _string_generation(self.materialized_generation),
        )
        object.__setattr__(self, "operation_id", _safe_operation_id(self.operation_id))
        if self.base_url is not None:
            base_url = _bounded_text(
                self.base_url, field_name="model base URL", maximum=MAX_FIELD_BYTES
            )
            if any(character in base_url for character in "\x00\r\n"):
                raise ProfileInputError("model base URL is invalid")
            object.__setattr__(self, "base_url", base_url)
        if self.ally_id is not None:
            object.__setattr__(
                self,
                "ally_id",
                _bounded_text(
                    self.ally_id, field_name="Ally ID", maximum=MAX_FIELD_BYTES
                ),
            )
        object.__setattr__(
            self, "credential_refs", _validate_credentials(self.credential_refs)
        )
        identity = dict(_validate_identity(self.identity))
        if self.ally_id is not None:
            identity.setdefault("ally_id", self.ally_id)
        identity.setdefault("ally_name", self.ally_name)
        object.__setattr__(self, "identity", _validate_identity(identity))
        object.__setattr__(self, "version", self.seed_version)
        object.__setattr__(
            self, "first_chat_instruction_version", self.first_chat_version
        )

    @property
    def fingerprint(self) -> str:
        """Return a deterministic digest containing no resolved credentials."""

        payload = {
            "schema_version": self.seed_version,
            "foundry_profile_id": self.foundry_profile_id,
            "hermes_profile_key": self.hermes_profile_key,
            "identity": dict(self.identity),
            "personality": self.personality,
            "first_chat_version": self.first_chat_version,
            "first_chat_instruction": self.first_chat_instruction,
            "model": {
                "provider": self.provider,
                "default": self.model,
                "base_url": self.base_url,
            },
            "credential_refs": dict(self.credential_refs),
        }
        return hashlib.sha256(
            b"allies-profile-seed-v1\0" + _canonical_json(payload)
        ).hexdigest()

    @property
    def model_provider_name(self) -> str:
        return self.provider

    @property
    def model_default_name(self) -> str:
        return self.model

    @property
    def profile_key(self) -> str:
        return self.hermes_profile_key or ""

    @property
    def seed_fingerprint(self) -> str:
        return self.fingerprint


@dataclass(frozen=True, slots=True)
class ProfileReceipt:
    status: ProfileProvisionStatus
    profile_key: str
    foundry_profile_id: str
    seed_fingerprint: str | None
    lifecycle_epoch: int
    materialized_generation: str | None
    operation_id: str | None
    receipt_id: str
    repair_code: str | None = None

    @property
    def result_code(self) -> str:
        return self.status.value.lower()

    @property
    def state(self) -> str:
        return self.status.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "result_code": self.result_code,
            "profile_key": self.profile_key,
            "foundry_profile_id": self.foundry_profile_id,
            "seed_fingerprint": self.seed_fingerprint,
            "lifecycle_epoch": self.lifecycle_epoch,
            "materialized_generation": self.materialized_generation,
            "operation_id": self.operation_id,
            "receipt_id": self.receipt_id,
            "repair_code": self.repair_code,
        }


@dataclass(frozen=True, slots=True)
class CleanupReceipt:
    status: ProfileCleanupStatus
    profile_key: str
    lifecycle_epoch: int
    operation_id: str
    receipt_id: str
    repair_code: str | None = None

    @property
    def result_code(self) -> str:
        return self.status.value.lower()

    @property
    def state(self) -> str:
        return self.status.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "result_code": self.result_code,
            "profile_key": self.profile_key,
            "lifecycle_epoch": self.lifecycle_epoch,
            "operation_id": self.operation_id,
            "receipt_id": self.receipt_id,
            "repair_code": self.repair_code,
        }


def _default_api_key_factory() -> str:
    return secrets.token_urlsafe(32)


def _validate_generated_key(value: Any) -> str:
    if not isinstance(value, str) or not 16 <= len(value) <= 256:
        raise ProfileStoreError("profile API key factory returned an invalid key")
    if any(character in value for character in "\x00\r\n"):
        raise ProfileStoreError("profile API key factory returned an invalid key")
    return value


def _validate_resolved_value(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > MAX_FIELD_BYTES
    ):
        raise ProfileStoreError("credential resolver returned an invalid value")
    if any(character in value for character in "\x00\r\n"):
        raise ProfileStoreError("credential resolver returned an invalid value")
    return value


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _receipt_id(
    *,
    profile_key: str,
    operation_id: str,
    fingerprint: str,
    epoch: int,
    generation: str,
) -> str:
    payload = (
        f"{profile_key}\0{operation_id}\0{fingerprint}\0{epoch}\0{generation}".encode()
    )
    return "pr-" + hashlib.sha256(payload).hexdigest()[:32]


def _cleanup_receipt_id(*, profile_key: str, operation_id: str, epoch: int) -> str:
    payload = f"cleanup\0{profile_key}\0{operation_id}\0{epoch}".encode()
    return "cr-" + hashlib.sha256(payload).hexdigest()[:32]


def _safe_repair_code(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value in _SAFE_REPAIR_CODES:
        return value
    return "invalid_repair_code"


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _is_symlink(path: Path) -> bool:
    info = _lstat(path)
    return info is not None and stat.S_ISLNK(info.st_mode)


def _is_regular_file(path: Path) -> bool:
    info = _lstat(path)
    return info is not None and os.path.isfile(path) and not os.path.islink(path)


def _is_directory(path: Path) -> bool:
    info = _lstat(path)
    return info is not None and os.path.isdir(path) and not os.path.islink(path)


def _reject_symlinked_components(path: Path) -> None:
    """Reject symlinks in the configured path before any directory creation."""

    current = Path(path.anchor)
    for component in path.parts:
        if component == path.anchor:
            continue
        current /= component
        if _is_symlink(current):
            raise ProfileStoreError("volume root contains a symlinked component")
        if _lstat(current) is None:
            # No later component can exist without this component existing.
            break


def _process_is_alive(pid: int) -> bool:
    """Return false only when the operating system confirms that ``pid`` is gone."""

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        # An indeterminate liveness result must not permit lock stealing.
        return True
    return True


def _read_lock_metadata(path: Path) -> tuple[int, str] | None:
    if not _is_regular_file(path):
        return None
    try:
        payload = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    pid = payload.get("pid")
    nonce = payload.get("nonce")
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or not isinstance(nonce, str)
        or not re.fullmatch(r"[0-9a-f]{24}", nonce)
    ):
        return None
    return pid, nonce


class _ProfileLock:
    def __init__(self, store: ProfileStore, key: str) -> None:
        self.store = store
        self.key = key
        self.marker: Path | None = None
        self.owner = secrets.token_hex(12)
        self.pid = os.getpid()

    def _acquire_file(self, deadline: float) -> None:
        locks_root = self.store._locks_root()
        self.marker = locks_root / f"{self.key}.lock"
        while True:
            try:
                fd = os.open(
                    self.marker,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                try:
                    metadata = json.dumps(
                        {"nonce": self.owner, "pid": self.pid},
                        separators=(",", ":"),
                    ).encode("ascii")
                    os.write(fd, metadata)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                try:
                    os.chmod(self.marker, 0o600)
                except OSError:
                    pass
                return
            except FileExistsError:
                info = _lstat(self.marker)
                if info is not None and not stat.S_ISLNK(info.st_mode):
                    age = max(0.0, time.time() - info.st_mtime)
                    metadata = _read_lock_metadata(self.marker)
                    owner_is_alive = metadata is not None and _process_is_alive(
                        metadata[0]
                    )
                    if (
                        age > self.store.stale_lock_seconds
                        and _is_regular_file(self.marker)
                        and not owner_is_alive
                    ):
                        try:
                            self.marker.unlink()
                        except OSError:
                            pass
                if time.monotonic() >= deadline:
                    raise ProfileStoreError(
                        "profile lock acquisition timed out"
                    ) from None
                time.sleep(min(0.02, max(0.001, deadline - time.monotonic())))
            except OSError:
                raise ProfileStoreError("profile lock acquisition failed") from None

    def release(self) -> None:
        if self.marker is None:
            return
        try:
            metadata = _read_lock_metadata(self.marker)
            if metadata == (self.pid, self.owner):
                self.marker.unlink()
        except OSError:
            pass


class ProfileStore:
    """Materialize and clean one profile namespace on a mounted volume."""

    def __init__(
        self,
        volume_root: str | os.PathLike[str],
        *,
        api_key_factory: Callable[[], str] | None = None,
        credential_resolver: Callable[[str], str] | Mapping[str, str] | None = None,
        lock_timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
        stale_lock_seconds: float = DEFAULT_STALE_LOCK_SECONDS,
        cleanup_timeout_seconds: float = DEFAULT_CLEANUP_TIMEOUT_SECONDS,
        max_cleanup_entries: int = MAX_CLEANUP_ENTRIES,
    ) -> None:
        root = Path(volume_root)
        if not root.is_absolute():
            raise ProfileInputError("volume root must be absolute")
        if not 0 < lock_timeout_seconds <= 60:
            raise ProfileInputError("lock timeout is invalid")
        if not 0 < stale_lock_seconds <= 86_400:
            raise ProfileInputError("stale lock timeout is invalid")
        if not 0 < cleanup_timeout_seconds <= 300:
            raise ProfileInputError("cleanup timeout is invalid")
        if not 1 <= max_cleanup_entries <= MAX_CLEANUP_ENTRIES:
            raise ProfileInputError("cleanup bound is invalid")
        # Keep the configured path intact.  Resolving it here would erase the
        # symlink evidence that the volume checks below must reject.
        self.volume_root = root
        self.api_key_factory = api_key_factory or _default_api_key_factory
        self.credential_resolver = credential_resolver
        self.lock_timeout_seconds = lock_timeout_seconds
        self.stale_lock_seconds = stale_lock_seconds
        self.cleanup_timeout_seconds = cleanup_timeout_seconds
        self.max_cleanup_entries = max_cleanup_entries
        self._local_locks: dict[tuple[str, str], threading.Lock] = {}
        self._local_locks_guard = threading.Lock()

    def _profiles_root(self) -> Path:
        try:
            _reject_symlinked_components(self.volume_root)
            self.volume_root.mkdir(parents=True, exist_ok=True)
            profiles = self.volume_root / "profiles"
            if _is_symlink(profiles):
                raise ProfileStoreError("profile namespace is symlinked")
            profiles.mkdir(exist_ok=True)
            if not _is_directory(profiles):
                raise ProfileStoreError("profile namespace is not a directory")
            return profiles
        except ProfileStoreError:
            raise
        except OSError:
            raise ProfileStoreError("profile namespace is unavailable") from None

    def _locks_root(self) -> Path:
        root = self._profiles_root() / ".allies-profile-locks"
        if _is_symlink(root):
            raise ProfileStoreError("profile lock namespace is symlinked")
        try:
            root.mkdir(exist_ok=True)
        except OSError:
            raise ProfileStoreError("profile lock namespace is unavailable") from None
        if not _is_directory(root):
            raise ProfileStoreError("profile lock namespace is not a directory")
        return root

    def _tombstones_root(self) -> Path:
        root = self._profiles_root() / ".allies-profile-tombstones"
        if _is_symlink(root):
            raise ProfileStoreError("profile tombstone namespace is symlinked")
        try:
            root.mkdir(exist_ok=True)
        except OSError:
            raise ProfileStoreError(
                "profile tombstone namespace is unavailable"
            ) from None
        if not _is_directory(root):
            raise ProfileStoreError("profile tombstone namespace is not a directory")
        return root

    def _profile_path(self, key: str) -> Path:
        key = validate_profile_key(key)
        profiles = self._profiles_root()
        path = profiles / key
        if path.parent != profiles:
            raise ProfileStoreError("profile path escaped its namespace")
        try:
            if path.parent.resolve() != profiles.resolve():
                raise ProfileStoreError("profile path escaped its namespace")
        except OSError:
            raise ProfileStoreError("profile path could not be verified") from None
        return path

    def _local_lock(self, key: str) -> threading.Lock:
        identity = (str(self.volume_root), key)
        with self._local_locks_guard:
            return self._local_locks.setdefault(identity, threading.Lock())

    @contextmanager
    def _lock(self, key: str) -> Iterator[None]:
        local_lock = self._local_lock(key)
        acquired = local_lock.acquire(timeout=self.lock_timeout_seconds)
        if not acquired:
            raise ProfileStoreError("profile lock acquisition timed out") from None
        file_lock = _ProfileLock(self, key)
        try:
            file_lock._acquire_file(time.monotonic() + self.lock_timeout_seconds)
            yield
        finally:
            file_lock.release()
            local_lock.release()

    def _receipt(
        self,
        seed: ProfileSeed,
        status: ProfileProvisionStatus,
        *,
        repair_code: str | None = None,
        operation_id: str | None = None,
        fingerprint: str | None = None,
        generation: str | None = None,
        receipt_id: str | None = None,
    ) -> ProfileReceipt:
        fingerprint = fingerprint if fingerprint is not None else seed.fingerprint
        operation_id = operation_id if operation_id is not None else seed.operation_id
        generation = (
            generation if generation is not None else seed.materialized_generation
        )
        if receipt_id is None:
            receipt_id = _receipt_id(
                profile_key=seed.hermes_profile_key or "invalid",
                operation_id=operation_id,
                fingerprint=fingerprint,
                epoch=seed.lifecycle_epoch,
                generation=generation,
            )
        return ProfileReceipt(
            status=status,
            profile_key=seed.hermes_profile_key or "invalid",
            foundry_profile_id=seed.foundry_profile_id,
            seed_fingerprint=fingerprint,
            lifecycle_epoch=seed.lifecycle_epoch,
            materialized_generation=generation,
            operation_id=operation_id,
            receipt_id=receipt_id,
            repair_code=repair_code,
        )

    def _tombstone_path(self, key: str) -> Path:
        path = self._tombstones_root() / f"{validate_profile_key(key)}.json"
        if path.parent != self._tombstones_root():
            raise ProfileStoreError("profile tombstone path escaped its namespace")
        return path

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not _is_regular_file(path):
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _write_bytes(self, path: Path, content: bytes, *, mode: int) -> None:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
            try:
                view = memoryview(content)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.chmod(path, mode)
        except OSError:
            raise ProfileStoreError("profile file write failed") from None

    def _write_json_atomic(
        self, path: Path, payload: Mapping[str, Any], *, mode: int
    ) -> None:
        parent = path.parent
        if not _is_directory(parent) or _is_symlink(path):
            raise ProfileStoreError("profile metadata path is unsafe")
        temporary = parent / f".{path.name}.tmp-{secrets.token_hex(8)}"
        try:
            self._write_bytes(
                temporary,
                _canonical_json(dict(payload)) + b"\n",
                mode=mode,
            )
            os.replace(temporary, path)
            try:
                os.chmod(path, mode)
            except OSError:
                pass
        except ProfileStoreError:
            try:
                if _is_regular_file(temporary):
                    temporary.unlink()
            except OSError:
                pass
            raise
        except OSError:
            raise ProfileStoreError("profile metadata publish failed") from None

    def _sync_directory(self, path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            # Directory fsync is not available on every supported runtime.
            pass

    def _temp_prefix(self, key: str) -> str:
        return f".{key}.tmp-"

    def _temp_path(self, profiles_root: Path, seed: ProfileSeed) -> Path:
        operation_digest = hashlib.sha256(seed.operation_id.encode()).hexdigest()[:24]
        return (
            profiles_root
            / f"{self._temp_prefix(seed.hermes_profile_key or 'invalid')}{operation_digest}"
        )

    def _find_temp_siblings(self, profiles_root: Path, key: str) -> list[Path] | None:
        prefix = self._temp_prefix(key)
        try:
            entries = [
                item for item in profiles_root.iterdir() if item.name.startswith(prefix)
            ]
        except OSError:
            return None
        if len(entries) > self.max_cleanup_entries:
            return None
        return entries

    def _remove_owned_path(
        self, path: Path, *, parent: Path, allow_directory: bool = True
    ) -> None:
        if path.parent != parent or _is_symlink(path):
            raise ProfileStoreError("cleanup path is unsafe")
        info = _lstat(path)
        if info is None:
            return
        try:
            if os.path.isdir(path):
                if not allow_directory:
                    raise ProfileStoreError("cleanup path is unsafe")
                shutil.rmtree(path)
            elif os.path.isfile(path):
                path.unlink()
            else:
                raise ProfileStoreError("cleanup path is unsafe")
        except ProfileStoreError:
            raise
        except OSError:
            raise ProfileStoreError("profile cleanup failed") from None

    def _profile_tree_is_bounded_and_local(self, profile: Path) -> bool:
        """Bound deletion work and refuse nested links that could redirect it."""

        pending = [profile]
        entries_seen = 0
        try:
            while pending:
                current = pending.pop()
                with os.scandir(current) as entries:
                    for entry in entries:
                        entries_seen += 1
                        if (
                            entries_seen > self.max_cleanup_entries
                            or entry.is_symlink()
                        ):
                            return False
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
        except OSError:
            return False
        return True

    def _build_profile(self, seed: ProfileSeed, temporary: Path) -> tuple[str, str]:
        try:
            temporary.mkdir(mode=0o755)
            os.chmod(temporary, 0o755)
            for directory in HERMES_PROFILE_DIRECTORIES:
                child = temporary / directory
                child.mkdir(mode=0o755)
                os.chmod(child, 0o755)

            key = self._resolve_api_key()
            env_lines = [f"API_SERVER_KEY={key}"]
            for env_name, reference in seed.credential_refs.items():
                env_lines.append(f"{env_name}={self._resolve_credential(reference)}")
            self._write_bytes(
                temporary / ".env",
                ("\n".join(env_lines) + "\n").encode("utf-8"),
                mode=0o600,
            )

            config_lines = [
                "model:",
                f"  provider: {_yaml_string(seed.provider)}",
                f"  default: {_yaml_string(seed.model)}",
            ]
            if seed.base_url is not None:
                config_lines.append(f"  base_url: {_yaml_string(seed.base_url)}")
            self._write_bytes(
                temporary / "config.yaml",
                ("\n".join(config_lines) + "\n").encode("utf-8"),
                mode=0o644,
            )

            separator = "" if seed.personality.endswith("\n") else "\n"
            soul = (
                seed.personality
                + separator
                + "\n"
                + f"<!-- allies-first-chat:v{seed.first_chat_version} -->\n"
                + f"## Allies first-chat/system instruction (v{seed.first_chat_version})\n"
                + seed.first_chat_instruction
                + "\n"
            )
            self._write_bytes(temporary / "SOUL.md", soul.encode("utf-8"), mode=0o644)

            receipt_id = _receipt_id(
                profile_key=seed.hermes_profile_key or "invalid",
                operation_id=seed.operation_id,
                fingerprint=seed.fingerprint,
                epoch=seed.lifecycle_epoch,
                generation=seed.materialized_generation,
            )
            manifest = {
                "schema": MANIFEST_SCHEMA,
                "schema_version": MANIFEST_VERSION,
                "foundry_profile_id": seed.foundry_profile_id,
                "hermes_profile_key": seed.hermes_profile_key,
                "lifecycle_epoch": seed.lifecycle_epoch,
                "seed_fingerprint": seed.fingerprint,
                "seed_version": seed.seed_version,
                "first_chat_version": seed.first_chat_version,
                "materialized_generation": seed.materialized_generation,
                "operation_id": seed.operation_id,
                "receipt_id": receipt_id,
                "completion_state": "complete",
                "lifecycle_state": "active",
            }
            self._write_bytes(
                temporary / MANIFEST_NAME,
                _canonical_json(manifest) + b"\n",
                mode=0o644,
            )
            self._sync_directory(temporary)
            return key, receipt_id
        except ProfileStoreError:
            raise
        except Exception:  # noqa: BLE001 - injected factories must be sanitized
            raise ProfileStoreError("profile materialization failed") from None

    def _resolve_api_key(self) -> str:
        try:
            return _validate_generated_key(self.api_key_factory())
        except ProfileStoreError:
            raise
        except Exception:  # noqa: BLE001 - injected factories must be sanitized
            raise ProfileStoreError("profile API key generation failed") from None

    def _resolve_credential(self, reference: str) -> str:
        resolver = self.credential_resolver
        if resolver is None:
            raise ProfileStoreError("credential resolver is unavailable")
        try:
            if isinstance(resolver, Mapping):
                value = resolver[reference]
            else:
                value = resolver(reference)
        except Exception:  # noqa: BLE001 - injected resolvers must be sanitized
            raise ProfileStoreError("credential resolution failed") from None
        return _validate_resolved_value(value)

    def _inspect_existing(
        self, seed: ProfileSeed, profile: Path
    ) -> ProfileReceipt | None:
        if _is_symlink(profile):
            return self._receipt(
                seed,
                ProfileProvisionStatus.REPAIR_REQUIRED,
                repair_code="symlinked_profile",
            )
        if not _is_directory(profile):
            if _lstat(profile) is not None:
                return self._receipt(
                    seed,
                    ProfileProvisionStatus.REPAIR_REQUIRED,
                    repair_code="profile_is_not_directory",
                )
            return None

        manifest_path = profile / MANIFEST_NAME
        manifest = self._read_json(manifest_path)
        if manifest is None:
            return self._receipt(
                seed,
                ProfileProvisionStatus.REPAIR_REQUIRED,
                repair_code="incomplete_manifest",
            )
        if (
            manifest.get("schema") != MANIFEST_SCHEMA
            or manifest.get("schema_version") != MANIFEST_VERSION
        ):
            return self._receipt(
                seed,
                ProfileProvisionStatus.REPAIR_REQUIRED,
                repair_code="unsupported_manifest",
            )
        if (
            manifest.get("foundry_profile_id") != seed.foundry_profile_id
            or manifest.get("hermes_profile_key") != seed.hermes_profile_key
        ):
            return self._receipt(
                seed, ProfileProvisionStatus.CONFLICT, repair_code="identity_collision"
            )
        if manifest.get("seed_fingerprint") != seed.fingerprint:
            code = (
                "instruction_version_conflict"
                if manifest.get("first_chat_version") != seed.first_chat_version
                else "seed_fingerprint_conflict"
            )
            return self._receipt(
                seed, ProfileProvisionStatus.CONFLICT, repair_code=code
            )
        if manifest.get("lifecycle_epoch") != seed.lifecycle_epoch:
            if (
                isinstance(manifest.get("lifecycle_epoch"), int)
                and manifest["lifecycle_epoch"] > seed.lifecycle_epoch
            ):
                return self._receipt(
                    seed,
                    ProfileProvisionStatus.FENCED,
                    repair_code="stale_lifecycle_epoch",
                )
            return self._receipt(
                seed,
                ProfileProvisionStatus.REPAIR_REQUIRED,
                repair_code="lifecycle_epoch_mismatch",
            )
        if manifest.get("completion_state") != "complete":
            return self._receipt(
                seed,
                ProfileProvisionStatus.REPAIR_REQUIRED,
                repair_code="incomplete_profile",
            )
        required_files = ("config.yaml", ".env", "SOUL.md", MANIFEST_NAME)
        if any(not _is_regular_file(profile / name) for name in required_files):
            return self._receipt(
                seed,
                ProfileProvisionStatus.REPAIR_REQUIRED,
                repair_code="incomplete_profile",
            )
        for directory in HERMES_PROFILE_DIRECTORIES:
            if not _is_directory(profile / directory):
                return self._receipt(
                    seed,
                    ProfileProvisionStatus.REPAIR_REQUIRED,
                    repair_code="incomplete_layout",
                )
        env_mode = os.stat(profile / ".env", follow_symlinks=False).st_mode & 0o777
        if os.name != "nt" and env_mode & 0o077:
            return self._receipt(
                seed,
                ProfileProvisionStatus.REPAIR_REQUIRED,
                repair_code="secret_file_permissions",
            )

        stored_operation = manifest.get("operation_id")
        stored_generation = manifest.get("materialized_generation")
        stored_receipt = manifest.get("receipt_id")
        try:
            _safe_operation_id(stored_operation)
        except ProfileInputError:
            return self._receipt(
                seed,
                ProfileProvisionStatus.REPAIR_REQUIRED,
                repair_code="invalid_manifest_metadata",
            )
        if (
            not isinstance(stored_generation, str)
            or not isinstance(stored_receipt, str)
            or not _RECEIPT_ID_PATTERN.fullmatch(stored_receipt)
        ):
            return self._receipt(
                seed,
                ProfileProvisionStatus.REPAIR_REQUIRED,
                repair_code="invalid_manifest_metadata",
            )
        if (
            stored_operation != seed.operation_id
            or stored_generation != seed.materialized_generation
        ):
            updated = dict(manifest)
            updated["operation_id"] = seed.operation_id
            updated["materialized_generation"] = seed.materialized_generation
            updated["receipt_id"] = _receipt_id(
                profile_key=seed.hermes_profile_key or "invalid",
                operation_id=seed.operation_id,
                fingerprint=seed.fingerprint,
                epoch=seed.lifecycle_epoch,
                generation=seed.materialized_generation,
            )
            try:
                self._write_json_atomic(manifest_path, updated, mode=0o644)
            except ProfileStoreError:
                return self._receipt(
                    seed,
                    ProfileProvisionStatus.REPAIR_REQUIRED,
                    repair_code="manifest_update_failed",
                )
            stored_operation = seed.operation_id
            stored_generation = seed.materialized_generation
            stored_receipt = updated["receipt_id"]
        return self._receipt(
            seed,
            ProfileProvisionStatus.EXISTING,
            operation_id=stored_operation,
            fingerprint=seed.fingerprint,
            generation=stored_generation,
            receipt_id=stored_receipt,
        )

    def _read_tombstone(self, key: str) -> dict[str, Any] | None:
        path = self._tombstone_path(key)
        info = _lstat(path)
        if info is None:
            return None
        if not _is_regular_file(path):
            return {"_invalid_tombstone": True}
        payload = self._read_json(path)
        return payload if payload is not None else {"_invalid_tombstone": True}

    def _tombstone_receipt(self, payload: Mapping[str, Any]) -> CleanupReceipt | None:
        status = payload.get("status")
        if status not in {item.value for item in ProfileCleanupStatus}:
            return None
        key = payload.get("profile_key")
        operation_id = payload.get("operation_id")
        epoch = payload.get("lifecycle_epoch")
        receipt_id = payload.get("receipt_id")
        if (
            not isinstance(key, str)
            or not isinstance(operation_id, str)
            or not isinstance(epoch, int)
            or isinstance(epoch, bool)
            or not isinstance(receipt_id, str)
            or not _RECEIPT_ID_PATTERN.fullmatch(receipt_id)
        ):
            return None
        try:
            validate_profile_key(key)
            _safe_operation_id(operation_id)
        except ProfileInputError:
            return None
        return CleanupReceipt(
            ProfileCleanupStatus(status),
            key,
            epoch,
            operation_id,
            receipt_id,
            _safe_repair_code(payload.get("repair_code")),
        )

    def materialize(
        self,
        seed: ProfileSeed,
        *,
        operation_id: str | None = None,
        lifecycle_epoch: int | None = None,
        materialized_generation: str | int | None = None,
    ) -> ProfileReceipt:
        """Create or inspect one profile, returning a sanitized receipt."""

        if not isinstance(seed, ProfileSeed):
            raise ProfileInputError("profile seed is invalid")
        overrides: dict[str, Any] = {}
        if operation_id is not None:
            overrides["operation_id"] = operation_id
        if lifecycle_epoch is not None:
            overrides["lifecycle_epoch"] = lifecycle_epoch
        if materialized_generation is not None:
            overrides["materialized_generation"] = materialized_generation
        if overrides:
            seed = replace(seed, **overrides)

        try:
            profiles_root = self._profiles_root()
            profile = self._profile_path(seed.hermes_profile_key or "invalid")
            with self._lock(seed.hermes_profile_key or "invalid"):
                tombstone = self._read_tombstone(seed.hermes_profile_key or "invalid")
                if tombstone is not None:
                    tombstone_receipt = self._tombstone_receipt(tombstone)
                    if (
                        tombstone_receipt is None
                        or tombstone_receipt.profile_key != seed.hermes_profile_key
                    ):
                        return self._receipt(
                            seed,
                            ProfileProvisionStatus.REPAIR_REQUIRED,
                            repair_code="invalid_cleanup_tombstone",
                        )
                    return self._receipt(
                        seed,
                        ProfileProvisionStatus.FENCED,
                        repair_code="profile_deprovisioned",
                    )

                existing = self._inspect_existing(seed, profile)
                if existing is not None:
                    return existing

                temp_siblings = self._find_temp_siblings(
                    profiles_root, seed.hermes_profile_key or "invalid"
                )
                if temp_siblings is None:
                    return self._receipt(
                        seed,
                        ProfileProvisionStatus.REPAIR_REQUIRED,
                        repair_code="temporary_state_unreadable",
                    )
                temporary = self._temp_path(profiles_root, seed)
                for sibling in temp_siblings:
                    if sibling == temporary:
                        if _is_symlink(sibling):
                            return self._receipt(
                                seed,
                                ProfileProvisionStatus.REPAIR_REQUIRED,
                                repair_code="symlinked_temporary_state",
                            )
                        self._remove_owned_path(sibling, parent=profiles_root)
                    else:
                        return self._receipt(
                            seed,
                            ProfileProvisionStatus.REPAIR_REQUIRED,
                            repair_code="unknown_temporary_state",
                        )

                try:
                    _, receipt_id = self._build_profile(seed, temporary)
                    if _lstat(profile) is not None:
                        return self._receipt(
                            seed,
                            ProfileProvisionStatus.REPAIR_REQUIRED,
                            repair_code="profile_appeared_during_publish",
                        )
                    os.rename(temporary, profile)
                    self._sync_directory(profiles_root)
                    return self._receipt(
                        seed, ProfileProvisionStatus.CREATED, receipt_id=receipt_id
                    )
                except ProfileStoreError:
                    if _is_regular_file(temporary) or _is_directory(temporary):
                        # Preserve an interrupted operation for bounded repair;
                        # a retry of the same operation owns this exact sibling.
                        return self._receipt(
                            seed,
                            ProfileProvisionStatus.REPAIR_REQUIRED,
                            repair_code="materialization_failed",
                        )
                    return self._receipt(
                        seed,
                        ProfileProvisionStatus.REPAIR_REQUIRED,
                        repair_code="materialization_failed",
                    )
                except OSError:
                    return self._receipt(
                        seed,
                        ProfileProvisionStatus.REPAIR_REQUIRED,
                        repair_code="profile_publish_failed",
                    )
        except ProfileStoreError as exc:
            code = (
                "lock_timeout"
                if "timed out" in str(exc)
                else "profile_store_unavailable"
            )
            return self._receipt(
                seed, ProfileProvisionStatus.REPAIR_REQUIRED, repair_code=code
            )

    provision = materialize
    materialize_profile = materialize

    def cleanup(
        self,
        profile_key: str,
        operation_id: str,
        lifecycle_epoch: int,
        expires_at: datetime | float | str | None = None,
    ) -> CleanupReceipt:
        """Fence and remove one exact profile directory, safely and idempotently."""

        key = validate_profile_key(profile_key)
        operation_id = _safe_operation_id(operation_id)
        if (
            isinstance(lifecycle_epoch, bool)
            or not isinstance(lifecycle_epoch, int)
            or lifecycle_epoch < 0
        ):
            raise ProfileInputError("lifecycle epoch is invalid")
        expiry = self._expiry_timestamp(expires_at)
        # Foundry commits the incremented lifecycle epoch before dispatching
        # cleanup.  Runtime records that fenced epoch; it does not advance
        # control-plane state a second time.
        requested_epoch = lifecycle_epoch
        receipt_id = _cleanup_receipt_id(
            profile_key=key, operation_id=operation_id, epoch=requested_epoch
        )

        try:
            profiles_root = self._profiles_root()
            profile = self._profile_path(key)
            tombstone_path = self._tombstone_path(key)
            with self._lock(key):
                existing_payload = (
                    self._read_json(tombstone_path)
                    if _lstat(tombstone_path) is not None
                    else None
                )
                if _lstat(tombstone_path) is not None and existing_payload is None:
                    return CleanupReceipt(
                        ProfileCleanupStatus.REPAIR_REQUIRED,
                        key,
                        requested_epoch,
                        operation_id,
                        receipt_id,
                        "invalid_cleanup_tombstone",
                    )
                if existing_payload is not None:
                    existing_status = existing_payload.get("status")
                    if existing_status == "CLEANUP_PENDING":
                        existing_key = existing_payload.get("profile_key")
                        existing_operation = existing_payload.get("operation_id")
                        existing_epoch = existing_payload.get("lifecycle_epoch")
                        if (
                            existing_key != key
                            or not isinstance(existing_operation, str)
                            or not isinstance(existing_epoch, int)
                            or isinstance(existing_epoch, bool)
                        ):
                            return CleanupReceipt(
                                ProfileCleanupStatus.REPAIR_REQUIRED,
                                key,
                                requested_epoch,
                                operation_id,
                                receipt_id,
                                "invalid_cleanup_tombstone",
                            )
                        if (
                            existing_operation == operation_id
                            and existing_epoch == requested_epoch
                        ):
                            pass  # Resume an interrupted delete for the same operation.
                        elif requested_epoch <= existing_epoch:
                            return CleanupReceipt(
                                ProfileCleanupStatus.FENCED,
                                key,
                                existing_epoch,
                                operation_id,
                                receipt_id,
                                "stale_cleanup_epoch",
                            )
                    else:
                        existing = self._tombstone_receipt(existing_payload)
                        if existing is None or existing.profile_key != key:
                            return CleanupReceipt(
                                ProfileCleanupStatus.REPAIR_REQUIRED,
                                key,
                                requested_epoch,
                                operation_id,
                                receipt_id,
                                "invalid_cleanup_tombstone",
                            )
                        if (
                            existing.operation_id == operation_id
                            and existing.lifecycle_epoch == requested_epoch
                        ):
                            if existing.status is ProfileCleanupStatus.DEPROVISIONED:
                                return existing
                        elif requested_epoch <= existing.lifecycle_epoch:
                            return CleanupReceipt(
                                ProfileCleanupStatus.FENCED,
                                key,
                                existing.lifecycle_epoch,
                                operation_id,
                                receipt_id,
                                "stale_cleanup_epoch",
                            )

                if _is_directory(profile):
                    profile_manifest = self._read_json(profile / MANIFEST_NAME)
                    profile_epoch = (
                        profile_manifest.get("lifecycle_epoch")
                        if profile_manifest
                        else None
                    )
                    if (
                        isinstance(profile_epoch, int)
                        and not isinstance(profile_epoch, bool)
                        and profile_epoch > lifecycle_epoch
                    ):
                        return CleanupReceipt(
                            ProfileCleanupStatus.FENCED,
                            key,
                            profile_epoch,
                            operation_id,
                            receipt_id,
                            "stale_cleanup_epoch",
                        )

                if expiry <= time.time():
                    repair_payload = {
                        "schema": MANIFEST_SCHEMA,
                        "schema_version": MANIFEST_VERSION,
                        "profile_key": key,
                        "lifecycle_epoch": requested_epoch,
                        "operation_id": operation_id,
                        "receipt_id": receipt_id,
                        "status": ProfileCleanupStatus.REPAIR_REQUIRED.value,
                        "repair_code": "cleanup_expired",
                    }
                    self._write_json_atomic(tombstone_path, repair_payload, mode=0o644)
                    return CleanupReceipt(
                        ProfileCleanupStatus.REPAIR_REQUIRED,
                        key,
                        requested_epoch,
                        operation_id,
                        receipt_id,
                        "cleanup_expired",
                    )

                pending_payload = {
                    "schema": MANIFEST_SCHEMA,
                    "schema_version": MANIFEST_VERSION,
                    "profile_key": key,
                    "lifecycle_epoch": requested_epoch,
                    "operation_id": operation_id,
                    "receipt_id": receipt_id,
                    "status": "CLEANUP_PENDING",
                    "expires_at": expiry,
                }
                self._write_json_atomic(tombstone_path, pending_payload, mode=0o644)

                if _is_symlink(profile):
                    repair_code = "symlinked_profile"
                elif _lstat(profile) is not None and not _is_directory(profile):
                    repair_code = "profile_is_not_directory"
                else:
                    repair_code = None
                if (
                    repair_code is None
                    and _is_directory(profile)
                    and not self._profile_tree_is_bounded_and_local(profile)
                ):
                    repair_code = "cleanup_bound_exceeded"
                if repair_code is None:
                    try:
                        self._remove_owned_path(profile, parent=profiles_root)
                        temp_siblings = self._find_temp_siblings(profiles_root, key)
                        if temp_siblings is None:
                            repair_code = "temporary_state_unreadable"
                        else:
                            for sibling in temp_siblings:
                                self._remove_owned_path(sibling, parent=profiles_root)
                    except ProfileStoreError:
                        repair_code = "profile_cleanup_failed"

                if repair_code is not None:
                    repair_payload = dict(pending_payload)
                    repair_payload["status"] = (
                        ProfileCleanupStatus.REPAIR_REQUIRED.value
                    )
                    repair_payload["repair_code"] = repair_code
                    try:
                        self._write_json_atomic(
                            tombstone_path, repair_payload, mode=0o644
                        )
                    except ProfileStoreError:
                        pass
                    return CleanupReceipt(
                        ProfileCleanupStatus.REPAIR_REQUIRED,
                        key,
                        requested_epoch,
                        operation_id,
                        receipt_id,
                        repair_code,
                    )

                complete_payload = dict(pending_payload)
                complete_payload["status"] = ProfileCleanupStatus.DEPROVISIONED.value
                complete_payload.pop("expires_at", None)
                self._write_json_atomic(tombstone_path, complete_payload, mode=0o644)
                return CleanupReceipt(
                    ProfileCleanupStatus.DEPROVISIONED,
                    key,
                    requested_epoch,
                    operation_id,
                    receipt_id,
                )
        except ProfileStoreError:
            return CleanupReceipt(
                ProfileCleanupStatus.REPAIR_REQUIRED,
                key,
                requested_epoch,
                operation_id,
                receipt_id,
                "cleanup_unavailable",
            )

    deprovision = cleanup
    cleanup_profile = cleanup

    def _expiry_timestamp(self, value: datetime | float | str | None) -> float:
        if value is None:
            return time.time() + self.cleanup_timeout_seconds
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.timestamp()
            return value.timestamp()
        if isinstance(value, bool):
            raise ProfileInputError("cleanup expiry is invalid")
        if isinstance(value, (float, int)):
            value = float(value)
        elif isinstance(value, str):
            try:
                value = datetime.fromisoformat(value).timestamp()
            except ValueError:
                raise ProfileInputError("cleanup expiry is invalid") from None
        else:
            raise ProfileInputError("cleanup expiry is invalid")
        if not math.isfinite(value):
            raise ProfileInputError("cleanup expiry is invalid")
        return value


def inspect_profile(store: ProfileStore, seed: ProfileSeed) -> ProfileReceipt:
    """Convenience wrapper used by startup reconciliation callers."""

    return store.materialize(seed)


__all__ = [
    "HERMES_PROFILE_DIRECTORIES",
    "MANIFEST_NAME",
    "CleanupReceipt",
    "ProfileCleanupStatus",
    "ProfileInputError",
    "ProfileProvisionStatus",
    "ProfileReceipt",
    "ProfileSeed",
    "ProfileStore",
    "ProfileStoreError",
    "derive_profile_key",
    "inspect_profile",
    "validate_profile_key",
]
