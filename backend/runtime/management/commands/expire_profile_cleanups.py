from time import sleep

from django.core.management.base import BaseCommand, CommandError

from runtime.services.profiles import expire_profile_cleanups


class Command(BaseCommand):
    help = "Fence runtime profile cleanups whose grace window has expired."

    def add_arguments(self, parser):
        parser.add_argument(
            "--watch",
            action="store_true",
            help="Run the expiry pass periodically for a bounded number of runs.",
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
            help="Required with --watch; maximum number of expiry passes (1-1440).",
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
        if max_runs is None:
            raise CommandError("--watch requires --max-runs")
        if not 1 <= max_runs <= 1440:
            raise CommandError("--max-runs must be between 1 and 1440")
        interval = 60 if interval is None else interval
        if not 1 <= interval <= 3600:
            raise CommandError("--interval must be between 1 and 3600 seconds")

        for run_number in range(max_runs):
            self._run_once()
            if run_number + 1 < max_runs:
                sleep(interval)

    def _run_once(self):
        receipts = expire_profile_cleanups()
        self.stdout.write(f"Fenced {len(receipts)} expired profile cleanup(s).")
