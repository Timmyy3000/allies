from django.core.management.base import BaseCommand, CommandError

from runtime.models import RuntimeOperationState, Workspace
from runtime.services.runtime_provider import runtime_power_provider
from runtime.services.runtime_readiness import is_runtime_ready
from runtime.services.runtime_releases import reconcile_workspace_release


class Command(BaseCommand):
    help = "Upgrade one workspace, or a bounded batch, to the configured image pair."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--workspace", help="Cloud workspace UUID (canary or retry)")
        group.add_argument("--batch", action="store_true")
        parser.add_argument("--limit", type=int, default=1)
        parser.add_argument(
            "--after", help="Continue after this Foundry workspace UUID"
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if not 1 <= limit <= 20:
            raise CommandError("limit must be between 1 and 20")
        query = Workspace.objects.filter(machine_generation__gt=0).order_by("id")
        if options["workspace"]:
            query = query.filter(tenant_ref=options["workspace"])
        if options["after"]:
            from uuid import UUID

            try:
                query = query.filter(id__gt=UUID(options["after"]))
            except ValueError as exc:
                raise CommandError("after must be a workspace UUID") from exc
        workspaces = list(query[:limit])
        if not workspaces:
            self.stdout.write("No matching provisioned workspaces.")
            return
        provider = runtime_power_provider()
        for workspace in workspaces:
            try:
                result = reconcile_workspace_release(workspace.id, provider=provider)
            except Exception as exc:
                raise CommandError(
                    f"Workspace {workspace.id}: {type(exc).__name__}; "
                    "rollout stopped. Inspect lifecycle state and retry this workspace."
                ) from exc
            workspace.refresh_from_db()
            self.stdout.write(
                f"{workspace.id}: {result}; generation={workspace.machine_generation}"
            )
            if result == "awaiting_readiness" or (
                result == "current"
                and workspace.runtime_operation_state
                == RuntimeOperationState.AWAITING_READINESS
                and not is_runtime_ready(workspace)
            ):
                self.stdout.write(
                    "Stopped at the readiness gate. Verify this canary before continuing."
                )
                return
        self.stdout.write(f"Next batch cursor: --after {workspaces[-1].id}")
