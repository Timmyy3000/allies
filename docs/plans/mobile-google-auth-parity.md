# Mobile Google sign-in parity Plan

## Feature Overview

- Problem: The mobile sign-in route is a placeholder and does not follow the
  existing web account-access flow.
- Target users: Allies mobile users who need to sign in before using protected
  account surfaces.
- Source docs/specs: `ENGINEERING_STYLE.md`, the mobile app instructions,
  `apps/web/app/sign-in/sign-in-client.tsx`,
  `apps/web/app/sign-in/sign-in.module.css`, the web auth-return route, and the
  approved Allies auth contract in the project notes.
- Success outcome: Mobile presents the same Google-only passwordless sign-in
  action as web, starts the native PKCE flow, restores the session safely, and
  returns the user to a validated protected route.

## Plan Hygiene and Evidence Boundaries

This plan uses repository-relative paths only. It contains no credentials,
private URLs, workstation paths, user records, or live provider payloads. The
worktree already contains unrelated onboarding edits and deletions; those are
out of scope and must remain intact.

## User Stories

1. As a mobile user, I want one clear Google sign-in action, so that I can
   access Allies without a second password system.
2. As a mobile user, I want the browser sign-in to return safely to the app,
   so that a canceled, stale, or malformed callback cannot sign me in or send
   me to an unsafe route.
3. As a maintainer, I want mobile to reuse the existing Cloud/session
   contracts, so that web and mobile keep the same account boundary.

## Scope

### In Scope

- Replace the mobile placeholder with the web-equivalent Google-only screen.
- Reconcile the existing mobile PKCE, browser, callback, and native session
  helpers with the current dirty worktree.
- Restore the mobile session route guard needed for protected-route redirects.
- Preserve a validated `returnTo` target and use `/allies` as the safe default.
- Restrict `returnTo` to current `/allies`, `/allies/new`, and one-segment
  `/allies/<allyId>` routes; reject deleted nested route families.
- Cover loading, cancellation, unavailable, invalid-return, and flow-failure
  states with focused tests.

### Out of Scope

- Username/password fields, password creation, or a separate mobile account
  system.
- Changes to Cloud auth endpoints, token shapes, secure storage, onboarding
  behavior, Ally artwork, or unrelated deleted routes.
- New dependencies, a new auth abstraction, or a native provider SDK.
- Changes to the web implementation.

### Dependencies and Assumptions

- `@allies/cloud-client` already exposes the native Google start and code
  exchange contract.
- The configured mobile native auth return URI is supplied by the existing
  environment/client boundary and is unavailable until the native build is
  registered correctly.
- Expo SDK 57 APIs already used by the repository remain the supported runtime.
- `MOCK_MODE` may continue to control local product data, but it must not block
  creation of the real Cloud/session client when valid environment values are
  configured.
- Session guarding is enabled exactly when the Cloud client exists. A build
  without a Cloud client stays in the current mock walkthrough; a configured
  build guards protected routes even while mock product data is enabled.
- Native device proof depends on the exact HTTPS return URI being allowlisted by
  Cloud, its Android App Link and iOS Universal Link association being hosted,
  and a fresh native build containing those generated entitlements. This is a
  release/device prerequisite, not a new auth implementation.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `apps/mobile/src/features/auth/google-sign-in.ts` | `createGoogleSignInFlow` | `createGoogleSignInFlow(options): { start(): Promise<GoogleSignInOutcome> }` | Requires the configured native redirect URI; generates one in-memory PKCE attempt and validates callback origin/path/state | Signed-in, canceled, or failed outcome | Opens the system browser, listens for the app return, exchanges the code, reports named statuses, and clears the active-flow guard |
| `apps/mobile/src/features/auth/use-google-sign-in.ts` | `useGoogleSignIn` | `useGoogleSignIn(): { isAvailable, isBusy, outcome, start, status }` | Derives availability from the native session client and registered redirect URI | UI-safe flow state | Owns screen-local status/outcome state; does not store tokens |
| `apps/mobile/src/lib/session/session-route.ts` | `getSessionRouteAction` | `getSessionRouteAction(status, pathname, returnTo?): SessionRouteAction \| null` | Treats navigation input as untrusted; only protected paths are valid signed-in destinations | Replace action or `null` | Redirects signed-out users to sign-in and signed-in users away from auth entry routes |

### API and Transport Contracts

