# CLD-003 Create and Manage a Real Ally Plan

## Feature Overview

- Problem: the official disposable onboarding preview creates no product Ally, Workspace data, conversation, or runtime profile. After authentication, the same route must create one durable Ally without a waitlist claim path.
- Target users: authenticated personal-Workspace owners completing onboarding.
- Source docs/specs: `docs/plans/cld-003-kickoff.md`; Nabu `projects/allies/engineering/specs/cld-003-create-and-manage-real-ally.md` and `projects/allies/engineering/specs/foundry-continuity-layer.md`; `ENGINEERING_STYLE.md`; Cloud auth, workspace, Celery, and API conventions.
- Success outcome: one Cloud-owned Ally, one immutable Foundry binding, truthful derived provisioning state, and the current preview greeting/reply preserved through the existing conversation boundary. A matching idempotent create replays; conflicting and cross-Workspace requests fail closed.

## User Stories

1. As an onboarding user, I can edit name, job, exact personality text, and appearance before sign-in so the durable Ally reflects my final choices.
2. As an authenticated Workspace owner, I receive a stable Ally and provisioning outcome so I can repeat the original create safely.
3. As an operator, I can see sanitized operation outcomes so failed provisioning can recover without private provider data.

## Scope

### In Scope

- Cloud `allies` domain app with Ally, immutable binding, onboarding attempt, and one provisioning operation.
- Authenticated Workspace-scoped create and retrieve APIs; separate idempotency-key digest and content fingerprint.
- Versioned Foundry profile-provisioning contract: typed request/receipt schemas, one checked JSON fixture, one shared service bearer, and a narrow HTTP function.
- AuthFlow-style opaque, expiring, single-use DB onboarding attempt associated with the Ally after authentication, retaining the bounded final seed plus the current greeting/reply for the downstream conversation handoff.
- Bounded scheduled cleanup of expired, unconsumed onboarding attempts; consumed handoffs remain attached to their Ally.
- Existing Celery worker and beat dispatch/retry using lease, attempt, next-attempt, and expiry fields on `ProvisioningOperation`.
- Focused model, service, API, contract, and PostgreSQL concurrency tests; migration and rollout documentation.

### Out of Scope

- Waitlist lookup, claim, import, or reconciliation; creation before authentication; anonymous Workspace or Foundry profile.
- Signed onboarding-token issuer/audience/key/nonce protocol, separate handoff receipt model, or second handoff contract representation.
- `ProvisioningOutbox`, retry service/schema/route, gateway class, mTLS configuration, new dispatcher or feature-flag framework, synthetic canaries.
- Post-creation editing/deletion, team Workspaces, frontend layout, product Ally limits, and ongoing conversation/streaming lifecycle.
- Cloud/Foundry shared models, databases, queues, provider references, credentials, raw provider output, or runtime addresses.

### Dependencies and Assumptions

- AUTH-001 supplies session and Workspace capability helpers. The onboarding attempt follows its opaque-record, digest, expiry, and row-lock conventions.
- Existing worker and beat run on the `cloud` queue; a due-operation task and sweep extend that mechanism.
- Foundry exposes the agreed private endpoint with one shared service bearer. Cloud stores only allowlisted receipt fields. A matching Foundry Workspace identified by the opaque Cloud Workspace correlation already exists.
- Typed schemas plus one checked fixture are the authoritative Foundry contract representation and are checked in both repositories.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `backend/allies/services/onboarding.py` | `begin_onboarding` | `begin_onboarding(*, payload, browser_binding, generation_identity) -> OnboardingStart` | Bounded final seed, trusted browser binding, existing greeting generation admission and output checks. | Opaque attempt token and server-authored greeting. | Stores one expiring attempt with token/browser digests and bounded handoff content; raw token is never stored or logged. |
| `backend/allies/services/onboarding.py` | `cleanup_expired_onboarding_attempts` | `cleanup_expired_onboarding_attempts(*, now, limit) -> int` | Bounded batch of expired attempts that were never consumed. | Deleted-row count. | Existing Celery/beat runtime purges abandoned seed/greeting text; consumed handoffs are retained. |
| `backend/allies/services/creation.py` | `create_ally` | `create_ally(*, user, workspace_id, payload, idempotency_key, onboarding_attempt, browser_binding) -> AllyCreationResult` | Capability; locked opaque attempt expiry and browser binding; final values must match the attempt; nonblank reply; separate key digest and fingerprint. | Stable public Ally, operation ID, derived state. | Transaction creates/replays Ally, binding, operation, associates the attempt, and retains the reply. Same key/fingerprint replays; changed fingerprint conflicts; invalid/expired/consumed attempt rejects. Schedules normal dispatch after commit. |
| `backend/allies/services/creation.py` | `retrieve_ally` | `retrieve_ally(*, user, workspace_id, ally_id) -> Ally` | Workspace-scoped capability and Ally lookup. | Allowlisted fields plus state derived from binding and operation. | Uses `select_related("workspace", "binding", "binding__provisioning_operation")`; denied and absent resources are indistinguishable. |
| `backend/allies/gateways/foundry.py` | `provision_profile` | `provision_profile(request: ProfileProvisioningRequest) -> ProfileProvisioningReceipt` | Typed versioned binding, operation, fingerprint, job, and personality; no appearance or end-user credential. | Typed allowlisted receipt. | Existing service bearer to Foundry private HTTP endpoint; timeout/429/5xx retryable; malformed, incompatible, or unauthenticated replies fail closed and are redacted. |
| `backend/allies/services/provisioning.py` | `dispatch_due_provisioning` | `dispatch_due_provisioning(*, now, limit) -> DispatchReport` | Claim due operations with `select_for_update(skip_locked=True)`, lease, bounded attempts, and expiry. | Redacted counts/outcomes. | The wrapper in `backend/allies/tasks.py` lets existing Celery worker/beat call `provision_profile`; lease expiry recovers crashes; operation identity tolerates duplicates; expiry becomes repair-required. |

