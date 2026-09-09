# FND-012 routine conversations plan

Status: revised once against Sol's ADV-001..005 and SIM-001..003 findings; implementation is proceeding against the accepted CLD-012 routines-v1 revision-14 implementation-facing compatibility candidate and contract-independent runtime groundwork. Revisions 7 through 9 remain preserved historical baselines, with revision 9 the last coordinated downstream consumer baseline. Revision 14 is not released traffic: explicit paired Cloud-first acceptance/order and the deferred interfaces and capability gates below still block routine release. Route: full. HTML required: no. The earlier review record describes the original draft; dispositions at the end of this plan govern this revision.

## Feature Overview

Execute each routine in a fresh conversation using its Ally's existing profile, memory, files, and authorized tools. Main chat and different routines must run concurrently. One routine retains exclusive execution ownership through working, approval waiting, and effective cancellation. Deliver a truthful, attributed outcome to main chat for every terminal run.

### Evidence inspected

Repository baseline: `e8285f9211b50cb9cbda05bad2ff07446ff6b44b` on `ft/fnd-012-routine-conversations`. Read `episode-state.md`, `AGENTS.md`, `ENGINEERING_STYLE.md`, `docs/templates/PLAN_TEMPLATE.md`, README, Makefile, both package/test configurations, `.github/workflows/ci.yml`, and `scripts/validate.py`. No nested AGENTS.md was found.

Read the accepted Nabu routines specification and FND-012 ticket after the knowledge-space index. They require the management tool bridge as well as execution, approval continuation, and concurrency. The manager subsequently accepted the CLD-012 routines-v1 revision-14 successor as the current implementation-facing compatibility candidate, preserving revisions 7 through 9 as historical and revision 9 as the last coordinated downstream consumer baseline. Revision 14 is not released traffic and remains gated on explicit paired Cloud-first acceptance/order; the Class A/Class B limitations remain. Its older backlog wording does not override that release or this planning request. No Nabu mutation is needed because the canonical ticket already records the successor handoff.

Verified exact SHA-256 values against the preparation and lock:

| Artifact | SHA-256 |
| --- | --- |
| `docs/contracts/routines-v1.md` | `f05ab0a1baf63551f426c288f0144484c813b5cda535bf1cf5d614fb7a22ea84` |
| `docs/contracts/fixtures/routines-v1.json` | `2660d30ee73e8f3cebf94340ea1169019e3c937fd01a30bff6d0e16ecd54ab35` |
| `docs/contracts/routines-v1.lock.json` | `9005d25a8186d325a2efdcc42ec9e6cfe4d2d6c445088c9ba7a6b4d87429cb04` |

Read the supplied CLD-012 `docs/operations/routine-session-feasibility.md` in its preparation worktree. Hermes source is pinned to `36cb5ae5530a75def7df3195e49b7a4aa2add482`. Class A had one distinct-session `mnemosyne_remember` failure and two passes against image prefix `sha256:4127ae957bc3d`; concurrent writes remain inconclusive. Class B is setup-blocked, with no verified final image digest or real overlapping-session proof. The cited probe and launcher are absent from this Foundry baseline; bringing reviewed copies into this worktree is an implementation step, not an available command today. The episode's `roadmap/routines-handoffs/FND-012.md` is also absent here; this plan uses the episode, canonical ticket, and directly inspected seams without inventing its contents.

| Current seam | Finding and implication |
| --- | --- |
| `backend/runtime/models.py`, `services/executions.py`, `services/sessions.py` | `ConversationBinding.profile` is the primary-key OneToOne; command admission and session CAS resolve by profile. Keep this protection for main chat and add a routine-specific session record. |
| `services/claims.py`, `services/leases.py` | Active/stopping leases are unique per profile; claims skip any occupied profile. Replace that exclusion with explicit execution scope, preserving attempt/token/machine checks. |
| `services/attempts.py`, `services/events.py`, `services/event_delivery.py` | Atomic terminal/event/outbox writes, exact receipts, event budgets, bounded delivery and repair already exist. Extend them; do not create another delivery system. Retryable failure and stopped/expired-lease paths can requeue and need routine-specific guards. |
| `runtime/allies_runtime/foundry.py`, `hermes.py` | The production worker already uses bounded concurrent tasks and stable profile+conversation session identifiers. It lacks a routine approval continuation path. Hermes normalization rejects events outside its existing allowlist. |
| `runtime/allies_runtime/coordinator.py`, `worker.py` | Coordinator is a profile-serialized proof helper; `worker.py` only reexports the real worker. Do not mistake either for the production concurrency bottleneck. |
| `runtime/hermes-image/provider/allies_mnemosyne/provider.py` | Initialization has a global environment lock; delegated memory operations and shutdown have no shared operation guard. Preserve its profile validation, allowlist, retention filters, quotas, and fail-soft behavior. |
| `backend/runtime/api/register.py`, `contracts.py`, `api/schemas.py` | Existing Cloud service authentication and runtime bearer+lease authentication are reusable. Existing execution DTOs use different scope/producer shapes from routines-v1; routine DTOs must be separate. |
| `backend/runtime/default_allies_soul.md` | Hermes owns dangerous-action enforcement. Routine approval plumbing must retain that enforcement. No complete FND-010 cancellation implementation was found in the inspected baseline. |

## User Stories

1. A user receives a main-chat reply while their Ally runs scheduled work in a separate conversation.
2. A routine uses its complete saved prompt and shared authorized resources without inheriting another conversation's transcript.
3. A user approves or rejects one waiting action in main chat; expiry and replacement prevent stale permission from acting.
4. The Ally reports saved management changes and terminal results honestly, including unchanged checks and failures.

## Scope

### In Scope

