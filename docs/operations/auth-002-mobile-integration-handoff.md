# AUTH-002 Mobile Integration Handoff

## Status

The Cloud side of AUTH-002 is merged and available behind the feature flag
`ALLIES_AUTH_NATIVE_ENABLED`, which defaults to `false`. Mobile integration
must target the versioned native routes below; it must not emulate browser
cookies or call Google directly.

The contract is deployment-neutral. Forwarded client identity is accepted only
from explicitly configured trusted proxy peers through `ALLIES_TRUSTED_PROXY_IPS`.
The mobile app does not need to know which hosting or proxy product is used.

## End-to-end flow

1. Generate a cryptographically random `state` and PKCE verifier in memory.
2. Derive the S256 `code_challenge`; keep the verifier and state associated with
   this one attempt only.
3. Call `POST /api/v1/auths/native/sign-in/google`. Omit `completion_mode` (or
   send `redirect`) for the claimed-link flow. Temporary Expo Go environments
   may send `manual_code`.
4. Open the returned `authorization_url` in the system browser using Expo
   AuthSession or `Linking.openURL` for manual mode. Do not use an embedded
   WebView.
5. Google returns to Cloud's registered HTTPS callback. Cloud validates the
   provider response, then either redirects to the exact app `redirect_uri`
   with a short-lived, single-use Cloud `code` and the original app `state`, or
   (for `manual_code`) shows that same code in a short-lived HTML page for
   copy/paste into the initiating app.
6. Verify the returned state locally in redirect mode, or submit the copied
   code in manual mode, then call the Cloud token exchange with the in-memory
   PKCE verifier. Never persist the exchange code.
7. Keep the access token in memory. Store only the opaque refresh token in
   Expo SecureStore.
8. Send the access token as `Authorization: Bearer <access_token>` to the
   existing authenticated account, profile, avatar, and Workspace APIs.

## Native endpoints

All native routes are under `/api/v1/auths/native`. Requests are JSON and must
not include browser cookies or an `Authorization` header on public start,
callback, exchange, or refresh requests. Successful token responses include
`Cache-Control: no-store` and `Pragma: no-cache`.

### Start sign-in

`POST /api/v1/auths/native/sign-in/google`

```json
{
  "redirect_uri": "<exact registered app return URI>",
  "code_challenge": "<base64url SHA-256 of verifier>",
  "code_challenge_method": "S256",
  "state": "<random app state>",
  "completion_mode": "redirect"
}
```

Success (`200`):

```json
{
  "status": "success",
  "message": "Native sign-in started",
  "data": {
    "authorization_url": "https://accounts.google.com/...",
    "expires_at": "<ISO-8601 timestamp>"
  }
}
```

The app return URI must exactly match a configured allowlist entry. No
wildcards, query strings, fragments, or Expo proxy callbacks are allowed.
`completion_mode` is the closed choice `redirect` or `manual_code`; omission
preserves `redirect`.

### Cloud callback

`GET /api/v1/auths/native/callback/google`

This route is used by Google, not called by the app as an API request. On
success in `redirect` mode Cloud responds `303` to the stored app URI:

`<redirect_uri>?code=<one-time-cloud-code>&state=<original-app-state>`

The app must verify `state` and then exchange `code` immediately. The code is
short-lived and single-use; it is not an access or refresh token. Safe callback
errors use the app redirect only when the native transaction is known and
trusted. Unknown or unsafe state is not redirected.

In `manual_code` mode Cloud responds `200 text/html` with the same exchange code
and its configured expiry in a selectable field plus a Copy button. Clipboard
failure leaves the field selectable for a normal copy action. The page carries
`Cache-Control: no-store`, `Pragma: no-cache`, `Referrer-Policy: no-referrer`,
`X-Content-Type-Options: nosniff`, and a per-response nonce CSP; it has no
`Location` header, external assets, cookies, tokens, or user data. Callback
retries reuse the still-valid code and original expiry. Consumed or expired
attempts show restart guidance without revealing a code.

### Exchange the one-time code

`POST /api/v1/auths/native/token`

```json
{
  "grant_type": "authorization_code",
  "code": "<one-time-cloud-code>",
  "code_verifier": "<original-pkce-verifier>",
  "redirect_uri": "<same exact app return URI>"
}
```

Success (`200`) returns:

