"""Fail-soft, profile-fenced Mnemosyne adapter for pinned Hermes.

This module intentionally composes ``mnemosyne_hermes``.  It does not fork or
patch Hermes/Mnemosyne and it never lets their broad stock defaults become the
effective Allies policy.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import logging
import os
import re
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:  # Hermes is present in the image, while unit tests may run standalone.
    from agent.memory_provider import MemoryProvider
except ImportError:  # pragma: no cover - exercised by the standalone test path.

    class MemoryProvider:  # type: ignore[no-redef]
        """Small import-time fallback; the real image always supplies Hermes."""


logger = logging.getLogger(__name__)

POLICY_VERSION = "allies-mnemosyne-v1"
PROVIDER_VERSION = "0.1.0"
MNEMOSYNE_HERMES_VERSION = "0.5.0"
DEFAULT_MODE = "context_only"
MODES = frozenset({"context_only", "narrow_tools"})

ALLOWED_TOOLS = (
    "mnemosyne_forget",
    "mnemosyne_forget_canonical",
    "mnemosyne_invalidate",
    "mnemosyne_recall",
    "mnemosyne_recall_canonical",
    "mnemosyne_remember",
    "mnemosyne_remember_canonical",
    "mnemosyne_update",
)
_ALLOWED_TOOL_SET = frozenset(ALLOWED_TOOLS)
_WRITE_TOOLS = frozenset(
    {
        "mnemosyne_forget",
        "mnemosyne_forget_canonical",
        "mnemosyne_invalidate",
        "mnemosyne_remember",
        "mnemosyne_remember_canonical",
        "mnemosyne_update",
    }
)

# This is the canonical sorted JSON hash of the eight reviewed schemas from
# mnemosyne-hermes 0.5.0.  A package upgrade must update this fixture in a
# review; a runtime schema change therefore fails closed in narrow mode.
REVIEWED_SCHEMA_HASHES = {
    (
        MNEMOSYNE_HERMES_VERSION,
        ",".join(ALLOWED_TOOLS),
    ): "17104318aba250e46f9c215be393a831a1751bcbcc853f21431d2c604fabb5e3",
}

MAX_QUERY_BYTES = 4_096
MAX_ARGUMENT_BYTES = 8_192
MAX_RECORD_BYTES = 4_096
MAX_RESULT_BYTES = 16_384
MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_CONFIG_BYTES = 65_536
SQLITE_BUSY_TIMEOUT_MS = 5_000

_PROFILE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SECRET_RE = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|"
    r"secret|private[_ -]?key|authorization\s*:\s*bearer|\bsk-[A-Za-z0-9]{16,})"
)
_TRANSCRIPT_RE = re.compile(
    r"(?i)(?:^|[\n\r])\s*(?:system|developer|user|assistant|tool)\s*[:>]|"
    r"<\|(?:system|developer|user|assistant|tool)\|>|tool_(?:call|result)|"
    r"raw\s+transcript|conversation\s+history"
)
_EPHEMERAL_RE = re.compile(
    r"(?i)(?:one[- ]off|one[- ]time|temporary|scratchpad|just\s+computed|"
    r"completed\s+(?:status|artifact)|artifact\s+(?:id|identifier)\b|"
    r"commit\s+(?:sha|identifier|id)\b)"
)
_COMMIT_RE = re.compile(r"\b[0-9a-f]{7,64}\b", re.IGNORECASE)
_SAFE_SOURCES = frozenset(
    {
        "correction",
        "decision",
        "environment",
        "fact",
        "identity",
        "insight",
        "knowledge",
        "preference",
        "relationship",
        "task",
        "user",
    }
)
_FORBIDDEN_ARGUMENT_KEYS = frozenset(
    {
        "author_id",
        "bank",
        "db",
        "db_path",
        "filesystem_path",
        "path",
        "profile",
        "profile_id",
        "shared",
        "shared_surface",
        "shared_surface_path",
        "surface",
    }
)

_INIT_ENV_LOCK = threading.RLock()


class _ProviderInvariantError(RuntimeError):
    """An authored, safe-to-report provider invariant failure."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_reason(exc: BaseException) -> str:
    """Return a reason code without echoing provider/user/path data."""

    if isinstance(exc, _ProviderInvariantError):
        return exc.reason_code
    return type(exc).__name__.lower().replace("error", "") or "provider_fault"


