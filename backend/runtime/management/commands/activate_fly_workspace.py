from __future__ import annotations

import os
from uuid import UUID, uuid4

from django.core.management.base import BaseCommand, CommandError

from runtime.models import RuntimeCredential, Workspace, WorkspaceProvisioningPhase
from runtime.providers import FlyProvider, ProviderError, deterministic_resource_names
from runtime.services.continuity_proof import (
    FlyCliSecretStore,
    ProofCredentialBootstrap,
    ProofCredentialHandle,
    ProofDependencyCredentialBootstrap,
    ProofDependencyCredentialHandle,
    proof_workspace_spec,
)
from runtime.services.workspaces import WorkspaceLifecycle, WorkspaceSpec

_REQUIRED_SETTINGS = (
    "FLY_API_TOKEN",
    "FLY_ORG",
    "FLY_REGION",
    "FOUNDRY_ORIGIN",
    "RUNTIME_IMAGE",
    "HERMES_IMAGE",
    "PROFILE_PROVISIONING_API_KEY",
)
_MACHINE_PHASES = frozenset(
    {
        WorkspaceProvisioningPhase.MACHINE_CREATED,
        WorkspaceProvisioningPhase.MACHINE_STARTED,
        WorkspaceProvisioningPhase.HEALTHY,
    }
)


