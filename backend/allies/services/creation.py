from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from uuid import UUID

from django.db import IntegrityError, transaction

from allies.exceptions import IdempotencyConflict, OnboardingInvalid
from allies.models import (
    Ally,
    AllyBinding,
    LabelGenerationState,
    OnboardingAttempt,
    ProvisioningOperation,
)
from allies.services.onboarding import (
    _native_attempt_binding,
    digest_value,
    normalize_multiline_field,
    normalize_seed,
)
from auths.config import digest_key
from auths.models import User
from chat.exceptions import ChatError
from chat.services.conversations import (
    ensure_default_conversation,
    reconcile_onboarding_reply,
)
from common.uuids import canonical_uuid
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


def _legacy_crlf_fingerprints(
    operation: ProvisioningOperation,
    values: dict[str, str],
    attempt_token_digest: str,
) -> set[str]:
    ally = operation.binding.ally
    if "\r\n" not in ally.job and "\r\n" not in ally.personality:
        return set()
    try:
        job = normalize_multiline_field(ally.job, max_length=200)
        personality = normalize_multiline_field(ally.personality, max_length=4000)
    except ValueError:
        return set()
    if (job, personality) != (values["job"], values["personality"]):
        return set()
    retained = {**values, "job": ally.job, "personality": ally.personality}
    return {
        _fingerprint(retained),
        _fingerprint({**retained, "onboarding_attempt_digest": attempt_token_digest}),
    }


def _load_result(
    operation: ProvisioningOperation,
    fingerprint: str,
    legacy_fingerprint: str,
    values: dict[str, str],
    onboarding_attempt: str,
    browser_binding: bytes | None,
):
    accepted_fingerprints = {fingerprint, legacy_fingerprint}
    if operation.content_fingerprint not in accepted_fingerprints and (
        operation.content_fingerprint
        not in _legacy_crlf_fingerprints(
            operation, values, digest_value(onboarding_attempt)
        )
    ):
        raise IdempotencyConflict("idempotency key conflicts with accepted content")
    try:
        attempt = operation.binding.ally.onboarding_attempt
    except OnboardingAttempt.DoesNotExist as exc:
        raise IdempotencyConflict(
            "idempotency key conflicts with accepted content"
        ) from exc
    if attempt.consumed_at is None or not hmac.compare_digest(
        attempt.attempt_token_digest, digest_value(onboarding_attempt)
    ):
        raise IdempotencyConflict("idempotency key conflicts with accepted content")
    binding = (
        browser_binding
        if browser_binding is not None
        else _native_attempt_binding(onboarding_attempt)
    )
    if not hmac.compare_digest(attempt.browser_binding_digest, digest_value(binding)):
        raise IdempotencyConflict("idempotency key conflicts with accepted content")
    return AllyCreationResult(operation.binding.ally, operation, True)


def create_ally(
    *,
    user: User,
    workspace_id: UUID | str,
    name: str,
    job: str,
    personality: str,
    appearance_catalog_version: str,
    appearance_key: str,
    onboarding_attempt: str,
    reply: str,
    browser_binding: bytes | None,
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
        or (
            browser_binding is not None
            and (not isinstance(browser_binding, bytes) or not browser_binding)
        )
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
    attempt_token_digest = digest_value(onboarding_attempt)
    legacy_fingerprint = _fingerprint(values)
    fingerprint = _fingerprint(
        {**values, "onboarding_attempt_digest": attempt_token_digest}
    )
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
        return (
            _load_result(
                operation,
                fingerprint,
                legacy_fingerprint,
                values,
                onboarding_attempt,
                browser_binding,
            )
            if operation
            else None
        )

    if existing := existing_result():
        return existing

    try:
        with transaction.atomic():
            if existing := existing_result():
                return existing
            try:
                attempt = OnboardingAttempt.objects.select_for_update().get(
                    attempt_token_digest=attempt_token_digest
                )
            except OnboardingAttempt.DoesNotExist as exc:
                raise OnboardingInvalid("onboarding attempt unavailable") from exc
            if existing := existing_result():
                return existing
            binding = (
                browser_binding
                if browser_binding is not None
                else _native_attempt_binding(onboarding_attempt)
            )
            if not hmac.compare_digest(
                attempt.browser_binding_digest, digest_value(binding)
            ):
                raise OnboardingInvalid("onboarding attempt unavailable")
            if not attempt.is_usable():
                raise OnboardingInvalid("onboarding attempt unavailable")
            try:
                expected = (
                    attempt.name,
                    normalize_multiline_field(attempt.job, max_length=200),
                    normalize_multiline_field(attempt.personality, max_length=4000),
                    attempt.appearance_catalog_version,
                    attempt.appearance_key,
                )
            except ValueError as exc:
                raise OnboardingInvalid("onboarding content changed") from exc
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
                label_generation_state=LabelGenerationState.PENDING,
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
            ensure_default_conversation(
                ally=ally,
                greeting=attempt.greeting,
                reply=values["reply"],
            )
            transaction.on_commit(_enqueue_dispatch)
            transaction.on_commit(
                lambda ally_id=ally.pk: _enqueue_label_generation(ally_id)
            )
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


def _enqueue_label_generation(ally_id: UUID) -> None:
    try:
        from allies.tasks import generate_ally_label_task

        generate_ally_label_task.delay(str(ally_id))
    except Exception:  # noqa: BLE001 - beat recovery owns broker failures.
        return


def retrieve_ally(*, user: User, workspace_id: UUID | str, ally_id: UUID | str) -> Ally:
    context = require_workspace_capability(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.PROFILE_READ,
    )
    try:
        parsed_ally_id = canonical_uuid(ally_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("ally unavailable") from exc
    ally = Ally.objects.select_related(
        "workspace", "binding", "binding__provisioning_operation"
    ).get(workspace=context.workspace, pk=parsed_ally_id)
    try:
        attempt = ally.onboarding_attempt
    except OnboardingAttempt.DoesNotExist:
        return ally
    if attempt.consumed_at is not None and attempt.reply:
        try:
            ensure_default_conversation(
                ally=ally,
                greeting=attempt.greeting,
                reply=attempt.reply,
            )
            reconcile_onboarding_reply(ally=ally)
        except ChatError:
            # Conversation repair remains owned by the chat read boundary; Ally
            # retrieval retains its existing product contract for malformed data.
            pass
    return ally


def list_allies(*, user: User, workspace_id: UUID | str) -> tuple[Ally, ...]:
    context = require_workspace_capability(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.PROFILE_READ,
    )
    return tuple(
        Ally.objects.select_related("binding", "binding__provisioning_operation")
        .filter(workspace=context.workspace)
        .order_by("-created_at", "-id")
    )
