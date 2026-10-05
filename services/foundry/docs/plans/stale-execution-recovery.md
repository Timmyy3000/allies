# Stale execution recovery plan

## Feature overview

- Problem: an expired `active` or `stopping` lease remains covered by the profile uniqueness constraint, so `claim_next_execution` skips later queued work indefinitely when the runtime's immediate failure or stopped request is lost.
- Target users: people waiting for a later turn with the same Ally, plus operators responsible for durable recovery after a runtime or Hermes disconnect.
- Source docs and evidence: `.agent/stale-execution-recovery/brief.md`; `ENGINEERING_STYLE.md`; `docs/architecture/foundry-continuity.md`; Nabu's accepted Foundry continuity, conversation/streaming, decision-log, and Hermes/Fly notes; the current claim, lease, event, worker, and delivery code; and the staging trace with one dispatch, 86 partial deltas over about 8.4 seconds, no terminal event, and an expired lease.
- Success outcome: the next claim pass retires expired lease state transactionally. Only pre-dispatch work is requeued. Dispatched or otherwise ambiguous work ends unknown-safe with one durable `execution.failed` event, and later same-profile work can proceed.

## Scope

### In scope

- A bounded, PostgreSQL-backed reconciliation pass at the start of the existing runtime claim transaction.
- Exact replay classification using the existing `execution.dispatched` event or session-receipt evidence as the safety boundary.
- Release or fencing of every expired unresolved `active` or `stopping` lease that can satisfy the blocker query, including leases from retired generations, while preserving profile serialization and cleanup safeguards.
- The accepted idle claim delay: exponential growth from 1 to 10 seconds with bounded jitter, reset after a claim or recovered claim transport.
- Focused concurrency, failure, ordering, and backoff tests, plus architecture/runtime documentation updates.

### Out of scope

- Redis, a queue service, a new scheduler or reaper process, a dependency, or a public/internal API version change.
- Replacing or disabling SSE, changing Cloud or Interface behavior, or implementing FND-009 idle stop/wake.
- `message.delta` coalescing in this PR. The adapter currently forwards each validated delta in order, caps text at 16 KiB, reserves 512 nonterminal projection positions, and uses a bounded delivery batch. The observed 86 deltas did not exhaust those limits, and the incident points to missing lease recovery rather than event pressure. Timed coalescing would add an ordering-sensitive async buffer and needs measured delivery or database pressure before it earns that complexity.

### Dependencies and assumptions

- Foundry remains the durable owner of executions, attempts, leases, ordered events, and delivery outbox rows; PostgreSQL row locks and constraints remain the production concurrency boundary.
- `execution.dispatched` is the replay boundary. A session mutation without a dispatch event is still ambiguous and must not replay.
- An unknown Hermes outcome is represented by terminal `AttemptStatus.UNKNOWN`, `ExecutionStatus.FAILED`, and a safe `execution.failed` event. `AttemptStatus.FAILED` remains reserved for a positively reported runtime failure.
- A profile in `cleanup_pending` and an execution from a retired generation are never made claimable by reconciliation, even when no dispatch checkpoint exists.
- The latest work brief intentionally changes the older documentation rule that required a stopped acknowledgement or confirmed Machine retirement before reclaim. Implementation must update that documentation and the canonical Nabu notes after the behavior is accepted.

## Contract and state changes

No HTTP request, response, or event schema changes. The existing `POST /api/v1/runtime/claims` call gains an internal pre-claim reconciliation side effect. A one-step constraint migration reserves sequence `100001` for a server-owned terminal recovery event while runtime-authored events remain capped at `100000`.

| Expired unresolved lease evidence | Attempt | Execution | Lease | Event | Replay |
| --- | --- | --- | --- | --- | --- |
| No `execution.dispatched`, no session request/receipt, current generation, and profile not `cleanup_pending` | `unknown` | `queued` | `released` | none | A new attempt may be claimed |
| Dispatch event or session request/receipt exists | `unknown` | `failed` | `released` | one next-sequence `execution.failed` with safe code `lease_expired` and `retryable: false` | Never |
| Profile is `cleanup_pending` | existing cleanup-safe terminal or fenced state | never changed to `queued` | released or fenced through the existing cleanup path | only the event already required by that path | Never |
| Lease belongs to a retired generation | `unknown` | `failed` unless already terminal | `fenced` | one idempotent safe failure event when a terminal projection is required | Never |
| Lease already released/fenced or attempt already terminal | unchanged | unchanged | unchanged | none | Existing terminal/idempotent behavior |