Proceed now with validators for exact released fixture shapes, durable routine execution/session groundwork, scoped lease authority, internal approval/action state invariants, authenticated Foundry adapters for the current revision-14 implementation-facing dispatch/approval/cancel command envelopes, the smallest demonstrated memory-operation fix, and focused PostgreSQL and runtime evidence preparation. Foundry's transport responsibility includes accepting the exact revision-14 candidate Cloud commands and emitting/reconciling authoritatively published `routine.result`, `routine.approval_requested` and other events through the existing outbox. Revision-14 remains compatibility validation only until paired Cloud-first release acceptance; Cloud scheduling, management persistence, and model-visible insertion remain Cloud-owned integration work.

### Out of Scope

Cloud scheduling/discovery implementation, Foundry main-history append/marker mechanisms, UI, push, event triggers, run inspection, automatic transcript copying, automatic terminal whole-task reruns, a new memory provider, a general workflow engine, profile-wide execution serialization, and new user-facing quotas. Never edit the three normative artifacts independently or add wire fields to fill interface gaps.

### Dependencies and Assumptions

CLD-013 owns scheduler admission, owner authorization, management persistence, and main-chat insertion. FND-012 owns the Foundry-side authenticated adapters for the already released `routine.dispatch`, `routine.approval_decision`, and `routine.cancel_wait` envelopes, plus the existing runtime event outbox. Cloud insertion remains a Cloud integration dependency, never a Foundry append mechanism. The Cloud adapter must use the route map selected below without adding wire fields. These interfaces, both implementations, the capability gate and real Class B evidence are explicit release gates. Existing slot limits remain capacity controls, not a new product cadence restriction. Configure at least three slots for the main+two-routine acceptance proof.

The designs below are local implementation choices, not amendments to Cloud's contract. Reconcile the actual FND-010 stop service when it becomes available; preserve its effective-stop evidence rather than introducing a competing public cancel API. A stopped transport alone is not evidence that an external action stopped.

## Contract and Shape Definitions

### Function and Service Shapes

The service names below are the Foundry implementation seams. Expose only the three authenticated internal command routes selected in this revision; do not add a user-facing route or fabricate fields absent from the released tuple. Keep orchestration in small services and use the existing persistence and transport primitives.

| Location | Symbol/signature | Inputs and validation | Return / effects |
| --- | --- | --- | --- |
| `backend/runtime/routine_contracts.py` (new) | `validate_routine_command(value: dict) -> RoutineCommand` | Closed discriminated shapes, exact scope, strict IDs/integers, fingerprint, UTC deadlines, UTF-8 bounds | Validated command; safe error before writes |
| `backend/runtime/services/routines.py` (new) | `accept_routine_dispatch(command: RoutineDispatch) -> RoutineDispatchReceipt` | Authenticated Cloud scope maps to existing workspace/profile/main binding; immutable tuple and replay checks | Transaction stores execution, reserved attempt, run session, receipt and wake intent |
| same | `decide_routine_approval(command: RoutineApprovalDecision) -> RoutineApprovalReceipt` | Exact permission/action/run/attempt/generation, pending/unconsumed state, database time | Single CAS consumes permission, persists decision/action intent, or terminal outcome |
| same | `cancel_routine_wait(command: RoutineCancelWait) -> RoutineCancelReceipt` | Same scope and fence; replacement identity retained | Persist the existing fencing transition and return its bounded receipt (`code`, routine execution, fence, status, replayed) |
| same | `expire_routine_approvals(limit: int = 20) -> int` | Due pending approvals selected in bounded batches and rechecked after locking | Terminal expiry and outbox in one transaction |
| existing `services/sessions.py` | `update_session_binding(...) -> binding receipt` | Resolve target from authenticated attempt's execution; caller cannot select another run | Main binding path stays intact; routine path changes only its own session |
| `runtime/allies_runtime/routines.py` (new) | `resume_approved_action(claim, continuation) -> action receipt` | Durable action identity, current lease, fixed action digest and provider permission | Exact continuation, bounded reconciliation; never resubmit whole prompt |
| Deferred management integration | No adapter or transport signature selected | CLD-013 must publish authenticated context/confirmation and closed transport interfaces | Retain product acceptance requirements; implementation waits for the release gate |

### API and Transport Contracts

Reuse the existing `/api/v1` authentication and transport mechanisms. Foundry accepts the exact revision-14 candidate messages with `Authorization: Bearer ALLIES_CLOUD_SERVICE_TOKEN` through these internal routes: `POST /api/v1/internal/routines/dispatch` -> `RoutineDispatchReceipt`, `POST /api/v1/internal/routines/approval-decision` -> `RoutineApprovalReceipt`, and `POST /api/v1/internal/routines/cancel-wait` -> the existing `RoutineCancelReceipt` fields. All three reject unsupported kinds, unknown fields, invalid fingerprints, stale scope/generation, and conflicting replay identities through the existing safe error mapping. Existing `execution.command` and reconciliation remain unchanged. Cloud event ingestion remains `POST /api/v1/internal/foundry/events` on the Cloud side, with the existing direction-scoped event bearer and `202 {event_id,status}` receipt.

Use fixture JSON objects directly as representative request/response examples rather than rewriting their bytes:

| Boundary | Exact JSON examples in `docs/contracts/fixtures/routines-v1.json` | Behavior |
| --- | --- | --- |
| Dispatch and reconciliation | `dispatch.command`, `dispatch.receipt` | Same key/fingerprint returns original accepted receipt; acceptance is not completion. Reserve the returned attempt ID before replying. |
| Approval | `approval.requested`, `approval.decision`, `approval.receipt` | Foundry event, Cloud decision, Foundry durable CAS receipt; no provider call inside DB transaction |
| Replacement | `approval.cancel_wait` | Return the existing Foundry fencing receipt; effective cancellation fences the waiting run and retains `replacing_occurrence_id` |
| Results | `result.event`, `result.receipt` | Validate full scope, event identity and fingerprint; applied/pending insertion remains pending |
| Management bridge | `management.{create,update,pause,resume,delete}.request/receipt`, `management.{get,list}.request/response` | Preserve Cloud-owned authority, revision checks, saved semantics, default 50/max 100 pagination and owner/filter-bound opaque cursor |

