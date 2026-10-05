# Mobile and Web Product Parity Plan

## Feature overview

- **Problem:** the consolidated native app and the restored web Home each contain reviewed pieces of the real Allies flow, but they are not yet delivered from one Interface branch. Native also lacks the content-free wake hint, app foreground reconciliation, and the deployed callback-path alias needed by the configured sign-in return. Live staging additionally exposed a Foundry activation replay that treats a stopped, already-bound Machine as read-only readiness verification, leaving first-Ally creation pending forever.
- **Outcome:** one Interface branch preserves each platform's current UI while Google sign-in, first-Ally creation, roster, conversation history, send/retry, durable reply recovery, and sleep/wake behavior use the same versioned Cloud contracts; the narrow Foundry follow-up wakes a stopped bound Machine through its durable operation and current-boot readiness path.
- **Starting points:** `mobile/consolidated-app@0e2b26a` and the reviewed committed `web/fix/restore-live-home@2b092b6`, which already includes the PR24 recovery work.
- **Source docs:** `.agent/mobile-web-parity/brief.md`, `.agent/mobile-web-parity/episode-state.md`, `apps/mobile/README.md`, `docs/plans/restore-live-home.md`, the accepted Nabu conversation/auth/mobile notes recorded in the episode, and both repositories' engineering policies.

## Scope and boundaries

### In scope

- Merge the web restore head into the mobile base with ancestry intact and retain the superset of mobile auth/creation support and web durable-reply/recovery behavior.
- Make native Google redirect completion work through both the existing `/auth/return` route and the configured `/auth/callback` path, with the same callback broker and safe `returnTo` handling.
- Close native creation recovery gaps: storage errors, cancellation/session races, successful roster invalidation, idempotent replay, and actionable post-setup error states.
- Add a content-free native `composing_started` hint on the first meaningful edit for an Ally. Use the existing `CloudClient.requestRuntimeIntent` contract; do not send draft text or make message sending depend on the hint.
- Add native foreground/background handling so polling pauses off-screen or in the background, then the newest durable conversation and activity replay reconcile when the app becomes active.
- Prove the real route components and shared-client requests with mounted tests, then separate local controlled evidence from web preview, staging, and physical-device acceptance.
- Make the narrow Cloud authorization change that permits an authenticated native bearer on the existing runtime-intent endpoint while retaining browser CSRF behavior.
- Make the narrow Foundry activation-recovery change on `fix/activation-wake-recovery` from `dev@313dde0`: a stopped bound Machine receives one durable wake operation and activation remains pending until that start epoch's readiness receipt is current.

### Out of scope

- Unifying React, React Native, navigation, secure-token storage, UI components, or platform presentation.
- Mobile waitlist, username/password or ChatGPT authentication, a second API client, production mocks, rich actions, Events, Routines, search, or Foundry calls from Interface.
- Native SSE in this delivery, a new streaming dependency, background execution, or enabling SSE by default. Web and native keep bounded replay/poll fallback; web SSE remains opt-in.
- Cloud/Foundry redesign, production promotion, OTA publication, or claiming provider/device acceptance from fixtures.

## Current evidence and decisions

