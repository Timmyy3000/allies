# Allies Engineering Policy

**Core version:** 1.0
**Repository profile:** Interface 1.0
**Status:** Required for new and materially changed code

## Purpose

Allies code should preserve user intent, protect product and account
boundaries, remain predictable under failure and concurrency, and be
understandable to the next engineer, contributor, or agent who changes it.

Our priorities are:

1. Trust.
2. Clear ownership and contracts.
3. Operational stewardship.

## Scope and legacy boundary

This policy applies to new code, materially changed code, plans, and reviews.
Existing violations are not automatically findings. A change must not worsen a
known violation, add another responsibility to an overloaded area without a
design decision, or hide correctness, authorization, security, or data-loss
risk as unspecified future work.

## Shared policy

### AL-01 — Design before implementation

Substantial changes identify ownership, boundaries, inputs, outputs, states,
failure behavior, concurrency, compatibility, and the relevant test evidence.
The design may be short, but important decisions must be deliberate.

### AL-02 — Validate trust boundaries

Treat API requests, URLs, browser state, files, provider responses, AI output,
and persisted legacy data as untrusted until validated at a clear boundary.
Authentication does not replace authorization.

### AL-03 — Preserve intent and durable state

Failed persistence must not be reported as success. Do not silently overwrite,
duplicate, delete, or reinterpret user work. Destructive actions need explicit
authorization and a reversible or reconciliable failure path where practical.

### AL-04 — Make ownership, states, and invariants explicit

Important state has one authoritative owner, named states, valid transitions,
and deliberate behavior for repeated, invalid, stale, and out-of-order input.
Derived copies define their synchronization and conflict behavior.

### AL-05 — Define external-I/O behavior

Meaningful network, provider, storage, and process operations define timeout,
cancellation, retry, backoff, idempotency, duplicate-response, malformed-
response, partial-failure, and operational-evidence behavior.

### AL-06 — Expect concurrency and duplication

Assume requests, streams, and events can be repeated, reordered, reconnected,
or resumed after a process restart. Use cancellation, request identity,
deduplication, conflict handling, or server reconciliation as appropriate.

### AL-07 — Bound work

Define practical limits for requests, uploads, pages, batches, retries,
polling, payloads, memory, and execution time. Avoid unbounded client work and
per-item network calls without an explicit bound and measurement.

### AL-08 — Keep interfaces narrow and versioned

Use typed API, event, storage, and persisted-state contracts. The Interface
must talk to Cloud through its public versioned contract and must not call
Foundry directly or import backend implementation details.

### AL-09 — Keep operations privacy-safe

Logs, telemetry, errors, fixtures, and review comments must not expose
credentials, tokens, private URLs, customer data, full documents, or
unnecessary personal data.

### AL-10 — Test the risk

Tests cover the failure and boundary cases most likely to regress: invalid
input, authorization, loading and empty states, retries, stale responses,
offline or reconnect behavior, compatibility, and state transitions.

### AL-11 — Use dependencies and abstractions deliberately

Prefer existing workspace capabilities. A new dependency or abstraction needs a
concrete current benefit, an ownership boundary, and a maintenance and
security assessment. Do not build speculative frameworks.

### AL-12 — Make changes reviewable

Keep commits and diffs focused. Include relevant tests and contract changes in
the same change. Record a concrete owner, impact, mitigation, and revisit
condition for an exception rather than hiding it in a TODO.

## Interface profile

### INT-01 — Keep client ownership clear

The Interface owns presentation, interaction, local view state, and transport
adapters. Cloud owns product truth, authorization, and durable state. Do not
duplicate backend business rules in screens or silently invent fallback data.

### INT-02 — Make user-visible states explicit

Every meaningful request surface defines loading, empty, success, error,
retry, cancellation, and reconnect behavior appropriate to the product flow.

## Exceptions

An exception names the rule, scope, reason, risk, mitigation, owner, and expiry
or revisit condition. Exceptions cannot waive authorization, secret handling,
or honest persistence outcomes.

## Review severity

- **P0:** credible data loss, exposed secrets, cross-account access, or destructive corruption.
- **P1:** clear correctness, security, compatibility, or operational impact; fix before merge.
- **P2:** meaningful robustness or maintainability risk; fix or record an exception.
- **Nit:** preference without meaningful risk; policy review should normally remain silent.

## Responsibilities

`ENGINEERING_STYLE.md` owns these rules. `.enkii/policy-review.md` owns the
review procedure. `.github/CODEOWNERS` identifies the owners for governance
changes; branch protection or an equivalent approval control must enforce that
ownership when required. Repository instructions and feature documents may add
constraints but may not silently weaken these rules.
