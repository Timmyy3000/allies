from time import sleep

from django.core.management.base import BaseCommand, CommandError

from runtime.services.provisioning_hints import publish_due_profile_readiness_hints


class Command(BaseCommand):
    help = "Publish pending Foundry profile-readiness hints."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--interval", type=int, default=None, metavar="SECONDS")
        parser.add_argument("--max-runs", type=int, default=None, metavar="COUNT")

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
        interval = 1 if interval is None else interval
        if not 1 <= interval <= 3600:
            raise CommandError("--interval must be between 1 and 3600 seconds")
        run_number = 0
        while max_runs is None or run_number < max_runs:
            delivered = self._run_once()
            run_number += 1
            if not delivered and (max_runs is None or run_number < max_runs):
                sleep(interval)

    def _run_once(self):
        try:
            report = publish_due_profile_readiness_hints(limit=1)
        except Exception as exc:  # noqa: BLE001 - next supervised pass recovers
            self.stderr.write(
                f"Profile readiness hint pass failed: {type(exc).__name__}"
            )
            return 0
        self.stdout.write(
            f"Delivered {report.delivered} profile hint(s); "
            f"deferred {report.deferred}; exhausted {report.exhausted}."
        )
        return report.delivered
