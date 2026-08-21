from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

from django.db import IntegrityError, transaction

from allies.exceptions import IdempotencyConflict, OnboardingInvalid
from allies.models import Ally, AllyBinding, OnboardingAttempt, ProvisioningOperation
from allies.services.onboarding import digest_value, normalize_seed
from auths.config import digest_key
from auths.models import User
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability


@dataclass(frozen=True, slots=True)
class AllyCreationResult:
    ally: Ally
    operation: ProvisioningOperation
    replayed: bool


def _key_digest(value: str) -> str:
    return hmac.new(digest_key(), value.encode(), hashlib.sha256).hexdigest()


def _fingerprint(payload: dict[str, str]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _load_result(operation: ProvisioningOperation, fingerprint: str):
    if operation.content_fingerprint != fingerprint:
        raise IdempotencyConflict("idempotency key conflicts with accepted content")
    return AllyCreationResult(operation.binding.ally, operation, True)


def create_ally(
    *,
    user: User,
    workspace_id: str,
    name: str,
    job: str,
    personality: str,
    appearance_catalog_version: str,
    appearance_key: str,
    onboarding_attempt: str,
    reply: str,
    browser_binding: bytes,
    idempotency_key: str,
) -> AllyCreationResult:
    context = require_workspace_capability(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.WORKSPACE_WRITE,
    )
    if (
        not isinstance(onboarding_attempt, str)
        or not 32 <= len(onboarding_attempt) <= 256
        or not onboarding_attempt.strip()
        or not isinstance(browser_binding, bytes)
        or not browser_binding
    ):
        raise OnboardingInvalid("onboarding attempt is invalid")
    if (
        not isinstance(idempotency_key, str)
        or not idempotency_key.strip()
        or not 16 <= len(idempotency_key) <= 128
    ):
        raise OnboardingInvalid("idempotency key is invalid")
    values = normalize_seed(
        name=name,
        job=job,
        personality=personality,
        appearance_catalog_version=appearance_catalog_version,
        appearance_key=appearance_key,
    )
    if not isinstance(reply, str) or not reply.strip() or len(reply) > 4000:
        raise OnboardingInvalid("onboarding reply is invalid")
    values["reply"] = reply
    fingerprint = _fingerprint(values)
    key_digest = _key_digest(idempotency_key)

    def existing_result():
        operation = (
            ProvisioningOperation.objects.select_related("binding__ally")
            .filter(
                workspace=context.workspace,
                user=user,
                api_idempotency_key_digest=key_digest,
            )
            .first()
        )
        return _load_result(operation, fingerprint) if operation else None

    if existing := existing_result():
        return existing

    try:
        with transaction.atomic():
            if existing := existing_result():
                return existing
            try:
                attempt = OnboardingAttempt.objects.select_for_update().get(
                    attempt_token_digest=digest_value(onboarding_attempt)
                )
            except OnboardingAttempt.DoesNotExist as exc:
                raise OnboardingInvalid("onboarding attempt unavailable") from exc
            if existing := existing_result():
                return existing
            if not hmac.compare_digest(
                attempt.browser_binding_digest, digest_value(browser_binding)
            ):
                raise OnboardingInvalid("onboarding attempt unavailable")
            if not attempt.is_usable():
                raise OnboardingInvalid("onboarding attempt unavailable")
            expected = (
                attempt.name,
                attempt.job,
                attempt.personality,
                attempt.appearance_catalog_version,
                attempt.appearance_key,
            )
            submitted = (
                values["name"],
                values["job"],
                values["personality"],
                values["appearance_catalog_version"],
                values["appearance_key"],
            )
            if expected != submitted:
                raise OnboardingInvalid("onboarding content changed")
            ally = Ally.objects.create(
                workspace=context.workspace,
                **{key: value for key, value in values.items() if key != "reply"},
            )
            binding = AllyBinding.objects.create(ally=ally)
            operation = ProvisioningOperation.objects.create(
                binding=binding,
                workspace=context.workspace,
                user=user,
                api_idempotency_key_digest=key_digest,
                content_fingerprint=fingerprint,
            )
            attempt.consume(user=user, ally=ally, reply=values["reply"])
            transaction.on_commit(_enqueue_dispatch)
            return AllyCreationResult(ally, operation, False)
    except IntegrityError:
        if existing := existing_result():
            return existing
        raise


def _enqueue_dispatch() -> None:
    try:
        from allies.tasks import dispatch_due_provisioning_task

        dispatch_due_provisioning_task.delay()
    # The operation is durable and beat will claim it; broker failure must not
    # turn a committed create into a false API failure.
    except Exception:  # noqa: BLE001
        return


def retrieve_ally(*, user: User, workspace_id: str, ally_id: str) -> Ally:
    context = require_workspace_capability(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.PROFILE_READ,
    )
    return Ally.objects.select_related(
        "workspace", "binding", "binding__provisioning_operation"
    ).get(workspace=context.workspace, public_id=ally_id)
