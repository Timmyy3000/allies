from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction

from waitlist.models import WaitlistEntry

from ._business_export import (
    BATCH_SIZE,
    BUSINESS_FIELDS,
    EXPORT_FORMAT_VERSION,
    SOURCE_TABLE,
    RowChecksum,
    artifact_paths,
    iter_encoded_rows,
    validate_waitlist_schema,
)


def _output_directory(raw_output: str) -> Path:
    path = Path(raw_output)
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise CommandError("export output already exists")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


class Command(BaseCommand):
    help = "Export waitlist business data as a versioned JSONL artifact."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        output_directory = _output_directory(options["output"])
        try:
            with TemporaryDirectory(
                dir=output_directory.parent,
                prefix=f".{output_directory.name}.waitlist-export-",
            ) as staging_raw:
                staging_directory = Path(staging_raw)
                manifest_path, data_path = artifact_paths(staging_directory)
                with data_path.open("xb") as data_file:
                    with transaction.atomic():
                        if connection.vendor == "postgresql":
                            with connection.cursor() as cursor:
                                cursor.execute(
                                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
                                )
                        validate_waitlist_schema(connection)
                        rows = WaitlistEntry.objects.values(*BUSINESS_FIELDS).order_by(
                            "attempt_id_digest"
                        )
                        checksum = RowChecksum()
                        for _, encoded in iter_encoded_rows(
                            rows.iterator(chunk_size=BATCH_SIZE)
                        ):
                            data_file.write(encoded)
                            checksum.add(encoded)
                    data_file.flush()
                    os.fsync(data_file.fileno())

                manifest = {
                    "format_version": EXPORT_FORMAT_VERSION,
                    "source_table": SOURCE_TABLE,
                    "business_columns": list(BUSINESS_FIELDS),
                    "row_count": checksum.count,
                    "canonical_checksum": checksum.value,
                    "exported_at": datetime.now(UTC)
                    .isoformat(timespec="microseconds")
                    .replace("+00:00", "Z"),
                }
                with manifest_path.open("xb") as manifest_file:
                    manifest_file.write(
                        (
                            json.dumps(
                                manifest,
                                ensure_ascii=False,
                                separators=(",", ":"),
                                indent=2,
                            )
                            + "\n"
                        ).encode("utf-8")
                    )
                    manifest_file.flush()
                    os.fsync(manifest_file.fileno())

                if output_directory.exists():
                    output_directory.rmdir()
                os.replace(staging_directory, output_directory)
        except (DatabaseError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        except OSError as exc:
            raise CommandError("could not write waitlist export") from exc
        self.stdout.write(f"exported {checksum.count} waitlist entries")
