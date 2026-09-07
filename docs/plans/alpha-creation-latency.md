# Alpha creation latency plan

## Outcome and scope

Reduce two measured backend waits in the Ally-creation path while preserving truthful readiness, tenant/runtime isolation, idempotency, leases, fencing, and failure backoff:

- Cloud currently receives a truthful `pending` provisioning receipt, exits the worker task, and can wait for the next 15-second beat even when runtime materialization finishes a few seconds later.
- An awake runtime currently increases successful empty-claim polling from 1 second through 10 seconds, so a newly persisted first execution can wait behind an old idle delay.
- Cloud terminal `completed_at` and retry scheduling currently reuse the timestamp captured before Foundry and onboarding-handoff I/O.

This fast-route plan covers bounded scheduling changes, meaningful timestamps, focused tests, and local proof. It does not add a broker, machine pool, long poll, public API, migration, auth exception, UI change, provider/model tuning, or permanently aggressive polling. First workspace provisioning, an asleep workspace, or a slow/failing runtime must remain pending/retryable until Foundry reports actual materialization.

Source baseline: the approved work brief, Nabu AT-010 and CLD-003, Cloud `dev` at `5d8a739`, and Foundry `dev` at `e8285f9`. The 2026-09-07 work brief records explicit implementation and shipping approval. Nabu AT-010 has been reconciled with that authorization.

## Approach and contracts

Use two short success-path windows and retain every durable fallback.

### Cloud materialization confirmation

Keep `ProvisioningOperation` and the existing idempotent `POST /api/v1/internal/profile-provisioning` replay as the authority. When an attempt ends specifically with a valid matching `pending` receipt and `materialization_pending`, return the existing internal outcome plus its eligible integer delay; do not introduce a generalized hint object or setting. Allow eligible delays only after attempts 1, 2, and 3, using the existing 2-second, 4-second, and 8-second provisioning backoff. This gives a cumulative 14-second bounded confirmation window, covering the runtime's existing worst-case 10-second profile-reconciliation interval. Attempt 4 and later rely on the persisted `next_attempt_at` plus the existing 15-second beat. Do not sleep inside the single-concurrency Cloud worker.

The dispatch report derives a sorted tuple of distinct eligible delays from those internal outcomes. The Celery wrapper schedules each integer countdown, up to the three possible values `(2, 4, 8)`. Scheduling only the earliest delay can strand a row already due at a later backoff when the earlier follow-up runs, so mixed-attempt batches must retain every distinct countdown. Each operation contributes a delay only for its first three materialization-pending attempts; later tasks cannot extend that operation's accelerator window.

The scheduled task is only an accelerator. A publish failure, duplicate scheduled task, worker restart, or overlap with beat leaves the retryable database row intact; due-time checks, the existing lease, and `attempt_count` fencing decide which task may call Foundry. Gateway, activation, malformed receipt, rejection, and other failures do not request fast follow-ups and keep their existing retry/repair behavior.

Use a fresh `timezone.now()` after the last relevant external or handoff operation when calculating `next_attempt_at` or writing a terminal `completed_at`. `last_attempt_at` remains the claim-start timestamp. For an active receipt, settle the terminal operation after the onboarding reply handoff attempt so `completed_at` does not precede execution/outbox persistence; handoff failure still leaves the Foundry binding bound and records the current repair-required outcome.

Likely Cloud surfaces:

- `backend/allies/services/provisioning.py`: return the internal outcome with an optional eligible delay, derive sorted distinct delays for the batch, preserve claim fencing, and use outcome-time timestamps.
- `backend/allies/tasks.py`: schedule up to three distinct bounded follow-ups from the aggregate report while returning the existing public count dictionary.
- `backend/allies/tests/test_provisioning.py` and a focused task test beside existing Ally tests: cover hint limits, truthful state, fresh timestamps, and scheduler fallback.

No HTTP schema, database schema, or user-visible response changes are required.

### Runtime claim responsiveness

Keep the existing 1/2/4/8/10-second jittered backoff for rate limits, service unavailability, ambiguous claim responses, readiness failures, and ordinary long-term idle operation. Add one integer worker field for remaining fast empty polls. When `ProfileReconciler.reconcile()` successfully reports one or more newly materialized profiles, set it to eight. During that window only, a successful empty claim waits the existing 1-second minimum and decrements the counter; after eight empty successes, the worker resumes the existing exponential idle schedule. A claim, shutdown, or zero counter ends the window. Retryable errors continue through the existing failure backoff and must not be converted into 1-second success polling. Do not add a runtime setting or generalized polling state object.

