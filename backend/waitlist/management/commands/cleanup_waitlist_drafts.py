from django.core.management.base import BaseCommand, CommandError

from waitlist.services.cleanup import cleanup_waitlist_drafts


class Command(BaseCommand):
    help = "Perform one bounded cleanup pass over abandoned waitlist drafts."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args, **options):
        try:
            result = cleanup_waitlist_drafts(batch_size=options["batch_size"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"deleted={result.deleted} abandoned={result.abandoned} joined={result.joined}"
        )