Routine messages use `foundry-service`, matching the current Foundry implementation. Retain 60-second command lifetime, 16 KiB UTF-8 prompt/result text, 64 KiB event envelope, ordinary sequence maximum 100000 and reserved terminal sequence 100001. Validate byte counts before storage or dispatch; do not reuse the legacy 16000-character field restriction as the routine limit. Unknown fields and unsupported kinds fail closed. Canonical fingerprints exclude only fingerprint/issued_at/deadline_at and use sorted compact ASCII JSON with finite numbers. Retries refresh transport timestamps as needed without changing semantic identity or stored receipt identity.

Deferred management integration must preserve immediate creation for a complete user request, clarification for missing task/time/timezone, agreement before an Ally suggestion becomes a routine, recurring-only pause/resume, and exact conversational deletion confirmation tied to routine and expected revision. Model arguments cannot confer `cloud-service` authority. CLD-013's published interface must define trusted session context, owner/confirmation validation and replay identity. A pending/ambiguous receipt must not become a saved claim. The Foundry command adapters do not grant management authority; they accept only Cloud-authenticated released envelopes.

### Schema and Data Shapes

Prefer one routine execution extension and one approval/action record over changing the main binding's primary key or adding a second execution engine.

| Model / change | Fields and constraints | Migration / compatibility |
| --- | --- | --- |
| `RoutineExecution` (new, OneToOne to `Execution`) | Full immutable trusted scope; routine/revision/schedule generation, occurrence/run IDs, scheduled instant, delayed flag, main/run conversation UUIDs, title/prompt snapshot; effective Hermes session nullable; current attempt/fence; run status; dispatch receipt | Unique run ID, unique fresh run conversation, unique occurrence for transport admission, partial unique `(profile, routine_id)` for queued/working/approval_waiting. Explicit retries need the released linked-identity mapping before adding alternate cardinality. No copied scheduling model. |
| `Lease.scope_key` (new non-null bounded string) | `main` for existing executions; `routine:<routine UUID>` for routine work. Server derives it from persisted execution, never caller input. Unique `(profile, scope_key)` where state is active/stopping | Backfill all old rows as `main`; add replacement constraint before dropping profile-only unique constraint. Keep attempt OneToOne, token digest, expiry and machine-generation checks. |
| `RoutineLeaseAcquisition` (new) plus nullable `Lease.current_acquisition` FK | Acquisition UUID; immutable FK to the existing Lease; ordinal; unique claim_id/token_digest; machine generation; issued/retired timestamps; immutable claim response; session/stop/terminal request digests and receipts. Unique `(lease, ordinal)` | Retain exactly one Lease per Attempt. Each reacquisition appends an authority record and updates the same Lease's current pointer/token/expiry/state under locks. No second Lease insertion and no rewriting Attempt replay fields. New fields are internal, not routines-v1 wire fields. |
| Routine approval/action record (new) | UUID approval/action IDs; run/attempt FK; immutable fence/action digest/provider key; pending/authorizing/rejected/expired/cancelled permission status; consumed flag; created/expiry timestamps; nullable action state until authorization; durable bounded continuation reference and provider receipt; command receipts | One pending approval per run, unique action identity/provider key in its scope; action state limited to released vocabulary. Expiry indexed. Credentials are resolved at dispatch, never stored in continuation JSON. |
| Routine replay receipts | Dispatch receipt on run record; decision/cancel receipts keyed by scope+command replay key, canonical digest and exact response | Preserve competing command receipts separately; do not overwrite approval receipt with cancellation receipt. Use a small routine command receipt table if multiple commands cannot fit existing receipt fields safely. |
| `Execution` / `Attempt` / event paths | Routine-specific status handling and an explicit source discriminator. Add routine fence separate from existing machine generation; reserve queued attempt on acceptance | Keep legacy command constraint valid through explicit source-specific branches; do not fabricate a Cloud message ID/turn ordinal for a routine. Existing main callers keep original DTOs and semantics. |

Check all relation invariants under locks: run execution/profile/workspace agree; owner/Ally/binding scope agrees with dispatch; main binding is that profile's existing main chat; run, main and execution IDs are pairwise different. UUID possession is not authority. Resolve every conversation through its trusted workspace/profile and execution type, never by a bare reference across binding tables. Check same-workspace reference reuse under the workspace lock; retain each table's uniqueness constraints and reject attempts to target another scope. The workspace lock does not provide global cross-workspace exclusion.

`RoutineExecution.profile` is an explicit foreign key needed by its partial unique constraint; validate that it equals `execution.profile` on every admission. Store the prompt once in the immutable execution payload and refer to that snapshot from the extension. Run status is the authority for routine lifecycle; update the existing Execution/Attempt operational statuses in the same transaction, with explicit mappings for approval_waiting and expired. Add reconciliation tests for inconsistent legacy or malformed persisted values; do not silently infer permission from them.

#### Concurrency, lease and session design