class Command(BaseCommand):
    help = "Activate one registered workspace on Fly for local end-to-end testing."

    def add_arguments(self, parser):
        parser.add_argument("workspace_id")

    def handle(self, *args, **options):
        workspace = self._workspace(options["workspace_id"])
        workspace_id = workspace.id

        required = {
            name: os.environ.get(name, "").strip() for name in _REQUIRED_SETTINGS
        }
        missing = sorted(name for name, value in required.items() if not value)
        if missing:
            raise CommandError(f"Missing required settings: {', '.join(missing)}")

        names = deterministic_resource_names(workspace_id)
        app_name = names.app
        machine_name = names.machine(
            workspace.provisioning_target_generation
            or workspace.machine_generation
            or 1
        )
        secret_store = FlyCliSecretStore()
        provider = FlyProvider(api_token=required["FLY_API_TOKEN"])
        credential_bootstrap = ProofCredentialBootstrap(secret_store)
        dependency_bootstrap = ProofDependencyCredentialBootstrap(
            secret_store,
            provider_api_key=required["PROFILE_PROVISIONING_API_KEY"],
        )
        credential_handle: ProofCredentialHandle | None = None
        dependency_handle: ProofDependencyCredentialHandle | None = None
        credential_prepared = False
        cleanup_owned_dependencies = False
        existing_machine = None

        try:
            provider.assert_proof_capabilities()
            base_spec = WorkspaceSpec(
                organization=required["FLY_ORG"],
                region=required["FLY_REGION"],
                hermes_image=required["HERMES_IMAGE"],
                runtime_image=required["RUNTIME_IMAGE"],
            )
            app = provider.ensure_app(base_spec.app_spec(workspace_id))
            app_name = app.name

            # A generation is not a readiness proof.  Verify the recorded
            # Machine before reporting a replayed activation as successful.
            workspace.refresh_from_db()
            if (
                workspace.machine_generation > 0
                and workspace.provisioning_phase == WorkspaceProvisioningPhase.IDLE
            ):
                binding = WorkspaceLifecycle(
                    provider, jitter=False
                ).verify_workspace_ready(workspace_id, base_spec)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Workspace {workspace_id} is already active at generation "
                        f"{binding.machine_generation}."
                    )
                )
                return

            target_generation = (
                workspace.provisioning_target_generation
                or workspace.machine_generation
                or 1
            )
            machine_name = workspace.provisioning_machine_name or names.machine(
                target_generation
            )
            existing_machine = provider.inspect_machine(app_name, machine_name)
            credential = self._active_credential(workspace_id, target_generation)

            if existing_machine is None:
                dependency_handle = dependency_bootstrap.prepare(app_name)
                cleanup_owned_dependencies = True
                if credential is None:
                    if target_generation != 1:
                        raise RuntimeError(
                            "a partial workspace is missing its runtime credential"
                        )
                    credential_handle = credential_bootstrap.prepare(
                        workspace_id,
                        app_name,
                        generation=target_generation,
                        operation_id=uuid4(),
                    )
                    credential_prepared = True
                else:
                    credential_handle = self._credential_handle(
                        workspace_id, app_name, target_generation, credential
                    )
            else:
                if credential is None:
                    raise RuntimeError(
                        "an existing workspace Machine has no runtime credential"
                    )
                dependency_handle = ProofDependencyCredentialHandle(
                    app_ref=app_name,
                    hermes_key_secret_name="ALLIES_FND008_HERMES_KEY",
                    provider_key_secret_name="ALLIES_FND008_OPENAI_KEY",
                )
                credential_handle = self._credential_handle(
                    workspace_id, app_name, target_generation, credential
                )

            spec = proof_workspace_spec(
                base_spec,
                required["FOUNDRY_ORIGIN"],
                credential_handle,
                dependency_handle,
            )
            if existing_machine is None:
                provider.set_release_metadata(
                    *secret_store.bootstrap_release(
                        app_name,
                        required["RUNTIME_IMAGE"],
                        required["FLY_REGION"],
                    )
                )
            binding = WorkspaceLifecycle(provider, jitter=False).ensure_workspace(
                workspace_id,
                spec,
            )
        except Exception as exc:
            machine_may_exist = self._machine_may_exist(
                provider,
                workspace_id,
                app_name,
                machine_name,
                existing_machine,
            )
            resumable_failure = isinstance(exc, ProviderError) and exc.retryable
            if (credential_prepared or cleanup_owned_dependencies) and not (
                machine_may_exist or resumable_failure
            ):
                self._cleanup_owned_credentials(
                    credential_bootstrap,
                    credential_handle if credential_prepared else None,
                    dependency_bootstrap,
                    dependency_handle,
                )
            elif credential_handle is not None or dependency_handle is not None:
                self.stderr.write(
                    self.style.WARNING(
                        "Activation failed; retained staged credentials because the "
                        "workspace Machine may already exist. Rerun activation to "
                        "resume it."
                    )
                )
            raise CommandError("Fly workspace activation failed") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Activated workspace {workspace_id} at generation "
                f"{binding.machine_generation}."
            )
        )

    @staticmethod
    def _workspace(value: object) -> Workspace:
        try:
            tenant_ref = str(UUID(value))
            return Workspace.objects.get(tenant_ref=tenant_ref)
        except (TypeError, ValueError, Workspace.DoesNotExist) as exc:
            raise CommandError("workspace_id is not registered") from exc

    @staticmethod
    def _active_credential(
        workspace_id: UUID, generation: int
    ) -> RuntimeCredential | None:
        credentials = tuple(
            RuntimeCredential.objects.filter(
                workspace_id=workspace_id,
                machine_generation=generation,
                revoked_at__isnull=True,
            ).order_by("created_at", "id")
        )
        if len(credentials) > 1:
            raise RuntimeError("multiple active runtime credentials exist")
        return credentials[0] if credentials else None

    @staticmethod
    def _credential_handle(
        workspace_id: UUID,
        app_ref: str,
        generation: int,
        credential: RuntimeCredential,
    ) -> ProofCredentialHandle:
        return ProofCredentialHandle(
            workspace_id=workspace_id,
            app_ref=app_ref,
            generation=generation,
            operation_id=credential.id,
            credential_id=credential.id,
            secret_name=f"ALLIES_FND008_G{generation}_{credential.id.hex[:16].upper()}",
            credential_ref="file:///run/secrets/foundry-runtime-token",
            raw_token="",
        )

    @staticmethod
    def _machine_may_exist(
        provider,
        workspace_id: UUID,
        app_name: str,
        machine_name: str,
        existing_machine,
    ) -> bool:
        """Fail closed before revoking anything after a provider failure."""

        if existing_machine is not None:
            return True
        try:
            workspace = Workspace.objects.get(pk=workspace_id)
            if workspace.machine_ref or workspace.provisioning_phase in _MACHINE_PHASES:
                return True
            return provider.inspect_machine(app_name, machine_name) is not None
        except Exception:  # noqa: BLE001 - uncertainty must retain credentials
            return True

    def _cleanup_owned_credentials(
        self,
        credential_bootstrap: ProofCredentialBootstrap,
        credential_handle: ProofCredentialHandle | None,
        dependency_bootstrap: ProofDependencyCredentialBootstrap,
        dependency_handle: ProofDependencyCredentialHandle | None,
    ) -> None:
        """Attempt cleanup without replacing the original activation failure."""

        failures: list[Exception] = []
        if credential_handle is not None:
            try:
                credential_bootstrap.cleanup(credential_handle)
            except Exception as exc:  # noqa: BLE001 - preserve the original error
                failures.append(exc)
        if dependency_handle is not None:
            try:
                dependency_bootstrap.cleanup(dependency_handle)
            except Exception as exc:  # noqa: BLE001 - preserve the original error
                failures.append(exc)
        if failures:
            self.stderr.write(
                self.style.WARNING(
                    "Activation failed and credential cleanup was incomplete; "
                    "the original activation error is preserved."
                )
            )
