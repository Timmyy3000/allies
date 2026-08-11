from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from auths.models import AuthFlow, RefreshToken
from auths.services.avatars import cleanup_avatar_assets


class Command(BaseCommand):
    help = "Perform one bounded cleanup pass over expired auth and avatar artifacts."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        if not 1 <= batch_size <= 100:
            raise CommandError("batch-size must be between 1 and 100")
        now = timezone.now()
        with transaction.atomic():
            flow_ids = list(
                AuthFlow.objects.filter(expires_at__lt=now)
                .order_by("expires_at", "pk")
                .values_list("pk", flat=True)[:batch_size]
            )
            flow_count, _ = AuthFlow.objects.filter(pk__in=flow_ids).delete()
            token_ids = list(
                RefreshToken.objects.filter(
                    expires_at__lt=now, family__absolute_expires_at__lt=now
                )
                .order_by("expires_at", "pk")
                .values_list("pk", flat=True)[:batch_size]
            )
            token_count, _ = RefreshToken.objects.filter(pk__in=token_ids).delete()
        deleted, failed = cleanup_avatar_assets(batch_size=batch_size)
        self.stdout.write(
            f"flows={flow_count} refresh_tokens={token_count} avatars={deleted} failures={failed}"
        )
        if failed:
            raise CommandError(f"{failed} avatar cleanup operations failed")