1. Preserve the short workspace lock as the existing serialization point for claims and mutations. Within it, use one documented order: Workspace -> Profile -> Execution -> RoutineExecution -> Attempt -> Lease -> Approval -> Event/Receipt. Read IDs without locks only as hints, then recheck under locks. No network/model/file work runs while DB locks are held.
2. Main-chat claims still serialize on the profile's `main` scope. Routine claims serialize on profile+routine ID. The partial active-run constraint also prevents two queued/waiting runs even when no lease exists. Different routine IDs and main chat can obtain separate leases and worker slots.
3. Claims resolve conversation/session from the execution type. Main executions use the existing binding; routines use their own run conversation and nullable session. `stable_session_identifiers(profile_id, run_conversation_id)` provides retry stability and fresh occurrence separation. Preserve effective-session CAS and exact replay receipts; never rotate the main session when a routine finishes.
4. Dispatch acceptance reserves a queued attempt and initial routine fence so the fixture receipt can contain execution/attempt/generation immediately. Claim activation attaches current machine generation and creates the lease for that reserved attempt; it must not allocate another attempt on first claim. Wire routine generation is a persisted per-run fence, while runtime authentication separately checks the machine generation.
5. A confirmed approval pause persists the pending action/continuation and binding, retires the current `RoutineLeaseAcquisition`, marks the single Lease released and frees the worker slot. The run remains approval_waiting and occupies its routine's active-run slot. Reacquisition locks the existing Attempt and Lease, verifies suspension/quiescence, authorization and nonterminal run state, inserts a new acquisition with a fresh claim_id/token, then updates that same Lease to active with its new current pointer and expiry. Keep the same run/attempt identity for exact continuation; never create a second Lease for the Attempt. Acquisition IDs are internal and require no new wire field.
6. Approval arriving before runtime suspension is confirmed may consume permission, but cannot start a second consumer. Finish suspension or continue the original consumer under the same guarded action identity. Recovery after a process crash must prove a resumable checkpoint and quiescence; absent that evidence, report failure/manual reconciliation, never restart the prompt.
7. Effective cancellation invalidates permission, increments the internal run fence and retires lease authority atomically with terminal state and durable cancellation evidence. Keep the cancelled attempt's correlation in that evidence. Its outcome/fencing wire representation is deferred until CLD-013 publishes the closed interface; do not invent retired/current fence fields. New actions/projections require current authority. Delivery of an already committed valid terminal event remains valid after fencing; worker-originated late events do not.
8. Profile cleanup and machine shutdown still inspect all scopes. Never power down or delete shared profile resources while any sibling lease/action is live. A memory lock must not encompass a model turn, tool network call unrelated to memory, or whole Ally execution.

#### Approval, action and terminal invariants

For routine claims, `claims.py` resolves claim_id through `RoutineLeaseAcquisition` before the legacy `Attempt.claim_id` path. Store the initial acquisition there too; leave routine Attempt.claim_id unset and keep the legacy main path untouched. Exact replay returns the original acquisition's response only while it is current and live. Retired/expired acquisition replay returns the existing safe no-claim/fenced behavior, never a replacement token. Reusing a claim key for another scope or semantic request conflicts. Generate the token from the existing server-secret mechanism using the fresh acquisition claim identity; preserve its digest and original claim response.

Route routine session/stop/terminal idempotency through the acquisition selected by token digest; never clear or overwrite Attempt.session/stop/terminal replay fields to permit a second authority. Require `Lease.current_acquisition`, live lease state/expiry, workspace machine generation and run fence to agree before every mutation or action dispatch. A retired token may receive its exact stored receipt as a read-only replay where the existing endpoint permits it, but cannot renew, bind, complete, stop or authorize new work. Keep event sequence monotonic across acquisitions. Final terminal state makes the run non-reacquirable; another acquisition cannot emit a second terminal event. These rules apply to claims, leases, sessions, attempts and event services together.

Migrate only the new internal authority table/pointer; existing main attempts and receipts remain in place. Test two concurrent reacquisitions: one current acquisition wins, one receives conflict/replay, one Lease row remains, and neither contender overwrites history. Also cover crash after acquisition commit before response, stale initial claim replay after resume, stale session/stop/terminal tokens, and resume after machine-generation change. This is the chosen schema/service shape, not an alternative left to implementation.

Create expiry from the database clock after acquiring locks: `expires_at = created_at + 24h`. On PostgreSQL use a statement-time clock sampled after locks, not transaction-start time. Cloud `decided_at` is evidence only. At decision CAS, require pending, unconsumed permission, matching immutable tuple/action digest, current fence, approval_waiting and `database_now < expires_at`; equality expires. Persist decision, consumed permission, working status and `pre_dispatch` action in one transaction.

Approval wins before cancellation: return `APPROVAL_ALREADY_AUTHORIZING` to cancellation and let Cloud skip the new occurrence. Cancellation/rejection/expiry wins: permission is invalid and no action may dispatch. Replacement must wait for durable effective fencing, not a timeout or stop request. Rejection terminalizes as cancelled; expiry as expired. Main-chat outcome delivery is required for both.

Commit `dispatching` before the external effect. A lost response or crash after dispatch intent is `unknown` even if the send may not have occurred. Reconcile with at most three read-only status calls within 60 seconds. Only a verified provider same-key guarantee permits an effectful recovery call. Persist the provider completion receipt before continuing the paused run. Unresolved ambiguity reaches `manual_reconciliation` and a truthful terminal failed outcome; later evidence updates action evidence without reopening the terminal run. Exercise every fixture crash vector.

All routine terminal paths must write exactly one outcome and outbox intent atomically, including errors before a normal model completion, rejected/expired/cancelled waits, lost leases and unknown actions. Routine `fail(retryable=True)` cannot requeue terminal work. Existing stopped and expired-lease recovery may retry only demonstrably unstarted dispatch under the same identity; a dispatch/checkpoint/action record forbids whole-prompt replay. Preserve the legacy main execution behavior outside the routine branch.

#### Result and main-history contract

Normalize the terminal result into bounded text, changed/unchanged/failed outcome, allowed typed references and saved correlation. Preserve the saved title/revision and delayed flag; do not infer a changed outcome merely from nonempty assistant text. Runtime capability work must provide a typed result or return an explicit failure when malformed. Never copy the full run transcript, hidden notes, grants, secrets or run-inspection URL.

Append the event and existing `ExecutionEventDelivery` together with terminal state. Keep stable event ID and sequence on retry, check changed replay conflicts, preserve reserved terminal budget, and retain evidence needed for supported replay windows. Reuse delivery limits: batch 20, eight attempts per cycle, maximum backoff 300 seconds and three automatic repair cycles. Bounded HTTPS requests, no redirects with credentials, and receipt identity checks remain required.

