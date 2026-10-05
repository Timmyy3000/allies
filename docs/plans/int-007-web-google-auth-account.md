# INT-007 Web Google Auth and Personal Account Plan

## Feature Overview

- Problem: The web foundation can call Cloud and restore a session, but people cannot yet sign in with Google or manage an account. The current session layer also keeps an account DTO outside TanStack Query, ties restoration to the waitlist flag, clears unrelated query data on sign-out, and coordinates refresh only while restoring.
- Target users: A person signing in to Allies on the web and managing their profile, avatar, and Cloud-created personal Workspace. Interface operators also need a release path that separates client correctness from missing Cloud or provider configuration.
- Source docs/specs: Accepted Nabu `projects/allies/engineering/specs/interface/INT-007-web-google-auth-and-account.md` at revision `f4478a0ec56dc9ca97409f62d98a3df45f551e9d6eace6bee0c55f384f61b36f`; Nabu index at revision `ed0914c934877645ac8d28818638013cfca9c0a8bc4bf1907d1c52ad98dae3cf`; linked INT-006, AUTH-001, Interface roadmap, and first product requirements. Repository evidence includes `AGENTS.md`, `ENGINEERING_STYLE.md`, `.agent/napkin.md`, `.agent/kickoff.yaml`, the durable work brief, pinned OpenAPI, current client/session/UI code, CI, tests, installed Next.js 16.2.12 documentation, merged Cloud PR #13, and current Cloud auth implementation.
- Success outcome: Google is the only visible provider. The browser starts, restores, refreshes, and ends the Cloud-owned session without exposing credentials. `/account` shows the profile, avatar, Workspace, and failure states. TanStack Query is the only account DTO cache, fixture-backed checks pass, and live Google proof waits for the required Cloud deployment and staging configuration.

## User Stories

1. As a signed-out person, I want to sign in with Google and return to the intended safe Allies page, so that I can reach my account without handling Cloud credentials.
2. As an account owner, I want to restore or end my session, edit my display name, replace or delete my avatar, and inspect my personal Workspace, so that I can manage the identity Cloud uses for Allies.
3. As a person facing an expired session, provider denial, upload problem, or temporary outage, I want an accurate state and a bounded recovery action that preserves my input, so that I do not mistake failure for success or get trapped in a retry loop.
4. As an Interface operator, I want fixture-backed acceptance separated from live provider and origin proof, so that the client can be reviewed without hiding external release blockers.

## Scope

### In Scope

- Add `/sign-in`, `/auth/return`, and `/account` App Router routes.
- Expose Google as the only sign-in action and make the existing onboarding sign-in affordance a semantic link to `/sign-in` without replacing its authored geometry.
- Validate the final and Cloud return paths as root-relative, bounded, control-character-free paths before use; use `/account` as the fallback.
- Restore the cookie-backed Cloud session through `/api/v1/auths/me`; coordinate a single refresh for concurrent `401` responses and limit each operation to two total invocations.
- Capture the cross-origin `X-CSRFToken` response header in one in-memory owner, validate and rotate it after bootstrap, and inject it into every unsafe auth/account request without reading Interface-origin cookies.
- Give each Cloud operation one replay budget. Its first eligible `401` or `csrf_rejected` consumes the sole replay; a second eligible failure is surfaced without another invocation.
- Make TanStack Query the source of truth for the current account DTO and signed avatar read metadata. Keep session status in context and form/upload state in route-local React state.
- Add display-name edit, private avatar prepare/direct-upload/complete/read/delete, Workspace summary, logout, accurate pending/success/error states, and recovery actions.
- Extend focused cloud-client, session, request, route-component, and account interaction tests using the existing Vitest and Testing Library setup.
- Preserve the current OpenRunde typography, warm white/near-black/orange palette, large rounded controls, authored Ally art, visible focus treatment, responsive behavior, and reduced-motion handling.

### Out of Scope

- Password, email, Apple, Microsoft, or any provider other than visible Google sign-in.
- Provider callback processing in Interface. Google returns to Cloud; Cloud owns `/api/v1/auths/callback/google` and redirects the browser to Interface `/auth/return`.
- Native/mobile authentication, account linking, multi-Workspace switching, invitations, billing, settings beyond display name and avatar, Foundry/runtime work, or onboarding-to-account data migration.
- Copying, proxying, logging, persisting, or rendering HttpOnly cookies, JWTs, refresh values, provider claims, object-store credentials, raw signed URLs, exact upload headers, or raw Cloud error bodies.
- Interface-side authorization rules derived from capability strings. Cloud remains authoritative and permission failures remain visible.
- New state libraries, auth frameworks, route proxies, upload libraries, hashing libraries, generated design systems, or a shared account component abstraction without a second demonstrated consumer.
- Committed browser-level automated end-to-end tests in this slice. Live Google proof is a conditional manual/staging check under the accepted INT-007 scope.
- Cloud implementation changes. Any incompatible Cloud behavior is reported against the Cloud contract.

### Dependencies and Assumptions

