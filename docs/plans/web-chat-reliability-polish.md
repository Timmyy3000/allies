# Web Chat Reliability Polish Plan

## Feature Overview

- Problem: 13 reported web-only chat defects in `apps/web` break reading, sending, trusting, and resuming conversations: autoscroll stalls during long tasks, file previews lack skeletons / break for `pdf`/`docx` / show wrong sizes, markdown preview is undecided, the composer grows odd top padding while typing, the approvals endpoint is polled unconditionally, the mascot overlaps text, there is no routine list manager (only debug stubs), the ally sometimes echoes the user prompt, responses are sometimes slow or fail, and refresh loses scroll position.
- Target users: web chat users reading and sending messages, approving ally actions, previewing files and markdown, and managing routines for an ally.
- Source docs/specs: `docs/plans/web-chat-reliability-polish-episode-state.md`; repo policy in `AGENTS.md`, `apps/web/AGENTS.md`, `ENGINEERING_STYLE.md`; Mobbin markdown research summarized in episode state (most common = rendered doc modal + metadata sidebar, e.g. Fabric / Craft / Dropbox Dash; inline rendered markdown, e.g. Manus / Mistral / Basecamp).
- Success outcome: all 13 items fixed or decided behind small reviewable web-only PRs, with conditional polling, stable scroll and composer behavior, correct previews, one chosen markdown pattern, a minimal routines manager on the existing Cloud contract, and explained reliability behavior with retry and recovery intact.

## Plan Hygiene and Evidence Boundaries

- Uses repository-relative paths only. No workstation paths, tunnel URLs, credentials, tokens, private deployment URLs, or customer data.
- API paths below are stable Cloud contract paths already present in `packages/cloud-client` or explicitly marked `TBD — confirm in Phase 1`. Local navigation paths and staging hosts belong in untracked operator notes, not in this plan.
- Examples use synthetic fixtures (e.g. "a seeded conversation exceeding the 200-row bound"). No real user, message, or conversation identifiers.
- Before acceptance, scan the Markdown presentation for local paths, private URLs, identifiers, credentials, and walkthrough residue.

## User Stories

1. As a chat user, I want the thread to stay pinned to the latest activity during a long-running task until I scroll up, so that I can watch progress without manual scrolling.
2. As a chat user, I want file uploads to show a skeleton loader then a correct preview, so that I know the upload is progressing and can trust the result.
3. As a chat user, I want `pdf`, `docx`, and other common types to preview (or degrade explicitly), with the correct file size, so that I am not shown a broken card or wrong number.
4. As a chat user, I want a predictable markdown preview, so that long formatted content is readable without losing my place in chat.
5. As a chat user, I want the composer to keep stable padding while typing, so that multi-line input does not jump or look broken.
6. As a chat user, I want approvals to update promptly without constant background polling, so that my device and the API are not worked when nothing is pending.
7. As a chat user, I want the ally mascot to never cover message or activity text, so that content stays readable in all states.
8. As an ally owner, I want to view all routines for an ally and pause / resume / delete them, so that I can manage automation without asking in chat.
9. As a chat user, I want the ally to never parrot my prompt back as its answer, so that I can trust replies.
10. As a chat user, I want fast-feeling responses with honest waiting states, so that slow turns do not feel hung.
11. As a chat user, I want failed or stopped responses to explain what happened and offer one safe retry, so that I can recover without duplicating work.
12. As a returning chat user, I want refresh to restore my scroll position in the current conversation, so that I resume where I left off.
13. As an operator, I want bounded polling, timeouts, cancellation, and cursor-based recovery preserved, so that polish does not trade reliability for appearance.

## Scope

### In Scope

- Web only: `apps/web` conversation thread, composer, presence, approvals UI, preview UI, markdown UI, routines manager UI, scroll behavior.
- Read-only use of `packages/cloud-client` mappers and generated contract for approvals, conversation, messages, and activities.
- Phase 1 investigations with recorded verdicts: approvals conditional-polling design, file-preview code locator, markdown pattern choice.
- TanStack Query for all server state; local `useState` / `useRef` for view state; `sessionStorage` scroll anchor only (non-sensitive).
- Accessibility and `prefers-reduced-motion` handling for every changed surface.
- Vitest + Playwright `home-smoke` and `chat-frames` coverage for changed behavior.

### Out of Scope

- Mobile (`apps/mobile`) — excluded; cannot test per episode decision.
- Backend contract changes, unless Phase 4 root-cause analysis proves echo / latency / failure originates server-side; then file a Cloud follow-up instead of changing Cloud here.
- New file-sharing backend, new routine scheduling engine, new design system, new chat transport.
- Credential storage in Zustand; no new global store without demonstrated need.

### Dependencies and Assumptions

- Base is `dev` at `f21e5ff`; delivery branch is `web/chat-reliability-polish`; PRs target 200–500 lines, split above 500, normally split above 1,000 per `ENGINEERING_STYLE.md` AL-12.
- TanStack Query owns server state. Cloud cursors (`resumeCursor` / `nextCursor`) are the recovery boundary; web never invents fallback conversation data. No chat-derived fallback data substitutes for a missing routine / file contract without a formal AL-08 exception naming owner, risk, mitigation, and revisit condition.
- Approvals contract is stable: `ApprovalSummary` / `ApprovalDetail` in `packages/cloud-client/src/mappers/approvals.ts`, transported by `packages/cloud-client/src/client.ts`.
- Routine and file contracts are uncertain on this base: current generated OpenAPI (`packages/cloud-client/openapi/allies-cloud-0.1.0.json`) exposes approvals, conversation, messages, activities, and avatar uploads, but no routine / schedule / file-preview endpoints. File-sharing backend is reported to live on a Cloud file-sharing branch. Phase 1 must resolve this before preview byte-wiring or manager mutations (Phase 3 gate below).
- The live conversation surface is `ConversationFrame` in `apps/web/app/home/conversation-frame.tsx` composed by `apps/web/app/home/home-workspace.tsx`; the legacy `.composer` block in `apps/web/app/home/home.module.css` is unconfirmed legacy until Phase 2 confirms which composer ships (confirm-then-delete-in-PR or dated defer with owner; see Phase 2).
- Streamdown (`streamdown` dependency in `apps/web/package.json`) is the markdown renderer. Markdown dialogs portal outside the conversation accent scope, so the body-level `--active-chat-accent` handoff in `conversation-frame.tsx` must be preserved.
- Phase 1 contract artifact (blocking gate for Phase 3 byte-wiring and manager mutations): the Phase 1 PR description (and implementation PR preamble) must record exact repository-relative source paths, pinned OpenAPI file + version, and representative request/response JSON for every routine and file-preview binding used. No invented endpoints. Preview skeleton / size formatter / unsupported card (Phase 3a) needs no contract; byte wiring (Phase 3b) and routines pause/resume/delete must not merge without this artifact.

