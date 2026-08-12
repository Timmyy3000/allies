from __future__ import annotations

import base64
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from runtime.exceptions import RuntimeConflictError, RuntimeFencedError
from runtime.models import (
    Attempt,
    AttemptStatus,
    ConversationBinding,
    Execution,
    ExecutionEvent,
    ExecutionStatus,
    RuntimeCredential,
    RuntimeProfile,
    Workspace,
)
from runtime.providers import (
    ContainerFileSecret,
    ContainerSpec,
    MachineState,
    ProviderNotFoundError,
    ProviderRetryableError,
)
from runtime.services.executions import create_execution
from runtime.services.profiles import ProfileSeed, ensure_runtime_profile
from runtime.services.runtime_auth import (
    RuntimeCredentialIssue,
    authenticate_runtime_token_for_claim,
    issue_runtime_credential_for_generation,
    revoke_runtime_credential,
)
from runtime.services.workspaces import (
    ReplacementProofPrecondition,
    WorkspaceLifecycle,
    WorkspaceSpec,
)

_CREDENTIAL_REF = "file:///run/secrets/foundry-runtime-token"
HERMES_PROOF_CREDENTIAL_REF = "file:///run/secrets/hermes-api-key"
OPENAI_PROOF_CREDENTIAL_REF = "file:///run/secrets/openai-api-key"
_HERMES_KEY_PATH = "/opt/data/.allies-secrets/key"
_HERMES_RUNTIME_KEY_PATH = "/run/secrets/hermes-api-key"
_SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_SAFE_FLY_SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SAFE_BASE64 = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
_FLY_CLI_TIMEOUT_SECONDS = 15
_FLY_DEPLOY_TIMEOUT_SECONDS = 180
_CLEANUP_TIMEOUT_SECONDS = 30
_CLEANUP_POLL_SECONDS = 1


class ProofSecretStore(Protocol):
    def stage(self, app_ref: str, secret_name: str, encoded_value: str) -> None: ...

    def remove(self, app_ref: str, secret_name: str) -> None: ...

    def remove_many(self, app_ref: str, secret_names: tuple[str, ...]) -> None: ...


class ProofProgressDriver(Protocol):
    def __call__(self, stage: str, state: ProofRunState) -> None: ...


