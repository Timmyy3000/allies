# INT-107 — Web routines controls and results implementation plan

## Planning status

- Route: full.
- Status: Ready for Luna implementation handoff.
- HTML required: no. DSN-009’s accepted interim mapping, exact Aphrodite node references, and existing conversation-frame primitives provide sufficient visual authority; the review artifact is this Markdown plan.
- Planning fallback: the configured Astra planning worker was retried twice and closed after bounded waits with no artifact. This plan is authored from the accepted local handoff/state and the released contract evidence; no source implementation changes were made by the planning fallback.
- Adversarial review: final Sol review `01a0843e-35c4-7da0-bda0-9df9b22d74cc` is Ready with no ADV-004+ findings. `ADV-001` (path-resolution block) was resolved by the embedded-evidence rerun; `ADV-002` (CI-inaccessible sibling fixtures) was resolved by the explicit repository-owned/authorized-vendoring gate; `ADV-003` (ambiguous direct mutation callbacks) was resolved by the explicit Ally-conversation-mediated mutation rule and negative test. Residual concurrency, approval-fencing, and result-insertion proof remains correctly dependent on CLD-013/FND-012.
- Simplicity review `01a0843f-63c2-7ad3-94ec-fedb29053376` returned Needs revision with SIM-001..004. Dispositions: accept deferral of route-specific/OpenAPI/privileged management methods until a reviewed byte-identical CLD-013 tuple; retain only the released contract-neutral DTO/validator/projection-adapter slice now as manager-authorized independent work; remove browser-facing direct mutation methods in favor of the existing conversation `sendMessage` path; reuse existing queue/send state plus Cloud projections; and test each risk once at its owning boundary. A simplicity re-review is required after these changes.
- Simplicity re-review `01a08443-4e70-7002-b130-c2c12b298a6c` is Ready with no SIM-005+ findings. `SIM-001..004` are resolved as recorded above. The authoritative rev9 tuple and CI-safe fixture are now available and consumed by the shared contract slice. The committed CLD-013 read source is now consumed only by a bounded list/detail client adapter; production routine mutation/presentation remains held, and existing debug primitives are not production behavior.
- Rev9 correction disposition: owner-published Cloud artifact commit `e303c14ced1d3028ebb556a0664057737aa82f23` and Foundry vendor commit `cffa731573ee9c6ae25b8cfca496dca28a74b512` were verified byte-identical for the contract, fixture, and lock. The web branch now targets that tuple, vendors the exact fixture under `packages/cloud-client/test/fixtures/`, and keeps mobile/INT-108 on hold. Rev7 and rev8 remain preserved as historical inputs in git history.
- CLD-012 rev9 preserves required `routine.result.title_snapshot` equality with the accepted dispatch title, corrects schedule-generation progression to 1/2/3/4, separates Foundry-assigned dispatch identities into `required_dispatch_receipt`, and renames constraint evidence to `expected_constraint_outcome`. The rev9 fixture with SHA-256 `259577de2ea7e8343b266995767496d359aef196f1a19d6841e67ef133fb3343` is consumed without editing normative owner bytes.
- CR-002 remains deferred: the parsed-object schema enforces the compact semantic 64 KiB event bound, but original transport bytes are not checked in this route-neutral slice. Original-byte enforcement belongs to the concrete CLD-013 transport adapter and is not claimed here.
- CLD-013 read-source disposition: committed Cloud `5e1eb9d34ff11243fedc7d7e1eef01e05f6a6318` (parent `8581052a65bb3158661a37e291365bd71af569df`) is the sole authority for owner-scoped `GET /api/v1/workspaces/{workspace_id}/routines` and `GET /api/v1/workspaces/{workspace_id}/routines/{routine_id}`. The adapter reads only committed source via `git show`; it does not consume mutable scheduler worktree files or change generated OpenAPI.

## Objective and acceptance

Implement the accepted routine experience in the web conversation surface using the versioned Cloud client: routine card and detail controls, Full prompt, one-time and recurring schedule controls, browser timezone capture, truthful pending/saved/error states, running/result/delayed/failure/approval presentation, and Ally-mediated control requests.

All user-initiated routine mutations are chat-mediated. The browser sends an unambiguous, owner/routine-attributed request through the owning Ally’s existing conversation flow; the resulting Cloud projection and durable receipt drive the UI. The web surface never directly mutates routine state through a management route.

The implementation is accepted only when it also:

