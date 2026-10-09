"""Message-linked Foundry dispatch and bounded retry state."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from allies.exceptions import (
    FoundryGatewayConflict,
    FoundryGatewayInvalid,
    FoundryGatewayNotFound,
    FoundryGatewayRejected,
    FoundryGatewayRetryable,
    FoundryGatewayUnknownOutcome,
)
from allies.gateways.contracts import (
    MAX_COMMAND_TEXT_BYTES,
    ExecutionCommand,
    ExecutionReceipt,
    FirstTurnBootstrap,
    ReconciliationReceipt,
    canonical_fingerprint,
    canonical_json_bytes,
)
from allies.gateways.foundry import create_execution_intent, reconcile_execution_intent
from allies.models import Ally, AllyBinding, AllyDeletionState, BindingStatus
from chat.exceptions import (
    DispatchConflict,
    DispatchUnavailable,
    OnboardingHandoffRepairRequired,
    OnboardingHandoffUnavailable,
)
from chat.models import (
    NONTERMINAL_MESSAGE_STATUSES,
    Conversation,
    DispatchOutbox,
    DispatchState,
    Message,
    MessageLifecycle,
    MessageOrigin,
    MessagePreparation,
    MessageSender,
)
from files.models import FileAllyTombstone

DISPATCH_LEASE_SECONDS = 60
DISPATCH_MAX_ATTEMPTS = 5
DISPATCH_MAX_BACKOFF_SECONDS = 300


@dataclass(frozen=True, slots=True)
class DispatchReceipt:
    message_id: UUID
    status: str
    attempt_count: int
    command_fingerprint: str


@dataclass(frozen=True, slots=True)
class DispatchReport:
    claimed: int = 0
    accepted: int = 0
    deferred: int = 0
    exhausted: int = 0
    reconciled: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "claimed": self.claimed,
            "accepted": self.accepted,
            "deferred": self.deferred,
            "exhausted": self.exhausted,
            "reconciled": self.reconciled,
        }


def _enabled() -> bool:
    return bool(getattr(settings, "ALLIES_FOUNDRY_EXECUTION_ENABLED", False))


def _file_input_enabled() -> bool:
    return bool(getattr(settings, "ALLIES_FILE_INPUT_DELIVERY_ENABLED", False))


def _delivery_enabled(message: Message) -> bool:
    return message.preparation == MessagePreparation.NONE or (
        message.preparation == MessagePreparation.READY
        and message.send_armed
        and _file_input_enabled()
    )


def _file_manifest(message: Message) -> list[dict[str, object]] | None:
    if message.preparation == MessagePreparation.NONE:
        return None
    if (
        message.preparation != MessagePreparation.READY
        or not message.send_armed
        or not _file_input_enabled()
    ):
        raise DispatchConflict("file message is not dispatchable")
    from files.models import FileDirection, FileState, MessageFile
    from workspaces.models import Membership, MembershipStatus

    links = list(
        MessageFile.objects.select_related("file")
        .filter(message=message, removed_at__isnull=True)
        .order_by("position", "id")
    )
    workspace_id = message.conversation.ally.workspace_id
    ally_id = message.conversation.ally_id
    if not links or any(
        link.file.workspace_id != workspace_id
        or link.file.ally_id != ally_id
        or link.file.direction != FileDirection.INBOUND
        or link.file.state != FileState.READY
        or link.file.actual_size is None
        for link in links
    ):
        raise DispatchConflict("file manifest is not ready")
    owner_ids = {link.file.owner_id for link in links}
    active_owner_ids = set(
        Membership.objects.filter(
            workspace_id=workspace_id,
            user_id__in=owner_ids,
            status=MembershipStatus.ACTIVE,
        ).values_list("user_id", flat=True)
    )
    if active_owner_ids != owner_ids:
        raise DispatchConflict("file manifest is not ready")
    return [
        {
            "file_id": str(link.file_id),
            "name": link.file.original_name,
            "media_type": link.file.media_type,
            "size": link.file.actual_size,
            "sha256": link.file.sha256,
        }
        for link in links
    ]


def _first_turn_bootstrap(message: Message) -> FirstTurnBootstrap | None:
    if (
        not message.conversation.is_default
        or message.sender != MessageSender.USER
        or message.origin != MessageOrigin.SEND
    ):
        return None
    if message.sequence != 2:
        if message.retry_of_id is None:
            return None
        first_reply_id = (
            Message.objects.filter(
                conversation_id=message.conversation_id,
                sequence=2,
                sender=MessageSender.USER,
                origin=MessageOrigin.SEND,
            )
            .values_list("id", flat=True)
            .first()
        )
        if message.retry_of_id != first_reply_id:
            return None
    try:
        greeting = Message.objects.only(
            "id",
            "content",
            "sender",
            "origin",
            "status",
            "send_key_digest",
            "content_fingerprint",
        ).get(conversation_id=message.conversation_id, sequence=1)
    except Message.DoesNotExist as exc:
        raise OnboardingHandoffRepairRequired(
            "onboarding handoff needs repair"
        ) from exc
    if (
        greeting.sender != MessageSender.ASSISTANT
        or greeting.origin != MessageOrigin.ONBOARDING
        or greeting.status != MessageLifecycle.COMPLETED
        or greeting.send_key_digest
        or greeting.content_fingerprint
        or not isinstance(greeting.content, str)
        or not greeting.content.strip()
    ):
        raise OnboardingHandoffRepairRequired("onboarding handoff needs repair")
    try:
        return FirstTurnBootstrap(
            kind="assistant_message",
            message_id=greeting.id,
            text=greeting.content,
        )
    except ValueError as exc:
        raise OnboardingHandoffRepairRequired(
            "onboarding handoff needs repair"
        ) from exc


def _command_for_message(message: Message) -> tuple[ExecutionCommand, bytes, str]:
    if message.conversation.ally.deletion_state != AllyDeletionState.ACTIVE:
        raise DispatchConflict("ally deletion is pending")
    if (
        message.sender != MessageSender.USER
        or message.origin != MessageOrigin.SEND
        or message.status not in {MessageLifecycle.QUEUED, MessageLifecycle.IN_PROGRESS}
    ):
        raise DispatchConflict("message is not dispatchable")
    try:
        binding_id = message.conversation.ally.binding.id
    except AllyBinding.DoesNotExist:
        raise DispatchUnavailable("ally binding unavailable") from None
    issued_at = timezone.now()
    deadline_at = issued_at + timedelta(seconds=5)
    payload = {
        "kind": "execution_input",
        "text": _model_input_text(message),
    }
    if files := _file_manifest(message):
        payload["files"] = files
    bootstrap = _first_turn_bootstrap(message)
    if bootstrap is not None:
        payload["bootstrap"] = bootstrap.model_dump(mode="json")
    values = {
        "schema_version": "v1",
        "kind": "execution.command",
        "producer": "cloud",
        "service_identity": "cloud-service",
        "command_id": str(message.id),
        "idempotency_key": str(message.id),
        "scope": {
            "kind": "workspace",
            "cloud_workspace_id": str(message.conversation.ally.workspace_id),
        },
        "conversation_turn_ordinal": message.sequence,
        "cloud": {
            "ally_id": str(message.conversation.ally_id),
            "conversation_id": str(message.conversation_id),
            "message_id": str(message.id),
            "cloud_binding_id": str(binding_id),
        },
        "source_kind": "conversation_message",
        "payload": payload,
        "issued_at": issued_at.isoformat(),
        "deadline_at": deadline_at.isoformat(),
    }
    values["fingerprint"] = canonical_fingerprint(values)
    command = ExecutionCommand.model_validate({**values})
    body = canonical_json_bytes(command.model_dump(mode="json"))
    return command, body, hashlib.sha256(body).hexdigest()


def _routine_contexts_for_message(message: Message):
    from activities.models import RoutineResultContext

    pending = tuple(
        RoutineResultContext.objects.filter(
            conversation_id=message.conversation_id,
            consumed_at__isnull=True,
        ).order_by("created_at", "id")
    )
    return _oldest_routine_contexts_within_budget(message, pending)


def _oldest_routine_contexts_within_budget(message: Message, pending) -> tuple:
    fitted: tuple = ()
    for context in pending:
        candidate = (*fitted, context)
        text = "\n\n".join(_model_input_parts(message, candidate))
        if len(text.encode("utf-8")) > MAX_COMMAND_TEXT_BYTES:
            break
        fitted = candidate
    return fitted


def _model_input_parts(message: Message, contexts) -> list[str]:
    routine_action = getattr(message, "routine_action", None)
    if not contexts and not message.client_timezone and routine_action is None:
        return [message.content]
    parts = [context.context_text for context in contexts]
    if message.client_timezone:
        parts.append(
            f"[Conversation context]\nBrowser timezone: {message.client_timezone}\n"
            f"Message sent at: {message.created_at.isoformat()}\n"
            "Use this timezone for new schedules unless the user explicitly specifies another."
        )
    if routine_action is not None:
        parts.append(
            "[Structured routine action]\n"
            + json.dumps(
                routine_action, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            )
        )
    parts.append(f"[User message]\n{message.content}")
    return parts


def _model_input_text(message: Message) -> str:
    text = "\n\n".join(
        _model_input_parts(message, _routine_contexts_for_message(message))
    )
    if len(text.encode("utf-8")) > MAX_COMMAND_TEXT_BYTES:
        raise DispatchConflict("routine result context exceeds command budget")
    return text


def _ensure_outbox_locked(message: Message) -> DispatchReceipt:
    existing = (
        DispatchOutbox.objects.select_for_update().filter(message=message).first()
    )
    if existing is not None:
        return DispatchReceipt(
            message_id=message.id,
            status=existing.status,
            attempt_count=existing.attempt_count,
            command_fingerprint=existing.command_fingerprint,
        )
    if message.deleted_at is not None:
        return DispatchReceipt(
            message_id=message.id,
            status=DispatchState.FAILED,
            attempt_count=0,
            command_fingerprint="",
        )
    command, body, body_digest = _command_for_message(message)
    message.foundry_binding_id = command.cloud.cloud_binding_id
    message.save(update_fields=("foundry_binding_id", "updated_at"))
    file_manifest = [
        file.model_dump(mode="json") for file in (command.payload.files or [])
    ]
    outbox = DispatchOutbox.objects.create(
        message=message,
        command_bytes=body,
        command_byte_length=len(body),
        command_sha256=body_digest,
        command_fingerprint=command.fingerprint,
        file_manifest=file_manifest,
    )
    contexts = _routine_contexts_for_message(message)
    if contexts:
        from activities.models import RoutineResultContext

        updated = RoutineResultContext.objects.filter(
            pk__in=[context.pk for context in contexts],
            consumed_at__isnull=True,
        ).update(target_message=message, consumed_at=timezone.now())
        if updated != len(contexts):
            raise DispatchConflict("routine result context changed during dispatch")
    return DispatchReceipt(
        message_id=message.id,
        status=outbox.status,
        attempt_count=outbox.attempt_count,
        command_fingerprint=outbox.command_fingerprint,
    )


def _validate_outbox_command(message: Message) -> None:
    """Validate a missing command before taking any lower-level row locks."""

    if (
        message.deleted_at is None
        and not DispatchOutbox.objects.filter(message=message).exists()
    ):
        _command_for_message(message)


def _dispatch_accepted_locked(
    *, conversation: Conversation, message: Message
) -> DispatchReceipt:
    if (
        conversation.ally.deletion_state != AllyDeletionState.ACTIVE
        or FileAllyTombstone.objects.filter(ally_id=conversation.ally_id).exists()
    ):
        return DispatchReceipt(
            message_id=message.id,
            status=DispatchState.FAILED,
            attempt_count=0,
            command_fingerprint="",
        )
    _validate_outbox_command(message)
    from .messages import _claim_next_turn_locked

    claimed = _claim_next_turn_locked(conversation=conversation)
    receipt = _ensure_outbox_locked(message)
    if claimed is not None and claimed.pk != message.pk:
        claimed = (
            Message.objects.select_for_update(of=("self",))
            .select_related("conversation__ally__workspace")
            .get(pk=claimed.pk, conversation=conversation)
        )
        try:
            _ensure_outbox_locked(claimed)
        except DispatchUnavailable:
            _mark_pre_call_failure_for_message(
                claimed, "binding_unavailable", now=timezone.now()
            )
        except (OnboardingHandoffUnavailable, OnboardingHandoffRepairRequired) as exc:
            _mark_pre_call_failure_for_message(claimed, exc.code, now=timezone.now())
        except (DispatchConflict, ValueError):
            _mark_pre_call_failure_for_message(
                claimed, "command_invalid", now=timezone.now()
            )
    return receipt


def dispatch_accepted_message(message: Message) -> DispatchReceipt:
    """Persist exactly one command for an accepted message."""

    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().get(
            pk=message.conversation_id
        )
        locked = (
            Message.objects.select_for_update(of=("self",))
            .select_related("conversation__ally__workspace")
            .get(pk=message.pk, conversation=conversation)
        )
        if not _delivery_enabled(locked):
            return DispatchReceipt(
                message_id=locked.id,
                status=DispatchState.PENDING,
                attempt_count=0,
                command_fingerprint="",
            )
        return _dispatch_accepted_locked(conversation=conversation, message=locked)


def _schedule_dispatch() -> None:
    try:
        from chat.tasks import dispatch_pending_messages_task

        dispatch_pending_messages_task.delay()
    except Exception:  # noqa: BLE001 - the durable outbox is the recovery path
        return


def ensure_dispatch_after_accept(message: Message) -> None:
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().get(
            pk=message.conversation_id
        )
        locked = (
            Message.objects.select_for_update(of=("self",))
            .select_related("conversation__ally__workspace")
            .get(pk=message.pk, conversation=conversation)
        )
        if not _delivery_enabled(locked):
            return
        try:
            _dispatch_accepted_locked(conversation=conversation, message=locked)
        except DispatchUnavailable:
            return
        except (DispatchConflict, ValueError):
            _mark_pre_call_failure_for_message(
                locked, "command_invalid", now=timezone.now()
            )
        locked.refresh_from_db(fields=("execution_claimed_at", "deleted_at", "status"))
        if locked.execution_claimed_at is not None and _enabled():
            transaction.on_commit(_schedule_dispatch)
        message.execution_claimed_at = locked.execution_claimed_at
        message.deleted_at = locked.deleted_at
        message.status = locked.status


def _claim_due(*, now, limit: int) -> list[tuple[UUID, int, bool]]:
    lease_until = now + timedelta(seconds=DISPATCH_LEASE_SECONDS)
    due = (
        Q(
            status__in=[DispatchState.PENDING, DispatchState.RECONCILIATION_NEEDED],
            next_attempt_at__lte=now,
        )
        & (Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now))
    ) | Q(status=DispatchState.IN_PROGRESS, lease_expires_at__lte=now)
    bound = max(1, min(limit, 100))
    candidate_ids = list(
        DispatchOutbox.objects.filter(
            due,
            message__execution_claimed_at__isnull=False,
            message__deleted_at__isnull=True,
            message__sender=MessageSender.USER,
            message__origin=MessageOrigin.SEND,
            message__status__in=NONTERMINAL_MESSAGE_STATUSES,
            message__conversation__ally__deletion_state=AllyDeletionState.ACTIVE,
        )
        .order_by(
            "message__conversation_id", "message__sequence", "next_attempt_at", "id"
        )
        .values_list("pk", flat=True)[:bound]
    )
    with transaction.atomic():
        claimed: list[tuple[UUID, int, bool]] = []
        for pk in candidate_ids:
            identity = (
                DispatchOutbox.objects.filter(pk=pk)
                .values("message_id", "message__conversation_id")
                .first()
            )
            if identity is None:
                continue
            try:
                conversation = Conversation.objects.select_for_update(
                    skip_locked=connection.features.has_select_for_update_skip_locked
                ).get(pk=identity["message__conversation_id"])
            except Conversation.DoesNotExist:
                continue
            message = (
                Message.objects.select_for_update()
                .filter(
                    pk=identity["message_id"],
                    conversation=conversation,
                    execution_claimed_at__isnull=False,
                    deleted_at__isnull=True,
                    sender=MessageSender.USER,
                    origin=MessageOrigin.SEND,
                    status__in=NONTERMINAL_MESSAGE_STATUSES,
                )
                .first()
            )
            if message is None:
                continue
            row = (
                DispatchOutbox.objects.select_for_update()
                .filter(due, pk=pk, message=message)
                .first()
            )
            if row is None:
                continue
            if (
                conversation.ally.deletion_state != AllyDeletionState.ACTIVE
                or FileAllyTombstone.objects.filter(
                    ally_id=conversation.ally_id
                ).exists()
            ):
                _terminalize_claim_locked(
                    conversation=conversation,
                    message=message,
                    outbox=row,
                    code="ally_deleted",
                    now=now,
                )
                continue
            if not _prior_turn_ready(message):
                continue
            reconcile_first = row.status in {
                DispatchState.RECONCILIATION_NEEDED,
                DispatchState.IN_PROGRESS,
            }
            if row.attempt_count >= DISPATCH_MAX_ATTEMPTS and row.status in {
                DispatchState.PENDING,
                DispatchState.RECONCILIATION_NEEDED,
            }:
                row.status = DispatchState.RECONCILIATION_NEEDED
                row.safe_error_code = "dispatch_attempts_exhausted"
                reconcile_first = True
            if row.attempt_count < DISPATCH_MAX_ATTEMPTS:
                row.attempt_count += 1
            row.status = DispatchState.IN_PROGRESS
            row.last_attempt_at = now
            row.lease_expires_at = lease_until
            row.save(
                update_fields=(
                    "attempt_count",
                    "status",
                    "safe_error_code",
                    "last_attempt_at",
                    "lease_expires_at",
                    "updated_at",
                )
            )
            claimed.append((row.pk, row.attempt_count, reconcile_first))
        return claimed


def _backoff_seconds(attempt: int) -> float:
    base = min(DISPATCH_MAX_BACKOFF_SECONDS, 2 ** max(0, attempt - 1))
    return base * (1 + random.random() * 0.25)


def _receipt_digest(receipt: ExecutionReceipt | ReconciliationReceipt) -> str:
    return hashlib.sha256(
        canonical_json_bytes(receipt.model_dump(mode="json"))
    ).hexdigest()


def _mark_deferred(
    pk: UUID, fence: int, code: str, *, now, reconciliation: bool = False
) -> bool:
    status = (
        DispatchState.RECONCILIATION_NEEDED if reconciliation else DispatchState.PENDING
    )
    delay = _backoff_seconds(fence)
    return bool(
        DispatchOutbox.objects.filter(
            pk=pk, attempt_count=fence, status=DispatchState.IN_PROGRESS
        ).update(
            status=status,
            safe_error_code=code,
            next_attempt_at=now + timedelta(seconds=delay),
            lease_expires_at=None,
        )
    )


def _mark_binding_pending(pk: UUID, fence: int, *, now) -> bool:
    return bool(
        DispatchOutbox.objects.filter(
            pk=pk, attempt_count=fence, status=DispatchState.IN_PROGRESS
        ).update(
            status=DispatchState.PENDING,
            attempt_count=max(0, fence - 1),
            safe_error_code="binding_pending",
            next_attempt_at=now + timedelta(seconds=_backoff_seconds(fence)),
            lease_expires_at=None,
        )
    )


def _mark_prior_turn_pending(pk: UUID, fence: int, *, now) -> bool:
    return bool(
        DispatchOutbox.objects.filter(
            pk=pk, attempt_count=fence, status=DispatchState.IN_PROGRESS
        ).update(
            status=DispatchState.PENDING,
            attempt_count=max(0, fence - 1),
            safe_error_code="prior_turn_pending",
            next_attempt_at=now + timedelta(seconds=_backoff_seconds(fence)),
            lease_expires_at=None,
        )
    )


def _insert_pending_routine_context(conversation: Conversation, *, now) -> tuple:
    from routines.services.results import (
        RoutineResultConflict,
        RoutineResultInvalid,
        complete_pending_routine_results_locked,
    )

    try:
        return complete_pending_routine_results_locked(
            conversation=conversation,
            now=now,
        )
    except (RoutineResultConflict, RoutineResultInvalid):
        # Keep the result receipt pending when the model-input budget cannot
        # accommodate it. The next turn remains fail-closed and can retry once
        # the boundary has a safe command budget.
        return ()


def _release_next_locked(conversation: Conversation, *, now) -> Message | None:
    from .messages import _claim_next_turn_locked

    _insert_pending_routine_context(conversation, now=now)

    next_message = _claim_next_turn_locked(conversation=conversation, now=now)
    if next_message is None:
        return None
    try:
        _ensure_outbox_locked(next_message)
    except DispatchUnavailable:
        code = "binding_unavailable"
    except (OnboardingHandoffUnavailable, OnboardingHandoffRepairRequired) as exc:
        code = exc.code
    except (DispatchConflict, ValueError):
        code = "command_invalid"
    else:
        if _enabled():
            transaction.on_commit(_schedule_dispatch)
        return next_message
    next_message.status = MessageLifecycle.FAILED
    next_message.retry_allowed = False
    next_message.save(update_fields=("status", "retry_allowed", "updated_at"))
    DispatchOutbox.objects.create(
        message=next_message,
        status=DispatchState.FAILED,
        safe_error_code=code,
        next_attempt_at=None,
        completed_at=now,
    )
    return _release_next_locked(conversation, now=now)


def _finish_pre_call_failure_locked(
    *,
    conversation: Conversation,
    message: Message,
    outbox: DispatchOutbox,
    code: str,
    now,
    fence: int | None = None,
) -> bool:
    if fence is not None and (
        outbox.attempt_count != fence or outbox.status != DispatchState.IN_PROGRESS
    ):
        return False
    if fence is None and (
        outbox.status != DispatchState.PENDING
        or outbox.attempt_count
        or outbox.last_attempt_at is not None
    ):
        return False
    _terminalize_claim_locked(
        conversation=conversation,
        message=message,
        outbox=outbox,
        code=code,
        now=now,
    )
    return True


def _terminalize_claim_locked(
    *,
    conversation: Conversation,
    message: Message,
    outbox: DispatchOutbox,
    code: str,
    now,
    status: str = MessageLifecycle.FAILED,
) -> None:
    if message.deleted_at is None and message.status in NONTERMINAL_MESSAGE_STATUSES:
        message.status = status
        message.retry_allowed = False
        message.save(update_fields=("status", "retry_allowed", "updated_at"))
    outbox.status = DispatchState.FAILED
    outbox.safe_error_code = code
    outbox.command_bytes = b""
    outbox.command_byte_length = 0
    outbox.next_attempt_at = None
    outbox.lease_expires_at = None
    outbox.completed_at = now
    outbox.save(
        update_fields=(
            "status",
            "safe_error_code",
            "command_bytes",
            "command_byte_length",
            "next_attempt_at",
            "lease_expires_at",
            "completed_at",
            "updated_at",
        )
    )
    # The conversation lock serializes this with claim/delete. Keep the
    # terminal head and its successor in one durable transaction.
    _release_next_locked(conversation, now=now)


def _mark_pre_call_failure(pk: UUID, fence: int, code: str, *, now) -> bool:
    identity = (
        DispatchOutbox.objects.filter(pk=pk)
        .values("message_id", "message__conversation_id")
        .first()
    )
    if identity is None:
        return False
    with transaction.atomic():
        try:
            conversation = Conversation.objects.select_for_update().get(
                pk=identity["message__conversation_id"]
            )
            message = Message.objects.select_for_update().get(
                pk=identity["message_id"], conversation=conversation
            )
            outbox = DispatchOutbox.objects.select_for_update().get(
                pk=pk, message=message
            )
        except (
            Conversation.DoesNotExist,
            Message.DoesNotExist,
            DispatchOutbox.DoesNotExist,
        ):
            return False
        if outbox.attempt_count != fence or outbox.status != DispatchState.IN_PROGRESS:
            return False
        return _finish_pre_call_failure_locked(
            conversation=conversation,
            message=message,
            outbox=outbox,
            code=code,
            now=now,
            fence=fence,
        )


def _mark_pre_call_failure_for_message(message: Message, code: str, *, now) -> bool:
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().get(
            pk=message.conversation_id
        )
        locked_message = Message.objects.select_for_update().get(
            pk=message.pk, conversation=conversation
        )
        outbox = (
            DispatchOutbox.objects.select_for_update()
            .filter(message=locked_message)
            .first()
        )
        if outbox is None:
            if locked_message.status in NONTERMINAL_MESSAGE_STATUSES:
                locked_message.status = MessageLifecycle.FAILED
                locked_message.retry_allowed = False
                locked_message.save(
                    update_fields=("status", "retry_allowed", "updated_at")
                )
            DispatchOutbox.objects.create(
                message=locked_message,
                status=DispatchState.FAILED,
                safe_error_code=code,
                next_attempt_at=None,
                completed_at=now,
            )
            _release_next_locked(conversation, now=now)
            return True
        return _finish_pre_call_failure_locked(
            conversation=conversation,
            message=locked_message,
            outbox=outbox,
            code=code,
            now=now,
        )


def _pre_call_failure_or_retain(
    pk: UUID,
    fence: int,
    code: str,
    *,
    now,
    reconcile_first: bool,
) -> str:
    if fence == 1 and not reconcile_first:
        _mark_pre_call_failure(pk, fence, code, now=now)
        return "failed"
    elif fence >= DISPATCH_MAX_ATTEMPTS:
        _mark_reconciliation_exhausted(pk, fence, now=now)
        return "exhausted"
    else:
        _mark_deferred(pk, fence, code, now=now, reconciliation=True)
        return "deferred"


def _prior_turn_ready(message: Message) -> bool:
    prior = (
        Message.objects.filter(
            conversation_id=message.conversation_id,
            sender=MessageSender.USER,
            sequence__lt=message.sequence,
        )
        .order_by("-sequence", "-id")
        .first()
    )
    if prior is None:
        return True
    if prior.deleted_at is not None or prior.status in {
        MessageLifecycle.COMPLETED,
        MessageLifecycle.FAILED,
        MessageLifecycle.STOPPED,
    }:
        return True
    if prior.origin == MessageOrigin.ONBOARDING:
        return False
    if prior.origin != MessageOrigin.SEND:
        return False
    prior_outbox = (
        DispatchOutbox.objects.filter(message_id=prior.id)
        .only("status", "next_attempt_at")
        .first()
    )
    if prior_outbox is None:
        try:
            dispatch_accepted_message(prior)
        except DispatchUnavailable:
            _mark_pre_call_failure_for_message(
                prior, "binding_unavailable", now=timezone.now()
            )
        except (OnboardingHandoffUnavailable, OnboardingHandoffRepairRequired) as exc:
            _mark_pre_call_failure_for_message(prior, exc.code, now=timezone.now())
        except (DispatchConflict, ValueError):
            _mark_pre_call_failure_for_message(
                prior, "command_invalid", now=timezone.now()
            )
        prior_outbox = (
            DispatchOutbox.objects.filter(message_id=prior.id)
            .only("status", "next_attempt_at")
            .first()
        )
    if prior_outbox is None:
        return False
    prior.refresh_from_db(fields=("status", "deleted_at"))
    return prior.deleted_at is not None or prior.status in {
        MessageLifecycle.COMPLETED,
        MessageLifecycle.FAILED,
        MessageLifecycle.STOPPED,
    }


def _reconcile_onboarding_before_dispatch(message: Message) -> Message | None:
    from .conversations import reconcile_onboarding_reply

    reply = (
        Message.objects.filter(
            conversation_id=message.conversation_id,
            sequence=2,
            sender=MessageSender.USER,
        )
        .only("id", "origin")
        .first()
    )
    was_onboarding = reply is not None and reply.origin == MessageOrigin.ONBOARDING
    promoted = reconcile_onboarding_reply(ally=message.conversation.ally)
    if (
        message.conversation.is_default
        and message.sequence > 2
        and not Message.objects.filter(
            conversation_id=message.conversation_id,
            sequence=2,
            sender=MessageSender.USER,
        ).exists()
    ):
        raise OnboardingHandoffUnavailable("onboarding handoff unavailable")
    if (
        was_onboarding
        and promoted is not None
        and promoted.origin == MessageOrigin.SEND
    ):
        return promoted
    return None


def _transfer_claim_to_promoted(*, pk: UUID, fence: int, message_id: UUID, now) -> bool:
    """Move this worker's pre-call claim behind a newly promoted turn."""

    with transaction.atomic():
        outbox_identity = (
            DispatchOutbox.objects.filter(pk=pk)
            .values("message_id", "message__conversation_id")
            .first()
        )
        if outbox_identity is None:
            return False
        conversation = Conversation.objects.select_for_update().get(
            pk=outbox_identity["message__conversation_id"]
        )
        current = Message.objects.select_for_update().get(
            pk=outbox_identity["message_id"], conversation=conversation
        )
        promoted = Message.objects.select_for_update().get(
            pk=message_id, conversation=conversation
        )
        outbox = DispatchOutbox.objects.select_for_update().get(pk=pk, message=current)
        if (
            outbox.status != DispatchState.IN_PROGRESS
            or outbox.attempt_count != fence
            or current.execution_claimed_at is None
            or promoted.execution_claimed_at is not None
            or promoted.deleted_at is not None
            or promoted.status not in NONTERMINAL_MESSAGE_STATUSES
            or promoted.sender != MessageSender.USER
            or promoted.origin != MessageOrigin.SEND
        ):
            return False
        if (
            Message.objects.filter(
                conversation=conversation,
                sender=MessageSender.USER,
                origin=MessageOrigin.SEND,
                status__in=NONTERMINAL_MESSAGE_STATUSES,
                deleted_at__isnull=True,
                execution_claimed_at__isnull=False,
            )
            .exclude(pk=current.pk)
            .exists()
        ):
            return False
        _ensure_outbox_locked(promoted)
        current.execution_claimed_at = None
        current.save(update_fields=("execution_claimed_at", "updated_at"))
        promoted.execution_claimed_at = now
        promoted.save(update_fields=("execution_claimed_at", "updated_at"))
        return True