class _FlySecretCommandError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class FlyCliSecretStore:
    """Stage proof secrets through stdin so values never enter argv."""

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or _default_fly_executable()

    def stage(self, app_ref: str, secret_name: str, encoded_value: str) -> None:
        self._validate_secret_name(secret_name)
        if (
            not isinstance(encoded_value, str)
            or len(encoded_value) > 8192
            or len(encoded_value) % 4 != 0
            or not _SAFE_BASE64.fullmatch(encoded_value)
        ):
            raise ValueError("Fly file secret value must be bounded base64")
        self._run(
            ("secrets", "import", "--stage", "--app", app_ref),
            input_value=f"{secret_name}={encoded_value}\n",
        )

    def remove(self, app_ref: str, secret_name: str) -> None:
        self.remove_many(app_ref, (secret_name,))

    def remove_many(self, app_ref: str, secret_names: tuple[str, ...]) -> None:
        if not secret_names:
            return
        for secret_name in secret_names:
            self._validate_secret_name(secret_name)
        self._run(
            ("secrets", "unset", *secret_names, "--app", app_ref),
            timeout_seconds=_FLY_DEPLOY_TIMEOUT_SECONDS,
        )
        listed = self._run(("secrets", "list", "--app", app_ref, "--json"))
        try:
            payload = json.loads(listed.stdout)
            remaining = {
                str(item.get("Name") or item.get("name"))
                for item in payload
                if isinstance(item, dict)
            }
        except (TypeError, json.JSONDecodeError) as exc:
            raise _FlySecretCommandError("fly_secret_cleanup_verification_invalid") from exc
        if remaining.intersection(secret_names):
            raise _FlySecretCommandError("fly_secret_cleanup_incomplete")

    def bootstrap_release(
        self, app_ref: str, image: str, region: str
    ) -> tuple[str, str]:
        """Create the first Fly release so staged app secrets become active."""

        if not _SAFE_SLUG.fullmatch(app_ref) or not _SAFE_SLUG.fullmatch(region):
            raise ValueError("Fly release bootstrap identifiers are invalid")
        if not re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", image, re.IGNORECASE):
            raise ValueError("Fly release bootstrap image must use an immutable digest")
        descriptor, config_path = tempfile.mkstemp(suffix=".toml")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as config:
                config.write(
                    f'app = "{app_ref}"\n'
                    f'primary_region = "{region}"\n\n'
                    "[build]\n"
                    f'image = "{image}"\n\n'
                    "[experimental]\n"
                    'entrypoint = ["/bin/sh", "-c", "sleep 1800"]\n\n'
                    "[[vm]]\n"
                    'memory = "256mb"\n'
                    'cpu_kind = "shared"\n'
                    "cpus = 1\n"
                )
            self._run(
                (
                    "deploy",
                    "--config",
                    config_path,
                    "--app",
                    app_ref,
                    "--ha=false",
                    "--yes",
                ),
                timeout_seconds=_FLY_DEPLOY_TIMEOUT_SECONDS,
            )
            release = self._release_metadata(app_ref)
            self._stop_bootstrap_machine(app_ref, release)
            return release
        finally:
            Path(config_path).unlink(missing_ok=True)

    def deploy(self, app_ref: str) -> tuple[str, str]:
        """Promote secrets staged after the app's first release."""

        self._run(
            ("secrets", "deploy", "--app", app_ref),
            timeout_seconds=_FLY_DEPLOY_TIMEOUT_SECONDS,
        )
        return self._release_metadata(app_ref)

    def _release_metadata(self, app_ref: str) -> tuple[str, str]:
        completed = self._run(("machine", "list", "--app", app_ref, "--json"))
        try:
            machines = json.loads(completed.stdout)
            candidates = [
                (
                    item["config"]["metadata"]["fly_release_id"],
                    str(item["config"]["metadata"]["fly_release_version"]),
                )
                for item in machines
                if item.get("config", {})
                .get("metadata", {})
                .get("fly_release_id")
            ]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise _FlySecretCommandError("fly_release_metadata_invalid") from exc
        if not candidates:
            raise _FlySecretCommandError("fly_release_metadata_missing")
        release_id, version = max(candidates, key=lambda item: int(item[1]))
        if not re.fullmatch(r"rel_[A-Za-z0-9]+", release_id) or not version.isdigit():
            raise _FlySecretCommandError("fly_release_metadata_invalid")
        return release_id, version

    def _stop_bootstrap_machine(
        self, app_ref: str, release: tuple[str, str]
    ) -> None:
        completed = self._run(("machine", "list", "--app", app_ref, "--json"))
        try:
            machines = json.loads(completed.stdout)
            candidates = [
                str(item["id"])
                for item in machines
                if (
                    item.get("config", {}).get("metadata", {}).get("fly_release_id"),
                    str(
                        item.get("config", {})
                        .get("metadata", {})
                        .get("fly_release_version", "")
                    ),
                )
                == release
            ]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise _FlySecretCommandError("fly_release_metadata_invalid") from exc
        if len(candidates) != 1 or not _SAFE_SLUG.fullmatch(candidates[0]):
            raise _FlySecretCommandError("fly_release_metadata_invalid")
        self._run(("machine", "stop", candidates[0], "--app", app_ref))

    @staticmethod
    def _validate_secret_name(secret_name: str) -> None:
        if not isinstance(secret_name, str) or not _SAFE_FLY_SECRET_NAME.fullmatch(
            secret_name
        ):
            raise ValueError("Fly secret name is invalid")

    def _run(
        self,
        args: tuple[str, ...],
        *,
        input_value: str | None = None,
        timeout_seconds: float = _FLY_CLI_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                (self.executable, *args),
                input=input_value,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            code = (
                "fly_secret_release_bootstrap_timeout"
                if args[:1] == ("deploy",)
                else "fly_secret_deploy_timeout"
                if args[:2] == ("secrets", "deploy")
                else "fly_secret_cleanup_timeout"
                if args[:2] == ("secrets", "unset")
                else "fly_secret_command_timeout"
            )
            raise _FlySecretCommandError(code) from exc
        except OSError as exc:
            raise _FlySecretCommandError("fly_secret_command_unavailable") from exc
        if completed.returncode != 0:
            code = (
                "fly_secret_release_bootstrap_failed"
                if args[:1] == ("deploy",)
                else "fly_secret_deploy_failed"
                if args[:2] == ("secrets", "deploy")
                else "fly_secret_cleanup_failed"
                if args[:2] == ("secrets", "unset")
                else "fly_secret_command_failed"
            )
            raise _FlySecretCommandError(code)
        return completed


@dataclass(frozen=True, slots=True)
class ProofCredentialHandle:
    workspace_id: UUID
    app_ref: str
    generation: int
    operation_id: UUID
    credential_id: UUID | None
    secret_name: str
    credential_ref: str
    raw_token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProofDependencyCredentialHandle:
    app_ref: str
    hermes_key_secret_name: str
    provider_key_secret_name: str
    hermes_credential_ref: str = HERMES_PROOF_CREDENTIAL_REF
    provider_credential_ref: str = OPENAI_PROOF_CREDENTIAL_REF


class ProofDependencyCredentialBootstrap:
    """Stage the proof-only Hermes and provider credentials as Fly files."""

    def __init__(
        self,
        secret_store: ProofSecretStore,
        *,
        provider_api_key: str,
        hermes_key_factory: Callable[[], str] | None = None,
    ) -> None:
        self.secret_store = secret_store
        self._provider_api_key = _bounded_credential(
            provider_api_key, "provider API key"
        )
        self._hermes_key_factory = hermes_key_factory or (
            lambda: secrets.token_urlsafe(48)
        )
        self._handle: ProofDependencyCredentialHandle | None = None

    def prepare(self, app_ref: str) -> ProofDependencyCredentialHandle:
        if self._handle is not None:
            if self._handle.app_ref != app_ref:
                raise ValueError("proof dependency credentials were reused")
            return self._handle
        hermes_key = _bounded_credential(
            self._hermes_key_factory(), "Hermes API key", minimum=16
        )
        handle = ProofDependencyCredentialHandle(
            app_ref=app_ref,
            hermes_key_secret_name="ALLIES_FND008_HERMES_KEY",
            provider_key_secret_name="ALLIES_FND008_OPENAI_KEY",
        )
        values = (
            (handle.hermes_key_secret_name, hermes_key),
            (handle.provider_key_secret_name, self._provider_api_key),
        )
        staged: list[str] = []
        try:
            for name, value in values:
                encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
                self.secret_store.stage(app_ref, name, encoded)
                staged.append(name)
        except Exception:
            for name in reversed(staged):
                try:
                    self.secret_store.remove(app_ref, name)
                except Exception:  # noqa: BLE001, S110 - preserve original failure
                    pass
            raise
        self._handle = handle
        return handle

    def cleanup(self, handle: ProofDependencyCredentialHandle) -> None:
        failures: list[Exception] = []
        for name in (
            handle.provider_key_secret_name,
            handle.hermes_key_secret_name,
        ):
            try:
                self.secret_store.remove(handle.app_ref, name)
            except Exception as exc:  # noqa: BLE001 - every secret gets an attempt
                failures.append(exc)
        self._handle = None
        if failures:
            raise RuntimeError(
                "proof dependency credential cleanup failed"
            ) from failures[0]


def _bounded_credential(value: str, name: str, *, minimum: int = 1) -> str:
    if (
        not isinstance(value, str)
        or not minimum <= len(value) <= 4096
        or "\r" in value
        or "\n" in value
    ):
        raise ValueError(f"{name} is invalid")
    return value


class ProofCredentialBootstrap:
    """Own one in-memory bearer and one staged Fly secret per generation."""

    def __init__(
        self,
        secret_store: ProofSecretStore,
        *,
        token_factory: Callable[[], str] | None = None,
        credential_issuer: Callable[..., RuntimeCredentialIssue] = (
            issue_runtime_credential_for_generation
        ),
        credential_revoker: Callable[[UUID], None] = revoke_runtime_credential,
    ) -> None:
        self.secret_store = secret_store
        self.token_factory = token_factory or (lambda: secrets.token_urlsafe(48))
        self.credential_issuer = credential_issuer
        self.credential_revoker = credential_revoker
        self._handles: dict[UUID, ProofCredentialHandle] = {}

    def prepare(
        self,
        workspace_id: UUID,
        app_ref: str,
        *,
        generation: int,
        operation_id: UUID,
        issue: bool = True,
    ) -> ProofCredentialHandle:
        existing = self._handles.get(operation_id)
        if existing is not None:
            if (
                existing.workspace_id != workspace_id
                or existing.app_ref != app_ref
                or existing.generation != generation
            ):
                raise ValueError("proof credential operation was reused")
            return self.issue(existing) if issue else existing
        token = self.token_factory()
        secret_name = f"ALLIES_FND008_G{generation}_{operation_id.hex[:16].upper()}"
        encoded = base64.b64encode(token.encode("utf-8")).decode("ascii")
        self.secret_store.stage(app_ref, secret_name, encoded)
        handle = ProofCredentialHandle(
            workspace_id=workspace_id,
            app_ref=app_ref,
            generation=generation,
            operation_id=operation_id,
            credential_id=None,
            secret_name=secret_name,
            credential_ref=_CREDENTIAL_REF,
            raw_token=token,
        )
        self._handles[operation_id] = handle
        return self.issue(handle) if issue else handle

    def issue(self, handle: ProofCredentialHandle) -> ProofCredentialHandle:
        existing = self._handles.get(handle.operation_id)
        if existing != handle:
            raise ValueError("proof credential handle is unavailable")
        if handle.credential_id is not None:
            return handle
        try:
            issued = self.credential_issuer(
                handle.workspace_id,
                handle.generation,
                handle.raw_token,
                handle.operation_id,
            )
        except Exception:
            self.secret_store.remove(handle.app_ref, handle.secret_name)
            self._handles.pop(handle.operation_id, None)
            raise
        active = replace(handle, credential_id=issued.credential.id)
        self._handles[handle.operation_id] = active
        return active

    def cleanup(self, handle: ProofCredentialHandle) -> None:
        failures: list[Exception] = []
        if handle.credential_id is not None:
            try:
                self.credential_revoker(handle.credential_id)
            except Exception as exc:  # noqa: BLE001 - both cleanup legs must run
                failures.append(exc)
        try:
            self.secret_store.remove(handle.app_ref, handle.secret_name)
        except Exception as exc:  # noqa: BLE001 - both cleanup legs must run
            failures.append(exc)
        finally:
            self._handles.pop(handle.operation_id, None)
        if failures:
            raise RuntimeError("proof credential cleanup failed") from failures[0]


def _cleanup_proof_credentials(
    credential_bootstrap: ProofCredentialBootstrap,
    handles: tuple[ProofCredentialHandle, ...],
    dependency_bootstrap: ProofDependencyCredentialBootstrap | None,
    dependency_handle: ProofDependencyCredentialHandle | None,
) -> None:
    """Revoke database credentials and batch Fly secret removal by store/app."""

    failures: list[Exception] = []
    groups: list[tuple[ProofSecretStore, str, list[str]]] = []

    def add_secret(store: ProofSecretStore, app_ref: str, secret_name: str) -> None:
        for existing_store, existing_app, names in groups:
            if existing_store is store and existing_app == app_ref:
                names.append(secret_name)
                return
        groups.append((store, app_ref, [secret_name]))

    for handle in handles:
        if handle.credential_id is not None:
            try:
                credential_bootstrap.credential_revoker(handle.credential_id)
            except Exception as exc:  # noqa: BLE001 - all cleanup legs must run
                failures.append(exc)
        credential_bootstrap._handles.pop(handle.operation_id, None)
        add_secret(
            credential_bootstrap.secret_store,
            handle.app_ref,
            handle.secret_name,
        )

    if dependency_bootstrap is not None and dependency_handle is not None:
        dependency_bootstrap._handle = None
        add_secret(
            dependency_bootstrap.secret_store,
            dependency_handle.app_ref,
            dependency_handle.provider_key_secret_name,
        )
        add_secret(
            dependency_bootstrap.secret_store,
            dependency_handle.app_ref,
            dependency_handle.hermes_key_secret_name,
        )

    for store, app_ref, names in groups:
        remove_many = getattr(store, "remove_many", None)
        try:
            if callable(remove_many):
                remove_many(app_ref, tuple(names))
            else:
                for name in names:
                    store.remove(app_ref, name)
        except Exception as exc:  # noqa: BLE001 - provider cleanup must still run
            failures.append(exc)

    if failures:
        raise RuntimeError("proof credential cleanup failed") from failures[0]


def _proof_credentials_revoked(handles: tuple[ProofCredentialHandle, ...]) -> bool:
    credential_ids = tuple(
        handle.credential_id for handle in handles if handle.credential_id is not None
    )
    if not credential_ids:
        return True
    try:
        rows = tuple(
            RuntimeCredential.objects.filter(pk__in=credential_ids).values_list(
                "id", "revoked_at"
            )
        )
        return {credential_id for credential_id, _revoked_at in rows} == set(
            credential_ids
        ) and all(revoked_at is not None for _credential_id, revoked_at in rows)
    except Exception:  # noqa: BLE001 - cleanup verification fails closed
        return False


@dataclass(frozen=True, slots=True)
class ProofProfile:
    alias: str
    profile_id: UUID
    ally_ref: str
    seed: ProfileSeed
    recognizable_fact: str


@dataclass(frozen=True, slots=True)
class ContinuityProofConfig:
    run_id: str
    workspace_id: UUID
    tenant_ref: str
    foundry_origin: str
    workspace_spec: WorkspaceSpec
    profiles: tuple[ProofProfile, ProofProfile]
    timeout_seconds: float = 600.0
    poll_interval: float = 0.25

    def __post_init__(self) -> None:
        if not _SAFE_SLUG.fullmatch(self.run_id):
            raise ValueError("run_id must be a bounded lowercase slug")
        if len({profile.profile_id for profile in self.profiles}) != 2:
            raise ValueError("proof profiles must be distinct")
        if not 0 < self.timeout_seconds <= 900:
            raise ValueError("timeout_seconds must be between 0 and 900")
        if not 0 < self.poll_interval <= 5:
            raise ValueError("poll_interval must be between 0 and 5")


@dataclass(frozen=True, slots=True)
class ProofCheck:
    name: str
    status: Literal["pass", "fail"]
    detail_code: str

    def __post_init__(self) -> None:
        if not _SAFE_CODE.fullmatch(self.name) or not _SAFE_CODE.fullmatch(
            self.detail_code
        ):
            raise ValueError("proof checks require bounded safe codes")


@dataclass(frozen=True, slots=True)
class ProofRunState:
    workspace_id: UUID
    profile_ids: tuple[UUID, UUID]
    execution_ids: tuple[UUID, ...] = ()
    generation: int = 0


@dataclass(frozen=True, slots=True)
class ContinuityProofResult:
    run_id: str
    status: Literal["pass", "fail", "skipped", "incomplete_cleanup"]
    checks: tuple[ProofCheck, ...]
    workspace: dict[str, str | int]
    resources: dict[str, str]
    executions: tuple[dict[str, Any], ...]
    sessions: tuple[dict[str, str | bool], ...]
    cleanup: Literal["complete", "incomplete"]

    @property
    def exit_code(self) -> int:
        return {
            "pass": 0,
            "fail": 1,
            "skipped": 2,
            "incomplete_cleanup": 3,
        }[self.status]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "checks": [asdict(item) for item in self.checks],
            "workspace": dict(self.workspace),
            "resources": dict(self.resources),
            "executions": [dict(item) for item in self.executions],
            "sessions": [dict(item) for item in self.sessions],
            "cleanup": self.cleanup,
        }


