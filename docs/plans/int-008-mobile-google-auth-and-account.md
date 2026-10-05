# INT-008: Mobile Google auth and personal account

## Status

- Type: feature
- Planning status: accepted
- Platform: mobile
- Implementation branch: `mobile/int-008-google-auth-account`, targeting `mobile/dev/onboarding`
- Source of truth: Nabu canonical INT-008 and linked AUTH-002 notes
- Plan artifact: `docs/plans/int-008-mobile-google-auth-and-account.html`
- Working artifact: `.lavish/int-008-mobile-google-auth-and-account.html`
- Created: 2026-08-21

## Objective

Turn the mobile session placeholder into secure native Google sign-in, session restoration, profile and avatar editing, and personal Workspace access. Mobile owns the native browser/app-link/session lifecycle; Cloud remains the durable authority for identity, authorization, profile, avatar, and Workspace semantics.

The implementation must use the native contract from AUTH-002. It must not emulate browser cookies, embed a WebView, handle Google provider credentials directly, or create a second account contract.

## Context and current state

- `apps/mobile/src/lib/session/session-context.tsx` intentionally exposes only `native-session-contract-pending`; no native account route is mounted.
- `apps/mobile/src/app/_layout.tsx` already owns fonts, splash, providers, keyboard dismissal, and the Expo Router stack.
- `apps/mobile/src/lib/providers/app-providers.tsx` already mounts TanStack Query and the placeholder native session provider.
- `packages/cloud-client/src/client.ts` already owns typed Cloud transport, response envelopes, account/profile/avatar/Workspace view models, request preparation, timeout, response limits, and Cloud error normalization for the existing web path.
- `packages/cloud-client/openapi/allies-cloud-0.1.0.json` and its generated TypeScript currently contain browser auth/account paths but not the five `/api/v1/auths/native/*` operations required by AUTH-002.
- The AUTH-002 implementation handoff says the native Cloud implementation is merged into Cloud `dev`, but Nabu records that staging/production OpenAPI and `ALLIES_AUTH_NATIVE_ENABLED` still require verification before live device proof.
- The repository baseline uses Bun, Expo Router, TanStack Query for server state, React local state for interaction, Vitest, and local mobile lint/typecheck. CI does not currently prove the mobile build or device flow.

## Desired behavior

1. A signed-out user can remain in public onboarding or open the native Google sign-in route.
2. The app starts one PKCE attempt, asks Cloud for an authorization URL, opens the system browser, consumes the registered app return, verifies state, and exchanges the one-time Cloud code.
3. The access credential lives only in memory. The current opaque rotating refresh token lives only in Expo SecureStore.
4. The root session provider restores a refresh session on launch and never claims signed-in until Cloud validates it.
5. Authenticated routes can load the current account and personal Workspace, edit display name, and manage the avatar lifecycle.
6. Refresh is serialized. Revocation, logout, 401 session invalidation, and uncertain logout clear local credentials, memory, Query caches, and protected navigation.
7. Every request state is truthful: idle, opening browser, waiting, exchanging, canceled, failed, checking storage, refreshing, signed-in, signed-out, offline-with-session, unavailable, loading, ready, unauthorized, and retryable error where relevant.

## Scope

### In scope

- Expo Router public/authenticated route groups and a native sign-in entry.
- Expo AuthSession/system-browser Google flow with PKCE S256, app-link return, state verification, cancellation, and retry.
- SecureStore-backed refresh rotation, in-memory access credentials, restore, serialized refresh, revocation, and logout cleanup.
- Current account, display-name edit, avatar pick/upload/complete/read/delete, and personal Workspace semantics.
- Background/foreground and offline restoration behavior.
- Safe areas, keyboard, system back, screen-reader labels, touch targets, reduced motion, and privacy-safe error copy.
- Shared typed Cloud methods, response mapping, bearer allowlisting, and direct signed object-storage upload.
- Vitest coverage for pure session and contract logic, plus real Android and iOS dev-build smoke evidence.

### Out of scope

- WebView or browser-cookie emulation, Google/provider credentials, direct Google token handling, or browser CSRF behavior in native.
- Biometrics, device attestation, push, offline mutations, account switching, or pre-auth transfer.
- ChatGPT sign-in, team Workspaces, Ally creation, conversation streaming, or runtime execution.
- A new global store for credentials, account DTOs, or server state.
- Live device proof before Cloud staging deployment, native enablement, and exact redirect registration.

## Dependencies and release gates