This targets creation because materialization is the local runtime event immediately preceding Cloud's first-message dispatch. It avoids a global 1-second loop for already-idle machines and introduces no cross-repository callback or notification contract.

Likely Foundry surfaces:

- `runtime/allies_runtime/foundry.py`: arm and consume the bounded successful-empty window without changing claim identity, slot accounting, leases, or error backoff.
- `runtime/tests/test_foundry.py` and/or `runtime/tests/test_profile_reconciliation.py`: prove the eight 1-second empty waits after materialization, return to exponential idle, and unchanged retryable-error delays.
- `runtime/README.md`: replace the unconditional idle-backoff description with the bounded post-materialization rule. Keep the public text generic and free of customer identifiers, private URLs, or deployment details.

No runtime/Foundry API, database model, provider adapter, or deployment setting changes are required.

## Delivery lanes

1. **Cloud PR into `dev`** — implement the three bounded follow-up hints and outcome-time timestamps with focused provisioning/task tests. This lane is independently reviewable and safe without the Foundry change because all retries still use the existing contract and beat fallback.
2. **Foundry PR into `dev`** — implement the materialization-triggered eight-poll window, preserve failure backoff, update the runtime polling documentation, and add deterministic async tests. This lane is independently safe because it changes only timing after an already successful local reconciliation.
3. **Integrated proof after both branches pass their own checks** — run the existing local Cloud/Foundry/Fly-simulator topology with fake authentication, exercise creation scenarios, and record sanitized phase deltas. Merge order is flexible; deploy both before evaluating the combined latency result.

Each repository keeps its separate correctness and simplicity review. The implementation should remain a focused change; if either PR grows beyond the bounded services/tests/docs above, stop and reassess rather than introducing a generalized scheduler or polling framework.

## Acceptance and regression cases

1. A matching active receipt still binds exactly one Ally, promotes exactly one retained onboarding reply, and creates at most one dispatch/execution across replayed create requests and overlapping scheduled/beat tasks.
2. A valid pending receipt remains pending/retryable. Attempts 1, 2, and 3 can request follow-ups after 2, 4, and 8 seconds; attempt 4 and later cannot self-schedule and remain recoverable by beat. A mixed batch schedules every distinct hinted countdown, capped at those three values. Non-materialization failures never enter the fast path.
3. Completion and next-attempt timestamps are captured after the final mocked Foundry/activation/handoff operation; terminal success cannot predate first-execution persistence.
4. A newly materialized runtime profile arms exactly eight successful empty claims at the 1-second minimum, then returns to the current exponential idle sequence capped at 10 seconds. A claimed execution ends the fast window.
5. Rate-limited, unavailable, not-ready, response-loss, fencing, and lease paths retain their current bounded retry/stop behavior. The change does not weaken authorization, workspace/profile isolation, generation fencing, or ambiguous-claim reservation.
6. First workspace provisioning and an asleep workspace remain truthful: if materialization does not complete inside the three Cloud accelerators, the operation stays retryable and later settles only from a matching active receipt.
7. A deterministic worst-phase test places runtime materialization at the 10-second reconciliation ceiling, after the 2- and 4-second Cloud checks. The 8-second follow-up confirms at cumulative 14 seconds, and the materialization-triggered runtime window still performs a 1-second claim poll after dispatch. This is a bounded scheduling proof, not an absolute latency SLA.
8. Timing evidence contains phase names, UTC timestamps/durations, outcomes, counts, and simulator/real-runtime classification only. Do not include customer content, provider credentials, private URLs, raw tokens, or public Foundry fixtures derived from production identifiers.

## Validation and local proof

Run focused checks first, then repository gates:

```powershell
# Cloud, from the Cloud worktree
Set-Location backend
uv run pytest allies/tests/test_provisioning.py allies/tests/test_concurrency.py allies/tests/test_tasks.py
uv run ruff check allies
uv run ruff format --check allies
Set-Location ..
make check
make lint
make test

# Foundry, from the Foundry worktree
Set-Location runtime
uv run --locked pytest tests/test_foundry.py tests/test_profile_reconciliation.py
uv run --locked ruff check allies_runtime tests/test_foundry.py tests/test_profile_reconciliation.py
uv run --locked ruff format --check allies_runtime tests/test_foundry.py tests/test_profile_reconciliation.py
Set-Location ..
make check
make validate
make runtime-test
```

If the Cloud task tests fit the existing `test_provisioning.py` rather than a new `test_tasks.py`, use that actual path in the command. Do not add a file solely to match this plan.

