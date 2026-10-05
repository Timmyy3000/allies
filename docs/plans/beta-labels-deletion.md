# Beta labels and ally deletion plan

## Using this template

Route: full. HTML required: no. Status: implementation complete and undergoing PR checks, with accepted review simplifications SIM001 and SIM002 incorporated. The owner approved retaining a content-free deleted-ID marker; ADV005 was withdrawn. Labels are merged into the refreshed Cloud and Interface dev bases; preserve their independent [fast plan](beta-labels.md). Deletion is not merged or deployed.

## Feature Overview

Cloud will generate short, editable job labels at creation and keep labels hidden until the owner enables them. Web will expose a minimal Ally Settings surface. Confirmed deletion will remove the selected ally's operational data from Cloud and Foundry only after runtime, file and database cleanup are verified. Deletion preserves other allies and shared workspace resources.

This feature serves workspace owners. Sources are user items 5, 6, 7, the task brief, Enkii v1.3.0 release, and Nabu's index, decision log, continuity specification and allies-first requirements inspected by the orchestrator. Cloud owns product truth; Foundry owns runtime truth; web calls Cloud only. The user's `<ally name> - deletes me` phrase supersedes the older proposed confirmation. No timer is required.

## Plan Hygiene and Evidence Boundaries

Paths below are relative to the named repository and were inspected unless marked new. Use disposable synthetic two-ally fixtures. Validation must use synthetic allies. Keep jobs, labels, names, confirmation phrases, content, private paths and credentials out of logs. Record stage, operation identity, timing and safe error codes only.

| Repository | Evidence | Implication |
| --- | --- | --- |
| All | AGENTS, ENGINEERING_STYLE, README and CI; backend Makefiles/pyprojects; Interface package scripts | Preserve owner boundaries, durable outcomes, bounded work, reviews, locked tools and existing gates. |
| Interface | Full PLAN_TEMPLATE; Home, shared Cloud mapper/client and ally queries | Label fields must pass through shared schemas/cache. The implemented label settings surface is the deletion entry point; preserve its saved-state and cache safeguards. |
| Cloud | `backend/allies/models.py`, `services/creation.py`, API schemas/controllers, Foundry gateway | Creation already deduplicates and persists provisioning; retrieve repairs conversation state, which deletion must fence. Labels exist on the refreshed base; deletion lifecycle fields are new. |
| Cloud | `backend/activities/services/approval_explanations.py` | Reuse quick Responses conventions: Luna, reasoning none, store false, strict schema, bounded I/O and persisted claim. |
| Cloud | `backend/files/services/cleanup.py`, file/chat/activity/routine models | File tombstone and bounded object cleanup exist; many PROTECT edges require explicit child purge. Shared storage accounting must survive. |
| Foundry | `backend/runtime/services/profiles.py`, API register, runtime models | Cleanup fences epoch and moves leases to STOPPING; deprovision receipt currently retains profile and related rows. |
| Foundry | Runtime `profile_store.py`, `reconciliation.py`, `files.py`, Mnemosyne provider/tests | Existing cleanup removes profile tree, publication spools and temporary siblings but retains content-free tombstone. Mnemosyne is profile-isolated. Runtime reconciliation checks active leases before cleanup. |
| Orchestrator evidence | Aphrodite home `313:1159`, chat `315:1612`; Enkii action/release and workflow diffs | Reuse 40x40 header controls, Open Runde and existing dark tokens; no dedicated label/deletion design was verified. Enkii v1.3.0 inputs remain compatible; pins-only YAML/diff checks passed. |

Cloud S3 deletion calls delete_object without a VersionId. Object versioning, infrastructure backups/logs, external provider retention and actual deployed process quiescence remain unverified. Do not promise all-copy or instantaneous erasure.

## User Stories

1. As an owner, I want a short editable label and control over its visibility.
2. As an owner, I want exact confirmation before permanent deletion and honest progress if cleanup fails.
3. As an owner, I want my other allies preserved and deleted content unable to return after retries or restart.

## Scope

### In Scope

The complete labels/visibility slice in `beta-labels.md`; minimal web settings and confirmed deletion; Cloud/Foundry admission fences, active-work quiescence, file/memory cleanup, relational purge and retry receipts; contract/test/migration updates; Enkii v1.3.0 pins.

### Out of Scope

Name/job/personality editing, Account redesign, native settings UI, historical label generation backfill, generic deletion or AI frameworks, workspace/machine/volume removal, new infrastructure or workflow permissions, merge/deploy, and live destructive validation.

### Dependencies and Assumptions