### Cross-Repo Sequencing (File-Sharing Branches)

- Source branches (read-only inspection in Phase 1): Cloud `ft/cld-010-file-sharing` (file backend contract source) and Foundry `ft/fnd-011` (companion). Owner for sequencing decision: interface implementer confirms with Cloud owner before adopting any cross-branch code.
- Strategy: rebase-or-merge is decided in Phase 1 and recorded in the locator outcome. Default: do not cherry-pick preview UI across repos; pin the Cloud OpenAPI file + version that exposes the file/routine endpoints, regenerate `packages/cloud-client` from that pin, and build web UI against the regenerated client only.
- Merge-block conditions: Phase 3b (file byte wiring) and Phase 3 routines mutations are blocked until (a) the contract artifact above exists, (b) the OpenAPI pin + regen step is recorded, and (c) the base/merge strategy (stay on `dev` + client regen vs documented merge of file-sharing work) is stated with owner signoff.
- AL-12 merge order (also enforced by the PR split table below): scroll / composer / mascot / polling → skeleton + size formatter + unsupported card → markdown modal → routines (gated) → reliability copy/actions. Land independent fixes first; keep gated PRs unmerged until contracts confirm.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `apps/web/app/home/conversation-approvals.tsx` | `ConversationApprovals` | `function ConversationApprovals(props: ApprovalHostProps): JSX.Element` | `client: ApprovalClient`, `workspaceId`, `conversationId`, `allyName`, `accent`, `canApprove`, `enabled`; `enabled=false` suspends queries | Thread slots + optional `ApprovalDialog` | Today: unconditional `refetchInterval: 3_000` on both queries + 1s `now` timer. Planned: conditional interval, see Phase 1 |
| `apps/web/app/home/conversation-approvals.tsx` | `approvalStatusAt` | `function approvalStatusAt(approval: ApprovalSummary, now: number): ApprovalStatus` | Derives `expired` / `outcome_unknown` from `expiresAt` / `acknowledgementDeadlineAt` | Display status | Pure; no I/O |
| `apps/web/app/home/conversation-frame.tsx` | `ConversationFrame` | `function ConversationFrame(props: ConversationFrameProps): JSX.Element` | `model: ProductionConversationFrameModel`, `actions: ProductionConversationFrameActions`, `canvasRef`, `sleeping`, `stateReady`, `runtimeIntentStatus` | Thread, presence, composer | Owns scroll-follow refs and visual-viewport sync; must not own server data |
| `apps/web/app/home/conversation-frame-primitives.tsx` | `ConversationComposer` | `function ConversationComposer(props: ComposerProps): JSX.Element` | `value`, `placeholder`, `disabled`, `sending`, `onChange`, `onSubmit`, composition handlers | Auto-resizing textarea + paste card + send button | Auto-height via `scrollHeight` capped at 83px; planned padding stabilization |
| `apps/web/app/home/conversation-frame-primitives.tsx` | `RoutineCard`, `RoutineDetail`, `DeleteRoutineSheet` | Presentational components with `name` / `schedule` / `onOpen` / `onClose` / `onDelete` | Today: hardcoded copy in `RoutineDetail` / `DeleteRoutineSheet`; planned: real props | Static cards and sheets | No I/O today; Phase 3 wires to queries and mutations |
| `apps/web/lib/allies/queries.ts` | `conversationQueryKey`, `alliesQueryOptions` | `conversationQueryKey(workspaceId, allyId) => readonly [...]` | Workspace and ally identifiers as path segments | Stable query keys | Provisioning refetch already conditional; approvals must follow the same pattern |
| `apps/web/app/home/home-workspace.tsx` | `checkActivity`, `sendMessageContent`, `submit`, `retry`, `loadOlder` | Existing callbacks; no signature changes planned | Idempotency keys (`message-*`, `message-retry-*`), `AbortSignal` cancellation | Projection + query invalidation | Timeouts, cancellation, retry, and cursor recovery per AL-05 / AL-06 |

### API and Transport Contracts

| Consumer | Method and path / event | Authentication and authorization | Request schema | Success response schema | Error responses / retry semantics |
| --- | --- | --- | --- | --- | --- |
| Web client | `GET /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/approvals` | Session via `runCloudOperation`; membership-scoped | Path segments only; max 50 summaries | `SuccessResponse<{ approvals: ApprovalSummary[] }>` | `400`, `401`, `403`, `500`; `retry: false` in UI; manual "Try again" refetch |
| Web client | `GET /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/approvals/{approval_id}` | Same as above | Path segments only | `SuccessResponse<ApprovalDetail>` with `action_label` (1–120 chars) and `action_preview` (1 char–16 KiB, no NUL) | Same as above; detail polled only while dialog open after Phase 1 |
| Web client | `POST /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/approvals/{approval_id}/decision` | Same as above + `Idempotency-Key` header | `{ decision: "approve" \| "reject" }` | `200` / `202` with `ApprovalDetail` | Same-choice safe retry ("Retry the same choice to check safely"); cross-choice blocked while intent recorded |
| Web client | `GET /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/activities` + `.../activities/stream` | Session via `runCloudOperation` | `{ limit, cursor?, replay? }`; SSE when enabled with poll fallback | `ActivitySnapshotViewModel` with `resumeCursor` / `nextCursor` | Poll budget + `pollBudgetReached` UI; cursors are the recovery boundary; `document.visibilityState` gating already present in `checkActivity` |
| Web client | `GET /api/v1/workspaces/{workspace_id}/allies/{ally_id}/conversation`, `GET /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}` with `{ limit, cursor }` | Session via `runCloudOperation` | Pagination via `nextCursor`, limit 50 for older pages | Messages + `assistantReplies` + `nextCursor` | Older-page errors surface inline with retry; history revision guard preserves windows across refetch |
| Web client | Routines list / pause / resume / delete | TBD in Phase 1 — confirm against Cloud OpenAPI / staging contract; do not invent paths. GATED: no mutations merge without the Phase 1 contract artifact (exact paths + request/response JSON) | TBD — recorded in Phase 1 artifact before any implementation PR | TBD — recorded in Phase 1 artifact | If no stable contract exists, Phase 3 ships read-only list over chat-known routines (props-only extensions, no new store) plus an explicit Cloud follow-up with owner and revisit date; never fabricate a backend; any chat-fallback data beyond read-only requires a formal AL-08 exception |
| Web client | File preview fetch | TBD in Phase 1 — locate actual preview code (staging build, file-sharing branches, or confirm missing). GATED: byte wiring blocked until locator outcome + contract artifact | TBD — recorded in Phase 1 artifact before byte wiring | TBD — recorded in Phase 1 artifact | Phase 3a (skeleton CSS state + size formatter + unsupported card) needs no contract. Phase 3b byte wiring only after locator outcome. Allowlist MIME types; MIME sniffed at boundary (not extension alone); object URLs revoked on unmount; Cloud signed URLs never logged (AL-09) |

