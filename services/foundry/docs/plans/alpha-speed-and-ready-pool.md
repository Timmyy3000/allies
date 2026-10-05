# Alpha speed and ready-workspace pool

**Status:** Implemented and reviewed; local services plus real Fly proof completed. Production enablement remains off.  
**Planning route:** Full  
**HTML companion:** No. The change is primarily lifecycle, transport, and concurrency work; the Markdown contracts and test matrices are the review surface.  
**Repositories:** Allies Cloud, Allies Foundry, Allies Interface (web)  
**Prerequisite branches:** Cloud PR 30 at `77bda208`; Foundry PR 32 at `c589591`; Interface work starts from current `web/ft/finishing-touches` at `650fc1d` and targets that branch while its prerequisite remains open.

## Feature Overview

Alpha onboarding is slow for four separate reasons: Cloud can wait for a scheduled retry after Foundry has already materialized a profile; an awake runtime can take up to the idle polling backoff to discover a new profile; a stopped runtime is not woken until after the Ally has been created; and cold Fly provisioning spends substantial time preparing an image and release before Hermes can answer. This plan removes the avoidable waits while keeping the existing durable provisioning state machine as the source of truth.

It also proves a default-off ready-workspace pool with two complete Fly bundles in one test region. Each bundle contains an app, a blank mounted volume, a Machine, staged credentials, and a healthy runtime. Assignment permanently transfers a whole bundle to one new Cloud workspace. Assigned or previously used bundles are never returned to the pool.

The work preserves the one-way Interface → Cloud → Foundry → runtime dependency direction, Cloud product authority, Foundry runtime authority, generation fencing, one-volume/one-writer rules, service authentication, lease ownership, deterministic provider resource identity, and the normal cold-provisioning fallback.

The current seven-run baseline is:

| Scenario | Materialized | Cloud confirmed | First reply complete |
| --- | ---: | ---: | ---: |
| Cold | 119.88 s | 165.65 s | 184.13 s |
| Awake | — | — | 20.41 / 8.11 / 11.81 s |
| Asleep | 15.53 / 15.22 / 16.22 s | 40.62 / 16.02 / 45.26 s | 57.20 / 25.97 / 59.70 s |

The cold run spent 66.328 seconds preparing the Hermes image. The deployed image measured 3.96 GB. The Allies wrapper contributes only a few megabytes, so deleting files in a later wrapper layer would not reduce the inherited transfer size. This plan measures phase spans and optimizes a narrow bootstrap-helper shutdown path; it does not remove inherited Hermes capabilities without a separately proven rebuilt image.

The practical healthy-path targets are:

- accepted readiness receipt to Cloud confirmation: at most 2 seconds;
- queued execution to runtime claim: 1–2 seconds for a healthy awake runtime;
- desired profile to materialization: at most 2 seconds for a healthy awake runtime, including when the profile is created just after maximum idle begins and no web hint was sent;
- no permanent one-second HTTP or database polling while idle.

These are alpha load targets for matched local and Fly runs, not production service-level guarantees.

## User Stories

- As a user finishing Ally creation, I want the workspace to begin waking while I type the first meaningful name so that setup overlaps with the rest of onboarding.
- As a user whose runtime is already awake, I want it to notice a desired profile promptly without making every idle workspace poll continuously.
- As a user whose profile is already ready in Foundry, I want Cloud to confirm it promptly instead of waiting for an unrelated scheduled retry.
- As a user receiving one of the proof pool bundles, I want the same isolation, credentials, generation checks, and durable provisioning behavior as normal cold creation.
- As an operator, I want every speed hint to be optional for correctness, bounded in cost, safe under duplicates and restarts, and observable by phase.
- As an operator, I want a failed, empty, stale, or disabled pool to fall back to normal workspace creation without blocking onboarding.

## Scope

### In scope

1. A dedicated Foundry-to-Cloud profile-readiness hint with bounded durable delivery. The hint advances the next check of an existing Cloud provisioning operation; it does not mark an Ally bound and does not reuse the execution-event outbox.
2. A bounded authenticated server-visible activity wait before an awake runtime would enter a long local idle sleep.
3. A workspace-scoped `ally_creation_started` intent emitted once on the first non-whitespace web name edit. Cloud authenticates the user, derives the workspace, deduplicates the intent, and asks Foundry to wake an existing stopped workspace.
4. Low-cardinality phase instrumentation across Cloud provisioning, Foundry lifecycle and profile reconciliation, and the retained benchmark harness.
5. A measured optimization of Foundry's unused Fly bootstrap helper: use a direct sleep entrypoint and a short, bounded termination path only if current Fly configuration and controlled runs prove the phase is faster without weakening staged-release validation or cleanup ownership.
6. A default-off ready-workspace pool proof with exactly two complete unassigned bundles in one test region, atomic permanent assignment, capped maintenance, stale-bundle eviction, replenishment, normal fallback, and real Fly evidence.
7. Web validation of the complete path from first meaningful creation input through first rendered reply, alongside API, concurrency, restart, and lifecycle tests.

### Out of scope

- Enabling a pool in production, selecting production capacity or regions, or making an availability commitment.
- Reusing, scrubbing, or returning an assigned workspace bundle to the pool.
- A pool of bare apps, unattached volumes, or Machines that would require attaching a new volume after creation.
- Removing Hermes tools, model support, caches, packages, or inherited image layers without a rebuilt-image transfer and capability proof.
- Adding a new scheduler, queue system, perpetual per-workspace timer, or unbounded background task.
- Replacing Cloud's provisioning operation, Foundry's runtime receipt, activation receipt, execution claim lease, or generation fencing with a hint.
- Sending draft Ally names, jobs, prompts, or other user content in wake or readiness signals.
- Editing native onboarding in this stack. The Cloud contract remains transport-neutral, and native must adopt the same first-meaningful-input rule before its onboarding branch is released.

### Dependencies and branch strategy

Cloud PR 30 and Foundry PR 32 remain unchanged prerequisites. New branches stack on their exact heads while they are open, then retarget to the repository default branch after the prerequisites merge. The Interface change starts from the current `web/ft/finishing-touches` head (`650fc1d`) and targets that branch until its open prerequisite merges. The stale root Interface checkout is not an implementation base.

Delivery order is deliberately asymmetric:

1. Cloud accepts readiness hints and the workspace-scoped creation intent while retaining all old behavior.
2. Foundry emits readiness hints and understands the creation intent; older Cloud behavior remains correct because hint delivery is optional.
3. Interface emits the web creation intent; failure is invisible to the creation flow.
4. Foundry instrumentation and the bootstrap-helper experiment land independently.
5. Pool state and atomic assignment land default off.
6. Pool maintenance and the real-Fly proof land on top of the pool assignment work.