def run_machine_replacement_proof(
    config: ContinuityProofConfig,
    *,
    provider: Any,
    credential_bootstrap: ProofCredentialBootstrap,
    dependency_credential_bootstrap: ProofDependencyCredentialBootstrap | None = None,
    bootstrap_secrets: Callable[[str, str, str], Any] | None = None,
    activate_staged_secrets: Callable[[str], Any] | None = None,
    progress: ProofProgressDriver | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    old_token_probe: Callable[[str], bool] | None = None,
) -> ContinuityProofResult:
    """Run one owned, deterministic Machine-replacement continuity proof."""

    progress = progress or (lambda _stage, _state: None)
    mutated = False
    workspace_created = False
    handles: list[ProofCredentialHandle] = []
    dependency_handle: ProofDependencyCredentialHandle | None = None
    resources: dict[str, str] = {}
    checks: list[ProofCheck] = []
    executions: list[dict[str, Any]] = []
    sessions: list[dict[str, str | bool]] = []
    old_generation = 0
    new_generation = 0
    failure_code: str | None = None
    cleanup_complete = True
    deadline = clock() + config.timeout_seconds
    lifecycle = WorkspaceLifecycle(
        provider,
        sleep=sleep,
        jitter=False,
        phase_deadline_seconds=min(config.timeout_seconds, 180),
    )
    state = ProofRunState(
        workspace_id=config.workspace_id,
        profile_ids=tuple(profile.profile_id for profile in config.profiles),
    )

    try:
        capability = getattr(provider, "assert_proof_capabilities", None)
        if capability is None:
            capability = provider.assert_topology_supported
        capability()
        checks.append(ProofCheck("provider_preflight", "pass", "capabilities_ready"))

        workspace, workspace_created = Workspace.objects.get_or_create(
            id=config.workspace_id,
            defaults={"tenant_ref": config.tenant_ref},
        )
        if (
            not workspace_created
            or workspace.tenant_ref != config.tenant_ref
            or workspace.machine_generation != 0
        ):
            raise RuntimeError("workspace_not_fresh")
        app_spec = config.workspace_spec.app_spec(config.workspace_id)
        resources["app"] = app_spec.name
        # App creation may succeed remotely even when its response is lost.
        # From this point cleanup must reconcile the exact proof-owned name.
        mutated = True
        app = provider.ensure_app(app_spec)
        resources["app"] = app.name
        if dependency_credential_bootstrap is not None:
            dependency_handle = dependency_credential_bootstrap.prepare(app.name)

        first_handle = credential_bootstrap.prepare(
            workspace.id,
            app.name,
            generation=1,
            operation_id=UUID(bytes=secrets.token_bytes(16)),
        )
        handles.append(first_handle)
        second_handle = credential_bootstrap.prepare(
            workspace.id,
            app.name,
            generation=2,
            operation_id=UUID(bytes=secrets.token_bytes(16)),
            issue=False,
        )
        handles.append(second_handle)
        first_spec = _spec_for_handle(config, first_handle, dependency_handle)
        if bootstrap_secrets is not None:
            release_metadata = bootstrap_secrets(
                app.name,
                config.workspace_spec.runtime_image,
                config.workspace_spec.region,
            )
            _set_provider_release_metadata(provider, release_metadata)
        first_binding = lifecycle.ensure_workspace(workspace.id, first_spec)
        second_handle = credential_bootstrap.issue(second_handle)
        handles[-1] = second_handle
        old_generation = first_binding.machine_generation
        resources.update(
            {
                "volume": first_binding.volume_ref,
                "old_machine": first_binding.machine_ref,
            }
        )
        checks.append(ProofCheck("initial_machine", "pass", "generation_one_ready"))

        for profile in config.profiles:
            ensure_runtime_profile(
                workspace.id,
                profile.profile_id,
                profile.ally_ref,
                profile.seed,
            )
        state = replace(state, generation=old_generation)
        _wait_for(
            "profiles_generation_one",
            state,
            progress,
            lambda: (
                RuntimeProfile.objects.filter(
                    pk__in=state.profile_ids,
                    materialized_generation=old_generation,
                ).count()
                == 2
            ),
            deadline,
            clock,
            sleep,
            config.poll_interval,
        )

        first_turns = tuple(
            create_execution(
                workspace.id,
                profile.profile_id,
                f"{config.run_id}-first-{profile.alias}",
                {
                    "message": (
                        f"Remember this proof fact for {profile.alias}: "
                        f"{profile.recognizable_fact}"
                    ),
                    "cloud_conversation_ref": f"{config.run_id}-{profile.alias}",
                },
            )
            for profile in config.profiles
        )
        state = replace(state, execution_ids=tuple(item.id for item in first_turns))
        _wait_for(
            "first_turns",
            state,
            progress,
            lambda: _executions_succeeded(state.execution_ids),
            deadline,
            clock,
            sleep,
            config.poll_interval,
        )
        before_sessions = _session_map(state.profile_ids)
        if len(before_sessions) != 2:
            raise RuntimeError("first_sessions_missing")
        checks.append(ProofCheck("isolated_first_turns", "pass", "sessions_bound"))

        active = tuple(
            create_execution(
                workspace.id,
                profile.profile_id,
                f"{config.run_id}-active-{profile.alias}",
                {
                    "message": (
                        f"Keep this proof stream active for {profile.alias}. "
                        f"The continuity marker is: {profile.recognizable_fact}"
                    ),
                    "cloud_conversation_ref": f"{config.run_id}-{profile.alias}",
                    "proof_expected_history_marker": profile.recognizable_fact,
                    "proof_forbidden_history_marker": config.profiles[
                        1 - index
                    ].recognizable_fact,
                    "proof_hold_after_first_safe_event": True,
                },
            )
            for index, profile in enumerate(config.profiles)
        )
        queued = create_execution(
            workspace.id,
            config.profiles[0].profile_id,
            f"{config.run_id}-queued-{config.profiles[0].alias}",
            {
                "message": f"Continue as {config.profiles[0].alias}.",
                "cloud_conversation_ref": f"{config.run_id}-{config.profiles[0].alias}",
            },
        )
        state = replace(
            state,
            execution_ids=tuple(item.id for item in (*active, queued)),
        )
        precondition = _wait_for_active_precondition(
            state,
            queued.id,
            progress,
            deadline,
            clock,
            sleep,
            config.poll_interval,
        )
        checks.append(ProofCheck("active_overlap", "pass", "two_streams_and_queue"))

        second_spec = _spec_for_handle(config, second_handle, dependency_handle)
        replacement = lifecycle.replace_machine(
            workspace.id,
            second_spec,
            old_generation,
            precondition,
        )
        new_generation = replacement.machine_generation
        if replacement.volume_ref != first_binding.volume_ref:
            raise RuntimeError("replacement_volume_changed")
        inspect_old = getattr(provider, "inspect_machine_by_id", None)
        if inspect_old is None:
            raise RuntimeError("old_machine_inspection_unavailable")

        def old_machine_destroyed() -> bool:
            machine = inspect_old(app.name, first_binding.machine_ref)
            return machine is None or machine.state is MachineState.DESTROYED

        _wait_for(
            "old_machine_destroyed",
            state,
            progress,
            old_machine_destroyed,
            deadline,
            clock,
            sleep,
            config.poll_interval,
        )
        resources["replacement_machine"] = replacement.machine_ref
        checks.append(ProofCheck("machine_replacement", "pass", "volume_preserved"))

        probe = old_token_probe or _default_old_token_probe
        if not probe(first_handle.raw_token):
            raise RuntimeError("old_generation_token_accepted")
        checks.append(ProofCheck("generation_fence", "pass", "old_claim_rejected"))

        state = replace(state, generation=new_generation)
        _wait_for(
            "replacement_profiles",
            state,
            progress,
            lambda: (
                RuntimeProfile.objects.filter(
                    pk__in=state.profile_ids,
                    materialized_generation=new_generation,
                ).count()
                == 2
            ),
            deadline,
            clock,
            sleep,
            config.poll_interval,
        )
        resumed = tuple(
            create_execution(
                workspace.id,
                profile.profile_id,
                f"{config.run_id}-resume-{profile.alias}",
                {
                    "message": (
                        f"Reply with the exact proof fact for {profile.alias} only."
                    ),
                    "cloud_conversation_ref": f"{config.run_id}-{profile.alias}",
                    "proof_expected_history_marker": profile.recognizable_fact,
                    "proof_forbidden_history_marker": config.profiles[
                        1 - index
                    ].recognizable_fact,
                },
            )
            for index, profile in enumerate(config.profiles)
        )
        state = replace(
            state,
            execution_ids=tuple(item.id for item in (*active, queued, *resumed)),
        )
        def replacement_recovered() -> bool:
            failed_receipt = (
                Attempt.objects.filter(
                    execution_id__in=tuple(item.id for item in resumed),
                    status=AttemptStatus.FAILED,
                )
                .order_by("execution_id", "number")
                .values_list("terminal_receipt", flat=True)
                .first()
            )
            if isinstance(failed_receipt, dict):
                code = failed_receipt.get("code")
                safe_code = (
                    code
                    if isinstance(code, str) and _SAFE_CODE.fullmatch(code)
                    else "failed"
                )
                failure = RuntimeError(f"replacement_recovery_{safe_code}")
                raise failure
            return (
                Execution.objects.filter(
                    pk__in=tuple(item.id for item in active),
                    status=ExecutionStatus.FAILED,
                ).count()
                == 2
                and _executions_succeeded(tuple(item.id for item in (queued, *resumed)))
            )

        _wait_for(
            "replacement_recovery",
            state,
            progress,
            replacement_recovered,
            deadline,
            clock,
            sleep,
            config.poll_interval,
        )
        _assert_profile_fact_continuity(config.profiles, resumed)
        after_sessions = _session_map(state.profile_ids)
        for profile in config.profiles:
            sessions.append(
                {
                    "profile_alias": profile.alias,
                    "resumed": before_sessions.get(profile.profile_id)
                    == after_sessions.get(profile.profile_id),
                    "isolated": after_sessions.get(profile.profile_id)
                    not in {
                        value
                        for key, value in after_sessions.items()
                        if key != profile.profile_id
                    },
                }
            )
        if not all(item["resumed"] and item["isolated"] for item in sessions):
            raise RuntimeError("session_continuity_failed")
        evidence_profiles = (*config.profiles, config.profiles[0], *config.profiles)
        evidence_executions = (*active, queued, *resumed)
        for index, (profile, execution) in enumerate(
            zip(evidence_profiles, evidence_executions, strict=True)
        ):
            attempt_rows = tuple(
                Attempt.objects.filter(execution=execution)
                .order_by("number")
                .values_list("id", "machine_generation")
            )
            generations = {generation for _attempt_id, generation in attempt_rows}
            expected_generations = {old_generation} if index < 2 else {new_generation}
            if generations != expected_generations:
                raise RuntimeError("execution_generation_history_invalid")
            attempts = tuple(str(attempt_id) for attempt_id, _ in attempt_rows)
            executions.append(
                {
                    "execution_id": str(execution.id),
                    "profile_alias": profile.alias,
                    "attempt_ids": attempts,
                    "terminal_state": (
                        ExecutionStatus.FAILED
                        if index < 2
                        else ExecutionStatus.SUCCEEDED
                    ),
                }
            )
        checks.append(ProofCheck("continuity_recovery", "pass", "history_complete"))
    except Exception as exc:  # noqa: BLE001 - result exposes only a bounded code
        failure_code = _safe_failure_code(exc)
        checks.append(ProofCheck("proof_run", "fail", failure_code))
    finally:
        credential_cleanup_complete = True
        try:
            _cleanup_proof_credentials(
                credential_bootstrap,
                tuple(reversed(handles)),
                dependency_credential_bootstrap,
                dependency_handle,
            )
        except Exception:  # noqa: BLE001 - provider cleanup must still run
            credential_cleanup_complete = False
        provider_cleanup_complete = True
        if mutated:
            try:
                _record_current_machine(config.workspace_id, resources)
            except Exception:  # noqa: BLE001 - provider cleanup must still run
                provider_cleanup_complete = False
            provider_cleanup_complete = (
                _cleanup_provider_resources(
                    provider,
                    resources,
                    clock=clock,
                    sleep=sleep,
                )
                and provider_cleanup_complete
            )
        if not credential_cleanup_complete and provider_cleanup_complete:
            # Destroying the app authoritatively removes its scoped Fly secrets.
            # Recover only when every independently stored bearer is also proven
            # revoked; a database cleanup failure must remain fail-closed.
            credential_cleanup_complete = _proof_credentials_revoked(
                tuple(handles)
            )
        cleanup_complete = credential_cleanup_complete and provider_cleanup_complete
        if cleanup_complete and workspace_created:
            Workspace.objects.filter(pk=config.workspace_id).delete()

    if not cleanup_complete:
        status: Literal["pass", "fail", "skipped", "incomplete_cleanup"] = (
            "incomplete_cleanup"
        )
    elif failure_code is not None:
        status = "fail" if mutated else "skipped"
    else:
        status = "pass"
    return ContinuityProofResult(
        run_id=config.run_id,
        status=status,
        checks=tuple(checks),
        workspace={
            "workspace_id": str(config.workspace_id),
            "old_generation": old_generation,
            "new_generation": new_generation,
        },
        resources=resources,
        executions=tuple(executions),
        sessions=tuple(sessions),
        cleanup="complete" if cleanup_complete else "incomplete",
    )