def _json_result(status: str, reason: str, **fields: Any) -> str:
    payload: dict[str, Any] = {"status": status, "reason": reason}
    payload.update(fields)
    try:
        return _canonical_json(payload)
    except (TypeError, ValueError):
        return '{"status":"memory_unavailable","reason":"result_encoding"}'


def _text_bytes(value: Any) -> int:
    if not isinstance(value, str):
        return 0
    return len(value.encode("utf-8", errors="replace"))


def _profile_memory_config(hermes_home: Path) -> dict[str, Any]:
    config_path = hermes_home / "config.yaml"
    try:
        if not config_path.is_file() or config_path.stat().st_size > MAX_CONFIG_BYTES:
            return {}
        import yaml

        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        memory = config.get("memory", {}) if isinstance(config, dict) else {}
        return memory if isinstance(memory, dict) else {}
    except Exception:  # noqa: BLE001 - invalid profile config fails closed
        return {}


def _contains_forbidden(value: Any) -> bool:
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            if (
                _SECRET_RE.search(current)
                or _TRANSCRIPT_RE.search(current)
                or _EPHEMERAL_RE.search(current)
                or _COMMIT_RE.search(current)
            ):
                return True
        elif isinstance(current, dict):
            pending.extend(current.values())
            pending.extend(str(key) for key in current)
        elif isinstance(current, (list, tuple)):
            pending.extend(current)
    return False


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return True


def _validate_args(schema: dict[str, Any], args: Any) -> str | None:
    if not isinstance(args, dict):
        return "arguments_object_required"
    try:
        argument_bytes = len(_canonical_json(args).encode("utf-8"))
    except (RecursionError, TypeError, ValueError):
        return "arguments_not_serializable"
    if argument_bytes > MAX_ARGUMENT_BYTES:
        return "arguments_too_large"
    if _FORBIDDEN_ARGUMENT_KEYS.intersection(args):
        return "profile_override_forbidden"
    parameters = schema.get("parameters") or {}
    if parameters.get("type") != "object":
        return "schema_parameters_invalid"
    properties = parameters.get("properties") or {}
    missing = [key for key in parameters.get("required", []) if key not in args]
    if missing:
        return "required_argument_missing"
    unknown = set(args).difference(properties)
    if unknown:
        return "unknown_argument"
    for key, value in args.items():
        definition = properties[key]
        if value is None and definition.get("type") != "null":
            return "argument_type_invalid"
        if value is not None and not _type_matches(value, definition.get("type", "")):
            return "argument_type_invalid"
        if "enum" in definition and value not in definition["enum"]:
            return "argument_value_invalid"
        if isinstance(value, str) and _text_bytes(value) > MAX_RECORD_BYTES:
            return "argument_string_too_large"
        if isinstance(value, (int, float)) and not (-1e9 <= value <= 1e9):
            return "argument_number_invalid"
        if isinstance(value, list) and len(value) > 64:
            return "argument_list_too_large"
    return None


