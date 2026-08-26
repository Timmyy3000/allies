import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, close_old_connections, connection
from django.utils import timezone

from waitlist.management.commands import _business_export as business_export
from waitlist.management.commands import export_waitlist, restore_waitlist
from waitlist.management.commands._business_export import (
    BUSINESS_FIELDS,
    DATA_NAME,
    EXPORT_FORMAT_VERSION,
    MANIFEST_NAME,
    SOURCE_TABLE,
    RowChecksum,
    artifact_paths,
    checksum_waitlist_rows,
    encode_waitlist_row,
    iter_artifact_rows,
    read_manifest,
    validate_waitlist_schema,
)
from waitlist.models import WaitlistEntry

POSTGRES_ONLY = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="requires PostgreSQL"
)


def _row(attempt_id_digest="a" * 64):
    now = datetime(2026, 8, 25, 12, 0, 0, 123456, tzinfo=UTC)
    return {field: "" for field in BUSINESS_FIELDS} | {
        "attempt_id_digest": attempt_id_digest,
        "generation_claimed_at": None,
        "greeting_generated_at": None,
        "reply_recorded_at": None,
        "joined_at": None,
        "expires_at": now,
        "created_at": now,
        "updated_at": now,
    }


class _Cursor:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Introspection:
    def __init__(self, columns, id_type, constraints=None):
        self.description = [
            SimpleNamespace(
                name=column, type_code=id_type if column == "id" else "text"
            )
            for column in columns
        ]
        self.constraints = constraints or {}

    def table_names(self, cursor):
        return [SOURCE_TABLE, *self.constraints]

    def get_table_description(self, cursor, table):
        return self.description

    def get_constraints(self, cursor, table):
        return self.constraints.get(table, {})

    def get_field_type(self, type_code, description):
        return "UUIDField" if type_code == "uuid" else "BigAutoField"


class _Database:
    def __init__(self, columns, id_type, constraints=None):
        self.introspection = _Introspection(columns, id_type, constraints)

    def cursor(self):
        return _Cursor()


def _artifact(directory, rows, *, checksum=None, version=EXPORT_FORMAT_VERSION):
    directory.mkdir()
    _, data_path = artifact_paths(directory)
    data = b"".join(encode_waitlist_row(row) for row in rows)
    data_path.write_bytes(data)
    checksum = checksum or checksum_waitlist_rows(rows)
    manifest_path = directory / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(
            {
                "format_version": version,
                "source_table": SOURCE_TABLE,
                "business_columns": list(BUSINESS_FIELDS),
                "row_count": len(rows),
                "canonical_checksum": checksum,
                "exported_at": "2026-08-25T12:00:00.000000Z",
            }
        )
    )
    return directory


def test_waitlist_encoder_rejects_non_nfc_strings():
    row = _row()
    row["name"] = "Cafe\u0301"

    with pytest.raises(ValueError, match="NFC"):
        encode_waitlist_row(row)


def test_waitlist_checksum_requires_order_and_rejects_duplicates():
    first = _row("a" * 64)
    second = _row("b" * 64)

    assert checksum_waitlist_rows([first, second]).startswith("sha256:")
    with pytest.raises(ValueError, match="not ordered"):
        checksum_waitlist_rows([second, first])
    with pytest.raises(ValueError, match="duplicate attempt_id_digest"):
        checksum_waitlist_rows([first, first])
    with pytest.raises(ValueError, match="attempt_id_digest is required"):
        checksum_waitlist_rows([_row("")])


def test_waitlist_artifact_parser_rejects_non_nfc_strings(tmp_path):
    artifact = tmp_path / "non-nfc"
    artifact.mkdir()
    _, data_path = artifact_paths(artifact)
    row = json.loads(encode_waitlist_row(_row()).decode())
    row["name"] = "Cafe\u0301"
    data_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="NFC"):
        list(iter_artifact_rows(artifact))


