# CLD-010 and FND-011 File Sharing Plan

## Feature Overview

- Problem: Cloud accepts text only. Owners need to send files and retrieve fixed versions of files returned by an Ally.
- Target users: Signed-in owners on web and mobile, the intended Ally, and service operators.
- Source: Approved Nabu specification `projects/allies/engineering/specs/cld-010-user-message-file-attachments.md`, revision `e8a30bf1eb812c614f4a00c815e6486749bcdec4f9ea26ce9b77731f5f18fa46`. See `cld-010-sources.md` for complete source snapshots.
- Outcome: Private files reach the correct Ally with optional text, once and in order. Shared versions remain available until Ally deletion.
- Route: full. HTML required: yes, by explicit user instruction. The HTML is prepared after substantive review.
- Status: Proposed engineering contract. Planning only; no feature implementation or Nabu publication is authorized yet.

### Current evidence

Cloud base is `dd8bba6`. `backend/chat/models.py` has message sequence, retry lineage, execution claims, and an exact-byte dispatch outbox. `chat/services/messages.py::_claim_next_turn_locked` skips failed messages; `accept_message` claims immediately. Failed preparation therefore needs a separate queue gate. `chat/api/schemas.py` and `allies/gateways/contracts.py::ExecutionInput` require nonempty text. These are explicit changes, not existing attachment support.

`backend/auths/storage/avatars.py` supplies an R2/S3 pattern and boto3, not a file-sharing service. `backend/workspaces/models.py` gives a personal workspace an owner. `backend/allies/models.py` has no deletion state; no product deletion endpoint was found in Ally controllers/services. Release requires the deletion integration described below.

The canonical CLD-004 snapshot in `cld-010-message-lifecycle-source.md` includes the accepted 6 September queue extension. Preserve claimed/unclaimed state, the complete bounded queue independent of history pages, and redacted stopped tombstones. Its historical PR text says Cloud is unmerged; the fetched base contains queue claims/migration 0006. Use current code for implementation state and retain the source mismatch explicitly.

Read-only sibling evidence: Foundry `e7e676094759ec30708a881c9bc4fa3d7b70902d`, clean; Interface `9510e146ac1d67441e5f5fc7a70095370ffbb027`, clean. Foundry `backend/runtime/contracts.py` has strict execution input, and `runtime/services/workspaces.py` owns volume/machine continuity. No Cloud file-transfer API was found. Interface `apps/mobile/src/features/conversation/conversation-state.ts` deduplicates messages by ID and sequence. These observations do not prove file continuity or device behavior; FND-011 and INT-106 must provide that evidence.

Historical pre-sync evidence, read from fetched refs on 9 September before the parent fast-forwarded the main checkouts: Foundry `origin/dev` is `1d03ea557be757f4eca4c6b6478d542291169b14` (then-local checkout behind 40 commits); Interface `origin/dev` is `f21e5ffae5a7b4e14ad8ab44c8a9c48b4f7c940b` (then-local checkout behind 18 commits). These fetched versions supersede the checkout observations for planning. Foundry execution input still requires text and has no file field; it now includes first-turn bootstrap and excludes absent optional fields from fingerprints. Workspace lifecycle now also covers image updates on wake and ready-pool allocation; replacement preserves volume identity and fences source/target generations. File spools must use the assigned tenant/profile continuity boundary, never an unassigned pool workspace. FND-011 must prove this rather than add a competing lifecycle.

Current Interface shared `packages/cloud-client/src/message-queue.ts` preserves tombstones, terminal progress and claimed queued copies; mobile `conversation-state.ts` merges the complete queue separately from paged history. Extend this shared mapper/merge contract with preparation revision and file state, preserving those existing precedence rules. Test late uploading responses after ready, claimed or cancelled state. Updating only mobile local state would miss the shared web contract.

## User Stories

1. As an owner, I can send files with optional text and continue work with another Ally.
2. As an owner, I can retry a failed file without uploading successful files again, or cancel before delivery and restore my draft.
3. As an owner, I can retrieve the exact file version from an old message.
4. As an operator, I can detect blocked inspection and cleanup without reading file contents.

## Scope

### In Scope

Cloud intake, validation, preparation, ordered delivery, immutable versions, publication, private retrieval, recovery, retention, accounting, and file deletion integration; Foundry incoming-file staging, model-facing publication tool, durable spool/recovery and workspace cleanup. The user expanded backend scope on 9 September: one later Terra high implementation worker can own both repositories, with separate commits/PRs. This remains planning only. Publish the contract before implementation; prove both backends before Interface work, then complete user-facing acceptance with INT-106.

### Out of Scope

Implementing Design or Interface tickets; active-execution Stop; a general Ally deletion/settings feature; public sharing; file manager/editor/version-history UI; folders; audio/video/archives/executables; Office previews. Upload success does not promise understanding of a format.

### Dependencies and Assumptions

- Preserve CLD-004 lifecycle and CLD-005 exact-command dispatch. Preparation retry changes the original unclaimed message; execution retry retains existing lineage rules.
- DSN-008 owns Photos/Camera/Files, retry designs and the modal. Existing Figma treatment is a Design input, not inspected evidence here.
- Use a separate private R2 bucket and existing boto3 dependency. Do not alter avatar behavior. No lifecycle rule may expire retained versions.
- MB means decimal bytes: 25,000,000 per file, 50,000,000 per message, at most 10 files, in both directions.
- The missing product Ally deletion entrypoint needs an explicitly assigned owner before release. CLD-010 supplies file revocation/cleanup integration and tests, not unrelated settings behavior.

## Contract and Shape Definitions

### Foundry implementation evidence and public boundary

The isolated Foundry branch `ft/fnd-011-file-sharing` starts at `1d03ea557be757f4eca4c6b6478d542291169b14`. Its root instructions and engineering policy require provider-neutral core, portable public docs and no private source material. No nested AGENTS.md was found. README, Makefile, both pyproject files, CI and `scripts/validate.py` were inspected. Fresh Nabu ticket evidence is in the private Cloud file `cld-010-foundry-source.md`.

Concrete seams: `backend/runtime/services/executions.py` maps command text/bootstrap into persisted input_payload; `services/claims.py` returns runtime claims; `runtime/allies_runtime/foundry.py::FoundryWorker._run_claim` validates the message before dispatching Hermes. `composition.py` wires FoundryClient, HermesClient, ProfileStore and ProfileReconciler. `profile_store.py` already creates each profile's workspace directory, rejects unsafe paths, and owns fenced cleanup. Backend `services/profiles.py::request_profile_cleanup` and `accept_cleanup_receipt` persist lifecycle fences. Hermes image patches already add profile/session-scoped endpoints and request context. Extend these boundaries; do not put file services into provider provisioning or import Cloud Django models.

Only sanitized generic schemas, fixtures, configuration names and contributor instructions go into Foundry. Keep this master plan, Nabu snapshots, private deployment details and workstation paths in Cloud. Provider-specific smoke configuration stays optional; ordinary CI must run against fake transport and temporary directories.

New JSON schemas reject unknown fields. IDs are canonical UUID strings, times UTC ISO-8601, hashes lowercase SHA-256. Use existing success/error envelopes. `{id}` in examples represents a UUID fixture. Paths are relative to the current API mount; Phase 1 verifies full paths in OpenAPI. `W` means `/workspaces/{workspace_id}`; `C` means `W/conversations/{conversation_id}`.

### Function and Service Shapes