| Gate | Evidence / owner | Plan treatment |
| --- | --- | --- |
| Native Cloud routes | AUTH-002 says implementation is merged to Cloud `dev`. | Verify staging exposes `POST /api/v1/auths/native/sign-in/google`, `GET /api/v1/auths/native/callback/google`, `POST /api/v1/auths/native/token`, `POST /api/v1/auths/native/token/refresh`, and `POST /api/v1/auths/native/logout`. |
| Feature enablement | `ALLIES_AUTH_NATIVE_ENABLED=true` in the target environment. | Keep live tests blocked and show unavailable/retry if routes are absent. Never silently switch to browser auth. |
| OpenAPI pin | Current local generated snapshot lacks native paths. | Refresh the shared snapshot and generated types from the accepted contract before adding native methods. |
| App return links | Exact HTTPS return URLs, schemes, Universal Links/App Links, and Google redirect registration. | Validate explicit configuration. Reject query/fragment/credential/wildcard redirect values. |
| Native build | AuthSession/SecureStore and app-link configuration affect native runtime. | Use real Android and iOS dev builds. The existing installed APK cannot prove this wave through OTA alone. |

The mobile implementation can proceed against fixtures while these gates are being completed. Device proof cannot be marked complete until they are satisfied.

## Architecture decision

### Recommended: shared typed contract plus a thin mobile adapter

Extend the shared Cloud boundary with the accepted native operations and keep the existing response view models. Wrap it with a small mobile session adapter that owns PKCE, app lifecycle, SecureStore, access-token memory, refresh serialization, and cleanup. Reuse the existing `createCloudClient` request-preparation seam for bearer injection and keep the native auth endpoints cookie-free.

This reuses the repository's existing transport, timeout, response-limit, error, and account mapping seams while keeping platform lifecycle concerns in mobile. It avoids screen-level token policy and avoids a second account contract.

### Rejected alternatives

- **Mobile-specific fetch layer:** duplicates envelope parsing, account mappers, error policy, and future OpenAPI changes without removing the native lifecycle work.
- **Browser cookies or WebView:** conflicts with the native session contract and creates ambiguous callback, privacy, logout, and lifecycle behavior.
- **Generic auth framework/global store:** adds more machinery than one provider requires and risks placing credentials or API data in an overly broad owner.

## Data path

```text
User
  -> useGoogleSignIn
  -> Cloud native sign-in start
  -> system browser -> Google -> Cloud callback
  -> registered app return URL
  -> verify state + exchange one-time Cloud code
  -> native session adapter
  -> SecureStore (opaque refresh) + memory (access/PKCE/state)
  -> bearer Cloud client
  -> TanStack Query account/profile/avatar/Workspace data
  -> authenticated mobile routes
```

No browser cookie crosses into native. The app never calls Google with a provider token and never sends a bearer to the object-storage upload URL.

## Ownership and implementation shape

| Area | Target files | Responsibility |
| --- | --- | --- |
| Contract boundary | `packages/cloud-client/openapi/`, `packages/cloud-client/src/generated/`, `packages/cloud-client/src/client.ts` | Pin the accepted native OpenAPI contract, regenerate types, add native sign-in/callback/token/refresh/logout methods, and preserve existing web cookie behavior. Map response envelopes and error codes without rendering raw provider/server details. |
| Credential port | `apps/mobile/src/lib/session/secure-session-store.ts` | Expose `readRefresh`, `writeRefresh`, and `clear`. Use Expo SecureStore only for the current opaque refresh token and minimal non-secret metadata required by AUTH-002. |
| Session lifecycle | `apps/mobile/src/lib/session/native-session-adapter.ts`, `apps/mobile/src/lib/session/session-context.tsx` | Own access-token memory, generation/cancellation, restore, one serialized refresh rotation, terminal revocation, logout cleanup, and explicit bootstrap states. A failed SecureStore write never becomes signed-in. |
| Google flow | `apps/mobile/src/features/auth/use-google-sign-in.ts`, `apps/mobile/src/app/auth/return.tsx` | Generate one in-memory PKCE attempt, call Cloud for an authorization URL, open the system browser, verify state, exchange the one-time Cloud code, and route cancellation/failure to retryable UI. |
| Authenticated transport | `apps/mobile/src/lib/cloud/native-cloud-client.ts`, `apps/mobile/src/lib/env.ts` | Reuse `createCloudClient` and request preparation for bearer injection. Keep native auth start/callback/exchange/refresh/logout cookie-free; send bearer only to allowlisted authenticated account routes. Centralize one refresh-and-retry path. |
| Account feature | `apps/mobile/src/features/account/`, `apps/mobile/src/app/(authenticated)/` | Use TanStack Query for account/avatar/Workspace server state, React local state for profile edits and upload progress, and existing Open Runde/safe-area UI conventions. Add profile schema validation at the mutation boundary. |
| Router/bootstrap | `apps/mobile/src/app/_layout.tsx`, `apps/mobile/src/app/(public)/`, `apps/mobile/src/app/(authenticated)/` | Mount one provider above route groups. Restore during splash/boot, redirect signed-in users to authenticated routes, keep public onboarding available while signed out, and never render protected data before Cloud validation. |
| Native configuration | `apps/mobile/app.json`, `apps/mobile/.env.example` | Configure exact redirect schemes/hosts, Android intent filters, iOS associated domains, and environment validation only after platform registration exists. Record runtime/version/build changes in the release handoff. |

