# Temporary native manual sign-in Plan

## Feature Overview

- Problem: Expo Go cannot complete the claimed-link return used by the accepted
  native Google flow, so Android and iOS testing currently stalls after Google
  authenticates the user.
- Target users: Allies developers and testers using Expo Go while Apple enrollment
  and native app-link setup are pending.
- Source docs/specs: the accepted Nabu `AUTH-002` native session contract and
  `INT-008` mobile handoff; both repositories' `AGENTS.md`,
  `ENGINEERING_STYLE.md`, READMEs, plan templates, tests, and CI; the current
  Cloud native authorization/session code; and the current mobile Google flow.
- Success outcome: A temporary, explicitly selected mode lets the Cloud callback
  show the existing short-lived exchange code for copy/paste into Expo Go. The
  app exchanges it with the initiating attempt's in-memory PKCE verifier and then
  uses the existing native session completion path.

## Plan Hygiene and Evidence Boundaries

This plan uses repository-relative paths and deployment placeholders. It contains
no credentials, live callback URLs, user data, workstation paths, or copied
provider payloads. The manual page must never expose provider credentials, Cloud
access tokens, refresh tokens, user/profile data, or the app PKCE verifier.

## User Stories

1. As an Expo Go tester, I want to copy a short-lived code from the completed
   Google browser page and paste it into Allies, so that I can sign in on Android
   or iOS before claimed links are available.
2. As a tester, I want cancel, expiry, wrong-device paste, retry, and screen exit
   to fail safely, so that an old attempt cannot install a session later.
3. As a maintainer, I want redirect delivery to remain the default and the manual
   path to reuse AUTH-002, so that removing the temporary mode does not disturb
   the production flow.

## Scope

### In Scope

- Add an optional `completion_mode` to the native Google start request, persist it
  on the authorization transaction, and default it to `redirect`.
- Add `manual_code`, which makes the existing Cloud callback return a no-store
  HTML page containing the existing 32-byte URL-safe exchange code, a copy
  control with a selectable fallback, and its existing expiry; callback retries
  do not extend that expiry.
- Preserve Google verification, exact redirect allowlisting, transaction locking,
  PKCE S256 binding, single-use exchange, refresh storage, account loading, and
  onboarding/session continuation.
- Add an explicit mobile `EXPO_PUBLIC_NATIVE_AUTH_COMPLETION_MODE` setting with
  `redirect` as the source-controlled default and `manual_code` for temporary
  Expo Go environments.
- Add a manual code-entry state to the current Google sign-in screen and make
  begin, exchange, cancel, restart, and unmount ownership explicit.
- Publish and pin the additive OpenAPI request/callback response contract.

### Out of Scope

- A device-code protocol, polling endpoint, second exchange-code system, custom
  short-code database, direct mobile Google SDK, embedded WebView, or browser
  cookie transfer.
- Changes to access/refresh token shapes, SecureStore ownership, refresh rotation,
  logout, account/profile/Workspace contracts, or onboarding completion.
- Replacing the claimed HTTPS return path. Manual mode still supplies the same
  exact allowlisted `redirect_uri` as a PKCE exchange binding, but Cloud does not
  navigate to it after the callback.
- Deploying or changing the separate callback/link host, production promotion,
  or removing real-development-build acceptance gates.

### Dependencies and Assumptions

- Cloud native auth is enabled and Google already returns to
  `GET /api/v1/auths/native/callback/google`.
- The existing exchange code is URL-safe, 32 random bytes, single-use, sealed at
  rest, and configured for a 60-second lifetime. The implementation must use the
  configured expiry rather than hardcode 60 seconds in UI logic.
- Only the opaque refresh token remains in SecureStore. State, verifier, pasted
  code, access token, and manual form state remain in memory.
- The current `NativeSessionAdapter.completeSignIn` path remains the session
  authority, but it needs cancellable, generation-safe completion before manual
  retry and unmount behavior is accepted.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `backend/auths/services/native_authorization.py` | `begin_native_sign_in` | `(..., completion_mode: NativeCompletionMode = REDIRECT) -> NativeAuthorizationStart` | Accept only `redirect` or `manual_code`; preserve redirect, state, and S256 checks | Existing authorization URL and expiry | Persists the selected mode with the transaction |