Representative approvals payloads follow the existing `approvalSummarySchema` / `approvalDetailSchema` shapes (camelCase view model: `id`, `messageId`, `status`, `expiresAt`, `decidedAt`, `acknowledgementDeadlineAt`, plus `actionLabel` / `actionPreview` on detail). No new HTTP API is introduced by this plan except the TBD routines and file-preview bindings, which must be documented with exact repository-relative paths and representative request/response JSON once Phase 1 confirms them (contract artifact in Dependencies). Until then the plan contains no routine/file endpoint paths by design.

### Schema and Data Shapes

| Schema / model | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- |
| `ApprovalSummary` / `ApprovalDetail` | `packages/cloud-client/src/mappers/approvals.ts` (read-only) | `id: UUID`, `messageId: UUID`, `status: enum`, `expiresAt: ISO`, `decidedAt: ISO \| null`, `acknowledgementDeadlineAt: ISO \| null`, `actionLabel: string`, `actionPreview: string` | As schema; detail preview bounded to 16 KiB | NUL rejected; label length bounded | No change; web reuses as-is |
| `ProductionConversationFrameModel` | `apps/web/app/home/conversation-frame-model.ts` (read-only shape, extended only if needed) | `messages`, `turns`, `activityGroups`, `timeline`, `composer`, `queuedMessages` | `composer.draft` local; `timeline` server-derived | Derived copies define sync behavior; Cloud is truth | Additive view fields only; no persisted-state migration |
| `RoutineListItem` (provisional) | New view model in `apps/web` (only after Phase 1 confirms contract; mutations gated on contract artifact) | `id: string`, `name: string`, `scheduleText: string`, `status: "active" \| "paused"`, `nextRunAt: string \| null`, `tool: string \| null` | All required except `nextRunAt` / `tool` nullable | Unknown Cloud fields validated at the mapper boundary per AL-02 | Provisional; must match confirmed Cloud schema or be revised before implementation; without a contract, UI is read-only props-only extensions with a Cloud follow-up |
| `FilePreview` (provisional) | New view model in `apps/web` (Phase 3a needs no contract; Phase 3b byte wiring only after Phase 1 locates code + contract artifact) | `id: string`, `name: string`, `mime: string`, `sizeBytes: number`, `state: "loading" \| "ready" \| "error"`, `url: string \| null` | `sizeBytes >= 0`; `url` null until ready | AL-02/AL-07 boundary: MIME allowlist validated by sniffed content type (not extension alone); max bytes bound recorded in implementation PR; executables blocked; per-type render — images native, `pdf`/`docx`/unknown = explicit unsupported card (icon + name + correct size + download/open); sandbox/CSP for any embedded bytes; size formatted with 1024-based units via the single pure helper | Provisional; confirm whether preview bytes come from signed Cloud URLs or local object URLs; no new doc-renderer dependency (no pdf.js/mammoth) |
| Scroll anchor | `sessionStorage` key namespaced per workspace + conversation (exact key in implementation PR, e.g. `allies:scroll:<workspaceId>:<conversationId>`) | `{ messageId: string, offsetPx: number, updatedAt: number }` + TTL (e.g. session-bounded; stale anchors older than the recorded TTL are ignored — exact TTL in implementation PR) | Nullable; absent or stale means "follow latest" | Never stores message content or credentials (AL-09); id-anchored with offset, not absolute pixels | Session-scoped so refresh restores but new tabs start clean; single-flag rollback (disable anchor restore, keep follow-latest) |

### Frontend Interaction Shapes (if applicable)

| UI entry point | Hook / action signature | State shape and transitions | API input/output mapping | Loading, error, empty, and permission behavior |
| --- | --- | --- | --- | --- |
| Thread canvas (`ConversationCanvas`) | `actions.onScroll(event)` + follow flag (reconciled — see Phase 2; `followLatestRef` vs scrolled-away unified to one owner) | `following <-> user-scrolled-away` (96px near-bottom threshold); `timelineSignature`-driven `scrollTo` | No direct API; reacts to `timelineSignature` (message ids/statuses, turn states, reply lengths, pending activity lengths) | Reduced-motion uses instant scroll; user scroll-up pauses follow and shows a "jump to latest" affordance: `button` with accessible name, `aria-live="polite"` status announcing new activity while scrolled away, focus stays in thread until user activates the button |
| Composer (`ConversationComposer`) | `onChange(value)`, `onSubmit()`, composition handlers | `idle -> typing -> sending`; `data-expanded` only after height / line threshold | Draft is local; submit path unchanged (`submit` / `sendMessageContent` with idempotency keys) | Disabled while `!canChat`; send errors inline with `role="alert"`; 16,000-char bound preserved; shipped composer confirmed in Phase 2 (legacy CSS deleted in-PR or dated-deferred with owner) |
| Approvals slots + dialog | `useQuery(["workspaces", workspaceId, "approvals", conversationId])`, detail query per `approvalId` | `loading -> pending -> decision_recorded -> approved \| rejected \| expired \| cancelled \| outcome_unknown` (see Phase 1 interval table) | Summary/detail mappers as above; `decideApproval` with `Idempotency-Key` | Loading, error-retry ("Try again" manual refetch), empty (no slot), permission-gated (`canApprove`); conditional `refetchInterval` reusing the `apps/web/lib/allies/queries.ts:31-44` function-form pattern with `refetchIntervalInBackground: false`; `now` tick only while a deadline-bearing item exists; focus restored to reopen button; post-decision + focus-return + manual refetch preserved; auto-open removed or gated behind explicit user action with a11y rationale recorded |
| File preview card | `state: loading -> ready \| error` (skeleton CSS state first; no named component) | Skeleton fixed-height row with `role="status"` + `aria-busy`, then per-type render (Phase 3a needs no contract) | TBD mapper (Phase 1 artifact; Phase 3b only); `URL.revokeObjectURL` on cleanup if local URLs used; signed URLs never logged | AL-02/AL-07: allowlist + sniffed MIME + max bytes + blocked executables; images native; `pdf`/`docx`/unknown = explicit unsupported card with icon + name + correct size + download/open; errors offer retry; sandbox/CSP for embedded content |
| Markdown preview | Open entry (button / link) -> `BottomSheet` modal dialog only; close returns focus | `closed -> open -> closed`; body `--active-chat-accent` set while open | Reuses Streamdown body on already-fetched message content; no new fetch; metadata (name/updated/size) optional-only-if-model-has-it (no invented filename); long-doc threshold defined in Phase 1 verdict (implementation PR records the exact char/line cutoff for modal vs inline) | Single dialog primitive (`BottomSheet` modal): `role="dialog"` + `aria-modal`, labelled heading, Escape + backdrop close, focus trap and restore; long content scrolls inside the dialog |
| Routines manager | List query + `pause(id)` / `resume(id)` / `delete(id)` mutations (names provisional; mutations gated on confirmed contract, else read-only) | `loading -> populated \| empty`; item `active <-> paused`; delete goes through confirm sheet | View model above mapped from confirmed Cloud DTOs; props-only extensions to existing `RoutineCard` / `RoutineDetail` / `DeleteRoutineSheet` (no new store, no speculative client) | Loading skeleton, empty ("No routines yet"), error-retry, permission-gated actions; destructive delete requires explicit confirm per AL-03; without a contract: read-only list + Cloud follow-up |

