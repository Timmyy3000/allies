"""Bounded file-type validation and ClamAV inspection helpers."""

from __future__ import annotations

import codecs
import hashlib
import os
import socket
import struct
import tempfile
import time
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from typing import BinaryIO, Protocol

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from files.previews import is_text_media_type
from files.types import MAX_FILE_BYTES
from files.types import MEDIA_TYPES as _MEDIA_TYPES

CHUNK_BYTES = 64 * 1024
MAX_OFFICE_ENTRIES = 1_000
MAX_OFFICE_EXPANDED_BYTES = 100_000_000

_JPEG = b"\xff\xd8\xff"
_PNG = b"\x89PNG\r\n\x1a\n"
_GIF = (b"GIF87a", b"GIF89a")
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_EOCD = b"PK\x05\x06"
_OOXML_PARTS = {
    "docx": "word/document.xml",
    "xlsx": "xl/workbook.xml",
    "pptx": "ppt/presentation.xml",
}
_LEGACY_EXTENSIONS = {"doc", "xls", "ppt"}


@dataclass(frozen=True, slots=True)
class TypeValidation:
    accepted: bool
    media_type: str | None
    preview_kind: str
    safe_error_code: str | None = None
    actual_size: int | None = None
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ScannerConfig:
    host: str
    port: int = 3310
    deadline_seconds: float = 60.0
    max_definition_age: timedelta = timedelta(hours=24)

    def __post_init__(self) -> None:
        if not self.host or not 1 <= self.port <= 65535:
            raise ValueError("invalid ClamAV address")
        if not 0 < self.deadline_seconds <= 60:
            raise ValueError("invalid ClamAV deadline")
        if not timedelta() < self.max_definition_age <= timedelta(hours=24):
            raise ValueError("invalid ClamAV bounds")


@dataclass(frozen=True, slots=True)
class ScannerResult:
    clean: bool
    safe_error_code: str | None
    scanner_version: str | None = None
    definitions_updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FileInspection:
    accepted: bool
    media_type: str | None
    preview_kind: str
    safe_error_code: str | None
    scanner_clean: bool
    actual_size: int | None = None
    sha256: str | None = None
    scanner_version: str | None = None
    definitions_updated_at: datetime | None = None


class ClamAvTransport(Protocol):
    def version(self, *, timeout_seconds: float) -> str: ...

    def scan(
        self, stream: BinaryIO, *, timeout_seconds: float, chunk_bytes: int
    ) -> str: ...


class SocketClamAvTransport:
    """The production transport sends bytes to the private scanner."""

    def __init__(
        self,
        config: ScannerConfig,
        *,
        connector: Callable[..., socket.socket] = socket.create_connection,
    ) -> None:
        self.config = config
        self.connector = connector

    def version(self, *, timeout_seconds: float) -> str:
        deadline = time.monotonic() + timeout_seconds
        with self._connect(timeout_seconds) as connection:
            self._send(connection, b"zVERSION\0", deadline)
            return self._response(connection, deadline)

    def scan(
        self, stream: BinaryIO, *, timeout_seconds: float, chunk_bytes: int
    ) -> str:
        deadline = time.monotonic() + timeout_seconds
        with self._connect(timeout_seconds) as connection:
            self._send(connection, b"zINSTREAM\0", deadline)
            for chunk in _chunks(stream, chunk_bytes):
                self._send(connection, struct.pack(">I", len(chunk)), deadline)
                self._send(connection, chunk, deadline)
            self._send(connection, b"\0\0\0\0", deadline)
            return self._response(connection, deadline)

    def _connect(self, timeout_seconds: float) -> socket.socket:
        connection = self.connector(
            (self.config.host, self.config.port), timeout=timeout_seconds
        )
        connection.settimeout(timeout_seconds)
        return connection

    @staticmethod
    def _send(connection: socket.socket, payload: bytes, deadline: float) -> None:
        connection.settimeout(_socket_remaining(deadline))
        connection.sendall(payload)

    @staticmethod
    def _response(connection: socket.socket, deadline: float) -> str:
        response = bytearray()
        while len(response) <= 16_384:
            connection.settimeout(_socket_remaining(deadline))
            chunk = connection.recv(4_096)
            if not chunk:
                raise OSError("ClamAV response ended")
            response.extend(chunk)
            if b"\0" in chunk:
                raw, _, _ = response.partition(b"\0")
                return raw.decode("ascii", "strict")
        raise ValueError("ClamAV response too large")