## Contract details to preserve

### Native Google flow

1. Generate a random PKCE verifier and app state in memory for one attempt.
2. Compute an unpadded base64url SHA-256 verifier challenge with method `S256`.
3. POST native sign-in with no cookies, CSRF, or bearer: exact registered `redirect_uri`, `code_challenge`, `code_challenge_method: "S256"`, and `state`.
4. Receive Cloud's `authorization_url` and expiry.
5. Open the system browser with Expo AuthSession/system-browser primitives. Do not use Expo Go as proof of production app-link behavior.
6. Let Cloud handle Google callback and return to `redirect_uri?code=<single-use-cloud-code>&state=<original>` or a safe error result.
7. Verify state and discard the attempt on mismatch.
8. POST token exchange with grant type, one-time code, verifier, and the same redirect URI; no cookies, CSRF, or bearer.
9. Store only the current opaque refresh token in SecureStore and keep access/verifier/state/code in memory.

### Restore, refresh, and logout

- Restore only when SecureStore has a refresh token.
- Serialize refresh so concurrent 401s share one rotation rather than racing.
- Persist the new refresh token before discarding the old one; a SecureStore write failure means the app is not signed in.
- On `session_invalid`, clear all local credentials, memory, account queries, and protected routes.
- Attempt server logout, but clear local state after success, 401, timeout, or network uncertainty. Never retry an old rotated token.

### Authenticated account APIs

- `GET /api/v1/auths/me`
- `PATCH /api/v1/auths/me/profile` with `{"display_name":"..."}`
- `POST /api/v1/auths/me/avatar/uploads` with content type, size, and SHA-256
- direct signed object-storage upload with exact returned headers and no bearer
- `POST /api/v1/auths/me/avatar/{asset_id}/complete`
- `GET /api/v1/auths/me/avatar/read`
- `DELETE /api/v1/auths/me/avatar`
- `GET /api/v1/workspaces/{workspace_id}` when detail beyond the `/auths/me` Workspace summary is required

## State model

### Sign-in attempt

`idle -> opening-browser -> waiting-for-return -> exchanging -> signed-in`.

Cancellation returns to `idle` without persistence. State mismatch, expired flow, replay, timeout, or provider unavailability discards the attempt and offers a fresh retry. A verifier, state, or one-time code is never reused after a terminal result.

### Bootstrap and refresh

`checking-storage -> refreshing -> signed-in` when Cloud validates the session. A missing/invalid refresh becomes `signed-out`. Network failure with a still-present session becomes `offline-with-session` and exposes retry without deleting usable local refresh state. A terminal 401 becomes signed-out and clears local state.

### Ownership

- Session adapter: access token, refresh rotation, lifecycle generation.
- SecureStore: current opaque refresh token only.
- TanStack Query: account, profile/avatar, and Workspace server state/cache.
- React local state: form text, focus, upload progress, and retry intent.
- Zustand: no credentials or account DTOs; only add it if a real cross-screen workflow appears.

## Route and account experience

- Root layout mounts one session provider above route groups.
- Public group retains existing onboarding and adds native Google sign-in.
- An app-link return route receives the one-time return and hands it to the in-flight sign-in attempt.
- Authenticated group exposes personal account/profile/avatar/Workspace surfaces and sign-out.
- Signed-in bootstrap redirects to authenticated routes instead of restarting account creation.
- Signed-out onboarding remains usable without an account.
- Offline-with-session keeps the protected shell available with a retry affordance; it does not claim fresh server state.

## Implementation phases

### Phase 00: Admit the native contract

**Goal:** Make the external dependency visible and pin the exact shape before mobile calls it.

**Work items:**

- Verify AUTH-002 implementation against staging OpenAPI.
- Regenerate the shared snapshot/types and record the contract revision.
- Confirm staging flag, callback URLs, schemes, and claimed links.