def test_waitlist_artifact_reads_are_bounded(tmp_path, monkeypatch):
    artifact = tmp_path / "bounded"
    artifact.mkdir()
    _, data_path = artifact_paths(artifact)

    monkeypatch.setattr(business_export, "MAX_LINE_BYTES", 8)
    data_path.write_bytes(b"x" * 9)
    with pytest.raises(ValueError, match="truncated"):
        next(iter_artifact_rows(artifact))

    monkeypatch.setattr(business_export, "MAX_MANIFEST_BYTES", 8)
    (artifact / MANIFEST_NAME).write_bytes(b"x" * 9)
    with pytest.raises(ValueError, match="too large"):
        read_manifest(artifact)

    row = _row()
    row["name"] = "x" * 20
    with pytest.raises(ValueError, match="row is too large"):
        checksum_waitlist_rows([row])


def test_waitlist_schema_accepts_only_locked_shapes():
    current = _Database(["id", *BUSINESS_FIELDS], "uuid")
    legacy = _Database(["id", "public_id", *BUSINESS_FIELDS], "bigint")

    assert validate_waitlist_schema(current, allow_legacy=False) == "uuid"
    assert validate_waitlist_schema(legacy) == "legacy"
    with pytest.raises(ValueError, match="columns"):
        validate_waitlist_schema(_Database(["id", *BUSINESS_FIELDS, "extra"], "uuid"))
    with pytest.raises(ValueError, match="columns"):
        validate_waitlist_schema(_Database(["id", *BUSINESS_FIELDS[:-1]], "uuid"))
    with pytest.raises(ValueError, match="inbound foreign key"):
        validate_waitlist_schema(
            _Database(
                ["id", *BUSINESS_FIELDS],
                "uuid",
                {"other_table": {"entry_fk": {"foreign_key": (SOURCE_TABLE, "id")}}},
            )
        )


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
def test_waitlist_export_restore_and_verify_round_trip(tmp_path, monkeypatch):
    expiry = timezone.now()
    WaitlistEntry.objects.create(
        attempt_id_digest="a" * 64,
        attempt_token_digest="b" * 64,
        completion_digest="",
        name="",
        appearance_catalog_version="v1",
        appearance_key="ghosty:fd304f",
        job="Planning",
        personality="",
        expires_at=expiry,
    )
    joined_at = timezone.now()
    WaitlistEntry.objects.create(
        attempt_id_digest="b" * 64,
        attempt_token_digest="c" * 64,
        completion_digest="d" * 64,
        name="Ari",
        appearance_catalog_version="v1",
        appearance_key="ghosty:fd304f",
        job="Planning",
        personality="Warm",
        email_normalized="same@example.com",
        consent_version="v1",
        joined_at=joined_at,
        expires_at=expiry,
    )
    WaitlistEntry.objects.create(
        attempt_id_digest="c" * 64,
        attempt_token_digest="d" * 64,
        completion_digest="e" * 64,
        name="Bea",
        appearance_catalog_version="v1",
        appearance_key="ghosty:fd304f",
        job="Planning",
        personality="Warm",
        email_normalized="same@example.com",
        consent_version="v1",
        joined_at=joined_at,
        expires_at=expiry,
    )
    source_rows = list(
        WaitlistEntry.objects.values(*BUSINESS_FIELDS).order_by("attempt_id_digest")
    )
    artifact = tmp_path / "waitlist-export"

    monkeypatch.setattr("waitlist.management.commands.export_waitlist.BATCH_SIZE", 2)
    monkeypatch.setattr("waitlist.management.commands.restore_waitlist.BATCH_SIZE", 2)
    monkeypatch.setattr("waitlist.management.commands.verify_waitlist.BATCH_SIZE", 2)
    call_command("export_waitlist", output=str(artifact))
    manifest = json.loads((artifact / "manifest.json").read_text())
    data = (artifact / "data.jsonl").read_bytes()
    assert manifest["business_columns"] == list(BUSINESS_FIELDS)
    assert manifest["row_count"] == 3
    assert manifest["canonical_checksum"].startswith("sha256:")
    assert data.endswith(b"\n")

    WaitlistEntry.objects.all().delete()
    call_command(
        "restore_waitlist",
        input=str(artifact),
        expected_checksum=manifest["canonical_checksum"],
    )
    restored = list(
        WaitlistEntry.objects.values(*BUSINESS_FIELDS).order_by("attempt_id_digest")
    )
    assert restored == source_rows
    assert list(
        WaitlistEntry.objects.order_by("attempt_id_digest").values_list(
            "email_normalized", flat=True
        )
    ) == ["", "same@example.com", "same@example.com"]
    assert all(entry.id.version == 4 for entry in WaitlistEntry.objects.all())

    call_command("verify_waitlist", manifest=str(artifact))
    with pytest.raises(CommandError, match="already exists"):
        call_command("export_waitlist", output=str(artifact))


