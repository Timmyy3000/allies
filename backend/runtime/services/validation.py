from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from runtime.exceptions import RuntimeValidationError

MAX_EXECUTION_PAYLOAD_BYTES = 64 * 1024
MAX_EVENT_PAYLOAD_BYTES = 16 * 1024
MAX_RECEIPT_BYTES = 8 * 1024
MAX_FAILURE_CODE_LENGTH = 64
MAX_STREAM_ID_LENGTH = 255
MAX_JSON_NESTING_DEPTH = 64
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json_bytes(payload: Any) -> bytes:
    """Return the canonical JSON representation used for payload identity."""

    if type(payload) is not dict:
        raise RuntimeValidationError("payload must be a JSON object")
    _validate_json_value(payload, depth=1)
    try:
        return json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RuntimeValidationError("payload must contain JSON values") from exc


def digest_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _validate_json_value(value: Any, *, depth: int) -> None:
    value_type = type(value)
    if value_type in {type(None), bool, int, float, str}:
        return
    if depth > MAX_JSON_NESTING_DEPTH:
        raise RuntimeValidationError(
            f"payload exceeds the {MAX_JSON_NESTING_DEPTH} level nesting limit"
        )
    if value_type is list:
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if value_type is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise RuntimeValidationError("payload object keys must be strings")
            _validate_json_value(item, depth=depth + 1)
        return
    raise RuntimeValidationError(
        "payload must contain only JSON objects, arrays, strings, numbers, booleans, or null"
    )


def validate_object_payload(payload: Any, *, max_bytes: int) -> dict[str, Any]:
    encoded = canonical_json_bytes(payload)
    if len(encoded) > max_bytes:
        raise RuntimeValidationError(f"payload exceeds the {max_bytes} byte limit")
    return payload


def digest_lease_token(token: str) -> str:
    if not isinstance(token, str) or not token:
        raise RuntimeValidationError("lease token must be a non-empty string")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_token_digest(token_digest: str) -> str:
    if not isinstance(token_digest, str) or not _DIGEST_RE.fullmatch(token_digest):
        raise RuntimeValidationError(
            "token_digest must be a lowercase SHA-256 hex digest"
        )
    return token_digest


def validate_nonempty(value: str, name: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise RuntimeValidationError(
            f"{name} must be a non-empty string of at most {max_length} characters"
        )
    return value


def validate_bounded_receipt(receipt: Any) -> dict[str, Any]:
    """Validate the small, canonical receipt persisted for response replay."""

    value = validate_object_payload(receipt, max_bytes=MAX_RECEIPT_BYTES)
    code = value.get("code")
    validate_nonempty(code, "receipt.code", max_length=MAX_FAILURE_CODE_LENGTH)
    summary_ref = value.get("summary_ref")
    if summary_ref is not None:
        validate_nonempty(
            summary_ref,
            "receipt.summary_ref",
            max_length=255,
        )
    return value