| Proposed location | Symbol / signature | Validation | Return / effects |
| --- | --- | --- | --- |
| `backend/files/services/intake.py` | `reserve_send(*, user, workspace_id, conversation_id, request, key) -> MessageAcceptance` | Owner, live Ally, manifest, quota, key | Atomic message sequence and byte reservation; conflict/rate limit |
| Same | `receive_file(*, scope, file_id, generation, chunks) -> FileView` | Size/hash, generation, state | Private staging then inspection; no execution |
| `files/services/preparation.py` | `retry_send(*, scope, message_id, revision) -> MessageView` | All active files ready; nonempty send | Arms original message under conversation lock |
| Same | `cancel_send(*, scope, message_id, revision) -> DraftView` | Before dispatch claim | Durable cancellation, writer revocation, draft recovery |
| `files/services/publication.py` | `reserve_publication(*, binding, request, key) -> PublicationView` | Binding/execution ancestry and limits | Fixed publication/file IDs; no link yet |
| `files/services/access.py` | `open_file(*, user, workspace_id, ally_id, file_id, mode) -> StreamingHttpResponse` | Owner, active Ally, clean version | Metadata or bounded bytes; no storage redirect |
| `files/services/cleanup.py` | `cleanup_files(*, now, limit=100) -> CleanupReport` | Limit 1..100 | Leased/fenced deletes outside transactions; safe counts |

### API and Transport Contracts

Customer calls use current native bearer or browser session. Mutations also use existing origin/CSRF rules. Check owner, active workspace and complete resource ancestry every time. A foreign resource returns 404; missing session returns 401. Link possession is not authority. New paths below are proposed, not existing endpoints.

| Consumer / method / path | Request example | Response example | Errors / retry |
| --- | --- | --- | --- |
| Interface POST `C/file-messages`, Idempotency-Key | `{"content":"Review","files":[{"client_id":"{id}","name":"report.pdf","size":1200,"sha256":"<64hex>"}]}` | 202 `{"message":{"id":"{id}","sequence":3,"status":"queued","preparation":"uploading","revision":1},"files":[{"id":"{id}","generation":1,"state":"pending"}],"replayed":false}` | 422 invalid/empty/limits; 409 changed key; 429 queue/capacity. Same canonical request replays original, even after cancellation. |
| Interface PUT `W/allies/{ally_id}/files/{file_id}/content?generation=1` | Raw bytes; exact Content-Length; application/octet-stream | 202 `{"id":"{id}","state":"validating","generation":1}` | 413 oversized; 409 stale/immutable; 422 hash/type; 503 storage. GET state resolves uncertain response. |
| Interface POST same file `/retry` | `{"generation":1}` | `{"id":"{id}","generation":2,"state":"pending"}` | 409 ready/stale; replay generation 1 returns generation 2; never replace ready bytes. |
| Interface DELETE `C/messages/{message_id}/files/{file_id}?revision=2` | No body | `{"message_id":"{id}","revision":3,"preparation":"needs_retry"}` | 409 dispatched/stale; repeated removal harmless; no auto-send. |
| Interface POST `C/messages/{message_id}/send-files` | `{"revision":3}` | `{"id":"{id}","revision":4,"preparation":"ready","status":"queued"}` | 409 not-ready/stale; 422 empty; repeated committed operation returns current outcome. |
| Interface POST `C/messages/{message_id}/cancel-files` | `{"revision":3}` | `{"id":"{id}","preparation":"cancelled","draft":{"content":"Review","files":[{"id":"{id}","name":"report.pdf","state":"ready"}]}}` | 409 delivery_started if claim won; repeated cancellation returns same draft. |
| Interface GET existing conversation/message/reply pages | Existing cursor/limit | Existing fields plus `"files":[{"id":"{id}","name":"report.pdf","size":1200,"state":"ready"}],"preparation":"uploading","revision":1` | Existing paging/auth; old rows get empty additions. Poll at 2 s then back off to 30 s; pause offline. |
| Interface GET `W/allies/{ally_id}/files/{file_id}` | No body | `{"id":"{id}","name":"report.pdf","type":"application/pdf","size":1200,"preview_kind":"pdf","state":"retained","open_path":"/files/{id}"}` | 404 denied/deleted; 409 unready; 503 retrieval. Product route opens authenticated modal. |
| Interface GET same file `/download` or `/preview` | Optional single Range for download | Binary response; safe Content-Type and length; text preview example `hello` | 416 invalid/multiple range; 404 denied; 409 unsafe/unready; 503 retrieval. No new version on retry. |
| Foundry POST `/internal/v1/file-publications` | `{"binding_id":"{id}","message_id":"{id}","publication_id":"{id}","files":[{"source_version_id":"{id}","name":"result.csv","size":12,"sha256":"<64hex>"}]}` | 202 `{"publication_id":"{id}","state":"uploading","files":[{"id":"{id}","generation":1}]}` | Service auth plus binding/execution ancestry; 409 changed source; same key replays; no URL/path fetch. |
| Foundry PUT `/internal/v1/file-publications/{publication_id}/files/{file_id}/content?generation=1` | Same bounded raw body contract | 202 `{"id":"{id}","state":"validating","generation":1}` | Same upload failures; bound service only. |
| Foundry GET internal publication; Interface GET `C/messages/{message_id}/publications/{publication_id}` | No body | `{"publication_id":"{id}","revision":2,"state":"ready","files":[{"id":"{id}","open_path":"/files/{id}"}],"retryable":false}` | Shared DTO; different authorization. Pending/failed omits open_path. |
| Interface POST same publication `/retry` | `{"revision":2}` | 202 `{"publication_id":"{id}","state":"retry_pending","revision":3}` | Durable same-version retry instruction; 409 stale/unavailable. Foundry polls and resumes spool. |
| Foundry GET `/internal/v1/accepted-files/{file_id}/content?binding_id={id}&message_id={id}` | No body | Bounded binary file | Service auth plus recorded accepted manifest/binding/Ally scope; reserved files denied. |

Internal service authentication follows the existing gateway credential boundary. Credentials are headers, not payloads. Interactive Foundry polling uses 2..30 seconds for at most five minutes per attempt. Stopping that poll does not stop retry delivery. A Foundry scheduled recovery worker calls the claim endpoint below on startup and every 30 seconds, at most one 20-item batch per run. It operates outside model execution and survives process replacement. Cloud persists due retry state on FilePublication; a five-minute fenced lease prevents concurrent work and expiry makes work claimable again. The worker opens the frozen spool through the assigned workspace continuity boundary. It must not start a new model turn or recreate a file. Missing spool returns source_unavailable, never a new source version. No runtime address reaches Interface.

| Recovery transport | Request | Response / semantics |
| --- | --- | --- |
| Foundry POST `/internal/v1/file-publication-retries/claim` | `{"binding_id":"{id}","limit":20}` | `{"items":[{"publication_id":"{id}","binding_id":"{id}","revision":3,"lease_token":"{id}","lease_until":"2026-09-09T00:05:00Z","files":[{"id":"{id}","source_version_id":"{id}","sha256":"<64hex>","generation":2,"state":"pending"}]}]}`. Service authentication; only its authorized bindings. Limit 1..20, oldest due then ID, skip locked; empty list when idle. |
| Foundry POST `/internal/v1/file-publications/{publication_id}/retry-result` | `{"revision":3,"lease_token":"{id}","outcome":"submitted"}` | `{"publication_id":"{id}","revision":3,"state":"validating"}`. Outcome submitted or failed (safe_error_code required for failure). 409 stale revision/lease; same committed result replays. Cloud alone declares ready after verification. |

Explicit user retry increments publication revision once and atomically advances only failed/incomplete file generations. Ready files and their keys/hashes stay unchanged. The claim returns all file states so Foundry skips successful files. Retry PUT includes publication revision and lease token headers, plus generation query; Cloud checks all three. Immutable source_version_id, declared hash and size cannot change. A repeated claim after expiry reuses these generations and checks file state. Expired receiving work may reset to pending for the same generation only after fencing its writer; validating/ready bytes cannot be replaced.

submitted acknowledges all required bodies, not successful publication; persisted inspection tasks own completion. Failed transfer or expired recovery lease uses at most five recovery attempts with 5/30/120/300-second delays, then failed with explicit Retry. Persist next due time/count and reset only for a new explicit retry revision. Death after upload but before result is recovered by inspecting file states and submitting the same result, without model execution. Cancellation/deletion invalidates leases; stale results cannot revive work. Use the existing scheduled-worker pattern and publication row, not a new retry-job table. Logs contain IDs and safe codes only.