def _spec_for_handle(
    config: ContinuityProofConfig,
    handle: ProofCredentialHandle,
    dependency_handle: ProofDependencyCredentialHandle | None = None,
) -> WorkspaceSpec:
    containers = config.workspace_spec.containers
    runtime_credential_ref = config.workspace_spec.runtime_credential_ref
    if dependency_handle is not None:
        if (
            not config.workspace_spec.hermes_image
            or not config.workspace_spec.runtime_image
        ):
            raise ValueError("proof dependency files require both runtime images")
        containers = (
            ContainerSpec(
                "hermes",
                config.workspace_spec.hermes_image,
                command=_hermes_proof_command(dependency_handle),
                healthchecks=(
                    _proof_process_healthcheck("hermes"),
                ),
                environment={
                    "HERMES_HOME": "/opt/data",
                    "API_SERVER_HOST": "127.0.0.1",
                    "API_SERVER_PORT": "8642",
                    "GATEWAY_MULTIPLEX_PROFILES": "true",
                },
                secret_files=(
                    ContainerFileSecret(
                        "/run/secrets/hermes-api-key",
                        dependency_handle.hermes_key_secret_name,
                    ),
                ),
            ),
            ContainerSpec(
                "allies-runtime",
                config.workspace_spec.runtime_image,
                entrypoint=_runtime_proof_command(handle, dependency_handle),
                environment={
                    "HERMES_REQUEST_TIMEOUT": "180",
                    "HERMES_STREAM_TIMEOUT": "180",
                },
                healthchecks=(
                    _proof_process_healthcheck(
                        "allies-runtime",
                        (
                            _HERMES_RUNTIME_KEY_PATH,
                            "/run/secrets/openai-api-key",
                            "/run/secrets/foundry-runtime-token",
                        ),
                    ),
                ),
                secret_files=(
                    ContainerFileSecret(
                        "/run/secrets/hermes-api-key",
                        dependency_handle.hermes_key_secret_name,
                    ),
                    ContainerFileSecret(
                        "/run/secrets/openai-api-key",
                        dependency_handle.provider_key_secret_name,
                    ),
                ),
            ),
        )
        runtime_credential_ref = dependency_handle.hermes_credential_ref
    return replace(
        config.workspace_spec,
        containers=containers,
        runtime_credential_ref=runtime_credential_ref,
        foundry_origin=config.foundry_origin,
        foundry_runtime_credential_ref=handle.credential_ref,
        foundry_runtime_credential_secret_name=handle.secret_name,
    )


