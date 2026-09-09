# CLD-012 routines contract and feasibility plan

Current authoritative planning artifact by the owner's revision request. The singular-named concise plan is historical. Revision 7 retains the reviewed SOL-001 through SOL-005 and SOL2-001 through SOL2-003 decisions while correcting the revision-6 normative artifacts; revision 7 remains the accepted and published predecessor baseline, revision 8 is the preserved accepted title-snapshot correction, revision 9 is the preserved accepted predecessor correcting three additional contract inconsistencies, revision 10 is the preserved accepted metadata correction, revision 11 is the preserved accepted successor adding the saved schedule/timezone to the dispatch snapshot and aligning the normative document identity, revision 12 was an unaccepted candidate, revision 13 is the preserved accepted lifecycle reconciliation correction, and revision 14 is the active successor aligning routine Foundry envelopes with the existing v1 service identity. No mutable worktree is frozen; revision 6 was never accepted and is now superseded by revision 7.

## Using this template

Route: full. HTML required: no, explicitly requested for this contract/evidence episode.
Status: revision-14 contract accepted by fresh Sol review as the active Cloud candidate; revision-7 is the historical predecessor, revisions 8 through 13 are preserved accepted intermediates, and revision-12 was an unaccepted candidate superseded by revision 13; synchronized Cloud/Foundry artifacts are byte-identical; current-head hosted checks remain a merge gate; revision 6 was never accepted and is now superseded by revision 7; no mutable worktree is frozen; Class A aggregate feasibility is INCONCLUSIVE_REVIEW_REQUIRED and Class B remains SETUP_BLOCKED.
Planning date: 2026-09-09. Worker: Astra planning worker, as selected in the copied .agent/kickoff.yaml.
This planning worker changes only documentation. Later CLD-012 execution is limited to contract artifacts, fixtures, and a minimal feasibility harness.

## Feature Overview

- Problem: the accepted routines specification requires concurrent main chat and fresh routine sessions for one Ally; current Foundry enforces a single conversation binding and unresolved lease per profile.
- Target users: Cloud and Foundry implementers, with Interface consuming the resulting public discovery/detail and message contracts later.
- Source docs/specs: Nabu projects/allies/engineering/specs/routines.md, accepted 2026-09-09, revision 9f8226916656619b66b617eb313a59e09901e4ecc5c7b5584552ea37f6913433; complete CLD-012, CLD-013 and FND-012 ticket notes under projects/allies/delivery/tickets; projects/allies/index.md.
- Success outcome: one reviewed routines-v1 contract with portable matching fixtures in both repositories, reproducible evidence distinguishing current support from required changes, and exact integration prerequisites. CLD-012 must not claim product delivery from a fake or direct adapter proof.

Evidence inspected (paths are relative to the named repository):

| Evidence | Finding and consequence |
| --- | --- |
| Cloud HEAD 41f06a2c25093015af4190a178c849114c4fb28a; Foundry HEAD 1d03ea557be757f4eca4c6b6478d542291169b14 | Assigned ft/cld-012-routine-contract worktrees based on origin/dev; initially clean |
| Both AGENTS.md and ENGINEERING_STYLE.md; Cloud docs/templates/PLAN_TEMPLATE.md; copied .agent/kickoff.yaml; durable CLD-012 handoff | Full template, separate correctness/simplicity review, public-safe Foundry artifacts, no HTML; retain authorization and saved selectors |
| Cloud backend/allies/gateways/contracts.py:112-204 | Canonical sorted ASCII JSON, SHA-256 fingerprint excluding fingerprint/issued_at/deadline_at, unknown fields forbidden, strict bounded input; existing execution source is conversation_message only |
| Cloud backend/allies/gateways/contracts.py:17-30 and Foundry backend/runtime/contracts.py | v1 transport, 16 KiB text, 64 KiB Cloud event payload, 60-second command lifetime, existing approval lifetime 300 seconds; cannot silently reinterpret these as 24-hour routine approval support |
| Foundry backend/runtime/models.py:771 | ConversationBinding.profile is a OneToOneField and primary key; cloud_conversation_ref is unique |
| Foundry backend/runtime/services/executions.py:126-184,288-333 | Command resolution rejects a different conversation for the same profile; binding creation locks/reserves one profile conversation |
| Foundry backend/runtime/models.py:1037-1040 | runtime_lease_profile_unresolved_unique forbids more than one ACTIVE or STOPPING lease per profile |
| Foundry backend/runtime/services/claims.py:145-195,355-380 | Claim selection skips any profile with an unresolved lease; claim conversation/session come from the profile's single binding |
| Foundry backend/runtime/services/sessions.py:29 onward | Session compare-and-set is authorized through attempt and lease and returns durable receipts; preserve this fencing when binding scope changes |
| Foundry runtime/allies_runtime/hermes.py:360-379 | stable_session_identifiers(profile_id, cloud_conversation_ref) derives distinct candidate/session keys for distinct conversations; this alone proves neither simultaneous execution nor persistent-memory sharing |
| Foundry runtime/allies_runtime/coordinator.py:35-47,112-118 | ProfileProofCoordinator explicitly serializes even distinct sessions by profile; it is a proof coordinator, not evidence that the production worker itself uses this lock |
| Foundry runtime/allies_runtime/foundry.py:1643 onward | Worker derives session identifiers from claim conversation; current claim binding therefore matters end to end |
| Foundry runtime/hermes-image/provider/allies_mnemosyne/provider.py:413-510 | Profile-root and identity checks, guarded initialization environment, SQLite busy timeout; background/cron contexts are skipped. Default context_only disallows arbitrary memory writes. Safe concurrent mutations are unproved |
| Foundry runtime/hermes-image/Dockerfile | Hermes source pin 36cb5ae5530a75def7df3195e49b7a4aa2add482; mnemosyne_hermes 0.5.0 and mnemosyne_memory 3.15.1. Image/runtime behavior must be recorded at the actually tested digest |
| Cloud backend/chat/services/dispatch.py; backend/activities/services/projection.py | Message-linked durable dispatch/reconciliation and ordered event projection exist; visible projection is not proof of insertion into the existing Hermes main-session history |
| Both README.md, Makefile, backend/pyproject.toml, .github/workflows/ci.yml; Foundry runtime/pyproject.toml | Python 3.13+, locked uv, pytest, Ruff, Django checks; Cloud has PostgreSQL concurrency CI, Foundry uses scripts/validate.py |

## User Stories

1. As an implementer, I need exact shared shapes and failure rules so independent Cloud and Foundry work agrees.
2. As a user, I need main chat and different routines to remain available with separate histories and the same Ally's authorized resources.
3. As an operator, I need reproducible evidence that identifies unsupported behavior without exposing private content or implying deployment readiness.

## Scope

### In Scope

- Publish management, discovery/detail, schedule, dispatch, result, approval and lifecycle contracts using the existing strict v1/fingerprint/gateway conventions.
- Freeze each boundary listed below, including deterministic ordering, idempotency, stale updates, retention and capacity reconciliation.
- Add small generic fixtures and tests; demonstrate existing constraints and direct runtime feasibility with bounded local harness execution.
- Document the smallest required CLD-013/FND-012 change boundary. Report failed probes honestly.
- Maintain the durable episode handoff. Canonical Nabu updates belong to the owning delivery task after contract review, using revision-aware writes.

### Out of Scope

Production models/migrations, endpoints, scheduler/beat tasks, management tools, feature flags, lease changes, runtime memory policy changes, broad Hermes refactors, interface work, deployments, merges, and production data.
This worker makes no commits, pushes, PRs or additional agents. Later delivery authorization remains with the parent task.
No event triggers, silent completed runs, push notifications, prompt editor, authoring form, separate-run inspection, or deletion sheet.

### Dependencies and Assumptions

Product approval and autonomous delivery authorization already exist; do not reopen them.
Engineering choices below are recommendations for contract review, not newly accepted product policy.
Use the existing installed dependencies and gateway. No shared Django package or schema registry.
Both repositories use the assigned branch and origin/dev base. Refresh evidence if relevant code changes.
Retain the full accepted specification as authority. Screens are not binding copy and need no inspection for this nonvisual episode.

## Contract and Shape Definitions

Use a standalone routines-v1 document and executable JSON fixtures first; do not register new handlers or widen existing runtime DTOs during CLD-012.
The envelope schema_version remains v1. A distinct routine kind/source discriminator must be defined explicitly; existing execution.command with source_kind=conversation_message remains unchanged. Old consumers must reject unsupported routine messages safely. Dependent integration enables new kinds only after both consumers support the same frozen revision.

### Function and Service Shapes

These are proposed harness helpers, not product services.

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| Foundry runtime/tests/test_routine_session_feasibility.py (new) | test_stable_separate_session_ids | () -> None | Same profile, main and two occurrence conversation IDs; different profile negative case | Assertions | None |
| Foundry runtime/hermes-image/smoke_routine_sessions.py (new) | main | () -> int | Local sandbox profile, bounded timeout, pinned image, synthetic facts/files only | Exit code and sanitized JSON evidence | Temporary sessions/files; nonzero for failure; missing prerequisites reported separately |
| Both new fixture test files listed in Phase 1 | test_routines_v1_vectors | () -> None | Case metadata, artifact hashes and canonical fingerprint expectations | Structural/compatibility assertions only | No network, migrations or product mutations |