Execution input requires a negotiated `file_input_v1` capability. Both strict v1 schema implementations must accept optional `files` before enablement. Example payload: `{"kind":"execution_input","text":"","files":[{"file_id":"{id}","name":"report.pdf","media_type":"application/pdf","size":1200,"sha256":"<64hex>"}]}`. Text-only bytes remain unchanged by omitting files. Require text or files. Freeze ordered manifest into the existing canonical outbox once, without expiring credentials or URLs. Foundry deduplicates command ID, stages every verified file, then starts the model. Uncertain receipt uses existing reconciliation, never a new message. Shared fixtures prove old/new compatibility.

Keep current bootstrap validation and fingerprint omission behavior: absent files must be omitted, not serialized as null or an empty default array in old text commands. Add fixtures for bootstrap plus files, files-only input, and unchanged bootstrap/text-only fingerprints.

No new public stream event is needed. Existing authenticated reads expose preparation/publication state. Reply text may link `/files/{id}` only after its publication is ready. Cloud validates internal file references against ready publications for that source message before durable reply projection. Pending/invalid file references produce a safe publication failure with Retry, not a broken clickable link. Ordinary external links are unchanged. Limits apply across all publications for one reply/source message, not per API call.

### Data Shapes and Invariants

#### Database Models

| Category | Model/location | Fields / defaults | Constraints and migration |
| --- | --- | --- | --- |
| Table | `FileVersion`, `backend/files/models.py` | UUID; workspace/Ally FKs; owner UUID; nullable source message/publication; direction; original_name varchar(255); type varchar(127); expected/actual size bigint; sha256 char(64); private object_key; state; generation=1; error; timestamps; lease_until/cleanup_after nullable | Size <=25,000,000; immutable ready key/hash; state/cleanup_after/id index. Retain cleanup identity across deletion. Additive. |
| Table | `MessageFile`, same | message/file FKs; position smallint; removed_at nullable | Unique message/position and message/file; active count/bytes checked under lock. Old messages empty. |
| Fields | Existing Message | preparation default none; preparation_revision=0; send_armed=false | Preparation-aware queue checks/index; armed only with valid manifest. Existing rows none. |
| Table | `FilePublication`, files models | UUID; source message/binding; request_digest; revision=1; state; safe error; timestamps; retry_due_at/lease_until/lease_token nullable; retry_attempts=0; last_result revision/token/outcome nullable | Unique binding/publication ID; aggregate reply limits under message lock; due-state index; attempts 0..5; result replay fenced by revision/token. |
| Fields | FileVersion publication association | source_version_id UUID for return; publication FK | Return scope matches publication; source version/hash immutable. No runtime path. |
| Table | `FileStorageAccount` | workspace one-to-one; reserved_bytes=0; retained_bytes=0 | Nonnegative; lock for reservations. New file accounting only, not avatars. |
| Table | `FileDraftRecovery` | UUID; cancelled message one-to-one; owner/Ally scope; content <=16,000 bytes; ordered file references; discarded_at nullable | Created atomically before message redaction; owner-only, excluded from history; deleted on explicit discard or Ally deletion. Keeps cancellation compatible with existing redacted tombstones. |
| Table | `FileDraftFile` | draft/file FKs; position smallint | Unique draft/file and draft/position; indexed file FK; protects bytes while draft is not discarded. Mutations take FileVersion lock. |
| Integration field | Ally deletion owner supplies deleted_at or equivalent tombstone | Nullable timestamp, absent today | File calls deny tombstone. Cleanup identity survives hard-delete until verified. |

Do not add a generic job system. File rows own cleanup/inspection leases and generations. Publications own return recovery. The deletion owner must include admin/account deletion paths, not only a customer endpoint.

#### Enums

| Category | Enum | Values / invariants |
| --- | --- | --- |
| Persisted vocabulary | Preparation | none, uploading, failed, needs_retry, ready, cancelled; execution status remains queued while preparation blocks |
| Persisted vocabulary | FileState | pending, receiving, validating, ready, retained, failed, rejected, cleanup_pending, deleted; ready immutable, retained never expires |
| Persisted vocabulary | PublicationState | uploading, validating, ready, failed, retry_pending, cancelled; links only ready |
| DTO vocabulary | PreviewKind | image, pdf, text, none; Markdown/code/HTML are inert text |

#### API Request Schemas

| Category | Schema | Validation / compatibility |
| --- | --- | --- |
| DTO | SendFilesRequest | content default empty <=16,000 UTF-8 bytes; 1..10 descriptors; basename 1..255 chars without controls; size 1..25,000,000; unique client UUID; SHA-256 required. New endpoint, old text unchanged. |
| DTO | Reuse descriptor | `{"reuse_file_id":"{id}"}` instead of new manifest; mutually exclusive; same owner/Ally, ready recoverable draft only. Counts toward message limits, not duplicate storage. |
| DTO | RevisionRequest | Nonnegative revision; compare-and-set and operation replay |
| DTO | PublicationRequest | Publication, binding, message UUIDs and 1..10 immutable source descriptors |
| DTO | Upload retry | Positive generation; old writers cannot overwrite new generation |

#### API Response Schemas

| Category | Schema | Fields / invariant |
| --- | --- | --- |
| DTO | FileView | ID, name/type/size/state/generation/error/preview kind; no key, credentials, local path or contents |
| DTO | Message additions | preparation, revision, ordered files; defaults for old history |
| DTO | PublicationView | ID/revision/state/files/retryable; no link before ready |
| DTO | DraftView | Content and ordered descriptor/file IDs; local file handles client-only |

#### Temporary / Internal Shapes

| Category | Shape | Lifetime / boundary |
| --- | --- | --- |
| Internal bytes | Generation staging object | Random key recorded before writing; not product version; bounded partial cleanup |
| Internal DTO | InspectionResult | Hash/size/type/scanner version/verdict; no content logs |
| Internal bytes | Foundry spool | FND-011 freezes before reservation and preserves across retry/replacement until ready or explicit cancellation/deletion |
| Configuration | Admission gate | Off by default; reads and cleanup remain on during rollback |

#### Service Primitives

| Primitive | Lock / failure ownership |
| --- | --- |
| Reserve | Lock storage account, Ally, Conversation, Message in that order; sequence and bytes atomic |
| Finish intake | I/O/inspection outside locks; reacquire same order plus file; check generation, tombstone and cancellation |
| Arm/claim | Conversation then Message lock; earliest unresolved preparation blocks; only none or ready+armed claims |
| Cancel | Same claim lock; before claim cancel and fence generations; after claim return delivery_started |
| Delete | Owner tombstones first; file hooks fence reads/admission; durable cleanup survives; remote I/O outside locks |

### Plain-language glossary

A model is a database row. A schema validates boundary data. An enum is a closed set of states. A DTO carries data between systems. A primitive owns one state change. An index supports a bounded query. A constraint rejects invalid combinations. An invariant must hold across retries and failures.

### Preparation, ordering and cancellation

Send reserves sequence before transferring bytes. Initial successful completion can arm the first send only if no failure, removal, cancellation or stale revision occurred. First failure sets preparation=failed and clears send_armed. File retry preserves ready files and never arms delivery. Removal sets needs_retry; explicit send-files checks the complete final manifest. Removing the last file from a file-only message cannot dispatch an empty message; restore/edit a new draft or cancel.

Queue selection includes unresolved uploading/failed/needs_retry messages. Their execution lifecycle stays queued and they count against the current pending cap. Select earliest sequence first, then test readiness; do not filter unready rows out. All later text and file messages wait. Other Allies have independent locks.

Cancellation linearizes against execution claim before remote delivery starts. Successful cancel removes dispatch eligibility, invalidates writers and returns saved draft. If claim won, 409 delivery_started shows current truth. Clients cannot infer success from aborting HTTP. Late upload completion discards bytes. No outbox exists before readiness. Existing queued-delete delegates to this boundary for attachment messages.

