from django.core.management.base import BaseCommand, CommandError

from waitlist.services.cleanup import cleanup_waitlist_entries


class Command(BaseCommand):
    help = "Delete expired waitlist entries in a bounded batch."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args, **options):
        try:
            result = cleanup_waitlist_entries(batch_size=options["batch_size"])
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(f"Deleted {result.deleted} waitlist entries")
        )
