from __future__ import annotations

import struct
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from files.inspection import (
    CHUNK_BYTES,
    ClamAvClient,
    ScannerConfig,
    inspect_file,
    validate_file_type,
)

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)


class FakeTransport:
    def __init__(
        self, *, scan_response: str = "stream: OK", updated_at: datetime = NOW
    ):
        self.scan_response = scan_response
        self.updated_at = updated_at
        self.scanned_chunks: list[int] = []

    def version(self, *, timeout_seconds: float) -> str:
        assert timeout_seconds > 0
        return f"ClamAV 1.0/123/{self.updated_at.strftime('%a %b %d %H:%M:%S %Y')}"

    def scan(self, stream, *, timeout_seconds: float, chunk_bytes: int) -> str:
        assert timeout_seconds > 0
        while chunk := stream.read(chunk_bytes):
            self.scanned_chunks.append(len(chunk))
        return self.scan_response


class NonSeekable:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0

    def read(self, size: int = -1) -> bytes:
        end = len(self.data) if size < 0 else self.position + size
        result = self.data[self.position : end]
        self.position += len(result)
        return result

    def seek(self, offset: int) -> int:
        del offset
        raise OSError("stream cannot seek")


def scanner(transport: FakeTransport) -> ClamAvClient:
    return ClamAvClient(ScannerConfig(host="scanner.internal"), transport=transport)


def ooxml(*, macro: bool = False, encrypted: bool = False) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("_rels/.rels", "<Relationships />")
        archive.writestr("word/document.xml", "<document />")
        if macro:
            archive.writestr("word/vbaProject.bin", b"macro")
        if encrypted:
            archive.writestr("EncryptionInfo", b"encrypted")
    return output.getvalue()


def test_validation_rejects_magic_mismatch_and_invalid_utf8():
    assert (
        validate_file_type(
            name="report.png", stream=BytesIO(b"%PDF-1.7"), size=8
        ).safe_error_code
        == "type_mismatch"
    )
    assert (
        validate_file_type(
            name="notes.txt", stream=BytesIO(b"\xff"), size=1
        ).safe_error_code
        == "type_invalid"
    )


def test_validation_rejects_macro_and_encrypted_office_containers():
    macro = ooxml(macro=True)
    encrypted = ooxml(encrypted=True)
    assert (
        validate_file_type(
            name="report.docx", stream=BytesIO(macro), size=len(macro)
        ).safe_error_code
        == "office_macro"
    )
    assert (
        validate_file_type(
            name="report.docx", stream=BytesIO(encrypted), size=len(encrypted)
        ).safe_error_code
        == "office_encrypted"
    )


def test_inspection_scans_stream_in_bounded_chunks_and_requires_clean_verdict():
    data = b"a" * (CHUNK_BYTES * 2 + 3)
    transport = FakeTransport()
    result = inspect_file(
        name="notes.txt",
        source=BytesIO(data),
        size=len(data),
        scanner=scanner(transport),
        now=NOW,
    )
    assert result.accepted is True
    assert result.scanner_clean is True
    assert result.actual_size == len(data)
    assert result.sha256 == sha256(data).hexdigest()
    assert transport.scanned_chunks == [CHUNK_BYTES, CHUNK_BYTES, 3]


def test_inspection_spools_non_seekable_sources_without_changing_verdict():
    data = b"safe text"
    result = inspect_file(
        name="notes.txt",
        source=NonSeekable(data),
        size=len(data),
        scanner=scanner(FakeTransport()),
        now=NOW,
    )
    assert result.accepted is True


def test_legacy_office_requires_an_approved_parser():
    data = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    result = validate_file_type(name="old.doc", stream=BytesIO(data), size=len(data))
    assert result.safe_error_code == "office_legacy_unsupported"


