"""Cloud-owned due scanning and atomic routine occurrence admission."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from allies.gateways.contracts import canonical_fingerprint, canonical_json_bytes
from chat.models import Conversation

from ..models import (
    ROUTINE_ACTIVE_RUN_OUTCOMES,
    Routine,
    RoutineApprovalCommand,
    RoutineApprovalCommandKind,
    RoutineApprovalDeliveryState,
    RoutineApprovalProjection,
    RoutineApprovalStatus,
    RoutineDispatchOutbox,
    RoutineDispatchState,
    RoutineOccurrence,
    RoutineOccurrenceDisposition,
    RoutineRunOutcome,
    RoutineRunSnapshot,
    RoutineState,
)
from .approvals import (
    RoutineApprovalConflict,
    RoutineApprovalUnavailable,
    request_routine_approval_replacement,
)
from .schedule import (
    NoFutureOccurrence,
    ScheduleKind,
    resolve_next_occurrence,
    validate_schedule,
)

ROUTINE_DISPATCH_DEADLINE_SECONDS = 60
ROUTINE_SCAN_MAX = 100
ROUTINE_RECOVERY_ITERATIONS = 10_000

STALE_DUE_CANDIDATE = "STALE_DUE_CANDIDATE"
ROUTINE_DELETED = "ROUTINE_DELETED"
ROUTINE_PAUSED = "ROUTINE_PAUSED"
ROUTINE_EXHAUSTED = "ROUTINE_EXHAUSTED"
CANDIDATE_SUPERSEDED = "CANDIDATE_SUPERSEDED"
NOT_DUE = "NOT_DUE"
OCCURRENCE_REPLAY = "OCCURRENCE_REPLAY"
OCCURRENCE_SKIPPED_ACTIVE = "OCCURRENCE_SKIPPED_ACTIVE"
OCCURRENCE_ADMITTED = "OCCURRENCE_ADMITTED"
OCCURRENCE_REPLACEMENT_PENDING = "OCCURRENCE_REPLACEMENT_PENDING"


@dataclass(frozen=True, slots=True)
class DueRoutineCandidate:
    routine_id: UUID
    scheduled_at: datetime
    observed_revision: int
    observed_schedule_generation: int


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    result_code: str
    occurrence: RoutineOccurrence | None = None
    run: RoutineRunSnapshot | None = None
    outbox: RoutineDispatchOutbox | None = None
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class SchedulerReport:
    candidates: int = 0
    admitted: int = 0
    replayed: int = 0
    skipped_active: int = 0
    replacement_pending: int = 0
    stale: int = 0
    not_due: int = 0
    paused: int = 0
    exhausted: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "candidates": self.candidates,
            "admitted": self.admitted,
            "replayed": self.replayed,
            "skipped_active": self.skipped_active,
            "stale": self.stale,
            "not_due": self.not_due,
            "paused": self.paused,
            "exhausted": self.exhausted,
        }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("routine scheduler timestamps must be timezone-aware")
    return value.astimezone(UTC).replace(microsecond=0)


def _wire_timestamp(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _next_after(schedule: dict[str, Any], *, after: datetime) -> datetime | None:
    try:
        return _utc(resolve_next_occurrence(schedule, after=_utc(after)))
    except NoFutureOccurrence:
        return None


def _latest_missed(
    schedule: dict[str, Any], *, first: datetime, now: datetime
) -> tuple[datetime, bool]:
    """Select the latest missed recurring instant once, without replaying a backlog."""

    candidate = _utc(first)
    boundary = _utc(now)
    if candidate >= boundary:
        return candidate, False
    if validate_schedule(schedule).kind is ScheduleKind.ONCE:
        return candidate, True
    for _ in range(ROUTINE_RECOVERY_ITERATIONS):
        following = _next_after(schedule, after=candidate)
        if following is None or following > boundary:
            return candidate, True
        candidate = following
    raise ValueError("routine recovery exceeded its bounded scan")


def due_routine_candidates(
    *, now: datetime | None = None, limit: int = ROUTINE_SCAN_MAX
) -> tuple[DueRoutineCandidate, ...]:
    """Read a bounded candidate batch without treating the read as admission."""

    bound = max(1, min(int(limit), ROUTINE_SCAN_MAX))
    boundary = _utc(now or timezone.now())
    rows = (
        Routine.objects.filter(
            state=RoutineState.ACTIVE,
            next_run_at__isnull=False,
            next_run_at__lte=boundary,
        )
        .order_by("next_run_at", "id")
        .values("id", "next_run_at", "revision", "schedule_generation")[:bound]
    )
    return tuple(
        DueRoutineCandidate(
            routine_id=row["id"],
            scheduled_at=_utc(row["next_run_at"]),
            observed_revision=row["revision"],
            observed_schedule_generation=row["schedule_generation"],
        )
        for row in rows
    )


def _dispatch_values(
    *,
    routine: Routine,
    occurrence: RoutineOccurrence,
    run: RoutineRunSnapshot,
    issued_at: datetime,
) -> tuple[dict[str, Any], bytes, str]:
    command_id = uuid4()
    issued = _utc(issued_at)
    deadline = issued + timedelta(seconds=ROUTINE_DISPATCH_DEADLINE_SECONDS)
    values: dict[str, Any] = {
        "schema_version": "v1",
        "kind": "routine.dispatch",
        "producer": "cloud",
        "service_identity": "cloud-service",
        "command_id": str(command_id),
        "idempotency_key": str(command_id),
        "routine_id": str(routine.id),
        "routine_revision": run.routine_revision,
        "schedule_generation": run.schedule_generation,
        "occurrence_id": str(occurrence.id),
        "run_id": str(run.id),
        "schedule": run.schedule_snapshot,
        "scheduled_at": _wire_timestamp(run.scheduled_at),
        "delayed": run.delayed,
        "occurrence_disposition": occurrence.disposition,
        "main_conversation_id": str(run.main_conversation_id),
        "run_conversation_id": str(run.run_conversation_id),
        "cloud_binding_id": str(routine.binding_id),
        "execution_prompt": run.execution_prompt,
        "title_snapshot": run.title_snapshot,
        "scope": {
            "kind": "workspace",
            "workspace_id": str(routine.workspace_id),
            "owner_user_id": str(routine.owner_id),
            "ally_id": str(routine.ally_id),
            "cloud_binding_id": str(routine.binding_id),
        },
        "issued_at": _wire_timestamp(issued),
        "deadline_at": _wire_timestamp(deadline),
    }
    values["fingerprint"] = canonical_fingerprint(values)
    body = canonical_json_bytes(values)
    return values, body, hashlib.sha256(body).hexdigest()


def _advance_after_admission(
    routine: Routine, *, schedule: dict[str, Any], now: datetime
) -> None:
    parsed = validate_schedule(schedule)
    if parsed.kind is ScheduleKind.ONCE:
        routine.state = RoutineState.EXHAUSTED
        routine.next_run_at = None
        routine.revision += 1
        routine.save(update_fields=("state", "next_run_at", "revision", "updated_at"))
        return
    next_run_at = _next_after(schedule, after=now)
    if next_run_at is None:
        raise NoFutureOccurrence("recurring routine has no future occurrence")
    routine.next_run_at = next_run_at
    routine.save(update_fields=("next_run_at", "updated_at"))


def _advance_after_skip(
    routine: Routine, *, schedule: dict[str, Any], now: datetime
) -> None:
    if validate_schedule(schedule).kind is ScheduleKind.ONCE:
        routine.state = RoutineState.EXHAUSTED
        routine.next_run_at = None
        routine.revision += 1
        routine.save(update_fields=("state", "next_run_at", "revision", "updated_at"))
        return
    next_run_at = _next_after(schedule, after=now)
    if next_run_at is None:
        raise NoFutureOccurrence("recurring routine has no future occurrence")
    routine.next_run_at = next_run_at
    routine.save(update_fields=("next_run_at", "updated_at"))


def _create_admitted_run_locked(
    *,
    routine: Routine,
    occurrence: RoutineOccurrence,
    schedule: dict[str, Any],
    scheduled_at: datetime,
    delayed: bool,
    boundary: datetime,
) -> tuple[RoutineRunSnapshot, RoutineDispatchOutbox]:
    """Create the run/outbox after a prior approval cancellation is effective."""

    run_conversation = Conversation.objects.create(
        ally=routine.ally,
        is_default=False,
    )
    run = RoutineRunSnapshot(
        occurrence=occurrence,
        routine=routine,
        workspace_id=routine.workspace_id,
        owner_id=routine.owner_id,
        ally_id=routine.ally_id,
        binding_id=routine.binding_id,
        routine_revision=routine.revision,
        schedule_generation=routine.schedule_generation,
        title_snapshot=routine.title,
        execution_prompt=routine.execution_prompt,
        schedule_snapshot=schedule,
        timezone=schedule["timezone"],
        scheduled_at=scheduled_at,
        occurrence_disposition=occurrence.disposition,
        delayed=delayed,
        main_conversation_id=routine.main_conversation_id,
        run_conversation_id=run_conversation.id,
        outcome=RoutineRunOutcome.QUEUED,
    )
    run.full_clean()
    run.save()
    values, body, body_digest = _dispatch_values(
        routine=routine,
        occurrence=occurrence,
        run=run,
        issued_at=boundary,
    )
    outbox = RoutineDispatchOutbox(
        routine=routine,
        occurrence=occurrence,
        run=run,
        command_id=UUID(values["command_id"]),
        idempotency_key=UUID(values["command_id"]),
        command_bytes=body,
        command_byte_length=len(body),
        command_sha256=body_digest,
        command_fingerprint=values["fingerprint"],
        status=RoutineDispatchState.PENDING,
        next_attempt_at=boundary,
    )
    outbox.full_clean()
    outbox.save()
    _advance_after_admission(routine, schedule=schedule, now=boundary)
    return run, outbox


def _replacement_command_for(occurrence: RoutineOccurrence):
    return (
        RoutineApprovalCommand.objects.select_related("approval")
        .filter(
            replacing_occurrence=occurrence,
            kind=RoutineApprovalCommandKind.CANCEL_WAIT,
        )
        .first()
    )


def _replacement_is_effective(command) -> bool:
    return bool(
        command
        and command.status == RoutineApprovalDeliveryState.ACCEPTED
        and command.approval.status
        in {
            RoutineApprovalStatus.CANCELLED,
            RoutineApprovalStatus.EXPIRED,
            RoutineApprovalStatus.REJECTED,
        }
    )


def _prepare_approval_replacement_locked(
    *,
    routine: Routine,
    active_run: RoutineRunSnapshot,
    scheduled_at: datetime,
    delayed: bool,
    boundary: datetime,
) -> RoutineOccurrence | None:
    approval = (
        RoutineApprovalProjection.objects.select_for_update()
        .filter(
            run=active_run,
            status__in=(
                RoutineApprovalStatus.PENDING,
                RoutineApprovalStatus.DECISION_RECORDED,
                RoutineApprovalStatus.AUTHORIZING,
            ),
        )
        .order_by("created_at", "id")
        .last()
    )
    if approval is None:
        return None
    occurrence = (
        RoutineOccurrence.objects.select_for_update()
        .filter(routine=routine, scheduled_at=scheduled_at)
        .first()
    )
    if occurrence is None:
        occurrence = RoutineOccurrence(
            routine=routine,
            workspace_id=routine.workspace_id,
            owner_id=routine.owner_id,
            ally_id=routine.ally_id,
            binding_id=routine.binding_id,
            scheduled_at=scheduled_at,
            observed_revision=routine.revision,
            observed_schedule_generation=routine.schedule_generation,
            disposition=RoutineOccurrenceDisposition.ADMITTED,
            delayed=delayed,
        )
        occurrence.full_clean()
        occurrence.save()
    try:
        request_routine_approval_replacement(
            approval_id=approval.id,
            replacing_occurrence_id=occurrence.id,
            reason="replacement",
            now=boundary,
        )
    except (RoutineApprovalConflict, RoutineApprovalUnavailable):
        # A concurrent expiry/decision or a terminal Foundry projection leaves
        # the existing occurrence fenced; the next scan re-evaluates it.
        return occurrence
    return occurrence


@transaction.atomic
def admit_due_candidate(
    candidate: DueRoutineCandidate, *, now: datetime | None = None
) -> AdmissionResult:
    """Admit one candidate under the locked routine revision/generation fence."""

    boundary = _utc(now or timezone.now())
    routine = (
        Routine.objects.select_for_update()
        .select_related("ally", "binding")
        .get(pk=candidate.routine_id)
    )
    if routine.state == RoutineState.DELETED:
        return AdmissionResult(ROUTINE_DELETED)
    if routine.state == RoutineState.PAUSED:
        return AdmissionResult(ROUTINE_PAUSED)
    if routine.state == RoutineState.EXHAUSTED:
        return AdmissionResult(ROUTINE_EXHAUSTED)
    if (
        routine.revision != candidate.observed_revision
        or routine.schedule_generation != candidate.observed_schedule_generation
    ):
        return AdmissionResult(STALE_DUE_CANDIDATE)
    if routine.next_run_at is None:
        return AdmissionResult(CANDIDATE_SUPERSEDED)
    if _utc(routine.next_run_at) != _utc(candidate.scheduled_at):
        return AdmissionResult(CANDIDATE_SUPERSEDED)
    if routine.next_run_at > boundary:
        return AdmissionResult(NOT_DUE)

    schedule = validate_schedule(routine.schedule).as_dict()
    scheduled_at, delayed = _latest_missed(
        schedule,
        first=routine.next_run_at,
        now=boundary,
    )
    active_run = (
        RoutineRunSnapshot.objects.select_for_update()
        .filter(routine=routine, outcome__in=ROUTINE_ACTIVE_RUN_OUTCOMES)
        .first()
    )
    existing = (
        RoutineOccurrence.objects.select_for_update()
        .filter(routine=routine, scheduled_at=scheduled_at)
        .first()
    )
    if existing is not None:
        try:
            existing_run = existing.run_snapshot
        except RoutineRunSnapshot.DoesNotExist:
            existing_run = None
        if existing_run is None:
            replacement = _replacement_command_for(existing)
            if _replacement_is_effective(replacement):
                run, outbox = _create_admitted_run_locked(
                    routine=routine,
                    occurrence=existing,
                    schedule=schedule,
                    scheduled_at=scheduled_at,
                    delayed=existing.delayed,
                    boundary=boundary,
                )
                return AdmissionResult(
                    OCCURRENCE_ADMITTED,
                    occurrence=existing,
                    run=run,
                    outbox=outbox,
                )
            if replacement is not None:
                return AdmissionResult(
                    OCCURRENCE_REPLACEMENT_PENDING,
                    occurrence=existing,
                )
        try:
            existing_outbox = existing_run.dispatch_outbox if existing_run else None
        except RoutineDispatchOutbox.DoesNotExist:
            existing_outbox = None
        return AdmissionResult(
            OCCURRENCE_REPLAY,
            occurrence=existing,
            run=existing_run,
            outbox=existing_outbox,
            replayed=True,
        )

    disposition = (
        RoutineOccurrenceDisposition.RECOVERED
        if delayed
        else RoutineOccurrenceDisposition.ADMITTED
    )
    if active_run is not None:
        if active_run.outcome == RoutineRunOutcome.APPROVAL_WAITING:
            replacement = _prepare_approval_replacement_locked(
                routine=routine,
                active_run=active_run,
                scheduled_at=scheduled_at,
                delayed=delayed,
                boundary=boundary,
            )
            if replacement is not None:
                return AdmissionResult(
                    OCCURRENCE_REPLACEMENT_PENDING,
                    occurrence=replacement,
                )
        occurrence = RoutineOccurrence(
            routine=routine,
            workspace_id=routine.workspace_id,
            owner_id=routine.owner_id,
            ally_id=routine.ally_id,
            binding_id=routine.binding_id,
            scheduled_at=scheduled_at,
            observed_revision=candidate.observed_revision,
            observed_schedule_generation=candidate.observed_schedule_generation,
            disposition=RoutineOccurrenceDisposition.SKIPPED_ACTIVE,
            delayed=delayed,
        )
        occurrence.full_clean()
        occurrence.save()
        _advance_after_skip(routine, schedule=schedule, now=boundary)
        return AdmissionResult(OCCURRENCE_SKIPPED_ACTIVE, occurrence=occurrence)

    occurrence = RoutineOccurrence(
        routine=routine,
        workspace_id=routine.workspace_id,
        owner_id=routine.owner_id,
        ally_id=routine.ally_id,
        binding_id=routine.binding_id,
        scheduled_at=scheduled_at,
        observed_revision=candidate.observed_revision,
        observed_schedule_generation=candidate.observed_schedule_generation,
        disposition=disposition,
        delayed=delayed,
    )
    occurrence.full_clean()
    occurrence.save()
    run, outbox = _create_admitted_run_locked(
        routine=routine,
        occurrence=occurrence,
        schedule=schedule,
        scheduled_at=scheduled_at,
        delayed=delayed,
        boundary=boundary,
    )
    return AdmissionResult(
        OCCURRENCE_ADMITTED,
        occurrence=occurrence,
        run=run,
        outbox=outbox,
    )


def admit_due_routines(
    *, now: datetime | None = None, limit: int = ROUTINE_SCAN_MAX
) -> SchedulerReport:
    """Admit a bounded candidate batch; every result is fenced independently."""

    boundary = _utc(now or timezone.now())
    candidates = due_routine_candidates(now=boundary, limit=limit)
    counts = {
        "admitted": 0,
        "replayed": 0,
        "skipped_active": 0,
        "replacement_pending": 0,
        "stale": 0,
        "not_due": 0,
        "paused": 0,
        "exhausted": 0,
    }
    for candidate in candidates:
        result = admit_due_candidate(candidate, now=boundary)
        if result.result_code == OCCURRENCE_ADMITTED:
            counts["admitted"] += 1
        elif result.result_code == OCCURRENCE_REPLAY:
            counts["replayed"] += 1
        elif result.result_code == OCCURRENCE_SKIPPED_ACTIVE:
            counts["skipped_active"] += 1
        elif result.result_code == OCCURRENCE_REPLACEMENT_PENDING:
            counts["replacement_pending"] += 1
        elif result.result_code == STALE_DUE_CANDIDATE:
            counts["stale"] += 1
        elif result.result_code == NOT_DUE:
            counts["not_due"] += 1
        elif result.result_code == ROUTINE_PAUSED:
            counts["paused"] += 1
        elif result.result_code in {ROUTINE_EXHAUSTED, ROUTINE_DELETED}:
            counts["exhausted"] += 1
    return SchedulerReport(candidates=len(candidates), **counts)


__all__ = [
    "CANDIDATE_SUPERSEDED",
    "NOT_DUE",
    "OCCURRENCE_ADMITTED",
    "OCCURRENCE_REPLACEMENT_PENDING",
    "OCCURRENCE_REPLAY",
    "OCCURRENCE_SKIPPED_ACTIVE",
    "ROUTINE_DELETED",
    "ROUTINE_EXHAUSTED",
    "ROUTINE_PAUSED",
    "STALE_DUE_CANDIDATE",
    "AdmissionResult",
    "DueRoutineCandidate",
    "SchedulerReport",
    "admit_due_candidate",
    "admit_due_routines",
    "due_routine_candidates",
]