def _mark_terminal(
    pk: UUID, fence: int, status: str, code: str, *, now, receipt_digest: str = ""
) -> bool:
    values = {
        "status": status,
        "safe_error_code": code,
        "receipt_digest": receipt_digest,
        "lease_expires_at": None,
        "next_attempt_at": None,
        "completed_at": now
        if status in {DispatchState.ACCEPTED, DispatchState.FAILED}
        else None,
    }
    if status in {DispatchState.ACCEPTED, DispatchState.FAILED}:
        values["command_bytes"] = b""
        values["command_byte_length"] = 0
    return bool(
        DispatchOutbox.objects.filter(
            pk=pk, attempt_count=fence, status=DispatchState.IN_PROGRESS
        ).update(**values)
    )


def _mark_deleted_if_fenced(
    *, pk: UUID, fence: int, outbox: DispatchOutbox, now
) -> bool:
    """Serialize a late dispatch callback with the Ally deletion fence."""

    with transaction.atomic():
        ally = (
            Ally.objects.select_for_update()
            .filter(pk=outbox.message.conversation.ally_id)
            .first()
        )
        if ally is not None and ally.deletion_state == AllyDeletionState.ACTIVE:
            return False
        Message.objects.filter(
            pk=outbox.message_id,
            status__in=NONTERMINAL_MESSAGE_STATUSES,
            deleted_at__isnull=True,
        ).update(
            status=MessageLifecycle.FAILED,
            retry_allowed=False,
            updated_at=now,
        )
        _mark_terminal(pk, fence, DispatchState.FAILED, "ally_deleted", now=now)
        return True


