import struct
import zlib
from io import BytesIO

from PIL import Image

from files.previews import MAX_TEXT_PREVIEW_BYTES, build_preview


def image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (20, 10), (30, 60, 90)).save(output, format="JPEG")
    return output.getvalue()


def test_raster_preview_is_reencoded_without_original_bytes():
    preview = build_preview(
        media_type="image/jpeg", stream=BytesIO(image_bytes()), size=100
    )
    assert preview.kind == "image"
    assert preview.media_type == "image/png"
    assert isinstance(preview.content, bytes)
    assert preview.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_text_preview_escapes_markup_and_marks_truncation():
    data = b"<script>unsafe</script>" + b"a" * MAX_TEXT_PREVIEW_BYTES
    preview = build_preview(
        media_type="text/html", stream=BytesIO(data), size=len(data)
    )
    assert preview.kind == "text"
    assert "&lt;script&gt;" in preview.content
    assert preview.truncated is True
    assert "Download the full file" in preview.content


def test_pdf_and_heif_previews_are_safely_unsupported():
    pdf = build_preview(
        media_type="application/pdf", stream=BytesIO(b"%PDF-1.7"), size=8
    )
    heif = build_preview(media_type="image/heif", stream=BytesIO(b"bytes"), size=5)
    assert pdf.safe_error_code == "pdf_preview_unsupported"
    assert heif.safe_error_code == "heif_preview_unsupported"


def test_large_image_header_returns_safe_fallback():
    payload = struct.pack(">2I5B", 10_000, 10_000, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + payload
    data = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(payload))
        + chunk
        + struct.pack(">I", zlib.crc32(chunk))
        + b"\x00\x00\x00\x00IDAT\x35\xaf\x06\x1e"
    )
    preview = build_preview(
        media_type="image/png", stream=BytesIO(data), size=len(data)
    )
    assert preview.safe_error_code == "image_too_large"
