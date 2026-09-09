"""Owner-scoped persistence primitives for saved routine intent."""

from __future__ import annotations

import base64
import binascii
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from allies.models import Ally, AllyBinding
from allies.services.onboarding import digest_value
from chat.models import Conversation
from common.uuids import canonical_uuid
from workspaces.capabilities import Capability
from workspaces.services.access import require_workspace_capability

from ..models import (
    ROUTINE_PROMPT_MAX_BYTES,
    ROUTINE_TITLE_MAX_LENGTH,
    Routine,
    RoutineDeletionConfirmation,
    RoutineDeletionConfirmationState,
    RoutineManagementReceipt,
    RoutineState,
)
from .schedule import (
    ScheduleSpec,
    resolve_next_occurrence,
    validate_schedule,
)


class RoutineRevisionConflict(ValueError):
    """The caller attempted to mutate a stale routine revision."""


class RoutineStateError(ValueError):
    """The requested state transition is not valid for the saved schedule."""


class RoutineCursorInvalid(ValueError):
    """A routine page cursor is malformed or bound to another query."""


CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
CONFIRMATION_STALE = "CONFIRMATION_STALE"
CONFIRMATION_REPLAYED = "CONFIRMATION_REPLAYED"
CONFIRMATION_WRONG_CONVERSATION = "CONFIRMATION_WRONG_CONVERSATION"
CONFIRMATION_WRONG_OWNER = "CONFIRMATION_WRONG_OWNER"
CONFIRMATION_WRONG_WORKSPACE = "CONFIRMATION_WRONG_WORKSPACE"
CONFIRMATION_WRONG_ALLY = "CONFIRMATION_WRONG_ALLY"
CONFIRMATION_WRONG_BINDING = "CONFIRMATION_WRONG_BINDING"
CONFIRMATION_WRONG_ROUTINE = "CONFIRMATION_WRONG_ROUTINE"


class RoutineConfirmationError(ValueError):
    """A deletion confirmation failed without mutating either bound record."""

    def __init__(self, result_code: str):
        self.result_code = result_code
        self.code = result_code
        super().__init__(result_code)


_UNSET = object()


@dataclass(frozen=True, slots=True)
class RoutineScope:
    """The live workspace context and owner filter used by routine services."""

    user_id: UUID
    workspace_id: UUID


@dataclass(frozen=True, slots=True)
class RoutinePage:
    """A bounded owner-scoped page of eligible routine projections."""

    items: tuple[Routine, ...]
    next_cursor: str | None


