from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from allies.models import Ally, AllyDeletionState
from files.models import (
    FileAllyTombstone,
    FileIOOutcome,
    FileStagingObject,
    FileVersion,
)
from files.services.cleanup import _account_locked


class Command(BaseCommand):
    help = "Settle one deletion-owned write only after verified provider completion or abort."

    def add_arguments(self, parser):
        for name in ("workspace-id", "ally-id", "file-id", "write-fence", "key"):
            parser.add_argument(f"--{name}", required=True)
        parser.add_argument(
            "--outcome", required=True, choices=("completed", "aborted")
        )

    def handle(self, *args, **options):
        identity = {}
        for name in ("workspace_id", "ally_id", "file_id", "write_fence"):
            try:
                parsed = UUID(options[name])
            except (TypeError, ValueError) as exc:
                raise CommandError(f"{name} must be a canonical UUID") from exc
            if str(parsed) != options[name]:
                raise CommandError(f"{name} must be a canonical UUID")
            identity[name] = parsed
        key, outcome = options["key"], options["outcome"]
        if (
            not key
            or len(key) > 500
            or outcome
            not in (
                FileIOOutcome.COMPLETED,
                FileIOOutcome.ABORTED,
            )
        ):
            raise CommandError("exact key and definitive outcome are required")
        with transaction.atomic():
            if not FileVersion.objects.filter(
                pk=identity["file_id"],
                workspace_id=identity["workspace_id"],
                ally_id=identity["ally_id"],
            ).exists():
                raise CommandError("deletion write unavailable")
            _account_locked(identity["workspace_id"])
            ally = (
                Ally.objects.select_for_update()
                .filter(
                    pk=identity["ally_id"],
                    workspace_id=identity["workspace_id"],
                    deletion_state__in=(
                        AllyDeletionState.PENDING,
                        AllyDeletionState.REPAIR_REQUIRED,
                    ),
                )
                .first()
            )
            if ally is None or not FileAllyTombstone.objects.filter(ally=ally).exists():
                raise CommandError("deletion write unavailable")
            candidates = list(
                FileStagingObject.objects.select_for_update().filter(
                    file_id=identity["file_id"],
                    file__workspace_id=identity["workspace_id"],
                    file__ally_id=identity["ally_id"],
                    write_fence=identity["write_fence"],
                    key=key,
                    deleted_at__isnull=True,
                    io_outcome__in=(FileIOOutcome.IN_FLIGHT, FileIOOutcome.AMBIGUOUS),
                )[:2]
            )
            if len(candidates) != 1:
                raise CommandError("exact unresolved deletion write unavailable")
            candidate = candidates[0]
            candidate.io_outcome = outcome
            candidate.cleanup_after = timezone.now()
            candidate.save(update_fields=("io_outcome", "cleanup_after"))
        self.stdout.write(
            f"file_id={identity['file_id']} write_fence={identity['write_fence']} outcome={outcome}"
        )