Cancellation keeps the accepted queued-delete contract: retain message ID, sequence, send digest and fingerprint, blank content/command bytes, set deleted_at and status=stopped. Store draft restoration separately in FileDraftRecovery before redaction; exact send-key replay returns the tombstone. A repeated cancel call may return the owner-authorized recovery record. Add GET `C/messages/{message_id}/file-draft` with no request body and the same DraftView JSON as cancel, and DELETE that path with no body returning `{"discarded":true}`. Both require owner/Ally scope; GET after discard returns 404 and repeated DELETE is harmless. Discard schedules successful objects only when no live accepted message (including an unclaimed queued send), retained message/publication, or nondiscarded draft protects them. It never removes a delivered shared version.

GET reconstructs unsent states after refresh. Ready bytes are reusable; only incomplete files without accessible local handles need reselection. Resubmission after cancellation uses a new send key and optional reuse_file_id. Editing never changes an old key's fingerprint. Original key replays cancellation, not a new send.

Reuse and cleanup use MessageFile and draft-file relations as protection, not a reference-count table. Protection includes every live accepted message (also unclaimed queued sends), nondiscarded draft, and retained message/publication. reserve_send locks storage account, Ally, Conversation, Message, then affected FileVersion rows in UUID order. It validates ready state and adds MessageFile relations atomically with acceptance. Discard, removal, cancellation and cleanup follow the same applicable lock order. Never check references before locking the file and delete later without a state fence.

Cancellation adds draft protection before removing message protection in one transaction. Removal/discard releases only its own relation. Under the file lock, successful immutable-object cleanup rechecks all protection and may set cleanup_pending only with no reference and no active upload/inspection lease. Reuse rejects cleanup_pending/deleted. If reuse wins first, cleanup sees the queued relation and cannot delete. Object I/O follows cleanup_pending commit with a generation fence. Ally deletion overrides references only after its tombstone denies new operations.

That reference rule protects successful immutable bytes. Incomplete generation staging follows the cleanup rule below. A pending/receiving generation with no progress for 24 hours and no live receiver lease is eligible for staging cleanup even when its message/draft remains referenced. Under account/file locks, fence that generation's writer, record its staging key for deletion, and set the file to failed with upload_interrupted. Preserve the FileVersion ID, expected manifest, message/draft relation, and all ready sibling bytes. A late writer cannot promote after the fence. Delete only that expired generation key outside locks. Release its reserved bytes once after confirmed staging deletion; failed deletion retains the reservation and cleanup record. Do not set the referenced logical file to deleted or remove its metadata.

Retry after this cleanup reserves the expected bytes again under the account lock and advances generation atomically before issuing a new writer. If old staging deletion is still pending, retain that reservation and renew it for the new generation without double release: do not start the new upload until deletion is confirmed. Capacity denial leaves the same failed file and retryable draft unchanged. Retry with the old generation request replays the newly committed generation; a late completion for the cleaned generation is rejected. Ready sibling objects require neither upload nor new reservation. This separates temporary-body cleanup from immutable-object cleanup without weakening live accepted-message protection.

Accounting counts each object once, not each reference. Reuse reserves no extra bytes. retained_bytes includes ready draft objects and delivered versions; promotion transfers reserved to retained once. Removing references does not decrement bytes until confirmed deletion, which releases the charge exactly once under account/file locks. Failed deletion keeps charge and evidence. Draft file references use the indexed FileDraftFile relation below, not opaque JSON, so cleanup can query them under the file lock.

### Storage, inspection, retention and access

Initial extension allowlist: jpg, jpeg, png, gif, webp, heic, heif; pdf; doc, docx; xls, xlsx, csv; ppt, pptx; txt, md, markdown; js, jsx, ts, tsx, html, htm, css, json, py, rb, go, rs, java, c, h, cpp, hpp, cs, sh, sql, yaml, yml, xml, toml. Publish one versioned extension/type mapping. Check binary magic/container structure and bounded UTF-8 for text/code. Reject mismatch, encrypted unreadable containers and macro-bearing Office files clearly. Cap Office parsing at 1,000 entries/100 MB expanded; never silently drop a rejected file.

Cloud streams bytes through authenticated endpoints into a separate private R2 bucket; no user receives storage URLs. Spool in 64 KiB chunks, <=25 MB, with 120-second total/15-second idle timeout. Limit receiving work to two files per owner and eight per worker deployment. Verify proxy buffering and disk limits in staging. Reads never load complete files in application memory.

Scan both directions with isolated ClamAV before ready. Fail closed on malware, unavailable scanner, definitions older than 24 hours, timeout or parser failure. Scan deadline 60 seconds; at most three automatic attempts with 5/30/120-second backoff, then explicit retry. Malware requires removal/reselection. Pin scanner image/version; test EICAR and harmless fixtures. No file content is sent to a third-party analysis service.

Promote validated bytes to a new random immutable key; never expose a writer for that key. Verify stored hash/size before ready. Database failure leaves a recorded cleanup candidate. Same publication retry returns the same IDs/hash; source edits require a new source_version_id/publication. Foundry keeps its working copy and immutable retry spool.

Images use re-encoded raster previews with 40-megapixel limit; GIF first frame. HEIC/HEIF needs a reviewed decoder in an isolated worker before those formats enable; missing decoder is a release gap. PDF uses isolated raster pages, up to 100 pages, loaded lazily; preview failure still offers clean Download. Text/Markdown/code/HTML is escaped plain text, capped at 1 MB with truncation notice and full Download. No raw Office/SVG preview. Use nosniff, private no-store, sandbox CSP, inert preview types and attachment disposition with safe filenames. The app does not auto-open downloaded files; it cannot promise behavior in a separate user application.

Retained versions and ready recoverable draft files have no age expiry while the Ally exists. Remove partial staging after 24 hours, rejected bytes after verdict, and unreferenced promotion candidates after 24 hours. Preserve message/selection metadata. Cancellation restores drafts; it does not silently discard successful bytes. Explicit draft discard releases unused ready objects. Cleanup runs at most 100 indexed rows and 60 seconds per task, leases/fences rows, performs I/O outside locks, and retries five times before alerting with durable evidence. No routine broad bucket scan. Record every staging key before I/O so crash cleanup is possible.

Atomic reserved+retained accounting protects aggregate storage. Proposed operational ceiling: 10 GB per workspace, adjustable upward, alert at 80%, reject new reservations at 100% with storage_capacity_unavailable. Existing files remain readable. This admission policy requires engineering and product-owner review before release; it does not reduce 25/10/50 or expire retained files. Failures can retry after capacity expansion. Reconcile counters in bounded ID pages. Cleanup releases abandoned partial reservations but preserves draft metadata for renewed reservation on retry.

Deletion integration must run under the owner's Ally tombstone boundary: immediately deny reads/admission/dispatch, cancel uploads/publications, then remove file/preview keys with durable retries. Keep cleanup identity until object deletion and Foundry working/spool cleanup acknowledgement. Remote failure cannot restore access. Current Cloud has no product entrypoint, so assignment and integration are a release blocker; CLD-010 does not independently invent general deletion UI/lifecycle scope.

### Foundry file pipeline

The new provider-neutral `runtime/allies_runtime/files.py` owns local verified file placement and immutable spools. `backend/runtime/services/files.py` owns authorization and the Cloud transport adapter; `backend/runtime/api/register.py` exposes narrow authenticated runtime routes. `FoundryClient` calls those routes. The runtime and Hermes never receive Cloud service credentials or object-store credentials. Use the existing runtime workspace identity plus attempt lease for incoming reads and active publication calls. Recovery uses the current workspace generation and assigned profile, without an attempt lease or new execution. Backend validates that identity before invoking the Cloud internal endpoints above.

#### Foundry functions and durable shapes