### API and Transport Contracts

| Consumer | Method and path | Authentication and authorization | Request schema | Success response schema | Error responses / retry semantics |
| --- | --- | --- | --- | --- | --- |
| Web client | `POST /api/v1/onboarding/attempts` | Trusted origin and CSRF-bound browser; no account or production record required. | `OnboardingAttemptRequest` with final seed fields. | `200 OnboardingAttemptResponse` with opaque token and server-authored greeting. | Bounded generation/admission failures are structured; no waitlist row is read or written. |
| Web client | `POST /api/v1/workspaces/{workspace_id}/allies` | Authenticated session and existing Workspace write capability; denial is 404. | `CreateAllyRequest`, `Idempotency-Key`, opaque onboarding attempt, and reply; final seed must match the attempt. | `201` settled; `202` pending, retryable, or repair-required. | Same key/fingerprint replays; changed content is `409`; invalid/expired/consumed attempt is `422`; client retries only by repeating this request with the same key. |
| Web client | `GET /api/v1/workspaces/{workspace_id}/allies/{ally_id}` | Authenticated session and existing Workspace read capability. | None. | `200 AllyResponse`. | `401` invalid session; `404` unavailable or denied. |
| Cloud service | `POST /api/v1/internal/profile-provisioning` | Shared service bearer; no end-user credential. | `ProfileProvisioningRequest` with opaque Cloud Workspace/binding/Ally/operation identities and exact behavioral seed. | `ProfileProvisioningReceipt` echoing only Cloud identities, status, and evidence digest. | `401/403`, unknown version, identity mismatch, malformed receipt fail closed; `408/429/5xx` retry automatically. Foundry resolves Workspace by opaque tenant correlation and derives its private profile identity without returning it. |

```json
{
  "name": "Mira",
  "job": "Study partner",
  "personality": "Calm, curious, and specific.",
  "appearance": {"catalog_version": "v1", "key": "sunrise"},
  "onboarding_attempt": "opaque-onboarding-attempt",
  "reply": "Help me map out tomorrow's study block."
}
```

`ProfileProvisioningRequest` and `ProfileProvisioningReceipt` are typed schemas in `backend/allies/gateways/foundry.py`. Their one authoritative checked example is `docs/contracts/foundry-profile-provisioning-v1.json`; neither repository keeps a second Markdown schema or ticket-named contract file.

### Schema and Data Shapes

| Model / schema | Location | Fields | Invariants and migration notes |
| --- | --- | --- | --- |
| `Ally` | `backend/allies/models.py` | public ID, Workspace, seed fields, timestamps | Bounded seed fields; no persisted lifecycle state; public state derives elsewhere. |
| `AllyBinding` | `backend/allies/models.py` | Ally one-to-one, immutable Cloud binding ID, version, binding status, receipt digest | Binding ID unique and immutable; store no provider reference unless reconciliation proves it necessary. |
| `OnboardingAttempt` | `backend/allies/models.py` | opaque value digest, browser binding digest, bounded final seed fields, greeting, nullable reply/user/Ally, expiry, consumption | Lock before consume; verify browser and final values; atomically retain a nonblank reply and associate the authenticated user and Ally once; raw token is never stored and handoff text is never logged. |
| `ProvisioningOperation` | `backend/allies/models.py` | binding, tenant/user, key digest, fingerprint, status, attempts, next attempt, lease, expiry, safe error/receipt digest | Unique `(workspace, user, api_idempotency_key_digest)`; due-operation index; no outbox table. |
| `AllyResponse` | `backend/allies/api/schemas.py` | public seed fields, derived provisioning state, operation ID, retry metadata | No provider IDs, credentials, raw receipt, or handoff receipt. |

### Frontend Interaction Shapes (if applicable)

Cloud does not implement layout. The client retains final values through authentication, repeats the original create request with the same `Idempotency-Key` only when it retries, and retrieves the same Ally on reconnect. No waitlist record is queried.

## Phases

### Phase 1 - Durable Cloud records

