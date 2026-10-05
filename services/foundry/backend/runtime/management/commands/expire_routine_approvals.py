from django.core.management.base import BaseCommand

from runtime.services.routines import expire_routine_approvals


class Command(BaseCommand):
    help = "Expire bounded routine approval waits using the database clock."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **options):
        count = expire_routine_approvals(limit=options["limit"])
        self.stdout.write(str(count))
