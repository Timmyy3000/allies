from time import sleep

from django.core.management.base import BaseCommand, CommandError

from runtime.services.event_delivery import publish_pending_event_deliveries
from runtime.services.runtime_intents import cleanup_runtime_intents
from runtime.services.runtime_power import (
    process_runtime_wakes,
    stop_idle_workspaces,
)


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
        try:
            # Bound Fly latency ahead of the durable event queue. Execution
            # wakes are ordered ahead of speculative intent by the service.
            wake = process_runtime_wakes(limit=1)
        except Exception as exc:  # noqa: BLE001 - delivery must survive power faults
            wake = None
            self.stderr.write(f"Runtime wake pass failed: {type(exc).__name__}")

        try:
            report = _publish_one_delivery()
        except Exception as exc:  # noqa: BLE001 - cleanup/next wake must continue
            report = None
            self.stderr.write(f"Event delivery pass failed: {type(exc).__name__}")

        try:
            expired = cleanup_runtime_intents()
        except Exception as exc:  # noqa: BLE001 - cleanup is independently bounded
            expired = 0
            self.stderr.write(f"Runtime intent cleanup failed: {type(exc).__name__}")

        try:
            idle = stop_idle_workspaces(limit=1)
        except Exception as exc:  # noqa: BLE001 - idle stop cannot stop future wakes
            idle = None
            self.stderr.write(f"Runtime idle-stop pass failed: {type(exc).__name__}")

        delivered = report.delivered if report is not None else 0
        deferred = report.deferred if report is not None else 0
        exhausted = report.exhausted if report is not None else 0
        repair_pending = report.repair_pending if report is not None else 0
        recovered = report.recovered if report is not None else 0
        wake_started = wake.started if wake is not None else 0
        wake_failed = wake.failed if wake is not None else 0
        wake_unavailable = wake.unavailable if wake is not None else 0
        idle_stopped = idle.stopped if idle is not None else 0
        idle_unavailable = idle.unavailable if idle is not None else 0
        self.stdout.write(
            f"Wake started {wake_started}; wake failed {wake_failed}; "
            f"wake unavailable {wake_unavailable}; "
            f"Delivered {delivered} event(s); deferred {deferred}; "
            f"exhausted {exhausted}; repair pending {repair_pending}; "
            f"recovered {recovered}; expired {expired} intent(s); "
            f"idle stopped {idle_stopped}; idle unavailable {idle_unavailable}."
        )


def _publish_one_delivery():
    """Keep tiny legacy command fakes usable while enforcing one live claim."""

    try:
        return publish_pending_event_deliveries(limit=1)
    except TypeError as exc:
        if "unexpected keyword" not in str(exc):
            raise
        return publish_pending_event_deliveries()
