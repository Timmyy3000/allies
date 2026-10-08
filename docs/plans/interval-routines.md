# Interval routines (hourly and arbitrary periods)

Route: fast. Grant: land ("continue with the task and land the task").

## Scope
Recurring routines can only be daily, weekly, or monthly. Users ask for "every hour"
or "every 3 hours" and the Ally cannot save it. Add one recurring frequency,
`interval`, so any fixed period from 15 minutes to 365 days is expressible.

Canonical Nabu sources: `projects/allies/engineering/specs/routines.md` (recurring
work is generic; missed-run recovery runs once for the latest missed occurrence).

## Shape
```json
{"kind":"recurring","frequency":"interval","every_minutes":60,
 "starts_at":"2026-10-08T09:00:00","timezone":"Europe/Berlin"}
```
- `every_minutes`: integer 15..525600.
- `starts_at`: local wall-clock anchor (no offset), resolved once in `timezone`.
- Occurrences are `anchor + k * every_minutes` in elapsed time, so DST does not
  shift or duplicate runs. Daily-and-longer wall-clock cadences stay on the
  existing frequencies.

## Approach and affected surfaces
1. Cloud `routines/services/schedule.py`: validate, serialize, and resolve the next
   occurrence arithmetically. Add `latest_occurrence_at_or_before` so recovery
   is O(1) for short intervals.
2. Cloud `routines/services/scheduler.py`: use the direct calculation for interval
   schedules in `_latest_missed`.
3. Hermes tool description (`allies_routines.py`) and capability skill text.
4. Routines contract doc, its lock (revision 15), and its unchanged fixture.
5. `packages/cloud-client` schema and view model; web and mobile labels.

## Acceptance
- Hourly routine created through the tool validates and its next run lands on the
  anchored grid.
- After a 30-day outage an hourly routine recovers once at the latest missed slot.
- Intervals below 15 minutes or above 365 days, or missing `starts_at`, are rejected.
- Existing daily/weekly/monthly behavior is unchanged.

## Validation
- `uv run --locked pytest routines allies/tests/test_routines_contract.py` (Cloud backend).
- `uv run --locked pytest tests/test_routine_management_tool.py` (Foundry runtime) and Foundry contract test.
- `bun run lint`, cloud-client tests, `bun run build:web`.

## Risks
- Minimum 15 minutes is a recorded default to bound scheduler load (AL-07).
- Contract revision bump: Foundry and Cloud both pin the lock; both tests run.