- INT-006 is the shipped foundation: Next.js 16.2.12, React 19.2.4, TanStack Query, Zod, Motion, the typed `@allies/cloud-client`, controlled transport, browser credential preparation, session adapter, and normalized errors already exist.
- AUTH-001 makes Cloud the authority for the user, profile, session, personal Workspace, owner membership, capabilities, and private avatar lifecycle.
- The pinned Cloud OpenAPI exposes every accepted endpoint, but two verified contract defects must be resolved or accepted before live release: its Workspace examples still show stale `workspace:manage` instead of the implemented dotted capabilities, and the Cloud presigned PUT returns `Content-Length` among exact headers even though a browser controls that header.
- Cloud PR #13, `fix(auth): return browser OAuth to frontend origin`, merged on 2026-08-21 at 20:30:04 UTC with four checks passing. Live callback proof now waits for that change to reach staging and for provider/origin configuration.
- Staging must have the final Interface origin in its trusted-origin/CORS/CSRF configuration, expose `X-CSRFToken` through CORS, enable Google, register the Google redirect URI to Cloud, use valid cookie attributes for the deployed origins, and allow the exact browser PUT through R2 CORS.
- `NEXT_PUBLIC_CLOUD_API_URL` must be valid whenever auth routes are used. The waitlist flag must not control auth session lifecycle, and the public landing route must not make an unsolicited account request.
- The browser supports `crypto.subtle.digest`, `AbortController`, `fetch`, `File`, and native form/file controls. These platform APIs replace new dependencies.
- Display names use the implemented Cloud rules: trim and collapse whitespace, require 1 to 80 characters, and reject Unicode control characters. Accepted avatar client support is JPEG, PNG, or WebP up to 5 MiB; staging must confirm the deployed Cloud limit because the current OpenAPI does not publish that constraint.
- The narrower accepted INT-007 Google-only slice supersedes broader early product notes that mention additional providers or pre-auth onboarding behavior.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `packages/cloud-client/src/client.ts` | `parseSafeReturnPath` | `function parseSafeReturnPath(value: unknown): string \| null` | String only; 1 to 500 characters; begins with one `/`; rejects `//`, backslashes, control characters, DEL, malformed percent escapes, and unsafe forms after at most eight decode passes | Valid root-relative path or `null` | Pure. `beginSignIn` maps `null` to the existing safe `bad-request` error |
| `packages/cloud-client/src/schemas.ts` and `client.ts` | `csrfTokenSchema`, `getCsrf` | `const csrfTokenSchema: ZodType<CloudCsrfToken>`; `getCsrf(signal?: AbortSignal): Promise<CloudCsrfToken>` | Read the exposed `X-CSRFToken` response header from the `204`; accept only Django-compatible 32- or 64-character ASCII alphanumeric tokens | Validated in-memory token | Missing, unreadable, or malformed header becomes a safe `contract` error; no cookie value is returned or read |
| `packages/cloud-client/src/client.ts` | existing auth/account methods | Existing `beginSignIn`, `refreshSession`, `logout`, `getCurrentAccount`, `updateProfile`, avatar methods, and `getWorkspace` signatures remain public | Continue using generated request shapes and runtime response mappers | Existing view models | No new transport or duplicated API layer. `getCsrf` now returns the validated response header; return-path validation is tightened |
| `apps/web/lib/cloud/csrf-token.ts` | `createCloudCsrfTokenOwner` | `function createCloudCsrfTokenOwner(): { has(): boolean; replace(token: CloudCsrfToken): void; prepare(request: Request): Request; clear(): void }` | One closure-owned token; `prepare` handles auth/account requests and requires a token for `POST`, `PUT`, `PATCH`, and `DELETE` | Prepared credentialed request or `void` for mutations | `replace` atomically rotates the value; `prepare` injects the exact token and `credentials: "include"`; missing token fails before network with safe `security/csrf_unavailable`; no storage, logging, or `document.cookie` access |
| `apps/web/lib/cloud/browser-request.ts` | `prepareBrowserCloudRequest` | `function prepareBrowserCloudRequest(request: Request, csrf: CloudCsrfTokenOwner): Request` | Existing waitlist branch remains separate; all auth/account requests become credentialed and unsafe methods delegate to the in-memory owner | Prepared request | Removes the Interface-origin `csrf_token` cookie branch and `readCookie`; every unsafe auth/account request is header-bound to the owner |
| `apps/web/lib/account/account-query.ts` | `currentAccountQueryOptions` | `function currentAccountQueryOptions(client: Pick<CloudClient, "getCurrentAccount">, runCloudOperation: RunCloudOperation): QueryOptions<AccountViewModel>` | Uses the shared session executor and query request signal | Account query options keyed by `CURRENT_ACCOUNT_QUERY_KEY` | Final unauthorized state signs out; normalized errors remain safe |
| `apps/web/lib/account/account-query.ts` | `avatarReadQueryOptions` | `function avatarReadQueryOptions(client: Pick<CloudClient, "getAvatarRead">, runCloudOperation: RunCloudOperation): QueryOptions<AvatarViewModel>` | Uses a 30-second expiry safety window; while data is valid, `refetchInterval(query)` returns `max(1_000, expiresAt - now - 30_000)`; it returns `false` when there is no valid URL or `errorUpdatedAt > dataUpdatedAt` | Signed avatar read metadata keyed by `AVATAR_READ_QUERY_KEY` | Set `refetchIntervalInBackground: true`; TanStack Query reschedules after new metadata, cancels on observer unmount through the consumed request signal, stops after renewal failure, and resumes after successful manual retry; metadata is never persisted |
| `apps/web/lib/account/account-query.ts` | `removePrivateAccountQueries` | `function removePrivateAccountQueries(queryClient: QueryClient): void` | Current query client | `void` | Removes only account/avatar-private keys; does not clear public waitlist queries |
| `apps/web/lib/session/web-session.ts` | `restore` | `restore(signal?: AbortSignal): Promise<RestoreResult>` | Optional cancellation signal | Signed in with a transient `account`, signed out, or unavailable | Reuses the shared refresh gate; retries `/me` once after one `401`; logout generation wins races |
| `apps/web/lib/session/web-session.ts` | CSRF gates | `ensureCsrf(): Promise<void>`; `refreshCsrf(): Promise<void>` | `ensure` reuses the current owner value or joins one bootstrap; `refresh` always joins/starts a fresh `getCsrf` and replaces the owner only after validation | `void` | One active bootstrap promise deduplicates concurrent callers. Refresh and logout fetch fresh CSRF. Logout clears the owner after local sign-out |
| `apps/web/lib/session/web-session.ts` | `runCloudOperation` | `runCloudOperation<T>(operation: (signal?: AbortSignal) => Promise<T>, options?: { signal?: AbortSignal; csrf?: boolean }): Promise<T>` | Caller operation, optional cancellation, and unsafe-method flag | Operation result | At most two operation invocations. Attempt 1 `401` uses one shared refresh; attempt 1 `csrf_rejected` uses one fresh CSRF bootstrap. Either consumes the sole replay. Any attempt 2 failure surfaces. Bootstrap/refresh failures surface without invoking attempt 2 |
| `apps/web/lib/session/session-context.tsx` | `SessionContextValue` | `{ client; state; restore(); logout(); runCloudOperation() }` | Provider-owned client, shared CSRF owner, and route-owned operations | Status-only session context plus actions | Initial state is always `unknown`; there is no `restoreOnMount` prop or provider effect. Explicit `restore()` moves to `restoring`, writes success to TanStack Query, and removes private queries on signed-out. Logout still wins by generation. No account DTO or CSRF value is exposed through context |
| `apps/web/lib/account/profile-schema.ts` | `profileFormSchema`, `ProfileFormValues` | `const profileFormSchema = z.object({ displayName: normalizedDisplayNameSchema })`; `type ProfileFormValues = z.infer<typeof profileFormSchema>` | Transform by trim/collapsing Unicode whitespace, then validate 1 to 80 characters and reject Unicode category `C` characters | Normalized Zod-inferred form values or field issues | Uses installed Zod; the component keeps the raw draft on recoverable Cloud failure and sends only parsed output |
| `apps/web/lib/account/avatar-upload.ts` | `uploadAvatar` | `async function uploadAvatar(file: File, client: Pick<CloudClient, "prepareAvatarUpload" \| "completeAvatar">, runCloudOperation: RunCloudOperation, signal?: AbortSignal): Promise<AvatarViewModel>` | JPEG/PNG/WebP; 1 byte to 5 MiB; SHA-256 via Web Crypto; prepared HTTPS URL and exact returned headers; `DIRECT_UPLOAD_TIMEOUT_MS = 10_000` | Completed Cloud avatar only after verification | Direct `PUT` uses `credentials: "omit"`; one local controller combines the caller signal and timeout, records the first cause as `caller` or `timeout`, and removes the listener and timer in `finally`; timeout is recoverable and never calls completion |
| `apps/web/app/sign-in/sign-in-client.tsx` | `startGoogleSignIn` | `async function startGoogleSignIn(): Promise<void>` | Safe final return path from server props, default `/account` | No return after top-level navigation | Runs sign-in through `runCloudOperation(..., { csrf: true })`, which captures/injects the cross-origin token, then uses `window.location.assign` only after the external URL validates; duplicate action disabled |
| `apps/web/app/auth/return/auth-return-client.tsx` and `apps/web/app/account/account-client.tsx` | protected entry controllers | `restore(): Promise<void>` through session context | Server-selected safe `returnTo` for return; mounted protected route for account | Replaces with the safe path or renders the account/recoverable state | Each route makes one guarded initial `restore()` call per mounted entry. `unknown` and `restoring` share pending UI, so signed-out controls do not flash. Retry remains explicit after a settled failure; public routes never call restore |

