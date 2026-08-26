from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXPORT_FORMAT_VERSION = "waitlist-business-export-v1"
SOURCE_TABLE = "waitlist_waitlistentry"
LEGACY_IDENTITY_COLUMN = "public_id"
MANIFEST_NAME = "manifest.json"
DATA_NAME = "data.jsonl"
BATCH_SIZE = 1000
MAX_LINE_BYTES = 1_000_000
MAX_MANIFEST_BYTES = 1_000_000
BUSINESS_FIELDS = (
    "attempt_id_digest",
    "attempt_token_digest",
    "completion_digest",
    "generation_claimed_at",
    "name",
    "appearance_catalog_version",
    "appearance_key",
    "job",
    "personality",
    "greeting_text",
    "greeting_policy_version",
    "greeting_generated_at",
    "reply_text",
    "reply_recorded_at",
    "email_normalized",
    "consent_version",
    "joined_at",
    "expires_at",
    "created_at",
    "updated_at",
)
DATETIME_FIELDS = frozenset(
    {
        "generation_claimed_at",
        "greeting_generated_at",
        "reply_recorded_at",
        "joined_at",
        "expires_at",
        "created_at",
        "updated_at",
    }
)
NULLABLE_DATETIME_FIELDS = frozenset(
    {"generation_claimed_at", "greeting_generated_at", "reply_recorded_at", "joined_at"}
)
CURRENT_COLUMNS = frozenset(("id", *BUSINESS_FIELDS))
LEGACY_COLUMNS = frozenset(("id", LEGACY_IDENTITY_COLUMN, *BUSINESS_FIELDS))


class RowChecksum:
    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self.count = 0

    def add(self, encoded: bytes) -> None:
        self._digest.update(encoded)
        self.count += 1

    @property
    def value(self) -> str:
        return f"sha256:{self._digest.hexdigest()}"


def validate_checksum(value: Any) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
    ):
        raise ValueError("checksum must be sha256:<64 lowercase hex>")
    return value


def _value(row: Mapping[str, Any], field: str) -> Any:
    try:
        return row[field]
    except KeyError as exc:
        raise ValueError(f"missing waitlist field: {field}") from exc


