from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from auths.models import SessionFamily


class Command(BaseCommand):
    help = "Revoke Cloud authentication session families without accepting raw tokens."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--actor-id")
        group.add_argument("--family-id")
        parser.add_argument("--reason", required=True)

    def handle(self, *args, **options):
        reason = options["reason"].strip()
        if not reason or len(reason) > 64:
            raise CommandError("reason is required")
        with transaction.atomic():
            if options.get("family_id"):
                families = SessionFamily.objects.select_for_update().filter(
                    public_id=options["family_id"]
                )
            else:
                families = SessionFamily.objects.select_for_update().filter(
                    actor__public_id=options["actor_id"], revoked_at__isnull=True
                )
            count = 0
            now = timezone.now()
            for family in families:
                if family.revoked_at is None:
                    family.revoked_at = now
                    family.revoke_reason = reason
                    family.save(update_fields=("revoked_at", "revoke_reason"))
                    count += 1
        self.stdout.write(f"revoked={count}")
