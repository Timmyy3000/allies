"""Move a workspace onto the configured provider at its next generation.

Used to migrate a hosted (Fly) workspace to a self-hosted Docker host: copy
the old Volume's contents into a provider volume first, then run this to
bind that volume and start a fresh Machine generation on it. Generations stay
monotonic, so leases and profile receipts from the old host are fenced off.
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from runtime.models import Workspace, WorkspaceProvisioningPhase
from runtime.providers.domain import AppSpec
from runtime.providers.fly import deterministic_resource_names
from runtime.services.continuity_proof import (
    ProofCredentialBootstrap,
    ProofDependencyCredentialBootstrap,
    proof_workspace_spec,
)
from runtime.services.runtime_provider import runtime_power_provider
from runtime.services.workspaces import WorkspaceLifecycle, WorkspaceSpec


class Command(BaseCommand):
    help = "Rebind a workspace to an existing provider volume at the next generation."

    def add_arguments(self, parser):
        parser.add_argument("workspace_id", type=UUID)
        parser.add_argument("--volume", required=True, help="Provider volume id to bind")

    def handle(self, *args, workspace_id, volume, **options):
        provider = runtime_power_provider()
        store = getattr(provider, "secrets", None)
        if store is None:
            raise CommandError("rehoming needs a provider with a local secret store")
        workspace = Workspace.objects.get(pk=workspace_id)
        if workspace.provisioning_phase != WorkspaceProvisioningPhase.IDLE:
            raise CommandError("workspace provisioning is not idle")
        source = workspace.machine_generation
        names = deterministic_resource_names(workspace.id)
        Workspace.objects.filter(pk=workspace.id).update(
            fly_app_ref=names.app, volume_ref=volume
        )
        provider.ensure_app(AppSpec(names.app, "local", "local"))

        handle = ProofCredentialBootstrap(store).prepare(
            workspace.id, names.app, generation=source + 1, operation_id=uuid4()
        )
        dependencies = ProofDependencyCredentialBootstrap(
            store, provider_api_key=os.environ["PROFILE_PROVISIONING_API_KEY"]
        ).prepare(names.app)
        base = WorkspaceSpec(
            organization="local",
            region="local",
            cpu_kind=settings.WORKSPACE_CPU_KIND,
            cpus=settings.WORKSPACE_CPUS,
            memory_mb=settings.WORKSPACE_MEMORY_MB,
            volume_size_gb=settings.WORKSPACE_VOLUME_SIZE_GB,
            hermes_image=os.environ["HERMES_IMAGE"],
            runtime_image=os.environ["RUNTIME_IMAGE"],
        )
        spec = proof_workspace_spec(
            base,
            os.environ["FOUNDRY_ORIGIN"],
            handle,
            dependencies,
            activity_wait_enabled=settings.ALLIES_RUNTIME_ACTIVITY_WAIT_ENABLED,
            rich_approvals_enabled=settings.ALLIES_RICH_APPROVALS_ENABLED,
        )
        binding = WorkspaceLifecycle(provider, jitter=False).replace_machine(
            workspace.id, spec, source
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Workspace {workspace.id} now runs generation "
                f"{binding.machine_generation} on {binding.machine_ref}."
            )
        )