- Goal: add durable ownership and concurrency state before external I/O.
- Work items: create `allies`; add Ally, immutable binding, AuthFlow-style onboarding attempt, and provisioning operation; add constraints/indexes and an additive domain-named migration.
- Exit criteria: binding, operation identity, attempt expiry/consume, and state-derivation tests pass; `make check` has no migration drift.

### Phase 2 - Authenticated create and retrieve

- Goal: issue one official attempt, then create or replay one tenant-safe Ally while retaining its preview exchange.
- Work items: add onboarding/create/retrieve schemas and controllers; generate the official greeting without a waitlist row; require Workspace capability; lock/consume/associate attempt with its reply; purge abandoned expired attempts in bounded batches; use `select_related`.
- Exit criteria: `201/202`, replay/conflict, cross-Workspace 404, abandonment cleanup, and no waitlist import/query tests pass.

### Phase 3 - Foundry provisioning and recovery

- Goal: call one typed Foundry HTTP contract and recover transient work through existing Celery.
- Work items: implement `provision_profile()` with the existing bearer; add typed mapping and checked fixture; add task/beat sweep that leases due operations and applies bounded backoff; coordinate matching Foundry endpoint/fixture check.
- Exit criteria: fixture passes in both repos; bound, pending, retryable, incompatible, malformed, and expired outcomes are truthful and private-data-safe.

### Phase 4 - Focused release

- Goal: release the smallest proven vertical slice.
- Work items: run focused tests and repository checks; deploy Foundry contract, migrate Cloud, enable route.
- Exit criteria: all checks pass and rollback leaves durable rows intact.

## Acceptance Criteria

1. One onboarding route serves new and prior preview visitors with no historical waitlist lookup, claim, import, or reconciliation.
2. Fields remain editable before authenticated creation; the onboarding attempt is expiring and single-use.
3. Expired, unconsumed attempts are purged in bounded batches; consumed handoff content remains attached to its Ally.
4. One durable Workspace Ally and immutable binding result; public state derives from binding/operation, not a synchronized Ally lifecycle field.
5. Same key/fingerprint replays; changed content returns `409` without mutation; concurrent creates yield one Ally, binding, and operation.
6. Repeating original create with the same key is the only client retry path; worker/beat retry transient provisioning automatically.
7. Cloud settles success only with allowlisted Foundry evidence; other outcomes are structured and truthful.
8. Tenant denial is non-enumerable; public and diagnostic data excludes provider/private details and preview text.
9. Typed schemas and the one checked JSON fixture prove Foundry compatibility.

## Backend Considerations

### Query Optimization Plan

- Follow existing `select_related("workspace", "user")` membership lookup and retrieve with `select_related("workspace", "binding", "binding__provisioning_operation")`.
- Use short row locks for attempt consumption and operation claims; due-operation sweeps use indexed fields and bounded batches.
- Do not add query-count assertions or N+1 machinery without a measured regression; this scope has no list endpoint.

### Detailed Unit Test Cases

- Model/service: immutable binding, idempotency/fingerprint, attempt expiry/single-use and abandoned-attempt cleanup, operation lease/expiry, derived state.
- Service/API: authenticated create, replay/conflict, invalid/replayed attempt, tenant-safe 404, retrieve, and original-request retry.
- Contract: fixture, bearer failure, timeout mapping, malformed receipt, and redacted logs.
- PostgreSQL: simultaneous same-key create and duplicate due-operation claims converge on one durable identity.

## Test Plan

- Focused tests: `make test APP=allies` covering model, service, API, contract, task, and PostgreSQL concurrency cases.
- Repository checks: `make check`, `make lint`, and `make test APP=allies`.
- Migration check: `make migrations APP=allies MIGRATION_NAME=ally_initial`, then `make check`.
- Contract check: run Cloud and Foundry tests against `docs/contracts/foundry-profile-provisioning-v1.json`.

## Risks and Mitigations

- Duplicate creates/claims: DB uniqueness, short locks, leases, immutable identity, concurrency tests; disable route without deleting rows.
- Timeout after materialization: remain pending/retryable from the operation; settle only on matching evidence; pause dispatch without deleting rows.
- Contract drift: typed schemas plus one fixture checked in both repos; do not enable route until it passes.
- Data leakage: allowlisted schemas/redacted errors; disable route/dispatch while preserving safe evidence.

## Rollout and Fallback

1. Deploy and verify the Foundry private contract with existing service bearer and checked fixture.
2. Deploy the additive Cloud migration and worker/beat support.
3. Enable the create route after focused Cloud and contract checks pass.

Disable the route and/or dispatch on failure; retain Ally, binding, attempt, and operation rows so recovery resumes from the authoritative operation.

## Revision Summary

- Replaced signed handoff token/receipt design with an AuthFlow-style opaque onboarding attempt.
- Removed outbox, retry surface, gateway class, mTLS option, provider reference, synchronized lifecycle state, query-count guards, and speculative rollout gates.
- Kept required tenancy, idempotency, lease/retry, contract, privacy, and concurrency protections using existing patterns.