The pool work must not merge partially enabled. Schema, assignment invariants, fallback, maintenance cleanup, and proof validation all land before any non-test target is configured above zero.

## Contract and Shape Definitions

### Function and Service Shapes

| Repository/location | Proposed symbol | Contract |
| --- | --- | --- |
| Foundry `runtime.services.profiles` | `accept_materialization_receipt(...)` | Atomically accepts the current receipt and inserts its idempotent hint delivery; publication begins only after commit. |
| Foundry `runtime.services.provisioning_hints` | `publish_due_profile_readiness_hints(*, limit, now) -> PublishResult` | Short leased claims, bounded attempts/backoff, separate from execution-event delivery. |
| Cloud `allies.services.provisioning` | `accept_profile_readiness_hint(payload, now) -> HintResult` | Locks the current operation, records a monotonic hint, advances only due time, preserves live leases. |
| Cloud `allies.services.runtime_intents` | `request_workspace_runtime_intent(*, principal, intent, idempotency_key, occurred_at) -> RuntimeIntentResult` | Derives the workspace, checks auth/gates/rate limit, and forwards the key as `Idempotency-Key` with `received_at` in the Foundry body. |
| Foundry `runtime.services.runtime_intents` | `request_runtime_intent(workspace_id, intent, idempotency_key, received_at) -> RuntimeIntentReceipt` | Extends the existing service to `ally_creation_started`; activation claims remain authoritative. |
| Foundry `runtime.services.workspaces` | `assign_or_register_workspace(tenant_ref) -> Workspace` | Exact tenant first; atomically claim one eligible bundle or execute current cold registration. |
| Foundry `runtime.services.ready_pool` | `maintain_ready_pool_once(*, now) -> MaintenanceResult` | Bounded target reconciliation, one claimed external phase at a time, resumable owned cleanup. |
| Interface web Ally flow | `requestCreationWake(): Promise<void>` | Send once on first committed non-whitespace name edit; timeout/abort never changes onboarding state. |

### API and Transport Contracts

| Consumer | Method and path | Auth | Request / success | Retry and compatibility |
| --- | --- | --- | --- | --- |
| Foundry → Cloud | `POST /api/v1/internal/foundry/profile-readiness-hints` | Existing Foundry service auth | Versioned hint below / `202 {"status":"accepted"}` | Same `hint_id` is idempotent; stale/terminal valid hints are accepted no-ops; bounded sender retry. |
| Interface → Cloud | `POST /api/v1/onboarding/runtime-intents` | Existing browser/native principal; browser CSRF/origin checks | `{version,intent,occurred_at}` / `202 SuccessResponse({status:"waking"})` | `Idempotency-Key` required; existing status vocabulary; one best-effort browser attempt. |
| Cloud → Foundry | `POST /api/v1/control/workspaces/{workspace_id}/runtime-intents` | Existing Cloud control auth | `Idempotency-Key` header plus `{intent,received_at}` / existing runtime-intent receipt | Additive enum after receiver deploy; Cloud maps timeouts to `failed`. |
| Runtime → Foundry | `POST /api/v1/runtime/activity-waits` | Runtime bearer bound to internal workspace ID | `{after_revision,wait_seconds}` / `{revision,reason}` | Additive, side-effect-free bounded wait; claim IDs and claim leases are unchanged. |

Representative creation response and Cloud-to-Foundry forwarding payload are:

```json
{"success":true,"message":"Runtime intent accepted","data":{"status":"waking"}}
```

```json
{"intent":"ally_creation_started","received_at":"2026-09-07T12:00:00Z"}
```

### Schema and Data Shapes

| Schema/model | Repository | Required shape and invariants | Compatibility |
| --- | --- | --- | --- |
| `ProvisioningHintDelivery` | Foundry runtime | Routing/receipt IDs, generation, state, attempt/lease/due fields; no content; logical receipt uniqueness. | Additive table; sender flag off. |
| Provisioning hint marker | Cloud provisioning operation | Nullable `readiness_hint_received_at`; monotonic and lease aware. | Nullable migration; no hint history/dedupe table; old scheduler remains correct. |
| `Workspace.activity_revision` | Foundry workspace | Non-negative monotonic integer advanced with a transactional PostgreSQL notification. | Additive column and activity-wait endpoint; old runtimes retain current polling. |
| `ally_creation_started` | Cloud/Foundry request enums | Content-free, workspace scoped, existing status vocabulary. | Receiver before sender; existing composing intent unchanged. |
| `ReadyWorkspaceBundle` | Foundry workspaces | One-to-one workspace, state/region/release/config, phase lease, attempts, readiness/health/expiry/assignment, safe error. | Additive table; target zero is off. |

### Frontend Interaction Shapes

| UI entry point | State | API mapping | Failure behavior |
| --- | --- | --- | --- |
| `NameAllyScreen` `ally-name-input` | Local per-flow `idle → sending → sent`; composition and remount guarded | First non-whitespace committed edit → content-free creation intent; response used only for telemetry | One attempt; timeout, abort, disabled, rate limit, or server error leaves preview/create flow unchanged. |

### Identity and ownership contract

`Workspace.id` is Foundry's immutable internal identity. Provider app names, Machine ownership metadata, runtime credentials, runtime bearer authentication, and generation state derive from it. `Workspace.tenant_ref` is the Cloud workspace reference used to find the Foundry record.

A pool bundle is built around a normal Foundry `Workspace` with an internal ID and a reserved, non-Cloud tenant reference. Assignment changes only `tenant_ref` to the authenticated Cloud workspace UUID inside the same database transaction that marks the bundle assigned. It does not change `Workspace.id`, provider resource references, ownership metadata, credentials, or generation, and it does not restart the Machine. This prevents a nominally warm assignment from becoming a credential rotation or cold restart.

Unassigned workspaces are inaccessible from Cloud lookups, have no Ally profiles, executions, prompts, or user data, and cannot be selected for activation outside pool maintenance. A pool readiness state means that the base runtime is healthy; it never means that a future user's Ally profile is already materialized.

### Profile-readiness hint

Foundry inserts a separate `ProvisioningHintDelivery` in the same database transaction that accepts a current-generation runtime profile materialization receipt. Receipt identity is the delivery's dedupe key. The transaction commits both rows or neither; network publication starts only after commit through a dedicated supervised one-second hint publisher. The materialization request never performs Cloud HTTP in an on-commit callback; the durable publisher scan supplies prompt delivery and crash recovery. The delivery row contains routing and idempotency metadata only:

```json
{
  "version": 1,
  "hint_id": "<hint-uuid>",
  "workspace_id": "<workspace-uuid>",
  "ally_ref": "<ally-uuid>",
  "runtime_profile_id": "<profile-uuid>",
  "generation": 4,
  "receipt_id": "<receipt-uuid>",
  "occurred_at": "2026-09-07T12:00:00Z"
}
```