Use existing owner PROFILE_WRITE capability plus workspace ancestry and session/CSRF rules. Existing allies get empty labels and false visibility without provider calls. Labels do not change Foundry seeds or creation fingerprints. Labels can proceed independently. Deletion requires the compatible runtime capability below. The content-free marker is authorized; no further retention decision is needed. Backup or provider policy changes are not silently added to this feature.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Proposed symbol/signature | Inputs and validation | Return | Side effects/errors |
| --- | --- | --- | --- | --- |
| Cloud new `backend/allies/services/labels.py` | `generate_creation_label(*, ally_id: UUID) -> None`; `update_label_settings(*, user, workspace_id, ally_id, label, show_label, revision) -> Ally` | One pending claim; owner, label bounds, matching revision | None/updated Ally | Bounded provider call outside locks; conditional persist prevents edit overwrite. Details in fast plan. |
| Cloud new `backend/allies/services/deletion.py` | `request_ally_deletion(*, user, workspace_id, ally_id, confirmation) -> DeletionOperation` | Owner, ancestry, locked current name, exact confirmation | Durable operation | Persist fence/file tombstone before remote I/O. |
| Cloud same new module | `reconcile_ally_deletion(*, operation_id: UUID) -> DeletionOperation` | Bounded exclusive operation claim | Progress/receipt | Same Foundry request identity, object verification, ordered purge. |
| Foundry profiles service or focused new purge module | `request_profile_deletion(*, workspace_id, ally_id, binding_id, operation_id) -> ProfileDeletionReceipt` | Service auth, exact scope/identity | Pending/complete/repair | Reuse cleanup lifecycle; persist fence even when profile never provisioned. |

### API and Transport Contracts

These new v1 routes are proposals. Public responses use current success_json/error_json envelopes. Labels append `label`, `show_label`, `settings_revision` to existing create/list/detail responses, as specified in the fast plan. Add `deletion_state: active | pending | repair_required` while the Ally exists. No pagination changes. Keep the deleting ally visible as a disabled progress item and deny content access and mutations.

| Consumer | Method/path | Auth/request | Success | Error/retry |
| --- | --- | --- | --- | --- |
| Web | PATCH `/api/v1/workspaces/{workspace_id}/allies/{ally_id}/settings` | Session, PROFILE_WRITE, origin/CSRF; settings payload | 200 updated Ally | 401/404/409/422; stale revision preserves draft. |
| Web | POST `/api/v1/workspaces/{workspace_id}/allies/{ally_id}/deletion` | Same owner checks; exact confirmation | 202 pending or 200 complete receipt | Mismatch 409 has no side effects; 401/404/422/503. Accepted repeats resume same operation. |
| Web | GET same deletion path | Authorized workspace and target or minimal terminal receipt | 200 progress/complete | 401/404; bounded poll. |
| Cloud | POST `/api/v1/internal/profile-deletion` | Existing Cloud service token; strict version/scope/identity | 200 typed receipt | 409 identity conflict, 422 invalid; retry 429/5xx/timeout with same identity. |

Representative settings request and appended response fields:

```json
{"label":"chief of staff","show_label":true,"settings_revision":0}
```

```json
{"label":"chief of staff","show_label":true,"settings_revision":1,"deletion_state":"active"}
```

Public deletion POST request and POST/GET response data inside existing envelope:

```json
{"confirmation":"Demo Ally - deletes me"}
```

```json
{"ally_id":"00000000-0000-0000-0000-000000000001","operation_id":"00000000-0000-0000-0000-000000000002","state":"pending","retryable":true,"safe_error_code":""}
```

This public example shows a pending response, where operation_id is required. Complete responses omit operation_id after compaction, as shown in the retained-marker contract below. `state` is pending, complete, or repair_required. Only complete is success. Internal bare JSON request/response follows provisioning conventions:

```json
{"version":1,"ally_id":"00000000-0000-0000-0000-000000000001","workspace_id":"00000000-0000-0000-0000-000000000003","binding_id":"00000000-0000-0000-0000-000000000004","operation_id":"00000000-0000-0000-0000-000000000002"}
```

```json
{"version":1,"binding_id":"00000000-0000-0000-0000-000000000004","operation_id":"00000000-0000-0000-0000-000000000002","state":"pending","receipt_id":null,"safe_error_code":""}
```

A non-compacted internal completion carries a bounded opaque receipt_id. After compaction the scoped marker itself is the completion evidence; Cloud records its canonical opaque target ID through the existing file receipt bridge. Foundry derives profile identity/digest; Cloud supplies no paths. First acceptance persists canonical deletion identity. Transport retries preserve the current attempt tuple; explicit repair resume creates a new attempt under the same parent operation. A service 404, timeout, malformed receipt or partial cleanup cannot mean complete. Public completed replay uses the approved scoped deleted-ID marker.

### Schema and Data Shapes