- preserves owner, workspace, Ally, routine, occurrence, run, and conversation attribution;
- uses expected revisions and Cloud idempotency semantics for mutations and never presents an acknowledgement or pending outbox as a durable success;
- keeps main chat, different routines, and routine results independent, with no client-side run transcript or direct Foundry call;
- preserves results after routine deletion and retains the existing chat confirmation flow for deletion;
- asks for a timezone when the browser cannot provide a valid IANA timezone instead of guessing;
- exposes running, delayed, failed, approval-waiting, expired/rejected, and retry/reconciliation states without silent success;
- introduces no full routines page, push notification, event-triggered work, user-accessible run inspection, or automatic whole-task rerun.

CLD-013 and FND-012 remain integrated release dependencies. Their absence from the current baseline must not be hidden with mock persistence or speculative route names.

## Authoritative evidence and boundaries

- Product authority: accepted Nabu specification `projects/allies/engineering/specs/routines.md`, revision `9f8226916656619b66b617eb313a59e09901e4ecc5c7b5584552ea37f6913433`.
- Design authority: DSN-009 interim handoff, revision `88845d21d12abbd65e85e63f4512ad7939d3090fa0d56ccb1826e328f09d07cd`; exact nodes `370:6544`, `370:6622`, `372:6829`, `376:7026`. The pragmatic-design waiver is accepted.
- Contract authority: CLD-012 routines-v1 revision 9, from immutable Cloud artifact commit `e303c14ced1d3028ebb556a0664057737aa82f23`; the byte-identical Foundry vendor is commit `cffa731573ee9c6ae25b8cfca496dca28a74b512`.
- Contract hashes: content revision `9`; contract `891a9eb9932be9e7826baaf313ded7c6fd4f8526a661e0be5a83b6118fee76de`; fixture `259577de2ea7e8343b266995767496d359aef196f1a19d6841e67ef133fb3343`; lock `a9dbd56d70bc8e63c74988a85e2121527ab54d398d04c086538fc2f3e4f107de`.
- Contract proof: the owner-published Cloud PR #36 head is `112c0695bb674f8720e95a02ca57c047adf1af43` and Foundry PR #50 head is `cffa731573ee9c6ae25b8cfca496dca28a74b512`; the exact three artifact blobs match across those owner repositories. Full runtime proof remains gated: Class A is `INCONCLUSIVE_REVIEW_REQUIRED` and Class B is `SETUP_BLOCKED`, with scoped runtime deficiencies owned by FND-012. Do not claim concurrency safety from the contract release.
- Drift/source guard: rev9 is the current authority for the transport-neutral routine contract, while committed Cloud `5e1eb9d34ff11243fedc7d7e1eef01e05f6a6318` is the authority for the released read-only discovery routes. Do not consume mutable sibling scheduler worktree bytes or infer routes from persistence code. Full production web wiring remains dependency-held on FND-012 and the separately gated presentation work.
- CI fixture provenance: the exact rev9 fixture is now vendored at `packages/cloud-client/test/fixtures/routines-v1.json` from the immutable Cloud artifact commit, with its source revision and SHA-256 recorded above and asserted by the contract test. Never reconstruct or edit the normative fixture bytes.
- Repository: `allies-interface`, worktree `E:/Users/Oluwatimilehin/Documents/Programming/helpers/.tmp/int-107-clean-wt`, branch `web/feat/int-107-routines`, based exactly on `origin/dev` `68936d50be0a3946cb4f2248a646095c5b771286`.
- Repository guidance: `allies-interface/AGENTS.md`, `apps/web/AGENTS.md`, and `ENGINEERING_STYLE.md`. PR base is `dev`; web branch prefix is `web/`.
- Existing primitives verified on `origin/dev`: `RoutineCard`, `RoutineDetail`, `BottomSheet`, `ActivityDisclosure`, and the existing approval sheet. They are presentation seams, not evidence of production routine behavior.
- Shared ownership: INT-107 is the single writer for `packages/cloud-client` routine DTOs, validators, mappers/adapters, and client methods. INT-108’s implementation worktree is `.tmp/int-108-impl-wt` on `mobile/ft/int-108-routines-v1`, clean at the same `origin/dev` base; it will not edit shared client files.

## Implementation sequence

### 1. Freeze the transport input and shared-client boundary

The committed CLD-013 source backs two released read-only discovery routes. The routines-v1 document still defines the transport-neutral boundary and does not authorize route-specific management calls. The manager-authorized independent slice preserves rev7/rev8 behavior as history, consumes the accepted revision-9 result contract, and adds only strict CLD-013 read DTOs plus a bounded list/detail client adapter. Do not infer additional paths, response envelopes, or Foundry calls from scheduler code.