def _set_provider_release_metadata(provider: Any, metadata: Any) -> None:
    if metadata is None:
        return
    if (
        not isinstance(metadata, tuple)
        or len(metadata) != 2
        or not all(isinstance(item, str) for item in metadata)
    ):
        raise RuntimeError("provider_release_metadata_invalid")
    setter = getattr(provider, "set_release_metadata", None)
    if setter is None:
        raise RuntimeError("provider_release_metadata_unsupported")
    setter(*metadata)


def _hermes_proof_command(
    dependency_handle: ProofDependencyCredentialHandle,
) -> tuple[str, ...]:
    if not _SAFE_FLY_SECRET_NAME.fullmatch(
        dependency_handle.hermes_key_secret_name
    ):
        raise ValueError("Fly secret name is invalid")
    secret_name = dependency_handle.hermes_key_secret_name
    command = (
        f"p={_HERMES_KEY_PATH};umask 77;mkdir -p ${{p%/*}};"
        f'[ -s $p ]||printf %s "${secret_name}"|base64 -d >$p||exit 1;'
        f"unset {secret_name};"
        's=/opt/data/gateway_state.json;'
        '[ ! -L "$s" ]&&{ [ ! -e "$s" ]||[ -f "$s" ]; }||exit 1;'
        't=$(mktemp /opt/data/.gateway-state.XXXXXX)||exit 1;'
        "echo '{\"desired_state\":\"stopped\"}'>\"$t\"&&"
        'chown 10000:10000 "$t"&&mv -fT -- "$t" "$s"'
        '||{ rm -f -- "$t";exit 1; };'
        'export API_SERVER_KEY="$(cat $p)";'
        "exec hermes gateway run --no-supervise"
    )
    chunk_size = 200
    chunks = tuple(
        command[offset : offset + chunk_size]
        for offset in range(0, len(command), chunk_size)
    )
    return ("sh", "-c", 'eval "$(printf %s "$@")"', "allies-proof", *chunks)