- Mobile already calls the shared client for onboarding, creation, workspace roster, account, conversation pages, send/retry, and bounded activity replay. Pending create/send commands are encrypted and account/workspace-bound.
- `apps/mobile/src/app/_layout.tsx` and `apps/mobile/src/lib/providers/app-providers.tsx` have no `AppState` bridge. The conversation uses route focus only, disables background polling, and refetches only current activity on focus; an app that remains on the same route can therefore miss the foreground edge.
- `apps/mobile/src/lib/cloud/native-cloud-client.ts` does not classify `POST /api/v1/allies/{ally_id}/runtime-intents` as bearer-authenticated, although `@allies/cloud-client` already validates and sends that contract.
- Cloud `RuntimeIntentController.request` on `dev@02771f0` calls `_require_origin(request)`; the existing accepted native pattern is `_require_origin(request, allow_native_bearer=True)`. Ninja/controller code owns this check; no separate middleware route exemption was found.
- `apps/mobile/src/app/allies/new/complete.tsx` reads/binds the pending command outside its error boundary, does not fence success cleanup/navigation against abort or session replacement, and does not invalidate the roster after confirmed creation. `post-setup.tsx` shows a permanent spinner for a missing ID and has no action on query failure.
- The app exposes `/auth/return`, while the deployed native callback path supplied for integration is `/auth/callback`. Both paths should be thin aliases of one screen; the configured exact HTTPS redirect remains the value verified by PKCE.
- The web restore head makes SSE opt-in and retains polling/replay fallback. Its stream reader is web-owned and depends on browser streaming primitives. Native has no adapter, no enabled flag, and no evidence that deployment connection capacity or mobile suspension behavior supports SSE safely.
- A three-way merge preview shows overlapping edits in CI triggers, secret scan, `bun.lock`, the mobile conversation-state tests, and generated/shared Cloud-client files. Generated schema files must be regenerated from one selected pin rather than resolved line by line.
- In Foundry, `activate_fly_workspace` currently calls read-only `WorkspaceLifecycle.verify_workspace_ready` whenever `machine_generation > 0` and provisioning is `IDLE`. A stopped Machine therefore remains retryable forever. Directly calling `request_execution_wake_locked` is insufficient because its `is_runtime_ready` fast path can trust a stale readiness receipt and return without a wake. The safe reuse point is a narrow activation-recovery service that locks and re-reads the Workspace, validates the still-live activation claim and exact observed binding/generation, clears stale readiness evidence, and then delegates the durable request transition to `request_execution_wake_locked`. `process_runtime_wakes` remains the exclusive owner of operation claims, provider start, `advance_runtime_start_epoch_locked`, retry/backoff, and transition to `AWAITING_READINESS`; `accept_runtime_readiness` supplies the generation/start-epoch/boot fence required before claims or activation success.

## Contracts to preserve or change

| Boundary | Contract and invariant | Failure/recovery behavior |
| --- | --- | --- |
| Native auth return | `/auth/return` and `/auth/callback` render the same callback broker. The existing sign-in flow owns one in-memory PKCE attempt across same-process sign-in-to-callback route navigation; PKCE verifies the exact configured redirect, state, single code, and active attempt before token exchange. | Unmounting the sign-in route for callback navigation does not cancel the attempt; completion, explicit cancellation, expiry, or existing provider teardown does. Stale, malformed, canceled, or mismatched returns expose retry. No verifier, state, code, URL, or access token is persisted, and process-death recovery is not promised. Manual-code mode remains a temporary explicit setting. |
| First-Ally creation | `POST /api/v1/workspaces/{workspace_id}/allies` keeps the saved command and idempotency key for the same input. Cloud success is authoritative. | Storage/read errors and uncertain HTTP outcomes keep an actionable retry. A late result from an aborted or replaced session cannot navigate or alter another account's cache. A replayed success invalidates the signed-in workspace roster and opens the returned Ally without creating a duplicate. |
| Foundry activation recovery | For an `IDLE`, already-bound Workspace whose owned Machine is observed `STOPPED`, activation passes the unexpired activation-claim token and observed app/Machine/binding/generation tuple to one narrow runtime-service helper. In one transaction the helper locks and re-reads the Workspace, rejects changed evidence, clears stale `ready_*` evidence without advancing the epoch, and enqueues or reuses the authoritative execution wake through `request_execution_wake_locked`. The normal `process_runtime_wakes` worker exclusively owns inspection, provider start, start-epoch advance, and `AWAITING_READINESS`. Activation reports active only after provider readiness and `is_runtime_ready` agree on the current generation, start epoch, and boot receipt. | Expired/replaced activation claims or a binding/generation changed since provider inspection produce a retryable conflict with no mutation. Replayed or concurrent activation observes the same operation and returns pending without another start. Retryable/uncertain provider failure stays on the existing bounded operation retry path. Missing/destroyed or foreign-owned binding never starts or replaces a Machine and keeps the existing safe unavailable/replacement-required result. |
| Runtime intent | `POST /api/v1/allies/{ally_id}/runtime-intents`, bearer or browser session as appropriate; body is exactly `{ intent: "composing_started", occurred_at }`, plus one UUID idempotency key. | Emit at most once for the first non-empty edit in the mounted Ally composer; reset for a different Ally/remount. Abort on teardown. Ignore disabled, throttled, offline, and other hint failures so draft/send remain usable. Never transmit draft content. |
| Conversation/send | The shared client owns DTO validation. Pending sends remain account/workspace/conversation-bound; one logical send retains one idempotency key; `replayed: true` is accepted and deduplicated. | Unknown outcomes keep the command. Definitive rejection releases it without losing the draft. Pages/replies merge by IDs and sequence; terminal state is monotonic and missing ranges remain visible as reconciliation failures. |
| Native lifecycle | Route focus **and** `AppState === "active"` determine live polling. TanStack Query receives native focus state. On background-to-active, refetch the newest durable conversation plus activity replay/tail for the selected conversation. | Backgrounding cancels/pauses client polling but never cancels server work. Foreground reconciliation is bounded, deduplicated, abortable, and leaves prior content visible on failure with retry available. Roster/account queries refetch through the existing query keys and current session only. |
| Streaming | `NEXT_PUBLIC_ACTIVITY_SSE_ENABLED` remains explicit opt-in after the web merge. Native continues the current bounded activity polling and signed-cursor replay. | A web stream timeout/error/close returns to replay/poll. Native does not open a long-lived stream in this change. Reconsider only with measured deployment connection capacity, React Native streaming/abort proof on both platforms, and the same cursor/dedupe/fallback tests. |