## Phases

### PR Split and Merge Order (AL-12)

Each row is one coherent PR with a line budget (excl. generated/lockfiles/formatting), dependency, per-PR acceptance, and rollback flag. Merge top-down; gated rows wait on the Phase 1 contract artifact.

| # | PR | Budget | Depends on | Per-PR acceptance | Rollback flag |
| --- | --- | --- | --- | --- | --- |
| P1 | Scroll follow + jump-to-latest (Phase 2.1) | 200–500 | Phase 1 measurement | Pinned follows mid-task; scrolled-up stays + affordance; reduced-motion instant | Revert follow-effect change; threshold untouched |
| P2 | Composer stabilization + legacy CSS verdict (Phase 2.2) | 200–400 | — | Shipped composer confirmed; stable states; dead CSS deleted or dated-deferred with owner | Revert style block only |
| P3 | Mascot gutter (Phase 2.3) | 100–300 | — | `home-smoke` geometry passes all states | Revert gutter CSS |
| P4 | Approvals conditional polling (Phase 1 verdict → build) | 200–500 | Phase 1 interval table | Interval table honored; background idle; missed-approval test passes | Two-line revert to prior intervals |
| P5 | Preview skeleton CSS state + size formatter + unsupported card (Phase 3a, contract-free) | 200–400 | — | Skeleton + correct sizes + explicit card; formatter unit tests | Revert component + helper |
| P6 | Markdown `BottomSheet` modal (Phase 3.3) | 200–500 | Phase 1 threshold | Focus trap/Escape/backdrop/return; threshold enforced; accent handoff | Revert modal PR |
| P7 | Routines manager — GATED (Phase 3.4) | 200–500 | Contract artifact | Mutations only with contract; else read-only + follow-up | Revert manager PR; chat untouched |
| P8 | File byte wiring — GATED (Phase 3b) | 200–500 | Locator outcome + artifact | Allowlist/sniff/max-bytes/sandbox enforced; no new dep | Revert wiring; 3a card remains |
| P9 | Reliability: echo guard + terminal copy/actions (Phase 4) | 200–500 | Root-cause comparison | Both echo tests; one copy + one action per terminal state | Remove guard; retry paths unchanged |
| P10 | Refresh anchor restore (Phase 2.4) | 200–400 | Settle signal | Test matrix passes (restore / nearest-loaded / fresh) | Single flag disables restore |

Dependencies/merge order: P1–P4 (scroll / composer / mascot / polling) → P5 (skeleton/size) → P6 (markdown) → P7–P8 (routines-gated, byte-gated) → P9–P10 (reliability, refresh). P2/P3 may land in either order; P7/P8 must not merge before the gate.

### Phase 1 — Investigations and verdicts

- Goal: remove the three unknowns before any UI is built: approvals polling design, file-preview location, markdown choice. Produce the blocking contract artifact that gates Phase 3 byte-wiring and manager mutations.
- Work items:
  1. Approvals polling verdict: measure current behavior (two `refetchInterval: 3_000` queries in `conversation-approvals.tsx:73-79,140-145` plus the 1s `now` timer at `:80-83` and the auto-open effect at `:86-90`). Decide conditional polling reusing the `apps/web/lib/allies/queries.ts:31-44` function-form `refetchInterval` pattern (no bespoke polling util) with `refetchIntervalInBackground: false`. Record this interval table in the implementation PR description:
     | Summaries query | `enabled` false → `enabled: false`, no poll | `enabled` true + tab hidden → no poll (`refetchIntervalInBackground: false`) | `enabled` true + visible + pending present (dialog closed or open) → poll (interval recorded in PR) | `enabled` true + visible + no pending, dialog closed → no poll |
     | Detail query | polls only while its dialog is open; closed → no poll |
     | `now` 1s tick | runs only while a `pending` / `decision_recorded` item with `expiresAt` / `acknowledgementDeadlineAt` is present; otherwise no timer |
     Preserve manual refetch ("Try again"), post-decision `summaries.refetch()`, and focus-return refetch. Remove the auto-open effect (or gate it behind explicit user action) and record the a11y rationale (focus theft / screen-reader surprise). Add a missed-approval regression case (pending arrives while idle → surfaces without background poll, e.g. via focus-return / manual refetch path).
  2. File-preview locator: search the staging build and the named file-sharing branches (`ft/cld-010-file-sharing` on Cloud, `ft/fnd-011` on Foundry) for the actual preview implementation; classify as (a) found and fixable on this base, (b) found only on another branch and needs a documented rebase/merge strategy with owner, or (c) missing so Phase 3a ships contract-free (skeleton CSS state + size formatter + unsupported card) and Phase 3b waits. Record which outcome occurred and the exact repository-relative paths found, or state "no chat preview code on this base" explicitly. Do not invent file paths. Also pin the Cloud OpenAPI file + version used and the regen step for `packages/cloud-client`.
  3. Markdown choice (locked): the single pattern is the `BottomSheet` modal with a Streamdown body (no separate metadata sidebar; metadata optional-only-if-model-has-it — never invent a filename). Reject inline full rendering for long docs (pushes chat, harder focus management). Permit inline Streamdown to remain for short assistant messages. Define the long-doc threshold (exact char/line cutoff recorded in the verdict; implementation PR enforces it) for modal vs inline. Single dialog primitive (`BottomSheet` modal) provides focus trap, Escape, backdrop close, focus return, and the body `--active-chat-accent` handoff. Record the decision and the rejected alternative with reasons.
  4. Routine contract discovery + contract artifact: confirm whether any stable Cloud routine / schedule / cron endpoint exists in the pinned OpenAPI or staging; emit the blocking artifact — exact repository-relative source paths, OpenAPI pin + version, and representative request/response JSON for every routine and file-preview binding. If none, define the minimal read-only manager over what chat already knows (props-only extensions, no new store, no speculative client) plus an explicit Cloud follow-up with owner and revisit date.
