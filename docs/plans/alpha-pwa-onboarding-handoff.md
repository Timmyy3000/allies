# Alpha PWA and onboarding handoff

Route: fast. HTML required: no. Base: `origin/dev`; branch: `web/fix/pwa-onboarding-handoff`. Implementation and acceptance remain tracked in `alpha-pwa-onboarding-handoff-todos.md`.

## Scope and evidence

Deliver AT-032, AT-033, and AT-039. AT-031 needs live mobile evidence; conversation styling, approval/backend work, and inline file preview remain outside this PR.

`app/app/page.tsx` and `app-page-client.tsx` implement `/app`; `manifest.ts` already specifies `start_url: /app`, `scope: /`, and standalone display. `next.config.ts` has no base path or route rewrite. Under DEC-005, this repository contract plus production build/smoke is the implementation gate. The orchestrator's 2026-09-08 probes of `https://yourallies.io/app` and `/manifest.webmanifest` returned 404; carry this as a delivery caveat, not a route change or implementation blocker. Do not invent another route or change the manifest scope.

Account logout currently replaces the URL with `/` or `/?signout=unconfirmed`. Its session-state guard already suppresses account content after sign-out. The handoff error screen has another logout caller. `/app` handles restoration and onboarding resume but does not present the unconfirmed-logout warning. PWA detection already exists in `lib/pwa/pwa-install.tsx`, including display-mode and iOS standalone signals.

`globals.css` owns light/dark tokens through `prefers-color-scheme`; `/app` welcome CSS overrides them with white, black, and `color-scheme: light`. No separate persisted theme selector was established by inspection. Use the existing token contract rather than adding a preference system.

In `home-workspace.tsx`, `handleCreated` seeds the roster cache, records the created ID, navigates, and immediately closes the drawer. Route selection and conversation loading settle separately. `AuthenticatedAllyFlowProvider.recordReply` creates the Ally with the first reply and a stable retry key; the normal conversation send path must not resend that first reply. `OnboardingHandoffScreen` is the adjacent resume path and must retain its account binding and saved-input recovery.

Nabu index, alpha tracker, first product requirements, conversation specification, and decision log were read through MCP. They require continuous greeting/reply history, Cloud-owned identities, same-key reconciliation of uncertain acceptance, and FIFO/head-correlated queue presentation. AT-039 is authorized by the brief; the inspected tracker lists AT-032/033 but does not yet include AT-039. No Nabu mutation is needed for this presentation fix.

## Implementation sequence

1. Use the verified repository route/manifest/config contract and require production `/app` and manifest smoke assertions under DEC-005. Read the installed Next 16.2.12 routing/navigation guide before editing routing behavior. Trace all logout callers and reuse the existing standalone detector with the smallest export/shared helper needed. Keep ordinary browser logout behavior unchanged. PWA logout, including unconfirmed/rejected server logout and handoff account switching, goes to `/app`, preserving `signout=unconfirmed`. Keep the session controller's clearing/generation behavior and render guards; never restore private cached content while navigation settles. Present the existing warning meaning accessibly at `/app`.
2. Replace the welcome page's local foreground/background/color-scheme and focus colors with existing app tokens. Inspect its welcome artwork for hard-coded monochrome foregrounds; change only those needed for parity and readable controls. Retain Ally colors, layout, safe areas, and sign-in behavior. Cover welcome, loading, error, and resume presentation without a new provider or theme store.
3. Coordinate creation through the concrete handoff contract below, using existing Home state and conversation query ownership. Keep the destination mounted behind the drawer. Do not wait for runtime completion or a generated answer. Verify the separate resume handoff still routes directly and retains saved inputs on failure; modify it only for demonstrated shared root causes.
4. Extend the existing focused tests and smoke fixtures with delayed route and conversation responses. Check intermediate visible states, not just the eventual URL. Run the required validation below. Apply separate correctness and simplicity reviews, including Ponytail review before PR creation; resolve material findings and rerun affected checks. Update the checkbox list and episode evidence only for verified outcomes.
5. Deliver a focused PR into `dev`, with tests, head SHA, concise behavior summary, and remaining device/deployment caveats. Do not merge. Immediately create the requested separate `gpt-5.6-luna`, thinking `max`, monitor using the PR URL/number and head SHA; monitor current-head CI/CU/tests, Enkii code/security/policy/full mergeability, comments, and head changes, remaining quiet while unchanged. Stop only on the specified complete passing state or concrete user-action blocker. Return monitor ID/status and retain the isolated worktree while the unmerged PR is monitored.

Ponytail full applies after tracing the flow: existing helpers first, then standard library/native CSS, then the minimum code. Add no dependency or general transition abstraction. Keep the fewest files and shortest root-cause diff that preserve accessibility, security, error handling, validation, drafts, and durable queue semantics. Aim for one reviewable PR; reassess above 500 non-generated changed lines.

## Handoff contract (ADV-001/002)

Home owns one reactive accepted handoff record: account/workspace identity, returned Ally, exact preview greeting, and submitted trimmed reply. Pass these existing values through `onCreated`; do not introduce a store or second creation command. Before acceptance, cancellation retains its existing behavior. Immediately after acceptance, lock creation submit, Escape, backdrop, close, and exit-to-roster actions; retain this record until successful release or session/account loss. A stale `/home/new` segment must never reopen/reset the provider. Pending routing renders the accepted Ally from this record even if an invalidated roster temporarily omits it, without claiming roster refresh is authoritative proof of deletion. Session loss still removes all private UI; authoritative access denial shows the existing safe error, not cached chat.