def _runtime_proof_command(
    handle: ProofCredentialHandle,
    dependency_handle: ProofDependencyCredentialHandle,
) -> tuple[str, ...]:
    secret_files = (
        (
            dependency_handle.hermes_key_secret_name,
            _HERMES_RUNTIME_KEY_PATH,
        ),
        (
            dependency_handle.provider_key_secret_name,
            "/run/secrets/openai-api-key",
        ),
        (handle.secret_name, "/run/secrets/foundry-runtime-token"),
    )
    if not all(_SAFE_FLY_SECRET_NAME.fullmatch(name) for name, _ in secret_files):
        raise ValueError("Fly secret name is invalid")
    materialize = "".join(
        f"if [ ! -s {path} ]; then "
        f'printf %s "${name}" | base64 -d > {path} || exit 1; fi; '
        f"unset {name}; "
        for name, path in secret_files
    )
    return (
        "sh",
        "-c",
        "umask 077; mkdir -p /run/secrets; "
        + materialize
        + f"test -s {_HERMES_RUNTIME_KEY_PATH}"
        " && test -s /run/secrets/openai-api-key"
        " && test -s /run/secrets/foundry-runtime-token"
        " || exit 1; chown 10000:10000 /run/secrets"
        + f" {_HERMES_RUNTIME_KEY_PATH}"
        + " /run/secrets/openai-api-key"
        + " /run/secrets/foundry-runtime-token"
        + "; chmod 0700 /run/secrets"
        + f"; chmod 0600 {_HERMES_RUNTIME_KEY_PATH}"
        + " /run/secrets/openai-api-key"
        + " /run/secrets/foundry-runtime-token"
        + "; attempts=0"
        + '; while [ "$(stat -c %u /opt/data)" != 10000 ]; do '
        + "attempts=$((attempts + 1)); "
        + '[ "$attempts" -lt 60 ] || exit 1; sleep 1; done'
        + "; exec setpriv --reuid=10000 --regid=10000 --clear-groups"
        + " python -m allies_runtime",
    )