@pytest.mark.parametrize(
    "failure", ["corrupt", "truncated", "duplicate", "version", "checksum"]
)
@pytest.mark.postgresql
@pytest.mark.django_db
def test_waitlist_restore_rejects_invalid_artifacts(tmp_path, failure):
    row = _row()
    artifact = tmp_path / failure
    if failure == "duplicate":
        encoded = encode_waitlist_row(row)
        checksum = RowChecksum()
        checksum.add(encoded)
        checksum.add(encoded)
        _artifact(artifact, [row, row], checksum=checksum.value)
    else:
        _artifact(artifact, [row])
    manifest_path = artifact / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    expected_checksum = manifest["canonical_checksum"]

    if failure == "corrupt":
        _, data_path = artifact_paths(artifact)
        data_path.write_bytes(
            data_path.read_bytes().replace(b'"name":""', b'"name":"changed"')
        )
    elif failure == "truncated":
        _, data_path = artifact_paths(artifact)
        data_path.write_bytes(data_path.read_bytes()[:-1])
    elif failure == "version":
        manifest["format_version"] = "waitlist-business-export-v0"
        manifest_path.write_text(json.dumps(manifest))
    elif failure == "checksum":
        expected_checksum = "sha256:" + "0" * 64

    with pytest.raises(CommandError):
        call_command(
            "restore_waitlist",
            input=str(artifact),
            expected_checksum=expected_checksum,
        )
    assert WaitlistEntry.objects.count() == 0


@pytest.mark.postgresql
@pytest.mark.django_db
def test_waitlist_restore_rejects_non_empty_target(tmp_path):
    WaitlistEntry.objects.create(
        attempt_id_digest="b" * 64,
        attempt_token_digest="c" * 64,
        name="Existing",
        appearance_catalog_version="v1",
        appearance_key="ghosty:fd304f",
        job="Planning",
        expires_at=timezone.now(),
    )
    artifact = _artifact(tmp_path / "non-empty", [_row()])
    manifest = json.loads((artifact / MANIFEST_NAME).read_text())

    with pytest.raises(CommandError, match="not empty"):
        call_command(
            "restore_waitlist",
            input=str(artifact),
            expected_checksum=manifest["canonical_checksum"],
        )
    assert WaitlistEntry.objects.count() == 1


@pytest.mark.postgresql
@pytest.mark.django_db(transaction=True)
def test_waitlist_export_restarts_after_interrupted_staging_directory(tmp_path):
    WaitlistEntry.objects.create(
        attempt_id_digest="a" * 64,
        attempt_token_digest="b" * 64,
        name="Retry",
        appearance_catalog_version="v1",
        appearance_key="ghosty:fd304f",
        job="Planning",
        expires_at=timezone.now(),
    )
    artifact = tmp_path / "retry"
    interrupted = tmp_path / ".retry.waitlist-export-interrupted"
    interrupted.mkdir()
    (interrupted / DATA_NAME).write_bytes(b"interrupted")

    call_command("export_waitlist", output=str(artifact))
    assert (artifact / MANIFEST_NAME).is_file()
    assert (artifact / DATA_NAME).is_file()
    assert interrupted.is_dir()

    user_file = tmp_path / "user-files"
    user_file.mkdir()
    note = user_file / "notes.txt"
    note.write_text("keep me")
    with pytest.raises(CommandError, match="already exists"):
        call_command("export_waitlist", output=str(user_file))
    assert note.read_text() == "keep me"