| Category / location | Shape or operation | Contract and persistence |
| --- | --- | --- |
| DTO, backend contracts and runtime client | FileDescriptor | file_id/name/media_type/size/sha256, same bounded ordered manifest as Cloud. Preserve in input_payload and claim payload; no machine path in external commands. |
| Service, runtime files | `stage_incoming(claim, descriptors) -> StagedManifest` | Resolve claimed profile, stream all bytes, verify hashes, commit a complete local receipt before Hermes sees any file. |
| Service, runtime files | `freeze_publication(context, call_id, paths) -> PublicationManifest` | Validate relative paths within profile workspace; freeze regular-file bytes and metadata once. Same profile/source message/tool-call ID returns same publication. |
| Internal local journal, runtime files | PublicationManifest | UUID publication/source versions; source message/profile; size/hash/name per file; spool relative keys; state frozen/reserved/uploading/ready/failed; Cloud IDs/revision. Atomic replace and fsync on durable volume; <=64 KiB per manifest. No credentials. |
| Internal local receipt, runtime files | StagedManifest | command ID, ordered immutable Cloud descriptors and workspace-relative installed paths, manifest hash. Atomic commit marker after all verified files; same command/hash replays, changed hash conflicts. |
| Service, runtime files | `recover_publications(profile, limit=20)` | Bounded Cloud retry claims through Foundry backend; find journal by publication ID; never rerun Hermes; preserves ADV-001 generations/leases/results. |
| Existing persistence, backend | Execution.input_payload | Add optional files; no new copy of Cloud file tables. Preserve command fingerprint and persisted payload digest. |
| Database model, backend/runtime/models.py | PublicationIntent | Recovery correlation and authority before Cloud registration; fields, uniqueness, due-state index and replay rules defined below. No product file metadata authority is transferred from Cloud. |
| Existing profile cleanup | ProfileStore.cleanup | Remove workspace file copies and runtime journal/spools under the same profile fence; report existing cleanup receipt only after actual removal. |

Incoming placement uses `<profile>/workspace/attachments/<command_id>/` with file UUID plus sanitized basename. Download to an adjacent private staging directory; verify all 1..10 files before one directory rename and receipt commit. The model receives only the committed manifest. Crash before commit leaves no model-visible partial manifest; replay verifies existing hashes and completes or repairs staging. Existing later working-file edits must not be overwritten by replay: committed receipt skips reinstallation; recovery of a missing received file uses a new isolated copy, not overwrite of an edited path. No network I/O holds profile locks; hold the short profile/file commit lock only for manifest checks and rename. Keep attempt renewal running during staging. Bound transfer at existing 25/50 MB limits, two concurrent files, 120 seconds/file and five minutes/set. On failure publish a safe pre-model failure; do not invoke Hermes with only part of the files. Existing Cloud execution reconciliation remains authoritative once the command is accepted; do not report this as an upload failure or manufacture a new message.

Files-only sends require changes at every text validator: backend ExecutionInput, persisted payload validation, runtime claim validation and Hermes adapter input. Keep external text empty; at the Hermes boundary create a bounded internal user-turn representation containing optional text plus the staged manifest and an instruction that files are user data. It is not stored as replacement Cloud text. Modify the pinned Hermes request patch to accept the manifest as structured context, with max 10 descriptors and no inline contents, so a 16,000-byte text send is not rejected by concatenating paths. Runtime validates the structured field before model invocation and directs file tools to this profile's workspace. Preserve bootstrap ordering, stable session IDs and existing lease/event/replay behavior.

#### Model-facing publication capability

Before freezing bytes, persist a narrow Foundry `PublicationIntent` row through the currently authorized attempt. Fields: publication UUID (unique), profile/source execution and Cloud binding/message IDs, tool-call digest (unique per source execution), state preparing/frozen/registered/failed, manifest digest nullable until frozen, next_due_at, attempts, safe_error and timestamps. The row holds correlation and recovery authority, not file bytes or Cloud product truth. Same attempt/tool-call request returns the original ID; changed descriptors conflict. Add this model/migration with the publication proxy. No spool is committed before intent acknowledgement; if the acknowledgement is uncertain, repeat the same key. This one durable record closes the gap between local freeze and Cloud registration without creating a model execution.

The intent is claimable by the currently assigned runtime profile/generation after the originating attempt ends. Authorization derives from persisted original attempt ancestry and current live profile, never a client-supplied replacement source message. The runtime first checks the local journal for that ID; a frozen journal supplies the exact manifest/hash for idempotent Cloud registration. It may register/transfer that frozen version through the backend even with no active attempt lease. The control-plane recovery command considers due unregistered intents as well as Cloud due bindings, and wakes their workspace through the existing deduplicated wake path. A runtime startup pass reconciles at most 20 intents in stable ID pages, then Cloud retry work. Thus sleep, process death or machine replacement cannot make a frozen version undiscoverable.

Add POST `/attempts/{attempt_id}/file-publication-intents` with `{"tool_call_id":"call-1","files":[{"name":"result.csv","size":12}]}` → `{"publication_id":"{id}","state":"preparing"}`; backend derives all scope. Runtime POST `/profiles/{profile_id}/file-publication-intents/{publication_id}/frozen` carries `{"files":[{"source_version_id":"{id}","name":"result.csv","size":12,"sha256":"<64hex>"}]}` → same ID/state frozen. This acknowledgement is replayable; startup can reconstruct it from a committed journal. GET `/profiles/{profile_id}/file-publication-intents?limit=20&cursor=...` returns scoped ID/state items and next_cursor. These routes use current runtime/profile generation; only intent creation requires the source attempt lease. Once frozen, only the exact manifest can be registered. Cap intent recovery to five attempts with 5/30/120/300-second delays, then retain failed state for explicit Retry; no polling loop creates fresh intents.

Cloud exposes the same recoverable publication identity even before full registration through an idempotent internal status upsert: POST `/internal/v1/file-publication-status` with `{"publication_id":"{id}","binding_id":"{id}","message_id":"{id}","state":"failed","error_code":"publication_unavailable"}` → PublicationView without links. Only Foundry service with matching source ancestry can create this placeholder; later reserve fills its manifest once under the same ID. Backend retries this status upsert from the durable intent if Cloud is unavailable. Until that projection arrives, the reply may show an unlinked publication failure, never a false successful link. Interface retrieval/Retry uses the existing publication routes once projected. Cloud retry for a placeholder is routed to the matching Foundry intent and its frozen journal; no model rerun. A pre-freeze failure with no committed snapshot is explicitly source_unavailable and is not claimed to have retryable bytes.

The status endpoint is create-only placeholder creation, despite the upsert transport name above. Under the publication identity lock, verify that an existing ID has the same authenticated binding/source-message ancestry; mismatch returns 409 without mutation. If the row exists, return its current PublicationView and do not change state, manifest, revision, leases or errors. Thus a delayed failed-status request cannot downgrade a reserved, validating or ready publication. Reserve and placeholder creation serialize on the same unique publication identity; reserve may fill an unregistered placeholder's manifest once, while a competing delayed placeholder call only reads the resulting state.

Crash cases: before intent acknowledgement, no frozen bytes exist; after intent but before freeze, incomplete copy follows bounded cleanup and reports source_unavailable; after freeze before frozen acknowledgement or Cloud reservation, journal reconciliation resumes the same version; uncertain Cloud reservation replays the same publication/hash; after attempt completion, current profile generation plus durable intent permits recovery. This supersedes any earlier statement that only an active attempt can reserve every publication or that Cloud's due feed alone discovers all recovery work.

Add a small image-owned Hermes tool `publish_files(paths: list[str])` through a pinned image patch/tool registration, using the existing profile/session request context. Input is 1..10 paths relative to the current profile workspace, no URL, absolute path, traversal, glob, directory or alternate profile selector. The tool-call ID plus bound source message yields a stable publication UUID; model-supplied identities are not trusted. A context-bound local runtime bridge performs the file work. Follow the existing opaque credential resolver pattern: no backend service token enters prompts, tool results, image settings, journal or file contents.