### API and Transport Contracts

Phase 1 must define each contract below with complete fields and valid request/response examples in routines-v1.md and fixtures. These are planned transport surfaces; this episode adds no HTTP route.

| Consumer | Method and path / event | Authentication and authorization | Request schema | Success response schema | Error responses / retry semantics |
| --- | --- | --- | --- | --- | --- |
| Owner client | Proposed GET /api/v1/routines and /api/v1/routines/{routine_id} | Existing browser session plus CSRF/origin where applicable, or native bearer; owner checked by Cloud across Allies | Cursor/limit and optional ally_id; detail UUID | RoutinePage / RoutineDetail | Existing product error envelope; unauthorized objects indistinguishable from missing |
| Ally tools via Cloud boundary | routine.manage v1 logical command; exact mounted internal route follows gateway convention at freeze | Service authentication plus immutable workspace/Ally/user context; never trust user_id supplied by model | RoutineManagementCommand | Durable management receipt/detail | Validation, missing ownership, stale revision, idempotency conflict; no optimistic success |
| Cloud to Foundry | routine.dispatch v1 logical command using existing gateway transport | Existing service identity and owned binding validation | RoutineDispatchCommand | Accepted execution correlation receipt | Same-key reconcile on timeout/unknown outcome; no whole-task replay after terminal failure |
| Foundry to Cloud | routine.result / routine.approval_requested | Existing service event authentication and immutable run correlation | Ordered routine event | Durable ingestion receipt | Duplicate identical event acknowledged; changed replay conflicts; stale attempts fenced |
| Cloud to Foundry | routine.approval_decision / routine.cancel_wait | Existing approval authorization and attempt/generation fencing | ApprovalDecision / CancelWaitingRun | Decision acceptance or effective terminal cancellation receipt | Acceptance is not action completion; expired/replaced decisions cannot authorize actions |

No deployed HTTP API changes occur here, so this plan does not claim working request/response examples. The following representative logical bodies show intended mapping; the final fixture set must include complete envelopes, real synthetic UUIDs, exact hashes, receipt/error bodies and every operation, without placeholder values.

```json
{"operation":"create","title":"Check availability","execution_prompt":"Check the agreed item and report the outcome, including no change.","schedule":{"kind":"once","local_at":"2026-09-10T09:00:00","timezone":"Europe/Berlin"}}
```

```json
{"outcome":"saved","revision":1,"scheduling_status":"active","next_run_at":"2026-09-10T07:00:00Z"}
```

```json
{"kind":"routine.result","routine_revision":1,"title_snapshot":"Check availability","outcome":"unchanged","text":"The item is still unavailable.","references":[],"delayed":false}
```

Freeze matrix (binding requirements plus recommended engineering resolutions):

| Area | Required contract |
| --- | --- |
| Ownership/identity | Cloud owns routine, schedule, user authorization, discovery and main-message projection. Foundry owns execution, attempt, lease, profile and ordered runtime events. Immutable workspace, owner, Ally and binding association; routine belongs to exactly one Ally. Keep main_conversation_id distinct from fresh run_conversation_id and from execution_id |
| Management | create, update, pause, resume, delete, get/list. title distinct from complete Ally-authored execution_prompt. Create immediately for a sufficiently specified user instruction; suggestions require agreement; missing essential task/timing/timezone is clarified. Deletion requires a Cloud-owned opaque one-shot confirmation_ref tied to the exact workspace/owner/Ally/binding, main conversation, routine and revision; CLD-013 validates and atomically consumes it with the delete CAS. Missing, stale, replayed or foreign references are zero-mutation outcomes. Controls send requests through the Ally. Receipt means persisted success; pending/failure cannot claim applied state |
| Discovery/detail | Owner-scoped across Allies; responsible Ally included. Active/Paused are schedule states. Include paused recurring routines with saved schedule even without next_run_at; exclude deleted and exhausted schedules, including finished one-time schedules, irrespective of execution outcome. Full prompt available in authorized detail. No run transcript URL. Recommend opaque owner/filter-bound keyset cursor ordered by created_at,id, default 50/max 100 items; recheck ownership each page; changes between pages are not a snapshot promise |
| Schedule/timezone | One-time aware instant derived from specified local time and IANA timezone; recurring wall-clock expression with stored timezone. Keep timezone fixed until explicit update; browser/device missing timezone means clarification. Recommend UTC wire instants to second precision and earliest repeated instant (fold=0); nonexistent time advances to next valid local instant. Phase 1 freezes supported expression grammar and precision with examples, rejecting rather than approximating unsupported input. Any new user-visible cadence restriction needs Product review |
| Recovery/overlap | Cloud durable scheduling survives sleeping Machine. Latest missed recurring occurrence once, missed one-time once, visibly delayed. Working prior run means skip, never backlog. Resume uses next future occurrence without paused catch-up. Approval replacement is the only stated exception; no overlapping action execution |
| Dispatch/context | Snapshot routine revision/title/full prompt/schedule occurrence at dispatch. New conversation per occurrence, same profile identity/memory/files/authorized tools. No automatic main or previous-run transcript copy. Stable occurrence identity reused for transport retries; explicit user retry has its own linked execution identity. Edits/pause/delete affect future work and do not rewrite/cancel already working context |
| Results/main context | Every completed run, including unchanged, and every failure yields attributed result. Preserve routine identity, title snapshot, result text and typed rich references such as label/full URL; no arbitrary hidden notes or full transcript. Preserve results after deletion. Recommended ordering: durably ingest at once, insert at a main-turn boundary after an already-started turn completes and before dispatch of the next turn. Pending insertion remains pending. Next user turn must include the result once in actual model input/history, including a user message queued before result arrival. Reconcile Hermes-session insertion with a durable receipt/watermark; a UI Message alone is insufficient. Never alter an in-flight model prompt |
| Approval expiry/replacement | Waiting request deadline is created_at + 24h. Earlier next occurrence causes cancel_wait; dispatch replacement only after effective terminal cancellation/fencing receipt. Foundry owns authoritative action permission and generation; Cloud owns user decision and projection. Race is serialized at that authority: approval already authorizing work wins into working state, so new occurrence is skipped; cancellation/expiry winning invalidates old decisions. Equality with expiry rejects approval. Rejection prevents action and posts outcome. Preserve 60s transport deadline separately from 24h human wait. Existing 300s approval schema needs a routine-specific contract, not a global constant bump |
| Waiting lifecycle | Waiting run releases active compute capacity only after continuation is durable and fenced; no long-lived worker is assumed for 24h. Resume must target same logical waiting run and approved action. FND-012 proves checkpoint/resource reclamation and reuses or reconciles FND-010 cancellation. If pinned Hermes cannot resume safely, record blocker and minimum required adapter work; never restart the entire prompt as a continuation |
| Lifecycle/errors | Keep schedule active/paused/deleted/exhausted distinct from occurrence due/skipped/delayed and run queued/working/approval_waiting/succeeded/failed/cancelled/expired. Exact enum mapping to existing ExecutionStatus/approval states must freeze. Terminal outcome is monotonic; cancellation request is not cancellation completion. Recurring failure retains next occurrence. Recover inside a live execution when safe; no automatic new whole-task execution after terminal failure. Safe transport/reconciliation retries remain bounded |
| Correlation/idempotency/revision | UUID routine_id, occurrence_id, run_id, both conversation IDs, binding, execution/attempt/generation and event sequence. Cloud assigns occurrence once; unique routine+scheduled instant prevents simultaneous scheduler claims; skipped occurrence remains recorded. Mutation expected_revision required; monotonic revision and compare-and-set reject stale writes. Same key/same semantic fingerprint returns same receipt; same key/changed payload conflicts. Retry timestamps may change without semantic hash change; ownership, prompt, revision, occurrence and result content may not. Stale generation never resumes/projects as current |
| Privacy/retention | No credentials/tool grants in saved prompt or evidence; profile's existing authorization and approval policy still applies. Reuse text/event bounds, with explicit reject before persistence if full prompt cannot be transported; never truncate. Preserve conversation results on delete. Phase 1 inventories current retention policy by record type and freezes cleanup dependencies: no deletion of unacknowledged delivery, live approval, execution evidence or dedupe tombstone needed for a supported replay window. No invented retention duration; absent policy is an explicit engineering blocker to cleanup design, not permission for destructive cleanup |
| Same-profile concurrency | Main chat plus two different routines must be eligible concurrently; at most one active run per routine, and existing same-conversation turn serialization remains. Profile-wide work locks cannot be the final workaround. Keep capacity bounded with existing worker controls, distinguish resource contention/delayed dispatch from same-routine skip. PROOF_SLOTS=2 is a proof setting, not a product quota. New usage limits require policy evidence or Product decision |

### Approval authority and atomic permission consumption (SOL-001)