The reconciler must:

- run after locking and validating the Workspace, before candidate selection, so a requeued older execution participates in the same ordered selection;
- process at most `MAX_AVAILABLE_SLOTS` oldest expired unresolved leases per claim call;
- use the Workspace row as the authoritative per-workspace serialization point because all competing runtime mutation paths lock it first; once held, follow the existing Workspace to Attempt to Profile to Lease order where those rows exist, without refactoring unrelated writers, and recheck expiry, generation, cleanup, and terminal state under lock;
- call a narrow server-owned synthetic failure-event append seam that accepts only the already locked stale attempt/lease and the fixed lease-expiry reason, requires no runtime token, validates the existing safe `execution.failed` payload, reuses the attempt's durable stream identity, derives a stable event identity from the attempt and failure reason, and allocates the next attempt-local sequence under the same lock, including when the prior sequence is high;
- write the synthetic event, its outbox row, attempt/execution transition, and lease release in the same outer transaction; any validation, sequence, event, or outbox failure rolls everything back, and a retry observes the stable identity or terminal state and becomes a no-op;
- make repeated and concurrent claim calls no-ops after the first committed reconciliation, preventing duplicate terminal events or leases.

## Simplest viable approach

Use the existing claim endpoint as the durable wake-up path. The runtime already polls it while alive or after restart, so no second process is needed. If no runtime is running, durable stale state remains safe in PostgreSQL and reconciliation waits for a runtime restart and its next claim. Add one transaction-local reconciler and one narrow synthetic-event helper in the existing backend runtime service layer; reuse current models, locks, payload validator, and outbox behavior. Keep the runtime's immediate `fail` request unchanged as the low-latency path; reconciliation covers disconnect races, process loss, and lost failure responses.

Keep polling backoff inside `FoundryWorker._run_loop`. Use standard-library randomness, fixed 1-second floor and 10-second ceiling, and injected or patched timing in tests. Empty claims grow the delay exponentially; a claimed execution or the first successful response after a retryable transport failure resets it. Production entrypoint code must stop forcing the current 250 ms fixed delay.

## Phases

### Phase 1: reconcile stale execution truth before claims

- Goal: clear expired blockers without replaying ambiguous Hermes work.
- Work items: add the bounded claim-time reconciler under the Workspace serialization lock; follow the existing Attempt to Profile to Lease order; classify dispatch/session, generation, and cleanup evidence; atomically requeue only eligible current-generation work or use the server-owned append seam for one safe failure event; release or fence the lease; then select from refreshed durable state.
- Impacted files: `backend/runtime/services/claims.py`; focused additions in `backend/runtime/tests/test_fnd005_backend.py`, `backend/runtime/tests/test_fnd007_execution.py`, and `backend/runtime/tests/test_services.py`.
- Exit criteria: eligible pre-dispatch expiry produces a new claimable attempt; dispatch plus partial delta plus a lost failure request produces one unknown-safe terminal result; cleanup-pending and retired-generation work never requeues; an empty claim with no successor still reconciles stale state; two concurrent claimers cannot duplicate reconciliation, events, outbox rows, or leases and complete without a lock-order regression.

### Phase 2: replace fixed idle polling with accepted backoff

- Goal: reduce idle claim traffic without changing active-turn responsiveness or transport semantics.
- Work items: track the bounded 1, 2, 4, 8, 10 second idle progression with bounded jitter; reset it on a successful claim and transport recovery; retain immediate slot refill while work completes; remove the production `idle_delay=0.25` override.
- Impacted files: `runtime/allies_runtime/foundry.py`, `runtime/allies_runtime/__main__.py`, `runtime/tests/test_foundry.py`, and `runtime/tests/test_composition.py`.
- Exit criteria: deterministic tests prove the floor, ceiling, growth, reset, retry, stop, and free-slot behavior without wall-clock sleeps; a restarted continuously polling runtime triggers reconciliation within the configured 10-second maximum idle-backoff bound.

### Phase 3: preserve contracts and document the new recovery rule

