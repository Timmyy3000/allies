# AUTH-002 Cloud Native Session Contract Plan

## Status

- Type: feature
- Planning worker: Sol-high (`gpt-5.6-sol` with `high` reasoning)
- Planning worker source: explicit user instruction on 2026-08-20
- Implementation delegation: always
- Delegation source: explicit user instruction and repository default
- Review worker: Terra-high (`gpt-5.6-terra` with `high` reasoning)
- Review worker source: explicit user instruction on 2026-08-20 and `docs/plans/kickoff.yaml`
- Implementation worker: personal named agent `luna_max`
- Implementation worker source: explicit user instruction and repository `AGENTS.md`
- Planning mode: full
- Planning mode reason: authentication, token rotation, redirect handling, migrations, and a cross-repository public contract create material security and compatibility risk
- Worktree manager: Forest
- Branch: `ft/auth-002-native-session-contract`
- Worktree path: `C:\Users\ASUS\Desktop\projects\allies-cloud\.forest\worktrees\ft\auth-002-native-session-contract`
- Task workspace: `C:\Users\ASUS\Desktop\projects\allies-cloud\.forest\worktrees\ft\auth-002-native-session-contract\docs\plans`
- Kickoff configuration: `C:\Users\ASUS\Desktop\projects\allies-cloud\.forest\worktrees\ft\auth-002-native-session-contract\docs\plans\kickoff.yaml`
- Created: 2026-08-20
- Target date: not specified
- Current phase: implementation complete; local validation passed; pull-request
  handoff in progress
- Change boundary: Cloud AUTH-002 application code and tests changed; mobile,
  Foundry, deployment consoles, provider registration, and Nabu are unchanged
- Native enablement status: disabled until owner acceptance, Railway edge-identity
  proof, exact callback registration, shared-cache proof, and migration proof are
  complete

## Objective

Publish a secure Cloud contract that lets the Expo mobile app use Google sign-in
through the system browser. The app must exchange a short-lived, one-time Cloud
code for a native Cloud session. It must then rotate, restore, and revoke that
session without browser cookies, provider tokens, or a client secret in the
mobile app.

The work extends the implemented AUTH-001 identity and session foundation. It
does not replace the browser session contract. It must give INT-008 a complete,
versioned OpenAPI contract and clear failure behavior.

## Context

AUTH-001 already provides the Cloud principal, Google identity resolution, a
ten-minute access JWT, a rotating opaque refresh token, refresh-family reuse
detection, logout, audit events, rate limits, profile APIs, and owner-only
Workspace access. These parts are implemented in `backend/auths/` and
`backend/workspaces/`.

The browser flow binds its callback to a CSRF value and an HTTP-only flow
cookie. A native app cannot safely copy that cookie flow. The Interface mobile
session provider therefore remains in the explicit
`unavailable:native-session-contract-pending` state.

The native flow needs two separate trust boundaries:

1. Cloud acts as the confidential Google relying party. Google returns to an
   exact Cloud HTTPS callback. Provider tokens stay in Cloud memory.
2. The mobile app acts as a public Cloud client. It receives only a one-time
   Cloud code and proves possession of its PKCE verifier at the Cloud token
   endpoint.

Nabu accepts AUTH-002 as a feature specification, but it marks some protocol
choices as proposed. The user accepted the contract and risk decisions listed
below. Exact environment-specific redirect and provider setup remains deferred;
native auth stays disabled until that setup and its proof are complete.

## Feature Overview

- Problem: The implemented Cloud contract supports browser cookies only. The
  Expo client has no safe native sign-in, session restore, refresh, or logout
  contract.
- Target users: People who use Allies on iOS or Android, Interface Mobile
  engineers, Cloud engineers, and operators who investigate authentication
  failures.
- Source docs/specs: Nabu `AUTH-002`, `INT-008`, `AUTH-001`, `EPIC-00`, RFC
  8252, RFC 9700, Google OAuth guidance, and Expo SDK 57 browser and linking
  guidance.
- Success outcome: Cloud publishes an additive OpenAPI contract that INT-008
  can consume without invented fields, browser-cookie emulation, provider
  credentials, or hidden Cloud knowledge.

## User Stories

1. As a mobile user, I want Google sign-in to use the system browser and return
   to Allies, so that the app cannot inspect my Google credentials or browser
   cookies.
2. As a returning mobile user, I want the app to restore and rotate my Cloud
   session, so that I do not sign in on every launch.
3. As a user, I want logout, expiry, cancellation, and revocation to have clear
   results, so that the app does not show a false signed-in state.
4. As an operator, I want safe audit records for each native auth stage, so that
   I can diagnose failures without seeing codes, tokens, claims, email, or
   redirect query values.
5. As an Interface engineer, I want a pinned OpenAPI contract with examples and
   stable errors, so that INT-008 does not guess Cloud behavior.

## Scope

### In Scope

- Google sign-in through an external system browser.
- Authorization code exchange with PKCE S256 between the mobile app and Cloud.
- An exact redirect URI allowlist. Production uses claimed HTTPS app links or
  universal links. Development can use exact registered custom schemes after
  owner approval.
- A separate, short-lived native authorization transaction that does not use
  the browser flow cookie.
- A short-lived, hashed, single-use Cloud exchange code. The app redirect
  contains only that code, the app state, or safe error fields.
- A short-lived bearer access JWT and a rotating opaque refresh credential.
- Refresh-token hashing, one-winner rotation, reuse detection, family
  revocation, expiry, and idempotent logout.
- Strict support for native bearer access on existing account, profile, avatar,
  and Workspace endpoints.
- Additive models, migrations, cleanup, configuration, OpenAPI publication,
  rate limits, audit events, redaction, unit tests, API tests, security tests,
  and PostgreSQL concurrency tests.
- A versioned Interface handoff that unblocks INT-008 after owner acceptance and
  staging publication.

### Out of Scope

- Foundry, Hermes, Fly, Ally, runtime, execution, gateway, conversation, or
  managed-conversation work.
- Pre-auth state, account claims, pre-auth Ally transfer, or waitlist changes.
- Direct Google tokens in Interface, a Google client secret in the mobile
  binary, embedded WebViews, or browser cookie copying.
- Device attestation, DPoP, mTLS, MFA, passkeys, biometrics, push approval,
  account linking UI, multiple mobile accounts, or a general OAuth server.
- Remote session-list UI, account recovery UI, mobile screens, SecureStore
  implementation, or INT-008 implementation.
- A new observability platform or a database audit-log product.
- Changes to Nabu in this planning worker.

### Dependencies and Assumptions

- AUTH-001 remains authoritative for identity resolution, account bootstrap,
  access JWT validation, refresh-family semantics, and Workspace ownership.
- Google remains the only native provider for this ticket.
- Cloud remains the Google confidential client and identity owner. Mobile is a
  public Cloud client and has no client secret.
- PostgreSQL is the deployment database and the required concurrency proof.
  SQLite remains a local development path.
- Redis or the configured shared Django cache remains available for production
  rate limits.
- Railway public networking supplies `X-Real-IP` as the remote client address.
  AUTH-002 treats that header as trusted only after staging proves that the edge
  overwrites client input and that the service has no public route around the
  edge. Native auth stays disabled if either condition is false or unproved.
- The current Cloud access lifetime is ten minutes. The current refresh limits
  are 14 days idle and 30 days absolute.
- Interface will keep the access token in memory when practical. It will keep
  only the opaque Cloud refresh token in Expo SecureStore. Credentials do not
  enter Zustand, TanStack Query, AsyncStorage, analytics, or ordinary files.
- The Cloud contract lands and is published before INT-008 starts its consumer
  implementation.
- AUTH-002 ends with Cloud staging publication, deployment-owned app-link and
  Google-registration evidence, and the Interface-owned contract-only proof.
  INT-008 owns iOS and Android device lifecycle smoke proof for callback,
  restore, refresh, revocation, and logout as its acceptance evidence.
- Cloud and Interface owners must accept the decision register before
  implementation starts.

## Contract and Shape Definitions

### Decision Register

All rows are proposed. Owner acceptance changes them from proposed to accepted.