FND-012 owns enforcement. Foundry creates the durable routine ApprovalRequest with immutable request/run/execution/attempt/generation/action identity, created_at and expires_at in the transaction that records approval_waiting. Use the Foundry database clock sampled after acquiring the relevant locks; expires_at = created_at + 24 hours. Delivery/retries cannot reset either timestamp. Cloud and Hermes echo the authoritative deadline for display/correlation; caller-carried expiry and client clocks cannot extend or shorten permission. Transport issued_at/deadline_at still use the existing bounded 60-second command contract.

At decision time, lock in the established order and sample fresh database wall time after lock acquisition (PostgreSQL clock_timestamp(), not transaction-start CURRENT_TIMESTAMP). One transaction/CAS requires request.status=pending, unconsumed permission, matching immutable identity and current fenced attempt/generation, run=approval_waiting, and now < expires_at. In that same transaction, record the decision receipt, consume the one-shot permission, and transition request to authorizing and run to working. An action may execute only under that committed, action-specific fenced permission; there is no separately checked/reusable boolean approval. Failed CAS produces no action. Unknown action outcome is reconciled without automatically replaying the action.

| Pending transition | Result code / durable outcome |
| --- | --- |
| Valid approve wins before expiry | APPROVAL_AUTHORIZED; request authorizing, run working, permission consumed atomically |
| Reject wins before expiry | APPROVAL_REJECTED; permission consumed/invalidated, run terminal cancelled with rejection reason; main-chat outcome |
| Database now >= expires_at | APPROVAL_EXPIRED; pending request and waiting run become terminal expired, permission invalidated; main-chat outcome |
| Replacement cancellation wins before expiry | APPROVAL_CANCELLED; pending request and waiting run terminal cancelled, permission invalidated; replacement waits for effective fencing receipt |
| Already authorizing/working | APPROVAL_ALREADY_AUTHORIZING for competing cancel/reject; next occurrence skips. Exact duplicate approve returns original receipt without consuming again |
| Wrong generation/identity, changed duplicate | STALE_GENERATION / CORRELATION_MISMATCH / IDEMPOTENCY_CONFLICT; no permission or run change |

Expiry takes precedence over a new pending decision at equality or later. Existing terminal states never reopen; matching retries return stored terminal receipt. For rejected/cancelled/expired states, no later decision authorizes action. Existing authorization checks still apply on duplicate lookup.

Required FND-012 acceptance vectors: one microsecond before expiry, equality, one microsecond after; lock wait crossing expiry; delayed Cloud event/command and skewed client clock; renewed transport envelope with unchanged request deadline; duplicate approve; changed-key replay; stale generation; approve/cancel and reject/approve with both lock winners; action crash after CAS. These are declared future behavior vectors under SOL-004, not claims of implemented enforcement.

### Durable action dispatch after approval (SOL2-002)

FND-012 owns a durable action-attempt record, not a new table in this episode. The authorization transaction creates its immutable action_attempt_id, approval_request_id, run/execution/attempt/generation, exact authorized action digest and any provider idempotency key, with state pre_dispatch. The approval receipt identifies this record. Approval retries cannot mint another action attempt or change its payload. Provider credentials remain in the existing secret boundary, not this record or fixture.

States advance monotonically: pre_dispatch -> dispatching -> completed, or dispatching -> unknown -> completed/manual_reconciliation. A fenced or invalid pre_dispatch action can go directly to manual_reconciliation without dispatch. Never transition backwards or create a replacement action identity automatically.

| Boundary | Durable behavior and retry rule |
| --- | --- |
| pre_dispatch | No external call is permitted. A recovery worker may CAS this same record to dispatching after validating current generation and exact authorized digest. Only one worker wins; no whole-prompt restart |
| dispatching | Commit dispatch intent and action identity before external I/O, then issue the exact authorized call. A crash after this commit is ambiguous even if no bytes were sent. A duplicate worker does not issue an ordinary second call |
| completed | Persist provider receipt/reference, action digest and result atomically with completion and result-delivery intent. Stored receipt answers retries; lost Cloud acknowledgement retries result delivery only |
| unknown | Timeout, connection loss, process death or missing completion receipt after dispatch produces ACTION_OUTCOME_UNKNOWN. Reconcile by read-only provider status lookup using the same action identity; never infer failure means no side effect |
| manual_reconciliation | If no authoritative lookup or safe recovery exists, durably terminate this run's automatic processing with ACTION_MANUAL_RECONCILIATION and report the possible effect plus required user action in main chat. Recurring future occurrences remain governed by the accepted schedule; this action is never automatically replayed |

Only an external API with a verified idempotency guarantee covering the exact operation, same payload/key and full recovery window may receive a bounded recovery request using that same key. This is transport reconciliation, not another logical action. Record that capability in the action contract. Without it, or after its window expires, no dispatch retry is allowed. Read-only status reconciliation is capped at three attempts within 60 seconds; unresolved outcomes become manual_reconciliation rather than leaving the run indefinitely working. Later human reconciliation appends evidence to the terminal record; it does not reopen automatic dispatch. User-authorized further work requires a new explicit action authorization and must disclose the unresolved prior effect.

Mandatory FND-012 crash vectors (structural specifications here, executable enforcement in FND-012):

| Crash point | Expected durable state/result and external-call count |
| --- | --- |
| Before authorization transaction commits | No action record/permission; no call; decision retry may perform the original CAS |
| After authorization commits, before dispatch-intent CAS | Same pre_dispatch action identity; recovery CAS may send once, provided fencing is current; duplicate decision returns original receipt |
| After dispatch-intent commit, before network send | Treat as unknown on recovery; zero calls may have happened but cannot be assumed. Read-only reconciliation or verified same-key recovery only; otherwise ACTION_MANUAL_RECONCILIATION |
| Request sent, response lost or timeout | unknown; side effect may have occurred once. No non-idempotent replay; authoritative lookup can complete the same action, otherwise manual_reconciliation |
| Provider success received, process dies before receipt commit | Same unknown treatment; do not fabricate completed state or repeat the action to recover the receipt |
| Completion transaction committed, response/Cloud receipt lost | completed with stored receipt and delivery intent; replay returns same receipt, delivery retries dedupe, external-call count unchanged |
| Worker restart/stale generation or two dispatch CAS contenders | Stale worker cannot consume or dispatch; one CAS winner only. If dispatch may already have occurred, use unknown reconciliation, never a second action |

All failures preserve the accepted prohibition on automatic whole-task/non-idempotent replay. This is the minimum action-level state needed to interpret a consumed approval after a crash, not a general workflow framework.

### Routine admission and mutation ordering (SOL-002)

CLD-013 owns one Cloud transaction that locks/CASes routine revision plus scheduling state, rechecks the due candidate against that revision, checks overlap, and creates the unique occurrence plus immutable run snapshot and dispatch outbox intent. Commit is the admission linearization point. Snapshot includes complete prompt/title, saved schedule/timezone, scheduled instant, revision, owner/Ally/binding and both conversation identities. No network call occurs inside this transaction.

Admission winning counts as already active for future-only edit/pause/delete semantics, even before Foundry receives dispatch. Subsequent mutation prevents future admissions but preserves that admitted run and its outbox. This engineering interpretation is explicit for review; it does not cancel an already admitted run or silently rewrite its context.

| Race / winner | CLD-013 outcome code and snapshot rule |
| --- | --- |
| Create not committed | NOT_ADMITTED; scheduler cannot see it. After create commits, re-evaluate the saved due schedule |
| Delete before admission | ROUTINE_DELETED; no new occurrence/run/outbox |
| Recurring pause before admission | ROUTINE_PAUSED; no admission or later catch-up for intentionally paused time. One-time pause returns PAUSE_UNSUPPORTED |
| Update before admission | Reject the old candidate as STALE_DUE_CANDIDATE; select a new candidate from the new revision. That new candidate may admit an entirely new snapshot only if still eligible/due; never reinterpret the old candidate |
| Admission before update | Existing occurrence retains old immutable revision/snapshot; future admissions use new revision |
| Admission before delete/pause | Existing run/outbox remains eligible to finish; subsequent admissions reject deleted/paused state |
| Duplicate scheduler admission | OCCURRENCE_REPLAY returns exact existing run/snapshot, including after a mutation; never rebuild snapshot from current routine |
| Stale management expected_revision | REVISION_CONFLICT; no partial mutation |
| Existing working same-routine run | OCCURRENCE_SKIPPED_ACTIVE, durable skip without backlog |
| Approval-waiting replacement | REPLACEMENT_PENDING until Foundry effective cancellation receipt; then recheck current Cloud revision/state in admission transaction. Delete/pause/update during cancellation is honored |

The occurrence dedupe identity is routine_id plus canonical scheduled UTC instant; revision is snapshot data, not a way to admit the same instant twice. Mutations cannot alter that identity or revive recorded skipped occurrences. Each race vector names both possible winners, expected state/outbox count and exact snapshot revision. CLD-013 must execute these against PostgreSQL; CLD-012 checks only case structure.

### Resume and stale due-candidate fencing (SOL2-001)