| Consumer | Method and path / event | Authentication and authorization | Request schema | Success response schema | Error responses / retry semantics |
| --- | --- | --- | --- | --- | --- |
| Mobile native auth client | `POST /api/v1/auths/native/sign-in/google` | Public start endpoint with server-side provider/state validation | `redirect_uri`, `code_challenge`, `code_challenge_method: "S256"`, `state` | Authorization URL plus server flow metadata | Existing Cloud error kinds map to unavailable or flow failure; no blind retry of a provider flow |
| Mobile native auth client | `POST /api/v1/auths/native/token` | Exchanges the one-time provider code | `grant_type: "authorization_code"`, `code`, `code_verifier`, `redirect_uri` | Native session token pair | Existing unauthorized, transient, storage, and auth outcomes remain owned by the session adapter |

The mobile flow must use the existing typed Cloud client. It must not call
Foundry or construct a second transport adapter.

### Schema and Data Shapes

| Schema / model | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- |
| `GoogleSignInOutcome` | `apps/mobile/src/features/auth/google-sign-in.ts` | `signed-in`, `canceled`, or `failed` with a bounded reason | Required status; failure reason is one of `invalid-return`, `flow-failed`, `unavailable`, or `already-in-progress` | A callback is accepted only when redirect URI and PKCE state match | Existing shape; UI-only wording may align with web |
| `NativeSessionState` | `apps/mobile/src/lib/session/native-session-adapter.ts` | Checking, refreshing, signed-out, signed-in, offline-with-session, unavailable | Existing nullable account only for signed-in | Token persistence stays inside the adapter and secure store | No schema change |

### Frontend Interaction Shapes

| UI entry point | Hook / action signature | State shape and transitions | API input/output mapping | Loading, error, empty, and permission behavior |
| --- | --- | --- | --- | --- |
| `apps/mobile/src/app/sign-in.tsx` | Press Google button -> `signIn.start()` | `idle -> opening-browser -> waiting-for-return -> exchanging -> idle`; outcome may be signed-in, canceled, or failed | Button action -> native client start -> callback validation -> code exchange -> session state | Button shows `Continue with Google`, then `Opening Google…`; status shows secure-opening copy; errors expose retryable web-equivalent messages |
| `apps/mobile/src/app/auth/return.tsx` | Deep-link URL -> `deliverNativeAuthReturn(url)` | Waiting flow consumes one callback; no active flow shows retry UI | App link -> in-memory listener; no token is accepted in the route component | Stale/missing callbacks show a safe retry action and never claim success |
| Root route guard | Session state + current path -> `getSessionRouteAction` | Checking/refreshing hold; signed-out protects private paths; signed-in leaves auth entry | Session state -> Expo Router replace | Safe `/allies` fallback; mock mode keeps current local preview behavior |

## Phases

### Phase 1 - Restore and reconcile the existing native auth path

- Goal: Reconnect the already-defined Cloud/session contracts without restoring
  unrelated mobile routes.
- Work items:
  - Restore only the native PKCE, auth-return listener, Google flow hook, auth
    return route, and session-route guard files required by the flow.
  - Reconcile imports and providers with the current mobile worktree.
  - Keep mock product content available while allowing configured real auth to
    initialize independently of `MOCK_MODE`.
  - Enable route guarding when `session.client` exists; skip it only for the
    client-less mock build.
  - Keep callback redirect/state validation and single-flight behavior intact.
- Impacted files/systems: `apps/mobile/src/features/auth/*`,
  `apps/mobile/src/app/auth/return.tsx`, `apps/mobile/src/app/_layout.tsx`,
  `apps/mobile/src/lib/session/session-route.ts`,
  `apps/mobile/src/lib/providers/app-providers.tsx`, and the affected README
  section.
- Exit criteria: The real session path compiles and the existing native auth
  and route tests can run without restoring out-of-scope screens. The native
  link/build prerequisite is recorded for device verification.

### Phase 2 - Match the web sign-in surface and verify behavior

- Goal: Make mobile sign-in visually and behaviorally equivalent to web.
- Work items:
  - Render one centered orange pill with the Google mark and exact web copy.
  - Remove username/password controls and create-account branching from the
    mobile sign-in surface.
  - Map mobile outcomes to web-equivalent cancellation, unavailable,
    invalid-return, and generic failure messages.
  - Add focused UI/state coverage and run mobile validation.
- Impacted files/systems: `apps/mobile/src/app/sign-in.tsx`, the focused auth
  tests, and only the native auth files needed to support the route.
- Exit criteria: Google-only sign-in is usable, accessible, retryable, and
  protected routes redirect correctly in a real configured build.

## Acceptance Criteria

1. Mobile sign-in shows only the web-equivalent `Continue with Google` action;
   no username, password, or create-account form is shown.
2. Pressing the action enters a disabled `Opening Google…` state and exposes
   `Opening a secure Google sign-in…` as live status text.
3. Native browser/app-link returns require the configured redirect URI and the
   exact PKCE state before code exchange.
