# Fix: Hermes single-event size cap fails long-session turns

## Scope

Hanz (ally `9f3411d1`) and Shaka turns fail with full text delivered plus
"This response failed." Root cause, proven against prod: the gateway echoes
the session transcript inside the terminal `run.completed` SSE event as one
data line; once the session passes ~256KB the worker's `MAX_EVENT_BYTES`
check trips `Hermes stream event exceeded the byte limit` and the attempt is
marked `malformed_response` after all deltas were delivered. No
`execution.completed` is ever recorded. #80/#81 fixed different bugs
(idle timeout, session bind race), so these failures persist.

In scope: worker-side tolerance for large terminal events, regression test,
failure observability. Out of scope: gateway transcript echo (upstream
OpenClaw behavior; follow-up), Cloud status presentation.

## Approach

1. `runtime/allies_runtime/hermes.py`: raise `MAX_EVENT_BYTES` from 256KB to
   `MAX_STREAM_BYTES` (4MB), so no single event can exceed the whole-stream
   budget. One constant, one `ponytail:` ceiling comment.
2. Same file, `finish()`: include `str(error)` in `provider.operation.failed`
   fields. The missing message turned this incident into hours of forensics.
3. `runtime/tests/test_hermes.py`: regression test — `run.completed` with a
   ~300KB transcript line must yield `execution.completed`, not raise.

## Affected surfaces

- `runtime/allies_runtime/hermes.py` (SSE parser caps, observability fields).
- `runtime/tests/test_hermes.py` (new test only).
- Rollout: backend deploy + runtime image release; warm Fly workspaces pick
  it up on wake/reconcile. No API, schema, or contract changes.

## Acceptance

- Oversize terminal event (300KB transcript) parses to `execution.completed`.
- Existing byte-limit tests (monkeypatched small caps) still pass unchanged.
- Failed stream events carry the error message text.
- Hanz-class turns (large transcript, small reply) complete end to end once
  the image release reaches the workspace.

## Validation

- `uv run --locked pytest tests/test_hermes.py` from `runtime/` (targeted).
- `make runtime-test`, `make runtime-lint` from repo root (integrated).
- Existing `test_incremental_stream_enforces_bounds_and_closed_state` must
  pass unmodified (proves strict caps still enforced where set).

## Risks

- A larger cap holds larger hostile payloads in memory per event (bounded by
  the 4MB stream cap; accepted: transcripts are trusted gateway output).
- Transcript growth is unbounded: if sessions pass 4MB this recurs. Mitigated
  by the ceiling comment naming the gateway-echo follow-up as the revisit
  trigger.
- `MAX_EVENTS` (512 messages) is the next transcript ceiling; unchanged here.

## Unresolved decisions

- None blocking. Gateway-side transcript echo removal is a recorded
  follow-up, not part of this PR.
