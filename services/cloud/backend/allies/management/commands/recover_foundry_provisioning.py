from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from allies.services.provisioning import recover_foundry_rejected


def _uuid(value: str, *, name: str) -> UUID:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as exc:
        raise CommandError(f"{name} must be a canonical UUID") from exc
    if str(parsed) != value:
        raise CommandError(f"{name} must be a canonical UUID")
    return parsed


class Command(BaseCommand):
    help = "Dry-run or requeue legacy Foundry-rejected Ally provisioning operations."

    def add_arguments(self, parser):
        parser.add_argument("--workspace-id", required=True)
        parser.add_argument("--operation-id")
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Apply the recovery. Without this flag the command is a dry run.",
        )

    def handle(self, *args, **options):
        workspace_id = _uuid(options["workspace_id"], name="workspace-id")
        operation_id = (
            _uuid(options["operation_id"], name="operation-id")
            if options.get("operation_id")
            else None
        )
        report = recover_foundry_rejected(
            workspace_id=workspace_id,
            operation_id=operation_id,
            confirm=options["confirm"],
        )
        mode = "confirmed" if options["confirm"] else "dry-run"
        self.stdout.write(
            f"mode={mode} workspace_id={workspace_id} "
            f"matched={report.matched} requeued={report.requeued}"
        )