| Model | Proposed fields/defaults | Invariants/compatibility |
| --- | --- | --- |
| Cloud Ally | `label: str = ""` max80; `show_label: bool = false`; `settings_revision: int = 0`; generation state pending/claimed/complete/unavailable | Old rows unavailable/empty/false; new create pending. Actual label/visibility changes increment revision; identical saves are no-ops. Only changed label text ends generator ownership. Empty labels require false visibility. Empty or 2-3 word manual labels, no controls/newlines. |
| Cloud new DeletionOperation | UUID, workspace FK, target ally UUID independent of deleted row, binding UUID, stage, attempt/lease/due fields, safe code, Foundry receipt | One per target; index identity/due work. No confirmation/name/job content. Compact transient operational fields to the scoped deleted-ID marker on completion. |
| Foundry new ProfileDeletionReceipt | Workspace/binding/profile/operation IDs, lifecycle epoch, state, receipt/safe code | Independent of purged profile. Provisioning/deletion share lock/fence. Compact transient operational fields to the scoped deleted-ID marker on completion. |
| Shared client | New fields mapped to camelCase | Missing old-server fields default empty/false/0/active. Unsupported writes show error. Never derive label from job. |

The accepted fast label plan owns the detailed generation contract, including empty-label visibility restrictions, identical-save no-ops and one Luna path without whole-job passthrough: updated_at-based 120-second stale-claim recovery, atomic revision increment on generated writes, named credential, 6/workspace and 30/global per-minute budget, four global provider slots, privacy-safe telemetry, and roster-only label presentation with existing chat job subtitle preserved. Role preservation uses prompt/output evidence, not a heuristic extractor or a perfect semantic guarantee. The independent labels plan and implemented code own generation mechanics; deletion only adds its admission check. New deletion operations reuse existing task/lease conventions. Do not hold locks over provider/network/storage I/O. Generation uses one persisted claim, one bounded Luna attempt, and conditional update; a crash after claim becomes unavailable rather than another potentially billed request. Pending scan recovers broker loss. No automatic historical backfill or provider retry.

### Frontend Interaction Shapes (if applicable)

| Entry/action | State transitions | Behavior |
| --- | --- | --- |
| `openAllySettings(allyId)` (new) | Closed/open | Focused Home dialog/sheet with label, Show label and Delete ally; Account remains separate. |
| Save settings | Dirty/saving/saved/error | Shared client PATCH; preserve draft on failure/409; announce successful persistence. |
| Confirm deletion | Idle/submitting/pending/repair/complete | Exact case-sensitive phrase; server authoritative; 202 displays progress. Closing after acceptance does not cancel deletion. |
| Roster | Active/deleting/removed | Show enabled label beneath name. Disable target interactions during cleanup; remove only after complete. |

Use named dialog, focus containment/restoration, explicit labels, keyboard/cancel, inline errors and status announcements. Initial focus must not be on the destructive button. On completion close target stream, remove only its query/draft state and select roster/empty state. Abort stale requests and prevent late responses restoring deleted content.

### Deletion lifecycle and retained marker

The permanent marker contains only opaque tenant and target identifiers and a deleted state. Cloud retains `(workspace_id, ally_id, deleted=true)`; Foundry retains `(workspace_id, profile_id, deleted=true)`, unique on that scoped profile identity. The local runtime retains only its opaque profile key and a permanent deleted flag. Foundry validates the incoming binding/ally tuple initially, derives the canonical profile UUID using the existing provisioning convention, and discards binding/ally IDs from its terminal marker. This small variant of SIM001's binding-key suggestion follows `ensure_runtime_profile`, which receives the profile UUID: every admission path can check one canonical ID without reversing UUID5 or retaining redundant identity mappings. Pending operations may hold epochs, random operation/receipt IDs, deadlines, safe errors and scoped object keys for recovery. Delete these transient records on completion. Terminal records retain no name, job, conversation, file, memory, seed fingerprint or content-derived digest.

Keep relational purge as a private helper inside the single Foundry deletion coordinator after its quiescence/absence checks. SIM002 removes the separately exported finalize_profile_deletion contract; there is no second public finalization boundary or scheduler.

Cloud completes its purge and marker transaction only after Foundry completes. Foundry may then compact its operation to the marker: an authenticated request for that exact scoped identity returns complete even if the original response was lost. Cloud POST/GET after completion returns `{"ally_id":"<uuid>","state":"complete","retryable":false,"safe_error_code":""}`; operation_id is present only for nonterminal operations. Authorize workspace membership/capability before looking up the marker. No old name or confirmation is stored for replay. An absent row without a marker is 404, never proof of deletion.

Markers permanently disallow reuse of the target/binding UUID. Restore procedures must reconcile deletion markers before serving restored application data. Backup erasure remains a separate documented retention boundary.

### Profile quiescence contract (ADV-DEL-001)

Add the lifecycle extension through Foundry's existing pinned Hermes image patch convention: new `runtime/hermes-image/patches/profile-quiescence.patch`, an image smoke test, provider close hooks, and the existing runtime Hermes client, reconciliation, worker and wire schemas. The inspected image pins Hermes source `36cb5ae5530a75def7df3195e49b7a4aa2add482`; preserve build-time patch checks and image identity tests. No shared listener, machine, volume or s6 service termination is part of ally deletion.

