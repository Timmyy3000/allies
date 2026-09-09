"""Pure validation and resolution for wall-clock routine schedules."""

from __future__ import annotations

import calendar
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ScheduleError(ValueError):
    """Base error for invalid or unresolvable schedule input."""


class ScheduleValidationError(ScheduleError):
    """The schedule shape or value is not supported."""


class NoFutureOccurrence(ScheduleError):
    """A valid schedule has no occurrence strictly after the boundary."""


class MonthlyShortMonthError(ScheduleError):
    """Monthly day behavior for the target short month is unspecified."""


class ScheduleKind(StrEnum):
    ONCE = "once"
    RECURRING = "recurring"


class RecurringFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


MAX_GAP_SEARCH_SECONDS = 2 * 24 * 60 * 60

_ONCE_KEYS = frozenset({"kind", "local_at", "timezone"})
_RECURRING_KEYS = frozenset(
    {"kind", "frequency", "local_time", "days_of_week", "day_of_month", "timezone"}
)


@dataclass(frozen=True, slots=True)
class ScheduleSpec:
    """Validated, immutable schedule data independent of Django or transport."""

    kind: ScheduleKind
    timezone: str
    local_at: datetime | None = None
    frequency: RecurringFrequency | None = None
    local_time: time | None = None
    days_of_week: tuple[int, ...] = ()
    day_of_month: int | None = None

    def as_dict(self) -> dict[str, object]:
        """Return the canonical internal shape used by Cloud persistence."""

        if self.kind is ScheduleKind.ONCE:
            return {
                "kind": self.kind.value,
                "local_at": self.local_at.isoformat(),
                "timezone": self.timezone,
            }

        result: dict[str, object] = {
            "kind": self.kind.value,
            "frequency": self.frequency.value,
            "local_time": self.local_time.isoformat(),
            "timezone": self.timezone,
        }
        if self.frequency is RecurringFrequency.WEEKLY:
            result["days_of_week"] = list(self.days_of_week)
        elif self.frequency is RecurringFrequency.MONTHLY:
            result["day_of_month"] = self.day_of_month
        return result


def _parse_local_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ScheduleValidationError(
                "local_at must be an ISO local datetime"
            ) from exc
    else:
        raise ScheduleValidationError("local_at must be an ISO local datetime")
    if parsed.tzinfo is not None:
        raise ScheduleValidationError("local_at must not include an offset")
    if parsed.microsecond:
        raise ScheduleValidationError("local_at must have second precision")
    return parsed


def _parse_local_time(value: object) -> time:
    if isinstance(value, time):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = time.fromisoformat(value)
        except ValueError as exc:
            raise ScheduleValidationError(
                "local_time must be an ISO local time"
            ) from exc
    else:
        raise ScheduleValidationError("local_time must be an ISO local time")
    if parsed.tzinfo is not None:
        raise ScheduleValidationError("local_time must not include an offset")
    if parsed.microsecond:
        raise ScheduleValidationError("local_time must have second precision")
    return parsed.replace(tzinfo=None)


def _parse_timezone(value: object) -> tuple[str, ZoneInfo]:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ScheduleValidationError("timezone must be an IANA timezone")
    try:
        return value, ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScheduleValidationError("timezone must be an IANA timezone") from exc


def _validate_keys(schedule: Mapping[str, object], allowed: frozenset[str]) -> None:
    unknown = set(schedule) - allowed
    if unknown:
        names = ", ".join(sorted(str(item) for item in unknown))
        raise ScheduleValidationError(f"unsupported schedule fields: {names}")


def _parse_days(value: object) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ScheduleValidationError("weekly days_of_week must be nonempty")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise ScheduleValidationError("weekly days_of_week must contain ISO weekdays")
    days = tuple(value)
    if any(day < 1 or day > 7 for day in days) or tuple(sorted(set(days))) != days:
        raise ScheduleValidationError(
            "weekly days_of_week must be ascending, unique ISO weekdays"
        )
    return days


def validate_schedule(value: Mapping[str, object]) -> ScheduleSpec:
    """Validate a closed schedule shape and return immutable normalized values."""

    if not isinstance(value, Mapping):
        raise ScheduleValidationError("schedule must be an object")
    raw_kind = value.get("kind")
    if not isinstance(raw_kind, str):
        raise ScheduleValidationError("schedule kind is required")
    timezone_name, _ = _parse_timezone(value.get("timezone"))

    if raw_kind == ScheduleKind.ONCE.value:
        _validate_keys(value, _ONCE_KEYS)
        if "local_at" not in value:
            raise ScheduleValidationError("once schedule requires local_at")
        return ScheduleSpec(
            kind=ScheduleKind.ONCE,
            timezone=timezone_name,
            local_at=_parse_local_datetime(value["local_at"]),
        )

    if raw_kind != ScheduleKind.RECURRING.value:
        raise ScheduleValidationError("schedule kind must be once or recurring")
    _validate_keys(value, _RECURRING_KEYS)
    frequency = value.get("frequency")

    if not isinstance(frequency, str):
        raise ScheduleValidationError("recurring schedule frequency is required")
    try:
        parsed_frequency = RecurringFrequency(frequency)
    except ValueError as exc:
        raise ScheduleValidationError("unsupported recurring frequency") from exc
    if "local_time" not in value:
        raise ScheduleValidationError("recurring schedule requires local_time")
    local_time = _parse_local_time(value["local_time"])

    if parsed_frequency is RecurringFrequency.DAILY:
        if "days_of_week" in value or "day_of_month" in value:
            raise ScheduleValidationError("daily schedule has no calendar selector")
        return ScheduleSpec(
            kind=ScheduleKind.RECURRING,
            timezone=timezone_name,
            frequency=parsed_frequency,
            local_time=local_time,
        )

    if parsed_frequency is RecurringFrequency.WEEKLY:
        if "day_of_month" in value:
            raise ScheduleValidationError("weekly schedule has no day_of_month")
        return ScheduleSpec(
            kind=ScheduleKind.RECURRING,
            timezone=timezone_name,
            frequency=parsed_frequency,
            local_time=local_time,
            days_of_week=_parse_days(value.get("days_of_week")),
        )

    if "days_of_week" in value:
        raise ScheduleValidationError("monthly schedule has no days_of_week")
    day_of_month = value.get("day_of_month")
    if (
        isinstance(day_of_month, bool)
        or not isinstance(day_of_month, int)
        or not 1 <= day_of_month <= 31
    ):
        raise ScheduleValidationError("monthly day_of_month must be between 1 and 31")
    return ScheduleSpec(
        kind=ScheduleKind.RECURRING,
        timezone=timezone_name,
        frequency=parsed_frequency,
        local_time=local_time,
        day_of_month=day_of_month,
    )