### API and Transport Contracts

No HTTP endpoint is added or changed by Interface. The feature consumes the pinned generated Cloud contract through the existing controlled client. All Cloud API requests use `credentials: "include"`; the direct object-store PUT is the only exception and uses `credentials: "omit"`.

The CSRF token has one owner per `AppProviders` lifetime. `AppProviders` creates it before the Cloud client, closes it over the client's `prepareRequest`, and passes the same owner to `SessionProvider`. `GET /auths/csrf` returns the exposed header to `getCsrf`; the session adapter validates/replaces the owner value. The browser preparer reads that owner for unsafe auth/account requests. It never reads an Interface-origin cookie, and the token never enters React state, Query data, Zustand, browser storage, or logs.

Each `runCloudOperation` call has one operation-wide replay budget. When `csrf: true`, `ensureCsrf` must succeed before attempt 1; a bootstrap failure sends no operation request. An eligible auth failure is exactly a normalized `401`. An eligible CSRF failure is exactly `CloudError.kind === "security" && CloudError.code === "csrf_rejected"`; `origin_rejected` and other security failures never trigger recovery.

| Attempt 1 result | Recovery before the sole replay | Attempt 2 behavior |
| --- | --- | --- |
| Success | None | Not invoked |
| `401` | Join/start one refresh gate; that gate obtains fresh CSRF, calls refresh once, and never recursively recovers itself | Invoke the original operation once. Surface every failure, including `csrf_rejected`, without another bootstrap or invocation |
| `csrf_rejected` | Join/start one fresh CSRF bootstrap and atomically replace the owner value | Invoke the original operation once. Surface every failure, including `401`, without refresh or another invocation |
| Any other failure | None | Not invoked |

Recovery infrastructure calls do not count as operation invocations, but a bootstrap or refresh failure stops the operation without spending a second invocation. Concurrent operations keep separate two-invocation budgets while sharing the active CSRF-bootstrap and refresh promises.

| Consumer | Method and path / event | Authentication and authorization | Request schema | Success response schema | Error responses / retry semantics |
| --- | --- | --- | --- | --- | --- |
| Sign-in page/session gate | `GET /api/v1/auths/csrf` | Trusted browser origin; credentials included | No body | `204` with CORS-exposed `X-CSRFToken` | Validate/capture the header in memory. Missing/invalid header is a contract error; show safe unavailable/retry state and do not send an unsafe request |
| Sign-in page | `POST /api/v1/auths/sign-in/google` | CSRF header plus credentials; Google is hard-coded by typed client | `{ "redirect_to": safeInterfaceReturnPath }` | Envelope data `{ "redirect_url": "https://..." }` | No automatic mutation retry; user may retry after safe error |
| Cloud/provider | `GET /api/v1/auths/callback/google` | Cloud flow cookie/state and provider code | Provider-owned query | `303` to exact trusted Interface origin and saved safe path | Cloud appends `auth_error`; Interface maps only allowlisted categories to copy |
| Return/account | `GET /api/v1/auths/me` | Credentialed Cloud session | No body | Envelope `AccountViewModel` source with user, profile, session, Workspace | Attempt 1 `401` joins one refresh and consumes the sole replay. Any attempt 2 failure surfaces; final `401` becomes signed out |
| Session gate | `POST /api/v1/auths/refresh` | Fresh in-memory CSRF header plus credentialed refresh cookie | No body | `204` | One shared in-flight refresh. It is never wrapped in or recursively calls the operation replay executor |
| Account page | `PATCH /api/v1/auths/me/profile` | Signed-in owner; in-memory CSRF header plus credentials | Zod-parsed `{ "display_name": string }` | Envelope profile `{ "display_name", "avatar_url" }` | Two total operation invocations maximum after the first eligible auth/CSRF failure; preserve raw input and map field issues |
| Account page | `POST /api/v1/auths/me/avatar/uploads` | Signed-in owner; CSRF plus credentials | `{ "content_type", "size", "sha256" }` | Envelope `{ "asset_id", "upload_url", "headers", "expires_at" }` | No generic mutation retry; expired/invalid preparation restarts from prepare on explicit retry |
| Browser to object store | `PUT <prepared upload_url>` | Presigned URL only; no Cloud cookie or auth header | Raw file bytes with returned exact headers | Successful object response; no JSON dependency | `credentials: "omit"`; 10,000 ms timeout combined with caller cancellation; first abort cause wins; no automatic retry or completion after timeout/failure; staging must prove browser-compatible headers/CORS |
| Account page | `POST /api/v1/auths/me/avatar/{asset_id}/complete` | Signed-in owner; CSRF plus credentials | No body | Envelope `{ "asset_id", "url", "expires_at" }` | UI remains uploading/verifying until Cloud success; explicit retry restarts a safe lifecycle if preparation expired |
| Account page | `GET /api/v1/auths/me/avatar/read` | Signed-in owner; credentials | No body | Envelope signed read metadata `{ "asset_id", "url", "expires_at" }` | Cache metadata only. While observed, refetch 30 seconds before expiry; reschedule on new metadata, cancel on unmount, stop automatic renewal after failure, and expose manual retry |
| Account page | `DELETE /api/v1/auths/me/avatar` | Signed-in owner; CSRF plus credentials | No body | `204` | Preserve prior display until success; then invalidate current account and avatar-read queries |
| Account page | `POST /api/v1/auths/logout` | CSRF plus credentials | No body | `204` | Local state always becomes signed out. `serverConfirmed: false` warns that server logout could not be confirmed |

Representative generated-contract exchanges:

```json
{
  "redirect_to": "/auth/return?returnTo=%2Faccount"
}
```

```json
{
  "status": "success",
  "message": "Authentication started",
  "data": { "redirect_url": "https://accounts.google.com/o/oauth2/v2/auth?..." }
}
```

```json
{
  "status": "success",
  "message": "Profile loaded",
  "data": {
    "user": { "id": "usr_example" },
    "profile": { "display_name": "Ada", "avatar_url": null },
    "session": { "id": "ses_example", "expires_at": "2026-08-21T12:00:00Z" },
    "workspace": {
      "id": "wsp_example",
      "name": "Ada's Workspace",
      "role": "owner",
      "capabilities": [
        "avatar.read",
        "avatar.write",
        "profile.read",
        "profile.write",
        "workspace.read",
        "workspace.write"
      ]
    }
  }
}
```