@pytest.mark.postgresql
@POSTGRES_ONLY
@pytest.mark.django_db(transaction=True)
def test_waitlist_export_uses_one_repeatable_read_snapshot(tmp_path, monkeypatch):
    expiry = timezone.now()
    WaitlistEntry.objects.create(
        attempt_id_digest="a" * 64,
        attempt_token_digest="b" * 64,
        name="before-a",
        appearance_catalog_version="v1",
        appearance_key="ghosty:fd304f",
        job="Planning",
        expires_at=expiry,
    )
    WaitlistEntry.objects.create(
        attempt_id_digest="b" * 64,
        attempt_token_digest="c" * 64,
        name="before-b",
        appearance_catalog_version="v1",
        appearance_key="ghosty:fd304f",
        job="Planning",
        expires_at=expiry,
    )
    source_snapshot_ready = threading.Event()
    writer_done = threading.Event()
    original_validate = export_waitlist.validate_waitlist_schema

    def gated_schema_validation(database_connection):
        schema_kind = original_validate(database_connection)
        source_snapshot_ready.set()
        if not writer_done.wait(timeout=10):
            raise AssertionError("writer did not finish")
        return schema_kind

    monkeypatch.setattr(export_waitlist, "BATCH_SIZE", 1)
    monkeypatch.setattr(
        export_waitlist, "validate_waitlist_schema", gated_schema_validation
    )

    def mutate_after_iteration_starts():
        close_old_connections()
        try:
            if not source_snapshot_ready.wait(timeout=10):
                raise AssertionError("export did not establish its source snapshot")
            WaitlistEntry.objects.filter(attempt_id_digest="b" * 64).update(
                name="after-b"
            )
            WaitlistEntry.objects.create(
                attempt_id_digest="c" * 64,
                attempt_token_digest="d" * 64,
                name="inserted-c",
                appearance_catalog_version="v1",
                appearance_key="ghosty:fd304f",
                job="Planning",
                expires_at=expiry,
            )
        finally:
            writer_done.set()
            connection.close()

    artifact = tmp_path / "snapshot"
    with ThreadPoolExecutor(max_workers=1) as executor:
        writer = executor.submit(mutate_after_iteration_starts)
        call_command("export_waitlist", output=str(artifact))
        writer.result(timeout=15)

    assert WaitlistEntry.objects.get(attempt_id_digest="b" * 64).name == "after-b"
    assert WaitlistEntry.objects.count() == 3
    manifest = read_manifest(artifact)
    assert manifest["row_count"] == 2
    rows = list(iter_artifact_rows(artifact))
    assert [row[0]["name"] for row in rows] == ["before-a", "before-b"]


@pytest.mark.postgresql
@POSTGRES_ONLY
@pytest.mark.django_db(transaction=True)
def test_waitlist_restore_rolls_back_after_later_batch_failure(tmp_path, monkeypatch):
    artifact = _artifact(tmp_path / "rollback", [_row(), _row("b" * 64)])
    manifest = json.loads((artifact / MANIFEST_NAME).read_text())
    original_insert_batch = restore_waitlist._insert_batch
    calls = 0

    def fail_on_second_batch(batch):
        nonlocal calls
        calls += 1
        original_insert_batch(batch)
        if calls == 2:
            raise DatabaseError("forced later batch failure")

    monkeypatch.setattr(restore_waitlist, "BATCH_SIZE", 1)
    monkeypatch.setattr(restore_waitlist, "_insert_batch", fail_on_second_batch)

    with pytest.raises(CommandError, match="restore failed"):
        call_command(
            "restore_waitlist",
            input=str(artifact),
            expected_checksum=manifest["canonical_checksum"],
        )
    assert WaitlistEntry.objects.count() == 0