| Decision | Recommendation | Why | Required owners |
| --- | --- | --- | --- |
| Native browser | Use the external system browser. Do not use an embedded WebView. | This follows native OAuth best practice and keeps browser credentials outside the app. | Cloud and Interface |
| App to Cloud proof | Use authorization code with PKCE S256. | A public client cannot hold a secret. PKCE limits intercepted-code use. | Cloud and Interface |
| Production app return | Use exact claimed HTTPS app or universal links. | The operating system can verify domain ownership. | Interface and deployment |
| Development app return | Allow only exact registered custom-scheme URIs for development builds. Do not allow wildcard schemes or Expo proxy callbacks. | This keeps the development exception narrow and reviewable. | Interface and deployment |
| Google callback | Use a dedicated exact Cloud HTTPS native callback and register it with Google for each environment. | This separates browser and native transaction handling and makes provider mix-up checks direct. | Cloud and deployment |
| Google callback settings | Keep `ALLIES_AUTH_GOOGLE_REDIRECT_URI` as the browser callback. Add `ALLIES_AUTH_GOOGLE_NATIVE_REDIRECT_URI` for native transactions. Make the Google adapter use only the callback stored in the selected `ProviderFlow`. | The current adapter overrides all flows with one setting. Explicit selection prevents a browser/native global switch. | Cloud and deployment |
| Native enablement | Add `ALLIES_AUTH_NATIVE_ENABLED`, default `false`. Enable it only after the callback registry, app-return allowlist, signed-off Railway edge-trust evidence, and shared cache are complete. Treat the setting as rollout acknowledgement, not runtime proof of edge behavior. | An incomplete trust chain must not expose a partial native protocol. | Cloud and deployment |
| Native requester identity | In Railway mode, use only the edge-overwritten `X-Real-IP`, parsed as one address and normalized to IPv4 `/24` or IPv6 `/64`. Pass that non-secret prefix directly to `auths.throttle.check_rate_limit`; the helper performs the sole HMAC and owns the Redis key format. Ignore `X-Forwarded-For` and every client-selected identifier. | This is the smallest non-cookie identity that Railway documents and that staging can test for anti-spoof behavior. | Cloud, security, and deployment |
| Provider attempt and transaction retention | Bound one Google callback attempt to 15 seconds, protect its claim for 30 seconds, and retain terminal transaction metadata for 24 hours. Keep the existing ten-minute pending lifetime. | The claim outlives the provider deadline, cleanup cannot delete active work, and bounded terminal evidence remains available. | Cloud and security |
| Redirect payload | Return a one-time Cloud exchange code plus app state. Never return an access or refresh token in a URI. | URLs can leak through history, logs, and operating-system routing. | Cloud and Interface |
| Access session | Reuse the current ten-minute Cloud JWT as `Authorization: Bearer`, but bind its session family to client kind `native`. | This reuses accepted JWT validation and blocks use of a browser-family token as a native bearer. | Cloud |
| Refresh session | Reuse the current opaque hashed refresh token and 14-day idle / 30-day absolute limits. Rotate on every use and revoke the family on reuse. | This reuses the tested AUTH-001 rotation boundary and follows current OAuth security guidance. | Cloud and Interface |
| Transaction lifetime | Ten minutes. | This matches the current provider-flow limit and gives enough time for system-browser consent. | Cloud and Interface |
| Exchange-code lifetime | Sixty seconds and one successful use. | The app receives it immediately and PKCE protects redemption. | Cloud and Interface |
| Endpoint names | Use the additive `/api/v1/auths/native/*` paths in this plan. | A separate namespace avoids changing browser route behavior. | Cloud and Interface |
| Logout | Accept the current refresh credential, revoke its family, return idempotent `204`, and clear local credentials on every result. If a valid bearer is also supplied, require the same family. | Logout must still work when the access token has expired. | Cloud and Interface |
| Lost device | Keep the lost refresh family valid only until revocation or its idle/absolute limit. Use the existing privileged revocation command until a later owner-approved self-service session manager exists. | Remote session management is not in AUTH-002. This residual risk must be accepted or moved into scope. | Product, Cloud, and Interface |
| OpenAPI version | Add the routes to the existing `/api/v1` API and `0.1.0` schema snapshot unless owners require a schema-version bump. | The routes are additive, but the Interface snapshot policy must confirm the version rule. | Cloud and Interface |

The Nabu feature specification is accepted. Every protocol row in this table
remains proposed until its named owners accept it. A staging proof confirms an
implementation property. It does not change a proposed product or protocol
decision to accepted.

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `backend/auths/services/native_authorization.py` | `begin_native_sign_in` | `(*, provider, redirect_uri, code_challenge, state) -> NativeAuthorizationStart` | Enabled Google provider; exact allowlist match; no query or fragment; S256 challenge; bounded random app state | Provider authorization URL and transaction expiry | Stores a native transaction with digests and sealed values; emits a safe start event |
| `backend/auths/services/native_authorization.py` | `complete_native_callback` | `(*, provider, provider_state, provider_code=None, provider_error=None) -> NativeAppRedirect` | Exact provider and callback kind; active transaction; one of code or denial; claim lease; nonce, issuer, audience, and provider redirect | Exact app redirect with the same sealed Cloud code on recoverable response replay, or a safe error and app state | Claims before provider I/O; finalizes under lock; resolves or creates the AUTH-001 user; never exposes provider details |
| `backend/auths/services/native_sessions.py` | `exchange_native_code` | `(*, code, code_verifier, redirect_uri) -> IssuedSession` | Code digest lookup; active and unused code; exact redirect; RFC 7636 verifier syntax; constant-time S256 match | Access token, refresh token, token type, expiries, and session ID | Consumes the code and creates one native session family in one transaction |
| `backend/auths/services/sessions.py` | `issue_session` | `(*, user, client_kind) -> IssuedSession` | Active user; closed `browser` or `native` kind | Existing issued-session value | Browser remains the default for current callers; native family is explicit |
| `backend/auths/services/sessions.py` | `rotate_refresh` | `(*, raw_token, expected_client_kind) -> IssuedSession` | Hashed token lookup under row lock; active family; expected client kind | One rotated token pair | Existing reuse behavior revokes the family; native and browser callers cannot cross transports |
| `backend/auths/authentication.py` | `resolve_request_session` | `(request) -> RequestSession` | Exactly one accepted transport: browser cookie or native bearer; strict `Bearer` syntax; active matching family kind | Authenticated session plus transport kind | Rejects missing, mixed, malformed, or cross-kind credentials |
| `backend/auths/services/native_sessions.py` | `logout_native_session` | `(*, refresh_token, access=None) -> None` | Refresh digest; if access is present, both credentials must name the same family | None | Revokes the family; unknown or already revoked input remains idempotent |
| `backend/auths/api/common.py` or focused native module | `native_rate_limit_identity` | `(request) -> NativeRequesterIdentity` | Railway mode and signed-off trust acknowledgement; one valid `X-Real-IP`; no alternate forwarded or client identity | Normalized non-secret prefix | Raises a safe unavailable error when identity trust is missing; passes the prefix unchanged to `check_rate_limit`; never logs or persists the raw address or prefix |
| `backend/auths/services/cleanup.py` | existing cleanup extension | `(*, batch_size) -> CleanupResult` | Bounded positive batch; row locks with PostgreSQL `skip_locked` where supported | Counts only | Expires stale claims to `failed`; deletes exchange codes before protected terminal transactions; never deletes an active claim or logs raw values |

The implementation can adjust symbol names during review, but it must preserve
the ownership and behavior in this table. Do not put HTTP response creation in
the service layer.

### API and Transport Contracts

| Consumer | Method and path | Authentication and authorization | Request schema | Success response | Error and retry behavior |
| --- | --- | --- | --- | --- | --- |
| Mobile app | `POST /api/v1/auths/native/sign-in/{provider}` | Public; Google only; rate limited | `redirect_uri`, `code_challenge`, `code_challenge_method: S256`, `state` | `200` with `authorization_url` and `expires_at` | `400 invalid_redirect` or `pkce_required`; `404 provider_unavailable`; `429`; `503`. Start a new flow after an error. |
| Google/system browser | `GET /api/v1/auths/native/callback/{provider}` | Matching provider transaction | Provider `code` and `state`, or provider denial fields | `303` to the stored exact app URI with one-time `code` and app `state` | Valid transactions can redirect with safe OAuth-style errors. Unknown or unsafe state returns a Cloud error and never redirects. |
| Mobile app | `POST /api/v1/auths/native/token` | Public; rate limited; no cookies | `grant_type: authorization_code`, Cloud code, verifier, and exact redirect URI | `200 NativeTokenResponse` | `400 exchange_invalid`; `409 exchange_replayed`; `429`; `503`. A consumed code cannot retry. |
| Mobile app | `POST /api/v1/auths/native/token/refresh` | Native refresh credential; rate limited | `grant_type: refresh_token`, refresh token | `200 NativeTokenResponse` with a rotated pair | `401 session_invalid`; reuse revokes the family. The client clears local credentials and signs in again. |
| Mobile app | `POST /api/v1/auths/native/logout` | Native refresh credential; optional matching native bearer | Refresh token | Idempotent `204` | Clear local credentials for `204`, `401`, network uncertainty, or an already revoked session. Do not retry with an old refresh token. |
| Mobile app | Existing `/api/v1/auths/me`, profile, avatar, and Workspace routes | `Authorization: Bearer <access JWT>` from a native family | Existing schemas | Existing responses | Existing authorization errors. Native writes do not use browser CSRF. Mixed cookie and bearer input is rejected. |

All native token responses include `Cache-Control: no-store` and
`Pragma: no-cache`. Native endpoints do not set auth cookies. CORS and CSRF
behavior for browser calls does not change. Native bearer requests must never
fall back to a browser cookie.

### Browser and Native Google Callback Configuration

The current Google adapter reads `ALLIES_AUTH_GOOGLE_REDIRECT_URI` during both
authorization and token exchange. AUTH-002 must remove that adapter-level
override. The service that creates a transaction selects one configured
callback, writes it to `ProviderFlow.redirect_uri`, and the adapter uses that
value unchanged for both Google requests.

| Flow kind | Exact Cloud setting | Selection and validation rule | Google registration |
| --- | --- | --- | --- |
| Browser | Existing `ALLIES_AUTH_GOOGLE_REDIRECT_URI` | Browser start selects this value only. It must match the browser callback route and the persisted browser `AuthFlow.callback_uri`. | Register the exact value as an authorized redirect URI on the configured Google web client. |
| Native | New `ALLIES_AUTH_GOOGLE_NATIVE_REDIRECT_URI` | Native start selects this value only. It must match the native callback route and the persisted native transaction callback URI. | Register the exact value as a second authorized redirect URI on the same configured Google web client unless owners approve a separate client. |
| App return | New `ALLIES_AUTH_NATIVE_REDIRECT_URIS` exact-value list | The request `redirect_uri` must equal one list member. This is not a Google redirect URI. | Do not register app return URIs with Google. Cloud uses them only after it completes the Google callback. |

