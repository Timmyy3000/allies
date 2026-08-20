# Allies Engineering Policy

**Core version:** 1.0
**Repository profile:** Foundry 1.0
**Status:** Required for new and materially changed code

## Purpose

Allies code should preserve user intent, protect runtime boundaries, remain
predictable under failure and concurrency, and be understandable to the next
engineer, contributor, or agent who changes it.

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

## Foundry runtime profile

### FND-01 — Keep runtime truth in Foundry

Foundry owns runtime profiles, workspaces, executions, attempts, leases,
ordered events, provider bindings, and runtime adapters. Product-facing Cloud
state is reached through a versioned contract; it is not recreated as shared
models or hidden imports.

## Open-source project profile

Foundry is a public repository. Apply these rules to new and materially changed
public code, documentation, fixtures, examples, and workflows.

### OSS-01 — Keep public content safe

Do not commit credentials, tokens, customer data, private URLs, internal host
names, absolute workstation paths, private package names, or exploit details.
Use generic fixtures and examples. If a security issue needs detail, publish
only the rule ID and severity in the public review and move the detail to a
private maintainer channel or GitHub Security Advisory.

### OSS-02 — Preserve provenance and license compatibility

New code, dependencies, examples, and assets need known provenance and terms
compatible with their use. Do not copy code or assets with unknown licensing or
remove required attribution. The absence of a repository-level license is a
tracked readiness gap, not an automatic finding on unrelated changes.

### OSS-03 — Keep setup portable

Document commands, configuration, and environment assumptions so a contributor
can work from a clean checkout. Do not hardcode a maintainer's filesystem,
machine, network, credentials, or private deployment as the only path.

### OSS-04 — Treat public contracts as compatibility work

Changes to public APIs, CLI commands, runtime protocols, schemas, or examples
include tests and clear documentation. Breaking behavior is versioned,
deprecated, or explicitly called out with migration guidance.

### OSS-05 — Make contribution behavior understandable

Use clear names, actionable errors, bounded examples, and deterministic tests.
Do not require private organizational context, unpublished services, or
maintainer-only steps for ordinary development and verification.

### OSS-06 — Preserve reproducible CI and security checks

Do not weaken tests, secret scanning, dependency checks, or review gates to
make a change pass. Pin or upgrade actions and dependencies deliberately, and
explain compatibility-impacting changes.

### OSS-07 — Keep the core provider-neutral

Core code, contracts, examples, required CI/workflows, and ordinary setup must
not depend on or name a hosting or domain vendor. Provider integrations may be
optional, isolated behind generic core boundaries, and documented separately;
provider-specific behavior must not become an implicit core contract.

Missing `LICENSE`, `SECURITY.md`, or contributor material remains an open
project-readiness item until deliberately adopted; policy review must not turn
that baseline gap into a finding on unrelated files.

## Exceptions

An exception names the rule, scope, reason, risk, mitigation, owner, and expiry
or revisit condition. Exceptions cannot waive runtime isolation, authorization,
secret handling, or honest persistence outcomes.

## Review severity

- **P0:** credible data loss, exposed secrets, destructive corruption, or a public privacy/security breach.
- **P1:** clear correctness, security, compatibility, or operational impact; fix before merge.
- **P2:** meaningful robustness, contributor, or maintainability risk; fix or record an exception.
- **Nit:** preference without meaningful risk; policy review should normally remain silent.

## Responsibilities

`ENGINEERING_STYLE.md` owns these rules. `.enkii/policy-review.md` owns the
review procedure. `.github/CODEOWNERS` identifies the owners for governance
changes; branch protection or an equivalent approval control must enforce that
ownership when required. Repository instructions and feature documents may add
constraints but may not silently weaken these rules.