| `backend/auths/services/native_authorization.py` | `complete_native_callback` | `(provider, provider_state, provider_code?, provider_error?) -> NativeCallbackResult` | Existing provider/state/claim/expiry checks | Evolve the existing redirect value into one tagged redirect/manual result carrying the existing code and absolute expiry | Reuses the single success/failure/terminal helpers and creates at most one existing `NativeExchangeCode`; terminal repeats never mint or extend it |
| `packages/cloud-client/src/native-auth.ts` | `beginGoogleSignIn` | `(input: NativeGoogleSignInInput, signal?) -> Promise<NativeAuthorizationStart>` | `completionMode?: "redirect" \| "manual_code"`; client default is `redirect` | Existing start result | Sends `completion_mode`; no credential persistence |
| `apps/mobile/src/features/auth/google-sign-in.ts` | `createGoogleSignInFlow` | `createGoogleSignInFlow(options): { start(); submitManualCode(code); cancel() }` | Owns only request-local verifier/state/code and UI lifetime; trims and validates a non-empty bounded URL-safe pasted code | Signed-in, canceled, failed, or waiting-for-code outcome | Opens the manual URL through `Linking.openURL`, retains the attempt when the user returns to the app, and hands exchange/session authority to the adapter |
| `apps/mobile/src/lib/session/native-session-adapter.ts` | `completeSignIn` | `(input, signal?) -> Promise<NativeSessionState>` | Existing exchange input plus abort signal; adapter/provider-wide sign-in generation | Existing session state | Serializes non-cancelable SecureStore commit/cleanup across flow instances; stale work neither survives nor clears a newer session |

### API and Transport Contracts

| Consumer | Method and path | Authentication | Request | Success | Errors and retry |
| --- | --- | --- | --- | --- | --- |
| Mobile Cloud client | `POST /api/v1/auths/native/sign-in/google` | Public; existing limits; no bearer/cookies | Existing fields plus optional `completion_mode: "redirect" \| "manual_code"` | Existing JSON start envelope | Unknown mode follows the existing schema-validation `422` response; a retry creates a fresh attempt |
| Google/browser | `GET /api/v1/auths/native/callback/google` | Existing provider callback | Existing provider `code`, `state`, or error | `redirect`: existing `303`; `manual_code`: `200 text/html` | Existing invalid/in-progress/throttled responses remain; known manual terminal states render a safe failure page |
| Mobile Cloud client | `POST /api/v1/auths/native/token` | Public; existing limits; no bearer/cookies | Existing code, original verifier, and same redirect URI | Existing native token envelope | Wrong verifier/device/redirect and expiry fail without a session; replay remains `409 exchange_replayed` |

Representative additive start request:

```json
{
  "redirect_uri": "https://<registered-app-return>/auth/return",
  "code_challenge": "<43-character-S256-challenge>",
  "code_challenge_method": "S256",
  "state": "<random-app-state>",
  "completion_mode": "manual_code"
}
```

