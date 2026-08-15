# CLD-008 Cloud Waitlist Draft And Claim-Ready Handoff

## Status

- Type: feature
- Implementation delegation: always
- Delegation source: `kickoff` workflow fallback
- Review worker: `gpt-5.6-terra` with `xhigh` reasoning
- Review worker source: `docs/plans/kickoff.yaml`
- Implementation worker: personal named agent `luna_max` (`gpt-5.6-luna` with `max` reasoning)
- Implementation worker source: `docs/plans/kickoff.yaml` and repository `AGENTS.md`
- Planning mode: full
- Worktree manager: Forest
- Branch: `codex/cld-008-waitlist`
- Worktree path: `.forest/worktrees/codex/cld-008-waitlist`
- Task workspace: `docs/plans`
- Kickoff configuration: `docs/plans/kickoff.yaml`
- Created: 2026-08-14
- Target date: not specified
- Current phase: implementation through `ship-it`

## Objective

Implement the accepted CLD-008 Cloud boundary so one unauthenticated visitor can
configure a temporary Ally, receive one bounded personalized greeting, preserve
an exact attempted reply as pending, and join the waitlist without creating an
account or any production product/runtime object. The state must survive refresh
through an opaque browser-bound capability and remain safely claimable later
only after authentication, verified matching email evidence, and explicit user
confirmation.

The implementation must publish the versioned staging OpenAPI contract required
by INT-009 while staying entirely inside `allies-cloud`. OBS-001 is parked behind
the waitlist priority.

## Context

Nabu identifies EPIC-WAITLIST as the current active delivery epic. CLD-008 is
ready and unassigned in the Foundry & Cloud lane, with CLD-001 complete. INT-009
may develop its fixture-backed Interface portion in parallel, but final
integration depends on the CLD-008 staging contract. No waitlist implementation
ticket was claimed when Nabu was reconciled on 2026-08-14.

The accepted Cloud specification deliberately separates this preview from the
authenticated product. This slice creates no account, Workspace, production
Ally, conversation, message delivery, Foundry/Hermes binding, runtime execution,
tool call, retrieval, memory, or global name reservation. The visitor's reply is
stored exactly and truthfully remains pending.

The repository is a Django 6 / Django Ninja Extra Cloud service. The accepted
plan follows its controller -> registrar -> root API composition and adds a
focused `waitlist` domain rather than coupling pre-auth state to the existing
authentication/account foundation.

## Canonical Evidence

- Nabu delivery state: `projects/allies/delivery/now.md`
- Nabu epic: `projects/allies/delivery/epics/EPIC-WAITLIST.md`
- Nabu ticket: `projects/allies/delivery/tickets/cloud/CLD-008.md`
- Nabu specification: `projects/allies/engineering/specs/waitlist/CLD-008-cloud-waitlist-draft.md`
- Repository guidance: `ENGINEERING_STYLE.md`, `README.md`, `.env.example`
- Kickoff configuration: `docs/plans/kickoff.yaml`
- Reviewable Lavish plan: `.lavish/cld-008-cloud-waitlist-plan.html`
- Accepted portable plan archive: `docs/plans/cld-008-cloud-waitlist-plan.html`

## Requirements

1. Add one focused `backend/waitlist` Django application and register its
   controllers through the repository's existing API composition pattern.
2. Issue one opaque high-entropy browser capability in a Secure, HttpOnly,
   appropriately scoped SameSite cookie. Return a CSRF token separately; never
   expose the raw capability to JavaScript, persistence, logs, traces, errors,
   or evidence. Store only a keyed digest.
3. Make Cloud the source of truth after each successful step. Support creating
   or resuming one draft, restoring it after refresh, updating configuration,
   generating or retrieving a greeting, recording a reply, and joining.
4. Require an exact trusted Origin/Referer policy and CSRF on public cookie-bound
   mutations. Normalize absent and unauthorized draft behavior so existence is
   not enumerable.
5. Use optimistic revisions for all state-changing operations. A stale revision
   returns `409 waitlist_draft_stale` without overwriting newer state.