Foundry sends the document to the new authenticated Cloud internal endpoint `POST /api/v1/internal/foundry/profile-readiness-hints`. It reuses the established Foundry service-auth transport, redaction rules, bounded timeouts, and request correlation. A successful request returns `202` for both first delivery and duplicates. A valid but stale or terminal hint is acknowledged and recorded as ignored; an invalid identity or signature is rejected.

`ProvisioningHintDelivery` is not an execution event. Its state is `PENDING`, `DELIVERING`, `DELIVERED`, or `EXHAUSTED`, with a short claim lease, a capped attempt count, safe error codes, and bounded backoff. The existing supervised delivery command may publish a bounded number per loop, but hint rows, claims, and metrics stay separate from execution delivery. Exhaustion raises an observable counter and leaves Cloud's existing retry/recovery path intact.

Cloud resolves the authenticated workspace and Ally, then locks the current `ProvisioningOperation`. It records only a monotonic `readiness_hint_received_at` in the same transaction that updates `next_attempt_at`; it does not add a Cloud hint history or dedupe store. It schedules the existing due-provisioning task with `transaction.on_commit`; if the process exits after commit but before that callback, the existing periodic due-work scan observes the durable due time. Behavior by operation state is:

| State | Hint behavior |
| --- | --- |
| Pending or retryable | Set `next_attempt_at` to now and dispatch the existing due-provisioning task. |
| In progress with a live lease | Preserve the owner and lease. Record the hint. If that attempt defers after the recorded hint, its defer path makes the next attempt due now. |
| In progress with an expired lease | Let the existing recovery/claim path reclaim it, with the recorded hint making it due. |
| Confirmed or terminal | Acknowledge as an idempotent no-op. |
| Unknown workspace, Ally, or mismatched profile | Reject or acknowledge as stale according to the established service-contract taxonomy; never bind. |

The after-commit task plus the lease-aware defer rule is sufficient. The implementation must not enqueue recurring per-hint tasks. Cloud still confirms only after its existing Foundry reads validate current profile receipt, activation receipt, operation epoch, generation, and digest. A hint received before Machine readiness therefore causes a prompt recheck and remains pending rather than producing false readiness.

### Bounded runtime discovery

Foundry adds the monotonic `activity_revision` column directly to `Workspace`. Creating or changing a desired runtime profile and committing a queued execution both advance it and issue the same transactional notification. The early creation intent remains useful for starting a stopped Machine, but prompt discovery by an already-running runtime does not depend on that web hint.

Before the runtime would enter an idle sleep longer than one second, it calls the new side-effect-free `POST /api/v1/runtime/activity-waits` with its last observed revision and a requested wait of at most five seconds. The PostgreSQL implementation subscribes to a workspace-scoped notification channel before reading the durable revision, then waits through the existing psycopg driver. Profile change or execution enqueue increments the revision and calls `pg_notify` in the same database transaction, so the notification is delivered only with committed work. A final revision read after notification or timeout closes subscribe and timeout races. The endpoint returns `200 {"revision":12,"reason":"changed"}` or `200 {"revision":11,"reason":"timeout"}`. A changed response forces immediate profile reconciliation followed by claim and resets idle backoff. A timeout waits a randomized 100–250 ms for waiter fairness, then starts the next claim/wait cycle without the former 10-second local sleep. Runtime cancellation returns control to the worker; because the urllib request runs in a thread, the server wait may live until its five-second bound and must close its listen connection in `finally`. Transport/service errors retain the existing jittered error backoff. Execution claim IDs, ambiguous-claim recovery, claim leases, generation fences, and active execution slots are unchanged.

Activity wait defaults off. Candidate and proof Foundry run with `WEB_THREADS=16` and at most eight waiters per Gunicorn worker process, validated to reserve at least eight ordinary request threads. The proof is capped at eight connected runtime workspaces in total, including unassigned reserve Machines. Each waiter holds for at most five seconds, and a PostgreSQL advisory lock rejects a second wait for the same workspace. Full capacity returns `429` and records saturation; the runtime follows existing error backoff, preserving correctness if acceleration is unavailable. At configured full occupancy each worker completes at most 1.6 timed-out waits per second, with two indexed revision reads per wait and no periodic database probe. The runtime urllib timeout is set above the wait plus request margin. This uses existing PostgreSQL, psycopg, HTTP, and runtime authentication and adds no service or package. Larger populations and non-PostgreSQL setups retain correctness through current polling but are outside this alpha latency claim.

### Early Ally-creation intent

The web calls a new workspace-scoped Cloud endpoint on the first non-whitespace edit of the Ally name input. It does not call on drawer open, route entry, focus, empty input, whitespace-only input, preview, or unrelated navigation. Composition events are respected, React remounts do not duplicate the logical intent, and no draft text leaves the browser.

Representative request:

```http
POST /api/v1/onboarding/runtime-intents
Idempotency-Key: <idempotency-uuid>
Content-Type: application/json

{
  "version": 1,
  "intent": "ally_creation_started",
  "occurred_at": "2026-09-07T12:00:00Z"
}
```

Cloud authenticates the current user, derives the user's workspace, applies existing session/CSRF/origin rules, enforces per-user and per-workspace limits, and deduplicates within a short TTL. It never accepts a browser-supplied workspace or Ally ID for this operation. The response reuses the existing `RuntimeIntentStatus` vocabulary: `disabled`, `already_ready`, `waking`, `ready`, `first_provision_required`, `rate_limited`, or `failed`. A duplicate returns the current safe status without starting a second activation.

Cloud forwards a service-authenticated, workspace-scoped `ally_creation_started` intent to Foundry. Foundry finds the workspace by tenant reference, applies global and workspace gates, and starts its existing Machine only when it is stopped and already provisioned. Concurrent intents use the existing activation claim/lease so there is one start attempt. A workspace that has never been provisioned returns `first_provision_required`; creation later follows the durable cold path. A running workspace returns its existing ready status; the independent activity-wait contract handles later profile discovery.

The browser call is one best-effort attempt. It has a short timeout, performs no automatic retry, does not block name entry or onboarding, and does not change `beginOnboarding`, preview generation, or `createAlly` ordering. The existing Ally-scoped `composing_started` intent remains unchanged for established Allies.

The Cloud request shape deliberately has no web-only fields and uses the normal authenticated principal abstraction. No native caller changes are part of this branch because current native onboarding is on a separate release-gated line. Native must adopt the same first-meaningful-input trigger and automated contract tests before that onboarding line is released.

### Ready-workspace pool data model

Add a one-to-one `ReadyWorkspaceBundle` associated with a Foundry `Workspace`:

```text
id: UUID
workspace_id: UUID, unique FK
state: PREPARING | READY | ASSIGNED | EVICTING | EVICTED | FAILED
region: bounded string
release_fingerprint: bounded string
config_version: positive integer
attempt_count: non-negative integer, database-capped
next_attempt_at: timestamp
phase_claim_owner / phase_claim_until: nullable bounded lease
ready_at / expires_at / last_health_at: nullable timestamps
assigned_at: nullable timestamp
safe_error_code: nullable bounded string
created_at / updated_at: timestamps
```

Database constraints and service checks enforce:

- only `READY` rows can become `ASSIGNED`;
- `ASSIGNED` is terminal for pool use and always has `assigned_at`;
- `READY` has complete provider references, current release/config fingerprints, runtime readiness, a future expiry, and fresh health evidence;
- attempts cannot exceed the configured cap;
- unassigned pool workspaces have a reserved tenant-reference namespace and no runtime profiles or executions;
- eviction and deletion are allowed only for unassigned bundles;
- a provider resource is always owned by the immutable internal workspace ID.

`READY_WORKSPACE_POOL_TARGET=0` is the pool's single off gate. The proof sets it to two with one explicit test region, at most one extra preparing row, a finite readiness TTL, a health-freshness threshold, and at most five attempts per failed phase. Configuration validation rejects a positive target without the region, cap, TTL, and release fingerprint.

### Pool preparation and maintenance

The one-shot `maintain_ready_workspace_pool` command runs one bounded control-plane pass. The existing external scheduler invokes it for repair and replenishment; the proof harness invokes it explicitly between proof steps. The command has no internal watch loop or per-workspace timer. Each pass:

1. Count fresh `READY` bundles for the configured region and release.
2. Resume one expired or available phase claim before creating more rows.
3. Create at most the bounded deficit and never exceed target plus the preparing allowance.
4. Use the existing lifecycle in order: app, blank volume, Machine with that volume attached, start, health, runtime credential/readiness, then `READY`.
5. Stage dependencies and runtime credentials before Machine boot. Preserve the one active Machine and one writer for the volume.
6. Mark expired, unhealthy, missing, wrong-release, or metadata-mismatched unassigned bundles `EVICTING` and clean only their owned Machine, volume, app, and credentials with resumable phases.
7. Leave capped failures visible as `FAILED`; a later explicit repair pass may retry only within the configured bound.

External Fly calls occur outside long database transactions. A short claim protects each phase, and every result is revalidated under a row lock before state advances. Cleanup addresses recorded provider IDs and verifies ownership metadata; it does not discover and delete by a broad name pattern.

An assignment immediately creates a capacity deficit because its row remains permanently `ASSIGNED`. The assignment transaction records the state change; the next maintenance pass replenishes from the observed target deficit. The periodic repair pass supplies restart recovery. No extra durable queue is required for correctness.

### Atomic assignment

`register_workspace(tenant_ref)` keeps its exact-tenant lookup first. If that returns an existing workspace, registration is idempotent and does not inspect the pool.

If no workspace exists and the pool target is positive, registration opens a transaction and selects one eligible `READY` bundle using row locks and `skip_locked`, locks its workspace, and rechecks all invariants. It then changes the reserved `tenant_ref` to the Cloud workspace UUID and changes the bundle state to `ASSIGNED`. The uniqueness constraint on `Workspace.tenant_ref`, bundle row lock, and retry of the exact-tenant lookup make concurrent calls safe.

If no bundle is eligible, or a candidate fails any recheck, registration creates a fresh workspace through the current code path. A stale candidate is moved toward eviction outside the assignment's critical path. Pool failure never converts a successful cold registration into an error.

PostgreSQL concurrency tests must prove that:

- two simultaneous registrations for the same tenant return one workspace and consume at most one bundle;
- two tenants cannot receive the same bundle;
- two available bundles can be assigned concurrently;
- process failure before commit leaves the bundle `READY`, while failure after commit leaves it `ASSIGNED` and idempotently discoverable by tenant;
- an assigned row can never transition back to `READY`, including after Cloud cancellation or activation failure.

After assignment, Cloud creates the actual Ally and desired profile normally. Foundry keeps the internal workspace ID and current runtime credential, so the running Machine can materialize the profile without a restart. The normal Cloud operation and Foundry receipt contracts establish user-visible readiness.

### Observability and benchmark contract

Add structured, low-cardinality spans or elapsed-time events for:

- Cloud: creation intent accepted/outcome, Ally created, provisioning operation claimed, each external status read, readiness hint received, hint-to-next-attempt, confirmed, execution queued;
- Foundry: dependency credential preparation, runtime credential preparation, staged release/bootstrap, app, volume, Machine create/start, Machine health, runtime readiness, desired-profile revision, activity-wait duration/outcome/saturation, reconciliation, materialization receipt commit, hint delivery, execution claim;
- runtime and harness: first Hermes HTTP-ready observation, first token, completed reply, and browser render when available;
- pool: phase duration, target/ready/preparing/failed counts, assignment result, fallback, eviction reason, cleanup result, and replenishment time.

Events use internal correlation IDs, phases, state enums, generation numbers, attempt counts, and durations. They do not log credentials, auth headers, prompts, Ally names, customer identifiers, provider secrets, or raw error bodies.

The retained harness runs matched revisions and configuration against the same topology. It records raw timestamps and derived durations for cold, cached-image cold, awake, asleep, and pool-assigned cases; first token and completion remain distinct. Every candidate comparison includes commit IDs, image fingerprint, feature flags, region, run count, and median plus individual samples. It must not hardcode auth subjects, commits, ports, application IDs, or credentials.

### Bootstrap-helper optimization gate

Foundry currently creates a short-lived release/bootstrap Machine with a shell command that sleeps, then stops it after staging validation. Recorded shutdown spent roughly six seconds between initial interruption and exit. The implementation may replace the shell wrapper with a direct sleep entrypoint and an explicit short, bounded termination signal/timeout for this unused helper only.

Before changing the path, the implementer must verify the current Fly Machine configuration accepts the direct entrypoint and termination settings, and add a focused configuration test. Controlled runs must show that:

- staged release metadata and secret validation are unchanged;
- only the recorded helper Machine ID is stopped;
- timeout fallback still cleans up a stuck helper;
- the measured bootstrap phase is shorter across repeated runs;
- the application Machine, Hermes init path, tools, models, and credentials-before-boot sequence are unchanged.

If the platform does not support the exact configuration or the repeated phase measurements do not improve, retain the existing helper behavior and land the instrumentation without claiming a cold-start win. Image slimming requires rebuilding or flattening the inherited owner image and a complete capability/transfer proof; it is not substituted into this packet.

## Phases

### Phase 0 — freeze baselines and benchmark inputs

**Deliverables**