Foundry only emits and reconciles released routine results/approval events and their published receipts. Cloud owns durable ingestion, turn-boundary insertion, the insertion watermark and model-visible history. An applied receipt with `result_insertion: pending` acknowledges ingestion only. Foundry does not append history, add markers or extend first-turn bootstrap for routine insertion. CLD-013 integration must prove that the attributed result enters actual main history once before the next turn, without changing an in-flight prompt; that proof is a release dependency. Missing insertion interfaces remain Cloud-owned deferred work. Deleting the routine does not remove an admitted run's result.

### Frontend Interaction Shapes (if applicable)

Not applicable to Foundry implementation. Cloud/Interface own running, result and approval presentation. Foundry supplies truthful typed states and correlation; no UI or run destination is added here.

## Phases

### Phase 1 - Contract adapters and executable capability checks

Create validators only for exact released fixture shapes without changing normative bytes. Add the three authenticated internal Foundry command adapters using those validators and the existing service seams; do not fill contract gaps with new fields. Inspect the pinned Hermes approval/continuation seam for contract-independent runtime groundwork; current local client support is insufficient. Bring the reviewed Class A/Class B probes into this worktree with source provenance and retain setup-blocked outcomes. Establish a barrier-controlled contention reproducer and a real suspension/resume probe.

Files: new `backend/runtime/routine_contracts.py`, `backend/runtime/tests/test_routines_contract.py`; proposed `runtime/hermes-image/smoke_routine_sessions.py`, `launch_routine_probe.py` and their focused tests. Exit: exact fixture identity passes, unsupported kinds fail safely, capability deficits are demonstrated and implementation seams are recorded. Do not call fake-session evidence Class B.

### Phase 2 - Durable admission and scoped concurrency

Add the routine extension, reserved attempt, acquisition authority/receipt and lease scope migrations as internal groundwork. Extend internal admission checks, claim construction, session CAS, stop/reclaim, terminal paths and profile lifecycle checks without exposing unresolved routine transport. Leave main binding schema untouched. Use production worker seams for overlap evidence. No coordinator test mode is planned; reconsider only if a documented production-seam limitation prevents the required proof.

Files: `models.py`; new migrations after current leaf `0018_workspace_runtime_release.py`; `services/routines.py`, `executions.py`, `claims.py`, `leases.py`, `sessions.py`, `attempts.py`, `profiles.py`; `api/register.py`, `api/schemas.py`; `runtime/allies_runtime/foundry.py`; focused backend/runtime tests. Exit: main+two distinct routines overlap, same routine/conversation cannot overlap, cross-scope CAS/replays make zero writes, historical main rows migrate intact.

Migration sequence: add extension/receipt tables and nullable scope field; backfill leases to `main` in bounded batches; validate scope/reference invariants; make scope non-null; install profile+scope partial unique constraint; remove profile-only constraint. Runtime run statuses must be supported by new code before routine admission is enabled. Test migration from 0018 with queued/running/terminal main rows and nullable bindings. Retain the old code path until updated workers/backend are ready. Never downgrade to old workers after multi-scope leases exist; drain routine work first and retain additive tables for evidence.

#### Enforced capability and mixed-version gate

Add a default-disabled server-side routine-admission setting and a persisted per-workspace enablement record bound to the current machine generation/runtime-start epoch and a reviewed, immutable runtime release/image digest. Reuse `services/runtime_releases.py` and `runtime_readiness.py` to verify that digest; this implementation derives the digest from the provider-applied immutable Hermes/runtime image pair and requires the reviewed `ALLIES_RUNTIME_ROUTINE_RELEASE_DIGEST` setting. Do not add a self-asserted capability bit to routines-v1. Unknown, missing, stale or unapproved release identity fails closed. The reviewed digest must support scoped leases, acquisition replay and approval suspension; all backend processes must run the migration-compatible services before enablement.

Enabling requires draining or effectively fencing every old worker/credential and unresolved old lease for that workspace, replacing the runtime with the approved digest, then accepting current authenticated readiness. The supervisor must start workers from that single verified release. Bind enablement to the authenticated generation/epoch, so an old process cannot claim using an old credential even if it remains alive. Do not enable if multiple worker versions can retain authority. Recheck the enablement record under the workspace lock at routine admission, first claim and reacquisition; a config switch alone is insufficient.

Files: `backend/config/settings.py`, `models.py`/migration, `services/runtime_releases.py`, `runtime_readiness.py`, `runtime_auth.py`, `routines.py`, `claims.py`, and `runtime/allies_runtime/foundry.py` as needed for release enforcement. Mixed-version tests must show zero routine admission/claims for old or unverified workers and invalidation after generation/epoch changes. Rollback first disables new admission, drains or effectively fences all routine authorities/actions, then retires compatible-worker credentials before starting older workers. Preserve evidence and pending deliveries; unresolved effects block downgrade. Old workers must never coexist with live scoped routine authority.

### Phase 3 - Cloud-owned integration and Foundry transport verification

Entry gate for Cloud-owned work: CLD-013 publishes authoritative management transport/context and insertion evidence, and resolves any remaining fixture/prose gaps. The Foundry command-adapter slice is no longer deferred: it uses the exact route map above and must be verified with Cloud-side adapter tests. Do not add guessed wire fields or placeholder receipts. Keep the capability gate and Class A/Class B evidence explicit without claiming live enablement.

After that gate, wire durable pause/CAS/expiry/action transitions and exact continuation to the published interfaces. Reuse FND-010 effective-stop semantics if available; otherwise implement only the waiting-action fence required here. Add bounded `expire_routine_approvals` processing to the control plane so expiry works while the tenant sleeps. Extend ordered outbox delivery/reconciliation only for released events, including `routine.result` and `routine.approval_requested`. Management adapters are selected from the published interface at that time. Cloud history insertion remains an external integration requirement; no Foundry append/marker code is included.

