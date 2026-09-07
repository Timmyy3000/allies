# Runtime readiness and activity operations

This runbook covers the optional Foundry activity wait and profile-readiness
hint delivery paths. Both paths are acceleration layers. Existing profile
reconciliation, execution claims, readiness receipts, and scheduled recovery
remain authoritative.

## Configuration

The acceleration flags are disabled by default:

- `ALLIES_RUNTIME_ACTIVITY_WAIT_ENABLED`: enables the authenticated PostgreSQL
  activity-wait endpoint for awake runtimes.
- `ALLIES_RUNTIME_ACTIVITY_WAIT_SECONDS`: requested wait bound, from 1 through
  5 seconds, defaulting to 5.
- `ALLIES_RUNTIME_ACTIVITY_WAIT_MAX_WAITERS`: per-process waiter cap, from 1
  through 8, defaulting to 8.
- `ALLIES_RUNTIME_READINESS_HINT_ENABLED`: enables durable Foundry-to-Cloud
  readiness hints.

When readiness hints are enabled, configure the existing Cloud origin and
service token variables as deployment secrets. Keep tokens and private URLs out
of logs, command output, fixtures, and checked-in evidence.

Activity waiting requires PostgreSQL. Non-PostgreSQL development environments
continue to use the existing polling behavior. The waiter is bounded to five
seconds, rejects a second waiter for the same workspace, and returns capacity
or service errors without changing runtime correctness.

For the candidate and proof topology, set the runtime container's
`ALLIES_RUNTIME_ACTIVITY_WAIT_ENABLED` flag as well as the matching Foundry
setting. Use `WEB_THREADS=16` and no more than eight waiters per process. The
proof is capped at eight connected runtime workspaces in total, including
unassigned reserve Machines, leaving at least eight ordinary request threads
available per worker process.

## Rollout

Deploy the Foundry migration and API before enabling either sender. Deploy the
Cloud readiness-hint receiver before enabling Foundry hint delivery. Start the
dedicated publisher with a one-second supervised loop when hint latency is a
release requirement:

```text
python manage.py publish_profile_readiness_hints --watch --interval 1
```

Run one bounded pass during inspection or recovery:

```text
python manage.py publish_profile_readiness_hints
```

Each pass claims at most one hint. A materialization receipt and its durable
hint row commit together; network publication begins after that transaction.
The existing Cloud periodic due-work scan confirms product readiness after a
hint is lost or exhausted. Resume the dedicated publisher to retry durable hint
rows after a sender or receiver outage.

## Operational checks

Before enabling activity waiting, verify that the database is PostgreSQL, the
runtime API accepts the bearer credential, and ordinary health and control
requests remain responsive. The endpoint is:

```text
POST /api/v1/runtime/activity-waits
```

It accepts `after_revision` and `wait_seconds` and returns a revision with
`reason` set to `changed` or `timeout`. A `429` indicates the bounded waiter
capacity is full; a `503` indicates that waiting is unavailable. The runtime
keeps its existing jittered polling/backoff behavior for both cases.

For hint delivery, inspect only aggregate claim, delivered, deferred, and
exhausted counts and the safe persisted error code. A `delivering` row with an
expired lease is reclaimed by the next pass. An expired final lease becomes
`exhausted` so it cannot be claimed indefinitely. The hint payload contains
routing and receipt identity only; it does not contain names, prompts, or seed
content.

## Rollback

Disable `ALLIES_RUNTIME_ACTIVITY_WAIT_ENABLED` if listener capacity or database
latency affects ordinary requests. Disable
`ALLIES_RUNTIME_READINESS_HINT_ENABLED` if Cloud delivery is unavailable.
Existing polling and scheduled reconciliation continue, and durable hint rows
can be inspected or retried after the receiver is healthy. Leave additive
columns and rows in place until all old and new binaries have been retired.