def _finish_accepted_dispatch(
    *, pk: UUID, fence: int, outbox: DispatchOutbox, receipt_digest: str, now
) -> str:
    """Persist a successful receipt only while the Ally remains admitted."""

    with transaction.atomic():
        ally = (
            Ally.objects.select_for_update()
            .filter(pk=outbox.message.conversation.ally_id)
            .first()
        )
        if ally is None or ally.deletion_state != AllyDeletionState.ACTIVE:
            Message.objects.filter(
                pk=outbox.message_id,
                status__in=NONTERMINAL_MESSAGE_STATUSES,
                deleted_at__isnull=True,
            ).update(
                status=MessageLifecycle.FAILED,
                retry_allowed=False,
                updated_at=now,
            )
            _mark_terminal(pk, fence, DispatchState.FAILED, "ally_deleted", now=now)
            return "failed"
        updated = _mark_terminal(
            pk,
            fence,
            DispatchState.ACCEPTED,
            "",
            now=now,
            receipt_digest=receipt_digest,
        )
        return "accepted" if updated else "deferred"


def _mark_reconciliation_exhausted(pk: UUID, fence: int, *, now) -> bool:
    return bool(
        DispatchOutbox.objects.filter(
            pk=pk, attempt_count=fence, status=DispatchState.IN_PROGRESS
        ).update(
            status=DispatchState.RECONCILIATION_NEEDED,
            safe_error_code="dispatch_attempts_exhausted",
            command_bytes=b"",
            command_byte_length=0,
            next_attempt_at=None,
            lease_expires_at=None,
            completed_at=now,
        )
    )