| Environment | Browser callback value | Native callback value | App return registry | Required proof |
| --- | --- | --- | --- | --- |
| Local development | Owner supplies the exact local browser value. | Owner supplies a different exact local native value. | Owner supplies exact development-build custom schemes only. | Both Cloud callback values match local Google client registration. Expo Go and proxy callbacks fail. |
| Staging | Deployment owner supplies the exact staging HTTPS browser value. | Deployment owner supplies a different exact staging HTTPS native value. | Interface and deployment owners supply exact staging claimed HTTPS app links. | Startup validation, Google-registration inspection, application identifiers, and domain-association evidence are signed off before enablement. |
| Production | Deployment owner supplies the exact production HTTPS browser value. | Deployment owner supplies a different exact production HTTPS native value. | Interface and deployment owners supply exact production claimed HTTPS app or universal links. | Startup validation, Google-registration inspection, application identifiers, and domain-association evidence are signed off before enablement. |

This matrix names settings and ownership. It does not supply any environment
value. In a deployed environment, `ALLIES_AUTH_NATIVE_ENABLED=true` fails
startup unless all required native values exist, both Cloud callbacks use
allowed schemes and hosts, the callback values differ, and the native app
allowlist is non-empty. Browser Google validation remains independent when
native auth is disabled.

Isolation tests must prove all of these cases:

- A browser transaction always sends the browser callback to Google during
  authorization and exchange. It rejects the native callback route.
- A native transaction always sends the native callback to Google during
  authorization and exchange. It rejects the browser callback route.
- Changing a request field cannot select another callback. The adapter cannot
  read a global redirect setting after it receives `ProviderFlow`.
- A production process cannot start with native enabled and a missing,
  duplicate, non-HTTPS, unregistered, or non-allowlisted value.
- Disabling native auth leaves the accepted browser callback and browser tests
  unchanged.

Representative sign-in request:

```json
{
  "redirect_uri": "https://<owner-approved-app-domain>/<exact-callback-path>",
  "code_challenge": "<base64url-sha256-challenge>",
  "code_challenge_method": "S256",
  "state": "<app-generated-random-state>"
}
```

Representative sign-in response:

```json
{
  "status": "success",
  "message": "Native sign-in started",
  "data": {
    "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?...",
    "expires_at": "2026-08-20T16:10:00Z"
  }
}
```

Representative app return:

```text
https://<owner-approved-app-domain>/<exact-callback-path>?code=<one-time-cloud-code>&state=<app-state>
```

Representative token exchange request:

```json
{
  "grant_type": "authorization_code",
  "code": "<one-time-cloud-code>",
  "code_verifier": "<app-held-pkce-verifier>",
  "redirect_uri": "https://<owner-approved-app-domain>/<exact-callback-path>"
}
```

Representative token response:

```json
{
  "status": "success",
  "message": "Native session issued",
  "data": {
    "token_type": "Bearer",
    "access_token": "<short-lived-cloud-jwt>",
    "expires_in": 600,
    "refresh_token": "<rotating-opaque-cloud-token>",
    "refresh_expires_in": 1209600,
    "session_id": "ses_..."
  }
}
```

`refresh_expires_in` reports the current token's remaining idle limit, bounded
by the family absolute limit. The access JWT does not contain Workspace roles,
capabilities, provider claims, email, profile data, or refresh material.

### Schema and Data Shapes

| Schema or model | Location | Fields | Required rules | Validation and invariants | Compatibility and migration |
| --- | --- | --- | --- | --- | --- |
| `NativeAuthorizationTransaction` | `backend/auths/models.py` | provider; callback kind and URI; provider state digest; sealed app state; app redirect URI; code challenge; sealed provider nonce and PKCE verifier; status; claim digest; claimed, claim-expiry, terminal, created, and pending-expiry times; safe error code | Security fields and closed status required; claim and terminal fields follow status constraints | Provider state is unique and hashed; exact redirects are allowlisted before write; S256 only; one active claim; terminal states do not transition | New table, status constraints, and expiry indexes; no browser-row rewrite |
| `NativeExchangeCode` | `backend/auths/models.py` | unique code digest; sealed code; protected transaction relation; user; app redirect URI; code challenge; created, expiry, and consumed times | Raw code is never stored in plaintext | One code per completed transaction; exact redirect and PKCE binding; one successful consume under lock; sealed value allows the same redirect after callback response loss | New table and expiry index; transaction deletion waits until the code is consumed or expired and removed |
| `SessionFamily.client_kind` | `backend/auths/models.py` | closed `browser` or `native` value | Required | Existing rows become `browser`; native issue is explicit; auth transport must match | Additive non-null field with safe browser default for existing rows |
| `RefreshToken` | existing model | existing family, digest, expiry, and used time | No new lineage field | Existing one-unused-token constraint and reuse behavior remain authoritative | No new token table or parallel rotation engine |
| Native API schemas | `backend/auths/api/schemas.py` or a focused native schema module | request and response fields from the API table | Strict bounded strings and closed literals | Reject extra security-critical alternatives such as `plain` PKCE | Additive OpenAPI shapes |
| Redirect allowlist | settings and deployment inventory | exact production and development URI values | Required when native auth is enabled | HTTPS claimed links for production; no wildcard, user info, query, fragment, or path-prefix match | Production startup fails closed when enabled but incomplete |

Raw app state, provider nonce, provider PKCE verifier, Cloud exchange code, and
refresh credential must not be stored in plaintext. Values that Cloud must
return or reuse are sealed with the existing dedicated auth key boundary. Values
used only for lookup are stored as keyed digests.

### Native Transaction State Machine and Cleanup Contract

| State | Entry | Allowed next state | Callback result and retry rule | Cleanup rule |
| --- | --- | --- | --- | --- |
| `pending` | Native start persists a valid transaction. | `claimed`, `denied`, or `failed` | A valid Google code can claim once. A valid provider denial becomes `denied`. Invalid or expired state returns a Cloud error and never redirects. | Delete only after the ten-minute pending expiry and only while locked. |
| `claimed` | A callback locks `pending`, writes a random claim digest, `claimed_at`, and `claim_expires_at`, then releases the lock before provider I/O. | `completed` or `failed` | One provider attempt has a 15-second total deadline and no automatic provider retry. A duplicate callback gets a safe in-progress response. | Never delete. After the 30-second claim lease, cleanup locks the row and changes stale `claimed` to `failed` with `provider_unavailable`. |
| `completed` | Provider verification, identity resolution, exchange-code creation, and terminal update commit under one final lock for the same claim digest. | None | While the exchange code is active and unused, a repeated callback returns the same app redirect from the sealed code without calling Google again. After code expiry or consumption, return a safe terminal error. | Retain for 24 hours after `terminal_at`. The transaction relation is protected until its exchange code is consumed or expired and deleted first. |
| `denied` | Google returns a recognized denial for a valid pending state. | None | Redirect only to the stored app URI with `error=access_denied` and the stored app state. A repeat returns the same safe denial. | Retain for 24 hours after `terminal_at`, then delete in a bounded batch. |
| `failed` | Provider timeout, malformed provider response, provider rejection, stale claim recovery, or failed finalization. | None | Redirect only for a known valid transaction, using `provider_unavailable` or `flow_failed`. Do not include provider text. The app starts a new flow. | Retain for 24 hours after `terminal_at`, then delete in a bounded batch. |

The callback uses two short database transactions. The first claims the row.
The second checks the same claim digest and finalizes the row. Google I/O occurs
between them and outside a database lock. Provider denial does not call Google.
Identity resolution and exchange-code creation must be atomic with the
`completed` transition, so a completed row always has one recoverable code.

PostgreSQL race tests must use real row locks and barriers:

- callback versus callback: one request claims; the other gets the documented
  in-progress or terminal result; only one provider attempt and one code exist;
- callback finalization versus cleanup before claim expiry: cleanup skips the
  locked or active claim; finalization can complete;
- callback finalization versus cleanup after claim expiry: one lock winner
  decides the terminal state; a late provider result cannot overwrite `failed`;
- completed callback versus code cleanup: cleanup deletes an expired code
  first and only then permits terminal transaction deletion;
- provider denial, timeout, malformed response, and response loss produce the
  safe repeat behavior in the table and do not create a session.

### Native Session State Contract for INT-008

| State | Trigger | Cloud behavior | Interface behavior |
| --- | --- | --- | --- |
| `signed_out` | No refresh credential or terminal session failure | No account data | Show sign-in entry |
| `authorizing` | Sign-in start accepted | Hold expiring transaction only | Open system browser and keep verifier plus state in short-lived flow memory |
| `cancelled` | User closes or Google denies browser flow | No session; a known denial becomes terminal `denied`; a closed browser leaves `pending` to expire | Delete flow memory and return to signed out with a new-sign-in action |
| `exchanging` | App receives matching code and state | Validate exact redirect, PKCE, expiry, and one-time code | Exchange once; never persist the Cloud code |
| `signed_in` | Token pair issued and `/auths/me` succeeds | Enforce native family and current Cloud account state | Keep access in memory and refresh in SecureStore |
| `refreshing` | Access expires or app restores | Rotate one refresh token under lock | Use one in-flight refresh operation and replace SecureStore only after success |
| `revoked` | Reuse, operator revoke, user disable, or logout | Reject access and refresh for the family | Clear credentials, clear account query data, and show sign-in |
| `offline` | A read or typed pre-mutation failure cannot reach Cloud | No false success | Keep the last safe state only when token mutation did not have an unknown outcome; unknown exchange or refresh clears credentials and requires sign-in |

