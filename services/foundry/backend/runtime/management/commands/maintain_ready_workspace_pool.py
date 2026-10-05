from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from runtime.services.ready_pool_maintenance import (
    MAX_MAINTENANCE_LIMIT,
    maintain_ready_pool_once,
)


class Command(BaseCommand):
    help = "Run one bounded ready-workspace pool maintenance pass."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=1,
            choices=range(1, MAX_MAINTENANCE_LIMIT + 1),
            help="Maximum bundles to claim in this pass (1-8).",
        )
        parser.add_argument(
            "--drain",
            action="store_true",
            help="Clean explicitly owned unassigned bundles while the target is zero.",
        )

    def handle(self, *args, **options):
        try:
            result = maintain_ready_pool_once(
                limit=options["limit"],
                drain=options["drain"],
            )
        except Exception as exc:
            raise CommandError(
                f"Ready pool maintenance failed ({type(exc).__name__})"
            ) from exc
        self.stdout.write(
            "Ready pool maintenance: "
            f"enabled={result.enabled} target={result.target} "
            f"created={result.created} resumed={result.resumed} "
            f"refreshed={result.refreshed} evicted={result.evicted} "
            f"failed={result.failed} skipped={result.skipped} "
            f"ready={result.ready} preparing={result.preparing} "
            f"evicting={result.evicting} failed_rows={result.failed_rows}"
        )


__all__ = ["Command"]