- Record exact prerequisite heads, current Hermes image fingerprint, feature settings, and the seven-run baseline in the retained benchmark artifact.
- Parameterize the harness for auth subject, revisions, endpoints, database, provider resources, and feature flags; load secrets from the environment.
- Add phase correlation IDs before behavioral optimization so before/after runs use the same markers.

**Exit criteria**

- One retained cold, awake, and asleep control run can be reproduced without source edits.
- The harness fails closed when a required revision or image fingerprint is missing.

### Phase 1 — readiness hint and targeted Cloud reconciliation

**Foundry work**

- Add the separate delivery model, migration, bounded claim/delivery service, settings, and metrics.
- Insert the deduplicated delivery in the same transaction as the current materialization receipt; start publication only after commit and retain the durable publisher scan.
- Publish through the existing supervised loop without sharing execution-delivery rows or retry state.

**Cloud work**

- Add the authenticated internal endpoint and schema.
- Store the monotonic hint marker on the current provisioning operation.
- Make pending/retryable work due immediately; preserve live leases; make a post-hint defer due immediately.
- Dispatch the existing task only after the due-time transaction commits; reuse periodic due-work recovery for an after-commit crash.
- Reuse the existing status/receipt validation and periodic recovery.

**Exit criteria**

- Duplicate, stale-generation, early-before-readiness, lost, exhausted, live-lease, expired-lease, restart, terminal-state, receipt/delivery commit-crash, and Cloud due-update/task-dispatch crash tests pass.
- A healthy materialization-receipt commit reaches Cloud confirmation within two seconds in matched local tests; endpoint acceptance alone does not satisfy the metric.
- Turning either side's flag off restores the current scheduled path.

### Phase 2 — bounded awake discovery

**Deliverables**

- Persist the workspace-activity revision; advance and transactionally notify for desired-profile changes and queued executions.
- Add the authenticated five-second activity-wait endpoint using PostgreSQL notifications, durable revision race checks, the validated candidate/proof `WEB_THREADS=16` and eight-waiter-per-process caps, per-workspace exclusion, and guaranteed connection cleanup.
- Replace only successful long local idle sleeps with the bounded wait; preserve cancellation behavior, error backoff, ambiguous claims, leases, slots, and generation fences.
- Add wait duration/outcome/saturation, ordinary-endpoint latency, and notification-to-reconcile/claim metrics.

**Exit criteria**

- A desired profile committed just after maximum idle begins reaches materialization within two seconds without any web creation hint.
- An execution queued just after the wait begins is claimed within two seconds.
- With two unassigned and two assigned runtimes waiting, profile writes, receipts, health, and ordinary APIs remain responsive; configured saturation leaves at least eight of sixteen request threads per worker available.
- Notification, subscribe/commit, timeout, API-process restart, waiter cancellation, and non-PostgreSQL fallback tests are bounded and leak no connections.
- Generation changes during a wait still discard stale materialization and execution work.

### Phase 3 — early web creation wake

**Cloud and Foundry work**

- Add the workspace-scoped, content-free creation intent with auth, gate, dedupe, TTL, rate limit, metrics, and activation-claim reuse.
- Ensure first provision, running, stopped, starting, and disabled outcomes are explicit and safe.

**Interface work**

- Emit one intent from `NameAllyScreen` on first non-whitespace committed edit.
- Keep it best effort and separate from onboarding state transitions.
- Cover IME composition, Strict Mode/remount, empty input, timeout, and route cancellation; assert no automatic retry.

**Exit criteria**

- Drawer open and empty/focus events produce no request.
- No user text appears in the request or telemetry.
- A stopped existing workspace starts during the remaining onboarding steps, while a never-provisioned workspace follows the normal cold path.
- Failure, timeout, or feature-off behavior never prevents preview or `createAlly`.

### Phase 4 — cold-path measurement and safe bootstrap improvement

**Deliverables**

- Add the defined lifecycle spans and benchmark extraction.
- Implement the direct bootstrap-helper entrypoint and bounded termination only after the platform/config test succeeds.
- Run repeated current-versus-candidate cold tests with the same image state, then cached-image tests.
- Document that wrapper-layer deletion cannot shrink inherited layers and retain all Hermes capabilities.

**Exit criteria**

- The retained report identifies image preparation, bootstrap/release, provider creation, health, profile materialization, Cloud confirmation, first token, and completion separately.
- Any claimed bootstrap win is repeatable and does not change provider ownership, credential order, or application runtime behavior.
- An unsupported or neutral candidate is omitted without blocking the other speed work.

### Phase 5 — pool state and atomic assignment, default off

**Deliverables**

- Add the bundle model, constraints, migration, validated settings, assignment service, and exact-tenant-first integration in `register_workspace`.
- Preserve immutable internal workspace identity through assignment.
- Add PostgreSQL concurrency, crash-boundary, idempotency, stale-candidate, and feature-off fallback tests.

**Exit criteria**

- Target zero uses the current registration path at the service boundary.
- All concurrency invariants pass on PostgreSQL.
- No assigned bundle can be selected, evicted, or returned to ready state.

### Phase 6 — pool preparation, repair, and real-Fly proof

**Deliverables**

- Add bounded lifecycle preparation, phase claims, health/release validation, resumable eviction, cleanup, target reconciliation, and the externally scheduled one-shot maintenance command.
- Prepare exactly two complete real Fly bundles in one test region using proof-only settings.
- Concurrently assign them to two fresh test workspaces, create actual Allies/profiles, produce first replies, observe automatic deficit replenishment, reject/evict one stale test bundle, and demonstrate empty-pool cold fallback.
- Retain sanitized timestamps, state transitions, resource-count evidence, and cleanup outcomes outside the public repository.

**Exit criteria**

- Both assignments are unique and permanent; neither Machine restarts solely to change tenant reference or credentials.
- Each volume was attached at Machine creation and has one writer.
- Unassigned capacity is unreachable through Cloud and contains no profiles, executions, or user data.
- Replenishment and repair obey the target, concurrency, attempt, TTL, and region caps.
- Assigned proof bundles are never recycled. After evidence collection their compute may be stopped under normal workspace lifecycle; remaining unassigned proof resources are removed by owned-ID cleanup.
- The checked-in configuration remains disabled with target zero.

### Phase 7 — integrated validation and rollout packet

**Deliverables**

- Run all repository checks and focused cross-repository tests.
- Repeat cold, cached, awake, asleep, and pool scenarios with matched revisions and report both first-token and completion results.
- Complete browser verification through first rendered reply for the web flow.
- Produce a feature-flag matrix, rollback order, sanitized operator runbook, and evidence index.

**Exit criteria**

- No correctness test depends on a hint arriving.
- Feature-off runs match the prerequisite behavior.
- The pool cannot be enabled accidentally by default or through an incomplete setting set.
- All accepted reviews are resolved before implementation PRs are marked ready.