## Phases

### Phase 0 - Freeze the Threat Model and Public Contract

- Goal: Turn every proposed protocol choice into an accepted Cloud and Interface
  contract before code changes.
- Work items:
  - Confirm the endpoint names, schema-version rule, lifetimes, and logout
    semantics in the decision register.
  - Supply the exact production iOS and Android claimed HTTPS return URIs and
    exact development-build custom-scheme URIs. Remove the generic `mobile`
    scheme from the consumer plan; do not change Interface in this Cloud ticket.
  - Confirm the dedicated Cloud native Google callback URI for local, staging,
    and production and register each exact URI in the correct Google client.
  - Accept the browser/native setting names, selection rule, environment
    matrix, and callback isolation tests.
  - Accept the Railway `X-Real-IP` prefix trust chain, prefix sizes,
    per-operation limits, and staging proof. Keep native auth disabled if
    Railway does not overwrite a forged value.
  - Accept the transaction attempt deadline, claim lease, terminal retention,
    state transitions, safe error catalog, and response-loss behavior.
  - Accept the lost-device residual risk or add a separate remote session
    management ticket. Do not silently expand AUTH-002.
  - Freeze the error catalog, token response, cache headers, audit event names,
    and Interface state table.
- Impacted systems: owner decision record, deployment configuration checklist,
  Cloud plan, and Interface consumer handoff.
- Exit criteria: Cloud and Interface owners accept every required row. Security
  and deployment owners accept the Railway proof procedure. No URI, field,
  lifetime, callback, requester-identity, or provider behavior is invented.

### Phase 1 - Add Native Transaction and Session Invariants

- Goal: Add the minimum durable state for a native authorization transaction
  and one-time exchange while reusing AUTH-001 sessions.
- Work items:
  - Add `NativeAuthorizationTransaction` and `NativeExchangeCode` with the five
    states, claim lease, safe terminal error, sealed recoverable code, protected
    relation, expiry indexes, and one-time constraints.
  - Add `SessionFamily.client_kind`. Migrate all existing rows to `browser`.
  - Add exact redirect configuration and fail-closed production checks. Keep
    browser callback configuration valid and unchanged.
  - Make the provider callback URI explicit in `ProviderFlow` so the browser
    and native Google callbacks cannot be mixed.
  - Extend bounded auth cleanup for expired native records.
  - Add the `MigrationExecutor` forward-upgrade test from
    `auths.0002` on SQLite and PostgreSQL. Prove the browser default and refresh
    rotation after migration.
  - Add model, configuration, cleanup, callback-isolation, and constraint tests.
- Impacted files and systems: `backend/auths/models.py`, a new auth migration,
  `backend/auths/config.py`, `backend/config/settings.py`,
  `.env.deploy.example`, Google provider flow input, cleanup service, task and
  command tests.
- Exit criteria: Fresh migrations and the exact old-to-new upgrade test pass on
  SQLite and PostgreSQL. Existing families remain usable browser families.
  Browser and native callbacks cannot mix. Cleanup cannot delete a live claim
  or a transaction with a live code. Browser auth tests still pass.

### Phase 2 - Implement the Native Google and Token Services

- Goal: Complete the two-hop flow without leaking provider or Cloud
  credentials.
- Work items:
  - Implement native begin, provider callback, code exchange, refresh, and
    logout services with the function shapes above.
  - Reuse `get_provider`, `resolve_or_create_user`, JWT issue and validation,
    refresh rotation, family revocation, and auth audit helpers.
  - Implement the `pending -> claimed -> completed|failed` and
    `pending -> denied` state machine. Do not add optional cookie binding to the
    native path.
  - Keep the bounded provider call outside locks. Finalize only under the same
    claim digest. Support safe callback response replay from the sealed Cloud
    code and terminal safe error.
  - Consume the one-time exchange code and create the native family in one
    database transaction after PKCE validation.
  - Preserve one-winner refresh semantics. Document that a concurrent second
    refresh is reuse and revokes the family. INT-008 must use single-flight
    refresh.
  - Add unit and PostgreSQL race tests for callback versus callback, callback
    versus cleanup, code cleanup versus transaction cleanup, exchange, and
    refresh.
- Impacted files and systems: new native authorization/session services,
  existing session service, Google provider flow input, account bootstrap,
  PostgreSQL auth test module, and cleanup.
- Exit criteria: A deterministic fake-provider flow proves one user and one
  native family. Denial, timeout, response loss, stale claim, cleanup race,
  replay, verifier mismatch, redirect mismatch, provider mix-up, concurrent
  exchange, and refresh reuse have the exact results in this plan.

### Phase 3 - Publish Strict Native HTTP and Bearer Boundaries

- Goal: Expose the accepted contract and let native bearer sessions use the
  existing account surface without weakening browser CSRF rules.
- Work items:
  - Add a focused native auth controller and register it under
    `/api/v1/auths/native`.
  - Add strict schemas, stable safe errors, `303` app redirects, and non-cache
    token response headers.
  - Add a request-session resolver that accepts one transport only. Cookie
    tokens require browser families and existing CSRF/origin rules. Bearer
    tokens require native families and do not use browser CSRF.
  - Apply the resolver to `/auths/me`, profile, avatar, and Workspace routes.
    Keep their response schemas and capability checks unchanged.
  - Reject bearer tokens on browser-only auth routes and reject cookie tokens on
    native token routes.
  - Add one shared Redis requester-prefix limit per native operation. Pass the
    normalized prefix directly to the existing `check_rate_limit` helper. Do
    not add a pre-HMAC identity or a second cache-key format. Do not use the
    browser cookie or process-local admission bucket for native routes.
  - Fail with `503` on missing, malformed, unproved, or unavailable native
    identity and cache state.
  - Emit bounded native events and add log-capture tests that prove redaction.
- Impacted files and systems: auth controllers, schemas, registration,
  authentication resolver, profile/avatar/Workspace controllers, error mapping,
  throttle calls, audit events, and API tests.
- Exit criteria: OpenAPI documents every route, header, request, response, and
  error. Unit and multi-worker staging tests prove one shared native requester
  bucket and fail-closed cache behavior. Browser behavior has no regression.
  Native bearer access cannot use a browser family, bypass Workspace
  authorization, or create a CSRF exception for cookie requests.

### Phase 4 - Security Proof, Publication, and Interface Handoff

- Goal: Publish a contract that INT-008 can consume without private Cloud
  knowledge.
- Work items:
  - Add OpenAPI examples and contract assertions in
    `backend/config/tests/test_api_contract.py`.
  - Run the complete Cloud validation and PostgreSQL concurrency matrix.
  - Inspect responses and captured logs for Google codes, Cloud exchange codes,
    JWTs, refresh tokens, app state, email, provider claims, and redirect query
    values.
  - Deploy the disabled routes and migration first. Enable native Google only
    after exact redirect and provider configuration is present and the Railway
    forged-header, rotation, concurrency, multi-worker, and cache-outage proof
    passes.
  - Publish staging OpenAPI. Let Interface fetch, generate, and verify the
    pinned snapshot through its existing scripts.
  - Require the Interface-owned native contract test to compile the four new
    native-session methods and separately capture the existing account,
    profile, avatar, and Workspace bearer allowlist. Prove request mapping,
    public exclusions, and every error-to-session-state mapping.
  - Run the diff-based boundary check. Reject any new Foundry, Hermes, Fly, or
    runtime import, dependency, setting, job, route, or deployment change.
  - Verify deployment-owned app-link association and exact Google registration
    evidence. Defer iOS/Android device lifecycle smoke proof for success,
    cancel, exchange, restore, refresh, logout, and revoked family to INT-008,
    after this contract-only handoff unblocks its implementation.
  - Record the accepted schema revision and sanitized proof for the INT-008
    handoff.
- Impacted systems: Cloud tests, OpenAPI, staging configuration, deployment
  runbook, and the later Interface contract snapshot.
- Exit criteria: Cloud validation, both forward-upgrade database tests, and the
  Railway proof pass. Staging publishes the accepted contract. The
  Interface-owned compilation and header/error tests pass. Deployment-owned
  callback registration and app-link evidence is complete. The dependency
  guard has no finding. INT-008 can move from blocked to ready through the
  normal Nabu owner process and owns the later device lifecycle proof.

## Acceptance Criteria

1. Native Google sign-in uses the external system browser and PKCE S256.
2. Cloud accepts only exact owner-approved return URIs. Production uses claimed
   HTTPS links. Wildcards, prefix matches, fragments, query-bearing registered
   URIs, and unapproved custom schemes fail.
3. Google returns to the exact callback selected by transaction kind. Browser
   and native settings, routes, persisted callback values, authorization
   requests, and token exchanges cannot cross. The app return URI contains only
   a one-time Cloud code, the app state, or safe error fields.