def test_inspection_fails_closed_for_malware_and_definitions_older_than_a_week():
    data = b"safe text"
    malware = inspect_file(
        name="notes.txt",
        source=BytesIO(data),
        size=len(data),
        scanner=scanner(FakeTransport(scan_response="stream: EICAR FOUND")),
        now=NOW,
    )
    one_week_old = inspect_file(
        name="notes.txt",
        source=BytesIO(data),
        size=len(data),
        scanner=scanner(FakeTransport(updated_at=NOW - timedelta(days=7))),
        now=NOW,
    )
    stale = inspect_file(
        name="notes.txt",
        source=BytesIO(data),
        size=len(data),
        scanner=scanner(FakeTransport(updated_at=NOW - timedelta(days=7, seconds=1))),
        now=NOW,
    )
    assert malware.accepted is False
    assert malware.safe_error_code == "malware_detected"
    assert one_week_old.accepted is True
    assert stale.accepted is False
    assert stale.safe_error_code == "scanner_definitions_stale"


def test_scanner_deadline_fails_closed_before_a_scan_starts():
    clock = iter((0.0, 0.0, 61.0)).__next__
    result = ClamAvClient(
        ScannerConfig(host="scanner.internal"),
        transport=FakeTransport(),
        monotonic=clock,
    ).scan(BytesIO(b"safe text"), now=NOW)
    assert result.clean is False
    assert result.safe_error_code == "scanner_timeout"


def test_seekable_size_mismatch_stops_within_one_chunk():
    stream = BytesIO(b"a" * (CHUNK_BYTES * 20))
    result = validate_file_type(name="notes.txt", stream=stream, size=1)
    assert result.safe_error_code == "size_mismatch"
    assert stream.tell() <= CHUNK_BYTES


@pytest.mark.parametrize(
    "name", ["../evil.txt", "..\\evil.txt", "C:\\evil.txt", "C:evil.txt", "bad\n.txt"]
)
def test_validation_rejects_cross_platform_paths(name):
    assert not validate_file_type(name=name, stream=BytesIO(b"x"), size=1).accepted


@pytest.mark.parametrize(
    "response", ["arbitrary: OK", "stream: field: OK", "stream: OK extra"]
)
def test_scanner_rejects_malformed_clean_responses(response):
    result = scanner(FakeTransport(scan_response=response)).scan(
        BytesIO(b"safe"), now=NOW
    )
    assert not result.clean
    assert result.safe_error_code == "scanner_unavailable"


def test_ooxml_checks_local_headers_and_crc():
    data = bytearray(ooxml())
    data[:4] = b"FAIL"
    assert not validate_file_type(
        name="report.docx", stream=BytesIO(data), size=len(data)
    ).accepted
    data = bytearray(ooxml())
    offset = data.index(b"PK\x01\x02")
    data[offset + 16] ^= 1
    assert not validate_file_type(
        name="report.docx", stream=BytesIO(data), size=len(data)
    ).accepted


@pytest.mark.parametrize(
    "xml",
    [
        '<Types><Override ContentType="application/vnd.ms-office.vbaProject" PartName="/word/evil.bin" /></Types>',
        '<Types><Override ContentType="application/vnd.ms-word.document.macroEnabled.main+xml" /></Types>',
        '<!DOCTYPE Types [<!ENTITY x "value">]><Types>&x;</Types>',
    ],
)
def test_ooxml_rejects_macro_metadata_and_entities(xml):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", xml)
        archive.writestr("_rels/.rels", "<Relationships />")
        archive.writestr("word/document.xml", "<document />")
    data = output.getvalue()
    assert not validate_file_type(
        name="report.docx", stream=BytesIO(data), size=len(data)
    ).accepted


def test_ooxml_rejects_false_entry_count_before_zipfile(monkeypatch):
    from files import inspection

    data = bytearray(ooxml())
    end = data.rindex(b"PK\x05\x06")
    struct.pack_into("<2H", data, end + 8, 1, 1)
    monkeypatch.setattr(
        inspection.zipfile, "ZipFile", lambda *_: pytest.fail("unbounded parser called")
    )
    assert not validate_file_type(
        name="report.docx", stream=BytesIO(data), size=len(data)
    ).accepted


def test_valid_ooxml_is_accepted():
    data = ooxml()
    assert validate_file_type(
        name="report.docx", stream=BytesIO(data), size=len(data)
    ).accepted
