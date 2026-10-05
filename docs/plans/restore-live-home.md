# Restore live Home

## Outcome and scope

Restore the authenticated Home experience on top of PR22 head `9428a6f`: `/home`, `/home/[allyId]`, and `/home/new` use the existing `HomeWorkspace` for real account, Ally, onboarding, conversation, and Cloud state at narrow and desktop widths. Preserve the current Magic Design/Exact geometry and authored onboarding. Incorporate the reviewed PR24 recovery series ending at `8f67c90` without changing either source branch.

Keep backend changes, Events, Routines, search, rich actions, and visual redesign out of scope. Add no dependency, transport, controller, or API. Cloud remains the durable source of truth; the Interface keeps presentation, local interaction state, and the existing bounded replay/send adapter.

## Simplest viable approach

1. **Merge the reviewed recovery branch into the fixed Exact head.** Run `git merge --no-commit origin/web/fix/audit-conversation-recovery` so the final integration commit retains PR24's reviewed ancestry. Resolve the single merge-tree overlap by keeping PR22's imported `useIsMobileHome` helper and PR24's message-acceptance constants, then retain PR22's Exact slots/current onboarding alongside PR24's assistant-reply mapping, bounded durable-history recovery, companion polling, account-scoped pending-send identity, definitive-rejection handling, SSE-default-off contract, pinned Cloud client/OpenAPI, and CI fixture updates. Do not replace the working tree with the older PR24 snapshot.

2. **Put every public Home route on the existing live workspace and keep transient states truthful.** Have `apps/web/app/home/page.tsx` render `HomeWorkspace` with no selection and `apps/web/app/home/[allyId]/page.tsx` pass the decoded route ID directly to it; keep `apps/web/app/home/new/page.tsx` on the same component with the `"new"` sentinel. Delete the `HomeDashboard`, `HomeRoute`, `HomeMobilePreview`, mock-data module, and their mock-only test once callers are gone. Remove `ConversationFrame`'s `ALLY_CHAT_SLEEP_DEMO_MS` timer/state so its header uses only the existing live `sleeping` prop. During mobile workspace/auth loading, pass empty action and create-control slots alongside the empty Ally slot so generated SD/create defaults cannot appear. Keep real roster links, account profile, Exact shells, creation overlay/drawer, created-Ally navigation, inactivity-driven sleep/wake artwork, and truthful loading, empty, error, and unknown-ID states.

3. **Remove only the production mock route path.** Delete the named mock wrappers/modules after the public routes stop importing them, and extend the route import-graph boundary to reject `home-dashboard`, `home-route`, `home-mobile-preview`, and `home-mobile-mock` from public Home. Leave the generated desktop/mobile Exact shell code, geometry, and reference defaults intact for the existing debug surface; `HomeWorkspace` already supplies every live slot, so public routes must render fetched content without exposing those defaults.

4. **Lock the route and recovery contracts with focused tests.** Reuse the account, Ally, conversation, and responsive fixtures in `home-workspace.test.tsx` to render the actual `/home`, `/home/[allyId]`, and `/home/new` page elements and assert fetched roster/profile/conversation/creation behavior with no mock output; this must fail if a public page returns to a preview component. Cover an arbitrary ID, both responsive layouts, created-ID navigation, and loading without generated SD/create controls. Replace the demo-timer assertion in `conversation-frame.test.tsx` with regressions proving the sleeping header follows the explicit prop and does not change merely because time elapses. Preserve PR24's durable-reply, replay-bound, unknown-send, rejected-queue, companion-polling, and SSE tests. Add no parallel fixture harness.

5. **Make the stacked PR testable, then validate from contracts through live behavior.** Retain PR24's `web/feat/chat-frames` pull-request triggers in CI and secret scan, and add the same exact base branch to `.github/workflows/railway-pr-environment.yml` so the existing isolated per-PR web preview is created and cleaned up without credential or deployment redesign. Run focused Home/Cloud-client tests first, then `bun run cloud:check`, `bun run test:run`, `bun run typecheck`, `bun run lint`, `bun run build:web`, and `bun run test:chat-frames` without updating baselines. On the Railway preview, verify signed-out redirect and authenticated desktop/narrow flows for real roster/profile, valid and invalid IDs, Ally creation and post-create navigation, persisted history, send, live reply, refresh/reconnect, and truthful failure states. Record mocked-contract results separately from preview/backend proof.

## Affected surfaces

- Home route entry files and the obsolete mock wrappers under `apps/web/app/home/`.
- `HomeWorkspace`, `ConversationFrame`, their model, styles only where required to merge PR24, and focused tests.
- Existing desktop/mobile Exact shells remain unchanged and continue receiving live slots from `HomeWorkspace`.
- `packages/cloud-client` pinned schema, mappers, transport/client exports, and tests carried by PR24.
- Web environment defaults/tests and the CI, secret-scan, production-bundle, and Railway PR-preview workflows.

## Acceptance criteria