```json
{
  "status": "success",
  "message": "Native session issued",
  "data": {
    "token_type": "Bearer",
    "access_token": "<short-lived-cloud-jwt>",
    "expires_in": 600,
    "refresh_token": "<opaque-rotating-token>",
    "refresh_expires_in": 1209600,
    "session_id": "<opaque-session-id>"
  }
}
```

The exact expiry values are deployment settings; use the returned values rather
than hardcoding them in the app.

### Refresh

`POST /api/v1/auths/native/token/refresh`

```json
{
  "grant_type": "refresh_token",
  "refresh_token": "<current-securely-stored-token>"
}
```

On `200`, atomically replace the stored refresh token with the returned one
before discarding the old in-memory value. Serialize refresh attempts so two
requests cannot race. A reused, expired, revoked, malformed, or wrong-kind
credential returns `401` with `session_invalid`; clear local session material
and require sign-in again. Refresh-token reuse revokes the whole family.

### Logout

`POST /api/v1/auths/native/logout`

```json
{
  "refresh_token": "<current-securely-stored-token>"
}
```

Send a matching native bearer when available, but do not block logout on an
expired access token. A successful or already-revoked logout returns `204` and
the app must clear SecureStore, in-memory access, and account query caches.
Clear the same local state on `401` or network uncertainty; do not retry with
an old refresh token.

## Error-to-state mapping

| HTTP / code | Mobile behavior |
| --- | --- |
| `400 pkce_required`, `invalid_redirect`, `exchange_invalid` | Treat as a terminal attempt failure; delete verifier/code and offer a fresh sign-in. |
| `400 flow_invalid`, `provider_denied` | Show a safe retry/cancel state; never display provider internals. |
| `409 exchange_replayed` or `flow_in_progress` | Discard the attempt and start a new one only after explicit user action. |
| `401 session_invalid` | Clear SecureStore, access memory, and query caches; route to sign-in. |
| `404 provider_unavailable` | Native auth is disabled or Google is not configured; show unavailable state. |
| `429 throttled` | Back off using the server response timing if present; do not tight-loop. |
| `503 auth_unavailable` | Keep credentials unchanged, show a retryable service-unavailable state. |
| Timeout/network failure during exchange or logout | Exchange: discard the one-time code and offer a new attempt. Logout: clear local state and let the next sign-in establish a new family. |

## Existing authenticated APIs

After token exchange, use the native bearer for the existing AUTH-001 account
surface, including `/api/v1/auths/me`, profile updates, avatar preparation /
completion / deletion, and Workspace context. The client boundary must inject a
bearer only for these explicitly allowlisted authenticated routes. It must not
attach the bearer to native start, callback, exchange, refresh, browser auth,
health, or public routes.

The app must not put credentials in Zustand, TanStack Query, AsyncStorage,
logs, analytics, URLs, crash reports, or ordinary files. Account and Workspace
responses may be cached in TanStack Query; clear those caches on terminal
revocation and logout.

## Enablement checklist

Cloud/deployment owners must complete these before setting
`ALLIES_AUTH_NATIVE_ENABLED=true`:

- Register distinct exact browser and native Google HTTPS callback URIs.
- Configure exact iOS/Android app return URIs in
  `ALLIES_AUTH_NATIVE_REDIRECT_URIS` (claimed HTTPS links for production;
  narrowly scoped custom schemes only for development builds).
- Configure `ALLIES_AUTH_GOOGLE_NATIVE_REDIRECT_URI` and the app allowlist in
  the deployment secret/config store; never commit credentials.
- Configure the shared cache and trusted proxy peer addresses through
  `ALLIES_TRUSTED_PROXY_IPS`; prove forwarded-header behavior in staging.
- Run the PostgreSQL concurrency and migration checks, then perform iOS and
  Android development-build smoke tests for sign-in, cancel, restore, refresh,
  revocation, logout, and offline recovery.
- Pin the generated OpenAPI contract in the Interface client and add contract
  tests for the request/response and error mappings above.

Until this checklist is complete, keep native auth disabled. Browser auth is
independent and remains available.

## Cloud evidence

The merged Cloud implementation includes regression coverage for PKCE and
redirect binding, callback and exchange replay, concurrent refresh and family
reuse, native/browser transport separation, safe error mapping, audit redaction,
trusted-proxy identity, and OpenAPI responses. The remaining device lifecycle
proof belongs to INT-008 and must be run with real iOS and Android development
builds rather than Expo Go.