4. Google access tokens, Google refresh tokens, Cloud refresh tokens, access
   JWTs, raw provider claims, and client secrets never appear in URLs, logs,
   traces, analytics, error bodies, ordinary files, or database plaintext.
5. A Cloud exchange code has a lookup digest and a sealed recoverable value. It
   is bound to one user transaction, redirect URI, and PKCE challenge, expires
   after the accepted short lifetime, and can create at most one native session
   family.
6. Native access uses `Authorization: Bearer` with a short-lived JWT. Browser
   families cannot authenticate as native bearer families, and native families
   cannot authenticate through browser cookies.
7. Native refresh credentials are opaque, hashed, rotated on every use, and
   bounded by idle and absolute expiry. Detected reuse revokes the family and
   invalidates its access JWTs through the existing family check.
8. Native logout is idempotent, cannot revoke an unrelated family, and tells the
   Interface to clear local credentials even after network or server
   uncertainty.
9. Existing account, profile, avatar, and Workspace routes support an active
   native bearer session without weakening cookie CSRF, origin, or
   cross-Workspace checks.
10. OpenAPI publishes all native request, success, error, header, cache, and
    expiry fields with representative examples.
11. Railway staging proves an edge-overwritten, non-cookie `X-Real-IP` prefix
    identity across forged headers, rotated client identifiers, concurrent
    requests, at least two web workers, and one shared Redis cache. Missing or
    unproved identity and cache outage fail with `503` and no process-local
    fallback. Native auth stays disabled until this proof passes.
12. The transaction state machine has `pending`, `claimed`, `completed`,
    `denied`, and `failed` states. Provider denial, timeout, response loss,
    stale claims, terminal retention, and PostgreSQL callback-versus-cleanup
    races have the exact behavior in this plan.
13. Existing browser auth and waitlist behavior continues to pass its full
    regression suite.
14. Interface consumer review compiles the four new native-session client
    methods against the pinned schema and separately proves the existing
    account, profile, avatar, and Workspace method-and-path bearer allowlist,
    public-route exclusions, and every documented error-to-session-state
    transition. INT-008 owns device lifecycle smoke proof after this handoff.
15. The forward-upgrade test starts at `auths.0002`, creates a browser-era
    family and refresh row, migrates forward once, proves
    `client_kind=browser`, and rotates the existing refresh successfully on
    SQLite and PostgreSQL. Normal migration checks cover repeat application.
16. No Foundry, Hermes, Fly, Ally, runtime, pre-auth, waitlist, or conversation
    dependency appears in the implementation. The required diff check rejects
    any new import, package, setting, job, route, or deployment reference.
17. Tests also cover cancellation, unknown state, callback replay, provider
    mix-up, redirect mismatch, plain PKCE, verifier mismatch, code expiry, code
    reuse, concurrent exchange, refresh expiry, concurrent refresh, reuse
    revocation, logout, user disable, mixed credentials, redaction, and
    Workspace denial.

## Backend Considerations

### Query Optimization Plan

- Native begin writes one indexed transaction. It does not load account or
  Workspace relations.
- Native callback locks one transaction to claim it, releases the lock for one
  bounded Google attempt, then locks the same row to resolve the identity and
  write one exchange code. Keep all provider I/O outside database locks.
- Exchange uses one indexed code-digest lookup under `select_for_update`, then
  creates one session family and one refresh row in the same transaction.
- Refresh keeps the existing indexed digest lookup and row locks. Add the
  client-kind predicate without collection scans.
- Bearer `/auths/me` and Workspace requests keep the current deliberate relation
  loading. Do not add a native-only account query path.
- Cleanup orders candidates by status and expiry, uses bounded batches and row
  locks, marks stale claims failed, deletes expired codes before protected
  transactions, and does not scan all auth rows.
- Add query-count or bounded-query assertions for begin, exchange, refresh, and
  `/auths/me`. Record the actual upper bound after implementation and fail on a
  relation N+1 regression.

### N+1 Prevention

- Native transaction and exchange endpoints operate on one row and direct
  relations only.
- Load the exchange-code user and transaction with explicit `select_related`.
- Load the refresh family and user through the existing joined lookup.
- Reuse the current account and Workspace response services. Do not loop over
  identities, memberships, sessions, or capabilities.
- Do not call Google or another external provider while serializing a response.

### Detailed Unit Test Cases

- Happy path: new and returning Google identity; exact redirect; callback;
  exchange; bearer `/auths/me`; profile and Workspace read; refresh; logout.
- Validation: unsupported provider, unknown redirect, redirect case or trailing
  slash mismatch, query or fragment, malformed state, invalid challenge,
  `plain` PKCE, malformed verifier, oversized code, malformed Authorization
  header, and mixed bearer plus cookie.
- Provider boundary: wrong issuer, audience, nonce, provider state, callback
  route, browser/native setting isolation, provider denial, timeout, malformed
  JSON, missing ID token, and provider response loss.
- One-time behavior: callback replay, exchange-code replay, expired transaction,
  expired code, verifier mismatch, and redirect mismatch.
- Concurrency: two valid callbacks for one provider state, callback finalization
  against cleanup before and after claim expiry, code cleanup against protected
  transaction cleanup, two valid exchanges for one Cloud code, and two
  refreshes for one refresh token. PostgreSQL must prove each lock winner and
  terminal result.
- Session boundary: native JWT on cookie transport, browser JWT on bearer
  transport, inactive user, revoked family, idle expiry, absolute expiry,
  access expiry, refresh reuse, access/refresh family mismatch, logout with
  valid, expired, reused, missing, and unknown credentials.
- Authorization: native bearer on self profile, avatar, and owner Workspace;
  foreign Workspace denial remains non-disclosing.
- Abuse controls: missing and malformed Railway identity, forged and rotated
  client-controlled identity inputs, real prefix change, each requester limit,
  stable requester bucket across refresh rotation, two-worker shared behavior,
  shared-cache failure, and no process-local security downgrade.
- Redaction: capture success, rejection, unhandled error, throttle, provider
  failure, reuse, and cleanup logs. Assert that raw request fields and secrets
  are absent.
- Migration and cleanup: exact `auths.0002` forward upgrade on SQLite and
  PostgreSQL; browser default and existing refresh rotation; fresh database;
  stale-claim recovery; protected cleanup ordering; bounded retry and count
  output. Normal migration checks cover repeat application.
- OpenAPI: routes, bearer security description, request unions or closed
  literals, errors, examples, `no-store`, and existing response envelopes.

### Migration Plan

1. Generate additive migration `auths.0003_native_session_contract` after the
   current pre-AUTH-002 leaf, `auths.0002_externalidentity_email_verification`.
   If another migration lands first, use an explicit merge and update the test
   target. Do not change the tested predecessor.
2. Add the native tables, indexes, status constraints, protected relation, and
   `SessionFamily.client_kind`. Add the field with a database-safe `browser`
   default, backfill every existing row to `browser`, then keep `browser` as the
   Python default for existing callers. Do not infer kind from tokens, user
   agents, or timestamps.
3. Add
   `backend/auths/tests/test_auth_002_migrations.py::test_auth_002_forward_upgrade_preserves_browser_refresh`.
   The test uses `MigrationExecutor` to migrate to `auths.0002`, creates a user,
   one active browser-era family, and one unused refresh row with a known raw
   token and valid digest, and then migrates to the AUTH-002 leaf.
4. After the forward migration, assert that the existing family has
   `client_kind=browser`, the native tables and constraints exist, and
   `rotate_refresh(known_raw_token, expected_client_kind="browser")` returns a
   successor in the same active browser family. Assert that browser access
   authentication and the existing refresh-reuse regression still pass.
5. Restore the full migration graph in `finally` so the test can run repeatedly
   and cannot contaminate later tests.
6. Run that same test on SQLite in the normal test job and on PostgreSQL in the
   `postgresql-auth` job before the concurrency suite. Keep the existing fresh
   migration path in both jobs. A fresh migration is not accepted as upgrade
   evidence.
7. Apply the production migration while native routes remain disabled. Deploy
   code and migration before owners register and enable native settings.
8. Roll back behavior by disabling native routes and revoking native families.
   Keep the additive schema for investigation. Do not destructively reverse
   identity or session data during an incident.

### Rate Limits and Audit Contract

#### Railway native requester identity

The proposed primary requester identity is a Railway-edge network prefix. It
is not a cookie and it is not supplied by Interface code.

| Trust step | Required property | Failure behavior |
| --- | --- | --- |
| Public path | Client TLS terminates at Railway's managed edge. The Cloud web service has no public listener or alternate proxy path around that edge. | Keep `ALLIES_AUTH_NATIVE_ENABLED=false`. |
| Edge header | Railway supplies `X-Real-IP` as the remote client address. Staging proves that the edge overwrites a client-sent header instead of forwarding it unchanged. | Keep native disabled. Do not trust `REMOTE_ADDR` in Railway mode. |
| Rollout acknowledgement | Deployment sets `ALLIES_RAILWAY_PROXY_MODE=true` and enables native auth only after the signed-off proof below is attached. `ALLIES_AUTH_NATIVE_ENABLED=true` acknowledges that evidence; it does not prove at runtime that Railway overwrites the header. | Keep native disabled when the evidence is missing or unsigned. |
| Application parser | Read exactly one `X-Real-IP` value. Reject missing, empty, malformed, or comma-separated input. Ignore `X-Forwarded-For`, `Forwarded`, user agent, app state, PKCE values, request IDs, and client-selected installation IDs. | Return `503 auth_unavailable` before provider or database work. |
| Privacy transform | Normalize IPv4 to `/24` and IPv6 to `/64`. Pass the normalized prefix directly as the non-secret `identity` to `auths.throttle.check_rate_limit`. The helper performs the only HMAC and is the sole owner of generated Redis key format. Never log or persist the raw address or normalized prefix. | Return `503` if the shared helper or cache is unavailable. |