Proposed internal endpoint: POST `/v1/profiles/{profile_key}/quiesce`. It accepts no filesystem paths. Enable deletion only for an image advertising profile_quiescence_v1. Example request:

```json
{"version":1,"operation_id":"<uuid>","attempt_id":"<uuid>","lifecycle_epoch":7,"request_digest":"<sha256-of-control-fields>","machine_generation":3,"runtime_start_epoch":9,"hermes_instance_id":"<boot-uuid>"}
```

The response echoes these identity fields and adds state (quiescing, quiesced or repair_required) and safe_error_code. Quiesced additionally requires active_runs=0, active_profile_io=0, open_profile_stores=0 and owned_children=0. HTTP 202 means quiescing; 200 requires completed closure; 409 rejects stale identity; unauthorized/malformed responses fail closed. Calls have a 5-second connection and 30-second total bound. Retry the identical command after timeout. Only the current Hermes boot identity may acknowledge closure.

This is a listener-level control route, registered before ordinary profile routing/materialization. The runtime calls its existing `HermesClient._credential()` resolver using settings.credential_ref, not `_profile_credential(profile_key)`. Hermes validates the bearer token against its listener `_api_key` with a constant-time comparison and rejects missing configuration. Ordinary `_check_auth` deliberately resolves a named profile's API_SERVER_KEY and cannot authenticate this retry after the profile tree is removed; do not weaken that normal data-route behaviour. The control handler authenticates first, validates the current runtime/machine/attempt scope, then resolves the opaque target key without opening profile stores. The existing listener credential remains in shared runtime credential storage, never in a deletion marker. An absent tree with the matching permanent local marker can replay verified absence and fresh boot-scoped quiescence; absence without a marker or with uncertain old-writer ownership stays pending/repair. No profile-secret retention or profile recreation is needed for retries.

Put profile admission and resource registration behind one per-profile gate in the existing API adapter. The inspected seams are `gateway/platforms/api_server.py` `_run_agent`, the `_handle_runs` executor path, `_publish_turn_process_ownership`, `_open_and_cache_session_db` and the existing profile-routing context. Associate the resolved opaque profile with its existing agent references, task IDs and executor futures; release registration only from the synchronous worker's finally block after cleanup, not when its asyncio wrapper is cancelled. Apply the gate to session/history/bootstrap and response persistence as well as run admission. Persist the local deletion fence before draining. Every route must reject reopening the fenced profile.

Quiesce uses the existing agent interrupt path and awaits actual executor completion. Reuse `AIAgent.close`, `shutdown_memory_provider`, `_active_children`, `process_registry.kill_all(task_id=...)`, `cleanup_vm(task_id)`, `cleanup_browser(task_id)` and `release_computer_use_session(task_id)` for the registered target task IDs. The current close/shutdown methods suppress exceptions, and `_reap_disconnected_agent_processes` starts a daemon reaper without joining it. Add a deletion-only checked completion result to those existing hooks: propagate cleanup failure and join owned child/reaper completion before acknowledging. Scope task ownership to the resolved profile, including delegated tasks; an ambiguous task ID must fail closed instead of cleaning another profile's resources.

The inspected `AlliesMnemosyneProvider.shutdown` delegates under `_invoke_profile_operation` but logs failures and clears its delegate. Preserve failure evidence for deletion and require successful provider shutdown before `SessionDB.close()` and eviction from `_session_dbs[home]`. The adapter's ResponseStore is shared: erase only target-owned response rows/cached entries while retaining its shared connection; never call adapter disconnect as profile cleanup. Inventory current target session/task IDs before removing their rows so terminal/browser/subagent cleanup can still resolve ownership. HTTP disconnect, asyncio cancellation and dropping references do not prove executor completion. Unknown ownership or an uninterruptible executor yields pending, then repair_required at the deadline. Never kill by PID alone, name matching or a shared process group.

Runtime also cancels and joins its own target workers, incoming-file readers, publication and scheduled work. Invoke quiesce while STOPPING leases still exist, then settle those leases. Waiting for zero leases before initiating quiesce would deadlock. Run ProfileStore cleanup only after matching quiescence and local writer drain, under its existing lock and bounds. Extend the authenticated Foundry cleanup receipt with attempt/digest, machine generation, runtime start epoch and Hermes boot identity; verify them against the current assignment.

After worker restart, recover fences before admitting work and obtain a fresh acknowledgement. A lost acknowledgement is replayed; an old boot acknowledgement cannot authorize a new process. If the old Hermes process may still be alive, refuse cleanup until closure or exit is proved through the owned supervisor identity. Restarted Hermes loads the durable fence before profile initialization and proves the preceding owned instance exited. Unknown ownership requires repair. An old image must refuse deletion if it cannot prove profile closure.

