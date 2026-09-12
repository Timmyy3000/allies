from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from allies.exceptions import DeletionConflict, DeletionInvalid, DeletionUnavailable
from allies.models import DeletionOperation, DeletionOperationState
from allies.services import deletion


def _uuid(value: str, *, name: str) -> UUID:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as exc:
        raise CommandError(f"{name} must be a canonical UUID") from exc
    if str(parsed) != value:
        raise CommandError(f"{name} must be a canonical UUID")
    return parsed


class Command(BaseCommand):
    help = (
        "Resume one repair-required Ally deletion after an operator has "
        "verified the failed attempt is safe to retry."
    )

    def add_arguments(self, parser):
        parser.add_argument("--workspace-id", required=True)
        parser.add_argument("--ally-id", required=True)
        parser.add_argument("--expected-attempt-id", required=True)

    def handle(self, *args, **options):
        workspace_id = _uuid(options["workspace_id"], name="workspace-id")
        ally_id = _uuid(options["ally_id"], name="ally-id")
        expected_attempt_id = _uuid(
            options["expected_attempt_id"], name="expected-attempt-id"
        )
        try:
            with transaction.atomic():
                operation = (
                    DeletionOperation.objects.filter(
                        workspace_id=workspace_id, ally_id=ally_id
                    )
                    .only("id")
                    .first()
                )
                if operation is None:
                    raise CommandError("deletion operation unavailable")
                resumed = deletion.resume_ally_deletion(
                    operation_id=operation.id,
                    expected_attempt_id=expected_attempt_id,
                )
                if resumed.state == DeletionOperationState.PENDING:
                    transaction.on_commit(
                        lambda: deletion._enqueue_reconciliation(resumed.id)
                    )
        except (DeletionConflict, DeletionInvalid, DeletionUnavailable) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            f"workspace_id={workspace_id} ally_id={ally_id} "
            f"operation_id={resumed.id} state={resumed.state} "
            f"attempt_id={resumed.attempt_id}"
        )
