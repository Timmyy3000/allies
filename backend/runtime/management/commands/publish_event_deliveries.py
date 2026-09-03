from time import sleep

from django.core.management.base import BaseCommand, CommandError

from runtime.services.event_delivery import publish_pending_event_deliveries


class Command(BaseCommand):
    help = "Publish pending Foundry event deliveries."

    def add_arguments(self, parser):
        parser.add_argument(
            "--watch",
            action="store_true",
            help="Run delivery passes periodically until stopped.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=None,
            metavar="SECONDS",
            help="Seconds between watch runs (1-3600; default: 60).",
        )
        parser.add_argument(
            "--max-runs",
            type=int,
            default=None,
            metavar="COUNT",
            help="Optional maximum number of watch passes (1-1440).",
        )

    def handle(self, *args, **options):
        watch = options["watch"]
        interval = options["interval"]
        max_runs = options["max_runs"]
        if not watch:
            if interval is not None or max_runs is not None:
                raise CommandError("--interval and --max-runs require --watch")
            self._run_once()
            return
        if max_runs is not None and not 1 <= max_runs <= 1440:
            raise CommandError("--max-runs must be between 1 and 1440")
        interval = 60 if interval is None else interval
        if not 1 <= interval <= 3600:
            raise CommandError("--interval must be between 1 and 3600 seconds")

        run_number = 0
        while max_runs is None or run_number < max_runs:
            self._run_once()
            run_number += 1
            if max_runs is None or run_number < max_runs:
                sleep(interval)

    def _run_once(self):
        report = publish_pending_event_deliveries()
        self.stdout.write(
            f"Delivered {report.delivered} event(s); deferred {report.deferred}; "
            f"exhausted {report.exhausted}."
        )