### Attempts, expiry and repair resume (ADV-DEL-002)

Keep a stable product operation_id until completion. Each runtime cleanup attempt has a random attempt_id, increasing lifecycle epoch, immutable expires_at no more than 24 hours after acceptance, and a digest of version, opaque scope IDs, operation/attempt IDs, epoch and expiry. The existing cleanup operation field carries attempt_id; the deletion coordinator owns its stable parent. No content enters the digest.

Transport retries replay the exact tuple and its outcome. Expiry creates a terminal repair receipt for that attempt and retains every fence. Add `resume_profile_deletion(operation_id, expected_attempt_id)` under existing service/operator authorization. Under the common scope lock, require repair_required, compare the failed attempt, and create the next attempt/epoch/expiry/digest atomically. Duplicate resumes for that failed attempt return its existing successor; other stale expectations return 409. Reconcile cannot silently reset expiry or repair state. Cloud's maintenance command invokes this boundary and resets only that operation's exhausted file candidates with bounded counters.

Validate attempt/epoch/digest and expiry before accepting or replaying success. An expired or superseded attempt cannot advance the current attempt. A receipt committed before expiry remains replayable. Serialize receipt/expiry/resume on the same row and test both lock winners. A new attempt independently proves closure and absence even if an old attempt removed files. ProfileStore accepts higher-epoch cleanup under the same parent deletion without removing its permanent admission fence; an already absent tree still requires current absence verification.

### Delete before provisioning (ADV-DEL-004)

Use Foundry's existing Workspace row lock to serialize provisioning and deletion, including when no profile exists. The wire workspace_id is the external Cloud workspace UUID; resolve it through the existing register_workspace mapping before taking the local Workspace row lock. Derive the internal profile identity from the binding using the provisioning convention and require ally_ref to equal str(ally_id). The existing RuntimeProfile carries the pending deletion fence, operation and attempt. If absent, create a cleanup-only profile without a seed under that same lock; this avoids a second pending-state owner while still requiring runtime absence proof. Provisioning checks the pending fence and the terminal DeletedProfile marker before creating a profile, seed or hint. All provisioning paths must use that lock/check. The internal deletion request requires ally_id alongside workspace/binding IDs; validate any existing profile matches the exact tuple.

If provisioning wins first, deletion captures its allocated profile/key and drains normally. If deletion wins first, verify no provisioning hint, assignment, conversation binding or materialization is outstanding. Inconsistent evidence stays pending/repair and reconciles the exact runtime identity. An absent RuntimeProfile alone is insufficient. Materialization requires persisted identity and current admission; it cannot create an unregistered profile.

Cloud also checks a unique scoped deleted-ID marker when Ally is absent and serializes creation/provisioning against deletion using existing lock order. Runtime retains its local fence across restart and refuses deleted-key materialization regardless of supplied epoch. Foundry continues rejecting provisioning after RuntimeProfile purge. Test both race winners and stale desired-state delivery after database purge and restart.

### Object absence and late writers (ADV-DEL-003)

Extend the existing injectable private storage port with bounded target-key erase-and-verify behavior. Before enabling deletion, inspect the configured store's versioning and retention capability through its supported API and record deployment evidence. Unsupported/forbidden inspection means unknown. Keep the existing client/timeouts; do not silently change bucket settings or permissions.

For verified unversioned storage, delete the recorded key and require metadata/HEAD to raise FileObjectMissing. A 403, timeout, malformed response, server error or delete acknowledgement is not absence. For versioned or suspended storage, enumerate every version and delete marker for each exact owned key, delete each VersionId including null versions, then require an empty version listing and absent current object. Process at most 100 entries per page and save the continuation token. Prefix listing results must match the exact key. Retention locks or unavailable version APIs require repair; retain cleanup references. Never perform bucket-wide deletion.

Preserve existing FileStagingObject keys until verification passes, including rejected/staging/current/publication objects. Audit intake/publication paths for writes before key registration and register every key before I/O. Reuse cleanup_files and FileAllyTombstone rather than adding another cleanup scheduler.

A database fence cannot stop an in-flight PUT. Use the existing FileVersion write_fence/lease and pre-registered FileStagingObject at the three inspected write boundaries: `intake.receive_file` (put_stream), `intake.promote_inspected_file` (promote), and `publication.receive_publication_file` (put_stream). Add in-flight/completed/ambiguous I/O outcome to that existing candidate, set before the call and settled on a definitive provider response, including when the target fence changed. Deny new calls after the tombstone. Timeout or worker loss leaves ambiguous I/O and keeps deletion pending/repair; neither HTTP timeout nor lease expiry proves remote abort. This requires no general Cloud process supervisor. Preserve every candidate until completion/abort evidence is available. After all candidate writes settle, repeat key/version absence verification, release accounting once and only then purge references. A delayed successful PUT test must settle its candidate and trigger deletion before completion can be reported.

