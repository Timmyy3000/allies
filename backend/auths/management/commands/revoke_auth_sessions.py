from uuid import UUID

from auths.models import SessionFamily
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = "Revoke Cloud authentication session families without accepting raw tokens."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--user-id")
        group.add_argument("--family-id")
        parser.add_argument("--reason", required=True)

    def handle(self, *args, **options):
        reason = options["reason"].strip()
        if not reason or len(reason) > 64:
            raise CommandError("reason is required")
        try:
            family_id = UUID(options["family_id"]) if options.get("family_id") else None
            user_id = UUID(options["user_id"]) if options.get("user_id") else None
            if family_id is not None and str(family_id) != options["family_id"]:
                raise ValueError
            if user_id is not None and str(user_id) != options["user_id"]:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise CommandError("identifier must be a canonical UUID") from exc
        with transaction.atomic():
            if family_id is not None:
                families = SessionFamily.objects.select_for_update().filter(
                    pk=family_id
                )
            else:
                families = SessionFamily.objects.select_for_update().filter(
                    user_id=user_id, revoked_at__isnull=True
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