No HTTP request or response schema changes. The Cloud OpenAPI description/security metadata should document that runtime intent accepts either the existing browser session plus trusted origin/CSRF or a validated native bearer; authorization, tenant hiding, status codes, rate limits, and strict content-free validation remain unchanged.

## Implementation phases

### 1. Integrate the reviewed web restore and reconcile the shared client

- Merge `web/fix/restore-live-home@2b092b6` into the integration branch with both parents preserved. Do not copy files from or edit the source worktree.
- Keep PR26's live `/home`, `/home/[allyId]`, `/home/new`, Exact shells, PR24 assistant replies, bounded 48 MiB chat-read limit, account-scoped pending sends, rejected-send recovery, opt-in SSE, polling fallback, and web route tests.
- Keep the mobile base's native completion mode, auth/session DTOs, mobile conversation projection/replay cases, and current Expo app. Resolve CI/secret-scan branch triggers as a union. Regenerate `bun.lock` from the merged manifests.
- Preserve the already verified deployed-staging OpenAPI pin, which contains both native `manual_code` completion and durable assistant replies; regenerate `packages/cloud-client/src/generated/openapi.ts`, then run `cloud:check`. The Cloud authorization-only patch does not require a new commit pin or DTO regeneration unless it changes published OpenAPI metadata. Do not hand-merge generated output or downgrade either contract.

**Exit:** the merged tree contains both real platform flows, no production mock route replaces them, and focused web/mobile/shared tests compile before parity changes begin.

### 2. Finish native authentication and creation recovery

- Extract the existing native callback screen into one feature component and make both `src/app/auth/return.tsx` and a new `src/app/auth/callback.tsx` thin route entries. Reuse the existing sign-in flow so its single in-memory PKCE attempt survives same-process navigation to either callback alias: sign-in route unmount must not cancel it, while completion, explicit cancellation, expiry, or existing provider teardown must dispose it. Update route guards/tests so either path stays available while signed out and returns through the same sanitized target after sign-in. Add no new provider, auth framework, or persistence, and do not claim recovery after process death.
- In `src/app/allies/new/complete.tsx`, place bind/read/create/cleanup inside one abortable operation keyed by the captured user/workspace. Before cache writes or navigation, verify the operation is current and the same session still owns it.
- Preserve the command for storage and uncertain network failures. After a confirmed/replayed create, invalidate `allyKeys.all(workspaceId)` (and seed/invalidate the returned detail as useful), attempt encrypted-command cleanup, and navigate using the Cloud-returned ID. A cleanup failure must not reinterpret confirmed creation as a failed create; replay remains safe under the same idempotency key.
- Give missing-ID and load-error states in `post-setup.tsx` explicit retry, return-to-roster, or restart actions instead of an indefinite spinner/static dead end.