- Impacted files/systems: `apps/web/app/home/conversation-approvals.tsx`; `apps/web/lib/allies/queries.ts:31-44` (pattern to reuse); `packages/cloud-client/src/mappers/approvals.ts`, `packages/cloud-client/src/client.ts` (read-only); generated OpenAPI; staging / file-sharing branches (read-only inspection); Mobbin notes in episode state.
- Exit criteria: three written verdicts (polling interval table + auto-open decision + missed-approval path, preview locator outcome with paths or explicit "missing" + OpenAPI pin, markdown lock + long-doc threshold with rationale) plus the routines/file contract artifact (or explicit read-only fallback + follow-up); no UI changes in this phase except measurement tests. Phase 3b and routines mutations must not start without the artifact.

### Phase 2 — Chat scroll, composer, mascot, refresh

- Goal: make the thread physically trustworthy: it follows live work, the composer stays stable, the mascot never covers text, refresh resumes position.
- Work items:
  1. Autoscroll during long tasks (bug 1): first run a measurement step to find which signal stalls (timelineSignature deltas vs scroll-effect firing vs `scrollTo` execution) on a seeded long task; record the stalling signal in the PR. Then reconcile `followLatestRef` vs scrolled-away into one owning flag (no parallel scroll system), keep the 96px near-bottom threshold in `home-workspace.tsx:2195-2198` and `conversation-frame.tsx:93-101`; ensure `timelineSignature` in `home-workspace.tsx:1213-1224` advances on streaming / activity deltas (turn `assistantText.length`, pending activity text length) so the `useEffect` at `:2045-2054` fires mid-task, not only on message commit; use `requestAnimationFrame` `scrollTo`, `behavior: "smooth"` only when not `prefers-reduced-motion` (reduced-motion gate: instant scroll); never steal scroll after the user scrolled up — show a "jump to latest" button (accessible name, `aria-live="polite"` announcement of new activity, focus stays put until activated). Cover with Vitest cases (extend `home-workspace.test.tsx` style) that append activity text and assert follow, plus a scrolled-up case that asserts no jump and that the affordance appears. No `setTimeout`-duration assertions.
  2. Composer top padding (bug 6): confirm which composer ships (`ConversationComposer` in `conversation-frame-primitives.tsx:378-523` + `conversation-frame.module.css:961-1031`). Stabilize the shipped composer: keep pill `min-height: 48px`, `padding: 6px 6px 6px 12px`, textarea `padding: 7px 0`, `align-self` behavior, and the `data-expanded` radius switch (`100px` to `18px`) so typing across the 48-char / newline / 83px-cap thresholds does not add top offset; verify the `useLayoutEffect` height reset (`height: auto` then capped `scrollHeight`) does not fight flex alignment. If legacy `home.module.css:1198-1355` is confirmed dead, delete it in the same PR; if ownership is unclear, record a dated defer with owner instead of leaving silent dead CSS. Drop brittle metric snapshots — assert stable padding/alignment states and no top-gap regression via `conversation-composer.test.tsx` + `home-smoke`, not pixel-metric snapshots.
  3. Mascot + text overlap (bug 8): fix `ConversationPresence` (`conversation-presence.tsx`) + `conversation-frame.module.css:374-460`. Reserve the 36px thread gutter in `.framePresenceRow` / `.framePresenceActivity` so the absolutely positioned `.framePresenceActor` cannot underlap text; keep the existing offscreen-hide logic but ensure text reflows rather than slides under; gate the 520ms placement animation behind `prefers-reduced-motion`. Assert no overlap in `home-smoke` geometry checks.
  4. Refresh position (bug 13): define the settle signal (conversation query settled + canvas laid out after `timelineSignature` settle) before reading the anchor. Persist a per-conversation namespaced `sessionStorage` anchor `{ messageId, offsetPx, updatedAt }` + TTL (exact key and TTL in the implementation PR) on scroll (debounced) and on settle; on mount, after settle, restore to the anchor when history is complete, else restore to nearest loaded message and offer "Earlier messages" without forcing bottom. Default (no anchor or stale TTL) keeps current follow-latest behavior. Privacy: never persist content or credentials (AL-09). Test matrix: reload-restore, older-page-available (nearest-loaded fallback), fresh conversation (follow latest). Single-flag rollback: disable anchor restore, keep follow-latest.
- Impacted files/systems: `apps/web/app/home/home-workspace.tsx`, `apps/web/app/home/conversation-frame.tsx`, `apps/web/app/home/conversation-frame-primitives.tsx`, `apps/web/app/home/conversation-frame.module.css`, `apps/web/app/home/conversation-presence.tsx`, `apps/web/app/home/conversation-frame-model.ts` (if a view field is needed).
- Exit criteria: stalling signal identified and recorded; threaded follow works mid-task and respects scrolled-up with the specified affordance; composer confirmed with dead CSS deleted or dated-deferred; presence geometry overlap assertion passes; refresh restores anchor per the test matrix; reduced-motion paths verified.

### Phase 3 — Previews, markdown, routines manager