## Phases

### Phase 1 - Labels and visibility

Labels are implemented on the refreshed Cloud and Interface dev bases. Preserve their accepted fast-plan behaviour and run regression checks; do not reimplement this slice. Foundry Enkii-only work remains independent.

### Phase 2 - Foundry deletion and quiescence

- Deliver two coherent dependent slices: first the image patch, checked close hooks, runtime quiesce client/receipt schema and real-resource tests; then Foundry admission markers, attempt/resume service, protected-row purge and contract/race tests. Keep user deletion unavailable until both slices pass. Existing cleanup expiry remains compatible for callers outside this deletion coordinator.
- Add internal boundary, durable fence and final receipt with the approved content-free marker. Serialize provisioning and deletion on identical workspace/profile identity. Record deletion before late provisioning can create an absent profile.
- Reuse request_profile_cleanup, epoch, STOPPING leases, runtime reconciliation and ProfileStore cleanup. Wake existing runtime through activation when needed; never destroy shared compute/volume.
- Implement the profile quiescence capability specified above. The current shared listener has no selected-profile process whose termination proves closure. Initiate quiesce before settling STOPPING leases; obtain the matching boot/attempt acknowledgement and drain runtime writers before filesystem cleanup.
- Fence executions, routine claims, approval actions, materialization, publications and callbacks. After verified runtime cleanup, purge target publications, routine actions/receipts, execution events/deliveries, approvals, attempts, leases, executions, conversation bindings, provisioning hints and RuntimeProfile in actual child-before-parent FK order. Keep workspace, RuntimeCredential, releases, ready bundle, machine and volume. Inspect PROTECT edges in runtime models and test fully populated graph; do not disable constraints or build a generic cascade framework.
- Exit: target profile tree/memory/spools/temp state and database content gone, same outcome on retries, stale creation fenced, sibling ally usable; unknown process or partial cleanup remains repair-required.

### Phase 3 - Cloud deletion and purge

- Validate owner/current-name phrase and establish operation/file tombstone atomically. Respect existing storage-account -> Ally -> conversations lock order. Never hold locks during remote I/O.
- Fence retrieve's onboarding repair, message/queue dispatch, routines, approvals, runtime intents, file intake/read/publication, label generation and provisioning. Recheck under common ally admission lock at write acceptance and callback persistence; late provisioning must reconcile with Foundry fence.
- Use Celery/beat bounded batches (100 operations/60 seconds), exclusive claims, stable identity, existing gateway timeout/no redirects/response validation. Retry transient failure with capped 5-second to 5-minute backoff; after 24 hours mark repair_required. Explicit operator resume compares the failed attempt and creates a new epoch under the same product operation as specified above; never revive an expired attempt.
- Copy verified Foundry receipt through record_foundry_cleanup_receipt. Reuse cleanup_files for all target file versions/staging/publication objects, including rejected/interrupted inputs. Wait for confirmed object absence and released accounting; five exhausted storage attempts require repair/resume. Fence/reconcile late uploads before purge. Do not interpret an S3 delete marker as proof all historical versions vanished.
- Explicitly purge protected Cloud child graphs: routine result context/receipts/projections, routine approval commands/projections, outboxes/snapshots/occurrences/management/deletion confirmations/routines; file message/draft links and recovery; file versions/staging/publications in actual FK order; tombstone after receipt copied; then conversation/message/activity/approval/event rows and Ally/binding/provisioning/onboarding attempt. Establish exact order from model references with populated graph tests. Preserve user/session/workspace/shared storage account and other allies.
- Keep operation/progress through partial failure; final transaction marks complete only after purge. Lost response replays complete through the approved scoped deleted-ID marker after transient receipt fields are removed. Exit: owned rows and active objects absent, accounting correct, other ally functional, restart/race tests pass.

### Phase 4 - UI and delivery

- Delivery dependencies are Hermes capability/runtime receipt support, Foundry deletion service, Cloud deletion/storage proof, then Web deletion. Keep each schema/migration and its tests with the owning slice. Recheck the refreshed dev bases before implementation; labels already merged into Cloud and Interface are regression scope only.
- Add deletion to phase-1 settings. Poll 2 seconds initially, cap at 30 seconds; suspend hidden/offline tabs and stop after 10 minutes with manual refresh. Cloud recovery continues. Refresh loads durable operation state.
- Update shared client/OpenAPI, exact-confirmation/error/pending/reload/empty-roster tests. Runtime/Foundry first, Cloud second, web deletion last. Keep migrations/contracts/tests together; split independent label PRs when useful under repository review-size policy. No merge/deploy authorization.
- Enkii workflow uses Timmyy3000/enkii@v1.3.0, release commit 1ce1ee8e2810d392f674c20e0b5f911a7737b212. Orchestrator made pins-only edits; preserve triggers, concurrency, secrets, policy input and permissions.
- After verified implementation, update canonical Nabu decisions/specification with current revision and readback. Record retention limits honestly.