The bridge opens path components using no-follow descriptor operations and verifies regular files under the authorized workspace, rejecting symlinks, hard-linked files with link count above one, device files and profile configuration/credential areas. Do not rely only on resolve-then-open. Copy from the opened descriptor into a runtime-owned spool outside the model-writable workspace, hash while copying, and verify source stat before/after. A detected concurrent edit returns source_changed; retry can request a fresh publication but cannot silently replace an already frozen one. Snapshot commit uses atomic rename/fsync; stop at 25 MB/file or 50 MB/set. Cloud's validation remains the final type/malware gate. A working copy stays intact.

Local spool directory is under the existing durable volume's profile namespace but outside Hermes's writable workspace and excludes it from file tools. Enforce filesystem permissions and separate runtime/Hermes identities in the runtime image boundary; test that model-side tool execution cannot read spool/bridge credentials or another profile. If existing image permissions cannot enforce this, the image change is required before enablement, not an assumed isolation property. Keep the interface provider-neutral; do not add hosting vendor names to core.

Local spool admission is independent of Cloud quota. Initial operational defaults: 100,000,000 bytes per profile, 250,000,000 bytes across the assigned volume, and at least 250,000,000 bytes free after the proposed copy. Limit each profile to two incomplete copy reservations and 20 retained publication manifests. Check these under a shared volume admission lock before creating a copy; include committed spools and reserved copy bytes. A source set still may use the full accepted 50 MB limit when capacity is available. Return local_storage_capacity_unavailable before copying if any bound fails; preserve existing frozen versions. These operational defaults join the existing capacity review, and may be raised only with measured volume headroom.

Persist local reservations in an atomic runtime-owned volume journal keyed by publication ID; reconcile at startup against manifest/copy directories in bounded pages of 100 entries. A crash cannot free a reservation while its bytes remain. Hold the admission lock only for ledger/state updates, not file copying. Check free space before each 64 KiB write; on ENOSPC stop, retain the durable intent and mark incomplete. This also handles unrelated workspace growth after admission. Reserve metadata headroom within the free-space floor so a failed copy can record its outcome. If journal persistence fails, return failure and leave reservation evidence for startup reconciliation, never report frozen success.

Incomplete copy directories have a recorded generation/lease and are not valid snapshots. After receiver lease expiry and 24 hours without progress, fence and remove only incomplete bytes, at most 100 entries/60 seconds per pass; release the reservation after confirmed deletion. A committed frozen manifest is never age-deleted, even after Cloud quota rejection or repeated recovery failure. It counts against local limits until durable Cloud ready permits spool deletion or profile deletion. Delete failure retains its charge; duplicate cleanup cannot release twice. Admission stops rather than consuming space reserved for other profiles. Test concurrent profiles, repeated Cloud rejection, disk-full during copy/journal commit, startup reconciliation and partial cleanup, with valid frozen hashes unchanged.

Tool response is `{"publication_id":"{id}","state":"ready","files":[{"name":"result.csv","open_path":"/files/{id}"}]}` only after Cloud validates all files. Pending or failure is `{"publication_id":"{id}","state":"failed","retryable":true,"error_code":"publication_unavailable"}` with no link. The Ally can explain the failure. A later user Retry runs publication recovery, not the model tool again. Raw machine paths are never returned as user-facing links. Cloud stores the publication status independently of reply completion so a failed tool result still has a recoverable reference.

#### Foundry transport and recovery wiring

Runtime routes below are relative to Foundry's runtime API mount, fixed in generated fixtures in Phase 1. They use existing runtime authentication; backend adds workspace/profile ancestry, generation and lease checks, rather than forwarding caller IDs blindly.

| Route | Request / response example | Authorization and bounds |
| --- | --- | --- |
| GET `/attempts/{attempt_id}/files/{file_id}/content` | No body → binary bytes | Current attempt lease, manifest membership and profile; backend forwards Cloud accepted-file request. No arbitrary URL. |
| POST `/attempts/{attempt_id}/file-publications` | `{"publication_id":"{id}","files":[{"source_version_id":"{id}","name":"result.csv","size":12,"sha256":"<64hex>"}]}` → Cloud PublicationView | Current attempt/profile; backend derives binding/source message. Same UUID/manifest replays. |
| PUT `/profiles/{profile_id}/file-publications/{publication_id}/files/{file_id}/content?generation=2` | Raw bytes → FileView | Either active source attempt context or current recovery lease/revision; scoped workspace generation. Preserve exact Cloud generation fencing. |
| GET `/profiles/{profile_id}/file-publications/{publication_id}` | No body → PublicationView | Current assigned profile and registered source publication; same limits/errors as Cloud. |
| POST `/profiles/{profile_id}/file-publication-retries/claim` | `{"limit":20}` → retry item list | Current workspace generation, assigned live profile; backend narrows Cloud discovery to that binding. |
| POST `/profiles/{profile_id}/file-publications/{publication_id}/retry-result` | Existing revision/token/outcome JSON → PublicationView | Same scoped recovery context; stale generation/token denied. |

Amend Cloud recovery claim request to accept a required binding_id derived by Foundry backend; it must match the authenticated service's authorized binding. This avoids a tenant runtime claiming another workspace's retry. Runtime never sees a global feed. The recovery pass runs at startup and every 30 seconds in FoundryWorker's existing service loop, alongside profile reconciliation, even when no model claim is active; compose it in composition.py. It uses at most one 20-item batch per profile pass and the existing bounded assigned-profile pagination. Run only one transfer at a time per profile; yield between bounded batches so execution lease renewal is not starved.

When a tenant machine is asleep, the Foundry control-plane recovery command discovers due Cloud retry bindings in bounded 20-item pages every 30 seconds, maps them to registered live profiles and invokes existing workspace wake intent. It does not claim runtime upload leases and does not create an Execution. Add a read-only Cloud due-binding endpoint restricted to the service: GET `/internal/v1/file-publication-retries/due-bindings?limit=20&cursor=...` → `{"binding_ids":["{id}"],"next_cursor":null}`. Stable keyset cursor; no file names or paths. Foundry wakes at most 20 workspaces/run and uses existing wake dedupe/backoff. Cloud remains the due-state authority. This closes the stopped-machine gap without keeping every machine awake.

After replacement, the existing assigned volume and profile reconciliation recover journals and files; a new runtime generation cannot use old attempt/retry credentials. Stop admitting publication calls as soon as profile cleanup begins. The existing cleanup request fences publication operations, waits/reconciles active work and removes runtime spools plus workspace files; expired cleanup remains repair_required, not success. The Cloud deletion owner consumes the existing Foundry cleanup receipt. Test two profiles on one volume and deletion of only one; never delete another profile's files or the shared volume. Spools remain until Cloud ready or explicit deletion; remove a ready spool only after durable ready receipt, since Cloud then owns immutable bytes.

### Frontend Interaction Shapes (contract only)

| Entry/action | State and mapping | Required behavior |
| --- | --- | --- |
| Photos/Camera/Files | Local descriptors only | No upload on selection; camera failure leaves alternatives usable |
| Send | draft → uploading → queued → delivered | Reserve then transfer; per-file progress; accessible status |
| Retry/Remove | failed → uploading/needs_retry → explicit send | Keep ready files; distinguish upload/send/publication/retrieval failure |
| Cancel | cancelling → cancelled on server success | Restore draft; 409 preserves truthful state |
| File link | loading → preview/download or failure | Modal name/type/size, focus trap, Escape and focus restoration, keyboard Download |

## Phases

### Remote synchronization and implementation coordination

On 9 September, the parent fast-forwarded clean main dev checkouts to Cloud `dd8bba6` (27 commits), Foundry `1d03ea5` (40), and Interface `f21e5ff` (18). Each then reported HEAD...origin/dev 0/0. Planning worktrees use these bases. This records synchronization, not feature test evidence.

Open Cloud PR `feat: add routine intent persistence foundation`, branch `ft/cld-013-routine-management`, touches shared registration/configuration in `backend/config/api.py`, `openapi.py`, `settings.py` and `backend/pyproject.toml`. Parent's merge-tree check against the committed Cloud plan succeeded; this does not establish that future implementation merges cleanly. Open Foundry PR `feat(runtime): add gated routine conversation execution (FND-012)`, branch `ft/fnd-012-routine-conversations`, overlaps `backend/runtime/contracts.py`, `api/register.py`, `models.py`, `services/claims.py`, `services/workspaces.py`, `runtime/allies_runtime/foundry.py` and worker tests.

