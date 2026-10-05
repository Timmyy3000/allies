from __future__ import annotations

from collections.abc import Iterable

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection

from waitlist.models import WaitlistEntry

from ._business_export import (
    BATCH_SIZE,
    BUSINESS_FIELDS,
    compare_encoded_rows,
    iter_artifact_rows,
    iter_encoded_rows,
    read_manifest,
    validate_waitlist_schema,
)


def _model_rows() -> Iterable[tuple[dict, bytes]]:
    rows = WaitlistEntry.objects.values(*BUSINESS_FIELDS).order_by("attempt_id_digest")
    return iter_encoded_rows(rows.iterator(chunk_size=BATCH_SIZE))


class Command(BaseCommand):
    help = "Verify a restored waitlist table against its export artifact."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)

    def handle(self, *args, **options):
        directory = options["manifest"]
        try:
            manifest = read_manifest(directory)
            validate_waitlist_schema(connection, allow_legacy=False)
            checksum = compare_encoded_rows(
                iter_artifact_rows(directory), _model_rows()
            )
            if checksum.count != manifest["row_count"]:
                raise ValueError("restored waitlist row count does not match manifest")
            if checksum.value != manifest["canonical_checksum"]:
                raise ValueError("restored waitlist checksum does not match manifest")
        except (DatabaseError, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"verified {manifest['row_count']} waitlist entries")
