from __future__ import annotations

import signal
import threading

from django.core.management.base import BaseCommand, CommandError

from runtime.services.foundry_worker import (
    DEFAULT_SHUTDOWN_GRACE_SECONDS,
    FoundryWorkerError,
    run_foundry_worker,
)


class Command(BaseCommand):
    help = "Run the persistent Foundry background worker."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-runs",
            type=int,
            default=None,
            metavar="COUNT",
            help="Run this many bounded passes per loop, then exit (1-1440).",
        )
        parser.add_argument(
            "--shutdown-grace",
            type=float,
            default=DEFAULT_SHUTDOWN_GRACE_SECONDS,
            metavar="SECONDS",
            help="Shared shutdown grace period (0-30; default: 30).",
        )

    def handle(self, *args, **options):
        max_runs = options["max_runs"]
        grace = options["shutdown_grace"]

        stop_event = threading.Event()
        previous_handlers = _install_signal_handlers(stop_event)
        try:
            run_foundry_worker(
                stop_event=stop_event,
                max_runs=max_runs,
                shutdown_grace_seconds=grace,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        except FoundryWorkerError as exc:
            raise CommandError(
                f"Foundry worker supervision failed ({type(exc).__name__})"
            ) from exc
        finally:
            _restore_signal_handlers(previous_handlers)


def _install_signal_handlers(stop_event: threading.Event) -> dict[int, object]:
    if threading.current_thread() is not threading.main_thread():
        return {}
    previous: dict[int, object] = {}

    def request_stop(signum, frame) -> None:
        del signum, frame
        stop_event.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, request_stop)
        except (OSError, ValueError):
            continue
    return previous


def _restore_signal_handlers(previous: dict[int, object]) -> None:
    if threading.current_thread() is not threading.main_thread():
        return
    for signum, handler in previous.items():
        try:
            signal.signal(signum, handler)
        except (OSError, ValueError):
            continue


__all__ = ["Command"]
