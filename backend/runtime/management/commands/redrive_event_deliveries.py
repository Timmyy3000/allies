from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from runtime.exceptions import RuntimeDomainError
from runtime.models import EventDeliveryState, ExecutionEventDelivery
from runtime.services.event_delivery import redrive_event_deliveries


class Command(BaseCommand):
    help = "Validate or redrive selected exhausted Foundry event deliveries."

    def add_arguments(self, parser):
        parser.add_argument(
            "identifiers",
            nargs="*",
            help="Delivery IDs to inspect (use --event-id for retained event IDs).",
        )
        parser.add_argument(
            "--delivery-id",
            action="append",
            default=[],
            help="Delivery UUID to inspect; may be repeated.",
        )
        parser.add_argument(
            "--event-id",
            action="append",
            default=[],
            help="Retained ExecutionEvent.event_id to inspect; may be repeated.",
        )
        parser.add_argument(
            "--attempt-id",
            action="append",
            default=[],
            help="Select every exhausted delivery of this attempt; may be repeated.",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Apply the validated redrive. Without this flag the command is read-only.",
        )

    def handle(self, *args, **options):
        delivery_ids = [*options["identifiers"], *options["delivery_id"]]
        if options["attempt_id"]:
            try:
                delivery_ids += [
                    str(delivery_id)
                    for delivery_id in ExecutionEventDelivery.objects.filter(
                        event__attempt_id__in=options["attempt_id"],
                        state=EventDeliveryState.EXHAUSTED,
                    ).values_list("id", flat=True)
                ]
            except ValidationError as exc:
                raise CommandError("attempt identifiers must be UUIDs") from exc
            if not delivery_ids and not options["event_id"]:
                self.stdout.write("no exhausted deliveries for the selected attempts.")
                return
        try:
            report = redrive_event_deliveries(
                delivery_ids=delivery_ids,
                event_ids=options["event_id"],
                confirm=options["confirm"],
            )
        except RuntimeDomainError as exc:
            raise CommandError(str(exc)) from exc
        mode = "confirmed" if options["confirm"] else "dry-run"
        self.stdout.write(
            f"{mode}: validated {report.validated} delivery(s); "
            f"redriven {report.redriven}; skipped {report.skipped}."
        )