Every selected due candidate carries routine_id, scheduled_at, observed_revision and observed_schedule_generation. Cloud starts schedule_generation at 1 and increments it exactly once on schedule/timezone changes and every effective pause/resume transition. Routine revision increments on every mutation. Admission compares both values under the routine lock; mismatch returns STALE_DUE_CANDIDATE and creates zero occurrences, runs or outbox rows. Even a candidate with an unchanged scheduled instant is not upgraded in place. A fresh selection is required. An already admitted occurrence replay returns its stored snapshot before candidate freshness is considered and creates zero additional outbox rows.

Resume atomically changes paused to active, increments revision/generation, records resume_effective_at from Cloud's database clock sampled after locking, and sets next_run_at to the first scheduled instant strictly greater than resume_effective_at. It excludes the paused interval, including equality with resume time. Admission requires a candidate selected under these new values and representing that eligible future schedule; a later genuine scheduler outage can recover it under the existing recovery rule. Repeated resume of active state is an idempotent no-op (ROUTINE_ALREADY_ACTIVE), not a new scheduling epoch.

| Race / lock winner | Expected code | New outbox count | Snapshot revision |
| --- | --- | --- | --- |
| Resume commits before a paused-interval candidate reaches admission | STALE_DUE_CANDIDATE for old candidate | 0 | None |
| Due admission checks paused state before resume commits | ROUTINE_PAUSED; resume then returns ROUTINE_RESUMED | 0 | None |
| Candidate selected after resume but before its new next_run_at | NOT_DUE | 0 | None |
| Fresh post-resume candidate reaches its new eligible instant | OCCURRENCE_ADMITTED | 1 | Exact post-resume observed_revision |
| Pause/resume cycle commits before previously active candidate admission | STALE_DUE_CANDIDATE, even if clock instant matches | 0 | None |
| Eligible admission commits first, followed by pause and resume | OCCURRENCE_ADMITTED; later mutations preserve admitted run | 1 total | Original admission revision, unchanged |
| Replay of that admission after resume | OCCURRENCE_REPLAY | 0 additional | Original stored revision |
| Resume at exactly a previously paused scheduled instant | ROUTINE_RESUMED; old candidate stale, next_run_at strictly later | 0 | None until new eligible admission |

CLD-013 must execute PostgreSQL transaction/barrier vectors for both lock winners of resume versus paused-candidate admission; admission versus pause/resume; update versus candidate admission; and two scheduler claims. Assert result codes, revision/generation values, next_run_at, occurrence/run/outbox counts and exact snapshot prompt/revision. Include resume equality, duplicate resume, multiple missed paused instants and an outage after the newly selected post-resume instant. No vector may use a sleep-only race or SQLite as proof. CLD-012 checks metadata for these vectors only. Add STALE_DUE_CANDIDATE, NOT_DUE, ROUTINE_RESUMED and ROUTINE_ALREADY_ACTIVE to the Cloud result-code mapping.

### Normative artifacts and drift prevention (SOL-005)

Cloud owns normative docs/contracts/routines-v1.md and docs/contracts/fixtures/routines-v1.json. Add docs/contracts/routines-v1.lock.json in both repos with the identity tuple:
(contract_name="routines", schema_version="v1", content_revision=positive integer, content_sha256, fixture_sha256).
Hashes cover exact file bytes (UTF-8 without BOM, LF line endings, one final newline), including normative prose/schema definitions and fixture case metadata. The lock file is outside its own hashes; version identity cannot depend on a self-referential embedded digest.

Foundry vendors byte-identical document, fixtures and lock from the accepted Cloud commit. Its non-authoritative status and source Cloud commit go in docs/contracts/README.md, outside hashed content. No registry, generated subset or shared package. Local fixture tests read the lock, assert identity fields, SHA-256 both raw files and compare to the pinned hashes; canonical fingerprint checks are separate from these raw-byte hashes.

The delivery task runs this exact cross-worktree check from the helpers workspace:
```powershell
$contractCloud = ".tmp/routines-cld012-cloud/docs/contracts"
$contractFoundry = ".tmp/routines-cld012-foundry/docs/contracts"
foreach ($relative in @("routines-v1.md", "fixtures/routines-v1.json", "routines-v1.lock.json")) {
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath "$contractCloud/$relative").Hash -ne
        (Get-FileHash -Algorithm SHA256 -LiteralPath "$contractFoundry/$relative").Hash) {
        throw "Routine contract drift: $relative"
    }
}
```

Review/release workflow: edit Cloud first, increment content_revision for any normative/fixture change, recompute both hashes and obtain contract review. Vendor that exact accepted candidate into Foundry, run both local hash tests and cross-worktree check. Future delivery merges Cloud before Foundry; Foundry records the actual accepted Cloud commit and rechecks the same tuple after Cloud merge. If content changed during either review/merge, refresh the vendored copy and rerun checks/review; never independently edit Foundry's copy or publish different bytes under the same tuple. Parent owns merges under separate authority; this worker does not merge. Dependent consumers pin the accepted tuple, and integration remains blocked until both merged artifacts match it.

### Fixture evidence limits (SOL-004)

CLD-012 executable fixture tests prove only raw artifact/hash identity, canonical JSON/fingerprint compatibility and structurally complete case metadata. Each case requires case_id, requirement, input, preconditions, ordered competing actions when applicable, exactly one of expected_result_code or evidence-specific expected_constraint_outcome, expected_postcondition and enforcing_owner (CLD-013, FND-012 or their integration). Code checks metadata presence/types and digest vectors; it does not authorize owners, validate future DTOs, advance clocks or execute state machines. No new generic/typed contract validator is authorized.

Owner/code mapping: Cloud CLD-013 enforces REVISION_CONFLICT, ROUTINE_DELETED, ROUTINE_PAUSED, PAUSE_UNSUPPORTED, CANDIDATE_SUPERSEDED, OCCURRENCE_ADMITTED/REPLAY/SKIPPED_ACTIVE and owner/shape failures (NOT_FOUND, INVALID_INPUT). Foundry FND-012 enforces approval codes above and runtime generation/identity rules. Integrated Cloud/Foundry tests own RESULT_INSERTED_ONCE and REPLACEMENT_PENDING -> OCCURRENCE_ADMITTED. These proposed stable contract codes must be mapped to existing safe transport envelopes in Phase 1; they are not currently implemented responses.

### Data Shapes and Invariants

#### Database Models

Not applicable to CLD-012 implementation: no migrations or tables. The future Foundry boundary must replace the single-binding assumption with per-conversation binding identity while preserving the existing main binding and session receipt; scope unresolved leases to the execution/conversation policy instead of the whole profile. Keep tenant, generation and same-conversation fencing. Do not simply remove uniqueness constraints. CLD-013 owns future durable routine/occurrence/revision and projection storage.

#### Enums

Contract vocabulary only: management operation, scheduling status, schedule kind, occurrence disposition, run outcome and approval decision as defined in the matrix. Phase 1 specifies closed values and allowed transitions; it must map existing persisted enums explicitly, not present these vocabularies as new tables.

#### API Request Schemas

RoutineManagementCommand: version/kind, command/idempotency IDs, trusted scope/correlation, operation, expected_revision for mutations, bounded title/full prompt and typed schedule for applicable operations. Delete carries only the opaque Cloud confirmation_ref for confirmed conversational intent; CLD-013 owns exact binding validation and atomic consumption; user_id is not model-controlled authority.

RoutineDispatchCommand: existing envelope identity/deadlines/fingerprint plus immutable routine/run/occurrence/revision, schedule_generation, main and run conversation IDs, scheduled_at, delayed, occurrence_disposition, and saved execution prompt. Foundry assigns execution_id, attempt_id, and generation in the dispatch receipt and ordered events; those fields are not Cloud command inputs. RoutineApprovalDecision: approval identity, run/execution/attempt/generation, decision and bounded transport times. CancelWaitingRun: same fencing tuple plus reason (replacement/expiry) and replacing occurrence when applicable. Required/null/omission behavior must be closed per operation in Phase 1.

#### API Response Schemas

RoutineDetail: ID/revision/title/full prompt/saved schedule/responsible Ally/scheduling status/nullable next_run_at. RoutinePage: bounded items and nullable opaque cursor; omit full prompt from list. ManagementReceipt: durable outcome and revision. DispatchReceipt: accepted execution correlation, not completed result. EventReceipt: durable dedupe/sequence disposition. Errors reuse established envelopes with stable safe codes, no raw exceptions or private payloads.

#### Temporary / Internal Shapes

Immutable run snapshot and typed result projection are DTOs, not new database tables here. Event sequence and attempt identity retain existing bounded wire limits. Cursor is opaque and scoped. Harness evidence includes source SHA/image digest, test name, synthetic identity labels, timestamps, overlap intervals, assertion outcomes, safe error codes, and temporary resource cleanup result. Never capture full prompts, transcripts, credentials or real user files.

#### Service Primitives

No production service is added. Planned contract operations own these atomic boundaries: Cloud routine revision CAS, Cloud occurrence admission, Foundry attempt/action fencing, Cloud event dedupe and main-context insertion acknowledgement. Keep transactions short and preserve the established Workspace -> Profile -> Execution -> Attempt -> Lease order where applicable; no database transaction spans model execution or a human approval wait.

### Plain-language glossary