**Impacted systems:** Cloud staging configuration, `packages/cloud-client`, iOS/Android app registration.

**Exit criteria:** Five native operations are typed; exact return URLs are registered; device proof is unblocked or explicitly recorded as pending.

### Phase 01: Build the native session adapter

**Goal:** Replace the unavailable mobile provider with one lifecycle owner and a fixture-tested Google flow.

**Work items:**

- Add Expo AuthSession/SecureStore dependencies using exact SDK 57 guidance.
- Implement PKCE, state, browser return, exchange, restore, rotation, revocation, and logout.
- Inject bearer credentials through the existing transport seam.
- Add root bootstrap and public/authenticated route gating.

**Impacted systems:** `apps/mobile/src/lib/session`, `apps/mobile/src/features/auth`, root providers, Expo Router, `packages/cloud-client`.

**Exit criteria:** Unit tests cover terminal paths; no secret is persisted outside SecureStore; Android and iOS dev builds prove sign-in, cancel, relaunch, refresh, and logout.

### Phase 02: Deliver account parity

**Goal:** Expose the same personal account semantics as web through native composition.

**Work items:**

- Build current account and personal Workspace views.
- Add display-name edit with the web limit and boundary validation.
- Add image pick, metadata hash, signed upload, completion, read, replace, and delete.
- Add query invalidation and recoverable offline/error states.

**Impacted systems:** `apps/mobile/src/features/account`, TanStack Query keys/invalidation, direct object-storage upload path.

**Exit criteria:** Loading/ready/offline/error/unauthorized states are visible and recoverable; bearer never reaches object storage; profile/avatar/Workspace behavior matches web semantics.

### Phase 03: Validate, polish, and hand off

**Goal:** Prove lifecycle and accessibility on both platforms and record the release evidence.

**Work items:**

- Exercise system back, keyboard, safe areas, reduced motion, cold start, background/foreground, and offline retry.
- Run focused mobile checks and the full repository validation.
- Use the Allies mobile release handoff for build/OTA classification and Nabu synchronization.
- Update `apps/mobile/README.md` and Nabu with version/runtime/build or update metadata only at the meaningful release boundary.

**Impacted systems:** Android/iOS dev builds, `apps/mobile/README.md`, Nabu delivery/spec records.

**Exit criteria:** Both platforms have evidence for the acceptance criteria; native version/build metadata is recorded; rollback is understood and docs are synchronized.

## Acceptance criteria

1. Google sign-in uses the system browser and Cloud-owned callback; no WebView, browser-cookie emulation, or direct Google token exchange exists.
2. PKCE uses a random verifier, unpadded base64url S256 challenge, exact registered redirect, and one-time in-memory state.
3. Only the current opaque refresh token is persisted in SecureStore; access token, verifier, state, code, URLs, logs, analytics, and crash payloads stay out of durable storage.
4. Refresh rotation is serialized; the new token is securely written before the old one is replaced; SecureStore failure never becomes signed-in.
5. Revocation, logout, 401 session invalidation, and uncertain logout clear local credentials, memory, Query caches, and protected navigation.
6. Bootstrap distinguishes checking storage, refreshing, signed-in, signed-out, offline-with-session, and unavailable; the UI never claims signed-in before Cloud validation.
7. Mobile can view and edit the current profile, manage avatar lifecycle through signed object-storage instructions, and load the personal Workspace.
8. Profile/avatar/Workspace requests use the shared typed Cloud boundary and bearer allowlist; object-storage upload receives exact signed headers and no bearer.
9. Loading, canceled, retryable, offline, unauthorized, throttled, provider-unavailable, and privacy-safe error states are explicit on native surfaces.
10. System back, safe areas, keyboard dismissal, screen-reader labels/focus order, touch targets, reduced motion, and narrow iOS/Android layouts are verified.
11. Vitest covers pure PKCE, redirect validation, SecureStore port, refresh coordinator, session reducer, response mapping, profile schema, error policy, query invalidation, and relevant keyboard/back behavior; no broad new test framework is added without evidence.
12. Full validation and real Android/iOS dev-build evidence are recorded, and the release/README/Nabu handoff identifies whether the result is native-build-required or OTA-compatible.

## Validation plan