```json
{
  "display_name": "Ada Lovelace"
}
```

```json
{
  "content_type": "image/png",
  "size": 245760,
  "sha256": "64-lowercase-hex-characters"
}
```

```json
{
  "status": "success",
  "message": "Avatar upload prepared",
  "data": {
    "asset_id": "avt_example",
    "upload_url": "https://private-object-store.example/presigned-put",
    "headers": {
      "Content-Type": "image/png",
      "Content-Length": "245760"
    },
    "expires_at": "2026-08-21T12:05:00Z"
  }
}
```

The direct upload is raw bytes, not JSON:

```text
PUT <data.upload_url>
credentials: omit
headers: exactly data.headers, if browser-settable
body: selected File
timeout: 10000 ms
```

The `Content-Length` example reflects current Cloud implementation evidence, not a promise that browser `fetch` can set the header. Implementation must verify this in staging before changing or filtering any returned header. If the browser cannot execute the signed request, Cloud must publish a browser-compatible preparation contract.

There is no pagination, filtering, or Interface idempotency key in this slice. Profile, avatar, and logout mutations have no general retry beyond the one shared operation replay budget. The direct PUT is never automatically retried; an explicit user retry starts again at prepare so it receives a fresh signed contract. The pinned API version remains `0.1.0`; additive unknown response fields are ignored by existing allowlisted mappers, while missing or unsafe required fields fail as a contract error.

### Schema and Data Shapes

| Schema / model | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- |
| `AccountViewModel` | `packages/cloud-client/src/mappers/account.ts` | `userId`, `displayName`, `avatarUrl`, `session`, `workspace` | `avatarUrl` nullable; all identifiers and Workspace fields required | External URLs must be HTTPS and credential-free; unknown Cloud fields are not exposed | Existing mapper remains the sole account DTO mapper |
| `CloudCsrfToken` | `packages/cloud-client/src/schemas.ts` | validated string from `X-CSRFToken` | Required only in memory; no default or persistence | Exactly 32 or 64 ASCII alphanumeric characters, matching Django token formats | Replaces the Interface-origin cookie read; never exposed to feature components |
| `SessionState` | `apps/web/lib/session/web-session.ts` | `signed-out`, `signed-in`, or `unavailable` | Status required; no account field | Adapter/session result after restoration or logout | Removes the existing duplicate context-owned DTO |
| `RootSessionState` | `apps/web/lib/session/session-context.tsx` | `unknown` or `restoring`, plus `SessionState` | Starts as `unknown`; status required; no account field | Context value observed by routes | No provider configuration selects an initial branch. `LogoutResult.serverConfirmed` remains a separate action result, not cached session state |
| Current account query | `apps/web/lib/account/account-query.ts` | key `['account', 'current']`; value `AccountViewModel` | Present only after authenticated fetch/restore | Cloud response is authoritative; mutation success patches known fields or invalidates | Remove on signed-out/logout; do not clear public query data |
| Avatar read query | `apps/web/lib/account/account-query.ts` | key `['account', 'avatar', 'read']`; value `AvatarViewModel` | URL nullable/expiring; 30-second renewal window | Never persisted; dynamic observed-query interval renews before expiry, reschedules on success, stops after failure, and cancels on unmount | Uses existing QueryClient scheduling and cancellation, not a second timer/store abstraction |
| `ProfileFormValues` | `apps/web/lib/account/profile-schema.ts` | `z.infer<typeof profileFormSchema>` with `displayName: string` | Required parsed output; route keeps the raw draft separately | Zod transforms trim/collapsed whitespace, then checks 1 to 80 characters and Unicode category `C` rejection | No custom result union; Cloud field issues remain authoritative after local parse |
| `AvatarActionState` | route-local in `account-client.tsx` | selected `File`; `idle/preparing/uploading/verifying/deleting/success/error` | File retained on recoverable failure; the UI may derive safe filename and status text | Completion is displayed only after Cloud verifies; prior server avatar remains until success | No browser persistence; no signed metadata in Zustand/storage |
| Workspace context | nested in `AccountViewModel` from `/auths/me` | `id`, `name`, `role`, `capabilities[]` | Required, Cloud-authored | Display values as account context. Do not infer permission grants or hide failures from stale example strings | Do not make a redundant `/workspaces/{id}` request for the same page load |
| Cloud OpenAPI metadata | existing pinned/generated files | version, source URL, SHA-256, generated types | Existing files remain required | Regeneration must be clean under LF checkout and Bun 1.2.20 | No schema edit is planned; stale examples are raised to Cloud |

No database, migration, server-side session store, feature flag payload, or browser-persisted schema is added.

### Frontend Interaction Shapes (if applicable)

| UI entry point | Hook / action signature | State shape and transitions | API input/output mapping | Loading, error, empty, and permission behavior |
| --- | --- | --- | --- | --- |
| Existing onboarding sign-in affordance | Next `Link` to `/sign-in` | Static link with native focus/activation | No API call | Remains usable when Cloud is unavailable; sign-in route owns service errors |
| `/sign-in` | `startGoogleSignIn()` | `idle -> starting -> navigating \| error` | Safe final path -> `runCloudOperation` CSRF bootstrap/injection -> Cloud redirect URL | One Google button, disabled while starting, status announcement, retry after error, no provider list; a missing/invalid CSRF header sends no POST |
| `/auth/return` | one guarded initial `restore()` | `unknown -> restoring -> signed-in redirect \| signed-out \| unavailable` | Safe selected query values -> `/me` -> account query -> `router.replace` | `unknown` and `restoring` render the same pending state; provider denial uses allowlisted copy; retry restoration; signed-out action links to `/sign-in`; raw query text never rendered |
| `/account` route guard | one guarded initial `restore()` and current-account query | `unknown -> restoring -> signed-in \| signed-out \| unavailable` | `/me` -> `AccountViewModel` | `unknown` and `restoring` render the same skeleton/status, preventing a signed-out flash; sign-in CTA appears only after unauthorized settles; retry when unavailable; stale private data not shown after sign-out |
| Profile form | `saveDisplayName()` | `pristine/dirty -> saving -> saved \| error` | raw draft -> `profileFormSchema.safeParse` -> `updateProfile` -> patch/invalidate current account | Zod field message, preserved raw input, duplicate save disabled, announced saved state, focus moved to the field on validation failure |
| Avatar form | `replaceAvatar(file)` and `removeAvatar()` | `preparing -> uploading -> verifying -> success \| error`; delete has its own pending state | file metadata/SHA -> prepare -> 10-second bounded direct PUT -> complete -> query invalidation | Native labelled file input; type/size errors before network; timeout and network failure preserve the previous avatar/file and offer retry; caller cancellation stays silent; completion requires Cloud verification |
| Mounted avatar read | observed `avatarReadQueryOptions` | `ready -> renewing -> ready \| renewal-error` | signed metadata expiry -> scheduled query refetch -> replacement metadata | Refreshes 30 seconds before expiry; query observer unmount cancels; new metadata reschedules; failure stops the interval and offers manual retry without a tight loop |
| Workspace summary | no mutation | renders authoritative nested `/me` data | `workspace.id/name/role/capabilities` -> plain view | No inferred permission gate; empty capabilities render an honest unavailable/none state, not guessed defaults |
| Logout | `logout()` | `idle -> ending -> signed-out` with confirmed/unconfirmed result | CSRF -> Cloud logout -> private query removal -> route replacement | Always leaves local signed-in UI. If Cloud confirmation fails, announce that server logout was not confirmed and offer sign-in/retry guidance |