def _invoke(
    callback: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> tuple[str, Any]:
    """Invoke a local provider hook and report its final outcome honestly."""

    try:
        return "ok", callback(*args, **kwargs)
    except BaseException as exc:  # noqa: BLE001 - cancellation must fail soft
        return _safe_reason(exc), None


class AlliesMnemosyneProvider(MemoryProvider):
    """Allies' fail-soft, profile-local wrapper around Mnemosyne for Hermes."""

    def __init__(self) -> None:
        self._delegate: Any = None
        self._available = False
        self._reason = "not_initialized"
        self._mode = DEFAULT_MODE
        self._tools: tuple[str, ...] = ()
        self._schemas: dict[str, dict[str, Any]] = {}
        self._schema_hash = ""
        self._schema_error = ""
        self._session_id = ""
        self._agent_context = ""
        self._profile_key = ""
        self._profile_root: Path | None = None
        self._db_path: Path | None = None
        self._correlation_id = ""
        self._turn_count = 0

    @property
    def name(self) -> str:
        return "allies_mnemosyne"

    def is_available(self) -> bool:
        """Check dependency presence only; initialization owns readiness."""

        if self._available:
            return True
        try:
            importlib.import_module("mnemosyne_hermes")
            importlib.import_module("mnemosyne")
        except (ImportError, OSError):
            return False
        return True

    def _discover_schemas(self) -> dict[str, dict[str, Any]]:
        if self._schemas:
            return self._schemas
        try:
            tools_module = importlib.import_module("mnemosyne_hermes.tools")
            raw = tools_module.ALL_TOOL_SCHEMAS
            discovered = {
                item.get("name"): item
                for item in raw
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            }
            selected = [discovered.get(name) for name in sorted(ALLOWED_TOOLS)]
            if any(item is None for item in selected):
                raise _ProviderInvariantError("reviewed_tool_missing")
            self._schema_hash = hashlib.sha256(
                _canonical_json(selected).encode("utf-8")
            ).hexdigest()
            version = MNEMOSYNE_HERMES_VERSION
            try:
                version = importlib.metadata.version("mnemosyne-hermes")
            except importlib.metadata.PackageNotFoundError:
                pass
            fixture_key = (version, ",".join(ALLOWED_TOOLS))
            if self._schema_hash != REVIEWED_SCHEMA_HASHES.get(fixture_key):
                raise _ProviderInvariantError("reviewed_schema_drift")
            self._schemas = {name: discovered[name] for name in ALLOWED_TOOLS}
            self._schema_error = ""
            return self._schemas
        except BaseException as exc:  # noqa: BLE001 - schema faults fail closed
            self._schema_error = _safe_reason(exc)
            self._schemas = {}
            return {}

    def _configuration(
        self, kwargs: dict[str, Any]
    ) -> tuple[Path | None, Path | None, str | None, str | None]:
        hermes_value = kwargs.get("hermes_home")
        context = kwargs.get("agent_context")
        if not isinstance(hermes_value, str) or not hermes_value:
            return None, None, None, "hermes_home_required"
        if not isinstance(context, str) or not context:
            return None, None, None, "agent_context_required"
        identity = kwargs.get("agent_identity")
        if not isinstance(identity, str) or not _PROFILE_KEY_RE.fullmatch(identity):
            return None, None, None, "profile_identity_invalid"
        if identity.lower() in {"default", "none", "primary"}:
            return None, None, None, "profile_identity_not_immutable"
        try:
            hermes_home = Path(hermes_value).expanduser()
            if not hermes_home.is_absolute():
                return None, None, None, "hermes_home_not_absolute"
            root_value = kwargs.get("profile_root") or hermes_value
            root = Path(str(root_value)).expanduser()
            if not root.is_absolute():
                return None, None, None, "profile_root_not_absolute"
            root = root.resolve(strict=False)
            hermes_home = hermes_home.resolve(strict=False)
            memory_config = _profile_memory_config(hermes_home)
            configured_provider = memory_config.get("provider", "allies_mnemosyne")
            if configured_provider != "allies_mnemosyne":
                return None, None, None, "memory_provider_invalid"
            configured_policy = memory_config.get("policy_version", POLICY_VERSION)
            if configured_policy != POLICY_VERSION:
                return None, None, None, "memory_policy_version_invalid"
            mode = kwargs.get(
                "memory_mode",
                kwargs.get("mode", memory_config.get("mode", DEFAULT_MODE)),
            )
            if mode not in MODES:
                return None, None, None, "memory_mode_invalid"
            if not _under(hermes_home, root):
                return None, None, None, "hermes_home_outside_profile"
            memory_root = (root / "mnemosyne").resolve(strict=False)
            if not _under(memory_root, root):
                return None, None, None, "memory_root_outside_profile"
            if (
                kwargs.get(
                    "profile_isolation", memory_config.get("profile_isolation", True)
                )
                is not True
            ):
                return None, None, None, "profile_isolation_required"
            if kwargs.get("shared_surface_read", False) is not False:
                return None, None, None, "shared_surface_forbidden"
            requested = kwargs.get(
                "memory_tool_allowlist",
                kwargs.get("tools", memory_config.get("tools", [])),
            )
            if requested is None:
                requested = []
            if not isinstance(requested, (list, tuple, set)):
                return None, None, None, "memory_tool_allowlist_invalid"
            selected_tools = tuple(sorted({str(item) for item in requested}))
            if not set(selected_tools).issubset(_ALLOWED_TOOL_SET):
                return None, None, None, "memory_tool_not_approved"
            if mode == DEFAULT_MODE:
                selected_tools = ()
            self._mode = mode
            self._tools = selected_tools
            return root, memory_root, identity, None
        except (OSError, TypeError, ValueError) as exc:
            return None, None, None, _safe_reason(exc)

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self.shutdown()
        self._session_id = str(session_id or "")
        self._correlation_id = str(kwargs.get("correlation_id") or uuid.uuid4().hex)
        self._mode = DEFAULT_MODE
        self._tools = ()
        self._agent_context = str(kwargs.get("agent_context") or "")
        root, memory_root, identity, error = self._configuration(kwargs)
        if error or root is None or memory_root is None or identity is None:
            self._reason = error or "configuration_invalid"
            return
        self._profile_root = root
        self._profile_key = identity
        if self._agent_context.lower() in {"cron", "flush", "subagent", "background"}:
            self._reason = "context_skipped"
            return
        delegate: Any = None
        try:
            memory_data = memory_root / "data"
            memory_data.mkdir(parents=True, exist_ok=True)
            if not _under(memory_data.resolve(strict=False), root):
                raise _ProviderInvariantError("memory_data_outside_profile")
            with _INIT_ENV_LOCK:
                previous = {
                    key: os.environ.get(key)
                    for key in (
                        "HERMES_HOME",
                        "MNEMOSYNE_DATA_DIR",
                        "MNEMOSYNE_AUTO_SLEEP_ENABLED",
                        "MNEMOSYNE_SYNC_ROLES",
                        "MNEMOSYNE_BUSY_TIMEOUT_MS",
                    )
                }
                os.environ["HERMES_HOME"] = str(root)
                os.environ["MNEMOSYNE_DATA_DIR"] = str(memory_data)
                os.environ["MNEMOSYNE_AUTO_SLEEP_ENABLED"] = "0"
                os.environ["MNEMOSYNE_SYNC_ROLES"] = ""
                os.environ["MNEMOSYNE_BUSY_TIMEOUT_MS"] = str(
                    SQLITE_BUSY_TIMEOUT_MS
                )
                try:
                    module = importlib.import_module("mnemosyne_hermes")
                    provider_class = module.MnemosyneMemoryProvider
                    delegate = provider_class()
                    delegate.initialize(
                        self._session_id,
                        hermes_home=str(root),
                        agent_identity=identity,
                        agent_context=self._agent_context,
                        profile_isolation=True,
                        shared_surface_read=False,
                        shared_surface_path=str(memory_root / "shared" / "disabled.db"),
                        sync_roles=[],
                        auto_sleep=False,
                        skip_contexts=[],
                        default_scope="global",
                        tools=[],
                    )
                finally:
                    for key, value in previous.items():
                        if value is None:
                            os.environ.pop(key, None)
                        else:
                            os.environ[key] = value
            self._delegate = delegate
            # Defend against provider config precedence re-enabling unsafe hooks.
            for attribute, value in (
                ("_profile_isolation_enabled", True),
                ("_shared_surface_read", False),
                ("_sync_roles", set()),
                ("_auto_sleep_enabled", False),
                ("_skip_contexts", set()),
            ):
                if hasattr(delegate, attribute):
                    setattr(delegate, attribute, value)
            beam = getattr(delegate, "_beam", None)
            candidate = getattr(beam, "db_path", None) if beam is not None else None
            if candidate is None:
                candidate = getattr(delegate, "_db_path", None)
            if beam is None or candidate is None:
                raise _ProviderInvariantError("mnemosyne_database_unavailable")
            connection = getattr(beam, "conn", None)
            if connection is None:
                raise _ProviderInvariantError(
                    "mnemosyne_database_connection_unavailable"
                )
            connection.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            db_path = Path(candidate).resolve(strict=False)
            profile_real = root.resolve(strict=False)
            if not _under(db_path, profile_real):
                raise _ProviderInvariantError("mnemosyne_database_outside_profile")
            if identity.lower() not in {part.lower() for part in db_path.parts}:
                raise _ProviderInvariantError("mnemosyne_database_not_profile_keyed")
            if getattr(delegate, "_surface_beam", None) is not None:
                raise _ProviderInvariantError("shared_surface_initialized")
            self._db_path = db_path
            if self._mode == "narrow_tools" and not self._discover_schemas():
                raise _ProviderInvariantError(
                    self._schema_error or "reviewed_schema_drift"
                )
            self._available = True
            self._reason = "ready"
        except BaseException as exc:  # noqa: BLE001 - lifecycle faults fail soft
            if delegate is not None:
                _invoke(delegate.shutdown)
            self._available = False
            self._reason = _safe_reason(exc)
            self._delegate = None
            self._db_path = None
            logger.warning("Mnemosyne provider unavailable: %s", self._reason)

    def system_prompt_block(self) -> str:
        if not self._available:
            return "# Allies Memory\nStatus: temporarily unavailable; continue without durable memory."
        if self._mode == DEFAULT_MODE:
            return (
                "# Allies Memory\n"
                "Relevant durable context may be supplied silently. Automatic conversation capture "
                "is disabled; only explicit, policy-approved memory requests can write."
            )
        return (
            "# Allies Memory\n"
            "Use the approved durable-memory tools only for explicit, policy-approved facts. "
            "Automatic conversation capture and consolidation are disabled."
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not self._available or self._delegate is None:
            return ""
        if (
            not isinstance(query, str)
            or not query.strip()
            or _text_bytes(query) > MAX_QUERY_BYTES
        ):
            return ""
        status, value = _invoke(
            self._delegate.prefetch,
            query,
            session_id=session_id or self._session_id,
        )
        if status != "ok" or not isinstance(value, str):
            return ""
        if _text_bytes(value) > MAX_RESULT_BYTES:
            return ""
        return value

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        # Background work can mutate provider state and outlive profile fencing.
        return None

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        # Alpha deliberately has no implicit transcript persistence.
        return None

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        if not self._available or self._mode == DEFAULT_MODE:
            return []
        schemas = self._discover_schemas()
        return [schemas[name] for name in self._tools if name in schemas]

    def has_tool(self, tool_name: str) -> bool:
        return bool(tool_name in self._tools and tool_name in self.get_tool_names())

    def get_tool_names(self) -> tuple[str, ...]:
        if not self._available or self._mode == DEFAULT_MODE:
            return ()
        schemas = self._discover_schemas()
        return tuple(name for name in self._tools if name in schemas)

    def _retention_error(self, name: str, arguments: dict[str, Any]) -> str | None:
        if name not in _WRITE_TOOLS:
            return None
        if _contains_forbidden(arguments):
            return "retention_policy_rejected"
        if name == "mnemosyne_remember":
            if arguments.get("scope", "global") != "global":
                return "non_durable_scope_rejected"
            if arguments.get("extract") or arguments.get("extract_entities"):
                return "implicit_extraction_disabled"
            source = str(arguments.get("source", "user")).lower()
            if source not in _SAFE_SOURCES:
                return "retention_source_rejected"
            if arguments.get("veracity") == "inferred":
                return "inferred_memory_rejected"
            metadata = arguments.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                return "metadata_object_required"
        content = arguments.get("content", arguments.get("body"))
        if content is not None and (
            not isinstance(content, str) or not content.strip()
        ):
            return "memory_content_required"
        if content is not None and _text_bytes(content) > MAX_RECORD_BYTES:
            return "memory_record_too_large"
        return None

    def _database_guard(self) -> str | None:
        if self._db_path is None:
            return "database_unavailable"
        try:
            if (
                self._db_path.exists()
                and self._db_path.stat().st_size > MAX_DATABASE_BYTES
            ):
                return "database_quota_exceeded"
        except (OSError, ValueError) as exc:
            return _safe_reason(exc)
        return None

    def handle_tool_call(
        self, tool_name: str, args: dict[str, Any], **kwargs: Any
    ) -> str:
        if not self._available or self._delegate is None:
            return _json_result("memory_unavailable", self._reason)
        if self._mode == DEFAULT_MODE or not self.has_tool(tool_name):
            return _json_result("tool_rejected", "tool_not_advertised")
        schema = self._schemas.get(tool_name)
        if schema is None:
            return _json_result("tool_rejected", "reviewed_schema_drift")
        validation_error = _validate_args(schema, args)
        if validation_error:
            return _json_result("tool_rejected", validation_error)
        retention_error = self._retention_error(tool_name, args)
        if retention_error:
            return _json_result("tool_rejected", retention_error)
        if tool_name in _WRITE_TOOLS:
            quota_error = self._database_guard()
            if quota_error:
                return _json_result("tool_rejected", quota_error)
        delegated_args = dict(args)
        if tool_name == "mnemosyne_remember":
            delegated_args["scope"] = "global"
        status, value = _invoke(
            self._delegate.handle_tool_call,
            tool_name,
            delegated_args,
            session_id=kwargs.get("session_id") or self._session_id,
        )
        if status != "ok":
            return _json_result("memory_unavailable", status)
        if not isinstance(value, str) or _text_bytes(value) > MAX_RESULT_BYTES:
            return _json_result("tool_error", "malformed_or_oversized_result")
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return _json_result("tool_error", "malformed_result")
        if not isinstance(parsed, (dict, list)):
            return _json_result("tool_error", "result_shape_invalid")
        return value

    def on_turn_start(self, turn_number: int, message: str, **kwargs: Any) -> None:
        self._turn_count = int(turn_number or 0)

    def on_session_end(self, messages: list[dict[str, Any]]) -> None:
        # Stock on_session_end launches consolidation; alpha must not do that.
        return None

    def on_session_switch(self, new_session_id: str, **kwargs: Any) -> None:
        self._session_id = str(new_session_id or "")

    def on_pre_compress(self, messages: list[dict[str, Any]]) -> str:
        return ""

    def on_delegation(self, task: str, result: str, **kwargs: Any) -> None:
        return None

    def on_memory_write(
        self, action: str, target: str, content: str, **kwargs: Any
    ) -> None:
        return None

    def get_config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "mode",
                "description": "Allies memory mode.",
                "choices": sorted(MODES),
                "default": DEFAULT_MODE,
            },
            {
                "key": "tools",
                "description": "Explicit approved tools for narrow_tools mode.",
                "default": [],
            },
        ]

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "provider_version": PROVIDER_VERSION,
            "mnemosyne_hermes": MNEMOSYNE_HERMES_VERSION,
            "policy_version": POLICY_VERSION,
            "available": self._available,
            "reason": self._reason,
            "mode": self._mode,
            "profile_keyed": bool(self._profile_key),
            "profile_db_root": str(self._db_path.parent) if self._db_path else None,
            "shared_surface": False,
            "sync_roles": [],
            "auto_sleep": False,
            "tools": list(self.get_tool_names()),
            "schema_hash": self._schema_hash or None,
        }

    def shutdown(self) -> None:
        delegate, self._delegate = self._delegate, None
        if delegate is not None:
            status, _ = _invoke(delegate.shutdown)
            if status != "ok":
                logger.warning("Mnemosyne shutdown fault: %s", status)
        self._available = False
        self._db_path = None
        self._schemas = {}
        self._schema_hash = ""
        self._schema_error = ""
        self._reason = "shutdown"


def register_memory_provider(ctx: Any) -> None:
    """Pinned Hermes memory-plugin registration hook."""

    ctx.register_memory_provider(AlliesMnemosyneProvider())


def register(ctx: Any) -> None:
    register_memory_provider(ctx)