Files after the entry gate: `services/routines.py`, new `management/commands/expire_routine_approvals.py`; `services/events.py`, `event_delivery.py`, `attempts.py`, `leases.py`; `runtime/allies_runtime/routines.py`, `foundry.py`, `hermes.py`, and thin registration in `api/register.py`. Any management plugin, Docker registration or soul-instruction change is deferred until the authoritative interface and pinned registration seam identify the necessary file; none is scaffolded now. Keep substantial new orchestration out of the already large `foundry.py` and `api/register.py`.

Exit: every approval race/crash vector passes, no stale effect or whole-task replay occurs, every terminal path produces an outcome, and management never claims pending persistence as saved. Cloud integration confirms actual model-visible insertion.

### Phase 4 - Smallest memory remediation and release evidence

Start from distinct provider instances/sessions sharing one profile database. Instrument sanitized operation/lifecycle boundaries to isolate the intermittent failure. The default candidate is a bounded profile/database-keyed operation guard around the proven contending delegate operation; extend it to prefetch/shutdown/initialization only where they share the same unsafe connection or reproduced state. A per-instance lock cannot protect two instances. Check actual process topology: a process-local RLock is insufficient for demonstrated cross-process contention; use an operation-scoped file/DB mechanism only if that topology requires it. Keep the existing environment lock separate, define one acquisition order, and never change global provider state during unlocked calls.

Use barriers at the demonstrated contending delegate boundary, not sleep-only timing, with distinct session/provider instances. Before fixing, run a predeclared bounded stress matrix against the pinned baseline and retain a reproduced failure, operation counts, contention schedule, thread/process topology, seed and image digest. Run the same matrix against the candidate with identical settings and require every iteration to pass, including fresh-session recall after acknowledged writes and independent-profile negatives. Repeat separate bounded batches to exercise lifecycle/initialization/shutdown interleavings. Choose and record the batch/iteration/time budget from reproduction evidence before evaluating the candidate; never stop after the first few passes or discard failures. If the baseline failure cannot be reproduced, the contention claim remains inconclusive and cannot satisfy release. Three runs alone are not proof of the fix.

Lock wait consumes the operation's timeout budget, cancellation releases the guard, exceptions are sanitized, and persistence failure remains failure. Do not blindly retry memory mutations after an unknown commit. Validate successful write acknowledgment with fresh-session recall, independent-profile negative checks and concurrent file canaries. Do not change context_only defaults or broaden the memory allowlist to make a test pass; use an authorized narrow_tools synthetic profile for write evidence.

Files: `runtime/hermes-image/provider/allies_mnemosyne/provider.py`, its existing `tests/test_provider.py`, and the imported probes. No memory schema migration, provider replacement, global execution mutex or general file-management rewrite is planned. If the reproduced operation needs no production change after a corrected oracle, record that evidence rather than adding speculative locking. A remaining real contention failure blocks release.

Validation support files: `.github/workflows/ci.yml` for a real PostgreSQL race job, `backend/runtime/services/runtime_power.py` for all-scope activity accounting if its current queries need adjustment, and `docs/operations/routine-session-feasibility.md` for sanitized final evidence. Inspect the power service before changing it; the requirement is to preserve all active scopes, not to refactor power management. Keep probe import provenance and any pinned Hermes overlay changes reviewable with the image build checks.

Exit: the barrier-controlled repeated stress demonstrates the baseline failure and complete post-fix passes under the same recorded matrix; a digest-pinned inherited `/init` Class B run proves server-observable overlap, correct stream attribution, canary isolation, same-profile memory continuity, file access and approval continuation. Both repositories then pass Cloud-owned result insertion and published approval/cancellation integration evidence. Sanitized evidence records exact hashes/digest/model and distinguishes pass, failure, inconclusive and setup-blocked.

Delivery order follows phases 1 -> 2 -> 3 -> integrated phase 4; the scoped memory fix can be reviewed independently after reproduction. Aim for coherent 200-500-line review units, splitting adapters/migrations, approvals and provider remediation where independently testable. Keep necessary tests/migrations with each change. This planning task performs none of those commits or PRs.

## Acceptance Criteria

1. Byte-identical revision-14 implementation-facing candidate artifacts and legacy execution compatibility remain intact; revisions 7 through 9 remain preserved as historical predecessor evidence, with revision 9 the last coordinated downstream consumer baseline. Revision 14 is not released or consumed until explicit paired Cloud-first acceptance/order.
2. Main chat and different same-profile routines overlap with correct identity/history, while duplicate same-routine admission and same-conversation turns serialize.
3. Fresh run conversations receive the full prompt and authorized shared resources; retries preserve identity and no prior transcript is imported.
4. Database-clock approval CAS has one winner; effective rejection/expiry/cancellation fences stale work, frees capacity and delivers an outcome.
5. Action response loss never causes unsafe replay; terminal runs never reopen or automatically rerun.
6. Results include unchanged/failure outcomes and survive routine deletion; Cloud and real Hermes history show exactly one attributed insertion before the next turn.
7. Management honors clarification, suggestion agreement and deletion confirmation, and reports only durable saved outcomes as success.
8. Memory remediation is limited to reproduced operations and preserves all existing access/retention protections. Class A and real Class B evidence are required for release.
9. Routine admission remains disabled until authoritative closed interfaces and verified compatible worker authority satisfy the release gates. Mixed-version or stale-generation workers cannot admit, claim or reacquire routine work.

## Backend Considerations (if applicable)

### Query Optimization Plan

Replace profile-wide occupied checks with indexed scope checks. Bound claim candidates in pages (proposed internal batch 20) and exclude occupied scopes before selection, so an early busy main conversation does not starve eligible routines. Keep deterministic `(created_at, id)` ordering. Fetch execution/profile/run together and avoid a relation query for every emitted event. Database locks protect short mutations only.