6. Make create, configuration, generation, reply, and join retries deterministic
   using an `Idempotency-Key` digest plus normalized request digest. Mutations
   return a small immutable acknowledgement (`operation`, `result_revision`,
   `result_lifecycle`) and clients use restore for the current snapshot. Reusing
   a key with different input returns `idempotency_conflict`; an active lease
   returns `waitlist_operation_in_progress`. Create is capability-bound
   create-or-resume after the session cookie has already been established.
7. Persist the current product snapshot in `WaitlistDraft` and the minimum retry
   receipts in `WaitlistOperation`; do not introduce configuration, greeting,
   reply, consent, history, email, or generic cross-domain idempotency models.
8. Preserve the Interface-owned appearance selection as
   `appearance_catalog_version` plus one bounded opaque `appearance_key`, but
   send only bounded name, job, and
   user-authored personality text to greeting generation. Never send email,
   reply, appearance keys, browser metadata, capability data, or internal IDs.
9. Call the OpenAI Responses API through a narrow provider abstraction with
   `store=false`, `background=false`, no tools, zero SDK retries, a short output
   bound, and an eight-second request timeout. Do not send an internal operation
   identifier: the canonical specification excludes internal IDs, and the
   current public API reference documents request IDs for support correlation,
   not Responses deduplication. An ambiguous timeout becomes `outcome_unknown`; Cloud performs
   no automatic retry, enforces a per-draft attempt cap/cooldown, and requires an
   explicit new-key user retry. A deterministic fake provider is used in unit
   and contract tests.
10. Treat model output as untrusted plain text. Use a versioned, owner-reviewed
    instruction that forbids claims about accounts, tools, memory, files,
    completed work, or other unavailable capabilities. A deterministic output
    policy rejects empty, oversized, malformed, or prohibited capability claims
    without storing/showing them. Provider or policy failure preserves the
    configuration and supports only the controlled retry protocol; Cloud must
    not invent a generic greeting that appears personalized.
11. Store the exact attempted reply as `reply_pending` without sending it to a
    model, queue, runtime, Foundry, Hermes, or any other external service.
12. On join, normalize and store the email plus active consent version and
    timestamp, preserve the full pending draft, and return only a masked email.
    Do not add public email or Ally-name lookup.
13. Leave an internal claim boundary that requires an authenticated Cloud user,
    verified matching email evidence, and explicit confirmation. Extend the
    existing `ExternalIdentity` record with verification status, timestamp, and
    provenance from an allowlisted provider assertion; fake/unverified snapshots
    are ineligible. Use one canonical email normalization/comparison routine.
    Email equality alone is never authority. Claiming is not exposed as a public
    endpoint in this slice. This adds no third waitlist model.
14. Expire abandoned pre-join drafts after seven days. Keep joined-draft
    retention separately configurable and disabled from destructive cleanup
    until product/legal approve the duration and matching privacy notice.
15. Apply request bounds through one narrowly scoped `waitlist/admission.py`
    module with Redis-backed atomic controls at three layers:
    network-aware bootstrap creation, per-capability operations, and a
    distributed global generation concurrency/budget lease shared by every web
    process. Cache loss fails public creation/generation closed. Use keyed
    network digests and privacy-safe structured outcomes without logging visitor
    content or sensitive identifiers.
16. Publish the binding request, response, lifecycle, and machine-readable error
   contract through the versioned OpenAPI artifact and prove it in staging for
   INT-009.
17. Replace the global verbatim Ninja/Pydantic validation payload with a stable
    privacy-safe shape containing only field locations and allowlisted reason
    codes. Never return `input`, `ctx`, provider details, or content-bearing
    messages; preserve existing endpoint status/envelope compatibility and add
    regression coverage for the auth/account APIs.

## Persistence Decisions

### `WaitlistDraft`

One row represents the current browser-bound preview. The accepted plan defines:

- `public_id`: opaque public UUID/identifier; never an authorization credential.
- `capability_digest`: nullable unique HMAC-SHA256 digest of the browser secret.
- `lifecycle`: choices for `configuring`, `ready_for_greeting`,
  `greeting_ready`, `reply_pending`, `pending_claim`, `claimed`, and `expired`.
- `revision`: monotonically increasing positive integer used for compare-and-set
  mutations.