- Model/table: persisted row; none added here.
- Schema/DTO: validated boundary data, not automatically a table.
- Enum: closed vocabulary with explicit transitions.
- Primitive: operation owning one atomic state change.
- Index: lookup aid; constraint: rule rejecting invalid combinations.
- Invariant: rule retained through retries/concurrency.
- Session: isolated working conversation; profile: shared Ally identity and authorized persistent resources.
- Occurrence: scheduled opportunity; run: its execution; attempt: Foundry's fenced runtime effort. Delayed or exhausted does not mean succeeded.

### Frontend Interaction Shapes (if applicable)

Not applicable: no interface implementation or design. Contract preserves Full prompt disclosure, conversation-led controls, distinct activity/result attribution and actionable main-chat approvals for downstream clients. Designers retain presentation and accessibility decisions.

## Phases

### Phase 1 - Freeze the narrow contract

- Goal: resolve wire-level engineering choices without changing approved product behavior.
- Work: author complete schemas, per-operation JSON request/response/error examples, canonical hash vectors, transition/race tables and the policy inventory described above. Keep a requirement-to-fixture index. Inspect existing gateway route/error/cursor conventions before choosing exact routes. Explicitly resolve schedule grammar, payload compatibility, 24h approval continuation, model-history insertion receipt, capacity and retention evidence before marking frozen.
- Impacted files/systems (new unless stated): Cloud docs/contracts/routines-v1.md (canonical contract), docs/contracts/fixtures/routines-v1.json, backend/allies/tests/test_routines_contract.py; Foundry docs/contracts/routines-v1.md (portable compatibility copy with revision/hash), docs/contracts/fixtures/routines-v1.json, backend/runtime/tests/test_routines_contract.py.
- Keep tests within these files; no runtime module import or route registration changes. Reuse existing canonical serialization/fingerprint functions directly. Executable tests are limited to the SOL-004 structural/hash oracle. Negative/race vectors are mandatory future acceptance inputs, not passing enforcement tests; do not add a generic schema engine.
- Also add docs/contracts/routines-v1.lock.json in both repos and Foundry docs/contracts/README.md for vendoring provenance, as specified in SOL-005. No registry or package is added.
- Exit: all matrix areas frozen or an exact unresolved item/owner blocks dependent integration. Both repos consume identical vectors. Current chat v1 examples retain byte-for-byte fingerprints. Contract review records its revision/hash and each disposition.

### Phase 2 - Prove current constraints and direct runtime feasibility

Two evidence classes are mandatory and reported separately: A, offline provider/storage diagnostics; B, real pinned Hermes service/worker sessions. Existing model/lease constraint tests are separate database evidence. Class A alone cannot complete CLD-012 or unblock dependent integration.

- Goal: distinguish unsupported Foundry orchestration from possible Hermes capability.
- Impacted files: Foundry backend/runtime/tests/test_routine_session_constraints.py, runtime/tests/test_routine_session_feasibility.py, runtime/hermes-image/smoke_routine_sessions.py, docs/operations/routine-session-feasibility.md. Cloud contract links the evidence rather than duplicating it.
- Database proof uses real existing models/services on a disposable test database: second binding fails, second unresolved profile lease fails, claim selection cannot admit concurrent same-profile work. Preserve these as passing assertions of current limitations; do not change constraints to make the proof green.
- Deterministic unit proof calls stable_session_identifiers for main and two occurrence IDs: all distinct, retry stable, profile change distinct. Existing coordinator proof records profile serialization explicitly.
- Class B runs the actual pinned Hermes service and its real session/model worker path; it bypasses Foundry admission only for diagnosis, never stubs the Hermes agent/session runner. Use two or more distinct session IDs for one synthetic profile; a held routine operation and main turn must have overlapping intervals, with main response before routine release. Add a second routine session. Inspect returned identity on every event; assert no history leakage with synthetic canaries.
- Class A probes actual offline provider/storage behavior; Class B repeats permitted memory/file operations through actual session tools. The memory/file probe uses the actual installed provider and normal authorized tools. Two separate provider/session instances share the same permitted profile root; write distinct approved facts, read them from a later fresh session, and check a second profile cannot read them. Test simultaneous writes and contention using barriers, bounded timeout and final persisted values. Verify default context_only/background behavior before selecting a supported context; do not enable forbidden tools or disable policy to pass.
- Test same-file read/modify/write with conflicting expected content and independent-file writes through the real supported file tool path. Detect lost updates, corruption or unreported overwrites. Atomic rename/SQLite busy timeout alone does not prove safe logical updates. If the tool has no conflict-aware path, record that specific FND-012 requirement; a harness-only lock is not production evidence.
- Keep the harness bounded (one main and two routines; per-scenario timeout 60 seconds; synthetic local data). Local subprocess/container resources must terminate on failure. Output pass/fail/blocked per property. Fake tests validate the harness and correlation only; never label them a real Hermes proof.
- Exit: attach sanitized output and exact commands/revisions/image digest; identify each unsupported layer. If local pinned image/provider is unavailable, return a named prerequisite and runnable command, mark live feasibility unverified, and do not mark CLD-012 complete.

### Phase 3 - Review and hand off

- Goal: contract and evidence ready for separate CLD-013/FND-012 implementation plans.
- Work: parent task runs separate correctness and simplicity reviews using saved workflow; this worker does not spawn them. Fix contract/evidence findings only. Keep each repo's future delivery change coherent, normally 200-500 lines excluding generated vectors; if larger, split contract from independently runnable evidence, preserving exact contract revision references.
- Impacted files: this plan and its editorial comparison; durable roadmap/routines-handoffs/CLD-012.md; contract/evidence docs. Owning delivery task reads/revision-updates canonical ticket/spec only when reviewed decisions/evidence are ready, then verifies by path. No Nabu changes are made by this planning worker.
- Exit: frozen revision and fixture hash, review dispositions, runnable evidence status, policy resolutions and smallest change map delivered. No deployment or merge.

Exact handoff prerequisites:

1. CLD-013 receives accepted routines-v1 revision/hash and complete management/discovery/schedule vectors; deterministic DST/recovery/skip/replacement behavior; revision/idempotency rules; owner authorization and deletion confirmation; selected main-context insertion/acknowledgement contract and retention/capacity resolution. It may develop against the accepted contract, but integrated release depends on FND-012.
2. FND-012 receives the same contract plus real feasibility output, binding/lease/claim/session-CAS change map and failing capabilities. Its scope includes backend/runtime/models.py and future migrations, services/executions.py, claims.py, sessions.py, approvals.py, runtime contracts, runtime/allies_runtime/foundry.py and hermes.py, and only the demonstrated provider/file conflict boundary. Reconcile FND-010 cancellation before approval replacement; do not broadly rewrite Hermes.
3. Preserve old main-chat binding identity during migration; prove same-conversation exclusion and generation fencing while allowing different conversations on one profile. No profile-wide lock may serialize the full routine against main chat.
4. CLD-013/FND-012 must jointly prove result context in actual main-session model input, 24h wait continuation without prompt restart, cancellation effectiveness before replacement, and no silent replay after terminal failure. Local manager E2E owns product acceptance. A direct adapter probe is not this E2E.
5. If any feasibility or policy item remains unresolved, explicitly distinguish contract sections safe for development from the integration blocker. No new user approval is needed merely to continue authorized engineering work.

## Acceptance Criteria

1. Complete versioned contract, fixtures and compatibility/error rules cover every freeze-matrix area and preserve the accepted specification.
2. Both repos agree on canonical vectors; no existing conversation-message v1 consumer behavior is silently broadened.
3. Evidence cites actual binding, lease uniqueness, claim and session-CAS constraints; runnable database tests reproduce them without production changes.
4. Class A provider/storage results are recorded separately. Class B must run the pinned service/session worker and either demonstrate concurrency or produce a reproducible capability failure with the smallest required change. Missing setup is not a capability failure. Offline-only evidence cannot complete CLD-012; a reproduced Class B failure can complete the investigation only with reviewed remediation prerequisites, while dependent integration stays blocked until that capability passes.
5. Main-context insertion, admission and approval races have structurally checked fixture specifications and mandatory future enforcement tests with owner/result codes; UI-only projection and request acceptance are not called completion.
6. One-time/recurring, timezone capture/clarification, DST, outage recovery, no-overlap, pause eligibility, future-only edits, deletion preservation, discovery and no-terminal-rerun semantics remain intact.
7. No production code, migrations, feature routes, scheduler, interface, deployment or merge enters this episode. Foundry artifacts are portable, generic and privacy-safe.
8. Handoff includes review status, contract revision/hash, exact commands/results, unresolved prerequisites and minimum dependent change boundary.

## Backend Considerations (if applicable)

### Query Optimization Plan

No query changes in CLD-012. Future discovery uses owner filtering before keyset pagination and a single responsible-Ally join; measure per-page query count in CLD-013. Existing claim candidate enumeration is observed, not refactored here. Do not turn a local proof into scheduler throughput work.

### N+1 Prevention

No new production relation access. Contract fixtures require bounded pages; CLD-013 verifies query count remains constant as page size grows. The harness uses a fixed three-session workload and bounded test data.