def _reconcile_one(
    pk: UUID,
    fence: int,
    outbox: DispatchOutbox,
    *,
    now,
    permit_post: bool,
) -> str | None:
    if _mark_deleted_if_fenced(pk=pk, fence=fence, outbox=outbox, now=now):
        return "failed"
    try:
        reconciliation = reconcile_execution_intent(
            outbox.message_id, outbox.command_fingerprint
        )
    except FoundryGatewayUnknownOutcome:
        _mark_deferred(
            pk, fence, "reconciliation_unavailable", now=now, reconciliation=True
        )
        return "deferred"
    except (
        FoundryGatewayConflict,
        FoundryGatewayInvalid,
        FoundryGatewayRejected,
        FoundryGatewayNotFound,
    ):
        _mark_terminal(
            pk, fence, DispatchState.FAILED, "reconciliation_conflict", now=now
        )
        return "failed"
    if reconciliation.status == "accepted":
        if (
            (
                reconciliation.command_id is not None
                and reconciliation.command_id != outbox.message_id
            )
            or reconciliation.idempotency_key != outbox.message_id
            or reconciliation.fingerprint != outbox.command_fingerprint
        ):
            _mark_terminal(
                pk,
                fence,
                DispatchState.FAILED,
                "receipt_identity_mismatch",
                now=now,
            )
            return "failed"
        finished = _finish_accepted_dispatch(
            pk=pk,
            fence=fence,
            outbox=outbox,
            receipt_digest=_receipt_digest(reconciliation),
            now=now,
        )
        return "reconciled" if finished == "accepted" else finished
    if reconciliation.status == "not_found":
        if permit_post and fence < DISPATCH_MAX_ATTEMPTS and outbox.command_bytes:
            return None
        if fence >= DISPATCH_MAX_ATTEMPTS:
            _mark_reconciliation_exhausted(pk, fence, now=now)
            return "exhausted"
        _mark_deferred(pk, fence, "not_found", now=now, reconciliation=True)
        return "deferred"
    _mark_terminal(pk, fence, DispatchState.FAILED, "reconciliation_conflict", now=now)
    return "failed"