## Implementation ownership and non-overlap

Workers use the saved `luna_execution_worker` selector at maximum reasoning and receive bounded packets. They do not commit, push, or widen their file sets unless the integration owner reassigns a conflict.

| Packet | Primary ownership | Excluded ownership | Dependency |
| --- | --- | --- | --- |
| Foundry readiness/discovery | Runtime profile and hint models/migration; profile/receipt and hint services; runtime claim/reconcile schemas/client; focused tests | Workspace registration, pool services, Fly bootstrap/image files | Foundry PR 32 |
| Cloud speed control | Provisioning-operation hint fields/migration; provisioning service/tasks; Foundry gateway; internal hint endpoint; workspace creation-intent endpoint; tests/settings | Interface UI; Foundry models | Cloud PR 30; contract coordinated with Foundry readiness |
| Interface creation wake | Cloud client schema/client; web runtime-intent hook; `NameAllyScreen` integration and tests | Native packages; onboarding ordering; Cloud backend | Interface prerequisite at `650fc1d`; Cloud endpoint contract |
| Foundry cold measurement | Lifecycle/activation instrumentation; bootstrap-helper configuration; focused tests and public runbook | Workspace/profile schema, registration, pool state | Foundry PR 32; may proceed in parallel |
| Foundry pool state | Bundle model/migration/settings; assignment service; `register_workspace` integration; PostgreSQL tests | Lifecycle maintenance command and real-Fly proof | Foundry readiness migration order fixed first |
| Foundry pool runtime | Pool maintenance/eviction service and command; proof harness/runbook; Fly lifecycle tests | Assignment semantics and earlier migrations | Pool-state packet; cold packet integrated first if files overlap |

The integration owner owns migration ordering, shared API schemas, conflict resolution, cross-repository benchmark runs, and PR descriptions. Each packet receives a focused correctness review and simplicity review; the complete stack receives an adversarial review before the real-Fly proof.

Suggested PR stack:

1. Foundry readiness/discovery → Foundry PR 32 branch.
2. Cloud speed control → Cloud PR 30 branch, with the Foundry contract linked.
3. Interface creation wake → current `web/ft/finishing-touches` prerequisite.
4. Foundry cold instrumentation/bootstrap → Foundry PR 32 branch; keep disjoint from item 1 where possible.
5. Foundry pool state/assignment → item 1 after migration order is fixed.
6. Foundry pool runtime/proof → item 5 after item 4 is integrated.

If a prerequisite merges during implementation, retarget without rebasing away the reviewed prerequisite behavior. Cross-repository rollout keeps receivers compatible before senders and keeps every new feature flag disabled until its counterpart is deployed.

## Acceptance Criteria

- Foundry's current-generation materialization receipt creates at most one logical readiness hint, and delivery is separately durable, authenticated, bounded, and content free.
- Cloud handles duplicate, stale, early, lost, lease-racing, exhausted, and post-restart hints without false confirmation or lease theft.
- Cloud's normal scheduled provisioning retry remains sufficient when hints are disabled or lost.
- A healthy awake runtime uses the bounded server-visible activity wait before any long local idle sleep; profile and execution commits wake it within two seconds without depending on a web hint.
- The web sends one content-free workspace intent on first non-whitespace name input and never sends on open, focus, empty input, or unrelated navigation.
- The creation wake is authenticated, deduplicated, TTL/rate limited, cost gated, and unable to block Ally creation.
- Phase evidence identifies the actual cold bottleneck before a performance claim is made.
- Bootstrap-helper optimization lands only with repeated improvement and unchanged staged-release/credential/ownership behavior.
- Pool assignment changes only the Cloud tenant reference and pool state; the immutable Foundry workspace ID, provider identity, runtime credential, generation, and attached volume remain stable.
- Two complete pool bundles can be assigned concurrently to two fresh workspaces exactly once and can create real profiles and replies without a pool-induced Machine restart.
- Pool maintenance is target bounded, one-region bounded, retry capped, health/release checked, restart safe, and capable of stale eviction and replenishment.
- Used or assigned capacity is never recycled; unassigned capacity is not reachable from Cloud and never holds user data.
- An empty, stale, failed, or disabled pool falls back to normal provisioning.
- Checked-in defaults keep the pool and every optional speed sender disabled until explicitly coordinated.
- Matched candidate runs report cold, cached, awake, asleep, and pool results with individual samples, medians, first token, completion, and browser render where available.

## Backend Considerations

### Transactions, leases, and races

- Use short `transaction.atomic` blocks and `select_for_update` for provisioning-operation hint updates and pool assignment.
- Do not hold database locks during Fly or cross-service HTTP calls.
- Preserve live provisioning, activation, execution, hint-delivery, and pool-phase leases. A hint changes due-time evidence; it does not seize work.
- Compare operation epoch, workspace generation, profile receipt/digest, and release fingerprint after external calls before committing state.
- Use uniqueness constraints for tenant references, one bundle per workspace, and logical hint identity. Treat `IntegrityError` as a reason to reread the winner, not create another resource.
- Use database time where existing lease services do so; keep clocks out of uniqueness or ownership decisions.

### Query Optimization Plan

- Resolve a readiness hint in a bounded set of indexed workspace, Ally/profile, and current-operation queries; do not scan historical operations or event rows.
- Add indexes for pending hint deliveries by state/due time and pool maintenance by state/region/release/due time.
- Fetch bundle and workspace in one assignment query and assert profile/execution absence with indexed existence checks.
- Bound every publisher/maintenance pass by batch size and time. Export counters for backlog, oldest due age, activity-wait outcomes/saturation, and pool state counts.
- Keep serialized API responses free of lazy per-row lookups; use `select_related`/`prefetch_related` only for the exact bounded batch.

### N+1 Prevention

Hint publishing and pool maintenance operate on bounded indexed batches with the needed workspace/bundle relations selected up front. Endpoint serializers return fixed receipts and must not traverse delivery history, provider resources, profiles, or executions per row. Focused query-count tests cover a full publisher batch and a pool maintenance batch.

### Detailed Unit Test Cases

The repository sections of the Test Plan enumerate successful requests, invalid inputs, authorization checks, repeated requests, retries, lease races, stale generations, rollback, restart recovery, caps, fallback, and terminal assignment. Concurrency cases run on PostgreSQL; provider failures use strict fakes plus the bounded real-Fly proof.

### Security and isolation

- Reuse established service authentication and TLS for internal calls. Browser calls use current session/native-principal authentication, CSRF/origin defenses, and permission checks.
- Derive workspace identity server-side for the browser intent. Validate every Foundry/Cloud UUID and cross-check Ally/profile ownership.
- Never include prompt text, names, credentials, auth tokens, private provider references, or raw exception bodies in signals or logs.
- Keep unassigned pool tenant references in a reserved namespace rejected by Cloud-facing operations.
- Verify recorded Fly ownership metadata before mutation or deletion; never operate on a resource owned by another internal workspace ID.