### Detailed Unit Test Cases

The following are future CLD-013/FND-012 enforcement cases. CLD-012 checks their metadata and hashes only; existing constraint and live capability probes execute separately.

- Happy path: all operation examples, one-time/recurring snapshots, fresh session identity, saved prompt round trip, unchanged result, success/failure outcomes.
- Validation: unknown fields/kinds/version, malformed UUID/timezone, naive timestamps, missing timing, oversize UTF-8 prompt/event, one-time pause, mismatched routine revision.
- Auth/RBAC: wrong owner/workspace/Ally/binding, forged cursor scope, stale approval attempt; no model-supplied owner escalation.
- Idempotency: identical retry, timestamp-only renewal, changed payload collision, duplicate/out-of-order result and stale generation; explicit retry distinguished from delivery retry.
- Failure: terminal failure keeps recurring schedule active but starts no automatic task; cancellation/approval/expiry boundary race; deleted routine result still valid; full prompt rejected rather than truncated.
- Time/order vectors: DST gap/fold, explicit timezone update, late one-time recovery, latest missed recurring recovery, paused/skipped nonrecovery, active main turn plus incoming result and queued user follow-up.

## Frontend Considerations (if applicable)

### Data Path

Not applicable to implementation here. Cloud contracts carry complete prompt/detail, responsible Ally, truthful pending/error state, attributed results and main-chat approval identity. No direct client mutation bypass or run-inspection destination.

### State Management Considerations

No client state changes. Cloud scheduling status remains separate from derived runtime status; show changed state only after persistence. Accessibility and visual treatment belong to downstream design/client work.

## Test Plan

Planning verification consists of source inspection, template coverage, artifact diff and scope review. No feasibility or product test has been run by this planning worker.

Later CLD-012 execution commands, from each repository root after local test environment setup:

```powershell
# Cloud: existing focused regression and new fixture file
make check
make lint
make test APP="allies/tests/test_contract.py allies/tests/test_routines_contract.py"

# Foundry: local test settings only
$env:DJANGO_DEBUG = "true"
make check
make lint
make test APP="runtime/tests/test_cld005_contract.py runtime/tests/test_routines_contract.py runtime/tests/test_routine_session_constraints.py"
uv run --locked --project runtime pytest runtime/tests/test_hermes.py runtime/tests/test_coordinator.py runtime/tests/test_routine_session_feasibility.py
make validate
```

Run constraint/admission concurrency assertions against disposable PostgreSQL as well as ordinary test configuration; SQLite cannot establish row-lock correctness. Supply DATABASE_URL through the local test environment, never through committed credentials. On Windows without make, execute each Makefile recipe in its stated directory with locked uv.

Class A command (new harness --mode offline; no service or model is launched):
```powershell
docker run --rm --network none --entrypoint /opt/hermes/.venv/bin/python --mount "type=bind,source=$PWD/runtime/hermes-image/smoke_routine_sessions.py,target=/tmp/smoke_routine_sessions.py,readonly" allies/hermes-mnemosyne:dev /tmp/smoke_routine_sessions.py --mode offline --timeout-seconds 60
```

Class B service prerequisites and exact execution boundary:

SOL2-003 setup status: no complete local inherited-/init launcher is established by the inspected repository evidence. `docs/operations/hermes-runtime-smoke.md` names `runtime.services.hermes_smoke.ProviderLifecycleSmokeIntegration` and secure bootstrap `available()`, `prepare(run_id)` and `install(run_id, timeout_seconds=...)` hooks. That integration provisions provider resources; it is not a reusable local Docker bootstrap command. `uv --directory runtime run --locked python -m allies_runtime --smoke fake` is offline; `--smoke live` requires the supplied lifecycle/bootstrap dependencies and is not a complete local launcher either. Do not treat these as a working Class B setup or invoke remote provisioning for this episode.

Add exactly one bounded harness launcher to Phase 2 impacted files: Foundry `runtime/hermes-image/launch_routine_probe.py`. This is test tooling only, alongside the existing planned probe. Until it implements and verifies the sequence below, Class B is SETUP_BLOCKED, CLD-012 remains incomplete, and missing setup must not be reported as a Hermes capability failure.

Launcher contract (proposed command, not an existing runnable script):

```powershell
uv run --locked --project runtime python runtime/hermes-image/launch_routine_probe.py --image <resolved-local-image-digest> --credential-ref <opaque-reference> --model-profile-ref <authorized-synthetic-profile-reference> --setup-timeout-seconds 60 --probe-timeout-seconds 60
```

1. Validate a local digest-pinned image against the inspected source label and Docker availability. Resolve only explicitly supplied opaque references through the existing secure credential/materialization boundary. Preflight rejects unavailable resolvers or profile configuration before creating resources. No keys in arguments/environment values/evidence; no fallback to fixture credentials or another provider.
2. Create a fresh owned temporary root and resource ledger, with separate disposable data, socket and harness paths. Reuse existing `profile_store` validation/materialization and profile-local mode-0600 API_SERVER_KEY behavior; do not invent a second production provisioning flow. The launcher must supply the missing local bootstrap/socket producer using existing resolver protocol. If that cannot be done within the one launcher, stop and report the exact prerequisite instead of broadening scope.
3. Launch the resolved image with `docker run --detach --name <unique-owned-name> --entrypoint /init`, no positional command override, no published ports and a dedicated local network. Mount disposable data at `/opt/data`, the owned credential socket directory at `/run/allies-runtime`, and the probe/runtime code read-only at `/tmp/smoke_routine_sessions.py` and `/tmp/allies-runtime`. Pass only `HERMES_CREDENTIAL_REF=<opaque-reference>`, `HERMES_CREDENTIAL_SOCKET=/run/allies-runtime/hermes-credential.sock` and `HERMES_ORIGIN=http://127.0.0.1:8642` for these credential-related settings. Existing materialized profile configuration supplies model routing; secret values stay in protected files/socket responses. Record resolved mount destinations and image identity without exposing host-sensitive paths.
4. Complete secure profile activation before probing. Run readiness and probe inside this container's network namespace using the profile/bootstrap resolvers, real model transport and exact readiness conditions below. Set probe Python import path to `/tmp/allies-runtime`; invoke `/opt/hermes/.venv/bin/python /tmp/smoke_routine_sessions.py --mode service --timeout-seconds 60` only after authenticated readiness and the bounded real-model preflight pass.
5. Report setup, readiness, model preflight, capability assertions and cleanup separately. Distinguish SETUP_BLOCKED, READINESS_FAILED, MODEL_PREFLIGHT_FAILED, CAPABILITY_FAILED and CAPABILITY_PASSED. Stop/remove only the ledger-owned container/network and temporary files, including partial setup, within a bounded cleanup timeout; incomplete cleanup is reported explicitly. Do not store secrets or prompts in Docker command logs, exception text or evidence.

Launcher tests use a mocked process runner solely to verify argument redaction, owned-resource cleanup, timeout handling and refusal to run the probe before readiness. They are not Class B evidence. The delivery task must record a verified end-to-end launcher invocation and sanitized output before replacing SETUP_BLOCKED with a capability result. This bounded launcher is the explicit alternative to claiming an existing bootstrap command that has not been established.

- Use the digest-resolved local build of runtime/hermes-image/Dockerfile with source pin 36cb5ae5530a75def7df3195e49b7a4aa2add482. Its production service entrypoint is inherited /init and upstream dispatch; do not override it with Python or the approval smoke. Run the service in an isolated local container with disposable /opt/data profile storage and existing secure profile materialization. A same-network-namespace probe reaches http://127.0.0.1:8642; never expose that port publicly.
- Materialize one synthetic profile using existing profile_store schema/config, its mode-0600 API_SERVER_KEY file, authorized tools and memory policy. Use the existing opaque HERMES_CREDENTIAL_REF/socket resolver for bootstrap health, and profile credential resolver for session calls. No credential in CLI arguments, fixtures or logs. No default/fake resolver is acceptable for Class B.
- Model transport is the materialized profile's real authenticated HTTPS model provider, model gpt-5.6-luna as recorded in runtime/README.md. provider and optional base_url come from that existing profile configuration, with its existing secret provisioning; require a successful bounded model turn before timing assertions. Do not invent a provider endpoint, switch credentials or replace GatewayRunner/model execution with a fixture. Missing permitted model transport is a setup blocker.
- Readiness uses HermesClient.health_detailed(): authenticated GET /health/detailed with status ok/ready/healthy, or degraded only when readiness.checks.gateway.status=ok and state=running, matching runtime/allies_runtime/__main__.py:probe_readiness. Poll for at most 60s with existing request timeout 5s. A 200 alone is not readiness.
- Proposed new harness entrypoint is /opt/hermes/.venv/bin/python /tmp/smoke_routine_sessions.py --mode service --timeout-seconds 60, executed inside the running service container. Mount the repository runtime package read-only and use HermesClient.create_profile_session/stream_profile with three distinct stable session identities and model gpt-5.6-luna. Keep actual service/agent workers intact; barriers are synthetic task/tool inputs, not replacements for workers.
- Implementation supplies --mode offline and --mode service in the single planned harness file. The service command is: docker exec routines-cld012-hermes /opt/hermes/.venv/bin/python /tmp/smoke_routine_sessions.py --mode service --timeout-seconds 60. Container name is local harness configuration; launch the resolved image using its inherited /init with that name and read-only harness/runtime mounts. The existing bootstrap must populate its credential socket/profile files before probe execution. Record resolved image digest, readiness, model transport class and sanitized results, not secrets.
- The SOL2-003 launcher owns the actual unique container name and replaces that illustrative fixed name. Its verified local bootstrap, rather than an assumed existing command, is a prerequisite for this sequence.
- Class B requires overlapping real worker intervals for main plus distinct routine sessions, main completion while a routine remains active, correct session/event attribution, isolated canary histories, and permitted memory/file observations. Same-profile backend admission remains separately demonstrated as blocked by existing binding/lease constraints. A real Hermes rejection/serialization is a reproducible capability failure; an unavailable credential/image is merely blocked setup.
- Use temporary resources and bounded provider spend (one preflight and the fixed session scenarios, no automatic model retries). Stop owned processes and clean owned temporary files on timeout. No production provider configuration is changed.