## Acceptance Criteria

1. New creation generates validated 2-3 word label, preserving chief of staff; failure does not fail creation; retries do not repeat provider call and edits win.
2. Hidden defaults, editable settings, enabled label beneath correct name, reload and cross-tab revision behavior work.
3. Cloud checks owner capability, workspace ancestry, CSRF and the exact current-name confirmation before destructive effects.
4. Success requires runtime quiescence, memory/file cleanup, object cleanup and relational purge; uncertainty stays pending/repair-required.
5. Provisioning, active/queued/routine work, uploads and late callbacks cannot recreate target content. Actual process-stop evidence or safe refusal is tested.
6. All exclusively owned active application data is removed; approved metadata and retention exclusions are explicit. Other allies and shared resources remain usable/correct.
7. Repeated deletion and restart converge; versioned contracts, Enkii policy/security gates and synthetic-only destructive tests remain intact.

## Backend Considerations (if applicable)

### Query Optimization Plan

Labels are scalar list fields with no per-row provider calls. Join/annotate deletion status once and index target/due operations. Use bounded scans and scoped bulk purges; large child graphs can purge over several passes before final parent transaction. Measure one/many-child deletion query counts and ensure one gateway call per operation pass.

### N+1 Prevention

Keep existing select_related binding/provisioning reads. Resolve scope once per deletion; no per-file Foundry call. Reuse bounded storage object loop and avoid unlimited history materialization.

### Detailed Unit Test Cases

Cover normal generation/edit/cleanup; malformed output/bounds/phrase/schema/revision; wrong session/workspace/binding/capability/token; duplicate create/task/delete and lost receipts; crashes at every deletion stage; unavailable runtime/process, stale epochs, expired cleanup, symlink escape/tree bounds, protected FK graph, storage exhaustion, late uploads/publications and other-ally preservation.

## Frontend Considerations (if applicable)

### Data Path

Home/header -> focused settings -> existing session shared Cloud client -> Cloud v1 -> mapper -> React Query roster/detail. No Foundry calls or new proxy. Cloud owns fields/progress; component owns drafts/confirmation.

### State Management Considerations

Update/invalidate roster and target after save. Keep dirty drafts on error/refetch; 409 reconciles explicitly. Accepted deletion disables target interactions and stream; complete removes only target queries/drafts/selection. Identity/revision guards reject stale asynchronous responses. Stop polling on unmount and keep manual refresh available for pending or repair state.

## Test Plan

Implementation validation is recorded below; these commands define the required delivery checks:

- Cloud: make check; make lint; `make test APP="allies/tests files/tests chat/tests activities/tests routines/tests"`; full CI migration/format/coverage gates before delivery. Add PostgreSQL transaction races for edit/generation, provisioning/deletion, uploads/purge and routine callbacks using existing local/CI database setup; SQLite alone cannot establish lock correctness.
- Foundry: make check; make lint; make test APP=runtime/tests; make runtime-test; with DJANGO_DEBUG=true run `uv run --locked --project backend python scripts/validate.py`. Preserve runtime image identity/dependency and migration CI checks. Extend fnd006/profile provisioning, runtime profile store/reconciliation/files/publications/worker tests. Use disposable runtime process to prove stop/handle-close/purge/restart and sibling memory readability.
- Interface: bun run cloud:check; bun run typecheck; bun run test:run; bun run lint; bun run build:web; bun run bundle:mobile for shared contract changes. Run Home smoke and scoped chat-frame regression when header changes. Test keyboard/narrow layouts, two allies, refresh, partial failure and stale response.
- Contract: matching internal fixture in Cloud/Foundry; locally generated public OpenAPI and metadata verification; malformed identity/receipt and old-server defaults. Runtime acknowledgement fields must be documented and fixture-tested before release.
- Hermes image: `make hermes-image-test`; exercise a real executor that outlives cancellation, failed provider shutdown, active terminal/browser/delegated resource, stale/lost acknowledgement and restart. The sibling must keep streaming and reading memory. Mocks of zero counters do not establish closure.
- Review regression matrix: ADV-DEL-001 covers boot identity and checked resource closure; ADV-DEL-002 covers expiry/receipt/resume races and duplicate resume; ADV-DEL-003 covers false delete acknowledgement, 403 HEAD, versions, retention locks and late PUT; ADV-DEL-004 covers both provisioning lock winners and stale materialization after purge.
- Synthetic end-to-end: create two allies, edit/toggle, start execution/upload, confirm deletion, interrupt cleanup, refresh/recover, verify no premature success, inspect all owned storage/rows, then use sibling ally. No live destructive testing.
- Workflow: pins-only diff, unchanged permissions/policy/events, YAML validity and git diff --check. Orchestrator verified release input compatibility.
- Plan: all full-template headings, acceptance-to-test mapping and privacy scan; complete better-docs then humanizer with preserved draft/clean/diff in local task workspace.

