"""Configuration for the small Allies runtime boundary.

The runtime intentionally has no secret store.  Foundry passes an opaque
credential reference and a resolver owned by the process that actually knows
how to retrieve the value.  Keeping that distinction in the type makes it
hard to accidentally put a bearer token in settings, evidence, or logs.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Self
from urllib.parse import urlsplit

DEFAULT_HERMES_ORIGIN = "http://127.0.0.1:8642"
DEFAULT_FOUNDRY_ORIGIN = "http://127.0.0.1:8000"
DEFAULT_FOUNDRY_CREDENTIAL_REF = "file:///run/secrets/foundry-runtime-token"
DEFAULT_VOLUME_ROOT = "/opt/data"
DEFAULT_MARKER_PATH = "/opt/data/.allies-proof/fnd-004"
DEFAULT_HERMES_IMAGE = (
    "nousresearch/hermes-agent@sha256:"
    "b6f18532e2c082ef6686c659fc222427e41fde3eed08aa058411f0ea5ab705ca"
)
PINNED_HERMES_SOURCE_COMMIT = "36cb5ae5530a75def7df3195e49b7a4aa2add482"
MAX_TIMEOUT_SECONDS = 180.0
MAX_PROOF_SLOTS = 32
MAX_WIDE_EVENT_BYTES = 16 * 1024
MAX_WIDE_EVENT_QUEUE_SIZE = 4096


class SettingsError(ValueError):
    """Raised when untrusted runtime configuration is unsafe or malformed."""


def _observability_bool(env: Mapping[str, object], name: str, default: bool) -> bool:
    value = env.get(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"0", "false", "no", "off"}:
        return False
    raise SettingsError(f"{name} must be a boolean")


def _observability_float(
    env: Mapping[str, object], name: str, default: float, *, maximum: float
) -> float:
    try:
        value = float(env.get(name, default))
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{name} must be a number") from exc
    if not 0 <= value <= maximum:
        raise SettingsError(f"{name} must be between 0 and {maximum:g}")
    return value


def _observability_int(
    env: Mapping[str, object], name: str, default: int, *, minimum: int, maximum: int
) -> int:
    try:
        value = int(env.get(name, default))
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise SettingsError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True, slots=True)
class WideEventSettings:
    enabled: bool = True
    success_sample_rate: float = 1.0
    slow_ms: float = 1000.0
    max_bytes: int = 16 * 1024
    sink_enabled: bool = False
    max_queue_size: int = 128

    @classmethod
    def from_env(cls, env: Mapping[str, object]) -> WideEventSettings:
        return cls(
            enabled=_observability_bool(env, "ALLIES_WIDE_EVENTS_ENABLED", True),
            success_sample_rate=_observability_float(
                env,
                "ALLIES_WIDE_EVENTS_SUCCESS_SAMPLE_RATE",
                1.0,
                maximum=1.0,
            ),
            slow_ms=_observability_float(
                env, "ALLIES_WIDE_EVENTS_SLOW_MS", 1000.0, maximum=86_400_000.0
            ),
            max_bytes=_observability_int(
                env,
                "ALLIES_WIDE_EVENTS_MAX_BYTES",
                16 * 1024,
                minimum=512,
                maximum=MAX_WIDE_EVENT_BYTES,
            ),
            sink_enabled=_observability_bool(
                env, "ALLIES_WIDE_EVENTS_SINK_ENABLED", False
            ),
            max_queue_size=_observability_int(
                env,
                "ALLIES_WIDE_EVENTS_MAX_QUEUE_SIZE",
                128,
                minimum=1,
                maximum=MAX_WIDE_EVENT_QUEUE_SIZE,
            ),
        )


_REFERENCE_PATTERN = re.compile(
    r"^[a-z][a-z0-9+.-]{1,31}://[^\s]{1,191}$", re.IGNORECASE
)
_DIGEST_PATTERN = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$", re.IGNORECASE)


class CredentialReference(str):
    """An opaque reference, never the credential value itself.

    A reference is still represented as a string so it can be handed to an
    injected resolver.  ``repr`` deliberately avoids echoing even the
    reference's identifying path into exceptions and debug output.
    """

    def __new__(cls, value: str) -> Self:
        if not isinstance(value, str) or not _REFERENCE_PATTERN.fullmatch(
            value.strip()
        ):
            raise SettingsError("HERMES_CREDENTIAL_REF must be an opaque URI reference")
        lowered = value.lower()
        # These forms are values, not references.  They are rejected before a
        # resolver is ever called, preventing accidental plaintext config.
        if lowered.startswith(("bearer ", "token=", "key=", "sk-", "api_key=")):
            raise SettingsError(
                "HERMES_CREDENTIAL_REF must not contain a credential value"
            )
        return str.__new__(cls, value.strip())

    def __repr__(self) -> str:  # pragma: no cover - exercised through logging tests
        return "CredentialReference(<redacted>)"


def validate_image_reference(value: str, *, field: str = "image") -> str:
    """Require an immutable OCI image reference (a digest, never ``latest``)."""

    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value.strip()):
        raise SettingsError(
            f"{field} must be an immutable image@sha256:digest reference"
        )
    return value.strip()


def _float_setting(env: Mapping[str, object], name: str, default: float) -> float:
    raw = env.get(name, default)
    try:
        result = float(raw)
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{name} must be a number") from exc
    if not 0 < result <= MAX_TIMEOUT_SECONDS:
        raise SettingsError(
            f"{name} must be greater than 0 and at most {MAX_TIMEOUT_SECONDS:g}s"
        )
    return result


def _int_setting(env: Mapping[str, object], name: str, default: int) -> int:
    raw = env.get(name, default)
    try:
        result = int(raw)
    except (TypeError, ValueError) as exc:
        raise SettingsError(f"{name} must be an integer") from exc
    if not 2 <= result <= MAX_PROOF_SLOTS:
        raise SettingsError(f"{name} must be between 2 and {MAX_PROOF_SLOTS}")
    return result


def _loopback_origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise SettingsError("HERMES_ORIGIN is not a valid URL") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise SettingsError("HERMES_ORIGIN must be the private http://127.0.0.1 origin")
    try:
        port = parsed.port or 8642
    except ValueError as exc:
        raise SettingsError("HERMES_ORIGIN must use a valid port") from exc
    if port != 8642:
        raise SettingsError("HERMES_ORIGIN must use Hermes port 8642")
    return f"http://127.0.0.1:{port}"


def _foundry_origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise SettingsError("FOUNDRY_ORIGIN is not a valid URL") from exc
    is_test_loopback = parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
    if (
        (parsed.scheme != "https" and not is_test_loopback)
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise SettingsError(
            "FOUNDRY_ORIGIN must be an HTTPS origin or the test loopback origin"
        )
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    suffix = f":{port}" if port is not None else ""
    return f"{parsed.scheme}://{host}{suffix}"


def _marker_path(value: str, *, volume_root: str) -> str:
    path = PurePosixPath(value)
    root = PurePosixPath(volume_root)
    if not path.is_absolute() or ".." in path.parts:
        raise SettingsError("VOLUME_MARKER_PATH must be an absolute path without '..'")
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise SettingsError("VOLUME_MARKER_PATH must remain under /opt/data") from exc
    return str(path)


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Validated, reproducible settings for one runtime process."""

    hermes_origin: str = DEFAULT_HERMES_ORIGIN
    foundry_origin: str = DEFAULT_FOUNDRY_ORIGIN
    foundry_credential_ref: CredentialReference = field(
        default_factory=lambda: CredentialReference(DEFAULT_FOUNDRY_CREDENTIAL_REF)
    )
    credential_ref: CredentialReference = field(
        default_factory=lambda: CredentialReference("ref://hermes/api")
    )
    request_timeout: float = 5.0
    stream_timeout: float = 15.0
    proof_slots: int = 2
    volume_root: str = DEFAULT_VOLUME_ROOT
    marker_path: str = DEFAULT_MARKER_PATH
    hermes_image: str = DEFAULT_HERMES_IMAGE
    runtime_image: str | None = None
    source_commit: str = PINNED_HERMES_SOURCE_COMMIT
    wide_events: WideEventSettings = field(default_factory=WideEventSettings)