def _proof_process_healthcheck(
    name: str, required_secret_paths: tuple[str, ...] = ()
) -> dict[str, object]:
    checks = [
        *(f"test -s {path}" for path in required_secret_paths),
        "test -r /proc/1/stat",
    ]
    return {
        "name": name,
        "exec": {"command": ["/bin/sh", "-c", " && ".join(checks)]},
        "interval": 5,
        "timeout": 2,
        "grace_period": 5,
    }


def _wait_for(
    stage: str,
    state: ProofRunState,
    progress: ProofProgressDriver,
    predicate: Callable[[], bool],
    deadline: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    interval: float,
) -> None:
    while True:
        progress(stage, state)
        if predicate():
            return
        if clock() >= deadline:
            raise RuntimeError(f"{stage}_timeout")
        sleep(interval)


def _wait_for_active_precondition(
    state: ProofRunState,
    queued_execution_id: UUID,
    progress: ProofProgressDriver,
    deadline: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    interval: float,
) -> ReplacementProofPrecondition:
    result: ReplacementProofPrecondition | None = None

    def ready() -> bool:
        nonlocal result
        failed_receipt = (
            Attempt.objects.filter(
                execution_id__in=state.execution_ids[:2],
                status=AttemptStatus.FAILED,
            )
            .order_by("execution_id", "number")
            .values_list("terminal_receipt", flat=True)
            .first()
        )
        if isinstance(failed_receipt, dict):
            code = failed_receipt.get("code")
            safe_code = (
                code
                if isinstance(code, str) and _SAFE_CODE.fullmatch(code)
                else "failed"
            )
            failure = RuntimeError(f"active_streams_{safe_code}")
            raise failure
        attempts = tuple(
            Attempt.objects.filter(
                execution_id__in=state.execution_ids[:2],
                status="running",
            )
            .order_by("execution_id")
            .values_list("id", flat=True)
        )
        if len(attempts) != 2:
            return False
        candidate = ReplacementProofPrecondition(attempts, queued_execution_id)
        workspace = Workspace.objects.get(pk=state.workspace_id)
        try:
            candidate.assert_satisfied(workspace)
        except RuntimeConflictError:
            return False
        result = candidate
        return True

    _wait_for(
        "active_streams",
        state,
        progress,
        ready,
        deadline,
        clock,
        sleep,
        interval,
    )
    if result is None:  # pragma: no cover - guarded by _wait_for
        raise RuntimeError("active_streams_missing")
    return result


def _executions_succeeded(execution_ids: tuple[UUID, ...]) -> bool:
    return Execution.objects.filter(
        pk__in=execution_ids,
        status=ExecutionStatus.SUCCEEDED,
    ).count() == len(execution_ids)


def _session_map(profile_ids: tuple[UUID, UUID]) -> dict[UUID, str]:
    return dict(
        ConversationBinding.objects.filter(profile_id__in=profile_ids).values_list(
            "profile_id", "hermes_session_id"
        )
    )


def _execution_text(execution_id: UUID) -> str:
    successful_attempts = tuple(
        Attempt.objects.filter(
            execution_id=execution_id,
            status=ExecutionStatus.SUCCEEDED,
        ).values_list("id", flat=True)
    )
    if len(successful_attempts) != 1:
        raise RuntimeError("successful_attempt_history_invalid")
    chunks: list[str] = []
    for payload in (
        ExecutionEvent.objects.filter(
            attempt_id=successful_attempts[0],
            event_type="message.delta",
        )
        .order_by("sequence")
        .values_list("payload", flat=True)
    ):
        if isinstance(payload, dict) and isinstance(payload.get("text"), str):
            chunks.append(payload["text"])
    return "".join(chunks)


def _assert_profile_fact_continuity(
    profiles: tuple[ProofProfile, ProofProfile],
    executions: tuple[Execution, Execution],
) -> None:
    for index, (profile, execution) in enumerate(
        zip(profiles, executions, strict=True)
    ):
        if not _history_verified(execution.id):
            raise RuntimeError("profile_fact_continuity_failed")
        output_tokens = set(
            re.findall(r"[a-z0-9]+", _execution_text(execution.id).casefold())
        )
        expected_tokens = _recognizable_fact_tokens(profile.recognizable_fact)
        other_tokens = _recognizable_fact_tokens(
            profiles[1 - index].recognizable_fact
        )
        if not expected_tokens <= output_tokens or other_tokens <= output_tokens:
            raise RuntimeError("profile_fact_continuity_failed")


def _recognizable_fact_tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold())) - {"the", "is"}


