---
title: ADR-002: Long Hermes stream completion
status: accepted
date: 2026-08-12
---

# ADR-002: Long Hermes stream completion

## Context

The incremental Hermes SSE parser rejected a valid turn after 512 raw events,
even when the terminal completion event had not arrived. Long-running Allies
tasks can legitimately contain hundreds or thousands of deltas and tool
lifecycle events, so a raw-event count cannot be the completion boundary.

## Decision

The incremental parser no longer rejects a stream because its raw event count
exceeds `MAX_EVENTS` (512). It continues to require valid event ordering,
profile and session identity, terminal completion, and the existing bounded
event and payload validation.

The parser retains these resource bounds:

- `MAX_STREAM_BYTES`: 4 MiB for the complete SSE stream;
- `MAX_EVENT_BYTES`: 256 KiB for one SSE event;
- the configured monotonic overall stream deadline (15 seconds by default,
  capped by runtime settings);
- bounded normalized event payloads and activity state.

The legacy whole-result parser remains bounded independently with
`MAX_BUFFERED_EVENTS = 65_536`. The existing `MAX_EVENTS` limit remains in
place for bounded history, transcript, and marker collections where retaining
the whole collection is intentional.

## Compatibility and failure behavior

This is a runtime-internal parser change; no Foundry or Hermes HTTP schema
changes. Streams that complete normally after more than 512 raw events now
persist their ordered normalized events and terminal receipt. Streams that
exceed byte, payload, identity, state, or overall-time bounds still fail
closed with a sanitized runtime error and retain any already-emitted user
visible deltas according to the existing execution contract.

## Validation

- Runtime suite: 279 passed, 5 skipped.
- Runtime Ruff checks: passed.
- Live long-stream gate: Sandy completed with 762 persisted generation-one
  events and terminal `ok`; Greg completed with 74 events.
- Live continuity gate: the standard two-container same-volume Machine
  replacement proof passed generation fencing, session isolation, recovery,
  and cleanup.

Local kickoff plans, review artifacts, rendered Lavish output, and raw proof
evidence remain operator-local under `.agent/` and `.lavish/`; durable
decisions belong in `docs/`.
