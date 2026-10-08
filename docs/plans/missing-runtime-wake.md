# Missing runtime wake failure

## Scope and evidence

A recorded runtime can disappear. Foundry's owned terminal wake-failure path clears the operation but leaves an accepted execution queued forever. Fix that silent outcome using the existing execution.failed event and Cloud delivery outbox. This fast plan needs no HTML. Nabu authentication returned 401; canonical knowledge could not be read. The root README and live branch use nightly, while nested Foundry guidance still says dev.

## Approach and ownership

Foundry owns runtime operations and execution state. After retry decisions in `_mark_operation_failed_locked`, fail never-started queued conversation executions when a wake ends without another retry. Reuse existing Attempt, ExecutionEvent, and ExecutionEventDelivery models. A failed Attempt numbered 1, with no claim or lease, records the server-owned failure. Append sequence 1 with the fixed safe payload `{code: runtime_wake_failed, retryable: true}` and enqueue through the existing event-delivery helper. No schema, contract, runtime replacement, or storage migration changes.

The workspace row remains locked through operation failure, execution failure, and outbox insertion. Existing operation ID and token comparisons reject stale claims. Acquire affected profile locks before execution locks, matching the claim path. Only executions with queued status and zero attempts qualify. Preserve running, previously attempted, terminal, and routine executions. Speculative wakes can carry execution demand after coalescing, so terminal STARTING and AWAITING_READINESS operations apply irrespective of their original trigger. STOPPING failures do not terminalize queued work.

## Steps and affected files

1. Add regression coverage in Foundry runtime tests. Prove missing runtime leaves accepted work silent before the change.
2. Add a small server-owned event helper in runtime/services/events.py and call it from runtime/services/runtime_power.py on terminal wake failure.
3. Verify the wire outbox, retry exhaustion, readiness timeout, stale-claim rejection, and preservation of attempted work. Parent independently handles live workspace recovery and delivery.

## Acceptance and validation

Missing runtime and exhausted wake retries produce one failed execution, one unclaimed failed attempt, one sequence-1 execution.failed event, and one durable outbox entry for contract-visible work. Repeated maintenance does not duplicate failure. Retryable wakes remain queued until their existing retry budget expires. Stale failure completion cannot alter a newer operation. Existing runtime session, lease, and routine behavior remains unchanged.

Run from services/foundry with DJANGO_DEBUG=true using the locked uv toolchain:

- `make test APP=runtime/tests/test_fnd009_runtime.py` for regression red and green.
- `make check`, `make lint`, and `make validate` for required repository validation.

CI also builds the runtime image and checks production configuration. This code changes only the backend; runtime image behavior is unchanged.

The worker environment has no `make` executable. Equivalent commands actually used:

- From backend, `DJANGO_DEBUG=true uv run --locked pytest runtime/tests/test_fnd009_runtime.py -q`.
- From Foundry, `DJANGO_DEBUG=true uv run --locked --project backend python scripts/validate.py`. This includes lockfiles, Django checks, migration checks, and both full test suites.
- From backend and runtime respectively, `uv run --locked ruff check .`.
- From backend, `uv run --locked ruff format --check runtime/services/events.py runtime/services/runtime_power.py runtime/tests/test_fnd009_runtime.py`.

## Risks, rollback, and decisions

A server-owned event needs an Attempt because the existing wire contract requires one. Its claim and lease stay absent, so it must not imply runtime execution. Cloud must accept failure as the first sequence; confirm against existing projection code and tests before delivery. The parent owns that integration check. Mark the failure retryable for safe user-initiated retry of never-started work. Keep Foundry execution status failed so there is no automatic replay. Existing attempted queued work is intentionally preserved because execution may already have produced side effects. Revert the patch to roll back code; preserve all existing workspace storage during operational recovery. No unresolved product decision or new architecture is required.