def load_settings(env: Mapping[str, object] | None = None) -> RuntimeSettings:
    """Load and validate settings from an environment-like mapping.

    Only the opaque ``HERMES_CREDENTIAL_REF`` is accepted.  A resolver is
    passed separately to :class:`HermesClient`; no plaintext key is loaded
    into this object.
    """

    values: Mapping[str, object] = env or {}
    origin = _loopback_origin(str(values.get("HERMES_ORIGIN", DEFAULT_HERMES_ORIGIN)))
    foundry_origin = _foundry_origin(
        str(values.get("FOUNDRY_ORIGIN", DEFAULT_FOUNDRY_ORIGIN))
    )
    foundry_ref = CredentialReference(
        str(
            values.get(
                "FOUNDRY_RUNTIME_CREDENTIAL_REF",
                DEFAULT_FOUNDRY_CREDENTIAL_REF,
            )
        )
    )
    raw_ref = values.get("HERMES_CREDENTIAL_REF", "ref://hermes/api")
    ref = CredentialReference(str(raw_ref))
    volume_root = str(values.get("VOLUME_ROOT", DEFAULT_VOLUME_ROOT))
    root = PurePosixPath(volume_root)
    if not root.is_absolute() or ".." in root.parts:
        raise SettingsError("VOLUME_ROOT must be an absolute path without '..'")
    marker = _marker_path(
        str(values.get("VOLUME_MARKER_PATH", DEFAULT_MARKER_PATH)),
        volume_root=str(root),
    )
    hermes_image = validate_image_reference(
        str(values.get("HERMES_IMAGE", DEFAULT_HERMES_IMAGE)), field="HERMES_IMAGE"
    )
    runtime_image = values.get("RUNTIME_IMAGE")
    if runtime_image:
        runtime_image = validate_image_reference(
            str(runtime_image), field="RUNTIME_IMAGE"
        )
    source_commit = str(
        values.get("HERMES_SOURCE_COMMIT", PINNED_HERMES_SOURCE_COMMIT)
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise SettingsError("HERMES_SOURCE_COMMIT must be a 40-character commit")
    wide_events = WideEventSettings.from_env(values)
    return RuntimeSettings(
        hermes_origin=origin,
        foundry_origin=foundry_origin,
        foundry_credential_ref=foundry_ref,
        credential_ref=ref,
        request_timeout=_float_setting(values, "HERMES_REQUEST_TIMEOUT", 5.0),
        stream_timeout=_float_setting(values, "HERMES_STREAM_TIMEOUT", 15.0),
        proof_slots=_int_setting(values, "PROOF_SLOTS", 2),
        volume_root=str(root),
        marker_path=marker,
        hermes_image=hermes_image,
        runtime_image=runtime_image,
        source_commit=source_commit,
        wide_events=wide_events,
    )


__all__ = [
    "DEFAULT_FOUNDRY_CREDENTIAL_REF",
    "DEFAULT_FOUNDRY_ORIGIN",
    "DEFAULT_HERMES_ORIGIN",
    "CredentialReference",
    "RuntimeSettings",
    "SettingsError",
    "WideEventSettings",
    "load_settings",
    "validate_image_reference",
]