Each native operation calls the existing `check_rate_limit` helper once for its
requester-prefix limit and passes the normalized prefix unchanged as the
non-secret identity. The helper performs the one privacy transform and owns the
generated Redis key. The plan does not prescribe or duplicate that internal
key format.

All counters use the configured Django cache in Redis logical database 0.
Their retention is exactly the accepted rate window because the existing
`check_rate_limit` counter TTL equals `period`. No process-local bucket is a
native security control. A cache error, unsupported cache backend, missing
identity, or unsigned edge-trust evidence returns `503` for begin, exchange,
refresh, and logout. Interface still clears local credentials after an
uncertain logout.

The exact values remain proposed and need owner acceptance:

| Operation | Shared identity | Proposed limit | Ordering and failure |
| --- | --- | --- | --- |
| Native sign-in begin | Normalized requester prefix | 10 per requester prefix per minute | One shared helper call runs before transaction or provider work. An unavailable check returns `503`. |
| Token exchange | Normalized requester prefix | 10 per requester prefix per minute | One shared helper call runs before code lookup. A typed `429` or `503` proves no consume. |
| Refresh | Normalized requester prefix | 20 per requester prefix per minute | One shared helper call runs before token lookup or rotation. A typed `429` or `503` proves no rotation. |
| Logout | Normalized requester prefix | 30 per requester prefix per minute | One shared helper call runs before revocation. On `503` or network uncertainty, local credentials clear and server revocation is unconfirmed. |

#### Required Railway and shared-cache proof

- Unit tests send no `X-Real-IP`, an empty value, malformed input, and a list.
  Each case returns `503` and performs no provider, database, or Redis work
  after identity validation.
- Unit tests change `X-Forwarded-For`, `Forwarded`, user agent,
  `X-Allies-Client-ID`, app state, redirect URI, and PKCE values. The derived
  requester identity and bucket do not change.
- A staging public-edge test sends forged and rotated `X-Real-IP` values from
  one controlled source. The combined requests consume one `/24` or `/64`
  bucket and reach `429`; the supplied header values do not create new buckets.
- The same staging test rotates all client-controlled headers above. It still
  consumes one requester bucket. Two controlled source prefixes prove that a
  real edge-observed prefix change creates a separate bucket.
- A direct private-network staging request with the edge header removed returns
  `503`. It cannot start or exchange a native flow.
- Run at least two Gunicorn workers against one Redis cache. Concurrent requests
  from one controlled source have one combined limit. Restarting or scaling a
  worker does not reset the counter.
- Stop or misconfigure the shared cache. Every native operation fails with
  `503`; no process-local fallback admits work. Restore Redis and prove that
  browser auth remains independent.
- Keep Google disabled during this proof. The disabled native start route can
  return `provider_unavailable` after admission, which allows throttle outcomes
  to be observed without creating a provider transaction. Enable native auth
  only after Cloud, security, and deployment owners sign the sanitized result;
  the enablement setting records rollout acknowledgement only.

Add these low-cardinality events to the existing privacy-safe auth envelope:
`auth.native.flow.started`, `auth.native.flow.completed`,
`auth.native.flow.rejected`, `auth.native.exchange.completed`,
`auth.native.exchange.rejected`, `auth.native.refresh.rotated`,
`auth.native.refresh.reuse_detected`, and `auth.native.session.revoked`.

Do not include raw or partial codes, tokens, app state, redirect URIs with query
values, provider claims, email, display names, full IP addresses, request
bodies, Google response bodies, or SecureStore data. Use only opaque user,
family, and correlation references already supported by `auths.audit`.

## Frontend Considerations

AUTH-002 does not implement Interface code. These details define the consumer
handoff.

### Concrete Interface Consumer Handoff

`@allies/cloud-client` keeps the generated OpenAPI types and adds four focused
native-session methods. The names and camel-case view models are part of the
proposed handoff:

| Client method | Cloud request | Headers and credentials | Return mapping | Retry rule |
| --- | --- | --- | --- | --- |
| `beginNativeSignIn(input, signal?)` | `POST /api/v1/auths/native/sign-in/google`; map `redirectUri`, `codeChallenge`, `state` to the request schema | `Accept` and JSON content type; no bearer, cookie, or CSRF header | `authorization_url` -> `authorizationUrl`; `expires_at` -> `expiresAt` | No automatic retry. A new user action creates a new state and verifier. |
| `exchangeNativeCode(input, signal?)` | `POST /api/v1/auths/native/token`; map code, verifier, and exact redirect | `Accept` and JSON content type; no bearer, cookie, or CSRF header | Token response -> `NativeTokenPair` with camel-case expiry and session fields | Retry the same code only after a typed `429` or `503`, because Cloud guarantees no consume. Network or timeout outcome is unknown; discard flow data and start again. |
| `refreshNativeSession(refreshToken, signal?)` | `POST /api/v1/auths/native/token/refresh` | JSON only; refresh token in body; no bearer, cookie, or CSRF header | Rotated `NativeTokenPair` | One in-flight call. Typed `429` or `503` can retry the same token after backoff because Cloud guarantees no rotation. Network or timeout outcome is unknown; clear the token and require sign-in. |
| `logoutNativeSession(input, signal?)` | `POST /api/v1/auths/native/logout` | Refresh token in body. Add the matching bearer only through this method when available. Never use global injection for logout. | `{ status: "signed-out", serverConfirmed: boolean }` | Never replay an old refresh token. Clear local credentials for every result. `204` or terminal `401` is confirmed; network, timeout, or `5xx` is unconfirmed. |

The existing `getCurrentAccount`, `updateProfile`, `prepareAvatarUpload`,
`completeAvatar`, `getAvatarRead`, `deleteAvatar`, and `getWorkspace` methods
remain unchanged. A native bearer preparer adds the current access token only
for their reviewed method-and-path pairs below. It sets no cookie or CSRF
header. After a `401`, one existing account request can run once after one
successful single-flight refresh. Authorization and contract errors do not
retry.

The bearer preparer requires the Cloud base origin, exact HTTP method, and one
of these path patterns:

| Method | Allowed bearer path |
| --- | --- |
| `GET` | `/api/v1/auths/me` |
| `PATCH` | `/api/v1/auths/me/profile` |
| `POST` | `/api/v1/auths/me/avatar/uploads` |
| `POST` | `/api/v1/auths/me/avatar/{asset_id}/complete` |
| `GET` | `/api/v1/auths/me/avatar/read` |
| `DELETE` | `/api/v1/auths/me/avatar` |
| `GET` | `/api/v1/workspaces/{workspace_id}` |

All native begin, callback, exchange, and refresh routes are public-route
exclusions and never receive a bearer. Browser CSRF, browser sign-in,
browser callback, browser refresh, browser logout, waitlist, health, OpenAPI,
external Google URLs, app-return URLs, and direct avatar upload URLs are also
excluded. Native logout receives an optional bearer only from its explicit
method. A new Cloud route does not receive a bearer until Interface adds its
method and path to this reviewed allowlist.

### Error to Session-State Mapping

| Operation and error | Interface state and credential action | User or retry action |
| --- | --- | --- |
| Begin `invalid_redirect`, `pkce_required`, or contract error | `signed_out`; keep no flow credential | Show a non-secret configuration failure. Do not retry automatically. |
| Begin `provider_unavailable`, `429`, `503`, network, or timeout | `signed_out`; keep no flow credential | Show retry. A new action creates a new flow. |
| App return `access_denied` | `cancelled` then `signed_out`; delete verifier and state | Show normal cancellation and allow a new sign-in. |
| App return state or callback mismatch | `signed_out`; delete verifier, state, and code | Show a security-safe failure. Start a new sign-in only by user action. |
| Exchange `exchange_invalid`, expired, replayed, network, or timeout | `signed_out`; delete code, verifier, and state | Start a new sign-in. Never auto-replay an outcome-unknown exchange. |
| Exchange typed `429` or `503` | Stay `exchanging` only while the code is unexpired | One bounded retry after server guidance; otherwise start again. |
| Refresh `session_invalid` or reuse | `revoked` then `signed_out`; clear access, refresh, and account queries | Require sign-in. |
| Refresh typed `429` or `503` before rotation | `offline` while current access remains valid; retain refresh | Retry through the one in-flight refresh operation after backoff. |
| Refresh network, timeout, or SecureStore write failure after rotation | `signed_out`; clear all local credentials | Require sign-in. Do not replay the old refresh token. |
| Authenticated account route `401` | `refreshing`; run one single-flight refresh, then replay the account request once | Terminal refresh result becomes `signed_out`. |
| Authenticated account route `403` or non-disclosing `404` | Remain `signed_in`; do not clear credentials | Show the route-level permission or absent result. |
| Logout `204` or terminal `401` | `signed_out`, `serverConfirmed=true`; clear all local data | No retry. |
| Logout network, timeout, `429`, `503`, or other `5xx` | `signed_out`, `serverConfirmed=false`; clear all local data | Explain that server revocation is uncertain. Do not replay the old token. |