Next.js route boundaries follow the installed 16.2.12 guidance: pages remain Server Components by default; browser actions live in narrow Client Components. `/sign-in` and `/auth/return` read the promise-based `searchParams` on the server, select only safe values, and pass them as props. This avoids using `useSearchParams` and an extra Suspense/CSR boundary. Navigation uses `Link` for user links and `router.replace` only for the already-validated local path.

## Phases

### Phase 1 - Lock the browser contract and session ownership

- Goal: Make safe redirects, bounded auth recovery, and TanStack Query ownership correct before adding account UI.
- Work items:
  - Export and test the strict safe return-path parser in `packages/cloud-client/src/client.ts`; keep Google hard-coded in `beginSignIn`.
  - Add `apps/web/lib/account/account-query.ts` with private query keys/options and targeted removal.
  - Change `getCsrf` to validate and return the CORS-exposed response header. Add the one-instance in-memory CSRF owner, wire it through `AppProviders`, the browser request preparer, and the session adapter, and delete the Interface-origin cookie read.
  - Refactor `apps/web/lib/session/web-session.ts` so restoration and Cloud operations share one CSRF-bootstrap gate, one refresh gate, an operation-wide two-invocation budget, abort propagation, and logout-wins generation handling.
  - Refactor `session-context.tsx` to store only status, initialize unconditionally as `unknown`, write restored account data to the query cache, and remove only private account queries. Delete `restoreOnMount`, its conditional initialization, early-return branch, provider prop, and mount effect. Keep logout generation/race handling.
  - Make `AppProviders` pass no restoration configuration. Public routes never call `restore()` and remain free of `/me`; `/auth/return` and `/account` own their initial restoration.
  - Extend Cloud client, token-owner/browser request, session adapter, context, and provider tests before route work. Cover no readable cookie, invalid/missing header, token replacement, both compound failure orders, and concurrent exact call counts.
- Impacted files/systems: `packages/cloud-client/src/client.ts`, `schemas.ts`, `index.ts`, `packages/cloud-client/test/client.test.ts`; `apps/web/lib/cloud/csrf-token.ts`, `browser-request.ts`; `apps/web/lib/account/account-query.ts`; `apps/web/lib/session/web-session.ts`, `session-context.tsx`; `apps/web/app/providers.tsx`; and their existing/new focused tests.
- Exit criteria: Unsafe return paths fail closed; every unsafe auth/account request uses the validated in-memory token with no cookie read; concurrent operations share recovery gates but each invoke the original operation at most twice; both compound failure orders stop after attempt 2; logout wins concurrent work and clears the token; context starts `unknown` with no provider restore effect or configuration; account DTOs exist only in Query cache; public queries survive sign-out.

### Phase 2 - Add sign-in and return routes

- Goal: Provide an accurate Google-only browser flow that restores the Cloud session and returns only to a safe local route.
- Work items:
  - Add server pages and narrow Client Components at `apps/web/app/sign-in/` and `apps/web/app/auth/return/` with route-local styles.
  - Map a small allowlist of known callback categories such as provider denial/unavailability to product copy, with one generic fallback. Never display the raw query value.
  - Start Google sign-in through `runCloudOperation(..., { csrf: true })`, which bootstraps and injects the exposed cross-origin token, then navigate the top-level browser only after the external HTTPS URL mapper succeeds.
  - On return, invoke context `restore()` once per mounted route entry, populate the account query, and replace with the safe final path. Use a route-local guard so React effect re-runs do not start another initial restore. Render `unknown/restoring` as one pending state, then signed-out, unavailable, and retry states in place.
  - Convert only the existing onboarding sign-in text into a semantic `Link` while preserving its current dimensions and placement.
- Impacted files/systems: `apps/web/app/sign-in/page.tsx`, `sign-in-client.tsx`, `sign-in.module.css`; `apps/web/app/auth/return/page.tsx`, `auth-return-client.tsx`, `auth-return.module.css`; `apps/web/app/(onboarding)/_components/sign-in.tsx`; focused route/component tests.
- Exit criteria: Google is the sole provider; no unsafe path reaches Cloud or `router.replace`; duplicate starts are blocked; provider/restore failures are safe and recoverable; successful restoration lands on `/account` by default.

### Phase 3 - Build the personal account experience

- Goal: Let a signed-in owner manage display name and avatar and inspect Workspace context without duplicating Cloud truth.
- Work items:
  - Add `/account` as a server page with one route-local Client Component and responsive module CSS matching the current Interface tokens and OpenRunde typography.
  - Invoke context `restore()` once per mounted `/account` entry through the same route-local guard, then load/render profile, current avatar, session state, Workspace name/role/capabilities, and logout. Keep `unknown/restoring` pending until the explicit restore settles.
  - Add `profileFormSchema` with installed Zod and infer `ProfileFormValues`; keep the raw draft locally, send only parsed/normalized output, and patch or invalidate only after Cloud success.
  - Before wiring live upload, run a minimal browser staging probe against the prepared header set and R2 CORS. If `Content-Length` cannot be sent as returned, file the Cloud defect and keep live avatar replacement behind that release blocker; do not filter or rewrite signed headers in Interface.
  - Add avatar type/size validation, SHA-256 calculation with Web Crypto, prepare, direct credential-free upload, Cloud completion, signed read query, delete, and abort cleanup once the browser contract is confirmed. Retain the selected `File` for retry and the prior Cloud-confirmed avatar until completion succeeds; derive safe filename/status text if useful. Bound the raw PUT at 10 seconds, let the first caller-abort/timeout cause win, and clean its timer/listener on every outcome. Fixture-backed client orchestration may proceed while staging is blocked.
  - Configure the avatar read query to renew 30 seconds before expiry while observed, reschedule from replacement metadata, cancel on unmount, and stop automatic renewal after failure until manual retry succeeds.
  - Invalidate the current-account and avatar-read query keys only after verified completion or deletion. Retain the prior server avatar and selected local file on recoverable failures.
  - Verify native controls, semantic labels, visible focus, `aria-live` status, keyboard order, narrow-screen reflow, and reduced-motion behavior.