- Configuration snapshot: bounded name, `appearance_catalog_version`, one
  bounded opaque `appearance_key`, bounded job, and bounded user-authored
  personality text.
- Generation snapshot: normalized-input fingerprint, generated plain text,
  owner-approved greeting-policy version, and generation timestamp. Provider and
  model identifiers remain deployment configuration and are not duplicated on
  each alpha draft.
- Reply snapshot: exact bounded text and recorded timestamp.
- Join snapshot: normalized email, consent version, consent/join timestamp.
- Claim seam: nullable `claimed_by` foreign key using `PROTECT` plus `claimed_at`.
- Retention and audit timestamps: `expires_at`, `created_at`, and `updated_at`.

Constraints and service invariants prevent impossible lifecycle/field
combinations, ensure configuration changes invalidate obsolete greetings, and
ensure joined drafts do not silently inherit abandoned-draft deletion.

### `WaitlistOperation`

One row represents one retry receipt per draft, operation kind, and client retry
key. The accepted plan defines:

- `draft`: foreign key to `WaitlistDraft` with `CASCADE`.
- `kind`: `create`, `configure`, `generate`, `reply`, or `join`.
- `idempotency_digest`: HMAC-SHA256 of the raw retry key.
- `request_digest`: canonical digest of normalized operation input.
- `status`: `in_progress`, `succeeded`, `failed`, or `outcome_unknown`.
- `lease_expires_at`: required only while an operation is active.
- `result_revision`: stored for successful deterministic replay.
- `result_lifecycle`: stored with `result_revision` so replay returns the
  original immutable acknowledgement even after later mutations.
- `failure_code`: safe machine-readable code for failed replay.
- `completed_at`, `created_at`, and `updated_at`.

The database enforces uniqueness on
`(draft, kind, idempotency_digest)`, indexes `(draft, kind, status)`, and checks
that active and terminal fields match the operation status. An unknown provider
outcome is terminal for the original key, carries no fabricated result, and is
eligible only for an explicit new-key retry after cooldown and below the
per-draft attempt cap. Raw retry keys and response bodies are not persisted.

## Public Contract

The plan exposes seven narrow operations below `/api/v1/waitlist`:

1. Get or establish the browser session and CSRF context.
2. Create or resume the authorized current draft.
3. Restore the authorized current draft.
4. Update configuration with a last-observed revision.
5. Generate or retrieve the greeting for the current generation fingerprint.
6. Record the exact attempted reply as pending.
7. Join with email and consent version and receive a masked confirmation.

Mutation responses are immutable acknowledgements containing the operation kind,
result revision, and result lifecycle; clients call restore for the current
snapshot. Join may recompute the masked address from its immutable joined email.
Errors distinguish
validation, origin/CSRF rejection, unavailable or unauthorized draft, stale
revision, invalid state, idempotency conflict/in-progress state, generation
outcome unknown/unavailability, throttling, and temporary service unavailability without
revealing private inputs or draft existence.

## Implementation Sequence

1. Confirm the worktree/branch assignment and capture baseline validation.
2. Add settings and the disabled-by-default waitlist feature boundary, exact
   trusted origins, cookie/CSRF policy, bounds, provider options, rate/admission
   limits, and separate abandoned/joined retention settings.
3. Add the `waitlist` app, the two models, choices, constraints, indexes, and
   initial migration. Verify both SQLite repository workflows and PostgreSQL
   concurrency behavior where locking matters.
4. Add capability, CSRF/origin, masking, normalization, revision, idempotency,
   and lifecycle services with privacy-safe domain errors. Sanitize the global
   Ninja validation handler before registering public waitlist schemas.
5. Add the provider interface, deterministic fake, versioned instruction/output
   policy, and bounded OpenAI Responses adapter. Keep network calls outside
   database transactions while retaining an operation lease and re-checking the
   draft revision/fingerprint before commit. Treat ambiguous timeouts/crashes as
   unknown outcomes with no automatic retry; enforce cooldown and attempt caps.
6. Extend `ExternalIdentity` with verified-email provenance, update the Google
   verified-identity path, keep the fake provider explicitly unverified, add
   auth regression tests, then add the internal confirmed
   claim service using the canonical comparison routine.