The JSON success response is unchanged. In `manual_code`, the callback returns
semantic HTML with a read-only/selectable code control, a `Copy sign-in code`
button, absolute/remaining expiry guidance, and restart instructions. A tiny
nonce-protected inline clipboard script powers the button; the selectable field
remains the fallback when clipboard access is denied. The response sends
`Cache-Control: no-store`,
`Pragma: no-cache`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options:
nosniff`, and a restrictive CSP (`default-src 'none'; style-src 'unsafe-inline';
script-src 'nonce-<per-response-nonce>'; base-uri 'none'; form-action 'none';
frame-ancestors 'none'`). It has no `Location` header, external assets, or
analytics. The raw exchange code appears only in the HTTPS response body.
Google’s provider code remains in the incoming callback URL as required by the
provider protocol.

### Schema and Data Shapes

| Schema/model | Location | Change | Invariants and compatibility |
| --- | --- | --- | --- |
| `NativeSignInRequest` | `backend/auths/api/schemas.py` | Add `completion_mode: Literal["redirect", "manual_code"] = "redirect"` | Omitted by old clients and accepted as redirect |
| `NativeCompletionMode` | `backend/auths/models.py` | Text choices `redirect`, `manual_code` | Single accepted vocabulary across API, model, service, and OpenAPI |
| `NativeAuthorizationTransaction` | `backend/auths/models.py` + additive migration | Add non-null mode with a persistent database default (`db_default`) of `redirect` | Mixed-version Cloud processes and old inserts remain safe; mode is fixed at start and read under the existing callback lock |
| `NativeGoogleSignInInput` | `packages/cloud-client/src/native-auth.ts` | Add optional `completionMode` | Wire mapper emits snake_case; runtime parser rejects other values |
| `MobileEnvironment` | `apps/mobile/src/lib/env.ts` | Add `nativeAuthCompletionMode` | Missing/blank defaults to `redirect`; invalid value fails closed to configuration unavailable |

No exchange/session schema changes. The existing redirect result becomes one
internal tagged callback result so the HTTP controller owns HTML rendering and
headers without a parallel manual callback lifecycle.

### Frontend Interaction Shapes

| UI entry point | State transitions | Behavior and recovery |
| --- | --- | --- |
| Google action in `apps/mobile/src/app/sign-in.tsx` | `idle -> opening-browser -> waiting-for-code` in manual mode | Starts a fresh PKCE attempt, opens the external URL with `Linking.openURL`, and exposes code entry without waiting for an AuthSession return or app link |
| Manual code form | `waiting-for-code -> exchanging -> signed-in \| failed` | Paste is held in component/flow memory, submitted once, cleared after every terminal result, and never logged or persisted |
| Browser dismissal / app resume | `waiting-for-code -> waiting-for-code` | Returning from Android Custom Tabs or iOS Safari is expected after copying; it keeps the attempt and pasted-code form active until expiry or explicit cancellation |
| Explicit cancel/navigation/unmount | any active manual state -> `canceled` | Abort begin/exchange where possible, invalidate the provider/adapter generation, clear code/verifier/state, and prevent late state/session publication |
| Retry | terminal failure -> fresh `opening-browser` | Waits for previous cleanup, creates a new state/verifier, and never reuses the old code |
| Redirect mode | Existing opening/waiting/app-link/exchange states | Existing behavior and callback validation remain unchanged |

The successful manual exchange calls the same session completion API as redirect
mode. Existing validated `returnTo` navigation and `/allies/new/complete`
onboarding continuation remain authoritative.

## Phases

### Phase 1 - Add the Cloud delivery mode

- Goal: Let the existing callback deliver the existing code as safe HTML.
- Work items: Add the request enum and transaction field/migration; carry the mode
  through begin/terminal callback handling; render the manual success/error page;
  document 200/303 responses in OpenAPI; cover headers, escaping, expiry, replay,
  wrong verifier/device, and redirect compatibility.
- Impacted files/systems: `backend/auths/api/{schemas,native}.py`,
  `backend/auths/{models,services/native_authorization}.py`, one auth migration,
  auth/OpenAPI tests, and the native integration handoff.
- Exit criteria: Redirect clients behave unchanged, while a manual transaction
  renders the same exchange code until consumption/expiry and never mints a
  second code or session.

### Phase 2 - Publish and consume the additive Interface contract

- Goal: Give mobile one typed switch and a safe copy/paste experience without
  changing token/session APIs.
- Work items: Add `completionMode` to the shared client input and request mapping,
  test omission/default/manual wire shapes, regenerate the pinned OpenAPI types,
  update the mobile environment parser/example, split redirect/manual delivery in
  the existing flow, add code entry/cancel/retry UI, use `Linking.openURL`, thread
  abort through session completion, and make the adapter the sole serialized
  sign-in generation/commit authority across component remounts.
- Impacted files/systems: `packages/cloud-client/src/native-auth.ts`, its tests and
  generated schema; `apps/mobile/src/lib/env.ts`, environment tests and example;
  Google flow/hook/screen; session adapter/context; focused auth/session/UI tests;
  and mobile documentation.
- Exit criteria: Old callers redirect; configured Expo Go clients request manual;
  invalid config fails closed; browser return, success, explicit cancel, restart,
  expiry, wrong-device paste, unmount/remount, and late exchange/storage completion
  are truthful; stale work neither survives nor clears a newer session.

### Release order - Cloud first, then temporary mobile enablement

Land the persistent database default and Cloud behavior, migrate and deploy Cloud,
then smoke an omitted-field 303 redirect and an explicit `manual_code` 200 page.
Only after both pass should the intended Expo Go staging environment set
`EXPO_PUBLIC_NATIVE_AUTH_COMPLETION_MODE=manual_code`. An old backend may ignore an
additive request field and still return 303, so mobile manual enablement must never
precede Cloud proof. Android/iOS live smoke evidence is a post-staging-deploy
acceptance gate. This plan grants no merge or deployment authority.
Implementation and delivery therefore stop at validated, reviewable Cloud and
Interface changes/PRs. Cloud merge, migration/deployment, staging smoke, and the
staging mobile environment mutation form a separately authorized post-PR gate;
the user approves that gate only after reviewing the concrete validated result.

## Acceptance Criteria

1. Omitting `completion_mode` preserves the existing 303 app redirect behavior.
2. A `manual_code` transaction returns a no-store, CSP-restricted HTML page from
   the existing Cloud callback with the existing exchange code only in the body.
3. Callback replay never extends the original expiry or creates another exchange
   code; consumed/expired attempts show restart guidance without revealing a code.
4. The pasted code succeeds only with the initiating attempt's verifier and same
   exact redirect URI. Wrong-device/verifier/redirect, expiry, and second exchange
   do not issue a session.
5. Mobile exposes manual mode only through the explicit environment setting;
   source-controlled omission continues to select redirect mode.
6. The pasted code, verifier, state, and access token remain in memory; only the
   existing opaque refresh token is persisted in SecureStore after valid exchange.
7. Returning from or dismissing the external browser keeps an unexpired manual
   attempt in `waiting-for-code`; explicit cancel, navigation, or unmount
   invalidates it. Late begin/exchange/storage completion cannot publish stale UI,
   leave a stale token, or clear a newer session after remount/retry.
8. A successful manual exchange uses the existing session/account completion and
   validated post-sign-in/onboarding navigation.
9. Cloud OpenAPI, Interface pinned types, docs, focused tests, and full repository
   checks agree on the additive contract. Cloud is migrated/deployed and both modes
   are smoked before the temporary mobile environment is enabled; manual Android
   and iOS Expo Go evidence is then recorded as the post-staging-deploy gate. Merge,
   deploy, smoke, and environment mutation wait for separate user approval after
   the validated Cloud and Interface changes/PRs are ready.

## Backend Considerations

### Query Optimization Plan

- Hotspot: the existing callback transaction lock and one-to-one exchange lookup.
- Query shape: reuse current `select_for_update` and indexed state digest; read the
  mode from the locked row. Do not add polling or page-refresh queries.
- Expected change: one column read, no extra query on the successful callback.
- Measurement: preserve focused callback query behavior and run the PostgreSQL
  concurrency job that covers callback claim/finalization races.

### N+1 Prevention

The flow handles one transaction and one exchange row. No collection relation or
new prefetch path is introduced.

### Detailed Unit Test Cases

- Happy path: manual start persists mode; callback returns code page; initiating
  verifier exchanges once; redirect mode remains 303.
- Validation: omitted/default/invalid mode with the existing `422` schema error,
  HTML escaping, CSP nonce/header agreement, clipboard fallback, safe provider
  failure, exact redirect mismatch, malformed pasted code, and no secret-bearing
  headers.
- Concurrency/retry: duplicate callback returns the same unexpired code without
  extending expiry; callback claim races remain one-winner; exchange replay fails;
  migration/database-default tests cover inserts from mixed Cloud versions.
- Security: wrong verifier/device does not consume the rightful code; consumed and
  expired code pages reveal no code; all manual pages carry required headers.

## Frontend Considerations

### Data Path

User -> mobile Google action -> typed Cloud start with `manual_code` -> system
browser -> Google -> existing Cloud callback -> backend HTML code page -> user
pastes code -> existing token exchange with in-memory verifier -> existing session
adapter/SecureStore/account load -> validated mobile destination.

### State Management Considerations

- The flow object owns only the current request's verifier, state, abort controller,
  pasted code, and UI lifetime. The hook exposes only UI-safe state and actions.
  The adapter is the sole durable active-sign-in generation and serialized commit /
  cleanup authority so it survives screen and hook replacement.
- Session adapter remains the only token owner. Manual UI cannot call token APIs
  directly or install account state.
- A restart begins only after the provider/adapter has serialized the previous
  attempt's non-cancelable SecureStore commit or cleanup. Generation and abort
  checks occur before durable write and state publication. A delayed stale write
  followed by immediate unmount/remount/retry must neither survive nor erase the
  newer session.
- No polling, cache entry, Zustand state, AsyncStorage value, or analytics event is
  added for the manual code.

## Test Plan

- Cloud focused: `make test APP=auths/tests/test_native_session.py` and callback /
  OpenAPI tests; `make check`; `make lint`.
- Cloud full/CI: `uv run pytest`, coverage at least the existing 90% auth/workspace
  gate, `uv run ruff format --check .`, migrations, and `uv run pytest -m
  postgresql` in the CI PostgreSQL service.
- Interface focused: native auth client wire tests; Google flow, environment,
  session adapter/context, parser, and sign-in UI tests.
- Interface full: `bun run cloud:check`, `bun run typecheck`, `bun run test:run`,
  `bun run lint`, `bun run build:web`, `bun run bundle:mobile`, and
  `git diff --check` in both repositories.
- Rollout: after Cloud migration/deployment, smoke omitted-field redirect (303)
  and explicit manual callback (200) before enabling the mobile manual environment.
- Manual post-deploy gate: on Android Custom Tabs and iOS Safari through Expo Go,
  prove return/dismiss keeps `waiting-for-code`, success, explicit cancel before
  paste, expired code, wrong-device paste, duplicate paste, fresh retry, unmount
  during delayed exchange/storage followed by immediate remount/retry, and
  successful continuation.

## Risks and Mitigations

- Risk: A copied code is visible in browser history/screen capture or shared with a
  different device. Mitigation: response body only, no-store/no-referrer/CSP,
  existing 60-second configured expiry, single use, exact redirect binding, and
  PKCE verifier binding. A copied code alone cannot create a session.
- Risk: Cancellation races with token persistence across a hook remount.
  Mitigation: provider/adapter-wide generation, serialized non-cancelable
  SecureStore commit/cleanup, cleanup-before-restart, and a delayed-write plus
  immediate remount/retry regression test.
- Risk: A rolling deploy mixes model code that knows the new field with processes
  that do not. Mitigation: a persistent database default of `redirect`, Cloud-first
  migrate/deploy, and both-mode smoke proof before mobile enablement.
- Risk: Temporary behavior becomes accidental production behavior. Mitigation:
  explicit mobile environment selection, server default `redirect`, docs that call
  the mode temporary, and no production setting change in source.
- Rollback: Set the mobile completion setting to `redirect` (or omit it) to restore
  the existing app-link flow immediately. The additive Cloud field can remain
  dormant; later removal deletes manual UI/rendering and the transaction column
  only after no deployed client requests `manual_code`.

## Resolved Decisions

- Use the existing Cloud callback to render the manual page; do not depend on the
  separate hosted link callback.
- Keep the current random exchange code and token endpoint; do not invent a short
  code or polling protocol.
- Persist delivery mode per transaction so callback and replay behavior cannot be
  changed by later environment configuration.
- Keep `redirect_uri` in manual start/exchange for exact allowlist and exchange
  binding even though the callback does not navigate to it.
- Ship the mode as a temporary, opt-in Expo setting with redirect as the compatible
  default.
- Use `Linking.openURL` for manual delivery; browser return is not cancellation and
  only explicit cancel/navigation/unmount invalidates the attempt.
- Roll out Cloud migration and callback behavior before the mobile manual setting;
  real-device evidence follows staging deployment.