- Impacted files/systems: `apps/web/app/account/page.tsx`, `account-client.tsx`, `account.module.css`; `apps/web/lib/account/profile-schema.ts`, `account-query.ts`, `avatar-upload.ts`; route/helper/component tests. Existing `AllyAvatar` may be reused only if it faithfully supports a user image and its accessible name; do not force a product-avatar use it was not designed for.
- Exit criteria: Zod profile boundaries and avatar lifecycle fixtures cover success and recoverable failures; a stalled direct PUT times out and cleans up; mounted-page fake-clock tests prove pre-expiry renewal, rescheduling, cancellation, and failure recovery; the direct upload contract is either confirmed in a browser or recorded as a Cloud release blocker; Workspace uses `/me` data without a duplicate fetch; no private data enters context/Zustand/storage/log output; every displayed completion is backed by Cloud success.

### Phase 4 - Verify contracts, accessibility, and release gates

- Goal: Produce repeatable repository evidence and clearly separate implementation acceptance from external live proof.
- Work items:
  - Run the locked repository contract, unit/component, type, lint, and production build commands under Bun 1.2.20 and an LF checkout.
  - Verify staging direct upload in a real browser before acceptance. If `Content-Length` or R2 CORS prevents the returned exact-header PUT, file a Cloud contract defect and keep live avatar acceptance blocked rather than dropping a signed header in Interface.
  - Verify the pinned Workspace example drift with Cloud. Client tests use the actual dotted capability set but do not make permissions depend on example strings.
  - After merged Cloud PR #13 reaches staging, run the manual local/staging Google flow with an authorized synthetic account and final trusted-origin/provider configuration.
  - Inspect sign-in, return, account, all error states, keyboard/focus behavior, announcements, narrow layouts, and reduced motion. Confirm network/storage/log panels contain no credentials, raw errors, signed URL/header output, or provider claims.
- Impacted files/systems: Repository validation commands, Railway preview/staging deployment, Google provider/origin configuration, and R2 CORS. No Interface proxy or Cloud patch is introduced.
- Exit criteria: Fixture-backed checks pass and external prerequisites are either proven or named as release blockers with exact owner/system. Live Google and avatar evidence is recorded only when the deployed contracts support it.

## Acceptance Criteria

1. `/sign-in` shows one Google action and no password or second provider; the existing onboarding sign-in affordance reaches it through a semantic link.
2. Every final/return path is validated before use. Absolute, protocol-relative, backslash, control-character, over-500-character, malformed encoded, and repeatedly encoded unsafe paths fall back or fail closed.
3. Browser Cloud calls include credentials without exposing cookie values. `getCsrf` validates the exposed response header; one in-memory owner rotates and injects it into every unsafe auth/account request; a missing token fails before network; no Interface-origin cookie is read. No password, provider token/claim, JWT, refresh value, signed URL/header, raw Cloud error body, object credential, or CSRF value enters local/session storage, React/Query/Zustand state, logs, analytics, or rendered text.
4. Session context starts as `unknown`; it has no provider-wide restore mode or mount effect. `/auth/return` and `/account` each invoke the explicit `restore()` exactly once per mounted entry, write the restored account to TanStack Query, and render `unknown/restoring` without a signed-out flash. Public routes send no `/me`; callback errors use safe copy and navigation uses only the validated local path.
5. Each Cloud operation has two total invocation slots. Attempt 1 `401` or `csrf_rejected` consumes the sole replay through the matching shared recovery gate; attempt 2 never triggers another recovery. Ordered `401 -> csrf_rejected` and `csrf_rejected -> 401` cases surface the second failure at exactly two operation calls. Concurrent calls share bootstrap/refresh work but keep separate two-call budgets. Logout remains the final session action, clears the in-memory CSRF value and private account state locally, and wins even when the server cannot confirm it.
6. TanStack Query is the sole account DTO and signed-avatar metadata cache. Session context stores status/actions only, route-local React state owns interaction, and sign-out does not clear unrelated public waitlist queries.
7. Display-name editing uses installed Zod to trim/collapse whitespace, enforce the post-normalization 1-to-80-character bound, reject Unicode category `C` characters, infer `ProfileFormValues`, disable duplicate submission, preserve the raw draft on recoverable failure, expose field/server errors safely, and update/invalidate the current-account query only after success.
8. Avatar replacement validates JPEG/PNG/WebP and the supported size, hashes with Web Crypto, prepares through Cloud, uploads only to the returned HTTPS URL with `credentials: "omit"` and the verified exact header contract, bounds the raw PUT at 10 seconds, deterministically distinguishes timeout from caller cancellation, cleans timer/listener resources, calls completion only after PUT success, and retains the previous avatar until Cloud verification.
9. Avatar read metadata is not persisted. While the account query is observed, it renews 30 seconds before expiry, reschedules after new metadata, cancels on unmount, and stops after a failed renewal until an explicit retry succeeds. Replace/delete invalidates the current account and avatar-read keys; renewal, delete, and upload failures do not claim a changed avatar.
10. The account page shows Cloud-authored Workspace ID/name/role/capabilities from `/auths/me`, makes no redundant Workspace request for the same view, and does not infer authorization from stale example strings.
11. Sign-in, return, account, forms, upload, logout, error, and retry states work with keyboard input, visible focus, semantic labels/headings, text status announcements, 320-pixel-wide layouts, zoom, and reduced motion without color-only meaning.
12. `bun run cloud:check`, `bun run typecheck`, `bun run test:run`, `bun run lint`, and `bun run build:web` pass in the repository's pinned Bun 1.2.20/CI conditions. Live Google and direct-avatar proofs are either recorded after prerequisites deploy or listed as external release blockers without weakening fixture-backed acceptance.

## Backend Considerations (if applicable)

Interface does not add or change a backend in this plan. Cloud owns persistence, provider callbacks, session rotation, CSRF/origin checks, Workspace authorization, and private object storage. The implementation must not hide a Cloud mismatch behind an Interface proxy or alternate contract.

### Query Optimization Plan

- Hotspots/endpoints: Not applicable to Interface database queries. On the client, use the single `/auths/me` response for profile, session, and Workspace summary rather than immediately calling `/workspaces/{id}`.
- Query-shape choices (`select_related`, `prefetch_related`, aggregates, pagination): Not applicable; no Cloud ORM change is authorized.
- Expected query-count change: One `/auths/me` request for restoration/account load, plus only user-triggered mutation/avatar requests. Concurrent unauthorized requests may add one shared CSRF/refresh pair.
- Measurement/monitoring plan: Assert client call counts in adapter/query tests and inspect the browser network panel during manual verification. Any backend query-count concern is filed in `allies-cloud`.

### N+1 Prevention

- Relation access map: Not applicable in Interface. `/auths/me` already returns the one profile/session/Workspace aggregate needed by this page.
- Prefetch/select plan per endpoint/service: Not applicable; no backend relation access is introduced.
- N+1 regression guardrails: Client tests assert that rendering the Workspace summary does not call `getWorkspace` after a successful `/me` response.

### Detailed Unit Test Cases