**Exit:** redirect/manual sign-in survives same-process route navigation, and first creation survives retry, cancellation, storage failure, and session replacement without duplicate Allies or cross-account cache writes.

### 3. Add native wake intent through the existing contract

- Add a small mobile composer hook beside the conversation feature, modeled on the reviewed web behavior. It observes native `onChangeText`, generates a UUID and timestamp only on the first meaningful edit for the current Ally, aborts on Ally change/unmount, and swallows speculative-hint failure.
- Call `session.accountClient.requestRuntimeIntent` through `session.adapter.withRefresh`. Add the exact runtime-intent path to `isAuthenticatedCloudRequest`; do not broaden the bearer allowlist.
- In the separate Cloud fix branch based on `dev@02771f0`, change only the runtime-intent origin check to the existing native-bearer-aware helper, add native/browser boundary tests, and update generated OpenAPI security/description if the published schema is affected. Interface consumes the resulting pinned schema through its normal generation workflow.
- Keep web and native presentation hooks platform-local. The request schema, response parser, authorization, retry classification, and idempotency contract remain shared in `@allies/cloud-client`; do not introduce a shared chat controller.

**Exit:** one non-empty native edit can wake the selected Ally without content leakage or per-keystroke requests, and failure never blocks the subsequent send.

### 4. Recover stopped bound Machines during Foundry activation

- In `activate_fly_workspace`, keep first provisioning and healthy replay unchanged. For the narrow `IDLE` plus existing binding plus provider-observed `STOPPED` case, call one runtime-service helper with the current activation-claim token and the exact observed app ref, Machine ref, ownership binding, and generation; then return a retryable activation result so the API continues to report `202 pending`. Do not call `request_execution_wake_locked` directly from the command.
- The helper must atomically lock/re-read the Workspace, require the same unexpired activation claim, revalidate that provisioning state and the observed binding/generation tuple have not changed, clear stale readiness receipt fields without advancing `runtime_start_epoch`, and call/reuse the existing `request_execution_wake_locked` transition. An expired/replaced claim or changed binding/generation aborts without clearing readiness or creating an operation.
- Let `process_runtime_wakes` exclusively claim and process that durable operation. Preserve its operation ID/token ownership checks, provider binding/generation verification, exactly-once start behavior under concurrent workers, `advance_runtime_start_epoch_locked` fence, `AWAITING_READINESS` transition, and existing bounded retry/backoff classification. Add no direct provider start, Machine replacement, second processor, or new operation state.
- On activation replay, return pending while the operation is `REQUESTED`, `STARTING`, or `AWAITING_READINESS`. Return active only after the owned Machine is started/healthy and `is_runtime_ready` proves a receipt for the current `machine_generation`, `runtime_start_epoch`, and boot. Do not accept the prior boot's receipt.
- Keep missing Workspace, path/body mismatch, missing/destroyed Machine, foreign provider ownership, and incomplete binding on their current safe paths; none may enqueue a wake, start a Machine, or silently replace one. Preserve the activation claim and runtime operation claim as separate serialized owners, including expired-claim recovery.

**Exit:** a stopped bound first-Ally Workspace with stale ready evidence wakes once and becomes active only after the current boot is ready; replay, concurrency, claim expiry/replacement, observed-binding races, and transient failure remain idempotent and retryable without weakening ownership or generation fences.

### 5. Reconcile native background, foreground, and reconnect