Before implementation and before each affected PR merge, fetch dev and the open PR heads, inspect their current status/diffs, and refresh the implementation base. Record both source SHAs and decide merge order with the routine owner before opening a combined validation revision. Preserve dirty work before rebasing; never reset another worker's changes. Reconcile file capability, execution input and claim schemas with routine execution explicitly, including omitted optional fields, fingerprint compatibility and the correct conversation/profile scope. Keep file staging/publication limited to supported command kinds; routine changes must not silently inherit a conversation-message contract. After integration rerun routine and file contract/claim/worker tests, unchanged text/bootstrap fingerprints, empty-text file input, configuration and migration checks on the combined revision. Do not merge the open routine PRs as part of planning; current remote heads may change before implementation.

Implementation PRs target dev from `ft/` or `fix/`, include tests/migrations and Codex co-author trailer. Aim for one behavior reviewable in 20–30 minutes and roughly 200–500 changed lines. Split larger work where coherent; explain larger atomic contract/migration work rather than omit tests.

### Phase 1 - Contract and capability

- Publish reviewed schemas, errors, byte units, fixtures and rollout contract under `docs/engineering/` and authorized Nabu after plan acceptance.
- Impact: gateway contracts/tests and OpenAPI fixtures; admission off.
- Exit: consumers accept fixtures; text command bytes unchanged. This contract is FND-011/INT-106's start dependency, not full CLD-010 completion. Assign deletion integration owner and resolve operational policy review.

### Phase 2 - Storage and intake

- PR 2a: files app, models/migrations, provider boundary, reservations and immutable writes with tests.
- PR 2b: bounded intake/inspection and metadata API with negative authorization tests.
- Impact: `backend/files/`, config registration/settings and deployment inventory. No avatar rewrite.
- Exit: boundary, uncertain-write, scan-failure and crash recovery tests pass; admission off.

### Phase 3 - Ordered send and recovery

- PR 3a: preparation/manifests, queue gate and PostgreSQL race tests.
- PR 3b: retry/remove/cancel/draft reuse/projections and capability-checked exact-byte dispatch.
- Impact: chat models/services/API/tests and gateway contract.
- Exit: files-only, no overtaking, cancellation fence, refresh recovery and text regression pass.

### Phase 4 - Return and private opening

- PR 4a: scoped publication, fixed-version retries and reply association/link validation.
- PR 4b: authenticated download, isolated inert previews and failure fallback.
- Impact: Cloud files, activities reply projection and gateway; coordinated Foundry work is in Phase 6. Interface remains later.
- Exit: source edits do not change old versions; failed publication has Retry, no broken link; foreign access denied.

### Phase 5 - Retention and deletion integration

- PR 5a: bounded cleanup, accounting reconciliation, privacy-safe metrics/runbook.
- PR 5b: connect file revocation/cleanup to the separately owned deletion entrypoint and Foundry acknowledgement.
- Exit: remote delete failure cannot restore access or erase cleanup identity; retained files survive maintenance; capacity policy accepted. If deletion entrypoint is absent, release remains blocked.

### Phase 6 - Foundry implementation slices

These separate Foundry PRs are part of the same implementation episode. The Terra high worker may handle both repositories, but each PR targets its own dev and includes its own tests. Shared contract changes land in Cloud Phase 1 and Foundry F1 before dependent runtime behavior. Cloud Phases 2–5 can proceed alongside F2–F4 behind disabled admission.

| PR | Work and affected paths | Merge dependency / exit evidence |
| --- | --- | --- |
| F1 Contract and backend adapter | backend/runtime/contracts.py, services/executions.py, services/files.py, API schemas/register, contract tests; sanitized portable contract docs | Cloud Phase 1; preserve text/bootstrap fingerprints, new file manifest survives command→claim, scoped fake Cloud transport passes |
| F2 Incoming staging | runtime/allies_runtime/files.py, foundry.py, composition.py, Hermes structured input patch and adapter; staging/worker tests | F1 plus Cloud intake/dispatch; all files commit before one model invocation, no partial invocation, two-profile isolation |
| F3 Publish capability | runtime file spool/bridge, image-owned publish tool and Docker build integration; backend publication proxy routes | F1/F2 and Cloud publication endpoints; existing/new working file returns real product reference, unsafe paths rejected, edited source cannot replace frozen bytes |
| F4 Durable recovery | runtime recovery pass, backend bounded wake recovery management command and transport; process/volume tests | F3 and Cloud retry protocol; Retry after polling stops or machine replacement transfers same spool without a model execution |
| F5 Cleanup and integration | existing profile cleanup hooks, runtime cleanup tests, sanitized backend round-trip harness | Cloud deletion boundary plus F2–F4; correct profile removal, receipt failure stays pending/repair, old versions survive source edits/replacement |

Keep each PR near the repository's 200–500-line review target; split F2/F3 runtime versus pinned image work when both intermediate states remain disabled and tested. Do not bundle unrelated provider lifecycle changes. Reassess size before opening a PR.

### Phase 7 - Backend integration, then Interface release

- First run the real Cloud→Foundry→runtime→Cloud file round trip through API clients and the runtime publication tool, before Interface exists. Record exact SHAs, hashes and model invocation counts with sanitized fixtures. This is backend acceptance only.
- Later coordinate INT-106 and DSN-008 web/real-device review, including app interruption and machine replacement. Backend acceptance must not close the user-facing feature.
- Deploy Cloud readers/capability, Foundry, clients, then test-workspace admission. Expand only after accepted evidence and operational checks.
- Exit: all criteria below, with sanitized evidence and exact repository SHAs. Cloud unit success alone cannot close CLD-010.

## Acceptance Criteria

1. Web/mobile Photos, Camera, Files and permission recovery work; selection alone does not upload.
2. Both directions enforce 25,000,000/file, 10 files, 50,000,000/message across publication calls.
3. Optional text and all files reach only the intended Ally together, once, in sequence. Other Allies proceed.
4. Failure retains successful files; retry/remove requires explicit resend; empty file-only sends never dispatch.
5. Confirmed cancellation prevents later delivery and restores draft; claim races remain truthful.
6. Switching and interruption preserve state; reselection occurs only when local access is required and missing.
7. Ally can use incoming files later or explain reading limits. FND-011 proves working-copy continuity.
8. Return retry uses frozen version; no broken link. Old link hash stays fixed after source edits/replacement.
9. Modal provides safe preview or information/Download; retrieval retry does not republish.
10. Anonymous/foreign-owner/foreign-Ally/stale-binding access fails; logs/events omit private data.
11. Retained files do not expire; Ally deletion revokes immediately and removes Cloud/Foundry files through durable cleanup.
12. Scanner, previews, aggregate policy and cleanup pass review; integrated proof includes failure, cancellation, authorization and later retrieval.

## Backend Considerations

### Query Optimization Plan

Prefetch ordered MessageFile/FileVersion and publication summaries for bounded conversation pages. Target at most three added queries, not one per file. File access selects Ally/workspace/source message. Queue head remains an indexed ordered query. Compare query growth at 1/10 files and a full page.

### N+1 Prevention

Prefetch queue and history alike. No storage HEAD per read: verified metadata is persisted. Cleanup uses indexed state/time keyset batches. Reservations process at most ten descriptors under one account lock.

### Detailed Unit Test Cases