Regression basis: retain both CI workflows, secret scanning and engineering-policy reviews; Cloud CI checks lockfile/migrations/full pytest/auth coverage/Ruff and PostgreSQL concurrency; Foundry validates backend/runtime, image dependencies and configuration. Do not weaken these checks or claim them passed from inspection.

Manual review: compare accepted requirements against matrix/fixtures; inspect exact source/image revisions; verify no runtime feature diff; verify both fixture hashes; inspect safe failure output; confirm cleanup is restricted to harness-created resources. Run git diff --check in both worktrees.

## Risks and Mitigations

| Risk / open engineering decision | Mitigation / owner / revisit condition |
| --- | --- |
| Removing one binding leaves profile-wide lease admission unchanged | FND-012 must change binding, lease constraint, claim lookup and session receipt scope together, retaining fencing; acceptance requires actual concurrent claim proof |
| Distinct session keys falsely imply shared memory correctness | Test actual pinned provider instances and later-session recall; background skip/context_only are existing safeguards, not flags to bypass |
| Shared file read/modify/write loses updates | Detect with real tool-path probe; record smallest conflict/serialization boundary around the operation, never a whole-profile execution lock |
| Five-minute approvals cannot satisfy accepted 24h waits | Routine-specific wait contract and durable continuation with exact cancellation race; do not globally relax existing schema or restart the prompt |
| Main UI result never enters Hermes context | Explicit insertion receipt/watermark and next-turn input verification; downstream dispatch waits for pending insertion, not for routine completion |
| Schedule grammar/precision, new limits or retention lack policy evidence | Phase 1 resolves engineering choices with citations. No product decision is reopened; new user-visible restrictions go to Product only if actually required. Cleanup stays outside this episode |
| Harness passes by faking the difficult layer | Separate constraint/unit, actual provider storage, direct Hermes session and integrated product evidence; missing prerequisites remain blocked/unverified |
| Public Foundry content leaks private context | Generic synthetic fixtures and portable paths; sanitized evidence only |
| Contract rollout reaches only one consumer | Freeze revision/hash, preserve old v1 semantics, reject unsupported kinds, require both integrations before feature enablement |

Rollback/fallback: this episode adds documentation/test/harness artifacts only. Revert those specific additions if withdrawn; there is no data migration or production switch to undo. Failed probes leave existing protections intact and produce required-change evidence. Never use profile serialization or disabled authorization as a fallback that claims the accepted concurrency requirement is met.


## Sol revision trail

Revision 2, 2026-09-09: SOL-001 through SOL-005 applied in the explicitly named sections above. Original review remains unchanged at worker-results/cld-012-sol-review.md with verdict Needs revision. Disposition: addressed in plan, pending independent re-review; not reviewer-accepted. Full template and HTML=no retained. No production implementation or Nabu changes. Editorial pass preserves requirement strength and distinguishes proposed contracts from implemented behavior.

Revision 3, 2026-09-09: review worker-results/cld-012-sol-review-2.md accepts the prior SOL-001/SOL-004/SOL-005 corrections and requests three further changes. SOL2-001 adds revision/generation-fenced resume race outcomes and PostgreSQL vectors; SOL2-002 adds durable action identity, monotonic dispatch/ambiguity states and crash receipts; SOL2-003 explicitly records missing local launcher as SETUP_BLOCKED and scopes one bounded launcher artifact. These changes were implemented in the plan and the resulting contract/feasibility artifacts were independently reviewed.

Historical execution freeze (revision 3; superseded), 2026-09-09: at that checkpoint Cloud and Foundry carried byte-identical routines-v1 revision-3 contract, fixture, and lock artifacts. This record is historical only; no mutable worktree is frozen. Cloud contract tests (5), Foundry contract/constraint tests (8), and runtime feasibility tests (20) pass; the full Foundry runtime suite passes 558 tests with 5 skipped. The pinned Class A evidence remains INCONCLUSIVE_REVIEW_REQUIRED after one failure and two passes; Class B remains SETUP_BLOCKED because secure inherited-/init setup and deterministic server-observable barrier evidence are unavailable. Final independent review `worker-results/cld-012-sol-code-review-final-3.md` reports no P0/P1 findings. No production implementation or live capability claim is made.

Contract correction candidate (revision 4), 2026-09-09: the independent PR review found three P2 defects in the revision-3 frozen artifacts: a duplicate `event_sequence` member in the result receipt, an unnamed/missing dispatch occurrence disposition in the complete command example, and an undefined `routine.outcome` event kind. The Cloud candidate removes the duplicate, names `occurrence_disposition`, removes the undefined event kind, increments `content_revision` to 4, and refreshes both artifact hashes. Foundry must re-vendor the exact accepted candidate before the downstream handoff is considered byte-identical. The Class A and Class B evidence dispositions are unchanged.

Contract correction candidate (revision 5), 2026-09-09: the subsequent independent PR review found three P2 fixture inconsistencies: weekly create/update receipts pointed to Thursday instead of the frozen Mon/Wed/Fri schedule, the result event preceded the approval event and reopened a terminal run in the example timeline, and the correlation inequality list omitted `main_conversation_id != execution_id`. The Cloud candidate corrects those vectors, increments `content_revision` to 5, and refreshes both artifact hashes. Foundry must re-vendor the exact accepted candidate before the downstream handoff is considered byte-identical. The Class A and Class B evidence dispositions are unchanged.

Contract correction candidate (revision 6), 2026-09-09: CR-001 requires a Cloud-owned V14 / Phase-2 deletion-confirmation boundary. The Cloud candidate defines the opaque one-shot confirmation challenge, exact workspace/owner/Ally/binding plus main-conversation/routine/revision binding, atomic consume/delete behavior, stable missing/stale/replayed/foreign result codes, and concrete positive/negative fixture vectors with zero-mutation assertions. It increments `content_revision` to 6 and refreshes both artifact hashes. Foundry was not edited in that scoped correction. The revision-6 candidate was never accepted or frozen and is now superseded by revision 7; no mutable worktree is frozen. The R4/R5 corrections and the Class A/B evidence dispositions remain unchanged.

Contract correction candidate (revision 7), 2026-09-09: the final Sol review adds three P2 corrections to the revision-6 candidate: raw `confirmation_ref` is transport-only and absent from downstream logs/traces, with correlation limited to a non-reversible keyed digest; workspace_id, ally_id, and cloud_binding_id each receive independent wrong-scope vectors and stable zero-mutation codes; and the historical execution-freeze wording is superseded. Final Sol review accepted the Cloud candidate, which increments `content_revision` to 7 and refreshes both artifact hashes. Cloud head `5d483dd7ac65e21fc18b2dad45837140adcbb4b6` and Foundry head `4517f6ef68b54b9c16760eb74bea1471aa8c3cde` are pushed and carry the byte-identical tuple with `content_sha256=0f3ba80c9331914c18d5ff4b7b0358d2afd832a12f7d068213ab1a49f8f32fbf`, `fixture_sha256=4b6ea7e917ef7df1e5a50240e6c2a87c0ba6437340de5ff750ea61697ebe6492`, and `lock_sha256=8027382ca5494ec41a54eab18f3f534228a89d63bf31cf6c0112502d46d92bc2`. No mutable worktree is frozen. The prior R4/R5/CR-001 corrections and Class A/B evidence dispositions remain unchanged; no merge, deployment, or live capability claim is made.