### Interface-Owned Contract Compilation

The handoff is not complete when Cloud generates OpenAPI alone. The Interface
owner adds
`packages/cloud-client/test/native-session-contract.test.ts` against the pinned
schema. The test imports generated request and response types and compiles the
four new native-session methods: `beginNativeSignIn`, `exchangeNativeCode`,
`refreshNativeSession`, and `logoutNativeSession`. It separately captures the
existing `getCurrentAccount`, `updateProfile`, `prepareAvatarUpload`,
`completeAvatar`, `getAvatarRead`, `deleteAvatar`, and `getWorkspace` methods
through the native bearer preparer, proves snake-case to camel-case mapping,
and asserts the exact bearer allowlist and public-route exclusions. It also
table-tests every error-to-state row above, including refresh reuse and logout
uncertainty.

INT-008 remains blocked until the Interface owner records a passing result for:

```powershell
bun run cloud:fetch
bun run cloud:check
bun --filter @allies/cloud-client typecheck
bun run test:run packages/cloud-client/test/native-session-contract.test.ts
```

This contract-only consumer proof belongs to the Interface repository. It does
not authorize Interface application changes in the AUTH-002 Cloud branch.

### Data Path

- User action entry: Mobile Google sign-in action.
- Client route/component: INT-008 sign-in and callback routes in the Expo Router
  app.
- Client API boundary: the generated contract, the four new native-session
  methods, the existing account surface, and the bearer allowlist.
- Backend path: native start, Google in the system browser, Cloud callback, app
  link, token exchange, bearer account APIs, refresh, and logout.
- Response mapping: token fields stay in the native session adapter. Existing
  account fields map through the shared account view model.
- Error, loading, and retry path: use the mapping table above. Do not replay a
  consumed code, an outcome-unknown exchange, or an outcome-unknown refresh.

### State Management Considerations

- The native session adapter owns access-token memory, SecureStore refresh
  reads and writes, and one in-flight refresh promise.
- Expo SecureStore is the only persistent credential store.
- TanStack Query owns Cloud account data. Clear it on terminal session failure
  and logout.
- Zustand and React context can hold non-secret workflow state only. They do
  not persist credentials.
- The client validates returned app state and the exact callback URI before
  token exchange.
- Save the new refresh token to SecureStore before discarding the old token in
  memory. If secure persistence fails after Cloud rotation, clear the local
  session and require sign-in. Do not retry the used token.
- Serialize refresh. The current Cloud reuse policy treats a second use as a
  breach and revokes the family.

## Test Plan

### Smallest Relevant Checks During Implementation

Run the smallest check after each meaningful phase:

```powershell
make check
make lint
make test APP=auths/tests
make test APP=config/tests/test_api_contract.py
```

Generate and apply the additive migration with repository targets:

```powershell
make migrations APP=auths MIGRATION_NAME=native_session_contract
make migrate APP=auths
```

Run the exact forward-upgrade proof on the default SQLite test database:

```powershell
Set-Location backend
uv run pytest auths/tests/test_auth_002_migrations.py::test_auth_002_forward_upgrade_preserves_browser_refresh
```

The `postgresql-auth` CI job uses its service `DATABASE_URL` and runs the same
test node before the PostgreSQL race suite:

```powershell
Set-Location backend
uv run pytest auths/tests/test_auth_002_migrations.py::test_auth_002_forward_upgrade_preserves_browser_refresh
uv run pytest -m postgresql
```

Run the PostgreSQL security race tests through the same command used by CI,
with the CI environment and a PostgreSQL `DATABASE_URL`:

```powershell
Set-Location backend
uv run pytest -m postgresql
```

### Complete Cloud Validation Before Handoff

These commands come from the current `Makefile` and `.github/workflows/ci.yml`:

```powershell
Set-Location backend
uv sync --locked
uv lock --check
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate --noinput
uv run python manage.py migrate --check
uv run pytest auths/tests/test_auth_002_migrations.py::test_auth_002_forward_upgrade_preserves_browser_refresh
uv run pytest
uv run pytest --cov=auths --cov=workspaces --cov-fail-under=90
uv run ruff check .
uv run ruff format --check .
Set-Location ..
git diff --check
```

The PostgreSQL CI job must run the same forward-upgrade test after its fresh
migration check and before `uv run pytest -m postgresql`. Do not claim upgrade,
row-lock, or race proof from a fresh SQLite migration.

### Interface Contract Handoff Checks

After the accepted Cloud contract is deployed to staging, the Interface owner
runs the existing consumer commands in `allies-interface`:

```powershell
bun run cloud:fetch
bun run cloud:check
bun --filter @allies/cloud-client typecheck
bun run test:run packages/cloud-client/test/native-session-contract.test.ts
```

The Interface test must compile the four new native-session methods and capture
their requests. It separately captures the existing named account methods
through the native bearer preparer and proves the bearer allowlist, public
exclusions, error mapping, refresh reuse, and logout uncertainty. The generated
diff must show the reviewed native routes and fields only. This is a
contract-only AUTH-002 gate; it does not require a development build. INT-008
owns the later iOS and Android callback and session-lifecycle smoke proof.

### Foundry and Runtime Dependency Guard

AUTH-002 has no Foundry work. Before handoff, compare the branch to its `dev`
merge base and inspect added lines in `backend/auths`, `backend/workspaces`,
`backend/config`, `backend/pyproject.toml`, `backend/uv.lock`, deployment jobs,
and CI. Reject the change if it adds a Foundry, Hermes, Fly, Ally-runtime, or
runtime-service import, package, setting, job, route, or deployment reference.

```powershell
$base = git merge-base HEAD origin/dev
git diff --unified=0 "$base...HEAD" -- backend/auths backend/workspaces backend/config backend/pyproject.toml backend/uv.lock .github/workflows docs/operations | rg -n -i '^\+.*(foundry|hermes|fly|ally.runtime|runtime.service)'
```

No output is the required result. A match blocks handoff until reviewers remove
it or prove that it is a test assertion for this boundary. The check does not
authorize a Foundry exception inside AUTH-002.

### Manual Verification Checklist

- Confirm each configured redirect URI is an exact allowlist entry and an exact
  Google registration for its environment.
- Prove that browser and native authorization and token exchange each use only
  their configured callback. Try both callback routes against the wrong
  transaction and confirm rejection.
- Run the Railway forged, missing, rotated, two-prefix, concurrent, multi-worker,
  restart, and cache-outage identity matrix while Google remains disabled.
- Complete new-user and returning-user Google sign-in on iOS and Android.
- Cancel and deny Google consent. Confirm that no Cloud session exists.
- Alter app state, provider state, redirect URI, code verifier, and Cloud code.
  Confirm safe rejection.
- Let the transaction, exchange code, access token, idle refresh limit, and
  absolute refresh limit expire in controlled tests.
- Restore a valid refresh token after app restart, rotate it once, and confirm
  the old token cannot be used.
- Submit two exchange requests and two refresh requests concurrently against
  PostgreSQL. Confirm the documented one-winner behavior.
- Race callback finalization against cleanup before and after claim expiry.
  Confirm the state-machine and protected-deletion results.
- Use the bearer token on `/auths/me`, profile, avatar, and personal Workspace.
  Confirm that a foreign Workspace remains unavailable.
- Log out with valid, expired, and already revoked credentials. Confirm local
  cleanup and server family state.
- Inspect headers, redirects, OpenAPI, responses, application logs, provider
  logs, and analytics for prohibited values.

## Risks and Mitigations

| Risk | Mitigation | Rollback or fallback |
| --- | --- | --- |
| An app or malicious handler intercepts a return URI. | Prefer claimed HTTPS links, require exact redirect binding, use PKCE S256, and keep the Cloud code short-lived and single-use. | Disable the affected redirect entry and native provider. Keep browser auth available. |
| A refactor breaks the accepted browser callback or cookie contract. | Keep native transaction tables and routes separate, add explicit provider callback configuration, and run all browser auth regression tests. | Disable native routes and revert only additive native routing while data remains. |
| Railway forwards a forged or missing requester header. | Require the public-edge anti-spoof proof, exact parser, one shared requester-prefix check per operation, and signed rollout evidence before enablement. | Keep native disabled. Continue browser auth with its existing cookie identity. |
| Callback completion races cleanup or the provider response is lost. | Use the five-state transaction, claim lease, two lock transactions, protected code relation, and PostgreSQL race tests. | Keep native disabled; retain terminal rows and codes for bounded investigation. |
| A browser access token is replayed as a native bearer token. | Store `client_kind` on the family and require transport-kind match on every request. | Revoke affected families and disable bearer acceptance until repaired. |
| Two refresh calls cause a legitimate family revocation. | Require Interface single-flight refresh and test the one-winner Cloud rule. | Clear the local session and require sign-in. Do not weaken reuse detection silently. |
| A token or code enters logs, traces, or analytics. | Use typed safe errors, bounded audit fields, no request-body logging, and explicit redaction tests. | Disable native routes, rotate Cloud signing and digest secrets as required, revoke native families, and follow incident response. |
| Exact mobile app-link domains are not ready. | Keep native auth disabled until domain association files, application identifiers, and exact URIs are verified. | Use exact development custom schemes only in development builds. Do not use them as the production fallback. |
| A lost device keeps a refresh family until expiry. | Keep short idle and bounded absolute limits and use the existing privileged family revocation command. Require an owner decision on this residual risk. | Add a separate remote session-management ticket if the accepted risk is too high. |
| Shared rate-limit cache is unavailable. | Fail closed for new native auth and refresh work. Keep all work bounded. | Valid access tokens work only until their short expiry. Restore cache or disable native auth. |
| Interface and Cloud OpenAPI versions drift. | Publish from staging, pin the snapshot, generate types, and review the generated diff before INT-008 starts. | Keep INT-008 blocked and leave the explicit unavailable session provider in place. |
| A migration labels or breaks an existing browser family. | Test the exact `auths.0002` forward path with a live refresh row on SQLite and PostgreSQL before enablement. | Keep native disabled and roll back code deployment without reversing the additive schema. |
| Bearer injection reaches a public, browser, provider, app-link, or upload URL. | Use the exact method-and-path allowlist and Interface-owned request-capture tests. | Keep INT-008 blocked and leave the mobile provider unavailable. |