def _routine_cursor_payload(
    *,
    scope: RoutineScope,
    ally_id: UUID | None,
    routine: Routine,
) -> str:
    payload = {
        "version": 1,
        "workspace_id": str(scope.workspace_id),
        "owner_user_id": str(scope.user_id),
        "ally_id": str(ally_id) if ally_id is not None else None,
        "created_at": routine.created_at.astimezone(UTC).isoformat(),
        "routine_id": str(routine.id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    signature = digest_value(f"routine-page-v1:{encoded}")
    return f"{encoded}.{signature}"


def _routine_cursor(
    *,
    cursor: str,
    scope: RoutineScope,
    ally_id: UUID | None,
) -> tuple[datetime, UUID]:
    try:
        encoded, signature = cursor.rsplit(".", 1)
        expected = digest_value(f"routine-page-v1:{encoded}")
        if not hmac.compare_digest(signature, expected):
            raise RoutineCursorInvalid("routine cursor signature is invalid")
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(raw)
        if not isinstance(payload, Mapping):
            raise RoutineCursorInvalid("routine cursor is invalid")
        if (
            payload.get("version") != 1
            or payload.get("workspace_id") != str(scope.workspace_id)
            or payload.get("owner_user_id") != str(scope.user_id)
            or payload.get("ally_id") != (str(ally_id) if ally_id else None)
        ):
            raise RoutineCursorInvalid("routine cursor is bound to another query")
        parsed_created_at = datetime.fromisoformat(str(payload["created_at"]))
        if parsed_created_at.tzinfo is None:
            raise RoutineCursorInvalid("routine cursor timestamp is invalid")
        created_at = parsed_created_at.astimezone(UTC)
        routine_id = canonical_uuid(payload["routine_id"])
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        binascii.Error,
    ) as exc:
        raise RoutineCursorInvalid("routine cursor is invalid") from exc
    return created_at, routine_id


def _scope(*, user, workspace_id: UUID | str, capability: Capability) -> RoutineScope:
    context = require_workspace_capability(
        user=user,
        workspace_id=workspace_id,
        capability=capability,
    )
    return RoutineScope(user_id=user.id, workspace_id=context.workspace.id)


def _validate_text(*, title: str, execution_prompt: str) -> None:
    if not isinstance(title, str) or not title.strip():
        raise ValidationError({"title": "title is required"})
    if len(title) > ROUTINE_TITLE_MAX_LENGTH:
        raise ValidationError({"title": "title is too long"})
    if not isinstance(execution_prompt, str) or not execution_prompt.strip():
        raise ValidationError({"execution_prompt": "execution prompt is required"})
    if len(execution_prompt.encode("utf-8")) > ROUTINE_PROMPT_MAX_BYTES:
        raise ValidationError(
            {"execution_prompt": "execution prompt exceeds the byte limit"}
        )


def _canonical_schedule(
    value: Mapping[str, object],
) -> tuple[ScheduleSpec, dict[str, object]]:
    spec = validate_schedule(value)
    return spec, spec.as_dict()


def _next_run(*, spec: ScheduleSpec, now: datetime) -> datetime:
    return resolve_next_occurrence(spec, after=now)


def _receipt_key(value: UUID | str | None) -> UUID:
    if value is None:
        return uuid4()
    try:
        return canonical_uuid(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("routine management identity is invalid") from exc


def _create_management_receipt(
    *,
    routine: Routine,
    operation: str,
    result_code: str,
    issued_at: datetime,
    confirmation: RoutineDeletionConfirmation | None = None,
    resume_effective_at: datetime | None = None,
    command_id: UUID | str | None = None,
    idempotency_key: UUID | str | None = None,
) -> RoutineManagementReceipt:
    return RoutineManagementReceipt.objects.create(
        confirmation=confirmation,
        command_id=_receipt_key(command_id),
        idempotency_key=_receipt_key(idempotency_key),
        routine=routine,
        workspace_id=routine.workspace_id,
        owner_id=routine.owner_id,
        ally_id=routine.ally_id,
        binding_id=routine.binding_id,
        operation=operation,
        outcome="saved",
        result_code=result_code,
        revision=routine.revision,
        schedule_generation=routine.schedule_generation,
        schedule_state=routine.state,
        next_run_at=routine.next_run_at,
        resume_effective_at=resume_effective_at,
        issued_at=issued_at,
    )


@transaction.atomic
def create_routine_intent(
    *,
    user,
    workspace_id: UUID | str,
    ally_id: UUID | str,
    main_conversation_id: UUID | str,
    title: str,
    execution_prompt: str,
    schedule: Mapping[str, object],
    now: datetime | None = None,
    command_id: UUID | str | None = None,
    idempotency_key: UUID | str | None = None,
) -> Routine:
    """Persist a fully validated, owner-scoped routine intent."""

    scope = _scope(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.WORKSPACE_WRITE,
    )
    _validate_text(title=title, execution_prompt=execution_prompt)
    spec, canonical_schedule = _canonical_schedule(schedule)
    try:
        conversation_id = canonical_uuid(main_conversation_id)
        parsed_ally_id = canonical_uuid(ally_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("routine identity is invalid") from exc
    ally = (
        Ally.objects.select_related("binding")
        .filter(pk=parsed_ally_id, workspace_id=scope.workspace_id)
        .first()
    )
    if ally is None:
        raise ValidationError({"ally": "ally is outside the routine workspace"})
    try:
        binding = ally.binding
    except AllyBinding.DoesNotExist as exc:
        raise ValidationError({"ally": "ally has no binding"}) from exc
    if not Conversation.objects.filter(
        pk=conversation_id,
        ally_id=parsed_ally_id,
    ).exists():
        raise ValidationError(
            {"main_conversation_id": "conversation is outside the routine ally"}
        )

    now = now or timezone.now()
    routine = Routine(
        workspace_id=scope.workspace_id,
        owner_id=scope.user_id,
        ally=ally,
        binding=binding,
        main_conversation_id=conversation_id,
        title=title,
        execution_prompt=execution_prompt,
        schedule=canonical_schedule,
        next_run_at=_next_run(spec=spec, now=now),
    )
    routine.full_clean()
    routine.save()
    _create_management_receipt(
        routine=routine,
        operation="create",
        result_code="MANAGEMENT_SAVED",
        issued_at=now,
        command_id=command_id,
        idempotency_key=idempotency_key,
    )
    return routine


def owner_routines(
    *,
    user,
    workspace_id: UUID | str,
    include_history: bool = False,
):
    """Return routines owned by the caller within an authorized workspace."""

    scope = _scope(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.WORKSPACE_READ,
    )
    routines = (
        Routine.objects.select_related("workspace", "owner", "ally", "binding")
        .filter(
            workspace_id=scope.workspace_id,
            owner_id=scope.user_id,
            ally__workspace_id=scope.workspace_id,
            binding__ally_id=F("ally_id"),
        )
        .order_by("created_at", "id")
    )
    if not include_history:
        routines = routines.filter(state__in=(RoutineState.ACTIVE, RoutineState.PAUSED))
    return routines


def owner_routine_page(
    *,
    user,
    workspace_id: UUID | str,
    limit: int = 50,
    cursor: str | None = None,
    ally_id: UUID | str | None = None,
) -> RoutinePage:
    """Return an opaque, owner- and filter-bound keyset page of live routines."""

    if not 1 <= limit <= 100:
        raise RoutineCursorInvalid("routine page limit is invalid")
    scope = _scope(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.WORKSPACE_READ,
    )
    parsed_ally_id: UUID | None = None
    if ally_id is not None:
        try:
            parsed_ally_id = canonical_uuid(ally_id)
        except (TypeError, ValueError) as exc:
            raise RoutineCursorInvalid("routine ally filter is invalid") from exc

    routines = owner_routines(
        user=user,
        workspace_id=scope.workspace_id,
        include_history=False,
    )
    if parsed_ally_id is not None:
        routines = routines.filter(ally_id=parsed_ally_id)
    if cursor:
        created_at, routine_id = _routine_cursor(
            cursor=cursor,
            scope=scope,
            ally_id=parsed_ally_id,
        )
        routines = routines.filter(
            Q(created_at__gt=created_at) | Q(created_at=created_at, id__gt=routine_id)
        )

    rows = tuple(routines[: limit + 1])
    selected = rows[:limit]
    next_cursor = None
    if len(rows) > limit and selected:
        next_cursor = _routine_cursor_payload(
            scope=scope,
            ally_id=parsed_ally_id,
            routine=selected[-1],
        )
    return RoutinePage(items=selected, next_cursor=next_cursor)


def owner_routine(
    *,
    user,
    workspace_id: UUID | str,
    routine_id: UUID | str,
    include_history: bool = True,
) -> Routine:
    try:
        parsed_routine_id = canonical_uuid(routine_id)
    except (TypeError, ValueError) as exc:
        raise Routine.DoesNotExist from exc
    routines = owner_routines(
        user=user,
        workspace_id=workspace_id,
        include_history=include_history,
    )
    return routines.get(pk=parsed_routine_id)


def _confirmation_scope(routine: Routine) -> dict[str, str]:
    return {
        "kind": "workspace",
        "workspace_id": str(routine.workspace_id),
        "owner_user_id": str(routine.owner_id),
        "ally_id": str(routine.ally_id),
        "cloud_binding_id": str(routine.binding_id),
    }


@transaction.atomic
def issue_deletion_confirmation(
    *,
    user,
    workspace_id: UUID | str,
    routine_id: UUID | str,
    expected_revision: int,
    main_conversation_id: UUID | str,
    now: datetime | None = None,
) -> dict[str, object]:
    """Issue a one-shot deletion challenge bound to the current routine revision."""

    scope = _scope(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.WORKSPACE_WRITE,
    )
    try:
        parsed_routine_id = canonical_uuid(routine_id)
        parsed_conversation_id = canonical_uuid(main_conversation_id)
    except (TypeError, ValueError) as exc:
        raise RoutineConfirmationError(CONFIRMATION_WRONG_CONVERSATION) from exc

    routine = (
        Routine.objects.select_for_update()
        .select_related("ally", "binding")
        .get(
            pk=parsed_routine_id,
            workspace_id=scope.workspace_id,
            owner_id=scope.user_id,
            ally__workspace_id=scope.workspace_id,
            binding__ally_id=F("ally_id"),
        )
    )
    if routine.state == RoutineState.DELETED:
        raise RoutineStateError("deleted routine cannot be confirmed")
    if routine.revision != expected_revision:
        raise RoutineConfirmationError(CONFIRMATION_STALE)
    if parsed_conversation_id != routine.main_conversation_id:
        raise RoutineConfirmationError(CONFIRMATION_WRONG_CONVERSATION)
    if not Conversation.objects.filter(
        pk=parsed_conversation_id,
        ally_id=routine.ally_id,
    ).exists():
        raise RoutineConfirmationError(CONFIRMATION_WRONG_CONVERSATION)

    issued_at = now or timezone.now()
    confirmation_ref = str(uuid4())
    RoutineDeletionConfirmation.objects.create(
        reference_digest=digest_value(confirmation_ref),
        routine=routine,
        workspace_id=routine.workspace_id,
        owner_id=routine.owner_id,
        ally_id=routine.ally_id,
        binding_id=routine.binding_id,
        main_conversation_id=routine.main_conversation_id,
        expected_revision=routine.revision,
        state=RoutineDeletionConfirmationState.UNCONSUMED,
        issued_at=issued_at,
    )
    return {
        "confirmation_ref": confirmation_ref,
        "scope": _confirmation_scope(routine),
        "main_conversation_id": str(routine.main_conversation_id),
        "routine_id": str(routine.id),
        "expected_revision": routine.revision,
        "state": RoutineDeletionConfirmationState.UNCONSUMED,
    }


def _confirmation_digest(confirmation_ref: str | None) -> str:
    if not confirmation_ref or not isinstance(confirmation_ref, str):
        raise RoutineConfirmationError(CONFIRMATION_REQUIRED)
    return digest_value(confirmation_ref)


@transaction.atomic
def delete_routine_intent(
    *,
    user,
    workspace_id: UUID | str,
    routine_id: UUID | str,
    expected_revision: int,
    main_conversation_id: UUID | str,
    confirmation_ref: str | None,
    now: datetime | None = None,
    command_id: UUID | str | None = None,
    idempotency_key: UUID | str | None = None,
) -> Routine:
    """Consume an exact deletion confirmation and delete its routine atomically."""

    scope = _scope(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.WORKSPACE_WRITE,
    )
    digest = _confirmation_digest(confirmation_ref)
    try:
        parsed_routine_id = canonical_uuid(routine_id)
        parsed_conversation_id = canonical_uuid(main_conversation_id)
    except (TypeError, ValueError) as exc:
        raise RoutineConfirmationError(CONFIRMATION_WRONG_CONVERSATION) from exc

    routine = (
        Routine.objects.select_for_update()
        .select_related("ally", "binding")
        .get(
            pk=parsed_routine_id,
            workspace_id=scope.workspace_id,
            owner_id=scope.user_id,
            ally__workspace_id=scope.workspace_id,
            binding__ally_id=F("ally_id"),
        )
    )
    try:
        confirmation = (
            RoutineDeletionConfirmation.objects.select_for_update()
            .select_related("routine")
            .get(reference_digest=digest)
        )
    except RoutineDeletionConfirmation.DoesNotExist as exc:
        raise RoutineConfirmationError(CONFIRMATION_REQUIRED) from exc

    if confirmation.state == RoutineDeletionConfirmationState.CONSUMED:
        raise RoutineConfirmationError(CONFIRMATION_REPLAYED)
    if (
        routine.revision != expected_revision
        or confirmation.expected_revision != expected_revision
        or confirmation.expected_revision != routine.revision
    ):
        raise RoutineConfirmationError(CONFIRMATION_STALE)
    if (
        parsed_conversation_id != routine.main_conversation_id
        or confirmation.main_conversation_id != parsed_conversation_id
    ):
        raise RoutineConfirmationError(CONFIRMATION_WRONG_CONVERSATION)
    if confirmation.owner_id != routine.owner_id:
        raise RoutineConfirmationError(CONFIRMATION_WRONG_OWNER)
    if confirmation.workspace_id != routine.workspace_id:
        raise RoutineConfirmationError(CONFIRMATION_WRONG_WORKSPACE)
    if confirmation.ally_id != routine.ally_id:
        raise RoutineConfirmationError(CONFIRMATION_WRONG_ALLY)
    if confirmation.binding_id != routine.binding_id:
        raise RoutineConfirmationError(CONFIRMATION_WRONG_BINDING)
    if confirmation.routine_id != routine.id:
        raise RoutineConfirmationError(CONFIRMATION_WRONG_ROUTINE)
    if routine.state == RoutineState.DELETED:
        raise RoutineStateError("deleted routine cannot be changed")

    deleted_at = now or timezone.now()
    routine.state = RoutineState.DELETED
    routine.deleted_at = deleted_at
    routine.next_run_at = None
    routine.revision += 1
    routine.full_clean()
    routine.save(
        update_fields=(
            "state",
            "deleted_at",
            "next_run_at",
            "revision",
            "updated_at",
        )
    )
    confirmation.state = RoutineDeletionConfirmationState.CONSUMED
    confirmation.consumed_at = deleted_at
    confirmation.save(update_fields=("state", "consumed_at", "updated_at"))
    _create_management_receipt(
        confirmation=confirmation,
        routine=routine,
        operation="delete",
        result_code="MANAGEMENT_SAVED",
        issued_at=deleted_at,
        command_id=command_id,
        idempotency_key=idempotency_key,
    )
    return routine


@transaction.atomic
def update_routine_intent(
    *,
    user,
    workspace_id: UUID | str,
    routine_id: UUID | str,
    expected_revision: int,
    title: str | object = _UNSET,
    execution_prompt: str | object = _UNSET,
    schedule: Mapping[str, object] | object = _UNSET,
    state: RoutineState | str | object = _UNSET,
    now: datetime | None = None,
    command_id: UUID | str | None = None,
    idempotency_key: UUID | str | None = None,
) -> Routine:
    """Apply a small locked CAS mutation without changing owner ancestry."""

    scope = _scope(
        user=user,
        workspace_id=workspace_id,
        capability=Capability.WORKSPACE_WRITE,
    )
    try:
        parsed_routine_id = canonical_uuid(routine_id)
    except (TypeError, ValueError) as exc:
        raise Routine.DoesNotExist from exc
    routine = (
        Routine.objects.select_for_update()
        .select_related("ally", "binding")
        .get(
            pk=parsed_routine_id,
            workspace_id=scope.workspace_id,
            owner_id=scope.user_id,
            ally__workspace_id=scope.workspace_id,
            binding__ally_id=F("ally_id"),
        )
    )
    if routine.revision != expected_revision:
        raise RoutineRevisionConflict("routine revision is stale")
    if routine.state == RoutineState.DELETED:
        raise RoutineStateError("deleted routine cannot be changed")

    changes: dict[str, object] = {}
    schedule_changed = False
    state_changed = False
    spec = validate_schedule(routine.schedule)
    if title is not _UNSET:
        _validate_text(title=title, execution_prompt=routine.execution_prompt)
        if title != routine.title:
            changes["title"] = title
    if execution_prompt is not _UNSET:
        _validate_text(title=routine.title, execution_prompt=execution_prompt)
        if execution_prompt != routine.execution_prompt:
            changes["execution_prompt"] = execution_prompt
    if schedule is not _UNSET:
        spec, canonical_schedule = _canonical_schedule(schedule)
        schedule_changed = canonical_schedule != routine.schedule
        if schedule_changed:
            changes["schedule"] = canonical_schedule
    if state is not _UNSET:
        try:
            requested_state = RoutineState(
                state.value if isinstance(state, RoutineState) else str(state)
            )
        except ValueError as exc:
            raise RoutineStateError("unknown routine state") from exc
        if requested_state == RoutineState.DELETED:
            raise RoutineConfirmationError(CONFIRMATION_REQUIRED)
        state_changed = requested_state != routine.state
        if state_changed:
            if routine.state == RoutineState.DELETED:
                raise RoutineStateError("deleted routine cannot be resumed")
            changes["state"] = requested_state

    effective_state = changes["state"] if state_changed else routine.state
    if effective_state == RoutineState.PAUSED and spec.kind.value == "once":
        raise RoutineStateError("one-time routines cannot be paused")

    if not changes:
        return routine

    now = now or timezone.now()
    if schedule_changed:
        if routine.state == RoutineState.PAUSED:
            changes["next_run_at"] = None
        else:
            changes["next_run_at"] = _next_run(spec=spec, now=now)
    if state_changed:
        requested_state = changes["state"]
        if requested_state == RoutineState.PAUSED:
            changes["next_run_at"] = None
        elif requested_state == RoutineState.ACTIVE:
            changes["next_run_at"] = _next_run(spec=spec, now=now)
            changes["resume_boundary"] = now
        elif requested_state == RoutineState.DELETED:
            changes["deleted_at"] = now
            changes["next_run_at"] = None
        elif requested_state == RoutineState.EXHAUSTED:
            changes["next_run_at"] = None

    routine.revision += 1
    if schedule_changed or state_changed:
        routine.schedule_generation += 1
    for field, value in changes.items():
        setattr(routine, field, value)
    routine.full_clean()
    routine.save(
        update_fields=tuple({*changes, "revision", "schedule_generation", "updated_at"})
    )
    operation = "update"
    result_code = "MANAGEMENT_SAVED"
    resume_effective_at = None
    if state_changed and changes["state"] == RoutineState.PAUSED:
        operation = "pause"
    elif state_changed and changes["state"] == RoutineState.ACTIVE:
        operation = "resume"
        result_code = "ROUTINE_RESUMED"
        resume_effective_at = changes.get("resume_boundary")
    _create_management_receipt(
        routine=routine,
        operation=operation,
        result_code=result_code,
        issued_at=now,
        resume_effective_at=resume_effective_at,
        command_id=command_id,
        idempotency_key=idempotency_key,
    )
    return routine


__all__ = [
    "CONFIRMATION_REPLAYED",
    "CONFIRMATION_REQUIRED",
    "CONFIRMATION_STALE",
    "CONFIRMATION_WRONG_ALLY",
    "CONFIRMATION_WRONG_BINDING",
    "CONFIRMATION_WRONG_CONVERSATION",
    "CONFIRMATION_WRONG_OWNER",
    "CONFIRMATION_WRONG_ROUTINE",
    "CONFIRMATION_WRONG_WORKSPACE",
    "RoutineConfirmationError",
    "RoutineCursorInvalid",
    "RoutinePage",
    "RoutineRevisionConflict",
    "RoutineScope",
    "RoutineStateError",
    "create_routine_intent",
    "delete_routine_intent",
    "issue_deletion_confirmation",
    "owner_routine",
    "owner_routine_page",
    "owner_routines",
    "update_routine_intent",
]