### Compatibility and migrations

- Additive request/response changes are versioned. The activity-wait endpoint is optional; older runtimes retain current claims and polling.
- New nullable timing/revision fields default to old behavior. Pool rows are absent and target is zero after migration.
- Migrations contain schema and deterministic constraint setup only; no provider calls or bulk pool construction.
- Each migration has a backwards-compatible deploy interval with the older sender/receiver and an explicit rollback note.

## Frontend Considerations

### Data Path

`HomeWorkspace` already mounts the authenticated Ally-flow provider for the new-Ally route, and `NameAllyScreen` contains the first editable `ally-name-input`. Add the intent at that input boundary so the trigger represents demonstrated creation intent while leaving onboarding state and `createAlly` unchanged.

The hook owns a per-flow idempotency key and a sent/in-flight guard. It commits after IME composition ends and the normalized value has a non-whitespace character. It makes one request and does not surface failure to the user. Abort outstanding work on unmount.

The client models the explicit safe outcome vocabulary and records only intent type, outcome, and duration. UI rendering, validation, focus, animation, and navigation are unchanged. Automated tests verify there is no request body field capable of carrying the draft name.

Browser verification covers: open the new-Ally flow, focus without typing, enter whitespace, enter the first meaningful character, finish the existing preview/create path, and observe the first reply. Network evidence should show exactly one content-free creation intent and the later normal Ally/profile requests.

### State Management Considerations

The per-flow hook owns the idempotency key, in-flight request, and sent guard; Ally-flow state remains the source of truth for creation. The wake result is not cached product state and does not invalidate onboarding data. The server owns cross-tab dedupe, workspace rate limits, and activation concurrency.

## Test Plan

### Foundry focused tests

- Materialization receipt and its one logical hint delivery commit atomically; rollback creates neither, and a process exit after commit leaves a publishable row.
- Duplicate receipt processing and worker restart do not create duplicate logical deliveries.
- Hint publisher claim expiry, retry, exhaustion, timeout, redaction, and auth behavior.
- Activity wait subscribe/commit and timeout races, profile and execution notifications, five-second bound, advisory-lock exclusion, one-per-worker capacity, `finally` cleanup, cancellation, saturation, and preserved error backoff.
- Max-idle race: commit a desired profile immediately after the runtime begins its former maximum idle period and assert materialization within two seconds with creation hints disabled.
- Queue race: commit an execution immediately after activity wait begins and assert claim within two seconds.
- Waiter-contention test: connect two unassigned reserve runtimes and two assigned runtimes, then assert desired-profile writes, receipts, health, and ordinary APIs remain responsive; separately saturate the configured cap and verify safe fallback.
- Stale generation/profile receipt cannot emit an effective Cloud transition.
- Creation intent states: missing workspace, first provision, running, stopped, already starting, disabled, duplicate, rate-limited, and activation-claim race.
- Bundle state and database constraints; exact-tenant idempotency; wrong release/region/health; profile/execution absence; assignment terminality.
- PostgreSQL parallel assignment and process-boundary tests.
- Maintenance phase resumption, caps, stale eviction, owned cleanup, missing provider resources, transient Fly failure, and target reconciliation.
- Bootstrap-helper config, owned-ID stop, timeout fallback, and lifecycle regression.

Run focused modules during each packet, then:

```bash
make check
make validate
make lint
make test APP=runtime
make runtime-test
make hermes-image-test
```

Run `make hermes-image-build` only when the owner image or wrapper build inputs change. The planned helper configuration should not trigger an unrelated image rebuild.

### Cloud focused tests

- Service-auth hint validation and workspace/Ally/profile mismatch rejection.
- Pending, retryable, live-lease, expired-lease, confirmed, terminal, duplicate, stale-generation, and restart behavior.
- Hint-aware defer preserves the live owner and makes the next attempt due once.
- A crash before hint transaction commit persists neither due marker nor task; a crash after commit but before `on_commit` dispatch is recovered by the periodic due-work scan.
- Existing periodic dispatch confirms readiness after lost/exhausted hints.
- Workspace-scoped browser/native-principal auth, server-derived workspace, CSRF/origin, dedupe TTL, limits, flags, timeout, and safe outcome mapping.
- Existing provisioning operation and execution generation/lease tests remain green.

Use the prepared dedicated PostgreSQL test instance through environment configuration; do not embed its credentials in tests or documentation. Run:

```bash
make check
make lint
make test APP=allies
```

Also run the repository's full pytest and PostgreSQL concurrency markers used in CI before marking the Cloud packet ready.

### Interface focused tests

- No call on mount, drawer open, focus, empty input, whitespace-only input, or unrelated route.
- One call after first non-whitespace committed edit, including IME composition.
- Strict Mode/remount reuses the logical idempotency key and does not duplicate the intent; transport failure triggers no automatic retry.
- Timeout/abort/disabled/error outcomes do not block preview, `beginOnboarding`, or `createAlly`.
- Request contains no name or other draft content.

Run the focused Vitest modules, then:

```bash
bun run test:run
bun run typecheck
bun run lint
bun run build:web
bun run cloud:check
```

Run the repository's Playwright path for new-Ally onboarding through first rendered reply.

### Cross-repository and adverse-path matrix

| Scenario | Required evidence |
| --- | --- |
| Hint lost or exhausted | Periodic Cloud path eventually confirms; no stuck lease. |
| Hint during live attempt | Owner/lease unchanged; one immediate due recheck after defer. |
| Hint before Machine readiness | No false bound; later readiness confirms through existing receipts. |
| Duplicate/stale generation | Idempotent no-op; current generation remains authoritative. |
| Profile committed just after maximum idle begins | Transactional notification wakes the bounded activity wait; materialization completes within two seconds without web hint. |
| Execution queued during activity wait | The same revision/notification wakes claim within two seconds. |
| Runtime/API restart during wait | Wait ends within the transport/server bound; durable revision and normal claim/reconcile recover. |
| Wake duplication/start race | One activation owner; safe duplicate outcome. |
| Pool double assignment | Database concurrency test proves unique terminal assignment. |
| Pool stale release/unhealthy Machine | Candidate skipped, evicted by owned IDs, normal fallback succeeds. |
| Pool maintainer restart | Expired phase claim resumes within caps; no extra resources above allowance. |
| Pool empty/disabled | Existing cold lifecycle unchanged. |
| Candidate performance | Same revisions, image, region, flags, and topology as control; raw samples retained. |

### Real-Fly proof topology