7. Add all Redis-backed bootstrap/per-capability limits, a per-capability
   generation fairness budget, and the distributed global generation
   budget/concurrency lease to the single waitlist admission module; fail
   creation/generation closed on cache loss.
8. Add Ninja schemas and controllers, register the API routes, and publish the
   versioned OpenAPI contract.
9. Add cleanup for expired pre-join drafts and safe operation receipts; keep
   joined deletion gated by explicit configured policy.
10. Add focused unit, service, API/contract, concurrency, migration, cleanup,
   privacy, provider-failure, and settings tests.
11. Add `waitlist` to `[tool.coverage.run].source`, keep focused waitlist
   coverage as supplementary evidence, and run full repository validation.
12. Inspect the OpenAPI/migration diff and prove
   the staging route, isolation, safe retries, failure recovery, and cleanup
   separation through the existing Cloud deployment path before handoff to
   INT-009. Add a bounded beat entry, but change Railway/process documentation
   only if an actual shared environment or topology contract changes.

## Acceptance Criteria

1. A new unauthenticated browser can establish one authorized draft, progress
   through the Cloud flow, and restore the last successful state after refresh.
2. A different browser or invalid capability cannot read or mutate the draft
   and cannot distinguish an absent draft from an unauthorized one.
3. Configuration fields persist independently, stale updates return the stable
   conflict code, and changing generation input invalidates obsolete output.
4. One policy-approved bounded greeting is stored for the current normalized
   input; duplicate retries are deterministic, prohibited capability claims are
   rejected, and provider/policy failure preserves the draft.
5. Provider requests contain only bounded name, job, and personality and use
   no storage, background execution, tools, or hidden SDK retries.
6. The exact reply is stored as pending and produces no downstream side effect.
7. Join stores normalized email and consent evidence, returns a masked address,
   and never adds a lookup or automatic claim path.
8. The claim service rejects unauthenticated, unverified, mismatched,
   unconfirmed, expired, or already-claimed attempts.
9. Seven-day cleanup deletes abandoned drafts and their operation receipts;
   joined drafts are governed by a separate release-approved policy.
10. Tests and evidence show immutable retry acknowledgement before and after
    later mutations, ambiguous provider-outcome recovery without automatic
    duplicate spend, stale-write rejection, concurrent generation safety,
    distributed admission controls, privacy-safe diagnostics/validation, and
    provider-failure recovery.
11. The versioned staging OpenAPI contract documents all operations, lifecycle
    states, success shapes, error semantics, credentials, CSRF, and retry rules
    required by INT-009.
12. No code path creates an account, Workspace, production Ally, conversation,
    runtime binding, execution, or global name reservation.

## Verification Plan

- Run the repository's formatting, lint, type/check, migration-check, security,
  and complete test commands identified during implementation intake.
- Run focused waitlist model/service/controller tests and PostgreSQL concurrency
  tests for compare-and-set updates and operation leases. Retain indexes and
  bounded cleanup; do not add brittle numeric ORM query-count budgets without a
  demonstrated performance problem.
- Assert capability secrets, retry keys, email, visitor-authored content,
  prompts, and model output never appear in logs, traces, errors, snapshots, or
  evidence.
- Diff and review the generated OpenAPI artifact and migrations.
- Exercise a credentialed staging walkthrough covering new browser, refresh,
  duplicate retries, stale revision, unauthorized browser, provider failure,
  recovery, pending reply, join, and cleanup.
- Record evidence without production personal data or secrets.

## Risks And Mitigations

- **Capability theft or leakage:** HttpOnly/Secure/path-scoped cookie, keyed
  digest only, exact origin plus CSRF, normalized unavailable responses, expiry,
  and secret-redaction tests.
- **Lost responses and duplicate provider spend:** immutable operation
  acknowledgements, request digests, leases, terminal unknown outcomes, zero
  automatic/SDK retries, cooldown plus per-draft attempt cap, and an explicit
  new-key caller retry only.
- **Holding locks during model latency:** reserve under a short transaction,
  call the provider outside the transaction, then compare revision and
  fingerprint before storing the result.
- **Concurrent stale overwrites:** database-backed compare-and-set revision
  checks and focused PostgreSQL concurrency proof.