- Signed-out visitors to every Home entry reach sign-in; signed-in requests query the current account/workspace and never substitute a mock roster, profile, conversation, or reply.
- `/home` shows the real roster on mobile and the real two-pane dashboard on desktop. `/home/<owned-id>` opens that Ally on both layouts; missing or unowned IDs show a truthful state and do not fabricate an Ally. `/home/new` opens the existing authenticated creation flow, and its returned ID becomes the selected live conversation.
- Mobile loading shows the preserved Exact shell without generated account/create defaults. Conversation sleeping visuals respond only to the existing live inactivity state and do not activate on a periodic demo timer.
- Persisted messages and durable assistant replies survive paging, refresh, reconnect, and bounded activity recovery. Unknown send outcomes retain their account-scoped idempotency identity; definitive rejection releases the queue safely and restores unsent text; existing queue, cancellation, dedupe, and SSE/poll safeguards remain covered.
- PR22's Exact shells, generated reference defaults, and onboarding remain intact; production Home imports none of the named mock route modules and renders no mock output. No dependency, duplicate controller, generated-shell fixture, or screenshot-baseline update is introduced.
- The stacked PR runs CI, secret scan, and an isolated Railway preview. Local mocked tests prove deterministic client contracts; authenticated preview evidence proves compatibility with the configured Cloud/auth environment or explicitly records the external gate that prevented it.

## Risks, mitigations, and open evidence

- **Recovery/Exact overlap:** PR24 branched before the latest mobile Exact work. Preserve both parents through the merge commit, resolve only the known helper/constants overlap, and inspect the final diff against `9428a6f` and `8f67c90` so neither recovery guarantees nor Exact slots disappear.
- **Pinned Cloud compatibility:** the local Cloud URL has no listener, and generated client changes depend on the deployed additive assistant-reply contract. `cloud:check` proves schema parity; only the remote preview can prove the configured backend and authentication combination.
- **Preview authentication:** OAuth redirect allowlists, cookies, CORS, repository secrets, or the preview deployment may block real sign-in. Treat that as a release/test gate with captured workflow or browser evidence, not as a reason to add an auth bypass or claim live acceptance.
- **Generated Exact defaults:** they remain available to the debug surface but must never render on public Home. Actual-page tests with fetched fixtures plus the import-graph boundary catch a route bypass without duplicating the generated shell.

Rollback is a single revert of this stacked PR; the existing preview workflow cleans up its environment on PR close. Do not merge either source PR as part of rollback or delivery.

## Provisional chat baseline approval

On 2026-09-05 the user explicitly approved the concrete 22-image provisional regression update for PR26 and PR27: “Yeah go ahead. We would do a one by one review after you are done.” This supersedes this plan's earlier no-baseline-update constraint for these exact captures only.

The comparison contained all 25 old/candidate pairs and their SHA-256 hashes, independently verified before approval. Captures use source commit `10afda963b7ca81e0f875ed6c224ed60cca0cbfd`, Ubuntu 24.04, Bun 1.2.20, Playwright 1.62.1 and Chromium 151.0.7922.34/revision 1234. Twenty-two images change; three remain byte-identical. The sign-off JSON records the exact resulting hashes.

This narrow maintainer exception accepts regression references, not pixel-perfect Figma or final product/design sign-off. Keep the manifest provisional and preserve unresolved asset evidence and the design-approver sentinel. Known vertical-spacing differences, the debug greeting's missing paragraph break, and full per-frame/Safari provenance remain for the deferred review. Complete provenance before the first production release or next intentional baseline update, whichever comes first. Test thresholds, inventory, production boundary, and review checks remain unchanged.

Source repair restores 44px hit targets around unchanged 40px visible circles and places the catalog's top date outside the scroll rail, matching the production component contract. All 15 geometry/interaction checks passed across Chromium, WebKit and Firefox; 17 focused component/boundary tests passed. The isolated Linux candidates passed all 30 Chromium checks on a clean no-update rerun. Final GitHub CI on the committed references remains the delivery gate.

## Optional SSE companion snapshot limit

Accepted P2 disposition for this restoration (AL-05, AL-07, INT-02): retain the existing 240-read budget for durable companion snapshots while optional SSE is healthy. The Interface conversation maintainer owns this exception. A turn exceeding roughly 12 minutes can pause automatic durable reply refresh until manual recovery or a terminal refresh; this is a known limitation, not continuous snapshot delivery.

Mitigations are the visible “Status checking is paused.” state, explicit “Check again” recovery, terminal refetch, and SSE disabled by default. Stream loss after companion exhaustion receives one fresh bounded fallback allowance, covered by the error/mismatch regression in home-workspace.test.tsx. Removing companion reads from the budget would introduce unbounded snapshot traffic and is outside this restoration's accepted recovery model.

Revisit before enabling SSE by default or claiming continuous durable reply refresh for long-running turns. That follow-up must define and test a bounded backoff/renewal policy. This disposition was recorded in the restoration episode and Nabu before the final baseline update; this tracked section makes it visible to PR reviewers. It does not waive access failures, durable-state truthfulness, or the stream-loss recovery fix.

## Browser storage unavailable

P2 disposition for this restoration: preserve the A09 requirement to persist the account-scoped retry identity before any send request, including an idle conversation. Browsers or webviews that deny storage writes, or exhaust their quota, cannot send until storage is available. The Interface conversation maintainer owns this limitation; it is not a claim of support for storage-disabled chat.

The composer retains the unsent draft and now explains that the message was not sent, asks the user to keep the page open, and suggests allowing site storage or freeing space before retrying. Direct idle-send regressions cover SecurityError and QuotaExceededError: no request before successful persistence, retained text, then one request with the persisted identity after recovery. The active-turn queue failure regression remains covered.

An in-memory fallback would lose the retry identity on reload and could duplicate a send whose response was lost. Revisit before claiming support for storage-restricted browsers or embedded webviews; such support needs a durable alternative with response-loss and reload tests. This disposition preserves the existing safety contract rather than relaxing duplicate-send protection to satisfy CI.