- Add one provider-level native lifecycle bridge using `AppState` and TanStack Query's `focusManager`; clean up its subscription and restore the active state deterministically on mount.
- Make conversation liveness require both Expo route focus and active app state. On transition back to active, refetch the newest durable conversation and bounded activity replay/tail, using the existing query keys, signed cursor, projection ordering, and abort signals. Coalesce duplicate focus events rather than starting parallel reconciliation.
- Keep `refetchIntervalInBackground: false` and continuous polling while the route is focused, the app is active, and the turn remains active: start at a 3-second interval, back off after two minutes, and cap the interval at 15 seconds without imposing an active-turn cutoff. Do not mark a backend execution failed because the app slept. A foregrounded terminal reply replaces/extends the projected activity monotonically and clears no saved send until Cloud acceptance is known.
- Let roster/account freshness use the same query focus bridge; session refresh remains serialized by `NativeSessionAdapter.withRefresh` rather than adding a second token-refresh loop.

**Exit:** backgrounding pauses native polling, and foregrounding the same mounted conversation recovers remote messages/replies that completed while suspended without duplicate sends or stale-account data.

### 6. Prove mounted behavior and delivery readiness

- Add mounted route tests outside the Expo Router directory, under `apps/mobile/src/features/` using the existing Vitest/jsdom stack and one controlled native boundary harness. Render the actual sign-in/callback, complete-creation, roster, and conversation route components; mock only native presentation/platform ports, not route orchestration or the shared-client request layer.
- Drive user actions through rendered controls and controlled `fetch`: start Google auth, transition the mounted app from sign-in to each callback alias while the existing flow remains alive, complete the return, verify attempt cleanup, resume creation, render fetched roster, open a conversation, type the first edit, send once, background/foreground, receive a durable reply, and recover a retained unknown send. Assert URLs, methods, bearer placement, content-free intent body, stable idempotency keys, query isolation, route navigation, and visible loading/error/retry states. Add a cancellation/expiry transition case and state explicitly that a fresh process has no recoverable PKCE attempt.
- Retain unit tests for pure projection, PKCE, secure session, storage, and transport edges. Source-string assertions may guard generated/import boundaries, but they do not satisfy route acceptance.
- Run web mounted-page and Playwright checks from PR26 so the integrated branch proves its real Home routes as well as native controllers.

**Exit:** deterministic mounted tests prove the orchestration; browser preview, staging probes, and physical-device/provider checks are recorded as separate evidence with any external gate stated explicitly.

## Likely affected files and systems

- Integration/shared: `.github/workflows/{ci,secret-scan,railway-pr-environment}.yml`, `package.json`, `bun.lock`, `packages/cloud-client/{openapi,src,test}`.
- Mobile routes: `apps/mobile/src/app/{_layout,sign-in}.tsx`, `apps/mobile/src/app/auth/{return,callback}.tsx`, `apps/mobile/src/app/allies/index.tsx`, `apps/mobile/src/app/allies/new/{complete,post-setup}.tsx`, `apps/mobile/src/app/allies/[allyId]/index.tsx`.
- Mobile boundaries: `apps/mobile/src/lib/providers/app-providers.tsx`, `apps/mobile/src/lib/query/create-query-client.ts`, `apps/mobile/src/lib/cloud/native-cloud-client.ts`, `apps/mobile/src/lib/session/session-route.ts`, and focused tests.
- Mobile conversation: a small lifecycle/runtime-intent hook under `apps/mobile/src/features/conversation/`, existing conversation state/layout wiring, and mounted route tests under `apps/mobile/src/features/` importing the real route components.
- Cloud follow-up: `backend/allies/api/controllers.py`, `backend/allies/tests/test_runtime_intents.py`, and OpenAPI customization/tests only if generated security metadata changes.
- Foundry follow-up: `backend/runtime/management/commands/activate_fly_workspace.py`, one narrow helper in the existing runtime wake/readiness service boundary, and `backend/runtime/tests/{test_activate_fly_workspace_command,test_fnd009_runtime,test_profile_provisioning_api}.py`; no new processor, model state, migration, or public API.

## Acceptance criteria