### N+1 Prevention

Claim and delivery paths use `select_related` for execution/profile/routine metadata. Expiry reads at most 20 indexed pending rows, then rechecks each under locks. Add query-count comparisons for one and twenty ready rows; no full queued-execution scan or per-row network request inside a transaction. Measure lock contention and queue delay with IDs and safe codes, excluding prompts/tool payloads.

### Detailed Unit Test Cases

Closed fields and every immutable correlation component; wrong owner/workspace/Ally/binding; expired/overlong transport; multibyte limits; same replay versus changed replay; null-to-effective session CAS and stale token rotation; no second main binding; no routine-bound session overwrites; all terminal paths enqueue once. Test results/approvals without persisting credentials or arbitrary hidden fields.

## Frontend Considerations (if applicable)

### Data Path

Not applicable to local UI code. Integration path is Hermes routine tool -> authenticated Cloud management; Cloud dispatch -> Foundry routine session; Foundry outcome -> Cloud ingestion/insertion -> main session's next model input.

### State Management Considerations

Cloud owns schedule and presentation state. Foundry owns execution/attempt/lease/session/action truth. An event ingestion receipt is not an insertion receipt. Retain this distinction in integration assertions and failure reporting.

## Test Plan

| Focused test file (new unless stated) | Required evidence |
| --- | --- |
| `backend/runtime/tests/test_routines_contract.py` | Raw hashes, complete fixture mapping, canonical vectors, 60s/16KiB/64KiB bounds, legacy DTO regressions, safe unknown kind rejection |
| `backend/runtime/tests/test_routines.py` | Internal admission/receipt replay, fresh sessions, scoped leases, one-Lease/multiple-acquisition authority and immutable receipts; release disablement/current digest checks; published terminal/approval integration only after phase 3 entry gate |
| `backend/runtime/tests/test_routines_postgres.py` | Real PostgreSQL, separate connections and barriers; both winners for duplicate dispatch, same routine, approval/cancel, approval/expiry equality, session CAS, lease rotation, late terminal event and profile cleanup. Assert row/event/provider-call counts, not just response codes; fail explicitly if selected without PostgreSQL. |
| existing `test_migrations.py`, `test_cld005_contract.py`, `test_services.py`, `test_fnd007_execution.py` | Upgrade old rows, preserve main restrictions, legacy recovery and delivery, no missing migrations |
| `runtime/tests/test_routines.py`; existing `test_fnd007_worker.py`, `test_hermes.py`, `test_coordinator.py` | Barrier-controlled main+two-routine overlap; same-session serialization; stable identifiers, paused worker slot release, exact continuation, late stream suppression, malformed result and no restart |
| existing provider `tests/test_provider.py` | Barrier-controlled repeated baseline-failure/post-fix stress with retained matrix and counts; distinct-instance writes; recall after acknowledged writes; independent profile; lock timeout/cancellation/shutdown; all existing retention/allowlist/context_only rules |
| Class B plus CLD-013 integration | Real main turn overlaps routine; result arriving mid-turn inserts before queued follow-up and appears in actual model history once; approval resumes exact action; rejected/replaced/expired permission never acts; real memory/files and negative canaries |

Commands below are for implementation validation, from repository root unless `Push-Location` specifies otherwise. They have not been run for this documentation change. New test paths/commands become available in their phases.

```powershell
$env:DJANGO_DEBUG = 'true'
make check
make lint
make test APP="runtime/tests/test_routines_contract.py runtime/tests/test_routines.py runtime/tests/test_cld005_contract.py runtime/tests/test_services.py runtime/tests/test_migrations.py runtime/tests/test_fnd007_execution.py"
Push-Location runtime
uv run --locked pytest tests/test_routines.py tests/test_hermes.py tests/test_fnd007_worker.py tests/test_coordinator.py
uv run --locked pytest hermes-image/provider/tests/test_provider.py
Pop-Location
make validate
```

For races, provide `DATABASE_URL` for a disposable PostgreSQL test database and `DJANGO_SECRET_KEY` through the existing environment mechanism; do not print either. The ordinary CI configuration uses SQLite, and its production settings check uses a non-routable PostgreSQL URL, so neither proves locking. Add an actual PostgreSQL service job to CI for the selected race/migration suite.

```powershell
make test APP="runtime/tests/test_routines_postgres.py runtime/tests/test_migrations.py"
Push-Location backend
uv run --locked python manage.py migrate --plan
uv run --locked python manage.py migrate --noinput
uv run --locked python manage.py migrate --check
uv run --locked python manage.py expire_routine_approvals --limit 20
Pop-Location
```

After reviewing/importing the probes, build the pinned image with `make hermes-image-test`; resolve its full local digest before Class B. Run the recorded barrier-controlled stress matrix against baseline and candidate in repeated bounded batches; retain every result, including failures. The single offline invocation below is only a launcher example, not the stress acceptance criterion. Class B uses authorized synthetic credentials through opaque references, inherited `/init`, authenticated readiness, no published ports and bounded setup/probe times:

```powershell
docker run --rm --network none --entrypoint /opt/hermes/.venv/bin/python --mount "type=bind,source=$PWD/runtime/hermes-image/smoke_routine_sessions.py,target=/tmp/smoke_routine_sessions.py,readonly" allies/hermes-mnemosyne:dev /tmp/smoke_routine_sessions.py --mode offline --timeout-seconds 60
uv run --locked --project runtime python runtime/hermes-image/launch_routine_probe.py --image <resolved-local-image-digest> --credential-ref <opaque-reference> --model-profile-ref <authorized-synthetic-profile-reference> --setup-timeout-seconds 60 --probe-timeout-seconds 60
```