4. Canceled, unavailable, invalid-return, and generic flow failures show clear
   retryable messages and never report a signed-in state.
5. Successful exchange persists and exposes the session through the existing
   native session provider, then routes to a validated `returnTo` or `/allies`.
6. Signed-out users cannot enter protected mobile routes without sign-in;
   mock onboarding behavior remains unchanged.
7. Configured authentication can initialize while mock product data remains
   available for the current walkthrough.
8. Validated return targets exclude deleted nested route families.
9. No unrelated onboarding or route deletion is restored or overwritten.
10. A client-less build keeps the mock walkthrough, while a configured client
    enables session guarding and real Google access.
11. Focused auth tests, mobile lint, mobile typecheck, the relevant full test
   command, and `git diff --check` pass.

## Backend Considerations (if applicable)

No backend code or contract is changed. The client uses the existing versioned
native Google start and exchange endpoints. Cloud remains responsible for
provider identity, authorization, token issuance, and account truth.

### Query Optimization Plan

Not applicable.

### N+1 Prevention

Not applicable.

### Detailed Unit Test Cases

- Happy path: create PKCE attempt, start Google, accept a valid callback, and
  exchange the code once.
- Validation: reject malformed URLs, wrong redirect origin/path, missing code,
  and mismatched state.
- Flow state: prevent a second concurrent start and dispose the return listener.
- Failure path: map cancellation, transient Cloud errors, invalid return, and
  generic errors to bounded outcomes.
- Route behavior: hold during checking, protect private routes while signed
  out, and use only safe signed-in return targets.

## Frontend Considerations (if applicable)

### Data Path

- User action entry: Google button on `/sign-in`.
- Client route/component: `apps/mobile/src/app/sign-in.tsx`.
- Client API route/proxy: existing `NativeAuthClient` implementation.
- Backend endpoint: existing Cloud native Google start/exchange contract.
- Response -> UI mapping: native session outcome -> web-equivalent status or
  error copy.
- Error/loading/retry path: local hook state, disabled button while busy, and
  a fresh button press after a failure.

### State Management Considerations

- State ownership: the sign-in hook owns transient flow UI state; the native
  session provider owns authenticated account/session state; the adapter owns
  tokens and secure storage; the mock provider owns only local walkthrough
  content.
- Source of truth: Cloud/session adapter for identity; `returnTo` is derived
  navigation input and is revalidated before use.
- Caching/invalidation: existing session provider/query invalidation only; no
  new cache.
- Concurrency: one active Google flow at a time; callback listener is disposed
  after either browser completion or app-link completion.
- Configuration boundary: `AppProviders` creates the client from the existing
  environment regardless of `MOCK_MODE`; the route guard skips only when that
  client is absent. The generated platform links are verified at native-build
  time from the exact configured HTTPS return URI.

## Test Plan

- Unit tests: PKCE/callback parsing, Google flow outcomes, session route rules,
  and sign-in UI states.
- Integration/API tests: retain the existing typed Cloud-client native-auth
  tests; do not add a duplicate HTTP client.
- Regression checks: current mobile onboarding, session provider, and cloud
  client tests.
- Manual verification checklist:
  - Open `/sign-in` in the configured native build and confirm the single
    orange Google action matches web spacing and copy.
  - Start and cancel Google sign-in; confirm the button recovers and the error
    is retryable.
  - Complete a valid sign-in and confirm the app reaches the safe destination.
  - Open a protected route while signed out and confirm the `returnTo` path is
    preserved only when safe.
  - Before device proof, verify Cloud redirect allowlisting, hosted Android
    App Link/iOS Universal Link association, and a fresh binary with the
    generated link entitlements.
- Commands:
  - `bun run test:run -- apps/mobile/src/features/auth apps/mobile/src/lib/session`
  - `bun --filter mobile typecheck`
  - `bun run lint:mobile`
  - `bun run test:run`
  - `git diff --check`

## Risks and Mitigations

- Risk: Restoring the old account form could contradict the web contract.
  Mitigation: keep the mobile route Google-only and restore only native flow
  primitives.
- Risk: A callback can be stale, malicious, or delivered twice. Mitigation:
  validate URI/state/code, allow one active flow, and dispose listeners.
- Risk: The native redirect URI is missing in a development build. Mitigation:
  disable the action with an explicit configuration message; do not fabricate a
  redirect URI.
- Risk: Existing dirty onboarding work is overwritten. Mitigation: patch only
  focused paths and inspect the exact final diff/status.
- Risk: A browser or network failure leaves the UI stuck. Mitigation: reset
  the flow to idle in `finally` and expose a retryable error.
- Rollback/fallback: revert only the focused auth files; no persisted data or
  Cloud schema changes are introduced.
