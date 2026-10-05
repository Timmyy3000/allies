"""Sanitized, reviewable proof evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class VolumeVisibility(StrEnum):
    ABSENT = "absent"
    READ_ONLY = "read-only"
    READ_WRITE = "read-write"


_SENSITIVE_KEY = re.compile(
    r"(?:secret|credential|authorization|bearer|token|password|api[_-]?key)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_PRIVATE_URL = re.compile(
    r"https?://(?:127\.0\.0\.1|localhost|0\.0\.0\.0)(?::\d+)?[^\s]*", re.IGNORECASE
)


def sanitize_value(value: Any, *, key: str = "") -> Any:
    """Return JSON-like evidence with secrets, URLs, and raw provider output removed."""

    if _SENSITIVE_KEY.search(key):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {str(k): sanitize_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_value(item, key=key) for item in value]
    if isinstance(value, str):
        value = _BEARER.sub("<redacted>", value)
        value = _PRIVATE_URL.sub("<private-url>", value)
        return value[:512]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)[:128]


@dataclass(frozen=True, slots=True)
class EvidenceCheck:
    name: str
    status: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceReport:
    run_id: str
    mode: str
    hermes_image: str
    runtime_image: str
    checks: tuple[EvidenceCheck, ...] = field(default_factory=tuple)
    volume_visibility: VolumeVisibility = VolumeVisibility.ABSENT
    cleanup: str = "complete"
    source_commit: str | None = None
    profile_proof_mode: str = "fake"
    resources: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "run_id": self.run_id,
            "mode": self.mode,
            "images": {"hermes": self.hermes_image, "runtime": self.runtime_image},
            "checks": [asdict(check) for check in self.checks],
            "volume_visibility": self.volume_visibility.value,
            "cleanup": self.cleanup,
            "profile_proof_mode": self.profile_proof_mode,
        }
        if self.resources:
            payload["resources"] = dict(self.resources)
        if self.source_commit:
            payload["source_commit"] = self.source_commit
        return sanitize_value(payload)


def check(name: str, status: str, detail: str | None = None) -> EvidenceCheck:
    if status not in {"pass", "fail", "skip"}:
        raise ValueError("evidence check status must be pass, fail, or skip")
    return EvidenceCheck(name=name, status=status, detail=detail)


def assert_sanitized(payload: Mapping[str, Any]) -> None:
    """Raise if a report still contains obvious private material."""

    rendered = repr(payload)
    if re.search(r"(?i)bearer\s+|https?://(?:127\.0\.0\.1|localhost)", rendered):
        raise ValueError("evidence contains a credential or private URL")


__all__ = [
    "EvidenceCheck",
    "EvidenceReport",
    "VolumeVisibility",
    "assert_sanitized",
    "check",
    "sanitize_value",
]