def _valid_local_candidates(
    local_value: datetime, timezone: ZoneInfo
) -> tuple[datetime, ...]:
    candidates: list[datetime] = []
    for fold in (0, 1):
        aware = local_value.replace(tzinfo=timezone, fold=fold)
        round_trip = aware.astimezone(UTC).astimezone(timezone).replace(tzinfo=None)
        if round_trip == local_value:
            instant = aware.astimezone(UTC).replace(microsecond=0)
            if instant not in candidates:
                candidates.append(instant)
    return tuple(sorted(candidates))


def resolve_local_datetime(local_value: datetime, timezone_name: str) -> datetime:
    """Resolve a local wall time to second-precision UTC.

    Gaps move to the first valid local second after the gap. Folds choose the
    earliest instant, which is deterministic ``fold=0`` behavior.
    """

    if not isinstance(local_value, datetime) or local_value.tzinfo is not None:
        raise ScheduleValidationError("local datetime must be naive")
    if local_value.microsecond:
        raise ScheduleValidationError("local datetime must have second precision")
    _, timezone = _parse_timezone(timezone_name)
    candidates = _valid_local_candidates(local_value, timezone)
    if candidates:
        return candidates[0]
    for seconds in range(1, MAX_GAP_SEARCH_SECONDS + 1):
        candidate = local_value + timedelta(seconds=seconds)
        candidates = _valid_local_candidates(candidate, timezone)
        if candidates:
            return candidates[0]
    raise ScheduleError("timezone gap has no resolvable local instant")


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ScheduleValidationError("future boundary must be timezone-aware UTC")
    return value.astimezone(UTC)


def _candidate(spec: ScheduleSpec, local_date: date) -> datetime:
    assert spec.local_time is not None
    return resolve_local_datetime(
        datetime.combine(local_date, spec.local_time), spec.timezone
    )


def _next_daily_or_weekly(spec: ScheduleSpec, after: datetime) -> datetime:
    assert spec.frequency in {
        RecurringFrequency.DAILY,
        RecurringFrequency.WEEKLY,
    }
    timezone = ZoneInfo(spec.timezone)
    local_date = after.astimezone(timezone).date()
    for offset in range(8):
        candidate_date = local_date + timedelta(days=offset)
        if spec.frequency is RecurringFrequency.WEEKLY and (
            candidate_date.isoweekday() not in spec.days_of_week
        ):
            continue
        candidate = _candidate(spec, candidate_date)
        if candidate > after:
            return candidate
    raise ScheduleError("recurring schedule did not resolve within one week")


def _next_monthly(spec: ScheduleSpec, after: datetime) -> datetime:
    assert spec.day_of_month is not None and spec.local_time is not None
    timezone = ZoneInfo(spec.timezone)
    local_date = after.astimezone(timezone).date()
    year, month = local_date.year, local_date.month
    for _ in range(2):
        last_day = calendar.monthrange(year, month)[1]
        if spec.day_of_month > last_day:
            raise MonthlyShortMonthError(
                "monthly day_of_month is unsupported for this short month"
            )
        candidate = _candidate(spec, date(year, month, spec.day_of_month))
        if candidate > after:
            return candidate
        month += 1
        if month == 13:
            month, year = 1, year + 1
    raise ScheduleError("monthly schedule did not resolve")


def resolve_next_occurrence(
    schedule: Mapping[str, object] | ScheduleSpec, *, after: datetime
) -> datetime:
    """Return the next occurrence strictly later than an aware UTC boundary."""

    spec = (
        schedule if isinstance(schedule, ScheduleSpec) else validate_schedule(schedule)
    )
    boundary = _as_utc(after)
    if spec.kind is ScheduleKind.ONCE:
        assert spec.local_at is not None
        candidate = resolve_local_datetime(spec.local_at, spec.timezone)
        if candidate <= boundary:
            raise NoFutureOccurrence("once schedule is not strictly after the boundary")
        return candidate
    if spec.frequency is RecurringFrequency.MONTHLY:
        return _next_monthly(spec, boundary)
    return _next_daily_or_weekly(spec, boundary)


__all__ = [
    "MonthlyShortMonthError",
    "NoFutureOccurrence",
    "RecurringFrequency",
    "ScheduleError",
    "ScheduleKind",
    "ScheduleSpec",
    "ScheduleValidationError",
    "resolve_local_datetime",
    "resolve_next_occurrence",
    "validate_schedule",
]