- **Abuse and cost growth:** strict request/output bounds, throttles, global
  generation admission, short timeout, disabled-by-default feature, and
  observable aggregate outcomes without sensitive payloads.
- **Privacy or retention drift:** separate abandoned and joined policies;
  destructive joined cleanup remains off until legal/product decisions land.
- **Scope creep into auth/runtime:** dedicated waitlist domain and explicit
  negative tests for product object creation and downstream calls.
- **Interface contract drift:** OpenAPI is binding, generated early, diffed in
  review, and pinned by INT-009 staging integration.

## Release Gates And Open Questions

These do not block non-production implementation but do block production:

1. Product/legal must approve joined-draft retention and deletion policy.
2. Product/legal must provide the privacy/consent copy and stable version ID.
3. Operations/product must approve the production model, exact output bound,
   timeout, request/generation limits, and cost thresholds.
4. Cloud and Interface must confirm exact production origins and credentialed
   cookie/CSRF deployment topology.

Planning defaults are a seven-day abandoned expiry, separately gated joined
retention, an OpenAI provider plus deterministic fake, an eight-second timeout,
zero SDK retries, and a short bounded plain-text greeting. These remain
configuration decisions, not silently hard-coded production policy.

## Decisions

- CLD-008 is the next Cloud implementation slice; OBS-001 remains parked.
- Only `allies-cloud` may be modified. Interface and Foundry are context only.
- Use a dedicated waitlist app and exactly two persistence models.
- Use a browser capability, not anonymous accounts or Django sessions, as the
  draft authorization boundary.
- Keep generation synchronous and bounded; do not add queues or background
  workflow infrastructure for one short greeting.
- Publish one narrow browser contract; do not introduce public lookup or claim
  endpoints.
- Treat release-policy questions as explicit gates instead of blocking the
  non-production implementation or guessing production policy.

## Review Record

### Human planning approval

- 2026-08-14: The user approved the expanded Lavish plan, including the explicit
  `WaitlistDraft` and `WaitlistOperation` model definitions, and directed
  Kickoff to continue to its next stages.
- 2026-08-14: The user authorized installing Forest globally and proceeding.
  Forest v0.8.0 was verified and created this isolated worktree.

### Independent adversarial review

- Status: complete; verdict was `Needs revision` and every finding was accepted.
- Full output: `docs/plans/cld-008-cloud-waitlist-adversarial-review.md`.

Dispositions:

1. **Major — privacy-safe validation: accepted.** Sanitize the global Ninja
   validation handler to field locations and allowlisted codes only, with
   auth/account compatibility and secret-like regression tests.
2. **Major — idempotency correctness: accepted.** Mutation responses become
   immutable acknowledgements. `WaitlistOperation` adds `result_lifecycle`,
   restore owns current snapshots, and create is explicitly capability-bound
   after session bootstrap.
3. **Major — provider retry/cost safety: accepted.** No provider idempotency is
   assumed. Ambiguous timeouts/crashes become terminal `outcome_unknown`; there
   is no automatic retry, and a new-key retry is gated by cooldown, per-draft
   attempt cap, and the global budget.
4. **Major — public abuse controls: accepted.** Replace process-local assumptions
   with Redis-atomic network bootstrap, per-capability, and distributed global
   generation leases that fail closed on cache loss.
5. **Major — claim authorization seam: accepted.** Extend existing
   `ExternalIdentity` with durable verified-email status/time/provenance, make
   fake/unverified evidence ineligible, and use one canonical comparison
   routine. The waitlist app still creates exactly two new models.
6. **Major — greeting truthfulness: accepted.** Add a versioned owner-approved
   instruction and persist its policy version; deterministically reject
   prohibited capability claims without storing/showing output.
7. **Minor — coverage integration: accepted.** Add `waitlist` to repository-wide
   coverage sources and retain focused waitlist coverage as supplementary proof.

### Independent simplicity review

- Status: complete; verdict was `Simplification recommended`, with no conflict.
- Full output: `docs/plans/cld-008-cloud-waitlist-simplicity-review.md`.

Dispositions:

1. **Keep — capability/origin/CSRF/unavailable behavior: accepted.** This is
   intrinsic to the accepted privacy boundary.