- Goal: ship the visible content surfaces on top of Phase 1 verdicts. Phase 3b byte wiring and routines mutations are gated on the Phase 1 contract artifact; Phase 3a is contract-free.
- Work items:
  1. (3a — contract-free) Skeleton + size formatter + unsupported card (bugs 2/4 baseline): skeleton is a CSS state on the preview card (fixed-height row, no named component) with `role="status"` + `aria-busy`, shimmer disabled under `prefers-reduced-motion`, shown from intent until resolve or error with no layout shift. Single pure size formatter (1024-based `B`/`KB`/`MB`, `Intl.NumberFormat`, 0-byte and singular handling; keep this helper — SIM-004). Explicit unsupported card for `pdf`/`docx`/unknown: icon + name + correct size + download/open, never a blank or broken frame. Unit tests colocated for the formatter (bytes, KiB boundary, MB rounding, previously wrong vector).
  2. (3b — gated byte wiring) `pdf` / `docx` / common types (bug 3): implement only the MIME set Phase 1 confirms (at minimum images already handled, plus `pdf`, `docx`, and the agreed common set). AL-02/AL-07 boundary: allowlist enforced on sniffed content type (not extension alone), max-bytes bound, executables blocked, sandbox/CSP for embedded bytes. Images render native; `pdf`/`docx`/unknown render the explicit unsupported card from 3a (no new doc-renderer dependency — no pdf.js/mammoth per SIM-003). Revoke object URLs on unmount; never log signed URLs (AL-09). Errors offer retry.
  3. Markdown preview (bug 5, locked): build the `BottomSheet` modal with Streamdown body only (no metadata sidebar; metadata optional-only-if-model-has-it). Enforce the Phase 1 long-doc threshold (modal for long docs, inline Streamdown stays for short messages). Single dialog primitive: focus trap, Escape, backdrop close, focus return, labelled heading, `role="dialog"` + `aria-modal`; preserve the body `--active-chat-accent` handoff; long content scrolls inside the dialog, never the thread. Keyboard and screen-reader coverage in `home-smoke` + colocated tests.
  4. Routines manager (bug 9, minimal, conditional): enable the existing disabled "Routines" entry (`home-workspace.tsx:534` area) as a list surface backed by TanStack Query on the confirmed contract. Props-only extensions to existing `RoutineCard` / `RoutineDetail` / `DeleteRoutineSheet` (real `name` / `Starts` / `Repeats` / `Tool` props replacing hardcoded copy; no new Zustand store; no speculative client per AL-08). Pause / resume are explicit buttons with optimistic-disabled states; delete goes through `DeleteRoutineSheet` confirm with the real name (AL-03); list handles loading, empty, error-retry, and permission-denied. If Phase 1 finds no stable contract: ship read-only list over chat-known routines only, plus a Cloud follow-up with owner and revisit date; pause/resume/delete stay out until the contract artifact exists.
- Impacted files/systems: new preview / markdown / routines components under `apps/web/app/home/` plus `conversation-frame.module.css`; `conversation-frame-primitives.tsx` (extend `RoutineCard` / `RoutineDetail` / `DeleteRoutineSheet` props only); `apps/web/lib/allies/` query keys (additive only); `chat-frame` fixtures and debug preview for visual baselines (fixture updates need signoff — see Test Plan).
- Exit criteria: 3a skeleton-to-card flow with correct sizes and no contract needed; 3b byte wiring only after locator outcome with trust bounds enforced; markdown modal meets a11y criteria on the single primitive; routines list with working pause / resume / delete on the confirmed contract (or documented read-only fallback + follow-up); each surface split into 200–500-line PRs per the split table.

### Phase 4 — Reliability: echo, latency, failures

