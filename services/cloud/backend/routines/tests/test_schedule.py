from datetime import UTC, datetime

import pytest

from routines.services.schedule import (
    MonthlyShortMonthError,
    NoFutureOccurrence,
    ScheduleValidationError,
    latest_interval_occurrence,
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


def _every(minutes, starts_at="2026-10-24T22:00:00"):
    return {
        "kind": "recurring",
        "frequency": "interval",
        "every_minutes": minutes,
        "starts_at": starts_at,
        "timezone": "Europe/Berlin",
    }


def test_hourly_interval_stays_on_elapsed_grid_across_dst_fold():
    schedule = _every(60)

    assert resolve_next_occurrence(
        schedule, after=datetime(2026, 10, 1, tzinfo=UTC)
    ) == datetime(2026, 10, 24, 20, 0, tzinfo=UTC)
    assert resolve_next_occurrence(
        schedule, after=datetime(2026, 10, 25, 0, 0, tzinfo=UTC)
    ) == datetime(2026, 10, 25, 1, 0, tzinfo=UTC)
    assert resolve_next_occurrence(
        schedule, after=datetime(2026, 10, 25, 0, 59, 59, tzinfo=UTC)
    ) == datetime(2026, 10, 25, 1, 0, tzinfo=UTC)


def test_arbitrary_interval_round_trips_canonical_shape():
    schedule = _every(3 * 24 * 60)

    assert validate_schedule(schedule).as_dict() == schedule
    assert resolve_next_occurrence(
        schedule, after=datetime(2026, 10, 24, 20, tzinfo=UTC)
    ) == datetime(2026, 10, 27, 20, tzinfo=UTC)


@pytest.mark.parametrize(
    "schedule",
    [
        _every(14),
        _every(525_601),
        _every(True),
        _every("60"),
        {k: v for k, v in _every(60).items() if k != "starts_at"},
        {**_every(60), "local_time": "09:00:00"},
        {**_every(60), "starts_at": "2026-10-24T22:00:00+02:00"},
    ],
)
def test_interval_rejects_unsupported_shapes(schedule):
    with pytest.raises(ScheduleValidationError):
        validate_schedule(schedule)


def test_interval_boundaries_are_strictly_after_and_at_or_before():
    spec = validate_schedule(_every(60))
    anchor = datetime(2026, 10, 24, 20, tzinfo=UTC)

    assert resolve_next_occurrence(spec, after=anchor) == datetime(
        2026, 10, 24, 21, tzinfo=UTC
    )
    assert latest_interval_occurrence(spec, at_or_before=anchor) == anchor
    assert (
        latest_interval_occurrence(
            spec, at_or_before=datetime(2026, 10, 24, 19, 59, 59, tzinfo=UTC)
        )
        is None
    )