`ConversationPane` owns the readiness predicate because its existing `conversationQueryKey(workspaceId, ally.id)` query supplies the destination transcript. Notify Home with the accepted Ally ID only when the current account/workspace match, that Ally route is selected, and the loaded conversation contains the correlated onboarding exchange: assistant sequence 1 with exact saved greeting and user sequence 2 with exact submitted reply (including an accepted live queue entry if that is the query's representation). If the API supplies conversation/message IDs, also compare them; never accept arbitrary nonempty history or another Ally's callback. Use existing mapped Cloud fields and original saved values, not synthesized messages. Once released, preserve the mounted pane and its draft/queue state. No new send occurs for the already-created first reply.

A successful but empty/partial/mismatched response is **incomplete**, not ready and not permission to dismiss. Reuse the pane's query/refetch path: at most three additional refreshes, two seconds apart, with no overlapping requests; cancel this handoff refresh on readiness, account/Ally change, or unmount. After exhaustion, or a real query failure, retain a visible handoff status with accessible manual retry. Retry resets only this bounded read budget and reissues navigation to the recorded `/home/<id>` if the route is still stale; it never invokes create or sends the first reply again. A route still stale after the same bounded window likewise exposes this retry control. Permanent access errors retain existing authorization-safe recovery rather than automatic retry. Loading/error controls must remain focusable and announced; errors do not satisfy readiness or silently reveal the roster. This small bounded retry is recovery, not a visual completion timer.

## Acceptance and focused validation

- AT-032: test standalone media and iOS signals, browser fallback, confirmed/unconfirmed/rejected logout, warning visibility, and no account/private content during session loss or delayed navigation. Preserve session restore and account-switch safeguards.
- AT-033: in production browser smoke tests emulate light and dark, assert computed canvas/text/color-scheme parity with global tokens and readable focus/error controls; include a runtime scheme change. Keep existing `/app` restoration/resume tests.
- AT-039: exercise signed-in creation from roster and `/home/new`, delayed route commit, delayed conversation fetch, and failure/retry on desktop/mobile. From first reply submission until final chat is visible, observe no intervening roster/list surface. Assert the same Ally ID and exact greeting/reply survive. Existing stable-create-key retry, saved resume/account isolation, queued-send persistence/reload, same-key uncertain-send retry, and queue tombstone tests remain green. Add only missing boundary assertions, reusing existing fixtures; do not duplicate the full queue suite.
- Handoff boundary regressions: successful empty/partial/wrong-exchange response cannot release; the matching exchange can. Exhausted reads expose manual retry; retry and stale-route recovery never increment create/send calls. Escape/backdrop/exit after acceptance cannot dismiss; an invalidated roster cannot recreate or substitute the Ally. Ignore readiness from another Ally/account and stop bounded refresh on unmount. Reuse a small parameterized test for these states rather than building a parallel harness.

Likely edits: `apps/web/app/account/account-client.tsx`, `app/app/app-page-client.tsx`, `app/app/app.module.css`, `app/home/home-workspace.tsx`, their existing tests, and `tests/home-smoke` specs. Adjacent conditional edits: `lib/pwa/pwa-install.tsx`, `lib/allies/onboarding-handoff-screen.tsx`, and welcome artwork. Avoid unrelated conversation-frame styling or queue refactoring.

From repository root with Bun 1.2.20 and the locked dependencies:

```sh
bun run test:run --project web apps/web/app/account/account-client.test.tsx apps/web/app/app/app-page-client.test.tsx apps/web/app/manifest.test.ts apps/web/lib/pwa/pwa-install.test.tsx apps/web/lib/allies/authenticated-onboarding-flow.test.tsx apps/web/lib/allies/onboarding-handoff.test.tsx apps/web/app/home/home-workspace.test.tsx
bun run lint:web
bun run typecheck
bun run build:web
bun run --cwd apps/web test:home-smoke
```

Build/smoke uses the CI public Cloud origin (`https://cloud.invalid`) and mocked Cloud fixtures; this is not live backend/device proof. Home smoke starts the production server on port 3012 and includes desktop/mobile Chromium plus PWA WebKit. CI additionally enforces `cloud:check`, full tests/lint, scoped chat-frame and motion checks and mobile build as selected by `scripts/ci-scope.ts`; all applicable current-head checks remain delivery gates. No tests were run during planning.

## Risks, decisions, rollback

Live deployment SHA and route availability remain unverified beyond the recorded 404s; disclose this in delivery and require a later deployed-build retest. They do not block the repository/build implementation gate (DEC-005). Theme selection is assumed to mean the current system-driven app contract; if an existing explicit selector is found, consume its authoritative tokens. Delayed routing can strand an overlay or reset state; test both intermediate success and error transitions, keyboard focus, and cancellation. Keep account/workspace/Ally queue keys, create/send idempotency keys, and accepted-first-reply ownership unchanged. Never use a visual delay timer as the completion condition.

Rollback is a focused revert of this web presentation/navigation change through the normal PR workflow. There is no migration, new storage format, dependency, or backend contract to roll back; preserve existing drafts and queues. Deployment and physical-device retesting remain distinct from local passing checks.
