from __future__ import annotations

from collections.abc import Iterable

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction

from waitlist.models import WaitlistEntry

from ._business_export import (
    BATCH_SIZE,
    BUSINESS_FIELDS,
    RowChecksum,
    compare_encoded_rows,
    iter_artifact_rows,
    iter_encoded_rows,
    model_values,
    read_manifest,
    validate_checksum,
    validate_waitlist_schema,
)


def _scan_artifact(directory, expected_count: int, expected_checksum: str) -> None:
    checksum = RowChecksum()
    for _, encoded in iter_artifact_rows(directory):
        checksum.add(encoded)
    if checksum.count != expected_count:
        raise ValueError("waitlist export row count does not match manifest")
    if checksum.value != expected_checksum:
        raise ValueError("waitlist export checksum does not match manifest")


def _model_rows() -> Iterable[tuple[dict, bytes]]:
    rows = WaitlistEntry.objects.values(*BUSINESS_FIELDS).order_by("attempt_id_digest")
    return iter_encoded_rows(rows.iterator(chunk_size=BATCH_SIZE))


def _insert_batch(batch: list[WaitlistEntry]) -> None:
    timestamps = {entry.id: (entry.created_at, entry.updated_at) for entry in batch}
    WaitlistEntry.objects.bulk_create(batch, batch_size=BATCH_SIZE)
    for entry in batch:
        entry.created_at, entry.updated_at = timestamps[entry.id]
    WaitlistEntry.objects.bulk_update(
        batch, ["created_at", "updated_at"], batch_size=BATCH_SIZE
    )
    batch.clear()


class Command(BaseCommand):
    help = "Restore a verified waitlist business export into an empty table."

    def add_arguments(self, parser):
        parser.add_argument("--input", required=True)
        parser.add_argument("--expected-checksum", required=True)

    def handle(self, *args, **options):
        directory = options["input"]
        try:
            manifest = read_manifest(directory)
            expected_checksum = validate_checksum(options["expected_checksum"])
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if manifest["canonical_checksum"] != expected_checksum:
            raise CommandError("manifest checksum does not match expected checksum")
        try:
            _scan_artifact(
                directory,
                manifest["row_count"],
                manifest["canonical_checksum"],
            )
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        try:
            with transaction.atomic():
                validate_waitlist_schema(connection, allow_legacy=False)
                if WaitlistEntry.objects.exists():
                    raise CommandError("waitlist target is not empty")
                batch: list[WaitlistEntry] = []
                for canonical, _ in iter_artifact_rows(directory):
                    batch.append(WaitlistEntry(**model_values(canonical)))
                    if len(batch) == BATCH_SIZE:
                        _insert_batch(batch)
                if batch:
                    _insert_batch(batch)

                checksum = compare_encoded_rows(
                    iter_artifact_rows(directory), _model_rows()
                )
                if checksum.count != manifest["row_count"]:
                    raise CommandError("restored waitlist row count does not match")
                if checksum.value != manifest["canonical_checksum"]:
                    raise CommandError("restored waitlist checksum does not match")
        except CommandError:
            raise
        except (DatabaseError, TypeError, ValueError) as exc:
            raise CommandError(
                "waitlist restore failed; no rows were restored"
            ) from exc
        self.stdout.write(f"restored {manifest['row_count']} waitlist entries")