class ClamAvClient:
    def __init__(
        self,
        config: ScannerConfig,
        *,
        transport: ClamAvTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.transport = transport or SocketClamAvTransport(config)
        self.monotonic = monotonic

    def scan(self, stream: BinaryIO, *, now: datetime | None = None) -> ScannerResult:
        started = self.monotonic()
        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("scanner time must be timezone aware")
        try:
            version = self.transport.version(timeout_seconds=self._remaining(started))
            scanner_version, updated_at = _parse_version(version)
        except TimeoutError:
            return ScannerResult(False, "scanner_timeout")
        except (OSError, UnicodeError, ValueError):
            return ScannerResult(False, "scanner_unavailable")
        if now - updated_at > self.config.max_definition_age:
            return ScannerResult(
                False,
                "scanner_definitions_stale",
                scanner_version,
                updated_at,
            )
        try:
            response = self.transport.scan(
                stream,
                timeout_seconds=self._remaining(started),
                chunk_bytes=CHUNK_BYTES,
            )
            self._remaining(started)
        except TimeoutError:
            return ScannerResult(False, "scanner_timeout", scanner_version, updated_at)
        except (OSError, UnicodeError, ValueError):
            return ScannerResult(
                False, "scanner_unavailable", scanner_version, updated_at
            )
        if response == "stream: OK":
            return ScannerResult(True, None, scanner_version, updated_at)
        if response.endswith(" FOUND"):
            return ScannerResult(False, "malware_detected", scanner_version, updated_at)
        return ScannerResult(False, "scanner_unavailable", scanner_version, updated_at)

    def _remaining(self, started: float) -> float:
        remaining = self.config.deadline_seconds - (self.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("ClamAV deadline elapsed")
        return remaining


def inspect_file(
    *,
    name: str,
    source: BinaryIO,
    size: int,
    scanner: ClamAvClient,
    now: datetime | None = None,
) -> FileInspection:
    """Validate and scan a bounded private object without loading it into memory."""
    if (
        not isinstance(name, str)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or not 1 <= size <= MAX_FILE_BYTES
    ):
        return FileInspection(False, None, "none", "unsupported_type", False)
    try:
        with _prepared_source(source, size) as stream:
            typed = validate_file_type(name=name, stream=stream, size=size)
            if not typed.accepted:
                return FileInspection(
                    False,
                    typed.media_type,
                    typed.preview_kind,
                    typed.safe_error_code,
                    False,
                    typed.actual_size,
                    typed.sha256,
                )
            stream.seek(0)
            scanned = scanner.scan(stream, now=now)
    except _InspectionFailure as exc:
        return FileInspection(False, None, "none", exc.code, False)
    except (OSError, ValueError):
        return FileInspection(False, None, "none", "inspection_unavailable", False)
    return FileInspection(
        typed.accepted and scanned.clean,
        typed.media_type,
        typed.preview_kind,
        scanned.safe_error_code,
        scanned.clean,
        typed.actual_size,
        typed.sha256,
        scanned.scanner_version,
        scanned.definitions_updated_at,
    )


def validate_file_type(*, name: str, stream: BinaryIO, size: int) -> TypeValidation:
    if not isinstance(name, str) or not isinstance(size, int) or isinstance(size, bool):
        return _rejected("unsupported_type")
    suffix = PurePath(name).suffix.lower().removeprefix(".")
    media_type = _MEDIA_TYPES.get(suffix)
    if (
        name != PurePath(name).name
        or "/" in name
        or "\\" in name
        or ":" in name
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
        or not media_type
        or not 1 <= size <= MAX_FILE_BYTES
    ):
        return _rejected("unsupported_type")
    try:
        actual_size, digest = _verify_size(stream, size)
        stream.seek(0)
        if is_text_media_type(media_type):
            _verify_utf8(stream)
        elif suffix in _OOXML_PARTS:
            _verify_ooxml(stream, _OOXML_PARTS[suffix])
        elif suffix in _LEGACY_EXTENSIONS:
            _verify_legacy_office(stream)
        else:
            _verify_magic(stream, suffix)
    except _InspectionFailure as exc:
        return _rejected(exc.code, media_type)
    except (
        OSError,
        UnicodeError,
        ValueError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
        DefusedXmlException,
        NotImplementedError,
    ):
        return _rejected("type_invalid", media_type)
    return TypeValidation(
        True,
        media_type,
        _preview_kind(suffix),
        actual_size=actual_size,
        sha256=digest,
    )


@contextmanager
def _prepared_source(source: BinaryIO, size: int) -> Iterator[BinaryIO]:
    try:
        source.seek(0)
    except (AttributeError, OSError):
        with tempfile.TemporaryFile() as staged:
            _copy_bounded(source, staged, size)
            staged.seek(0)
            yield staged
        return
    yield source


def _copy_bounded(source: BinaryIO, destination: BinaryIO, size: int) -> None:
    total = 0
    for chunk in _chunks(source, CHUNK_BYTES):
        total += len(chunk)
        if total > size:
            raise _InspectionFailure("size_mismatch")
        destination.write(chunk)
    if total != size:
        raise _InspectionFailure("size_mismatch")


def _verify_size(stream: BinaryIO, size: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    for chunk in _chunks(stream, CHUNK_BYTES):
        total += len(chunk)
        if total > size:
            raise _InspectionFailure("size_mismatch")
        digest.update(chunk)
    if total != size:
        raise _InspectionFailure("size_mismatch")
    return total, digest.hexdigest()


def _chunks(stream: BinaryIO, chunk_bytes: int) -> Iterator[bytes]:
    while chunk := stream.read(chunk_bytes):
        if not isinstance(chunk, bytes) or len(chunk) > chunk_bytes:
            raise ValueError("invalid file stream")
        yield chunk


def _verify_utf8(stream: BinaryIO) -> None:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    for chunk in _chunks(stream, CHUNK_BYTES):
        decoder.decode(chunk)
    decoder.decode(b"", final=True)


def _verify_magic(stream: BinaryIO, suffix: str) -> None:
    header = stream.read(32)
    if not isinstance(header, bytes):
        raise _InspectionFailure("type_invalid")
    valid = {
        "jpg": header.startswith(_JPEG),
        "jpeg": header.startswith(_JPEG),
        "png": header.startswith(_PNG),
        "gif": header.startswith(_GIF),
        "webp": len(header) >= 12
        and header.startswith(b"RIFF")
        and header[8:12] == b"WEBP",
        "pdf": header.startswith(b"%PDF-"),
        "heic": _is_heif(header),
        "heif": _is_heif(header),
    }.get(suffix, False)
    if not valid:
        raise _InspectionFailure("type_mismatch")


def _is_heif(header: bytes) -> bool:
    if len(header) < 16 or header[4:8] != b"ftyp":
        return False
    brands = {header[index : index + 4] for index in range(8, len(header) - 3, 4)}
    return bool(brands & {b"heic", b"heif", b"heix", b"hevc", b"hevx", b"mif1"})


def _verify_ooxml(stream: BinaryIO, required_part: str) -> None:
    if _zip_entry_count(stream) > MAX_OFFICE_ENTRIES:
        raise _InspectionFailure("office_too_complex")
    with zipfile.ZipFile(stream) as container:
        entries = container.infolist()
        if len(entries) > MAX_OFFICE_ENTRIES:
            raise _InspectionFailure("office_too_complex")
        total = sum(entry.file_size for entry in entries)
        if total > MAX_OFFICE_EXPANDED_BYTES:
            raise _InspectionFailure("office_too_complex")
        names = {entry.filename.casefold() for entry in entries}
        if (
            any(entry.flag_bits & 1 for entry in entries)
            or {
                "encryptedpackage",
                "encryptioninfo",
            }
            & names
        ):
            raise _InspectionFailure("office_encrypted")
        if any(name.endswith("vbaproject.bin") for name in names):
            raise _InspectionFailure("office_macro")
        if (
            "[content_types].xml" not in names
            or "_rels/.rels" not in names
            or required_part not in names
        ):
            raise _InspectionFailure("office_invalid")
        if len(names) != len(entries):
            raise _InspectionFailure("office_invalid")
        expanded = 0
        for entry in entries:
            name = entry.filename.casefold()
            if name.startswith("/") or "\\" in name or ".." in name.split("/"):
                raise _InspectionFailure("office_invalid")
            parser = None
            if name.endswith((".xml", ".rels")):
                parser = ElementTree.DefusedXMLParser(
                    target=_OfficeXmlTarget(name, required_part),
                    forbid_dtd=True,
                    forbid_entities=True,
                    forbid_external=True,
                )
            with container.open(entry) as part:
                for chunk in _chunks(part, CHUNK_BYTES):
                    expanded += len(chunk)
                    if expanded > MAX_OFFICE_EXPANDED_BYTES:
                        raise _InspectionFailure("office_too_complex")
                    if parser is not None:
                        parser.feed(chunk)
            if parser is not None:
                parser.close()


class _OfficeXmlTarget:
    def __init__(self, name: str, required_part: str) -> None:
        self.depth = 0
        self.elements = 0
        self.expected_root = {
            "[content_types].xml": "Types",
            "_rels/.rels": "Relationships",
            required_part: {
                "word": "document",
                "xl": "workbook",
                "ppt": "presentation",
            }[required_part.split("/")[0]],
        }.get(name)

    def start(self, tag: str, attributes: dict[str, str]) -> None:
        if (
            self.elements == 0
            and self.expected_root is not None
            and tag.rsplit("}", 1)[-1] != self.expected_root
        ):
            raise _InspectionFailure("office_invalid")
        self.depth += 1
        self.elements += 1
        if self.depth > 128 or self.elements > 1_000_000:
            raise _InspectionFailure("office_too_complex")
        for value in attributes.values():
            normalized = value.casefold()
            if "vbaproject" in normalized or "macroenabled" in normalized:
                raise _InspectionFailure("office_macro")

    def end(self, tag: str) -> None:
        self.depth -= 1

    def data(self, data: str) -> None:
        pass

    def close(self) -> None:
        pass


def _verify_legacy_office(stream: BinaryIO) -> None:
    if stream.read(8) != _OLE:
        raise _InspectionFailure("type_mismatch")
    raise _InspectionFailure("office_legacy_unsupported")


def _zip_entry_count(stream: BinaryIO) -> int:
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(max(0, size - 65_557))
    tail = stream.read(65_557)
    index = tail.rfind(_ZIP_EOCD)
    while index >= 0:
        if index + 22 <= len(tail):
            comment_size = struct.unpack_from("<H", tail, index + 20)[0]
            if index + 22 + comment_size == len(tail):
                disk, directory_disk, disk_count, count, length, offset = (
                    struct.unpack_from("<4H2I", tail, index + 4)
                )
                end = size - len(tail) + index
                if (
                    disk
                    or directory_disk
                    or disk_count != count
                    or offset + length != end
                ):
                    raise _InspectionFailure("office_invalid")
                if count > MAX_OFFICE_ENTRIES:
                    raise _InspectionFailure("office_too_complex")
                stream.seek(offset)
                actual = 0
                while stream.tell() < end:
                    header = stream.read(46)
                    if len(header) != 46 or header[:4] != b"PK\x01\x02":
                        raise _InspectionFailure("office_invalid")
                    actual += 1
                    if actual > MAX_OFFICE_ENTRIES:
                        raise _InspectionFailure("office_too_complex")
                    variable_length = sum(struct.unpack_from("<3H", header, 28))
                    stream.seek(variable_length, os.SEEK_CUR)
                if stream.tell() != end or actual != count:
                    raise _InspectionFailure("office_invalid")
                return actual
        index = tail.rfind(_ZIP_EOCD, 0, index)
    raise _InspectionFailure("office_invalid")


def _parse_version(value: str) -> tuple[str, datetime]:
    parts = value.split("/", 2)
    if len(parts) != 3 or not parts[0].startswith("ClamAV "):
        raise ValueError("invalid ClamAV version")
    updated_at = datetime.strptime(parts[2].strip(), "%a %b %d %H:%M:%S %Y").replace(
        tzinfo=UTC
    )
    return parts[0].removeprefix("ClamAV "), updated_at


def _socket_remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("ClamAV deadline elapsed")
    return remaining


def _preview_kind(suffix: str) -> str:
    if suffix in {"jpg", "jpeg", "png", "gif", "webp"}:
        return "image"
    if suffix == "pdf":
        return "pdf"
    if is_text_media_type(_MEDIA_TYPES[suffix]):
        return "text"
    return "none"


def _rejected(code: str, media_type: str | None = None) -> TypeValidation:
    return TypeValidation(False, media_type, "none", code)


class _InspectionFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