def _dispatch_one(pk: UUID, fence: int, reconcile_first: bool, *, now) -> str:
    outbox = DispatchOutbox.objects.select_related(
        "message__conversation__ally__binding"
    ).get(pk=pk)
    if _mark_deleted_if_fenced(pk=pk, fence=fence, outbox=outbox, now=now):
        return "failed"
    try:
        binding_status = outbox.message.conversation.ally.binding.status
    except AllyBinding.DoesNotExist:
        return _pre_call_failure_or_retain(
            pk,
            fence,
            "binding_unavailable",
            now=now,
            reconcile_first=reconcile_first,
        )
    if binding_status == BindingStatus.INCOMPATIBLE:
        return _pre_call_failure_or_retain(
            pk,
            fence,
            "binding_incompatible",
            now=now,
            reconcile_first=reconcile_first,
        )
    if binding_status != BindingStatus.BOUND:
        if reconcile_first or fence > 1:
            return _pre_call_failure_or_retain(
                pk,
                fence,
                "binding_pending",
                now=now,
                reconcile_first=True,
            )
        _mark_binding_pending(pk, fence, now=now)
        return "deferred"
    try:
        promoted = _reconcile_onboarding_before_dispatch(outbox.message)
    except (OnboardingHandoffUnavailable, OnboardingHandoffRepairRequired) as exc:
        return _pre_call_failure_or_retain(
            pk,
            fence,
            exc.code,
            now=now,
            reconcile_first=reconcile_first,
        )
    if promoted is not None and fence == 1 and not reconcile_first:
        _transfer_claim_to_promoted(pk=pk, fence=fence, message_id=promoted.id, now=now)
    if not _prior_turn_ready(outbox.message):
        _mark_prior_turn_pending(pk, fence, now=now)
        return "deferred"
    if reconcile_first:
        reconciled = _reconcile_one(pk, fence, outbox, now=now, permit_post=True)
        if reconciled is not None:
            return reconciled
    if not outbox.command_bytes:
        _mark_deferred(pk, fence, "command_unavailable", now=now, reconciliation=True)
        return "deferred"
    try:
        command = ExecutionCommand.model_validate_json(bytes(outbox.command_bytes))
    except ValueError:
        return _pre_call_failure_or_retain(
            pk,
            fence,
            "command_invalid",
            now=now,
            reconcile_first=reconcile_first,
        )
    try:
        receipt = create_execution_intent(command, raw_body=bytes(outbox.command_bytes))
    except FoundryGatewayUnknownOutcome:
        return (
            _reconcile_one(pk, fence, outbox, now=now, permit_post=False) or "deferred"
        )
    except FoundryGatewayRetryable:
        if fence >= DISPATCH_MAX_ATTEMPTS:
            _mark_reconciliation_exhausted(pk, fence, now=now)
            return "exhausted"
        _mark_deferred(pk, fence, "foundry_unavailable", now=now)
        return "deferred"
    except FoundryGatewayConflict:
        _mark_terminal(pk, fence, DispatchState.FAILED, "fingerprint_conflict", now=now)
        return "failed"
    except FoundryGatewayNotFound:
        _mark_terminal(pk, fence, DispatchState.FAILED, "binding_unavailable", now=now)
        return "failed"
    except (FoundryGatewayInvalid, FoundryGatewayRejected, ValueError):
        _mark_terminal(pk, fence, DispatchState.FAILED, "foundry_rejected", now=now)
        return "failed"
    if (
        receipt.command_id != command.command_id
        or receipt.idempotency_key != command.idempotency_key
        or receipt.fingerprint != outbox.command_fingerprint
    ):
        _mark_terminal(
            pk, fence, DispatchState.FAILED, "receipt_identity_mismatch", now=now
        )
        return "failed"
    return _finish_accepted_dispatch(
        pk=pk,
        fence=fence,
        outbox=outbox,
        receipt_digest=_receipt_digest(receipt),
        now=now,
    )


def dispatch_pending_messages(*, now=None, limit: int = 20) -> DispatchReport:
    from files.services.preparation import recover_file_preparation

    recover_file_preparation(limit=limit)
    if not _enabled():
        return DispatchReport()
    now = now or timezone.now()
    claims = _claim_due(now=now, limit=limit)
    outcomes = [
        _dispatch_one(pk, fence, reconcile_first, now=now)
        for pk, fence, reconcile_first in claims
    ]
    return DispatchReport(
        claimed=len(claims),
        accepted=outcomes.count("accepted"),
        deferred=outcomes.count("deferred"),
        exhausted=outcomes.count("exhausted"),
        reconciled=outcomes.count("reconciled"),
    )


__all__ = [
    "DispatchReceipt",
    "DispatchReport",
    "dispatch_accepted_message",
    "dispatch_pending_messages",
    "ensure_dispatch_after_accept",
]
