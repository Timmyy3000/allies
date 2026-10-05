from datetime import UTC, datetime

import pytest

from routines.services.schedule import (
    MonthlyShortMonthError,
    NoFutureOccurrence,
    ScheduleValidationError,
    resolve_local_datetime,
    resolve_next_occurrence,
    validate_schedule,
)


def test_dst_gap_moves_to_first_valid_instant_and_fold_uses_earliest():
    assert resolve_local_datetime(
        datetime.fromisoformat("2026-03-29T02:30:00"), "Europe/Berlin"
    ) == datetime(2026, 3, 29, 1, 0, tzinfo=UTC)
    assert resolve_local_datetime(
        datetime.fromisoformat("2026-10-25T02:30:00"), "Europe/Berlin"
    ) == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)


def test_daily_resolution_is_strictly_after_the_resume_boundary():
    schedule = {
        "kind": "recurring",
        "frequency": "daily",
        "local_time": "09:00:00",
        "timezone": "Europe/Berlin",
    }

    assert resolve_next_occurrence(
        schedule,
        after=datetime(2026, 9, 10, 7, 0, tzinfo=UTC),
    ) == datetime(2026, 9, 11, 7, 0, tzinfo=UTC)


def test_weekly_and_once_inputs_resolve_to_second_precision_utc():
    weekly = validate_schedule(
        {
            "kind": "recurring",
            "frequency": "weekly",
            "local_time": "09:00:00",
            "days_of_week": [1, 3, 5],
            "timezone": "Europe/Berlin",
        }
    )
    assert resolve_next_occurrence(
        weekly,
        after=datetime(2026, 9, 10, 7, 1, tzinfo=UTC),
    ) == datetime(2026, 9, 11, 7, 0, tzinfo=UTC)

    once = {
        "kind": "once",
        "local_at": "2026-09-10T09:00:00",
        "timezone": "Europe/Berlin",
    }
    assert resolve_next_occurrence(
        once,
        after=datetime(2026, 9, 10, 6, 59, 59, tzinfo=UTC),
    ) == datetime(2026, 9, 10, 7, tzinfo=UTC)


@pytest.mark.parametrize(
    "schedule",
    [
        {
            "kind": "recurring",
            "frequency": "weekly",
            "local_time": "09:00:00",
            "days_of_week": [3, 1],
            "timezone": "Europe/Berlin",
        },
        {
            "kind": "recurring",
            "frequency": "daily",
            "local_time": "09:00.500",
            "timezone": "Europe/Berlin",
        },
        {
            "kind": "once",
            "local_at": "2026-09-10T09:00:00",
            "timezone": "Not/AnIanaZone",
        },
        {
            "kind": "daily",
            "local_time": "09:00:00",
            "timezone": "Europe/Berlin",
        },
    ],
)
def test_schedule_validation_rejects_unsupported_values(schedule):
    with pytest.raises(ScheduleValidationError):
        validate_schedule(schedule)


def test_monthly_short_month_behavior_is_rejected_instead_of_skipped_or_clamped():
    schedule = {
        "kind": "recurring",
        "frequency": "monthly",
        "local_time": "09:00:00",
        "day_of_month": 31,
        "timezone": "Europe/Berlin",
    }

    with pytest.raises(MonthlyShortMonthError, match="short month"):
        resolve_next_occurrence(
            schedule,
            after=datetime(2026, 4, 1, tzinfo=UTC),
        )


def test_monthly_schedule_resolves_a_supported_calendar_day():
    assert resolve_next_occurrence(
        {
            "kind": "recurring",
            "frequency": "monthly",
            "local_time": "09:00:00",
            "day_of_month": 15,
            "timezone": "Europe/Berlin",
        },
        after=datetime(2026, 9, 10, tzinfo=UTC),
    ) == datetime(2026, 9, 15, 7, tzinfo=UTC)


def test_once_schedule_rejects_a_past_or_equal_boundary():
    with pytest.raises(NoFutureOccurrence):
        resolve_next_occurrence(
            {
                "kind": "once",
                "local_at": "2026-09-10T09:00:00",
                "timezone": "Europe/Berlin",
            },
            after=datetime(2026, 9, 10, 7, tzinfo=UTC),
        )
