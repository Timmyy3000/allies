"""Upgrade idle workspace compute through the existing fenced lifecycle."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections.abc import Mapping
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from runtime.exceptions import RuntimeConflictError
from runtime.models import (
    Attempt,
    Execution,
    Lease,
    RuntimeCredential,
    RuntimeOperationState,
    Workspace,
    WorkspaceProvisioningPhase,
)
from runtime.providers import MachineState, ProviderRetryableError

from .continuity_proof import (
    FlyCliSecretStore,
    ProofCredentialBootstrap,
    ProofCredentialHandle,
    ProofDependencyCredentialHandle,
    proof_workspace_spec,
)
from .release_targets import is_pending_release_target
from .runtime_readiness import advance_runtime_start_epoch_locked
from .workspaces import WorkspaceLifecycle, WorkspaceSpec

# Covers bounded lifecycle retries and secret staging, without a second worker.
RELEASE_CLAIM_SECONDS = 1200
_RELEASE_IMAGE_KEYS = frozenset({"allies-runtime", "hermes"})
_IMMUTABLE_IMAGE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$", re.IGNORECASE)
logger = logging.getLogger(__name__)


def runtime_release_digest(images: Mapping[str, str]) -> str | None:
    """Return the stable identity of one exact two-container release."""

    if set(images) != _RELEASE_IMAGE_KEYS or any(
        not isinstance(image, str) or not _IMMUTABLE_IMAGE.fullmatch(image)
        for image in images.values()
    ):
        return None
    payload = json.dumps(
        {"images": sorted((str(name), image) for name, image in images.items())},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def current_runtime_release_digest(workspace: Workspace) -> str | None:
    """Derive the release identity from the provider-proven image pair."""

    applied_images = workspace.applied_images
    if not isinstance(applied_images, Mapping):
        return None
    target = workspace.release_target
    if isinstance(target, Mapping) and "images" in target:
        target_images = target.get("images")
        if not isinstance(target_images, Mapping) or dict(target_images) != dict(
            applied_images
        ):
            return None
    return runtime_release_digest(applied_images)


def resume_runtime_releases(provider, *, limit):
    from .runtime_power import RuntimePowerReport

    report = {"examined": 0, "awaiting_readiness": 0, "failed": 0}
    ids = list(
        Workspace.objects.exclude(release_target={})
        .exclude(
            provisioning_phase=WorkspaceProvisioningPhase.FAILED,
        )
        .filter(
            Q(activation_claim_expires_at__isnull=True)
            | Q(activation_claim_expires_at__lte=timezone.now()),
            release_target__has_key="attempts",
            release_target__attempts__lt=5,
        )
        .order_by("updated_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    for workspace_id in ids:
        report["examined"] += 1
        try:
            result = reconcile_workspace_release(workspace_id, provider=provider)
            if result == "awaiting_readiness":
                report["awaiting_readiness"] += 1
        except Exception as exc:  # noqa: BLE001 - keep processing other wakes
            logger.error(
                "Runtime release resume failed: workspace_id=%s error_type=%s",
                workspace_id,
                type(exc).__name__,
            )
            report["failed"] += 1
    return RuntimePowerReport(**report)


def desired_images() -> dict[str, str]:
    images = {
        "allies-runtime": os.environ.get("RUNTIME_IMAGE", "").strip(),
        "hermes": os.environ.get("HERMES_IMAGE", "").strip(),
    }
    if not any(images.values()):
        return {}
    if any(
        not re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", image)
        for image in images.values()
    ):
        raise ValueError("RUNTIME_IMAGE and HERMES_IMAGE require immutable digests")
    return images


def release_on_wake(workspace, machine, claim, provider) -> bool:
    """Return true when replacement owns the wake; never restart old images."""
    if (
        os.environ.get("ALLIES_RUNTIME_IMAGE_UPDATES_ENABLED", "true").lower()
        == "false"
    ):
        return False
    target = (
        workspace.release_target
        if is_pending_release_target(workspace.release_target)
        else {}
    )
    images = target.get("images") or desired_images()
    if not images or machine.state is not MachineState.STOPPED:
        return False
    if dict(machine.images) == images:
        Workspace.objects.filter(pk=workspace.id, machine_ref=machine.id).update(
            applied_images=images,
        )
        return False
    result = reconcile_workspace_release(
        workspace.id,
        provider=provider,
        wake_claim=claim,
    )
    if result == "current":
        return False
    if result != "awaiting_readiness":
        raise RuntimeConflictError("workspace cannot upgrade while busy")
    return True


def reconcile_workspace_release(
    workspace_id: UUID,
    *,
    provider,
    wake_claim=None,
    secret_store=None,
) -> str:
    from .runtime_power import _inspect_machine, _verify_machine_binding

    workspace = Workspace.objects.get(pk=workspace_id)
    target = (
        workspace.release_target
        if is_pending_release_target(workspace.release_target)
        else {}
    )
    images = target.get("images") or desired_images()
    if not images and not target:
        raise ValueError("No desired runtime release is configured")
    machine = None
    if not target:
        machine = _inspect_machine(provider, workspace)
        _verify_machine_binding(workspace, machine)
        if dict(machine.images) == images:
            Workspace.objects.filter(pk=workspace.id, machine_ref=machine.id).update(
                applied_images=images,
            )
            return "current"
    token = _claim_release(workspace.id, machine, images, wake_claim)
    if token is None:
        return "busy"
    workspace.refresh_from_db()
    target = workspace.release_target
    try:
        store = secret_store or FlyCliSecretStore()
        operation_id = UUID(target["credential_id"])
        generation = target["source_generation"] + 1
        credential = RuntimeCredential.objects.filter(pk=operation_id).first()
        if credential is None:
            handle = ProofCredentialBootstrap(store).prepare(
                workspace.id,
                workspace.fly_app_ref,
                generation=generation,
                operation_id=operation_id,
            )
        else:
            if (
                credential.workspace_id != workspace.id
                or credential.machine_generation != generation
                or credential.revoked_at is not None
            ):
                raise RuntimeConflictError("release credential does not match")
            handle = ProofCredentialHandle(
                workspace_id=workspace.id,
                app_ref=workspace.fly_app_ref,
                generation=generation,
                operation_id=operation_id,
                credential_id=credential.id,
                secret_name=f"ALLIES_FND008_G{generation}_{operation_id.hex[:16].upper()}",
                credential_ref="file:///run/secrets/foundry-runtime-token",
                raw_token="",
            )
        base = WorkspaceSpec(
            organization=target["organization"],
            region=target["region"],
            runtime_image=target["images"]["allies-runtime"],
            hermes_image=target["images"]["hermes"],
        )
        spec = proof_workspace_spec(
            base,
            target["foundry_origin"],
            handle,
            ProofDependencyCredentialHandle(
                app_ref=workspace.fly_app_ref,
                hermes_key_secret_name="ALLIES_FND008_HERMES_KEY",
                provider_key_secret_name="ALLIES_FND008_OPENAI_KEY",
            ),
            activity_wait_enabled=settings.ALLIES_RUNTIME_ACTIVITY_WAIT_ENABLED,
            rich_approvals_enabled=settings.ALLIES_RICH_APPROVALS_ENABLED,
        )
        WorkspaceLifecycle(provider, jitter=False).replace_machine(
            workspace.id,
            spec,
            target["source_generation"],
        )
        return "awaiting_readiness"
    except Exception:
        # Keep the pinned target and generation so an explicit retry resumes it.
        Workspace.objects.filter(pk=workspace.id, activation_claim_token=token).update(
            activation_claim_token=None,
            activation_claim_expires_at=None,
        )
        raise


@transaction.atomic
def _claim_release(workspace_id, machine, images, wake_claim):
    from .runtime_power import ACTIVE_ATTEMPT_STATES, ACTIVE_LEASE_STATES

    workspace = Workspace.objects.select_for_update().get(pk=workspace_id)
    now = timezone.now()
    if workspace.provisioning_phase == WorkspaceProvisioningPhase.FAILED:
        raise RuntimeConflictError("workspace requires provisioning repair")
    if wake_claim is not None:
        if (
            workspace.runtime_operation_id != wake_claim.operation_id
            or workspace.activation_claim_token != wake_claim.token
            or workspace.runtime_operation_state != RuntimeOperationState.STARTING
        ):
            raise RuntimeConflictError("wake claim is stale")
    elif (
        workspace.activation_claim_token
        and workspace.activation_claim_expires_at
        and workspace.activation_claim_expires_at > now
    ):
        return None
    if not is_pending_release_target(workspace.release_target):
        if workspace.provisioning_phase != WorkspaceProvisioningPhase.IDLE:
            return None
        if (
            machine.id != workspace.machine_ref
            or machine.ownership.generation != workspace.machine_generation
        ):
            raise RuntimeConflictError("workspace binding changed")
        if machine.state not in (MachineState.STOPPED, MachineState.STARTED):
            raise ProviderRetryableError("workspace is changing power state")
        if (
            wake_claim is None
            and workspace.runtime_operation_state != RuntimeOperationState.IDLE
        ):
            return None
        if (
            Attempt.objects.filter(
                execution__workspace_id=workspace.id,
                status__in=ACTIVE_ATTEMPT_STATES,
            ).exists()
            or Lease.objects.filter(
                profile__workspace_id=workspace.id,
                state__in=ACTIVE_LEASE_STATES,
            ).exists()
            or Execution.objects.filter(
                workspace_id=workspace.id, status="running"
            ).exists()
        ):
            return None
        # Queued prompts are preserved on a stopped machine and wait for readiness.
        if machine.state is MachineState.STARTED and (
            workspace.speculative_keep_warm_until is None
            or workspace.speculative_keep_warm_until > now
            or Execution.objects.filter(
                workspace_id=workspace.id, status="queued"
            ).exists()
        ):
            return None
        origin = os.environ.get("FOUNDRY_ORIGIN", "").strip()
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("FOUNDRY_ORIGIN is required for image updates")
        admission = {
            key: value
            for key, value in (workspace.release_target or {}).items()
            if key == "routine_admission"
        }
        workspace.release_target = {
            **admission,
            "images": images,
            "source_generation": workspace.machine_generation,
            "credential_id": str(uuid4()),
            "region": machine.region,
            "organization": os.environ.get("FLY_ORG", "allies"),
            "foundry_origin": origin,
            "attempts": 0,
        }
        advance_runtime_start_epoch_locked(workspace)
    workspace.release_target["attempts"] += 1
    token = uuid4().hex
    workspace.activation_claim_token = token
    workspace.activation_claim_expires_at = now + timedelta(
        seconds=RELEASE_CLAIM_SECONDS
    )
    workspace.runtime_operation_id = workspace.runtime_operation_id or uuid4()
    workspace.runtime_operation_state = RuntimeOperationState.STARTING
    workspace.runtime_operation_requested_at = now
    workspace.save()
    return token