def _history_verified(execution_id: UUID) -> bool:
    receipts = tuple(
        Attempt.objects.filter(
            execution_id=execution_id,
            status=AttemptStatus.SUCCEEDED,
        ).values_list("terminal_receipt", flat=True)
    )
    return (
        len(receipts) == 1
        and isinstance(receipts[0], dict)
        and receipts[0].get("history_verified") is True
    )


def _default_old_token_probe(raw_token: str) -> bool:
    try:
        authenticate_runtime_token_for_claim(raw_token)
    except RuntimeFencedError:
        return True
    return False


def _cleanup_provider_resources(
    provider: Any,
    resources: dict[str, str],
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    complete = True
    deadline = clock() + _CLEANUP_TIMEOUT_SECONDS
    app = resources.get("app")
    machines = tuple(
        dict.fromkeys(
            machine
            for key in ("current_machine", "replacement_machine", "old_machine")
            if (machine := resources.get(key))
        )
    )
    for machine in machines if app else ():
        inspected = None
        inspect = getattr(provider, "inspect_machine_by_id", None)
        if inspect is not None:
            try:
                inspected = inspect(app, machine)
                if inspected is None or inspected.state is MachineState.DESTROYED:
                    continue
            except Exception:  # noqa: BLE001 - still attempt authoritative cleanup
                complete = False
        if inspected is None or inspected.state is not MachineState.STOPPED:
            stopped = _retry_cleanup_action(
                lambda machine=machine: provider.stop_machine(app, machine),
                deadline=deadline,
                clock=clock,
                sleep=sleep,
            )
            complete = stopped and complete
            if stopped:
                complete = (
                    _wait_for_cleanup_machine_state(
                        provider,
                        app,
                        machine,
                        {MachineState.STOPPED, MachineState.DESTROYED},
                        deadline=deadline,
                        clock=clock,
                        sleep=sleep,
                    )
                    and complete
                )
        destroyed = _retry_cleanup_action(
            lambda machine=machine: provider.destroy_machine(app, machine),
            deadline=deadline,
            clock=clock,
            sleep=sleep,
        )
        complete = destroyed and complete
        if destroyed:
            complete = (
                _wait_for_cleanup_machine_state(
                    provider,
                    app,
                    machine,
                    {MachineState.DESTROYED},
                    deadline=deadline,
                    clock=clock,
                    sleep=sleep,
                )
                and complete
            )
    if app and resources.get("volume"):
        volume_id = resources["volume"]
        complete = (
            _wait_for_volume_detachment(
                provider,
                app,
                volume_id,
                deadline=deadline,
                clock=clock,
                sleep=sleep,
            )
            and complete
        )
        complete = (
            _retry_cleanup_action(
                lambda: provider.delete_volume(app, volume_id),
                deadline=deadline,
                clock=clock,
                sleep=sleep,
            )
            and complete
        )
    if app:
        complete = (
            _retry_cleanup_action(
                lambda: provider.delete_app(app),
                deadline=deadline,
                clock=clock,
                sleep=sleep,
            )
            and complete
        )
    return complete


def _retry_cleanup_action(
    action: Callable[[], Any],
    *,
    deadline: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> bool:
    while True:
        try:
            action()
            return True
        except ProviderNotFoundError:
            return True
        except ProviderRetryableError:
            if clock() >= deadline:
                return False
            sleep(min(_CLEANUP_POLL_SECONDS, max(0.0, deadline - clock())))
        except Exception:  # noqa: BLE001 - cleanup must attempt remaining resources
            return False


def _wait_for_cleanup_machine_state(
    provider: Any,
    app: str,
    machine: str,
    accepted: set[MachineState],
    *,
    deadline: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> bool:
    inspect = getattr(provider, "inspect_machine_by_id", None)
    if inspect is None:
        return True
    while True:
        try:
            record = inspect(app, machine)
        except ProviderNotFoundError:
            return True
        except ProviderRetryableError:
            if clock() >= deadline:
                return False
            sleep(min(_CLEANUP_POLL_SECONDS, max(0.0, deadline - clock())))
            continue
        except Exception:  # noqa: BLE001 - cleanup result remains bounded
            return False
        if record is None or record.state in accepted:
            return True
        if clock() >= deadline:
            return False
        sleep(min(_CLEANUP_POLL_SECONDS, max(0.0, deadline - clock())))


def _wait_for_volume_detachment(
    provider: Any,
    app: str,
    volume_id: str,
    *,
    deadline: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> bool:
    list_volumes = getattr(provider, "list_volumes", None)
    if list_volumes is None:
        return True
    while True:
        try:
            volumes = tuple(list_volumes(app))
        except ProviderNotFoundError:
            return True
        except ProviderRetryableError:
            if clock() >= deadline:
                return False
            sleep(min(_CLEANUP_POLL_SECONDS, max(0.0, deadline - clock())))
            continue
        except Exception:  # noqa: BLE001 - cleanup result remains bounded
            return False
        matches = [volume for volume in volumes if volume.id == volume_id]
        if not matches or not matches[0].attached_machine_id:
            return True
        if clock() >= deadline:
            return False
        sleep(min(_CLEANUP_POLL_SECONDS, max(0.0, deadline - clock())))


def _record_current_machine(workspace_id: UUID, resources: dict[str, str]) -> None:
    machine_ref = (
        Workspace.objects.filter(pk=workspace_id)
        .values_list("machine_ref", flat=True)
        .first()
    )
    if machine_ref:
        resources["current_machine"] = machine_ref


def _safe_failure_code(exc: Exception) -> str:
    typed_code = getattr(exc, "code", None)
    if isinstance(typed_code, str) and _SAFE_CODE.fullmatch(typed_code):
        return typed_code
    value = str(exc)
    return value if _SAFE_CODE.fullmatch(value) else "proof_step_failed"


def _default_fly_executable() -> str:
    configured = os.environ.get("FLYCTL_PATH")
    if configured:
        return configured
    discovered = shutil.which("fly") or shutil.which("flyctl")
    if discovered:
        return discovered
    for candidate in (
        Path.home() / ".fly" / "bin" / "fly.exe",
        Path.home() / ".fly" / "bin" / "flyctl.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    return "fly"


__all__ = [
    "ContinuityProofConfig",
    "ContinuityProofResult",
    "FlyCliSecretStore",
    "ProofCheck",
    "ProofCredentialBootstrap",
    "ProofCredentialHandle",
    "ProofDependencyCredentialBootstrap",
    "ProofDependencyCredentialHandle",
    "ProofProfile",
    "ProofRunState",
    "ProofSecretStore",
    "run_machine_replacement_proof",
]
