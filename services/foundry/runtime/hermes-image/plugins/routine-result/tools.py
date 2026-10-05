"""The narrow, side-effect-free Allies routine result tool."""

from __future__ import annotations

import json
from typing import Any

_OUTCOMES = frozenset({"changed", "unchanged", "failed"})
_MAX_TEXT_BYTES = 16 * 1024
_MAX_REFERENCES = 32
_MAX_LABEL_BYTES = 255
_MAX_URL_BYTES = 2048

ROUTINE_RESULT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "allies_routine_result",
        "description": (
            "Report the final typed result of this scheduled routine. Call "
            "exactly once before ending the routine; this call is authoritative. "
            "Use failed when the requested work could not be completed."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": ["changed", "unchanged", "failed"],
                },
                "text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": _MAX_TEXT_BYTES // 4,
                    "description": (
                        "Concise result, without NUL characters. The 16384 UTF-8 byte "
                        "budget allows at most 4096 characters for any Unicode text."
                    ),
                },
                "references": {
                    "type": "array",
                    "maxItems": _MAX_REFERENCES,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "label": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": _MAX_LABEL_BYTES // 4,
                                "description": (
                                    "Source label without NUL characters; at most 255 "
                                    "UTF-8 bytes (63 characters for any Unicode text)."
                                ),
                            },
                            "url": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": _MAX_URL_BYTES // 4,
                                "description": (
                                    "HTTP(S) URL without NUL characters; at most 2048 "
                                    "UTF-8 bytes (512 characters for any Unicode text)."
                                ),
                                "pattern": "^https?://",
                            },
                        },
                        "required": ["label", "url"],
                    },
                },
            },
            "required": ["outcome", "text", "references"],
        },
    },
}


def _validate(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict) or set(args) != {"outcome", "text", "references"}:
        raise ValueError("result fields were invalid")
    outcome = args.get("outcome")
    text = args.get("text")
    references = args.get("references")
    if outcome not in _OUTCOMES:
        raise ValueError("result outcome was invalid")
    if (
        not isinstance(text, str)
        or not text
        or "\x00" in text
        or len(text.encode("utf-8")) > _MAX_TEXT_BYTES
    ):
        raise ValueError("result text was invalid")
    if not isinstance(references, list) or len(references) > _MAX_REFERENCES:
        raise ValueError("result references were invalid")
    for reference in references:
        if not isinstance(reference, dict) or set(reference) != {"label", "url"}:
            raise ValueError("result references were invalid")
        label = reference.get("label")
        url = reference.get("url")
        if (
            not isinstance(label, str)
            or not 1 <= len(label.encode("utf-8")) <= _MAX_LABEL_BYTES
            or "\x00" in label
            or not isinstance(url, str)
            or not 1 <= len(url.encode("utf-8")) <= _MAX_URL_BYTES
            or "\x00" in url
            or not url.startswith(("http://", "https://"))
        ):
            raise ValueError("result references were invalid")
    return {
        "outcome": outcome,
        "text": text,
        "references": [
            {"label": item["label"], "url": item["url"]} for item in references
        ],
    }


def handle_routine_result(args: dict, **_kwargs: Any) -> str:
    """Accept only the exact typed shape; never perform a side effect."""

    try:
        _validate(args)
    except (TypeError, UnicodeError, ValueError):
        return json.dumps(
            {"status": "rejected", "reason": "invalid routine result"},
            separators=(",", ":"),
        )
    return '{"status":"accepted"}'
