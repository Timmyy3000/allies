from django.core.management.base import BaseCommand, CommandError

from auths.exceptions import ValidationError
from auths.services.cleanup import cleanup_auth_artifacts


class Command(BaseCommand):
    help = "Perform one bounded cleanup pass over expired auth and avatar artifacts."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        try:
            result = cleanup_auth_artifacts(batch_size=batch_size)
        except ValidationError as exc:
            raise CommandError("batch-size must be between 1 and 100") from exc
        self.stdout.write(
            f"flows={result.flows} refresh_tokens={result.refresh_tokens} "
            f"avatars={result.avatars} failures={result.failures}"
        )
        if result.failures:
            raise CommandError(f"{result.failures} avatar cleanup operations failed")