## Risks and Mitigations

### Implementation evidence (September 11, 2026)

- Labels and visibility shipped separately to `dev` in Cloud PR 43 and Interface PR 51. Deletion uses fresh branches from `dev`: Cloud `85d9548`, Foundry `681f742`, Interface `276795b`.
- Foundry `scripts/validate.py` passes, including backend tests and 867 runtime tests (8 skipped), with 90.02% runtime coverage. The actual pinned Hermes image builds and runs its synthetic quiescence smoke: cancelled wrappers with live executor threads, checked provider and SQLite closure, two live Mnemosyne providers with sibling model routing preserved, owned process termination, unknown ownership refusal, admission fences, cache purge and restart.
- Interface full suite passes: 933 tests in 121 files; 170 shared-client tests; web/mobile/client typechecks; lint (48 existing web warnings, no errors); production web build; mobile bundle; and 55 desktop/mobile/PWA production home-smoke checks. Schema metadata is pinned to clean Cloud commit `51377536e3dcda7b69561bce5f8b772d7ee4f7c4`.
- Cloud final full suite passes: 965 tests, 41 skipped. Ruff lint/format, system and migration checks pass. PostgreSQL race/upload/callback validation passed 41 tests; after CI exposed a lock-order race, the corrected race passed three serial runs, the full concurrency module passed four tests, and combined PostgreSQL chat/intake/settlement coverage passed 26 tests. Original LF contract fixture bytes are preserved.
- Independent simplicity review removed the redundant marker boolean and temporary client schema shim and folded unshipped migrations. Explicit runtime fence/erase boundaries and the bounded UI polling registry remain because simplifying them would change compatibility or cancellation/recovery behavior.
- Independent correctness review identified cleanup retry counters, scoped cleanup starvation and delayed-task identity errors; all three were fixed and re-reviewed. Final review also required settling verified promotion I/O before the final database transaction and exposing the existing guarded resume service through an operator command.
- Final storage review preserves ambiguous and in-flight candidates and their writer identity until definitive provider completion/abort. A scoped settlement command validates workspace, Ally, file, fence, exact key and allowed outcome under locks. Tests cover refusal, settlement and subsequent verified cleanup. Independent follow-up review found no remaining P1/P2 issues. Shared workspace activation cannot recreate a deleted profile and was dismissed as a false positive.
- UI review follow-up reconciles 409 deletion conflicts through authoritative status before claiming deletion is pending. Name conflicts remain in confirmation; uncertain status keeps manual recheck available. The parent validates the returned Ally ID before changing global state. All 92 HomeWorkspace tests pass, including concurrent deletion, name conflict, mismatched identity and manual recheck; independent review is clear.
- Foundry [PR 61](https://github.com/alliesai/allies-foundry/pull/61), head `b028fda`, has passing CI and Enkii code/security/policy review. Cloud [PR 44](https://github.com/alliesai/allies-cloud/pull/44), head `5137753`, includes the portable index name, explicit negative tenant-isolation endpoint tests, automatic retry for ordinary cleanup delays, and consistent Ally-before-child locks. These follow-up fixes passed independent review and affected tests. Interface [PR 52](https://github.com/alliesai/allies-interface/pull/52) delivers the consumer after those services. Recurring monitoring is not requested; checks are followed during this task.
- No live deletion, deployment or merge was performed. The guarantee covers verified active application stores; backup/log/provider retention is a separate operator responsibility. Unknown external resources or ambiguous writers keep the operation in repair-required state.

Accepted owner decision: retain a content-free scoped marker meaning "Ally ID deleted". Retain no name, job, conversation, file, memory, seed fingerprint or content-derived digest after completion. Pending repair references remain until cleanup succeeds. Engineering review and capability tests remain required; the retention question is settled.

Object versions, infrastructure backups/logs and provider retention need operator evidence before final UI copy promises all-copy erasure. Scope immediate guarantees to verified active application stores, document actual exclusions/expiration, and do not silently expand into platform retention work.

Protected FK graphs and subprocess quiescence are the highest code risks. Explicit domain purge order, populated graph tests and runtime stop evidence are mandatory. Unknown writers/storage produce repair_required, never forced success or shared-resource removal.

Rollback labels by disabling generation/hiding controls while retaining additive columns. For deletion, disable new acceptance but keep recovery and fences for accepted operations. Completed deletion is irreversible; code rollback must not restore content. Downgrading to code that ignores fences is unsafe while stale work can remain. Deploy compatible runtime/backend first.
