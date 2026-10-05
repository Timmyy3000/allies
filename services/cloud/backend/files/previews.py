"""Inert private-file preview transformations."""

from __future__ import annotations

import html
import io
import warnings
from dataclasses import dataclass
from typing import BinaryIO

from PIL import Image

MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_PREVIEW_EDGE = 2_048
MAX_IMAGE_PREVIEW_BYTES = 10_000_000
MAX_TEXT_PREVIEW_BYTES = 1_000_000

_RASTER_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def is_text_media_type(media_type: str) -> bool:
    return media_type.startswith("text/") or media_type in {
        "application/json",
        "application/xml",
        "application/yaml",
        "application/toml",
    }


@dataclass(frozen=True, slots=True)
class Preview:
    kind: str
    media_type: str | None
    content: bytes | str | None
    truncated: bool = False
    safe_error_code: str | None = None


def build_preview(*, media_type: str, stream: BinaryIO, size: int) -> Preview:
    if media_type in _RASTER_TYPES:
        return raster_preview(stream)
    if is_text_media_type(media_type):
        return text_preview(stream, size=size)
    if media_type == "application/pdf":
        return _unsupported("pdf_preview_unsupported")
    if media_type in {"image/heic", "image/heif"}:
        return _unsupported("heif_preview_unsupported")
    return _unsupported("preview_not_supported")


def raster_preview(stream: BinaryIO) -> Preview:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(stream) as image:
                width, height = image.size
                if width * height > MAX_IMAGE_PIXELS:
                    return _unsupported("image_too_large")
                image.seek(0)
                image.load()
                preview = image.convert("RGB")
                preview.thumbnail(
                    (MAX_IMAGE_PREVIEW_EDGE, MAX_IMAGE_PREVIEW_EDGE),
                    Image.Resampling.LANCZOS,
                )
                output = io.BytesIO()
                preview.save(output, format="PNG", optimize=True)
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        return _unsupported("image_too_large")
    except (OSError, ValueError):
        return _unsupported("image_preview_invalid")
    data = output.getvalue()
    if len(data) > MAX_IMAGE_PREVIEW_BYTES:
        return _unsupported("image_preview_too_large")
    return Preview("image", "image/png", data)


def text_preview(stream: BinaryIO, *, size: int) -> Preview:
    if size < 1:
        return _unsupported("text_preview_invalid")
    raw = stream.read(MAX_TEXT_PREVIEW_BYTES)
    if not isinstance(raw, bytes) or len(raw) > MAX_TEXT_PREVIEW_BYTES:
        return _unsupported("text_preview_invalid")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        if error.end != len(raw):
            return _unsupported("text_preview_invalid")
        try:
            text = raw[: error.start].decode("utf-8")
        except UnicodeDecodeError:
            return _unsupported("text_preview_invalid")
    truncated = size > MAX_TEXT_PREVIEW_BYTES
    escaped = html.escape(text, quote=True)
    if truncated:
        escaped += "\n\n[Preview truncated. Download the full file.]"
    return Preview("text", "text/html; charset=utf-8", escaped, truncated)


def _unsupported(code: str) -> Preview:
    return Preview("none", None, None, safe_error_code=code)
