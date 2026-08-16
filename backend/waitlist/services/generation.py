"""Bounded, truthful greeting generation with conservative unknown recovery."""

from __future__ import annotations

import hashlib
import re
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..admission import acquire_generation, admit_capability, release_generation
from ..exceptions import (
    AdmissionUnavailable,
    DraftStale,
    DraftUnavailable,
    GenerationUnavailable,
    GenerationUnknown,
    IdempotencyConflict,
    InvalidDraftState,
    OperationInProgress,
    Throttled,
    WaitlistValidationError,
)
from ..idempotency import (
    acknowledgement,
    idempotency_digest,
    mark_failed,
    mark_succeeded,
    mark_unknown,
    request_digest,
    reserve_operation,
)
from ..models import (
    DraftLifecycle,
    OperationKind,
    OperationStatus,
    WaitlistDraft,
    WaitlistOperation,
)
from ..providers.base import (
    GreetingRequest,
    ProviderBilledError,
    ProviderUnavailableError,
    ProviderUnknownError,
)
from ..providers.fake import FakeGreetingProvider
from ..providers.openai import POLICY_VERSION, OpenAIResponsesProvider
from .drafts import configuration_complete, ensure_active

_CAPABILITY_NOUN = (
    r"(?:account|accounts|workspace|workspaces|ally|allies|conversation|"
    r"conversations|tool|tools|memory|memories|file|files|message|messages|"
    r"assistant|assistants)"
)
_CLAIM_SUBJECT = (
    r"(?:i(?:['’](?:m|ve|ll|d))?|we(?:['’](?:re|ve|ll|d))?|"
    r"this\s+assistant)"
)
_ACTION_VERB = (
    r"(?:creat(?:e|ed)|open(?:ed)?|access(?:ed)?|use(?:d)?|call(?:ed)?|"
    r"execut(?:e|ed)|ran|read|wrote|send|sent|set\s+up|deliver(?:ed)?|"
    r"complet(?:e|ed)|"
    r"finish(?:ed)?|remember(?:ed)?|stor(?:e|ed)|sav(?:e|ed))"
)
_ACTION_BRIDGE = (
    r"(?:(?:have|has|had|already|just|now|successfully)\s+|"
    r"(?:go|goes|went|gone)\s+ahead\s+and\s+|"
    r"proceed(?:ed)?\s+to\s+)"
)
_STATE_PREDICATE = r"(?:ready|set\s+up|waiting|live|available|configured|active)"
_MARKUP_CHARACTERS = re.compile(r"[<>]")