The shared slice should be the smallest reusable surface, with ownership kept in `packages/cloud-client`:

- Add a focused routine contract module (prefer a sibling such as `src/routines.ts` or `src/mappers/routines.ts` consistent with the existing package layout) containing strict runtime schemas and exported TypeScript types for `RoutineDetail`, `RoutinePage`, `ManagementReceipt`, schedule variants, run/result/approval projections, and stable error/action-attempt states.
- Validate closed vocabularies and bounds from routines-v1: UUID correlations, `once` versus `recurring` schedule grammar, IANA timezone, second-precision UTC instants, non-empty ascending weekdays, monthly day range, full prompt UTF-8 limit, and rejection of unknown fields. Never truncate `execution_prompt`.
- Add adapters that map the exact CLD-013 Cloud response/request shapes into the public DTOs. Preserve opaque cursors and all immutable correlation fields. Do not expose Foundry models or runtime-only credentials/tool grants.
- Do not add route-specific management methods or generated OpenAPI entries. The browser-facing package adds only the committed CLD-013 owner-scoped list/detail reads; no routine production control, result/run route, approval route, or full routines page is wired. A later coordinated CLD-013/CLD-012 release may add authorized command-boundary methods with expected revision, opaque delete `confirmation_ref`, and idempotency semantics, but those methods are not part of this implementation.
- Normalize only the released stable error codes. A revision conflict refetches and asks for reconfirmation; `NOT_FOUND` does not reveal another owner’s resource; stale, pending, unknown, expired, rejected, and failed outcomes remain non-successful states.
- Keep the package’s public `index.ts` limited to the controlled Cloud client, `RoutineListOptions`, discovery DTO types, and genuinely neutral existing helpers. Keep management, dispatch, event, approval, cancellation, receipt, and projection schemas/adapters internal to `packages/cloud-client`; mobile/INT-108 remains on hold and must not duplicate or consume speculative web routes.
- Update generated OpenAPI or its pinned source only when the authoritative Cloud route artifact is added to that source. This read adapter intentionally leaves the current generated OpenAPI snapshot unchanged. Never edit the normative routines-v1 Markdown, fixture, or lock bytes in either repository.

The shared tests must exercise the exact released rev9 fixture vendored from the immutable CLD-012 owner commit plus the committed CLD-013 read response shapes: strict parsing, schedule variants, prompt preservation, owner-isolation/error mapping, opaque confirmation transport, and no-direct-Foundry rule. Keep this commit independently consumable by web; mobile remains on hold. Record the resolved fixture path/hash and committed read-source head in the implementation handoff; no full routines-page or mutation UI is added here.

### 2. Wire production web data and frame modeling

Use the existing Cloud client and conversation/activity projections rather than a second persistence layer:

- `apps/web/app/home/home-workspace.tsx`: keep routine control/approval dispatch on the existing conversation send path and pass narrowly scoped routine projection data into the production frame when the released Cloud projection is available. Include routine id, expected revision, exact confirmation reference where applicable, and the captured timezone in the request context without allowing the browser to become the mutation authority. Capture `Intl.DateTimeFormat().resolvedOptions().timeZone` only while creating a schedule, and use existing conversation queue/send feedback plus Cloud projections for durable truth. A missing/invalid timezone opens clarification; it never falls back to the machine locale or UTC silently. The committed read adapter is available for a later narrow chat-detail seam; no full routines page or mutation UI is added in this wave.
- `apps/web/app/home/conversation-frame-model.ts`: extend the existing frame model with routine card/detail, operation status, approval, running, and attributed result data. Keep ordinary messages and activity groups intact; result projections must retain `routine_id`, routine revision/title snapshot, `run_id`, outcome, delayed marker, and safe typed references. The shared result adapter requires the trusted dispatch/run tuple and rejects mismatches across title, routine/revision, occurrence/run, conversation, attempt/execution/generation, and scope before projection.
- `apps/web/app/home/conversation-frame.tsx`: render routine items and result/approval states in the production path. Derive display state from Cloud data during render; do not use an effect to convert a pending response into a fake saved state. Reconnect/refetch must not duplicate an attributed result.
- `apps/web/app/home/conversation-frame-primitives.tsx`: adapt the existing `RoutineCard`, `RoutineDetail`, `BottomSheet`, `ActivityDisclosure`, and approval primitives to accept real DTOs and callbacks. Reuse the existing focus/escape/portal behavior and existing delete/chat confirmation seam; do not add a separate delete confirmation sheet.
- `apps/web/app/home/conversation-frame.module.css`: add only the styles needed for the accepted routine states and preserve the existing visual language. Apply interface-polish guidance: concentric radii, exact-property transitions, minimum 40px hit areas, balanced headings, and restrained state transitions. Do not add a new motion dependency or `transition: all`.
- Reuse `apps/web/app/home/conversation-approvals.tsx` where its existing approval behavior fits; if the routine approval projection needs a new prop, keep the change data-driven and accessible.