1. The integration branch contains the complete reviewed web restore/recovery ancestry and the current native app; each platform retains its existing UI and real routes.
2. Native Google sign-in completes through the exact registered HTTPS callback using either route alias, rejects stale/mismatched callbacks, and resumes the sanitized creation or roster target.
3. A first Ally is created from the saved real onboarding attempt/reply. Transient or storage uncertainty is retryable with the same idempotency key; confirmed/replayed success updates the roster and cannot navigate after account/session replacement.
4. A stopped, bound Foundry Machine with stale ready evidence receives exactly one durable activation wake. The power worker, and only that worker, starts the provider Machine and advances the runtime start epoch; activation waits for a readiness receipt from that current boot before first-Ally provisioning completes. Replayed/concurrent activation does not duplicate the operation or provider start.
5. The activation-recovery transaction rejects an expired/replaced activation claim and any binding or generation changed after provider observation without mutating readiness or wake state. Missing, destroyed, incompletely bound, or foreign-owned Machines are not started or replaced. Retryable and uncertain failures stay pending on the existing bounded retry path.
6. Roster, Ally detail, conversation history, send/retry, assistant replies, and account data come only from the signed-in workspace through `@allies/cloud-client`; cache and pending commands never cross user/workspace identity.
7. The first meaningful native composer edit sends one content-free runtime intent. Browser CSRF remains required, a valid native bearer is accepted, invalid/foreign sessions remain hidden/rejected, and hint failure does not change draft/send behavior.
8. Backgrounding stops native polling. Foregrounding the same route reconciles durable conversation and replayed activity, including a reply completed while suspended, without duplicate sends, reordered terminal state, or fabricated failure.
9. Web SSE is disabled unless explicitly enabled and always falls back to bounded replay/polling. Native uses bounded polling in this delivery; no streaming dependency or background-service claim is added.
10. Mounted route tests exercise real controller wiring and request shapes. Browser preview, staging contract/auth probes, and physical-device Google/app-link tests are reported separately and honestly.

## Validation

### Focused during implementation

- Interface: `bunx vitest run --project mobile <changed mobile tests>` and `bunx vitest run --project packages packages/cloud-client/test`.
- Web merge/recovery: run the focused `home-workspace`, public-route, runtime-intent, activity-stream, and Cloud-client tests carried by PR26.
- Cloud fix: `make test APP=allies/tests/test_runtime_intents.py`, `make check`, and `make lint` in the Cloud worktree.
- Foundry activation fix: `make test APP=runtime/tests/test_activate_fly_workspace_command.py`, `make test APP=runtime/tests/test_fnd009_runtime.py`, and `make test APP=runtime/tests/test_profile_provisioning_api.py`; cover a `STOPPED` bound Machine with stale `is_runtime_ready` evidence, start-once/current-boot readiness, exact replay and concurrent activation/runtime claims, binding or generation changed between provider observation and the helper lock, expired/replaced activation claims, retryable/uncertain provider failure, stale receipt rejection, and missing/destroyed/foreign-owned no-wake behavior.
- Foundry complete checks: `make check`, `make validate`, and `make lint` in the isolated Foundry worktree.
- Inspect actual controlled requests for exact route, method, body, idempotency key, bearer/CSRF choice, abort, and account/workspace query keys.

### Complete local checks

```text
bun run cloud:check
bun run test:run
bun run typecheck
bun run lint
bun run build:web
bun run bundle:mobile
cd apps/mobile && bunx expo export --platform android --output-dir dist/android-parity-check
git diff --check
```

Run the PR26 chat-frame/route Playwright scripts exposed by the merged `package.json` without updating approved baselines. Inspect the final diff against both merge parents to confirm the native-auth and web-recovery contracts survived resolution.

### External evidence, kept distinct