# Reject statements that assert a capability or completed action, while
# allowing ordinary discussion of a workspace/account and explicit negation.
# Keeping the subject and action in the pattern avoids the old noun-only false
# positives (for example, "Let's plan your workspace goals").
PROHIBITED_CLAIMS = re.compile(
    rf"""
    \b{_CLAIM_SUBJECT}\s+
       (?!(?:do\s+not|don't|cannot|can't|never|not)\b)
       (?:{_ACTION_BRIDGE})*
       {_ACTION_VERB}\b(?:\s+\w+){{0,5}}\s+{_CAPABILITY_NOUN}\b
    |
    \b{_CLAIM_SUBJECT}\s+
       (?!(?:do\s+not|don't|cannot|can't|never|not)\b)
       (?:am|are|is)\s+(?:(?:an?|your|the)\s+)?(?:\w+\s+){{0,3}}{_CAPABILITY_NOUN}\b
    |
    \b{_CLAIM_SUBJECT}\s+
       (?!(?:do\s+not|don't|cannot|can't|never|not)\b)
       (?:have|has|had)\s+(?:(?:an?|your|the)\s+)?{_CAPABILITY_NOUN}\b
    |
    \b{_CLAIM_SUBJECT}\s+
       (?!(?:do\s+not|don't|cannot|can't|never|not)\b)
       (?:can|could|may|will)\s+(?:{_ACTION_BRIDGE})*{_ACTION_VERB}\b
       (?:\s+\w+){{0,4}}\s+{_CAPABILITY_NOUN}\b
    |
    \b(?:i['’]m|we['’]re)\s+
       (?!(?:do\s+not|don't|cannot|can't|never|not)\b)
       (?:(?:an?|your|the)\s+)?(?:\w+\s+){{0,3}}{_CAPABILITY_NOUN}\b
    |
    \b(?:an?|the|your|this|that)\s+{_CAPABILITY_NOUN}
       \s+(?:was|were|has\s+been|have\s+been|is|are)
       \s+{_ACTION_VERB}\b
    |
    \b(?:an?|the|your|this|that)\s+{_CAPABILITY_NOUN}
       \s+(?:was|were|has\s+been|have\s+been|is|are)\s+
       (?!(?:not|never|no\s+longer)\b)
       (?:\w+\s+){{0,2}}{_STATE_PREDICATE}\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def generation_input_digest(draft: WaitlistDraft) -> str:
    value = (
        f"{draft.name.strip()}\x1f{draft.job.strip()}\x1f{draft.personality.strip()}"
    )
    return hashlib.sha256(value.encode()).hexdigest()


def _greeting_is_current(draft: WaitlistDraft) -> bool:
    return bool(draft.greeting_text) and draft.greeting_policy_version == POLICY_VERSION


def _requires_policy_refresh(draft: WaitlistDraft) -> bool:
    return (
        draft.lifecycle == DraftLifecycle.GREETING_READY
        and bool(draft.greeting_text)
        and not _greeting_is_current(draft)
    )


def validate_output(value: Any) -> str:
    max_chars = int(
        getattr(settings, "ALLIES_WAITLIST_GENERATION_MAX_OUTPUT_CHARS", 1200)
    )
    if not isinstance(value, str):
        raise WaitlistValidationError("greeting output is invalid", field="greeting")
    text = value.strip()
    if (
        not text
        or len(text) > max_chars
        or "\x00" in text
        or _MARKUP_CHARACTERS.search(text)
    ):
        raise WaitlistValidationError("greeting output is invalid", field="greeting")
    if PROHIBITED_CLAIMS.search(text):
        raise WaitlistValidationError("greeting output is invalid", field="greeting")
    return text


def _provider():
    if not bool(getattr(settings, "ALLIES_WAITLIST_PROVIDER_ENABLED", False)):
        raise GenerationUnavailable("generation unavailable")
    provider = str(getattr(settings, "ALLIES_WAITLIST_PROVIDER", "openai"))
    if provider == "fake":
        return FakeGreetingProvider()
    if provider == "openai":
        return OpenAIResponsesProvider()
    raise GenerationUnavailable("generation unavailable")


def _current_greeting_acknowledgement(draft: WaitlistDraft):
    operation = (
        WaitlistOperation.objects.filter(
            draft=draft,
            kind=OperationKind.GENERATE.value,
            status=OperationStatus.SUCCEEDED.value,
        )
        .order_by("-completed_at", "-pk")
        .first()
    )
    if operation is None:
        raise GenerationUnknown("generation outcome unknown")
    return acknowledgement(operation)


def _replay_failure(operation: WaitlistOperation) -> None:
    """Replay the original low-cardinality failure for a reused key."""

    if operation.failure_code == DraftStale.code:
        raise DraftStale("generation result is stale")
    if operation.failure_code == InvalidDraftState.code:
        raise InvalidDraftState("draft is not ready for greeting")
    if operation.failure_code == Throttled.code:
        raise Throttled("generation retry is throttled")
    raise GenerationUnavailable("generation unavailable")


def generate_greeting(
    *,
    capability_digest: str,
    revision: int,
    raw_key: str,
    provider=None,
    generation_identity: str | None = None,
):
    """Generate one current greeting and return an immutable acknowledgement."""

    admit_capability(capability_digest)
    preflight_error: Exception | None = None
    payload = {"revision": revision}
    with transaction.atomic():
        try:
            recovery_draft = WaitlistDraft.objects.select_for_update().get(
                capability_digest=capability_digest
            )
        except WaitlistDraft.DoesNotExist as exc:
            raise DraftUnavailable("waitlist draft unavailable") from exc
        ensure_active(recovery_draft)
        caller_operation = (
            WaitlistOperation.objects.select_for_update()
            .filter(
                draft=recovery_draft,
                kind=OperationKind.GENERATE.value,
                idempotency_digest=idempotency_digest(raw_key),
            )
            .first()
        )
        if caller_operation is not None:
            if caller_operation.request_digest != request_digest(payload):
                raise IdempotencyConflict("idempotency key was reused")
            if caller_operation.status == OperationStatus.SUCCEEDED:
                return acknowledgement(caller_operation)
            if caller_operation.status == OperationStatus.FAILED:
                _replay_failure(caller_operation)
            if caller_operation.status == OperationStatus.OUTCOME_UNKNOWN:
                raise GenerationUnknown("generation outcome unknown")
            if (
                caller_operation.lease_expires_at
                and caller_operation.lease_expires_at > timezone.now()
            ):
                raise OperationInProgress("waitlist operation is in progress")
            mark_unknown(caller_operation)
        expired_operations = list(
            WaitlistOperation.objects.select_for_update().filter(
                draft=recovery_draft,
                kind=OperationKind.GENERATE.value,
                status=OperationStatus.IN_PROGRESS,
                lease_expires_at__lte=timezone.now(),
            )
        )
        for expired_operation in expired_operations:
            mark_unknown(expired_operation)

    with transaction.atomic():
        try:
            draft = WaitlistDraft.objects.select_for_update().get(
                capability_digest=capability_digest
            )
        except WaitlistDraft.DoesNotExist as exc:
            raise DraftUnavailable("waitlist draft unavailable") from exc
        ensure_active(draft)
        if caller_operation is None and draft.revision != revision:
            raise DraftStale("draft revision is stale")
        if caller_operation is None and _greeting_is_current(draft):
            # Retrieving an already-current greeting must not mint a new
            # receipt for every fresh idempotency key.
            return _current_greeting_acknowledgement(draft)
        operation, replay = reserve_operation(
            draft=draft,
            kind=OperationKind.GENERATE.value,
            raw_key=raw_key,
            payload=payload,
            lease_seconds=int(
                getattr(settings, "ALLIES_WAITLIST_GENERATION_TIMEOUT_SECONDS", 8)
            )
            + 20,
        )
        if replay:
            if operation.status == OperationStatus.OUTCOME_UNKNOWN:
                raise GenerationUnknown("generation outcome unknown")
            if operation.status == OperationStatus.FAILED:
                _replay_failure(operation)
            return acknowledgement(operation)
        if (
            WaitlistOperation.objects.filter(
                draft=draft,
                kind=OperationKind.GENERATE.value,
                status=OperationStatus.IN_PROGRESS,
            )
            .exclude(pk=operation.pk)
            .exists()
        ):
            # Raising rolls back this caller's reservation while retaining the
            # already-committed operation that owns the provider lease.
            raise OperationInProgress("waitlist operation is in progress")
        if draft.revision != revision:
            operation.delete()
            raise DraftStale("draft revision is stale")
        unknown_operations = WaitlistOperation.objects.filter(
            draft=draft,
            kind=OperationKind.GENERATE.value,
            status=OperationStatus.OUTCOME_UNKNOWN,
        )
        attempt_cap = int(
            getattr(settings, "ALLIES_WAITLIST_GENERATION_ATTEMPT_CAP", 3)
        )
        if unknown_operations.count() >= attempt_cap:
            operation.delete()
            preflight_error = Throttled("generation attempt cap reached")
        else:
            latest_unknown = unknown_operations.order_by("-completed_at").first()
            cooldown = int(
                getattr(
                    settings,
                    "ALLIES_WAITLIST_GENERATION_ATTEMPT_COOLDOWN_SECONDS",
                    60,
                )
            )
            if latest_unknown and latest_unknown.completed_at:
                elapsed = (timezone.now() - latest_unknown.completed_at).total_seconds()
                if elapsed < cooldown:
                    operation.delete()
                    preflight_error = Throttled("generation retry cooldown is active")
        if preflight_error is not None:
            pass
        elif _greeting_is_current(draft):
            operation.delete()
            return _current_greeting_acknowledgement(draft)
        elif (
            draft.lifecycle != DraftLifecycle.READY_FOR_GREETING
            and not _requires_policy_refresh(draft)
        ) or not configuration_complete(draft):
            # Invalid lifecycle is a pre-provider rejection.  Do not retain a
            # failed receipt for it: fresh keys must not be able to exhaust
            # the finite generation receipt quota before the draft is ready.
            operation.delete()
            preflight_error = InvalidDraftState("draft is not ready for greeting")
        else:
            digest = generation_input_digest(draft)
            previous_attempt = (
                WaitlistDraft.objects.filter(pk=draft.pk)
                .values_list("generation_input_digest", flat=True)
                .first()
            )
            if previous_attempt == digest and _greeting_is_current(draft):
                operation.delete()
                return _current_greeting_acknowledgement(draft)

    if preflight_error is not None:
        raise preflight_error

    lease = None
    refund_budget = False
    try:
        if generation_identity is None:
            lease = acquire_generation(capability_digest)
        else:
            lease = acquire_generation(
                capability_digest, budget_identity=generation_identity
            )
        adapter = provider or _provider()
        output = adapter.generate(
            GreetingRequest(
                name=draft.name,
                job=draft.job,
                personality=draft.personality,
            )
        )
        text = validate_output(output)
    except ProviderUnknownError as exc:
        with transaction.atomic():
            locked_operation = WaitlistOperation.objects.select_for_update().get(
                pk=operation.pk
            )
            mark_unknown(locked_operation)
        raise GenerationUnknown("generation outcome unknown") from exc
    except AdmissionUnavailable as exc:
        _delete_reserved_operation(operation)
        raise GenerationUnavailable("generation unavailable") from exc
    except Throttled:
        # No provider call occurred.  Leave no failed receipt behind so a
        # transient global/capability admission rejection does not consume a
        # fresh idempotency key or the finite generation receipt quota.
        _delete_reserved_operation(operation)
        raise
    except (
        GenerationUnavailable,
        ProviderUnavailableError,
        WaitlistValidationError,
    ) as exc:
        # A provider-unavailable result is definitive: no greeting was
        # returned, so the minute budget reservation can be reused. Unknown
        # outcomes and malformed successful responses retain their budget in
        # case the provider accepted or billed the request.
        refund_budget = isinstance(
            exc, (GenerationUnavailable, ProviderUnavailableError)
        ) and not isinstance(exc, ProviderBilledError)
        with transaction.atomic():
            locked_operation = WaitlistOperation.objects.select_for_update().get(
                pk=operation.pk
            )
            mark_failed(
                locked_operation,
                failure_code=getattr(exc, "code", "generation_unavailable"),
            )
        if isinstance(exc, (WaitlistValidationError, ProviderUnavailableError)):
            raise GenerationUnavailable("generation unavailable") from exc
        raise
    except Exception as exc:
        with transaction.atomic():
            locked_operation = WaitlistOperation.objects.select_for_update().get(
                pk=operation.pk
            )
            mark_unknown(locked_operation)
        raise GenerationUnknown("generation outcome unknown") from exc
    finally:
        if lease is not None:
            release_generation(lease, refund_budget=refund_budget)

    stale_result = False
    with transaction.atomic():
        try:
            locked_draft = WaitlistDraft.objects.select_for_update().get(pk=draft.pk)
            locked_operation = WaitlistOperation.objects.select_for_update().get(
                pk=operation.pk
            )
        except (WaitlistDraft.DoesNotExist, WaitlistOperation.DoesNotExist) as exc:
            raise GenerationUnknown("generation outcome unknown") from exc
        if (
            locked_draft.revision != revision
            or generation_input_digest(locked_draft) != digest
            or (
                locked_draft.lifecycle != DraftLifecycle.READY_FOR_GREETING
                and not _requires_policy_refresh(locked_draft)
            )
        ):
            mark_failed(locked_operation, failure_code="waitlist_draft_stale")
            stale_result = True
        else:
            locked_draft.generation_input_digest = digest
            locked_draft.greeting_text = text
            locked_draft.greeting_policy_version = POLICY_VERSION
            locked_draft.greeting_generated_at = timezone.now()
            locked_draft.lifecycle = DraftLifecycle.GREETING_READY
            locked_draft.revision += 1
            locked_draft.expires_at = timezone.now() + timedelta(
                seconds=int(
                    getattr(
                        settings,
                        "ALLIES_WAITLIST_ABANDONED_RETENTION_SECONDS",
                        7 * 24 * 60 * 60,
                    )
                )
            )
            locked_draft.save()
            return _store_success(locked_draft, locked_operation)
    if stale_result:
        raise DraftStale("generation result is stale")


def _delete_reserved_operation(operation: WaitlistOperation) -> None:
    """Drop a fresh receipt after a pre-provider transient rejection."""

    with transaction.atomic():
        try:
            locked_operation = WaitlistOperation.objects.select_for_update().get(
                pk=operation.pk
            )
        except WaitlistOperation.DoesNotExist:
            return
        if locked_operation.status == OperationStatus.IN_PROGRESS:
            locked_operation.delete()


def _store_success(draft: WaitlistDraft, operation):
    return_value = acknowledgement(operation)
    if operation.status == OperationStatus.IN_PROGRESS:
        return_value = mark_succeeded(
            operation, revision=draft.revision, lifecycle=draft.lifecycle
        )
    return return_value