| Layer | Checks | Evidence required |
| --- | --- | --- |
| Shared contract | `bun install --frozen-lockfile`; `bun run typecheck`; `bun run test:run` | Generated native paths match the accepted OpenAPI snapshot; envelope/error mapping rejects malformed or untrusted fields. |
| Mobile static | `bun --filter mobile lint`; `bun --filter mobile typecheck`; `git diff --check` | Expo SDK 57 config resolves, route groups typecheck, and no native config/secret is accidentally committed. |
| Unit/component | Focused Vitest for PKCE, redirect parser, store, refresh serialization, state transitions, profile schema, mapping, query invalidation, and keyboard/back behavior. | Fixtures cover success, cancel, timeout, replay, 401, 429, 503, offline, SecureStore failure, rotation race, and logout uncertainty. |
| Native smoke | Android and iOS dev builds with staging enabled. | Fresh sign-in, cancel/retry, cold relaunch restore, refresh rotation, background/foreground, revoked session, logout, profile edit, avatar replace/delete, Workspace load, and offline retry. |
| Regression | `bun run lint`; `bun run build:web`; `bun run bundle:mobile` | Existing web onboarding/session behavior remains intact; mobile onboarding remains usable signed out. |

## Risks and mitigations

| Risk | Severity | Mitigation / rollback |
| --- | --- | --- |
| Callback works in Expo Go but fails in a real build | High | Use custom dev builds with exact schemes/claimed links; test cold return and background/foreground. If broken, keep native auth disabled and preserve public onboarding. |
| Refresh rotation race loses the current session | High | Serialize refresh, write the new SecureStore token before replacing memory, and test concurrent 401s. On write failure, fail closed rather than persisting a stale token. |
| Cloud staging is merged but not enabled | Medium | Use fixture/transport tests; show unavailable/retry; do not invent a browser fallback. Enable only after deployment and flag verification. |
| Avatar upload leaks bearer or uses stale signed headers | High | Keep object-storage PUT outside the authenticated API wrapper, send only exact signed headers, and treat expiry/retry as a fresh prepare step. |
| Account data remains in cache after logout/revocation | High | One session-generation cleanup path clears SecureStore, memory, Query cache, and protected routes on every terminal local sign-out. |
| Native dependency/config changes ship as OTA | Medium | Classify release changes. Bump app version and create a new EAS build for native changes; publish OTA only after the compatible runtime exists. |

### Rollback

Turn off native auth at the Cloud flag/config boundary, leave mobile routes behind an unavailable state, clear any locally stored native refresh token during the next app start, and ship a compatible JavaScript update only if the installed runtime supports it. Do not route users through browser-cookie auth as an emergency substitute.

## Documentation and release handoff

After implementation is accepted and released:

- Update `apps/mobile/README.md` with the native auth contract, environment/configuration, app-link setup, secure-storage rules, validation commands, app version/runtime/build metadata, and release history.
- Update the canonical Nabu INT-008/delivery record with contract revision, staging/device evidence, version/runtime/build or OTA metadata, known limitations, and rollback status.
- Use the Allies mobile release handoff skill to classify native versus OTA changes. AuthSession, SecureStore, schemes, app links, native plugins, or native configuration require a new build and app-version/runtime review; UI-only JavaScript changes can use a compatible OTA.
- Do not claim an installed device updates from GitHub alone. A merged UI commit still needs the device owner's EAS update command for the relevant channel.

## Evidence and sources

### Nabu

- `projects/allies/index.md`
- `projects/allies/engineering/specs/interface/INT-008-mobile-google-auth-and-account.md`
- `projects/allies/engineering/specs/interface/AUTH-002-cloud-native-session-contract.md`
- `projects/allies/engineering/specs/interface/INT-007-web-google-auth-and-account.md`
- `projects/allies/engineering/guides/interface-development.md`
- `projects/allies/delivery/tickets/interface/INT-008.md`
- `projects/allies/delivery/now.md`

### Repository

- `AGENTS.md`
- `ENGINEERING_STYLE.md`
- `docs/templates/PLAN_TEMPLATE.md`
- `README.md`
- `apps/mobile/src/app/_layout.tsx`
- `apps/mobile/src/lib/providers/app-providers.tsx`
- `apps/mobile/src/lib/session/session-context.tsx`
- `apps/mobile/app.json`
- `packages/cloud-client/src/client.ts`
- `packages/cloud-client/src/mappers/account.ts`
- `packages/cloud-client/src/transport.ts`
- `packages/cloud-client/openapi/allies-cloud-0.1.0.json`
- `apps/web/lib/session/web-session.ts`
- `apps/web/lib/session/session-context.tsx`
- `apps/web/app/(onboarding)/_components/sign-in.tsx`

## Archive

The accepted portable HTML is synchronized at `docs/plans/int-008-mobile-google-auth-and-account.html`. The `.lavish` copy remains as the editable working artifact for future plan feedback; implementation should begin from this accepted Markdown/HTML pair.