The UI state model is explicit but intentionally reuses the existing conversation queue/send state for transient feedback; Cloud routine projections are the only durable truth. Add only the minimum routine/run correlation needed to disable the originating control. Do not create a second routine operation state machine or persistence layer.

| State | Display and allowed action |
| --- | --- |
| `active`/`paused` | Show schedule state, next run when present, and only the controls valid for the schedule kind; paused recurring schedules remain discoverable. |
| create/update/pause/resume/delete pending | Show an in-flight operation and disable the matching duplicate action; do not show a saved receipt until the durable receipt arrives. |
| saved/resumed | Show the returned revision/state and refetch the owner page. |
| revision conflict/stale candidate | Keep the prior truth, refetch, explain that the routine changed, and ask for reconfirmation. |
| running/approval waiting | Show routine/run attribution and approval expiry/context; approval decisions use the exact run/attempt/generation identity. |
| succeeded/unchanged | Insert one attributed result in main chat, including safe result context; no transcript/run-inspection link. |
| delayed/recovered | Mark the result visibly delayed; never imply on-time execution. |
| failed/rejected/expired/cancelled/unknown/manual reconciliation | Keep a truthful non-success state, preserve any safe next action, and never auto-replay a non-idempotent action. |
| deleted | Remove future controls/discovery but keep already attributed results visible. |

Full prompt is available in detail without truncation. Creation requires a complete task, timing, and IANA timezone; a vague suggestion remains a clarification until the Ally/user supplies the missing information. Deletion continues through the exact conversational confirmation reference and expected revision.

### Ally-mediated mutation rule

The card/detail UI must emit an attributed conversational request for every user-initiated create, update, pause, resume, delete, approval, rejection, or cancellation action. The request is sent through the responsible Ally’s existing conversation flow and includes the routine identity, expected revision, and any required run/attempt/generation or confirmation reference. A sent-message acknowledgement or pending action is not a saved management receipt. Existing conversation queue/send feedback supplies transient state; the Cloud projection/receipt supplies durable truth. No web callback may call a routine management mutation method. Deletion remains the existing chat confirmation flow, not a new confirmation sheet.

### 3. Safeguard interaction and concurrent state

- Every mutation callback is owner/routine scoped by the Cloud client; the browser never substitutes an owner id or Ally id as authority.
- Use an expected revision from the rendered detail and a stable idempotency key per user action. Do not retry changed payloads under the same key. Treat uncertain action outcomes as unknown/manual reconciliation, not success.
- On reconnect or stale query data, refetch and reconcile by immutable routine/run/result ids. Do not append a result solely because a transport retry returned it twice.
- Keep main-chat send state independent from routine operations. Results are rendered only after the Cloud projection says they are inserted into main history; UI-only insertion is not enough.
- Approval decisions require pending status and matching run/attempt/generation. Disable repeated decisions while pending and make expiry/rejection visible. The web client does not implement or claim the backend CAS.
- A routine mutation changes future admissions only. Do not rewrite a working snapshot, rerun failed terminal work automatically, or expose run conversation transcripts.
- Keep full prompts out of list responses and avoid logging credentials, tool grants, or hidden runtime notes. Sanitize error/result text according to existing Cloud-client conventions.

### 4. Tests and evidence

Add focused tests alongside the touched modules before broad validation, with each risk tested once at its owning boundary:

- shared-client unit tests for strict rev9 DTO validation, full prompt preservation/size rejection, once/recurring/DST-compatible wire mapping, timezone rejection, projection correlation, pending/unknown/error normalization, opaque confirmation transport, and exact fixture compatibility from the CI-safe owner-published path. Route-specific management method tests wait with the held route implementation;
- frame-model/component tests for card/detail rendering, operation pending versus saved, paused/recurring controls, Full prompt, running/result/delayed/failure/approval states, deletion result preservation, and accessible modal/keyboard behavior;
- one integrated workspace/component suite for browser timezone capture, ask-not-guess fallback, existing queue/send feedback versus durable projection truth, reconnect/result deduplication, concurrent main-chat/routine state, and a negative assertion that every routine mutation control emits the correctly attributed conversational request without directly invoking a management mutation method;
- browser acceptance evidence against CLD-013/FND-012 when their released heads are available: create and clarify, once/recurring save, update/pause/resume/delete confirmation, owner isolation, result insertion after deletion, delayed/failure/approval outcome, reconnect, and a concurrent chat turn. Use sanitized traces and no mock persistence substitute.

Run, from the repository root, the proportionate gates required by CI and repository policy:

1. `bun run cloud:check`
2. `bun run typecheck`
3. `bun run test:run`
4. `bun run lint`
5. `bun run build:web`
6. The relevant web Playwright checks from CI, including home smoke, chat frames, and motion checks when their scope is touched.

Record the exact commands/results, fixture hashes, current branch/base, review findings, and sanitized integrated traces in the handoff and canonical INT-107 ticket. Do not claim the CLD-012 contract’s inconclusive/setup-blocked runtime evidence as a passing Class B result.

## Review and delivery sequence

1. Sol adversarial review of this plan, using stable `ADV-xxx` findings. Record every disposition in the episode state; material plan changes return through the planning route.
2. Sol simplicity review of the revised/accepted plan, using stable `SIM-xxx` findings. Reject unnecessary abstractions, generated-contract edits without an authoritative source, new dependencies, or a second state/persistence model.
3. Luna max implementation from an execution manifest. First land the released-rev9 contract-neutral DTO/validator/projection-adapter slice, inspect its diff, and keep it separable from any future route integration. Web production presentation/queue-flow work remains held until the concrete Cloud projection/discovery source exists; route-specific wire integration remains a separately gated follow-up. Do not combine unrelated history or resume mobile.
4. Run separate ponytail-overengineering review and correctness/code review on the non-empty diff. Resolve findings through the implementation worker or orchestrated integration, then run the full validation set.
5. Create/update a PR against `dev` only after the routine-only diff, validations, reviews, and Enkii policy review are clean. Start a separate Luna max current-head CI/Enkii/mergeability/comment monitor after the PR exists; never merge or deploy.

## Rollback and open risks

- Rollback is a PR revert or branch discard before merge; no production deployment or destructive data operation is part of INT-107. Keep shared-client and web-only commits separable so native can consume or revert the shared slice independently.
- The CLD-013 read routes are committed, but they are not yet represented in the pinned/generated Interface OpenAPI snapshot. Keep the manual GET adapter bounded to those exact two reads and update generated OpenAPI only when its authoritative source includes them.
- The rev9 contract tuple is released and byte-identical across Cloud and Foundry. Do not consume mutable CLD-013 scheduler worktree files. Full production UI and management integration remain gated on the coordinated runtime/presentation release.
- The exact rev9 fixture is vendored under `packages/cloud-client/test/fixtures/` from the owner-published immutable commit, with provenance and hash asserted by the contract test.
- The owning Ally conversational mutation path must remain available in the production frame. If a callback cannot route through it with the required attribution, do not fall back to a direct management endpoint; surface the pending/blocked state and report the integration dependency.
- FND-012 Class B runtime evidence is not yet available. Integrated acceptance must remain pending for concurrency, approval fencing, and result-insertion proof.
- DSN-009 is an accepted interim mapping, so visual parity is bounded to the supplied nodes and existing primitives; do not expand scope into a new design system.
- If a contract delta is required, route it through the normative snapshot owner and update Nabu/handoff revisions before changing shared DTOs. Do not silently reconcile implementation and specification in only one repository.

## Required handoff to INT-108

The shared-client completion message must include:

- exact commit SHA and base;
- public package import path and exported DTO/schema/adapter/client method names;
- the routine contract revision and all three hashes consumed;
- whether generated OpenAPI changed and its authoritative source;
- any native bearer allowlist or auth-scope change, with the exact file/line or explicit none;
- validation commands/results and known limitations;
- explicit statement that web UI files are separate and that INT-108 must not duplicate shared types or edit normative contract bytes.

For this correction, no INT-108/mobile handoff is authorized: mobile remains on hold, and the web branch reports the rev9 shared slice plus the bounded Cloud projection/discovery read adapter as the current limitation.