Split proof by what each harness actually executes:

1. **Real runtime-loop scheduling:** deterministic async tests must execute `FoundryWorker._run_loop` with controlled clock/sleep, a real `ReconciliationReport(materialized=...)`, and fake transport responses. Prove the 10-second materialization / 14-second Cloud confirmation / next 1-second claim worst phase without real sleeping. Also prove eight empty successes exhaust the fast window and retryable errors retain exponential backoff.
2. **Profile materialization contract:** run the existing Foundry backend/profile-reconciliation tests against the real `ProfileReconciler`, profile store test doubles, materialization receipt endpoint, lifecycle generation fencing, and idempotent receipt replay. Do not extend the isolated simulator for this work.
3. **Wake/sleep orchestration regression:** use the existing Foundry-owned FND-009 harness and deterministic fake provider unchanged:

```powershell
uv run --project backend python scripts/prove_fnd009.py `
  --cloud-root ../allies-cloud `
  --interface-root ../allies-interface `
  --no-cleanup
```

Use the harness-resolved worktree paths when running from this task workspace. Its fixed simulator loop does not execute the production `FoundryWorker` or real Hermes profile materialization. It proves the existing browser-visible wake/sleep flow and orchestration invariants only; label its elapsed values `simulator` and do not treat its loop timing as runtime-claim or real Fly/Hermes latency. Separately exercise and record:

- first profile with workspace provisioning/start;
- an additional profile while the workspace runtime is awake;
- an additional profile after the workspace sleeps;
- one pending materialization that outlives all three fast follow-ups;
- one retryable Foundry/claim failure and overlapping dispatch attempt.

For each scenario, compute deltas from authoritative persisted timestamps and existing privacy-safe task/runtime events: create to materialization receipt, materialization to Cloud terminal operation, first execution persistence to claim, first text, and completion. The deterministic worst-phase test must show the third Cloud accelerator covering materialization at the 10-second reconciliation ceiling and claim pickup on the next 1-second runtime cadence. The first/asleep scenarios have no local absolute SLA; they pass when state remains truthful and recovery is bounded. Repeat real staging measurements only after reviewed PRs reach `dev`, and compare p50/p95 by scenario before closing AT-010.

## Risks, rollback, and open decisions

- **Duplicate Celery accelerators:** a mixed batch can publish up to three distinct countdowns and overlapping tasks may run, but due-time checks, row leases, and attempt fences prevent duplicate Foundry effects. If broker pressure appears, disable the fast-follow-up branch; beat remains the rollback path.
- **Runtime request load:** the added cost is capped at eight successful empty claims per newly materialized profile event. Revert the fast-window branch to restore the documented exponential policy without state migration.
- **Clock accuracy:** use monotonic time only for elapsed/window control and timezone-aware wall time for persisted audit fields. Tests must inject or patch clocks rather than sleep in real time.
- **Local proof limitation:** simulator results validate relative scheduling and invariants, not real provider latency. Staging evidence remains required before declaring the user-reported multi-minute issue resolved.
- **Open measurement target:** no accepted first-machine latency SLA exists in Nabu. This work removes the demonstrated avoidable waits; the parent records staging distributions and proposes an SLA separately rather than embedding one in these PRs.

## Review findings and dispositions

- **ADV-001 — accepted:** two Cloud accelerators at cumulative 6 seconds did not cover the runtime's 10-second reconciliation ceiling. Add the third 8-second hint for cumulative confirmation at 14 seconds and require the worst-phase deterministic test.
- **ADV-002 — accepted:** scheduling only the earliest aggregate hint could leave later-due rows waiting for beat. Schedule every distinct batch hint, capped at the three fixed countdowns, while per-operation attempt fencing bounds self-scheduling.
- **ADV-003 — accepted:** the existing FND-009 simulator does not materialize profiles or run the production worker loop. Separate production-loop deterministic tests, profile materialization/receipt integration, and browser wake/sleep regression evidence; never label fixed simulator timing as real runtime latency.
- **SIM-001 — accepted:** avoid a reusable retry-hint abstraction or new settings. Return the existing internal outcome with an optional eligible integer delay and keep the fixed attempt/delay policy in the provisioning service.
- **SIM-002 — accepted:** derive one sorted set of distinct batch delays and have the Celery wrapper schedule those integers directly; do not add a scheduler layer.
- **SIM-003 — accepted:** represent runtime responsiveness with one remaining-polls integer set to eight by a materialization report and decremented only by successful empty claims; do not add a state machine or configuration surface.
