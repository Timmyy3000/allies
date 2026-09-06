# Allies Engineering Policy

**Core version:** 1.0
**Repository profile:** Cloud 1.0
**Status:** Required for new and materially changed code

## Purpose

Allies code should preserve user intent, protect tenant boundaries, remain
predictable under failure and concurrency, and be understandable to the next
engineer or agent who changes it.

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

Treat API requests, URLs, webhooks, queues, files, browser state, provider
responses, AI output, and persisted legacy data as untrusted until validated at
a clear boundary. Authentication does not replace authorization.

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

Assume requests, tasks, streams, and events can be repeated, reordered,
reconnected, or resumed after a process restart. Use transactions, locks,
leases, idempotency keys, request identity, or conflict handling as appropriate.

### AL-07 — Bound work

Define practical limits for requests, uploads, pages, batches, queues, retries,
polling, payloads, memory, and execution time. Do not put unbounded database,
network, or provider work inside a per-record loop.

### AL-08 — Keep interfaces narrow and versioned

Use typed request, response, event, task, and persisted-state contracts. Keep
cross-repository calls behind versioned boundaries and do not share Django
models or hidden implementation details between repositories.

### AL-09 — Keep operations privacy-safe

Logs, traces, tasks, errors, and review comments must not expose credentials,
tokens, private URLs, customer data, full documents, or unnecessary personal
data. Operational evidence should explain what failed without exposing why it
is sensitive.

### AL-10 — Test the risk

Tests cover the failure and boundary cases most likely to regress: invalid
input, authorization and tenant isolation, repeated or stale requests,
timeouts, retries, compatibility, and state transitions. Coverage supports
evidence but does not replace risk-based tests.

### AL-11 — Use dependencies and abstractions deliberately

Prefer existing repository capabilities. A new dependency or abstraction needs
a concrete current benefit, an ownership boundary, and a maintenance and
security assessment. Do not build speculative frameworks.

### AL-12 — Make changes reviewable

Keep commits and diffs focused. Include relevant tests and contract changes in
the same change. Record a concrete owner, impact, mitigation, and revisit
condition for an exception rather than hiding it in a TODO.

#### PR size and delivery

Strongly prefer one coherent change per PR that can be reviewed carefully in
about 20-30 minutes. Smaller PRs help us ship sooner by keeping Enkii reviews
shorter and more accurate; size is a strong planning consideration, not a hard
limit or an automatic review failure.

- Aim for roughly 200-500 changed lines (additions plus deletions); smaller
  focused fixes are welcome. Exclude generated files, lockfiles, and purely
  mechanical formatting from this sizing signal, but still review their risks.
- Above 500 lines, actively consider splitting independent behavior, refactors,
  and cleanup. Above 1,000 lines, normally split or explain in the PR description
  why keeping the change together is safer and easier to review.
- Keep implementation, relevant tests, and required contract or migration
  changes together. Each PR must remain coherent and testable; do not create
  broken intermediate states, omit tests, or compress code to meet a number.
- For dependent PRs, state the dependencies and merge/rollout order. Reassess
  scope before opening or substantially expanding a PR, rather than waiting
  until review to separate unrelated work.

## Cloud profile

### CLOUD-01 — Enforce tenant scope at the data boundary

Every tenant-owned lookup or mutation resolves an explicit tenant and checks
membership, resource ancestry, and capability before returning or changing
data. Negative cross-tenant tests are required for new scoped endpoints.

### CLOUD-02 — Keep product truth in Cloud

Cloud owns customer-facing product state, conversations, authorization, and
delivery state. Foundry runtime state is reached through a versioned gateway;
Cloud code must not import Foundry models or reproduce Foundry workflows.

## Exceptions

An exception names the rule, scope, reason, risk, mitigation, owner, and expiry
or revisit condition. Exceptions cannot waive tenant isolation, authorization,
secret handling, or honest persistence outcomes.

## Review severity

- **P0:** credible data loss, cross-tenant access, exposed secrets, or destructive corruption.
- **P1:** clear correctness, security, compatibility, or operational impact; fix before merge.
- **P2:** meaningful robustness or maintainability risk; fix or record an exception.
- **Nit:** preference without meaningful risk; policy review should normally remain silent.

## Responsibilities

`ENGINEERING_STYLE.md` owns these rules. `.enkii/policy-review.md` owns the
review procedure. `.github/CODEOWNERS` identifies the owners for governance
changes; branch protection or an equivalent approval control must enforce that
ownership when required. Repository instructions and feature documents may add
constraints but may not silently weaken these rules.