## Evidence and Sources

- Nabu: `projects/allies/index.md`
- Nabu: `projects/allies/delivery/now.md`
- Nabu: `projects/allies/delivery/epics/EPIC-00.md`
- Nabu: `projects/allies/delivery/tickets/cloud/AUTH-002.md`
- Nabu: `projects/allies/engineering/specs/interface/AUTH-002-cloud-native-session-contract.md`
- Nabu: `projects/allies/delivery/tickets/interface/INT-008.md`
- Nabu: `projects/allies/engineering/specs/auth-account-foundation.md`
- Nabu: `projects/allies/engineering/specs/interface/index.md`
- Local Cloud: `AGENTS.md`, `ENGINEERING_STYLE.md`, `README.md`, `Makefile`,
  `backend/pyproject.toml`, `.github/workflows/ci.yml`, and
  `docs/templates/PLAN_TEMPLATE.md`
- Local Cloud code: `backend/auths/`, `backend/workspaces/`, and
  `backend/config/`
- Local Interface consumer: `apps/mobile/src/lib/session/session-context.tsx`,
  `apps/mobile/app.json`, `apps/mobile/package.json`,
  `packages/cloud-client/`, and root `package.json`
- RFC 8252, OAuth 2.0 for Native Apps:
  `https://www.rfc-editor.org/rfc/rfc8252.html`
- RFC 9700, Best Current Practice for OAuth 2.0 Security:
  `https://www.rfc-editor.org/rfc/rfc9700.html`
- Google OAuth web-server and policy guidance:
  `https://developers.google.com/identity/protocols/oauth2/web-server` and
  `https://developers.google.com/identity/protocols/oauth2/policies`
- Expo SDK 57 WebBrowser guidance:
  `https://docs.expo.dev/versions/latest/sdk/webbrowser/`
- Railway public networking request-header reference:
  `https://docs.railway.com/networking/public-networking/specs-and-limits`
- Railway edge-network trust path:
  `https://docs.railway.com/networking/edge-networking`
- Visual plan guidance: `https://vercel.com/design.md`, used for hierarchy,
  evidence, responsive behavior, and accessibility with Allies identity.

## Decisions

- Use full planning because this work changes a security boundary and a public
  cross-repository contract.
- Reuse the implemented AUTH-001 user, identity, account bootstrap, JWT,
  refresh-family, audit, throttle, OpenAPI, profile, and Workspace boundaries.
- Add separate native transaction and exchange-code models. Do not overload the
  browser `AuthFlow`, because native flow has no browser cookie or CSRF binding.
- Add a session-family client kind and strict request transport resolution. Do
  not create a parallel native JWT or refresh-token engine.
- Keep the native routes additive under `/api/v1/auths/native`.
- Use a Railway-proven `X-Real-IP` network prefix as the native requester
  identity, HMAC it through the existing Redis throttle helper, and keep native
  disabled until anti-spoof and multi-worker proofs pass.
- Use separate browser and native Google callback settings. Select once in the
  transaction service and make the provider adapter consume that selected
  value unchanged.
- Use the five-state native transaction and protected cleanup order. Do not
  reuse the browser `consumed_at`-before-provider-I/O behavior.
- Make the Interface handoff executable through named client methods, an exact
  bearer allowlist, a complete error map, and an Interface-owned compile test.
- Prove the exact pre-AUTH-002 forward migration on SQLite and PostgreSQL.
- Reject Foundry, Hermes, Fly, and runtime dependencies in the branch diff.
- Keep implementation, Nabu changes, independent adversarial review,
  independent simplicity review, and INT-008 code outside this worker's scope.

## Risks

The detailed risk table above is authoritative. The user accepted the endpoint
contract, lifetimes, logout proof, rate limits, staged requester-identity
trust, bearer allowlist, public exclusions, error mapping, and privileged
revocation fallback. Owner action remains required for exact redirect and
callback values, provider registration, application identifiers, association
files, shared-cache and staging evidence, native enablement, and any OpenAPI
snapshot version change.

## Accepted Decisions and Deferred Setup

On 2026-08-21, the user accepted the endpoint paths, JSON fields, lifetimes,
error behavior, logout proof, rate limits, staged `X-Real-IP` trust chain,
prefix rules, global ceiling, four native-session methods, existing-account
bearer allowlist, public exclusions, error-to-state mapping, and privileged
revocation as the lost-device fallback. The user also accepted the ownership
requirement for shared-cache and staging proof.

The following setup is intentionally deferred until after this Cloud
implementation:

1. Exact production iOS and Android claimed HTTPS return URIs, application
   identifiers, and domain association files.
2. Exact development custom-scheme URIs.
3. Exact local, staging, and production Cloud callback URIs, Google
   registration, and the choice of one or separate Google web clients.
4. The deployment owner who supplies native enablement evidence, shared-cache
   proof, two-worker staging proof, and sanitized smoke evidence.
5. Any required OpenAPI snapshot version change after the Interface handoff.

## Plan

- Durable kickoff brief and full implementation plan:
  `docs/plans/auth-002-native-session-contract.md`
- Synchronized visual HTML plan:
  `docs/plans/auth-002-native-session-contract.html`
- Live Lavish preview: unavailable in the current environment. The static HTML
  review surface preserves the plan's decision path, contract tables, phases,
  validation evidence, risks, and owner gates.
- The existing adversarial and simplicity reviews are reconciled. The user
  approved implementation of the accepted Cloud contract while deferring exact
  redirect and provider setup. The implementation handoff uses `luna_max`.

## Execution Notes

- The Cloud implementation, additive migration, OpenAPI contract, tests, and
  fail-closed configuration were added. No deployment setting, provider
  registration, mobile or Interface source, Foundry source, or Nabu note was
  changed.
- Nabu was available and was used as the canonical source.
- Repository and Nabu evidence agree that AUTH-002 is ready and INT-008 is
  blocked on its accepted, published contract.
- The local Interface consumer still exposes
  `unavailable:native-session-contract-pending`, which matches Nabu.
- The existing Cloud browser session already has most required session
  invariants. AUTH-002 should extend it through explicit client-kind and bearer
  boundaries instead of duplicating it.
- LunaMax implemented the Cloud contract in the feature worktree. Terra-high
  independently reviewed it and identified three issues; all three were fixed
  with regression tests before handoff.
- Follow-up review fixed the two Enkii P2 findings: browser refresh and logout
  retain origin and CSRF protection, while only a valid native bearer can use
  the reviewed native mutations; callback claim and cleanup now re-check row
  existence and deletion eligibility. Google provider response and JWKS reads
  also enforce the flow's absolute deadline, including slow-stream bodies.
- A subsequent review also fixed native error-state and evidence gaps: invalid
  native bearers on profile and avatar mutations return `401 session_invalid`,
  requester-identity failures on native refresh and logout return `503
  auth_unavailable`, and native Workspace self-access and foreign denial are
  covered by HTTP tests.
- The final review also fixed malformed optional bearer handling on logout so a
  valid refresh proof still revokes the family, and added structured audit-log
  redaction coverage for native success, denial, provider failure, throttling,
  unhandled errors, refresh, and logout.
- The remaining review gap is fixed: an invalid or expired native bearer on the
  Workspace route now returns `401 session_invalid`, while an unknown or
  foreign Workspace remains a non-disclosing `404 workspace_denied`. OpenAPI
  publishes the Workspace `401`, and the HTTP test covers that response
  contract.
- Local validation passed: `python -m uv sync --locked`, `python -m uv lock
  --check`, Django checks, migration checks, the forward-upgrade migration
  test, 176 tests, 90.43% coverage, Ruff, formatting, and the
  repository diff check. The make wrappers were also attempted, but they could
  not find `uv` on `PATH`; the equivalent `python -m uv` commands passed.
- The PostgreSQL marker selected nine tests, but all were skipped because no
  PostgreSQL service was available locally. The CI PostgreSQL job includes the
  forward-upgrade test and remains the source of row-lock and concurrency
  proof.
- Railway documentation names `X-Real-IP` as the remote client address. It does
  not replace the required staging anti-spoof proof. Native auth remains
  disabled unless that proof passes and owners record acceptance.
- Native auth remains disabled by default. Exact provider registration,
  application-link values, native enablement, shared-cache proof, and staging
  evidence remain follow-up work after this pull request.
- The synchronized HTML remains a static, condensed review surface. The
  Markdown plan is the complete implementation record.