- Happy path: Existing Cloud endpoint methods and mappers remain covered; Interface tests cover restore, profile update, avatar prepare/upload/complete/read/delete, and logout orchestration.
- Validation and bad input: Unsafe return paths, control characters, display-name bounds/controls, avatar MIME/size/SHA, unsafe external URLs, stale/expired upload preparation, and malformed Cloud envelopes fail closed.
- Auth/RBAC boundaries: Final `401` becomes signed out; `403` is rendered as a permission failure without guessed capability logic; raw capability examples never grant an action.
- Idempotency/retry behavior: Profile/avatar/logout mutations have no general automatic retry. Tests prove two total operation invocations, `401 -> csrf_rejected` and `csrf_rejected -> 401` terminal behavior, shared gate call counts under same-kind and mixed concurrency, and no completion or automatic PUT retry after object failure.
- Failure-path behavior: Missing/malformed exposed CSRF header, missing in-memory token, network, timeout, server, contract, CSRF, provider-return, object-store, avatar-renewal, and unconfirmed-logout states preserve safe user data and expose one recovery action.

## Frontend Considerations (if applicable)

### Data Path

- User action entry: Existing onboarding sign-in link or direct `/sign-in`; Google button; `/auth/return`; protected `/account`; profile/avatar/logout controls.
- Client route/component: Server `page.tsx` selects safe search params and renders a narrow Client Component. `/account` uses route-local client interaction state.
- Client API route/proxy: None. The browser calls the configured Cloud base URL through `@allies/cloud-client`; the object PUT goes directly to the returned external URL.
- Backend endpoint: Cloud `/api/v1/auths/*` and the prepared object-store PUT only.
- Response -> UI model mapping: Generated OpenAPI request types plus Zod header/form/response validation -> `AccountViewModel`/profile/avatar view models -> TanStack Query -> route component.
- Error/loading/retry path: Controlled transport -> normalized `CloudError` -> operation-wide two-invocation executor -> query/component state -> safe state-specific copy and user-initiated retry. A missing CSRF token stops before the unsafe network call; raw responses stop at the mapper/error boundary.

### State Management Considerations

- State ownership by layer (local/hook/context/store): Cloud owns durable account/session/Workspace/avatar truth; one provider-lifetime closure owns the current CSRF header value; TanStack Query owns mapped Cloud DTOs and observed avatar renewal; session context owns status and bounded actions; route-local React owns raw form/file/pending/focus state; existing onboarding Zustand remains unrelated.
- Source of truth vs derived state: Current account query is authoritative for rendered account data. Dirty form value, selected file, safe filename/status text, and formatted capability labels are derived or ephemeral. The prior Cloud-confirmed avatar remains rendered until completion succeeds.
- Caching/invalidation approach: Stable private query keys, no browser persistence, targeted removal on signed-out/logout, patch known profile success or invalidate, invalidate account/avatar read after completion/delete, and a dynamic observed-query interval that renews signed metadata 30 seconds before expiry and stops after renewal failure.
- Concurrency and dedupe handling: One in-memory CSRF owner, one active CSRF-bootstrap promise, one refresh promise, two invocation slots per operation, one restore generation, logout abort/generation priority, duplicate form/action disabling, first-cause direct-PUT abort handling, and TanStack Query request dedupe/cancellation. No queue, mutex library, global credential store, upload store, or custom renewal scheduler.

## Test Plan

- Unit tests:
  - Extend `packages/cloud-client/test/client.test.ts` for strict return paths, Google-only start, generated request shapes, unsafe external URL rejection, valid 32/64-character exposed CSRF headers, and missing/malformed-header contract errors.
  - Add `csrf-token.test.ts` and replace cookie-oriented `browser-request.test.ts` cases. Start with no readable `document.cookie`; prove bootstrap capture, exact header injection on every unsafe auth/account method, no header on safe methods, no network call without a token, atomic token replacement, waitlist isolation, and clearing on logout.
  - Extend `apps/web/lib/session/web-session.test.ts` for `csrf_rejected` token replacement, `401 -> csrf_rejected`, `csrf_rejected -> 401`, bootstrap/refresh failure before replay, final unauthorized, abort, and logout races. Assert exactly two operation calls in each compound case, one shared refresh for concurrent `401`s, one fresh bootstrap for concurrent CSRF failures, and exact gate/operation counts for mixed concurrent failures.
  - Replace `restoreOnMount`, conditional-initialization, provider-effect, and duplicated mount-race tests. Keep focused `session-context.test.tsx` coverage for initial `unknown`, explicit `restoring` transition, targeted query write/removal, and logout generation priority. Keep `providers.test.tsx` coverage for one shared CSRF-owner instance, no provider-driven `/me` on public routes, and no Interface-origin cookie dependency.
  - Add `profile-schema.test.ts` for whitespace normalization, 1/80 accepted boundaries, empty/81-character failures, Unicode category `C` rejection, inferred parsed output, and raw draft preservation after Cloud failure.
  - Add avatar upload helper tests for native hash, exact verified headers, `credentials: "omit"`, 10,000 ms never-settling timeout, caller abort before timeout, timeout before later caller abort, resolved/rejected cleanup, expired preparation, no completion on failure, and explicit retry restarting prepare.
  - Add fake-clock mounted-component/query tests for pre-expiry avatar renewal, successful metadata rescheduling, unmount cancellation, metadata-change cancellation, one existing query retry under the shared policy, stopped scheduling after final renewal failure, safe visible recovery, and manual-retry resumption.
- Integration/API tests:
  - Component tests for sign-in start/error/duplicate guard; exactly one initial `restore()` from `/auth/return` and `/account`; `unknown/restoring` pending UI with no signed-out flash; return error mapping/safe replace; profile preservation; avatar state sequence with selected-file retry and prior confirmed avatar retention; Workspace rendering; and accurate logout status.
  - Use injected fetch/client fixtures and the pinned generated types. Assert exact operation/bootstrap/refresh/PUT counts, first abort cause, credentials modes, headers, timers/listener cleanup, cache scheduling/effects, and absence of raw sensitive strings.
  - Do not add a browser E2E framework or committed provider automation for this accepted slice.
- Regression checks:
  - Existing onboarding/waitlist flow and public Query data remain intact after session-context changes. Public routes issue no `/me`, and each protected entry route starts exactly one initial restore action.
  - Existing Cloud client timeout/size/error mapping, waitlist request isolation, logout-race, and query retry tests continue to pass after removing the auth-cookie CSRF branch.
  - Onboarding layout screenshots/reference geometry are not broadly rewritten; only the sign-in affordance semantics/navigation change.
  - `cloud:check` remains a clean generation check. On Windows, distinguish CRLF checkout hash drift from a real pinned-schema change and rely on LF CI/pinned Bun for acceptance.
- Manual verification checklist:
  - Inspect `/sign-in`, `/auth/return`, `/account`, unknown/restoring, signed-out, unavailable, provider-denied, field-error, upload-error, deleting, saved, and unconfirmed-logout states. Confirm protected entry has no signed-out flash.
  - Use keyboard only; confirm order, visible focus, button disabling, file input label, error focus, live announcements, and no focus loss after rerender.
  - Check 320, 768, and wide desktop widths, 200% zoom, long Workspace/display names, dark OS preference against the app's intentional light surface, and reduced motion.
  - Inspect browser network/application/console/analytics output. Confirm credentialed Cloud calls, credential-free object PUT, no client storage credentials, no raw errors, and no signed URL/header logging.
  - After merged Cloud PR #13 reaches staging and configuration is confirmed, sign in with an authorized synthetic Google account from each admitted Interface origin. Verify exact return path, exposed CSRF header capture/injection with no Interface cookie read, session cookie behavior, refresh `/account`, and logout.
  - In staging, perform replace/read/delete with a non-sensitive test image. Verify returned headers are browser-settable, R2 CORS accepts PUT, completion gates success, read URL expires, and delete removes access.