- Goal: prove that the small recovery change does not weaken existing continuity behavior.
- Work items: run focused and complete validation; update `docs/architecture/foundry-continuity.md` and `runtime/README.md`; after implementation is accepted, reconcile the changed expiry rule into the canonical Nabu continuity and conversation/streaming notes with revision-aware updates.
- Exit criteria: renewal, stopped acknowledgement, generation fencing, event order/delivery, immediate runtime failure, session compare-and-set, and coverage checks pass; docs no longer claim that every expired lease must wait for stopped acknowledgement or Machine retirement.

## Acceptance criteria

1. Each claim call reconciles a bounded set of expired unresolved `active` or `stopping` leases that can block selection, across current and retired generations, before candidate selection.
2. An eligible current-generation pre-dispatch expiry releases its lease, leaves its old attempt terminal and unknown, requeues the execution, and permits one new attempt; `cleanup_pending` and retired-generation work remains non-claimable.
3. A dispatch or session checkpoint expiry atomically marks the attempt unknown and execution failed, releases the lease, appends exactly one ordered `execution.failed` event, and never replays the turn.
4. Dispatch plus partial deltas plus omission of the runtime failure request is recovered on a later claim; the next same-profile execution becomes claimable.
5. Concurrent claimers serialize first on Workspace and then use the existing Attempt to Profile to Lease order, producing one reconciliation outcome, one synthetic event/outbox pair when required, and at most one replacement lease. Late writes from the expired token remain rejected, and focused race coverage detects lock-order or deadlock regressions using the existing transaction-test infrastructure.
6. Immediate runtime failure reporting, claim idempotency, profile serialization, generation fencing, session compare-and-set, ordered event delivery, and SSE behavior remain unchanged.
7. Idle polling uses bounded jitter over an exponential 1-to-10-second progression and resets on claim or transport recovery; active free slots can still refill promptly.
8. No service, dependency, Redis use, table, API version, Cloud/Interface change, or FND-009 work is added; migration `0014` only widens the event-sequence check by one reserved server terminal slot.
9. A claim with no queued successor still reconciles stale state and returns empty; if no runtime is running, recovery waits safely for restart, after which continuous polling reconciles within the 10-second backoff ceiling.

## Focused validation

- Backend recovery: `$env:DJANGO_DEBUG='true'; make test APP="runtime/tests/test_fnd005_backend.py runtime/tests/test_fnd007_execution.py runtime/tests/test_services.py"`. Cover active and stopping expiry, cleanup-pending profiles, retired generations, no-successor empty claims, concurrent claims, duplicate synthetic append, outbox rollback, and next-sequence allocation after a high prior sequence.
- Runtime polling and immediate failure: `cd runtime; uv run --locked pytest tests/test_foundry.py tests/test_fnd007_worker.py tests/test_composition.py`. Include restart recovery within the maximum backoff bound.
- Repository checks from the root: `$env:DJANGO_DEBUG='true'; make check`; `make lint`; `make validate`.
- `make validate` is the complete Foundry gate: both lockfiles, Django checks, migration drift, backend coverage/tests, and runtime coverage/tests. Runtime coverage must remain at least 90 percent per `runtime/pyproject.toml`.
- Review migration `0014`, the migration-drift check, and `git diff --check`; no other migration or lockfile change is expected.

## Risks, rollback, and open decisions

- Risk: expiry-based release can overlap a truly stuck old Hermes stream. Mitigation: retain the runtime's renewal-loss cancellation and late-write fencing, act only after the full 60-second lease expires, and test that the old token cannot mutate durable state. The brief accepts progress after expiry; this is the main behavior change reviewers must confirm.
- Risk: two claimers append duplicate failure events or deadlock through inconsistent ordering. Mitigation: Workspace as the shared serialization point, then the established Attempt to Profile to Lease order, state rechecks, stable synthetic identity, atomic commit, and focused concurrent transaction coverage using existing test infrastructure.
- Risk: an event sequence or outbox failure leaves half-reconciled state. Mitigation: create and enqueue the safe event in the same transaction; any validation or persistence error rolls back the lease release.
- Risk: jitter makes tests slow or flaky. Mitigation: patch randomness and sleep, assert ranges and transitions, and keep production bounds constant.
- Rollback: revert the application code and documentation while retaining the backward-compatible widened sequence constraint. Already committed failure events and released leases remain durable facts and must not be deleted or replayed. No dependency rollback is required.
- Open decision: none for implementation. `message.delta` coalescing remains a separately measured optimization; add it only when event delivery or database evidence shows current bounded one-for-one forwarding is a material bottleneck.