Contract correction successor (revision 8), 2026-09-09: CLD-012 corrects the result-event fixture omission without altering revision-7 history. `routine.result.title_snapshot` is now required and must exactly equal the immutable title snapshot accepted in `routine.dispatch`, alongside the already-required matching routine revision. This successor increments `content_revision` to 8 and refreshes the contract, fixture, and lock hashes. Its predecessor is Cloud head `de0835157618c58c7fd353e2ae3197cb6c409cb4` with `content_sha256=0f3ba80c9331914c18d5ff4b7b0358d2afd832a12f7d068213ab1a49f8f32fbf`, `fixture_sha256=4b6ea7e917ef7df1e5a50240e6c2a87c0ba6437340de5ff750ea61697ebe6492`, and `lock_sha256=8027382ca5494ec41a54eab18f3f534228a89d63bf31cf6c0112502d46d92bc2`. The accepted intermediate successor is Cloud head `1897ce64d431eddf84086190cab59e653ea35704` and Foundry head `ee0846164b7f4a0a3c03ef783eca6da24f0285ab`, carrying `content_sha256=9e355d7b8ead4d675cd79fef766faa634069117acb0e9927ad02efd8fe202cdc`, `fixture_sha256=70028e3e1935fc79b4d6bd4127facb4501c0a97492a808345921f423ec55cec8`, and `lock_sha256=488bad850829212951991f78e34cfd00b3f575969385a35af36761a87c7278e8`. Subsequent review identified three additional P1 inconsistencies, so revision 9 below is the active successor; revision 8 history is preserved. No merge, deployment, or live capability claim is made.

Contract correction successor (revision 9), 2026-09-09: preserve the revision-8 title-snapshot correction and correct three additional boundary inconsistencies. The fixture now defines schedule generation starting at 1 and increments exactly once for schedule/timezone changes and effective pause/resume, with management receipts, resume metadata, and dispatch aligned at generation 1/2/3/4. Constraint feasibility cases use `expected_constraint_outcome` for Foundry-owned current database/lease/claim evidence rather than pretending those implementation-only values are public result codes. Correlation separates Cloud-required dispatch fields from Foundry-assigned `execution_id`, `attempt_id`, and `generation` in the dispatch receipt/events. This successor increments `content_revision` to 9 and refreshes both artifact hashes. Its predecessor is the accepted revision-8 tuple above; no revision-8 bytes are rewritten. The accepted successor is Cloud head `e303c14ced1d3028ebb556a0664057737aa82f23` and Foundry head `cffa731573ee9c6ae25b8cfca496dca28a74b512`, carrying `content_sha256=891a9eb9932be9e7826baaf313ded7c6fd4f8526a661e0be5a83b6118fee76de`, `fixture_sha256=259577de2ea7e8343b266995767496d359aef196f1a19d6841e67ef133fb3343`, and `lock_sha256=a9dbd56d70bc8e63c74988a85e2121527ab54d398d04c086538fc2f3e4f107de`. Fresh Sol review found no actionable P0/P1/P2 findings. No merge, deployment, or live capability claim is made.

Contract correction successor (revision 10), 2026-09-09: preserve the accepted revision-9 wire contract and correct two fixture-owner metadata defects found in the fresh current-head Enkii review. The `race-resume-due` vector now starts from the reachable effective-pause generation 3 and fences resume at generation 4, while retaining `STALE_DUE_CANDIDATE` and the same zero-write behavior. The `dispatch-retry` vector retains `OCCURRENCE_REPLAY` and is assigned to its Cloud owner, CLD-013, matching the public result-code table and plan owner mapping. No schema field, required dispatch/receipt field, result code, or runtime behavior changes; only the immutable tuple advances to `content_revision=10`. The accepted revision-10 artifacts are Cloud head `876766444dab5411e9b0442cae04755358dc980d` and Foundry head `62a9f58e725af52482bcba70a40a0ab498e17774`, carrying `content_sha256=d1a75807463cb16c7306acad04569a32502b333d42bbc947feb78cc82d5ec24d`, `fixture_sha256=7d5b1e9cb7b2691719c89737de09058013074914bd6b3bf50391321559f59d28`, and `lock_sha256=90331cf4d09fbb0e851bb0da1a279fc74ed63c3e5a0b04c9b8e1067ada758098`. Fresh independent Sol review `worker-results/cld-012-sol-code-review-final-10.md` accepts revision 10 with no actionable P0/P1/P2 findings. Cloud contract tests (7) and Foundry contract/constraint tests (8) pass; the reviewer additionally verified Cloud Django/migration/Ruff, Foundry contract/backend/runtime, lock, Django/migration/Ruff, and byte-identical artifacts. Current-head hosted Enkii reruns must remain green before merge. Class A remains `INCONCLUSIVE_REVIEW_REQUIRED`; Class B remains `SETUP_BLOCKED`. No merge, deployment, or live capability claim is made.
Contract correction successor (revision 11), 2026-09-09: preserve the accepted revision-10 metadata corrections and add the saved recurring schedule, including its IANA timezone, to the immutable `routine.dispatch` command snapshot. The dispatch fingerprint, fixture/lock hashes, and content revision advance to 11; the normative document’s embedded `content_revision` is aligned with the fixture and lock, and both Cloud and Foundry assert that identity. No production route, model, migration, scheduler, runtime behavior, or result code changes. The accepted revision-11 artifacts are Cloud head `55e251fd482404cee2e19fbfc149e86e67816762` and Foundry head `6091df90650006c6b54c782d1e00d485e80ec8c4`, carrying `content_sha256=a343017252af242563b5a7a127f0b985d6dade73364f3dc1e207060dc15b7a36`, `fixture_sha256=3b903d65225dde3aef9a03d0c7feffff21c1b38acba8dd2392b9adf6dc83019d`, and `lock_sha256=5c7d945417f9e265ed3275d21f12c03c5d856985fe0998dab3273df175be3bbf`. Fresh independent Sol review `worker-results/cld-012-sol-code-review-final-11.md` accepts revision 11 with no actionable P0/P1/P2 findings. Cloud contract tests (7) and Foundry contract/constraint tests (8) pass; strict hash, byte-parity, duplicate-key, and diff checks pass. Current-head hosted Enkii reviews must remain green before merge. Class A remains `INCONCLUSIVE_REVIEW_REQUIRED`; Class B remains `SETUP_BLOCKED`. No merge, deployment, or live capability claim is made.
Contract correction successor (revision 13), 2026-09-09: revision 12 was not accepted after independent review found that its `lifecycle-terminal` vector still used the run lifecycle input while asserting an action-attempt reconciliation state. Revision 13 points the vector to `approval.crash_vectors`, requires the exact `unknown -> manual_reconciliation` transition, stops automatic processing, declares `ACTION_MANUAL_RECONCILIATION` in the stable result-code evidence, and adds Cloud/Foundry structural assertions. The exact revision-13 artifacts are Cloud normative artifact commit `fceba9c148d77c7d4bdc82bd5a0f376a5133a2b4` and Foundry follow-up head `b161436ab0c9b1ceda9ef2341ea3409939bebb44`, carrying `content_sha256=63215a54e80dd638167b6b579b55d41c77230525c5b9a0f944a58bef377cbb4e`, `fixture_sha256=8a2ce0b008fd8e681fe08c1b494a5ebf1b2477991611b18360e1a2460f7472ef`, and `lock_sha256=be76f5ade73a7e917a7eb0a69eab0267498cf64b7ca10653b2e820940691f7ea`. The bounded feasibility follow-up classifies post-preflight capability failures as `CAPABILITY_FAILED` and gives them precedence over a blocked server barrier; four regression assertions pass. Fresh independent Sol review `worker-results/cld-012-sol-code-review-final-13.md` accepts revision 13 with no actionable P0/P1/P2 findings, including the follow-up. Cloud contract tests (7), Foundry vendor contract tests (5), and Foundry focused feasibility tests (26) pass; strict JSON, duplicate-key, hash, byte-parity, newline, syntax, and diff checks pass. Current-head hosted Enkii reviews and CI must remain green before merge. Class A remains `INCONCLUSIVE_REVIEW_REQUIRED`; Class B remains `SETUP_BLOCKED`. No merge, deployment, or live capability claim is made.
Contract correction successor (revision 14), 2026-09-09: preserve the accepted revision-13 schedule, lifecycle/action-attempt, and feasibility corrections and align every routine Foundry envelope with the established v1 `foundry-service` identity literal. Revision 14 recomputes the four affected canonical fingerprints, advances `content_revision` to 14, refreshes the contract/fixture/lock hashes, and re-vendors exact bytes to Foundry. The exact revision-14 artifacts are Cloud head `3af3da24e8f8e516861f34ddaa85442bbe25eaa1` and Foundry head `2626076973cfa52eec00eed265ab045b8b7b9ac5`, carrying `content_sha256=f05ab0a1baf63551f426c288f0144484c813b5cda535bf1cf5d614fb7a22ea84`, `fixture_sha256=2660d30ee73e8f3cebf94340ea1169019e3c937fd01a30bff6d0e16ecd54ab35`, and `lock_sha256=9005d25a8186d325a2efdcc42ec9e6cfe4d2d6c445088c9ba7a6b4d87429cb04`. Fresh independent Sol review `worker-results/cld-012-sol-code-review-final-14.md` accepts revision 14 with no actionable P0/P1/P2 findings. Cloud contract tests (7), Foundry vendor contract tests (5), and Foundry focused feasibility tests (26) pass; strict JSON, duplicate-key, hash, byte-parity, newline, syntax, and diff checks pass. Current-head hosted Enkii reviews and CI must remain green before merge. Class A remains `INCONCLUSIVE_REVIEW_REQUIRED`; Class B remains `SETUP_BLOCKED`. No merge, deployment, or live capability claim is made.