def _datetime_value(value: Any, *, field: str) -> str | None:
    if value is None:
        if field not in NULLABLE_DATETIME_FIELDS:
            raise ValueError(f"waitlist field cannot be null: {field}")
        return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
        except ValueError as exc:
            raise ValueError(f"invalid waitlist datetime: {field}") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"waitlist datetime must be timezone-aware: {field}")
        canonical = (
            parsed.astimezone(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        if canonical != value:
            raise ValueError(f"non-canonical waitlist datetime: {field}")
        return canonical
    if not isinstance(value, datetime):
        raise TypeError(f"invalid waitlist datetime: {field}")
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def canonical_waitlist_row(row: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in BUSINESS_FIELDS:
        value = _value(row, field)
        if field in DATETIME_FIELDS:
            values[field] = _datetime_value(value, field=field)
        else:
            if not isinstance(value, str):
                raise ValueError(f"waitlist field must be a string: {field}")
            if unicodedata.normalize("NFC", value) != value:
                raise ValueError(f"waitlist field must already be NFC: {field}")
            values[field] = value
    if not values["attempt_id_digest"]:
        raise ValueError("attempt_id_digest is required")
    return values


def _encode_canonical_row(row: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            row,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def encoded_waitlist_row(
    row: Mapping[str, Any],
) -> tuple[dict[str, Any], bytes]:
    canonical = canonical_waitlist_row(row)
    return canonical, _encode_canonical_row(canonical)


def encode_waitlist_row(row: Mapping[str, Any]) -> bytes:
    return encoded_waitlist_row(row)[1]


def iter_encoded_rows(
    rows: Iterable[Mapping[str, Any]],
) -> Iterator[tuple[dict[str, Any], bytes]]:
    previous_attempt_id_digest = None
    for row in rows:
        canonical, encoded = encoded_waitlist_row(row)
        if len(encoded) > MAX_LINE_BYTES:
            raise ValueError("waitlist export row is too large")
        attempt_id_digest = canonical["attempt_id_digest"]
        if previous_attempt_id_digest == attempt_id_digest:
            raise ValueError("duplicate attempt_id_digest")
        if (
            previous_attempt_id_digest is not None
            and attempt_id_digest < previous_attempt_id_digest
        ):
            raise ValueError("waitlist rows are not ordered by attempt_id_digest")
        previous_attempt_id_digest = attempt_id_digest
        yield canonical, encoded


def checksum_waitlist_rows(rows: Iterable[Mapping[str, Any]]) -> str:
    checksum = RowChecksum()
    for _, encoded in iter_encoded_rows(rows):
        checksum.add(encoded)
    return checksum.value


def artifact_paths(directory: str | Path) -> tuple[Path, Path]:
    path = Path(directory)
    if not path.is_dir():
        raise ValueError("waitlist artifact path must be a directory")
    return path / MANIFEST_NAME, path / DATA_NAME


def read_manifest(directory: str | Path) -> dict[str, Any]:
    manifest_path, _ = artifact_paths(directory)
    try:
        with manifest_path.open("rb") as handle:
            raw_manifest = handle.read(MAX_MANIFEST_BYTES + 1)
        if len(raw_manifest) > MAX_MANIFEST_BYTES:
            raise ValueError("waitlist manifest is too large")
        value = json.loads(raw_manifest.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("waitlist manifest is unreadable") from exc
    required = {
        "format_version",
        "source_table",
        "business_columns",
        "row_count",
        "canonical_checksum",
        "exported_at",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("waitlist manifest is invalid")
    if value["format_version"] != EXPORT_FORMAT_VERSION:
        raise ValueError("unsupported waitlist export version")
    if value["source_table"] != SOURCE_TABLE:
        raise ValueError("waitlist export source table is invalid")
    if value["business_columns"] != list(BUSINESS_FIELDS):
        raise ValueError("waitlist export business columns are invalid")
    if type(value["row_count"]) is not int or value["row_count"] < 0:
        raise ValueError("waitlist export row count is invalid")
    validate_checksum(value["canonical_checksum"])
    if not isinstance(value["exported_at"], str):
        raise TypeError("waitlist export timestamp is invalid")
    return value


def iter_artifact_rows(
    directory: str | Path,
) -> Iterator[tuple[dict[str, Any], bytes]]:
    _, data_path = artifact_paths(directory)
    try:
        handle = data_path.open("rb")
    except OSError as exc:
        raise ValueError("waitlist export data is unreadable") from exc
    try:
        previous_attempt_id_digest = None
        line_number = 0
        while raw_line := handle.readline(MAX_LINE_BYTES + 1):
            line_number += 1
            if len(raw_line) > MAX_LINE_BYTES or not raw_line.endswith(b"\n"):
                raise ValueError(f"waitlist export line {line_number} is truncated")
            try:
                value = json.loads(raw_line[:-1].decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"waitlist export line {line_number} is invalid"
                ) from exc
            if not isinstance(value, dict) or set(value) != set(BUSINESS_FIELDS):
                raise ValueError(
                    f"waitlist export line {line_number} has invalid fields"
                )
            try:
                canonical, encoded = encoded_waitlist_row(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"waitlist export line {line_number} is invalid: {exc}"
                ) from exc
            if encoded != raw_line:
                raise ValueError(
                    f"waitlist export line {line_number} is not canonical JSONL"
                )
            attempt_id_digest = canonical["attempt_id_digest"]
            if previous_attempt_id_digest == attempt_id_digest:
                raise ValueError(
                    f"waitlist export line {line_number} duplicates attempt_id_digest"
                )
            if (
                previous_attempt_id_digest is not None
                and attempt_id_digest < previous_attempt_id_digest
            ):
                raise ValueError(
                    f"waitlist export line {line_number} is not ordered by attempt_id_digest"
                )
            previous_attempt_id_digest = attempt_id_digest
            yield canonical, encoded
    finally:
        handle.close()


def model_values(canonical: Mapping[str, Any]) -> dict[str, Any]:
    values = dict(canonical)
    for field in DATETIME_FIELDS:
        value = values[field]
        if value is not None:
            values[field] = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    return values


_MISSING = object()


def compare_encoded_rows(
    expected: Iterable[tuple[dict[str, Any], bytes]],
    actual: Iterable[tuple[dict[str, Any], bytes]],
) -> RowChecksum:
    expected_iterator = iter(expected)
    actual_iterator = iter(actual)
    checksum = RowChecksum()
    while True:
        expected_row = next(expected_iterator, _MISSING)
        actual_row = next(actual_iterator, _MISSING)
        if expected_row is _MISSING and actual_row is _MISSING:
            return checksum
        if expected_row is _MISSING or actual_row is _MISSING:
            raise ValueError("waitlist row count differs")
        if expected_row[1] != actual_row[1]:
            raise ValueError("waitlist business data differs")
        checksum.add(actual_row[1])


def _id_kind(database_connection, field) -> str:
    raw_type = str(field.type_code).lower()
    try:
        django_type = database_connection.introspection.get_field_type(
            field.type_code, field
        ).lower()
    except (AttributeError, KeyError, TypeError):
        django_type = ""
    if (
        raw_type in {"uuid", "2950", "char(32)", "character(32)"}
        or "uuid" in raw_type
        or django_type == "uuidfield"
    ):
        return "uuid"
    if raw_type in {
        "integer",
        "int4",
        "int8",
        "bigint",
        "serial",
        "bigserial",
    } or django_type in {
        "autofield",
        "bigintegerfield",
        "bigautofield",
        "integerfield",
    }:
        return "legacy"
    raise ValueError("waitlist primary-key type is not UUID or legacy integer")


def validate_waitlist_schema(database_connection, *, allow_legacy: bool = True) -> str:
    introspection = database_connection.introspection
    try:
        with database_connection.cursor() as cursor:
            tables = introspection.table_names(cursor)
            if SOURCE_TABLE not in tables:
                raise ValueError("waitlist source table is missing")
            description = introspection.get_table_description(cursor, SOURCE_TABLE)
            columns = frozenset(field.name for field in description)
            if columns == CURRENT_COLUMNS:
                schema_kind = "uuid"
            elif allow_legacy and columns == LEGACY_COLUMNS:
                schema_kind = "legacy"
            else:
                raise ValueError(
                    "waitlist source columns do not match the locked schema"
                )
            id_field = next(field for field in description if field.name == "id")
            if _id_kind(database_connection, id_field) != schema_kind:
                raise ValueError(
                    "waitlist source primary-key type does not match schema"
                )
            for table in tables:
                for name, constraint in introspection.get_constraints(
                    cursor, table
                ).items():
                    foreign_key = constraint.get("foreign_key")
                    if foreign_key and foreign_key[0].split(".")[-1] == SOURCE_TABLE:
                        raise ValueError(
                            f"waitlist source has inbound foreign key: {table}.{name}"
                        )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("waitlist source schema could not be inspected") from exc
    return schema_kind