- Happy: text+files, files-only, returned existing file, old version.
- Invalid: zero/oversized bytes, 11 files, aggregate edges, type mismatch, malformed/encrypted container, unsafe name, duplicates, hash mismatch.
- Auth: missing/foreign session, wrong Ally/workspace/binding/message, tombstoned Ally, reserved-file access.
- Retry: same-key replay, changed manifest conflict, stale generation, ready-file retention, explicit resend, fixed publication hash.
- Return recovery: retry after interactive polling ended; recovery worker/process replacement; death after upload before acknowledgement; expired lease/stale acknowledgement; exhausted attempts; missing spool; failed generation advances while ready siblings retain IDs/hash. Assert no new model execution.
- Pre-registration recovery: crash after freeze but before Cloud reservation, lost intent/frozen acknowledgements, uncertain Cloud reservation and recovery after source attempt completion or sleeping-machine replacement. Same publication ID/hash is registered and its failure projection becomes retrievable; model invocation count does not increase.
- Status ordering: replay failed-placeholder creation after reserve, validation and ready; race placeholder against reserve; reuse ID with foreign ancestry. Current publication state/manifest/revision/lease remains unchanged, and foreign ancestry fails without mutation.
- Local capacity: repeated Cloud quota rejection, concurrent profiles, shared-volume admission races, ENOSPC and failed journal commit, startup reservation reconciliation and expired incomplete-copy cleanup. Bounds reject new work before copying; committed retry versions never expire or lose accounting.
- Reference protection: accepted queued reuse then source draft discard; concurrent reuse/discard/cleanup and cancel/reuse; cancellation creates draft protection atomically; failed delete retains charge; final successful deletion releases bytes once. A queued reused file must still dispatch with its original hash.
- Temporary cleanup: a referenced abandoned partial generation is removed after 24 hours without deleting message/draft metadata or ready siblings; a late writer cannot promote. Retry renews capacity and advances generation once, including duplicate retry, quota denial and delayed deletion; no reservation is released twice.
- Failure: scanner down/stale, storage write/read/delete timeout, database failure after promotion, restart, publication failure, preview fallback.

## Frontend Considerations

### Data Path

INT-106 selection → app-level upload manager → Cloud reservation/bytes → message projection → modal metadata/content. Publication result enters durable reply association. No storage/runtime URLs reach UI. Transport progress is temporary; Cloud readiness is authoritative.

### State Management Considerations

Cloud owns message/file/publication truth. Interface owns local handles/textbox edits. Upload manager sits above selected-Ally views. Cache by scope/ID/revision; invalidate on mutation/reconnect and ignore stale revisions. New drafts are separate from dispatched messages. Server dedupe remains authoritative. No frontend implementation is included in Cloud slices.

## Test Plan

### Foundry and backend integration checks

- Foundry root, local/test environment: set `DJANGO_DEBUG=true`; run `make sync`, `make check`, `make lint`, `make validate`. The last target runs `uv run --locked --project backend python scripts/validate.py`, which validates both lockfiles, Django/migration drift, backend coverage and runtime coverage. It does not replace Ruff lint.
- Focused backend: `make test APP=runtime/tests/test_cld005_contract.py`, `make test APP=runtime/tests/test_workspace_lifecycle.py`, `make test APP=runtime/tests/test_fnd006_profiles.py`; new file/proxy tests in `backend/runtime/tests/test_files.py` run with `make test APP=runtime/tests/test_files.py`.
- Focused runtime: `uv run --locked --project runtime pytest runtime/tests/test_files.py runtime/tests/test_foundry.py runtime/tests/test_profile_store.py runtime/tests/test_composition.py`; run `make runtime-test` for the existing coverage gate (90%). New test_files.py is planned, not currently present.
- Foundry migration verification from backend: `uv run --locked python manage.py migrate --noinput`, `uv run --locked python manage.py migrate --check`. For changed row-lock behavior run relevant backend tests against configured PostgreSQL, not only SQLite. Add the test marker/config only if new PostgreSQL-specific tests require it; current Foundry config does not define Cloud's marker.
- Image validation: current CI command `docker build --tag allies/runtime:ci --file runtime/Dockerfile runtime`; run `make hermes-image-test` for the changed pinned Hermes image, adding a deterministic publication-tool smoke script with the same image-owned pattern. A fake Cloud endpoint proves tool registration, profile context, structured files-only input, safe link output, permissions and credential non-disclosure without external providers. Record image build/runtime results separately from unit tests.
- Backend round-trip harness in private Cloud tests uses two owner accounts and two Foundry profiles with a real local Cloud/Foundry stack and Hermes test model. Send mixed files/text, stage all bytes, publish an existing and a newly created file, retrieve hashes, mutate source, restart worker and replace machine while retaining volume. Inject upload/publication failures, cancel versus finish, discard a reused draft, and expire a referenced partial generation. Assert no duplicate model turn on publication retry and no cross-profile access. Reuse existing continuity proof hooks for optional provider replacement evidence; ordinary tests use fake provider and real temporary volume.
- Deletion integration is exercised through its owner-supplied callable boundary even before UI: tombstone Cloud Ally, revoke immediately, request Foundry profile cleanup, retry failed remote delete, verify only that profile's bytes disappear and acknowledgement matches the cleanup operation. Missing product deletion entrypoint remains a release gate.
- Public Foundry fixtures use synthetic IDs/data, generic service URLs and relative paths. Inspect staged public diffs for secrets/private hostnames/workstation paths/Nabu content. Do not publish this private master plan into Foundry.

### Cloud and later Interface checks

- Unit/API: new files tests, existing chat queue/dispatch/reply tests, gateway contract and negative scope tests.
- PostgreSQL: reserve races, finish/cancel, remove/finish, quota, deletion/publication, duplicate requests, earliest-message blocking. SQLite is not race evidence.
- External: dedicated private R2 test bucket, actual scanner/preview sandbox; verify hash and cleanup after restart. Use external marker and explicit non-production credentials; report skips honestly.
- Regression: chat, allies, activities, auths/workspaces and migrations; old text send/retry/queued-delete.
- Manual integration: two Allies; boundary files; failed upload then text; remove/retry; cancel during finish; close/reopen/switch; return failure/retry; source edit; machine replacement; old-link and foreign-account checks; deletion during transfer. Web keyboard/screen reader and mobile camera/permission/background/resume proof required.
- Exact root commands: `make check`, `make lint`, `make test APP=files/tests`, `make test APP=chat/tests`, `make test APP=allies/tests`, `make test APP=activities/tests`, `make test`.
- Exact backend CI commands: `uv sync --locked`, `uv lock --check`, `uv run python manage.py migrate --noinput`, `uv run python manage.py migrate --check`, `uv run pytest -m postgresql` with PostgreSQL 17 DATABASE_URL, `uv run pytest config/tests/test_uuid_schema.py`, `uv run pytest --cov=auths --cov=workspaces --cov-fail-under=90`, `uv run ruff format --check .`. Use `make format` when needed.
- Planning validation consists of evidence inspection, independent reviews, Markdown/HTML parity checks and a browser layout audit. Feature tests have not run.

## Risks and Mitigations

| Risk | Mitigation / release gate | Rollback |
| --- | --- | --- |
| Old queue skips failed preparation | Explicit preparation head gate and PostgreSQL tests | Stop new admission, retain recovery/reads |
| Strict old Foundry rejects payload | Negotiated capability and shared fixtures | Keep text path unchanged |
| HTTP abort mistaken for cancellation | Server claim lock and truthful 409 | Active Stop stays separate |
| Deletion entrypoint absent | Assigned owner, integrated tombstone and acknowledgements | Feature stays off |
| Scanner/preview operation incomplete | Isolated pinned workers and resource tests; HEIC decoder gate | Fail closed readiness; clean preview failure can download |
| Aggregate ceiling affects admission | Owner/engineering review of 10 GB policy and budget | Increase capacity/pause new admission; preserve data |
| Draft storage grows | Account bytes; discard explicitly; age-clean partial/orphan only | Never expire successful recoverable bytes |
| Rollback breaks links | Additive migrations and persistent readers | Do not reverse data migrations/delete bucket |

Open release decisions: acceptance of aggregate ceiling, scanner/preview deployment including HEIC decoder, and ownership of missing deletion entrypoint. These do not block plan review; they block feature enablement. No required risk control is deferred to an unnamed future task.