- Commands:
  - `bun install --frozen-lockfile`
  - `bun run cloud:check`
  - `bun run typecheck`
  - `bun run test:run`
  - `bun run lint`
  - `bun run build:web`
  - Run these with Bun 1.2.20, matching `packageManager` and CI. The planning workstation currently resolves Bun 1.3.14, so its successful frozen install is environment evidence, not the final locked validation.

## Risks and Mitigations

- Risk: Merged Cloud PR #13 has not reached staging, or staging lacks the final trusted origin, provider redirect URI, cookies, exposed CSRF header, or CORS configuration.
- Mitigation: Keep fixture-backed client acceptance independent; block only live proof/release; record the exact missing deployment/configuration evidence and owner.
- Rollback/fallback: Leave sign-in unavailable with clear retry/service copy. Do not introduce an Interface callback proxy or weaken origin validation.

- Risk: Cloud preparation returns `Content-Length` as an exact signed PUT header, but browser Fetch controls that header; current OpenAPI examples omit it.
- Mitigation: Make a real-browser staging PUT a pre-implementation/release gate. If it fails, raise a Cloud contract defect so preparation returns a browser-compatible signed header set and CORS policy.
- Rollback/fallback: Keep avatar replacement disabled/unavailable while profile, Workspace, session, and logout remain usable. Never silently drop a signed header or send Cloud cookies to storage.

- Risk: A direct object-store PUT can stall indefinitely or a late timeout can race a caller cancellation and report the wrong recovery state.
- Mitigation: Bound the PUT with `DIRECT_UPLOAD_TIMEOUT_MS = 10_000`, combine it with the caller signal through one local controller, record the first abort cause, and remove the timeout/listener in `finally`. Cover both race orders, never-settling fetch, and resolved/rejected cleanup with fake timers.
- Rollback/fallback: Preserve the prior avatar and selected file, skip completion, and offer an explicit retry that restarts at Cloud prepare.

- Risk: Signed avatar metadata can expire on a mounted account page, or a failed renewal can create a tight request loop.
- Mitigation: Let the existing QueryClient schedule renewal 30 seconds before expiry, recompute from replacement metadata, consume its cancellation signal, and return `false` after a final renewal failure until manual retry succeeds. Prove timing, rescheduling, unmount cancellation, and failure behavior with fake-clock mounted-page tests.
- Rollback/fallback: Keep the last successfully loaded image or a safe placeholder visible with a manual retry action. Do not persist or repeatedly fetch expired metadata.

- Risk: Pinned OpenAPI Workspace examples advertise stale `workspace:manage`, while Cloud code and accepted AUTH-001 use dotted capabilities.
- Mitigation: Raise the example drift to Cloud and test mapping with actual dotted values. Render capabilities as Cloud context but do not use example strings as client-side authorization.
- Rollback/fallback: Display Workspace identity and role with an explicit capability-unavailable state, and let endpoint permission responses remain authoritative.

- Risk: Cross-origin CSRF capture or compound auth/CSRF recovery can omit the header, reuse a rejected token, run an operation a third time, or allow stale restoration to win after logout.
- Mitigation: One provider-lifetime token owner with no cookie/storage path, validated replacement, pre-network missing-token failure, shared bootstrap/refresh gates, two total operation invocations, abort propagation, generation checks, logout priority/clear, and ordered/concurrent exact-count tests.
- Rollback/fallback: On final failure, transition to signed out/unavailable and require an explicit user retry rather than continuing automatic recovery.

- Risk: A signed avatar URL, returned upload headers, raw Cloud error, or account DTO can leak through logs, state persistence, analytics, or broad debug output.
- Mitigation: Allowlisted mappers, no persistence, no URL/header logging, safe copy mapping, targeted cache removal, scheduled renewal only inside Query, and negative assertions over rendered/logged/storage output.
- Rollback/fallback: Remove the affected rendering/action and show a generic safe failure until the boundary is corrected.

- Risk: A local preview, hash, or generated diff appears dirty only because Windows checked the pinned JSON out as CRLF or because local Bun is 1.3.14 instead of the repository's 1.2.20.
- Mitigation: Run final commands in CI-equivalent LF conditions with pinned Bun and compare generated content, not an unexplained working-tree hash.
- Rollback/fallback: Do not edit OpenAPI metadata to match a local line-ending hash; use CI evidence or a clean LF worktree.

- Risk: New account screens flatten or overwrite the authored onboarding identity, become card-heavy, or introduce a parallel token system.
- Mitigation: Reuse current OpenRunde fonts, palette, focus rules, radii, spacing, and Ally assets; use semantic layout and restrained surfaces; change the existing onboarding file only to add link semantics.
- Rollback/fallback: Remove decorative/extracted UI and return to the smallest route-local composition that preserves every state and accessibility requirement.

## Kickoff and Review History

- 2026-08-21: Kickoff created branch `web/feat/int-007-google-auth-account` at `fc167d5dfe5086f009be44d228b457def3b539e9`, the isolated Forest worktree, and the durable brief. Implementation delegation is `always`; configured workers are `sol_planning_worker`, `sol_review_worker`, and `luna_execution_worker`.
- 2026-08-21: Full planning inspected the accepted Nabu spec and relevant linked notes, repository policies and implementation, installed Next.js docs, pinned/generated Cloud contract, Cloud implementation evidence, Cloud PR #13/checks, CI/test commands, and current Interface visual system.
- 2026-08-21: Ponytail full mode kept the plan on the existing Cloud client, session adapter, QueryClient scheduling, installed Zod, route-local React state, native Fetch/Web Crypto, and three direct routes. The accepted safety mechanisms add one closure-owned CSRF value and reuse existing timeout/query patterns; no new dependency, proxy, generic auth framework, second DTO store, custom scheduler, redundant Workspace request, or speculative shared UI layer is planned.
- 2026-08-21: Independent adversarial review returned one blocker, four major findings, and one minor evidence correction. Every finding was accepted and integrated: cross-origin CSRF ownership, one operation-wide replay budget, bounded direct PUT timeout, proactive avatar metadata renewal, the accepted Zod schema, and current Nabu/merged PR evidence.
- 2026-08-21: Independent simplicity review recommended two reductions and both were accepted. The final plan removes provider-wide `restoreOnMount`, its mount effect/configuration/duplicate branches and tests, and the unrequired avatar preview object URL lifecycle. Protected routes now own one explicit initial restore while public routes stay request-free; selected-file retry and the prior confirmed avatar remain. All adversarial safeguards and protected complexity are unchanged.