- **Browser preview:** authenticated desktop and narrow `/home`, valid/invalid Ally routes, creation, send, live reply, refresh/reconnect, and SSE-off polling fallback.
- **Staging schema/probes:** pinned OpenAPI matches deployed Cloud; browser runtime intent still requires trusted origin/CSRF; native bearer runtime intent is accepted; roster/create/send/replay responses validate through the shared client.
- **Physical device/provider:** Android and iOS claimed-link callback, cancellation, provider return after app backgrounding, session restore, first creation, backgrounded reply completion, foreground reconciliation, and manual-code mode only where explicitly configured. These are release gates and cannot be replaced by fixture results.

## Risks, rollback, and open evidence

- **Merge regression:** shared generated files and conversation tests changed on both parents. Regenerate from one verified pin, combine behavioral cases, and inspect both-parent diffs. Roll back the integration merge as one commit if either platform contract is lost.
- **Creation success with failed local cleanup:** treating local deletion as the create outcome can strand the user. Treat the Cloud response as authoritative, keep idempotent replay safe, expose operationally safe retry/cleanup, and never delete a command before acceptance.
- **Lifecycle races:** rapid focus/AppState/session changes can apply stale replies or navigate under another account. Use aborts plus captured identity/generation and existing query keys; tests must cover a late old operation.
- **Wake authorization rollout:** Interface cannot enable native waking until the narrow Cloud fix is deployed; refresh the verified schema pin only if published OpenAPI metadata changes. Until then the hint fails harmlessly and send/poll remain functional.
- **Activation claim collision, stale readiness, or time-of-check race:** activation and runtime power reuse the Workspace claim fields; `request_execution_wake_locked` can early-return on stale ready evidence, and provider inspection can become stale before the database lock. The narrow helper must validate the unexpired exact activation token and observed app/Machine/binding/generation under lock, clear only the stale readiness receipt, and enqueue/reuse the wake atomically. The power worker alone starts and advances the epoch; activation gates `active` on the current generation/start epoch/boot readiness tuple.
- **SSE capacity and mobile suspension:** no current evidence supports native long-lived streams or default-on web SSE. Keep both decisions unchanged; a later proposal needs measured connection capacity, platform transport proof, and cursor/fallback tests.
- **External auth configuration:** redirect allowlists, association files, provider credentials, or staging deployment may block device proof. Record the exact gate and do not add an auth bypass.

Rollback is additive and bounded: revert the parity commits and the separate Cloud native-runtime-intent and Foundry activation-recovery commits if deployed, returning native to polling without wake hints, web to its reviewed restore head, and activation to its prior read-only replay behavior. Pending commands and Cloud durable conversation data remain valid because no storage or public API schema migration is introduced.

## Resolved decisions and deferred evidence

- **ADV-001 — accepted:** the minimal existing sign-in flow keeps its in-memory native-auth attempt across same-process callback navigation. Tests must cover route-unmount survival and terminal cleanup. Attempt persistence and process-death recovery remain outside the contract.
- **SIM-001 — accepted:** reuse the existing sign-in flow without adding a provider, framework, or persistence layer. Sign-in route unmount for same-process callback navigation preserves the attempt; existing provider teardown cancels it. No broader remount or process-death guarantee is made.
- Keep the verified deployed-staging OpenAPI pin. The native runtime-intent authorization patch does not change DTOs; refresh the pin only if its generated security/description metadata changes.
- Keep both `/auth/return` and `/auth/callback` as supported aliases. Existing builds/tests use `/auth/return`, while the configured integration path uses `/auth/callback`.
- Native SSE remains intentionally deferred. Reopen only when the evidence threshold in the streaming contract is met.
- **ADV-002 — accepted:** direct `request_execution_wake_locked` reuse is unsafe when stale ready evidence makes it return early. One activation-recovery helper must lock/re-read, validate the live activation claim and observed exact binding/generation, invalidate stale readiness, and enqueue/reuse the wake atomically.
- **SIM-002 — accepted:** the helper delegates to the existing wake transition, and `process_runtime_wakes` remains the sole start/epoch processor. Add no direct Machine start, replacement path, new processor, operation state, migration, or public API shape.

- Repository placement correction: keep test files outside `src/app`; the mobile README records a real Android failure when Expo Router bundled Vitest from a route test. Mounted tests still import actual routes.