The second command is a template; replace placeholders privately. The probe model is `gpt-5.6-luna`. Repeated offline success supports the targeted fix but does not replace Class B or PostgreSQL evidence. Preserve secret scanning, dependency/image checks, engineering policy review and runtime coverage requirements. The episode reports 82 focused runtime and 77 backend baseline passes at this HEAD; those are prior evidence, not tests rerun in this planning turn.

## Risks and Mitigations

| Risk | Mitigation / release condition |
| --- | --- |
| Widened leases weaken cleanup or same-chat protection | Server-derived scope, DB uniqueness, all-scope cleanup tests and main-binding regression tests |
| Receipt reserves an attempt before a machine is available | Keep queued attempt identity distinct from current machine authority; wake/claim attaches authority; no claimed/completed success in admission receipt |
| Durable approval outlives process or machine | Persist checkpoint/action identity; retire tokens; prove exact continuation and quiescence; fail honestly when unavailable |
| Late worker acts after replacement | Fence all mutations and action dispatch; replacement waits for effective receipt; never treat transport close as effect cancellation |
| Memory contention remains intermittent | Reproduce distinct-session failure, guard only proven operation boundary, verify real topology and recall; retain inconclusive/setup-blocked classification until evidence exists |
| Routine results acknowledged but absent from model history | Separate ingestion/insertion receipts; real next-turn history assertion with queued follow-up and duplicate delivery |
| Large orchestration change becomes hard to review | Split cohesive phases, keep new routine logic in small modules, preserve legacy paths and include tests/migrations with each change |

Rollback: disable new Cloud routine admission, retain pending deliveries and approval evidence, drain/fence routine actions, then roll back application behavior only to a version compatible with scoped leases. Do not restore profile-only uniqueness while multiple scopes exist; do not delete routine records to force rollback. Routine unavailability must be visible rather than silently converting work into main-chat turns.

### Exact open contract questions

These are engineering gaps in the released artifacts, not requests to reconsider settled product behavior. CLD-012/CLD-013 must provide one authoritative interpretation or a coordinated new release; Foundry must not patch normative artifacts itself. The revision-14 candidate is available for compatibility validation only, and new result-event traffic remains gated on explicit paired Cloud-first acceptance/order. Independent local implementation and tests can proceed.

1. What closed JSON shape carries `routine.outcome` and the effective cancellation/fencing receipt, including retired/current fence and terminal cancelled/expired/manual-reconciliation attribution? The prose requires them; the fixture contains only result/approval examples and cancel request. Specify whether terminal result or outcome carries each lifecycle case; revision 14 preserves the required result title snapshot.
2. Which additional dispatch snapshot fields are actually on the closed wire? Revision 14 preserves `occurrence_disposition`, schedule/timezone snapshots, schedule-generation progression, service identity/fingerprint evidence, manual-reconciliation vocabulary, and the separation of Foundry-assigned identities into `dispatch_receipt`. Specify the linked execution identity and occurrence/run cardinality for explicit user retry; do not add required fields that reject the exact candidate fixture without owner direction.
3. What authoritative closed management transport/context interface does CLD-013 publish, and what Cloud-owned insertion evidence satisfies the model-visible result requirement? Management route/confirmation handoff and any missing insertion shapes remain deferred until publication. Foundry will not design or implement an insertion request, append or marker mechanism. Cloud insertion proof and the published management interface are release gates.

The runtime continuation API, final image digest and memory failure locus are inspection/validation work in phases 1 and 4, not unanswered product decisions. Approval duration, expiry equality, replacement winner, unchanged delivery, no-overlap, timezone/DST, and retry safety are already answered and must not be reopened.

### Sol review dispositions (focused revision 1)

| Finding | Disposition | Plan change / validation obligation |
| --- | --- | --- |
| ADV-001 P1 | Accepted; addressed in plan | Keep Lease.attempt OneToOne; append RoutineLeaseAcquisition authorities/receipts, update the same Lease current pointer, preserve Attempt replay fields and reject stale tokens. Require concurrent reacquisition, crash/replay and one-Lease assertions. |
| ADV-002 | Accepted; addressed in plan | Remove Foundry append/marker mechanism. Foundry emits/reconciles published events; Cloud owns insertion and its integrated proof. |
| ADV-003 | Accepted; manager integration priority supersedes the transport deferral | The three Foundry command adapters now proceed against the exact revision-14 compatibility-candidate envelopes and existing service receipts; Cloud management, outcome projection, and main-chat insertion remain Cloud-owned gates. |
| ADV-004 | Accepted; addressed in plan | Default-disabled admission plus persisted generation/epoch/reviewed-digest enablement; drain/fence old workers, verify current readiness and enforce at admission/claim/reacquisition. Downgrade waits for routine authority drain/fence. |
| ADV-005 | Accepted; addressed in plan | Require barrier-controlled repeated baseline failure and matched post-fix stress passes with retained counts/budgets. Three runs alone cannot satisfy acceptance. |
| SIM-001 | Accepted; addressed with ADV-002 | No Foundry history insertion machinery or new insertion wire contract. |
| SIM-002 | Accepted; narrowed by the manager integration priority | No speculative management-tool wire shape; expose only the exact revision-14 candidate command adapters and existing Foundry cancellation receipt. |
| SIM-003 | Accepted; addressed in plan | Remove proposed coordinator mode; use production worker seams unless a demonstrated limitation requires reconsideration. |

This plan follows the accepted revision-14 implementation-facing candidate wire shape, including its `occurrence_disposition` dispatch field, schedule/timezone snapshots, 1/2/3/4 schedule-generation progression, service identity/fingerprint and manual-reconciliation deltas, separate required dispatch-receipt identities, and required result `title_snapshot`, without independently editing the normative artifacts or claiming Cloud insertion, released rev14 traffic, or Class B release gates. The Foundry command-adapter route map is an authenticated transport mapping, not a contract change. Implementation and validation records for the scoped Foundry work are maintained in `episode-state.md` and the FND-012 handoff.
