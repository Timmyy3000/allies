from __future__ import annotations

import secrets
from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from runtime.exceptions import (
    RuntimeAuthorizationError,
    RuntimeFencedError,
    RuntimeIdempotencyConflictError,
    RuntimeNotReadyError,
    RuntimeValidationError,
)
from runtime.models import (
    IN_FLIGHT_PROVISIONING_PHASES,
    RuntimeCredential,
    Workspace,
)

from .retry import run_with_sqlite_lock_retry
from .validation import digest_lease_token, validate_nonempty


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    """Authentication hint; every mutation re-reads the Workspace in-transaction."""

    workspace_id: UUID
    machine_generation: int
    credential_id: UUID


@dataclass(frozen=True, slots=True)
class RuntimeCredentialIssue:
    credential: RuntimeCredential
    raw_token: str

    def __iter__(self):
        yield self.credential
        yield self.raw_token


def issue_runtime_credential(
    workspace_id: UUID,
    raw_token: str | None = None,
) -> RuntimeCredentialIssue:
    """Issue a test/composition credential without persisting the raw token."""

    token = raw_token or secrets.token_urlsafe(32)
    validate_nonempty(token, "raw_token", max_length=512)

    @transaction.atomic
    def issue_once() -> RuntimeCredentialIssue:
        workspace = Workspace.objects.select_for_update().get(pk=workspace_id)
        _require_ready_workspace(workspace)
        credential = RuntimeCredential.objects.create(
            workspace=workspace,
            token_digest=digest_lease_token(token),
            machine_generation=workspace.machine_generation,
        )
        return RuntimeCredentialIssue(credential, token)

    return run_with_sqlite_lock_retry(issue_once)


def issue_runtime_credential_for_generation(
    workspace_id: UUID,
    generation: int,
    raw_token: str,
    operation_id: UUID,
) -> RuntimeCredentialIssue:
    """Issue or exactly replay one generation-bound proof credential."""

    if type(generation) is not int or generation <= 0:
        raise RuntimeValidationError("generation must be positive")
    if not isinstance(operation_id, UUID):
        raise RuntimeValidationError("operation_id must be a UUID")
    validate_nonempty(raw_token, "raw_token", max_length=512)
    token_digest = digest_lease_token(raw_token)

    @transaction.atomic
    def issue_once() -> RuntimeCredentialIssue:
        workspace = Workspace.objects.select_for_update().get(pk=workspace_id)
        existing = RuntimeCredential.objects.filter(pk=operation_id).first()
        if existing is not None:
            if (
                existing.workspace_id != workspace.id
                or existing.machine_generation != generation
                or existing.token_digest != token_digest
                or existing.revoked_at is not None
            ):
                raise RuntimeIdempotencyConflictError(
                    "credential operation was reused with different content"
                )
            return RuntimeCredentialIssue(existing, raw_token)

        targets_current = generation == workspace.machine_generation
        targets_expected_next = generation == workspace.machine_generation + 1
        if targets_current:
            _require_ready_workspace(workspace)
        elif not targets_expected_next:
            raise RuntimeNotReadyError(
                "credential generation is not the current or next expected target"
            )
        credential = RuntimeCredential.objects.create(
            id=operation_id,
            workspace=workspace,
            token_digest=token_digest,
            machine_generation=generation,
        )
        return RuntimeCredentialIssue(credential, raw_token)

    return run_with_sqlite_lock_retry(issue_once)


def create_runtime_credential(workspace_id: UUID, raw_token: str | None = None) -> str:
    """Convenience composition seam returning only the opaque raw value."""

    return issue_runtime_credential(workspace_id, raw_token).raw_token


def revoke_runtime_credential(credential_id: UUID) -> None:
    RuntimeCredential.objects.filter(pk=credential_id, revoked_at__isnull=True).update(
        revoked_at=timezone.now(), updated_at=timezone.now()
    )


def authenticate_runtime_token(raw_token: str) -> RuntimeContext:
    """Resolve a bearer token to one Workspace/current generation."""

    if not isinstance(raw_token, str) or not raw_token:
        raise RuntimeAuthorizationError("invalid runtime credential")
    digest = digest_lease_token(raw_token)
    credential = (
        RuntimeCredential.objects.select_related("workspace")
        .filter(token_digest=digest)
        .first()
    )
    if credential is None or credential.revoked_at is not None:
        raise RuntimeAuthorizationError("invalid runtime credential")
    workspace = credential.workspace
    if credential.machine_generation != workspace.machine_generation:
        raise RuntimeFencedError("runtime credential belongs to a retired generation")
    _require_ready_workspace(workspace, allow_not_ready=True)
    return RuntimeContext(
        workspace_id=workspace.id,
        machine_generation=credential.machine_generation,
        credential_id=credential.id,
    )


def authenticate_runtime_token_for_claim(raw_token: str) -> RuntimeContext:
    context = authenticate_runtime_token(raw_token)
    workspace = Workspace.objects.get(pk=context.workspace_id)
    _require_ready_workspace(workspace)
    return context


def _require_ready_workspace(
    workspace: Workspace,
    *,
    allow_not_ready: bool = False,
) -> None:
    if (
        workspace.provisioning_phase in IN_FLIGHT_PROVISIONING_PHASES
        or workspace.machine_generation <= 0
        or not workspace.fly_app_ref
        or not workspace.volume_ref
        or not workspace.machine_ref
    ):
        if allow_not_ready:
            return
        raise RuntimeNotReadyError("workspace is not ready for runtime work")


__all__ = [
    "RuntimeContext",
    "RuntimeCredentialIssue",
    "authenticate_runtime_token",
    "authenticate_runtime_token_for_claim",
    "create_runtime_credential",
    "issue_runtime_credential",
    "issue_runtime_credential_for_generation",
    "revoke_runtime_credential",
]