2. **Keep — lifecycle/revision/four receipt states: accepted.** These are the
   minimum honest stale-write, replay, and ambiguous-provider protocol.
3. **Simplify — appearance fields: accepted.** Store only catalog version plus
   one opaque selection key; align that representation with Interface before
   OpenAPI publication.
4. **Simplify — greeting provenance: accepted.** Remove per-draft provider/model
   columns; retain policy version and generation time.
5. **Simplify — admission ownership: accepted.** One waitlist-local module owns
   the three Redis operations; no generic rate-limit framework.
6. **Keep — three Redis layers: accepted.** Their identity scopes are distinct
   and directly address capability rotation, multi-worker safety, and cost.
7. **Keep — global validation sanitizer: accepted.** One global fix is smaller
   and safer than a waitlist-only fork.
8. **Simplify — fake verification: accepted.** Fake remains explicitly
   unverified; only the Google verified path gains durable provenance.
9. **Keep — identity provenance/claim seam: accepted.** This is required to
   prevent email equality from becoming authority.
10. **Keep — narrow synchronous provider/policy: accepted.** No registry, queue,
    fallback greeting, or extra provider framework is added.
11. **Remove/defer — numeric query budgets: accepted.** Keep indexes, bounded
    cleanup, review, and race tests; profile only from evidence.
12. **Remove/defer — waitlist Railway machinery: accepted.** Reuse the existing
    staging path and scheduler; update operations docs only for real contract
    changes.

## Execution Notes

- Planning and both independent reviews run from the Forest worktree named
  `codex/cld-008-waitlist`.
- 2026-08-14: The user gave final implementation approval. The accepted Lavish
  session was ended and exported to
  `docs/plans/cld-008-cloud-waitlist-plan.html` before `ship-it` began.
- Implementation delegation is `always` from the Kickoff workflow fallback.
  The configured implementation worker is the named agent `luna_max` from
  `docs/plans/kickoff.yaml` and repository `AGENTS.md`.
- CLD-008 is claimed in canonical Nabu delivery state by Codex as orchestrator,
  with `luna_max` recorded as the implementation worker. Nabu records the
  branch, Forest worktree, accepted plan, and work brief. The referenced local
  Task Master copy is not mounted in this Cloud workspace and remains a later
  reconciliation item; no second tracker was created.
- The host exposes Python 3.13.3 but not `uv` or `make` on PATH. Implementation
  may bootstrap `uv` inside ignored `backend/.venv` so dependency and validation
  work stays inside the Cloud worktree.
- Before implementation, the assigned engineer must claim CLD-008 through the
  delivery system and synchronize the assignee, branch, worktree, and plan link
  to Nabu as required by the canonical ticket.
- 2026-08-14: `luna_max` implemented the Cloud-only slice in the isolated
  worktree. Orchestrator integration added deterministic failure receipts,
  one-live-generation-per-draft protection, atomic admission counters, expired
  capability rotation, consent-rotation replay, complete cookie/error OpenAPI
  semantics, and PostgreSQL-marked create/generate/claim race coverage.
- Independent pre-PR code review found seven actionable state/contract issues;
  all were resolved before publication. The follow-up review is recorded in
  the delivery handoff.
- Enkii's first PR review added seven P2 findings. The follow-up change signs
  and expires capability cookies, reuses the server-issued Railway browser
  throttle identity, makes Redis lease ownership explicit and atomic, gates
  cleanup scheduling behind the feature flag, declares the capability TTL,
  and adds cross-browser plus auth-contract regression coverage.
- Enkii's second PR review confirmed those seven fixes and added two P2
  findings. The next follow-up makes capability validity slide on every
  successful draft operation without changing the draft binding and reserves
  generation capacity fairly with a per-capability minute budget ahead of the
  global cost budget.
- Validation after integration: Django system check and migration drift check
  pass; Ruff check and format check pass; the exact focused waitlist run passes
  with 35 tests and 3 PostgreSQL-only skips at 91.24% coverage; the full
  repository run passes with 156 tests, 9 PostgreSQL-only skips, and 91.34%
  aggregate coverage. A PostgreSQL service was not available locally; the
  committed race tests passed in the PR's PostgreSQL CI job before this
  follow-up and will rerun on the review-fix commit.