Use a local Cloud and Foundry control plane backed by dedicated PostgreSQL databases and a real Fly test region. Keep provider resource names, application IDs, credentials, auth subjects, and private endpoints in environment configuration and the private evidence bundle. The checked-in runbook describes variables and commands generically.

The proof sequence is: establish cold and cached controls; create two blank complete bundles; verify both healthy and inaccessible from Cloud; atomically assign them to two fresh test workspaces under concurrency; create and materialize one Ally per workspace; record first token and completion; observe a replacement deficit; inject one stale/unhealthy unassigned candidate and verify eviction; exhaust the ready pool and verify cold fallback; then perform owned-resource cleanup without returning assigned workspaces to ready.

## Rollout, fallback, and rollback

Each acceleration path defaults off. Enable receiver compatibility first, then a small sender cohort, and compare error/backlog/load metrics before widening. The pool has only the target gate and remains proof-only at target zero in checked-in and production configuration.

Fallback order:

1. Disable the Interface creation-intent sender. Normal Ally creation remains.
2. Disable Foundry activity-wait and creation-wake handling. Current activation and idle polling remain.
3. Disable Foundry hint sending, or Cloud targeted scheduling. Periodic Cloud reconciliation remains.
4. Disable the bootstrap-helper candidate and restore its prior entrypoint/termination settings.
5. Set the pool target to zero and disable assignment. Existing assigned workspaces remain ordinary permanent workspaces; unassigned rows are drained with owned cleanup. Normal new registration remains.

Rollback must not reverse an assignment, rotate its credentials merely to restore old code, detach or move its volume, or delete assigned provider resources. Additive columns/tables remain through the safe deploy interval even if code paths are disabled. Database removal is a later cleanup only after all old/new binaries and retained rows are accounted for.

## Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| A readiness hint becomes a second correctness system | Hint only changes due-time evidence; existing receipt/status checks and periodic recovery remain authoritative. |
| A hint steals a live lease or is overwritten by defer | Persist the monotonic marker, preserve live owner/lease, and make a post-hint defer due immediately. |
| Server-visible waits consume request threads or database connections | Default off; candidate/proof use sixteen threads and at most eight waiters per worker, five-second bound, per-workspace advisory lock, `finally` cleanup, saturation tests, and at least eight ordinary threads reserved. |
| A notification is missed around subscribe or commit | Subscribe before the first revision read, emit `pg_notify` transactionally with the revision, and reread after wake/timeout; the durable revision remains the fallback. |
| Creation wake leaks drafts or is triggered casually | Workspace-scoped content-free payload, server-derived identity, first non-whitespace edit, no open/focus trigger. |
| Wake costs grow through duplicate clients | TTL/idempotency, user/workspace limits, feature gates, activation lease, one browser attempt, and server dedupe across remounts/tabs. |
| Pool assignment breaks deterministic credentials | Keep immutable Foundry `Workspace.id`; change only `tenant_ref` and bundle state; assert Machine env has no tenant identity requiring restart. |
| An unassigned bundle becomes user-visible or contains user data | Reserved tenant namespace, no profile/execution rows, Cloud lookup isolation, assertions at readiness and assignment. |
| A used bundle returns to the pool | Terminal `ASSIGNED` transition enforced in model, database constraints, services, tests, and cleanup policy. |
| Provider calls under locks block registration | Only database selection/assignment is transactional; health is prevalidated and external maintenance runs outside locks. |
| Stale pool capacity serves an old release | Fingerprint/config/health/expiry eligibility checks, recheck under lock, eviction, and cold fallback. |
| Maintainer leaks resources on restart | Phase leases, recorded provider IDs, capped target/preparing counts, idempotent lifecycle phases, owned cleanup. |
| Image cleanup removes Hermes capabilities without shrinking transfer | Do not delete inherited files in wrapper layers; require rebuilt-image transfer and capability evidence for future image work. |
| Bootstrap change is unsupported or saves nothing | Gate on current platform configuration tests and repeated phase measurements; retain instrumentation and old behavior if neutral. |
| Cross-repository branches drift while prerequisites are open | Pin exact heads, stack receivers before senders, retarget after merge, and run integrated tests on the final combined revisions. |
| Public documentation exposes private proof infrastructure | Keep credentials, app/resource IDs, private endpoints, and raw logs in the local evidence bundle; use generic contracts here. |

## Decisions, assumptions, and review questions

### Decisions made by this plan

- Use a separate readiness-hint delivery type rather than fabricating an execution event.
- Preserve provisioning and activation leases; hints make durable work due but do not claim it.
- Use a workspace-scoped creation intent because no Ally exists at first name entry.
- Trigger on the first non-whitespace committed edit and send no draft content.
- Preserve Foundry's internal workspace ID through pool assignment; only the Cloud tenant reference changes.
- Pool complete app + mounted volume + Machine + credential + healthy-runtime bundles. Do not attach a volume after Machine creation.
- Make assignment permanent and prohibit recycling even after later onboarding failure.
- Keep the pool disabled with target zero outside the explicit proof.
- Measure cold phases and attempt only the narrow bootstrap-helper shutdown optimization in this stack.
- Implement the web caller now; keep the Cloud contract transport-neutral and make native adoption a release criterion for the separate native onboarding line.

### Assumptions to verify during implementation

- The runtime Machine environment and Hermes bootstrap do not embed `tenant_ref`; current code inspection shows authentication and ownership bind to internal `Workspace.id` and generation. Add a regression test before pool proof.
- The current Fly Machine configuration supports a direct sleep entrypoint and bounded termination for the helper. Verify against current platform behavior before changing it.
- PostgreSQL notifications are available in deployed Foundry; non-PostgreSQL development runs retain existing polling and are excluded from the two-second activity-wait target.
- Existing internal service-auth clients can add the readiness endpoint without broad gateway changes.
- The supervised delivery loop can process a small bounded hint batch without delaying execution-event delivery; prove with backlog/latency tests and split the command loop if it cannot.

### Material review questions

Both implementation checks are resolved: hints use a separate bounded publisher process, and the matched helper proof passed all six runs with a repeatable shutdown reduction. See [benchmark results](../operations/alpha-speed-benchmark-results.md) for measurements, outliers, pool assignment/replenishment/drain proof, and remaining runtime limitations. The original checks were:

1. Whether the existing supervised publisher can maintain separate fair budgets for execution events and hints. If not, run a second supervised process using the same bounded delivery service; do not merge the row types.
2. Whether Fly's direct-entrypoint termination removes a repeatable portion of the measured bootstrap phase. If it does not, land measurement only and make no speed claim for that subphase.

These questions affect implementation shape or whether a narrow optional optimization lands. They do not reopen the authorized four priorities, the two-bundle proof, the identity/lease safeguards, or the permanent-assignment rule.