- Goal: explain and harden the send-to-reply path without touching Cloud behavior. Copy honesty only; reuse existing transport and recovery.
- Work items:
  1. Echo root cause (bug 10): first run the root-cause comparison — last user content against incoming `assistantText` / `pendingAssistantText` paths (`conversation-frame.tsx:290-299`, `TurnMessage`, projection in `home-workspace.tsx`), including retry / `immediateMessageIds` / `mergeMessages` duplication and the Streamdown `static` vs `streaming` reveal handoff (`conversation-frame.tsx:254,394-401`). Fix the identified duplication with a narrow equality guard plus floor (guards only the proven identical-echo path; legitimate quotes and near-matches still render). No terminal state machine, no broad similarity filter. Two regression tests: (a) suppress-bug-echo (identical prompt not rendered as the ally's answer), (b) preserve-legitimate-quote (an assistant reply that legitimately quotes user text still renders). Sanitized evidence only in PR/issues (message ids, lengths, match boolean — never full content); forbid full-content logging (AL-09). If evidence points server-side, stop and file a Cloud issue with the sanitized comparison instead of masking it client-side (escalation path).
  2. Slow responses (bug 11): keep the existing poll + SSE design (`shouldPoll`, `activityPollInterval`, `checkActivity` with visibility and poll-budget guards); reuse SSE / visibility / `AbortController` / idempotency keys / cursors — no new latency fetch layer (SIM-011). Ensure thinking / waking states (`showThinkingState`, `gettingReady`, `runtimeIntentStatus`) render on send; surface time-to-first-activity honestly ("Thinking…", activity disclosure, "Waking up") rather than adding speculative fetching. Verify timeout, cancellation, idempotency, and cursor recovery still hold per AL-05 / AL-06. Assert honest waiting states without flaky duration thresholds (no `ms` timing assertions — assert state presence/transition, not elapsed time).
  3. Failures (bug 12): unify terminal handling (`failed` / `stopped` / `reconciliation_needed`, `activityError`, `retryError`, `sendError`) so every terminal turn offers exactly one honest copy line plus one safe recovery (`Retry` / `Try again` / `Check again`) wired to the existing `retry` / `refetch` / `onCheckAgain` paths; keep `MESSAGE_ACCEPTANCE_UNKNOWN_ERROR` distinct from definitive rejections; preserve tombstone and queue-lock behavior for queued sends. Test each terminal state renders copy + one action and that retry reuses the correct idempotency key.
- Impacted files/systems: `apps/web/app/home/home-workspace.tsx` (send / poll / retry paths), `apps/web/app/home/conversation-frame.tsx` (turn and pending-text rendering), `apps/web/app/home/conversation-frame-model.ts`, `apps/web/lib/allies/activity-stream.ts` and projection helpers (read and adjust only with evidence).
- Exit criteria: root-cause comparison recorded; narrow guard justified with both regression tests passing; slow-turn states honest and bounded with existing mechanisms intact; every terminal failure has one copy line + one safe retry; no Cloud contract change and no new polling introduced.

## Acceptance Criteria

1. Long task follow: while activity entries stream, a user pinned to bottom stays pinned without manual scrolling; a user scrolled up stays put and is offered the "jump to latest" button (accessible name + `aria-live="polite"` announcement); reduced-motion users get instant follow; stalling signal recorded.
2. Skeleton: every file preview shows a sized CSS-state skeleton with `aria-busy` until ready or error; no layout shift when bytes resolve; shimmer off under reduced motion. No contract needed for this slice.
3. Type previews: images render native; `pdf`, `docx`, and the Phase 1 agreed common set render a usable preview or the explicit unsupported card (icon + name + correct size + download/open); no blank or broken card; no new doc-renderer dependency. Byte wiring gated on the contract artifact; trust bounds (allowlist, sniffed MIME, max bytes, blocked executables, sandbox/CSP, revoked object URLs, no signed-URL logging) enforced.
4. Sizes: displayed sizes match the single pure 1024-based formatter (`Intl.NumberFormat`) across unit-test vectors including 0 B, sub-KB, KiB boundary, and MB rounding.
5. Markdown: the single locked pattern (`BottomSheet` modal + Streamdown body, threshold-gated) opens from chat, traps and returns focus, scrolls internally, preserves accent theming via the body handoff, and exposes metadata only if the model has it (no invented filename). Long-doc threshold enforced.
6. Composer: shipped composer confirmed; typing from empty through wrap, newline, and the 83px cap keeps pill padding and alignment stable; confirmed-dead legacy CSS deleted in-PR or dated-deferred with owner; no brittle metric snapshots.
7. Approvals polling: no unconditional 3s polling; interval table honored (summaries conditional on `enabled` + tab-visible + pending/dialog, detail only while dialog open, 1s `now` tick only with deadline-bearing items); `refetchIntervalInBackground: false`; function-form `refetchInterval` reusing the `queries.ts:31-44` pattern; manual, post-decision, and focus-return refetch work; background tabs do not poll; auto-open removed or explicitly gated with a11y rationale; missed-approval case covered.
8. Mascot: presence avatar never overlaps message or activity text in idle, thinking, waking, or docked states across desktop and mobile widths.
9. Routines: an ally's routines list loads with loading / empty / error states via props-only extensions to existing cards/sheets; pause / resume / delete work only against the confirmed contract (gated); otherwise read-only + Cloud follow-up with owner/date; delete requires explicit confirm; no stub copy on shipped paths; no new store.
10. Echo: narrow guard on the proven identical-echo path only; both regression tests pass (suppress bug echo, preserve legitimate quote); sanitized evidence only; server-side echo escalated rather than hidden; no full-content logging.
11. Latency: sends render an honest waiting state; first activity or reply timing is honest; no hung spinner; cancellation and poll budget still bound work; existing SSE/visibility/Abort/idempotency/cursors reused; no `ms` threshold assertions.
12. Failures: every terminal state shows one honest copy line plus exactly one safe recovery action reusing the correct idempotency path (`retry` / `refetch` / `onCheckAgain`); queue and cursor recovery still hold.
13. Refresh: reload restores the namespaced `{ messageId, offsetPx, updatedAt }` + TTL anchor after the settle signal when history is loaded, or the nearest loaded message with a clear path to older content; fresh or stale-anchor conversations start following latest; no content/credentials persisted; single-flag rollback available.
14. Policy: PRs follow the split table below (200–500 lines target; merge order honored; gated PRs blocked until the contract artifact); TanStack Query owns server state; cursors remain the recovery boundary; no credentials in state or logs; a11y + reduced-motion verified; `lint`, `typecheck`, unit, and smoke checks pass per Test Plan.

## Backend Considerations (if applicable)

Not applicable — no backend changes are planned. Web works read-only against the existing Cloud contract via `packages/cloud-client`. If Phase 1 or Phase 4 proves a Cloud change is required (routines, file bytes, or echo origin), the outcome is a filed Cloud follow-up with sanitized evidence, not a change in this episode.

### Query Optimization Plan

- Not applicable as a backend change. Web-side bound: approvals move from unconditional 3s polling to conditional polling; activity polling keeps its existing budget (`ACTIVITY_POLL_LIMIT`, `pollBudgetReached`) and visibility gating. No new per-item network calls; routine and file bindings reuse list-level queries.

### N+1 Prevention

- Not applicable as a backend change. Web guardrail: one summary query per conversation, one detail query per open dialog, one list query per routines view; no fan-out per message or per routine row.

### Detailed Unit Test Cases

- Not applicable as backend tests. Frontend unit and integration cases are listed under Test Plan.

## Frontend Considerations (if applicable)

### Data Path

- User sends or activity streams → `home-workspace.tsx` (`submit` → `sendMessageContent` → `checkActivity` / SSE → `projectConversationActivity`) → `buildProductionConversationFrameModel` → `ConversationFrame` → `ConversationCanvas` / `TurnMessage` / `ActivityGroup` / `ConversationApprovalSlot` / `ConversationPresence` / `ConversationComposer`. Errors map to `sendError` / `activityError` / `retryError` / `FrameError` with single recovery actions.
- Approvals read path: `useQuery(["workspaces", workspaceId, "approvals", conversationId])` → `toApprovalSummary` → `approvalStatusAt(now)` → slots and dialog; detail query `["workspaces", workspaceId, "approval", conversationId, approvalId]` only while open; `decideApproval` posts with `Idempotency-Key` and triggers `summaries.refetch()`.
- File preview path (after Phase 1 locator): intent → skeleton → resolve metadata + bytes (signed URL or object URL per confirmed source) → `FilePreview` ready / unsupported / error; size via shared formatter.
- Markdown path: existing message content → `BottomSheet` modal dialog with Streamdown body (metadata only if the model has it; threshold-gated); body accent via `document.body --active-chat-accent` set in `conversation-frame.tsx:45-53`.
- Routines path (after Phase 1 contract confirmation; mutations gated on the artifact): list query → `RoutineCard` rows → `RoutineDetail` → pause / resume / delete mutations → list invalidation; delete confirmed via `DeleteRoutineSheet`. Without a contract: read-only props-only list + Cloud follow-up.
- Scroll path: measurement → reconciled follow flag → `timelineSignature` → `scrollTo`; user `onScroll` flips follow and shows the jump-to-latest button; refresh path adds namespaced `sessionStorage` anchor read after the settle signal.

### State Management Considerations

- State ownership: TanStack Query owns approvals, conversation, messages, replies, activities, and (once confirmed) routines and file metadata. Local `useState` / `useRef` own draft, dialog open state, decision intents, scroll-follow flags, and composer height. No new Zustand store; never store credentials in any store.
- Source of truth vs derived: Cloud is truth for messages, turns, approvals, and cursors. `approvalStatusAt` derivations, `followLatestRef`, presence placement, and composer height are derived and recomputed, never persisted except the scroll anchor.
- Caching/invalidation: reuse existing `conversationQueryKey(workspaceId, allyId)` invalidation after terminal activity and sends; approvals refetch on record; routines mutations invalidate the routines list key only. No cross-key manual cache writes.
- Concurrency and dedupe: keep `AbortController` cancellation, `pollingRef` guards, idempotency keys for send / retry / approval decisions, queue locks and tombstones for queued messages, and `resumeCursor` / `nextCursor` recovery. New mutations (routines pause / resume / delete) must use the same idempotency and disabled-while-inflight discipline.

## Test Plan

- Unit tests (Vitest, colocated — reuse existing harnesses, no new harness; no `ms` duration thresholds — assert states/transitions, not elapsed time):
  - Scroll follow in `apps/web/app/home/home-workspace.test.tsx` style: activity-text append while pinned follows; scrolled-up append does not jump and shows the jump-to-latest affordance.
  - Composer in `apps/web/app/home/conversation-composer.test.tsx`: stable padding/alignment across single-line / wrapped / capped states (no brittle pixel-metric snapshots of dead CSS).
  - Size formatter (colocated with the helper): 0 B, 512 B, 1023 B, 1024 B, 1536 B, 1 MiB rounding, plus the previously misreported vector.
  - Approvals in `apps/web/app/home/conversation-approvals.test.tsx`: `approvalStatusAt` + `pruneDecisionIntents` (existing) plus conditional-polling option selectors (function-form interval, background false), `now`-tick gating, and the missed-approval case.
  - Echo guard (colocated with the guard): (a) identical prompt not rendered as assistant text; (b) legitimate quote still renders. Sanitized fixtures only.
  - Terminal states (colocated / `home-workspace.test.tsx` style): `failed` / `stopped` / `reconciliation_needed` each render one copy line + one recovery with the correct idempotency key.
  - Refresh anchor (colocated / `home-workspace.test.tsx` style): restore / nearest-loaded fallback / fresh-default matrix; stale-TTL ignored.
- Integration/API tests (mocked clients, existing patterns):
  - Approvals flow with mocked `ApprovalClient`: pending → dialog → approve → `decision_recorded` → refetch; error → "Try again"; permission-denied copy.
  - Routines flow (only after contract artifact; otherwise read-only states): list → pause → resume → delete-confirm with mocked client; error-retry and empty states.
  - Conversation flows in `home-workspace.test.tsx` style: send → activity → terminal → invalidation; load-older preserves window.
- Regression checks:
  - `bun run verify:chat-frames` and `chat-frame` manifest prebaseline/signoff for routine and composer fixtures; fixture update policy: `bun run --cwd apps/web test:chat-frames:update` only for intentional visual changes, followed by signoff verification before merge.
  - Playwright `home-smoke` for thread geometry (mascot non-overlap), composer stability, approvals dialog focus restore + keyboard path, markdown dialog keyboard path, refresh scroll restore, reduced-motion paths.
- Manual verification checklist:
  - Long task while pinned and while scrolled up (affordance role/live-region/focus); composer typing to cap; approvals with and without pending items, background tab idle; file types in allowlist + one unsupported + one oversize/blocked; markdown modal keyboard-only incl. Escape/backdrop/return; routines pause / resume / delete including confirm cancel (or read-only fallback); airplane / offline send then retry; refresh mid-thread, refresh with older history available, fresh conversation. Verify `prefers-reduced-motion` throughout. Scan for local paths, private URLs, identifiers, credentials before signoff.
- Commands (run from the repository root unless noted; prefer the locked `bun` toolchain):
  - `bun run lint`
  - `bun run lint:web`
  - `bun run typecheck`
  - `bun run test:run`
  - `bun run build:web`
  - `bun run cloud:check`
  - `bun run --cwd apps/web test:home-smoke` (Playwright `playwright.home-smoke.config.ts`)
  - `bun run --cwd apps/web verify:chat-frames` and, when fixtures change intentionally, `bun run --cwd apps/web test:chat-frames:update` followed by signoff verification

## Risks and Mitigations

- Risk: File-preview and routine contracts do not exist on this base, stalling Phase 3.
  - Mitigation: Phase 1 locator and contract discovery come first with explicit "missing" outcomes allowed; Phase 3a (skeleton CSS state + size formatter + unsupported card) ships contract-free; Phase 3b byte wiring and routines mutations wait on the contract artifact (exact paths + request/response JSON, OpenAPI pin + regen).
  - Rollback/fallback: land scroll / composer / mascot / polling fixes independently per the split table; keep gated PRs (P7/P8) unmerged until contracts confirm; read-only routines + Cloud follow-up with owner/date as fallback.
- Risk: Cross-branch file-sharing work merges in the wrong order or against an unpinned contract.
  - Mitigation: sequencing section pins source branches (`ft/cld-010-file-sharing`, `ft/fnd-011`), owner, rebase/merge strategy, and OpenAPI pin + regen; merge-block conditions enforced before P7/P8.
  - Rollback/fallback: revert to `dev`-pinned client regen; gated PRs stay unmerged.
- Risk: Conditional polling misses an approval or delays it visibly.
  - Mitigation: poll whenever a pending item exists or a dialog is open; keep immediate refetch on record, on focus return, and on manual retry; record the interval table in the PR.
  - Rollback/fallback: revert the polling options change alone; the unconditional intervals are a two-line revert.
- Risk: Scroll-restore fights pagination and lands on the wrong message.
  - Mitigation: restore only after query settle and layout; anchor to message id with offset, not absolute pixels; when older history is unloaded, land on nearest loaded message and preserve the "Earlier messages" path.
  - Rollback/fallback: disable anchor restore and keep follow-latest; one-flag revert.
- Risk: Echo guard masks a real server echo instead of fixing it.
  - Mitigation: require the root-cause comparison in the PR; if server origin is indicated, file the Cloud issue and keep the client guard narrow or behind the confirmed condition.
  - Rollback/fallback: remove the guard; terminal and retry behavior is unchanged.
- Risk: Markdown modal or routines manager grows past reviewable size.
  - Mitigation: split per surface and per state (list, then item actions; modal shell, then metadata); keep 200–500-line PRs with tests colocated.
  - Rollback/fallback: revert per-PR; each PR must remain coherent and testable on its own.
- Risk: Visual fixes regress reduced-motion or keyboard users.
  - Mitigation: gate smooth scroll, shimmer, and presence animation behind `prefers-reduced-motion`; preserve focus restore, dialog labelling, and `aria-live` semantics; cover with keyboard and motion-preference checks.
  - Rollback/fallback: revert the offending style or animation block without touching data paths.
