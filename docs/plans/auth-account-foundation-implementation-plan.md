# AUTH-001 Auth And Account Foundation Implementation Plan

## Feature Overview

- Problem: Allies Cloud has no product principal, external identity, revocable session, Workspace membership, profile, or avatar foundation.
- Target users: people using Allies and operators responsible for secure session lifecycle and privacy-safe diagnostics.
- Source docs/specs: accepted Nabu `projects/allies/engineering/specs/auth-account-foundation.md`, the durable work brief, local Cloud architecture, backend guide, and engineering style.
- Success outcome: an enabled verified provider returns a person to the same Cloud user, creates exactly one personal Workspace/owner membership on first sign-in, and supports self-profile/avatar operations through a revocable cookie session without runtime coupling.
- Delivery posture: Google is the general passwordless provider. Although the
  accepted Nabu contract names ChatGPT, ChatGPT enters implementation scope only
  if an ordinary consumer account can sign in without API access/billing,
  developer or partner status, a paid business/workspace tier, or an invite.
  If that test fails, remove ChatGPT and revise the Nabu provider decision before
  code begins. If it passes, add the provider only from OpenAI's official
  project-specific client contract.

## User Stories

1. As a person, I want passwordless sign-in through an approved provider so I can return to one durable Allies identity.
2. As a person, I want replay, provider, and session failures to fail closed so another browser cannot force or reuse my login.
3. As a Workspace owner, I want a self-owned profile and avatar so the product represents me without surrendering tenant isolation.
4. As an operator, I want bounded session revocation, safe audit outcomes, and cleanup commands so incidents can be contained without exposing credentials.

## Scope

### In Scope

- `auths` and `workspaces` Django apps and root API registration.
- Custom Cloud user; provider identities; user profile; one-time authorization flows; session families and one-time refresh tokens.
- Deterministic fake provider and Google OIDC. ChatGPT is not implementation
  scope while ordinary-user eligibility is unverified. It can be added only
  after that gate passes and OpenAI supplies the official project-specific
  contract; no placeholder endpoints or guessed claims land.
- One personal Workspace, one active owner membership, and a code-registered owner capability map.
- Private R2 avatar prepare, completion, read, replace, delete, and abandoned-object cleanup.
- CSRF, CORS/origin validation, throttles, structured audit outcomes, query guards, SQLite compatibility, and PostgreSQL concurrency CI.

### Out Of Scope

- Product passwords, magic links, MFA/recovery, teams, invitations, non-owner roles, billing, deletion/export.
- Pre-auth state, Ally creation, Foundry, Fly, Hermes, executions, runtime bindings, or product UI.
- A general permissions framework, general object-storage framework, or browser-session reverse engineering.

### Dependencies And Assumptions

- Python 3.13 / Django 6.0 / Django Ninja Extra remain the platform.
- Phase 0 installs `uv`, syncs the existing lock, runs an untouched baseline, and then adds only reviewed dependencies. Expected candidates are Authlib, boto3, Pillow, psycopg (test/deploy extra), and pytest-cov. Final versions and transitive advisories are checked before lock changes.
- A production shared cache is mandatory for distributed throttles. Startup/readiness fails when production enables auth without a non-local cache.
- Cloud and Interface use same-site HTTPS subdomains by default. Cross-site deployment is not silently inferred; it requires an approved alternate matrix.
- Access lifetime: 10 minutes. Refresh idle lifetime: 14 days. Refresh absolute lifetime: 30 days. Authorization-flow lifetime: 10 minutes.
- Avatar defaults: 5 MiB encoded bytes, JPEG/PNG/WebP, maximum 4096×4096 and 16 megapixels, five-minute upload/read URLs, five-second object connect and ten-second read timeouts, abandoned-pending cleanup after 24 hours.

### External readiness matrix

| Dependency | Account / owner | Required evidence before enablement | AUTH-001 effect |
| --- | --- | --- | --- |
| ChatGPT end user | Ordinary consumer ChatGPT account; no API or publisher setup | Written contract/sandbox proof of supported account tiers, age, regions, states, consent and production availability; no API billing, developer/partner, business/workspace or invite requirement | Fail means ChatGPT is removed from AUTH-001 before provider code starts |
| OpenAI publisher | Company-owned Platform organization plus partner enablement, only if the end-user gate passes | Partner/onboarding confirmation; issuer/discovery and endpoint metadata; client ID/auth method; scopes/claims; callback policy; sandbox; branding, data, regional and launch terms | Operator setup only; must never become an Allies user prerequisite |
| Google | Company-owned Google Cloud project and OAuth client | External consent configuration, verified authorized domain, exact HTTPS redirects, support/homepage/privacy/terms, client credentials, production brand status where required | Google provider cannot be enabled without a complete configuration |
| Deployment | Cloud/Railway owner | Final Interface and Cloud origins, Postgres, shared cache, HTTPS/proxy trust, secret store, scheduler and logging owner | Production auth readiness fails closed when incomplete |
| R2 | Cloudflare account owner | Private bucket, exact CORS, scoped credentials, lifecycle/cleanup policy and signed URL smoke evidence | Avatar routes remain disabled when incomplete |

The official publisher starting points are `https://platform.openai.com/` and
`https://platform.openai.com/partners/verify`. They are for the Allies team, not
for end users. The allowed public OpenAI documentation reviewed on 2026-08-11
does not establish consumer account-tier, age, region, or production
eligibility, so those facts must be confirmed before ChatGPT code is approved.

## Architecture And Invariants

1. `auths.User` is the sole Cloud principal and is configured through `AUTH_USER_MODEL` before any persistent product migration.
2. `ExternalIdentity(provider, subject)` is the only provider-to-user key. Email is snapshot data and is never a join key.
3. An `AuthFlow` is single-use and binds state, an initiating-browser cookie, provider, redirect, purpose, nonce, PKCE verifier, and—when linking—the initiating session family.
4. `SessionFamily` is the revocation authority referenced by JWT `sid`. Every cookie-authenticated request verifies the JWT and loads an active, unexpired family owned by `sub`.
5. Each `RefreshToken` stores only a keyed digest. Rotation locks the family and current token, consumes it once, and issues one successor. Reuse revokes the family before returning `401`.
6. Workspace role/capability is never in the JWT. Service-layer access loads the active membership and applies the code capability map.
7. Avatar bytes are never public. Completion verifies object bytes before a locked database transition makes an asset current.

## Migration Graph And Durable Constraints

No persistent `migrate` may run before `AUTH_USER_MODEL = "auths.User"` is committed. There is no repository database today; Phase 0 still verifies this precondition explicitly.

1. `auths/0001_initial.py`: User, ExternalIdentity, UserProfile, AuthFlow, SessionFamily, RefreshToken, AvatarAsset.
2. `workspaces/0001_initial.py`: depends on `migrations.swappable_dependency(settings.AUTH_USER_MODEL)` / `auths/0001`; creates Workspace and Membership.

| Model | Named constraints / indexes |
| --- | --- |
| User | unique opaque `public_id`; normalized inactive/staff flags; no product password endpoint |
| ExternalIdentity | `UniqueConstraint(provider, subject, name="auth_identity_provider_subject_uniq")`; index on user/provider |
| UserProfile | one-to-one user; normalized display name length/check constraint |
| AuthFlow | unique `state_digest`; index on `(expires_at, consumed_at)`; check: `purpose=link` requires initiating user and session family, sign-in forbids initiating user; one-time consumed timestamp |
| SessionFamily | unique opaque `public_id`; indexes on user and `(revoked_at, absolute_expires_at, idle_expires_at)` |
| RefreshToken | unique keyed `token_digest`; conditional unique unused token per family; index on family/expiry; consumed digest history is retained for reuse detection |
| AvatarAsset | unique private object key; `(user, created_at)` index; status/metadata check constraints; current pointer lives on UserProfile |
| Workspace | unique opaque `public_id`; conditional unique owner where `kind=personal`; personal kind requires owner |
| Membership | unique `(workspace, user)`; role/status check constraints; index on `(user, status)` |

The first-sign-in bootstrap uses one `transaction.atomic()` block, gets/creates identity under its unique key, locks the user bootstrap path, and gets/creates profile, personal Workspace, owner membership, and family. Integrity collisions retry by rereading the winning rows. The cross-table “personal Workspace has active owner membership” invariant is maintained by this sole creation service; AUTH-001 exposes no membership mutation that can invalidate it. SQLite proves idempotence/constraints; PostgreSQL tests prove lock/race behavior.

## Function And Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return / side effects and errors |
| --- | --- | --- | --- | --- |
| `auths/services/flows.py` | `begin_auth_flow` | `begin_auth_flow(*, provider: ProviderKey, purpose: FlowPurpose, redirect_to: str, browser_binding: bytes, user: User | None, family: SessionFamily | None) -> AuthorizationStart` | Enabled provider, exact allowlisted relative redirect, authenticated user/family iff link | Persists digests/protected verifier for 10 minutes; returns provider URL and raw flow-cookie secret; validation/disabled-provider errors |
| `auths/services/flows.py` | `complete_auth_flow` | `complete_auth_flow(*, provider: ProviderKey, state: str, code: str, browser_binding: bytes) -> AuthCompletion` | Constant-time browser binding; matching provider/purpose; unconsumed/unexpired state; OIDC issuer/audience/signature/time/nonce/subject; PKCE | Atomically consumes flow. Sign-in bootstraps/returns user and session; link attaches identity without replacing initiating session. Replay/collision/provider errors fail closed |
| `auths/services/accounts.py` | `resolve_or_create_user` | `resolve_or_create_user(identity: VerifiedIdentity) -> UserBootstrap` | Immutable provider+subject; safe snapshot fields only | Atomic user/profile/personal Workspace/owner membership creation or winner reread |
| `auths/services/identities.py` | `link_identity` | `link_identity(*, user: User, identity: VerifiedIdentity) -> ExternalIdentity` | Flow is link purpose and bound to user's active family | Creates link; same user is idempotent; other-user collision returns privacy-safe conflict; never changes session user |
| `auths/services/sessions.py` | `issue_session` | `issue_session(user: User, *, context: SessionContext) -> IssuedSession` | Active user; dedicated signing key configured | Creates family/current refresh row; returns access JWT and raw refresh once; secrets never logged |
| `auths/services/sessions.py` | `rotate_refresh` | `rotate_refresh(raw_token: SecretStr, *, request_context: SessionContext) -> IssuedSession` | Keyed digest lookup; origin/CSRF; family idle/absolute state | Locks family/token; consumes once; issues successor; reuse revokes family; unknown/revoked is privacy-safe `401` |
| `auths/services/sessions.py` | `authenticate_access` | `authenticate_access(raw_jwt: SecretStr) -> AuthenticatedSession` | Dedicated HS256 key; exact iss/aud; allowed claims only; expiry; active family whose user matches `sub` | One indexed family read; `401` for any invalid/revoked state |
| `auths/services/sessions.py` | `logout_session` | `logout_session(*, access: AccessContext | None, refresh: RefreshContext | None) -> None` | At least one cookie may identify an owned family; CSRF/origin required | Locks and revokes only the resolved owned family; unknown/expired is idempotent; clears both cookies |
| `auths/services/profiles.py` | `get_self_profile` | `get_self_profile(session: AuthenticatedSession) -> MeResult` | Active session | Deliberately joined singleton read of profile/avatar/Workspace/membership |
| `auths/services/profiles.py` | `update_display_name` | `update_display_name(user: User, display_name: str) -> UserProfile` | Trimmed Unicode, 1–80 chars, no control chars | Updates user-owned field; provider sync never overwrites it |
| `workspaces/services/bootstrap.py` | `ensure_personal_workspace` | `ensure_personal_workspace(user: User) -> WorkspaceContext` | Called inside atomic user bootstrap | Exactly one personal Workspace and active owner membership through constraints/retry |
| `workspaces/services/access.py` | `require_workspace_capability` | `require_workspace_capability(*, user: User, workspace_id: str, capability: Capability) -> WorkspaceContext` | Opaque ID; registered capability | One joined active-membership query; foreign/missing/inactive use the same denial |
| `auths/services/avatars.py` | `prepare_avatar_upload` | `prepare_avatar_upload(*, user: User, content_type: AvatarType, size: int, sha256: str) -> PreparedAvatar` | 1..5 MiB; allowlisted type; valid digest; throttle | Creates pending asset with user-scoped random key and five-minute signed PUT constrained to exact headers |
| `auths/services/avatars.py` | `complete_avatar_upload` | `complete_avatar_upload(*, user: User, asset_id: str) -> ReadyAvatar` | User-owned pending asset | HEAD then bounded streamed GET outside DB lock; hash, MIME sniff, single image decode/verify, ≤4096 each side/16MP; lock row/profile, recheck pending, make current; races are idempotent or `409` |
| `auths/services/avatars.py` | `delete_current_avatar` | `delete_current_avatar(user: User) -> None` | User only | Lock profile/current asset, clear pointer, mark deleted; object deletion is idempotent/retriable |
| `auths/providers/base.py` | `OIDCProvider` | `authorization_url(flow: ProviderFlow) -> str`; `verify_callback(code: str, flow: ProviderFlow) -> VerifiedIdentity` | Provider-specific strict config | Returns only normalized provider/subject/safe snapshot; discards code/tokens/raw claims |
| `auths/storage/avatars.py` | `AvatarObjectStore` | `sign_put`, `head`, `stream_get`, `sign_get`, `delete` | Private user-scoped keys; configured timeouts | Narrow R2 adapter; no bucket credentials leave Cloud |

`ProviderKey`, `FlowPurpose`, `Capability`, avatar status, membership status, and roles are closed enums. Expected domain errors are mapped by controllers; services never return HTTP responses.

## API And Transport Contracts

All responses use the existing versioned JSON envelope convention if one is established before implementation; otherwise successful singleton responses are direct typed objects and errors are `{"error":{"code":"…","message":"…"}}` with stable codes and non-sensitive messages. No pagination, client idempotency key, or backward-compatibility shim is needed because these are new singleton endpoints. Callback completion is idempotent only in the safe sense: a consumed state never performs work twice.

| Consumer | Method and path | Authentication / authorization | Request → success | Errors and retry |
| --- | --- | --- | --- | --- |
| Browser | `GET /api/v1/auths/csrf` | Anonymous; exact allowed Origin when present | `204`; seeds CSRF cookie | `403 origin_rejected`; safe to retry |
| Browser | `POST /api/v1/auths/sign-in/{provider}` | Anonymous + CSRF/origin + IP/provider throttle | `AuthStartRequest{redirect_to}` → `200 AuthorizationStartResponse{redirect_url}`; sets flow cookie | `400 invalid_redirect`, `404 provider_unavailable`, `429`; retry only after new start |
| Browser | `POST /api/v1/auths/identities/{provider}/link` | Active access family + CSRF/origin + user throttle | same start schema; purpose is link and user/family are bound | `401`, `409 already_linked_elsewhere`, `429` |
| Provider/browser | `GET /api/v1/auths/callback/{provider}?code&state` | Matching one-time flow + flow cookie; link also requires still-active initiating family | `303` to stored allowlisted relative target; sign-in sets cookie pair; link preserves existing cookies | Privacy-safe callback error redirect carrying a short error code; never retry same state |
| Browser | `POST /api/v1/auths/refresh` | Refresh cookie + CSRF/origin + token/IP throttle | `204`; rotates access and refresh cookies | `401 session_invalid`, `429`; reused token revokes family and must not retry |
| Browser | `POST /api/v1/auths/logout` | Access and/or refresh cookie + CSRF/origin | `204`; clears cookies | Always idempotent `204` after valid CSRF/origin; does not expose token state |
| Browser | `GET /api/v1/auths/me` | Active access family | `200 MeResponse` | `401 session_invalid` |
| Browser | `PATCH /api/v1/auths/me/profile` | Active access family + CSRF/origin | `ProfileUpdateRequest{display_name}` → `200 ProfileResponse` | `401`, `422 validation_error`, `429` |
| Browser | `POST /api/v1/auths/me/avatar/uploads` | Active access family + CSRF/origin | `AvatarPrepareRequest{content_type,size,sha256}` → `201 PreparedAvatarResponse{asset_id,upload_url,headers,expires_at}` | `401`, `415`, `422`, `429` |
| Browser | `POST /api/v1/auths/me/avatar/{asset_id}/complete` | Active access family + CSRF/origin | empty body → `200 AvatarResponse` | `401`, non-disclosing `404`, `409 invalid_state`, `422 object_invalid`, `429` |
| Browser | `GET /api/v1/auths/me/avatar/read` | Active access family | `200 AvatarReadResponse{url,expires_at}` | `401`, `404 avatar_absent` |
| Browser | `DELETE /api/v1/auths/me/avatar` | Active access family + CSRF/origin | `204` | idempotent after authorization |

Representative start:

```json
{"redirect_to":"/app"}
```

```json
{"redirect_url":"https://accounts.google.com/o/oauth2/v2/auth?..."}
```

Representative self response:

```json
{
  "user":{"id":"usr_..."},
  "profile":{"display_name":"Ada","avatar_url":null},
  "session":{"id":"ses_...","expires_at":"2026-08-09T22:10:00Z"},
  "workspace":{"id":"wsp_...","name":"Ada's Workspace","role":"owner","capabilities":["workspace.read","profile.write"]}
}
```

No response includes email unless AUTH-001 explicitly approves it, provider tokens, raw claims, token digests, object keys, database IDs, or runtime identifiers.

## Provider Payload Mapping

| Normalized field | Google source and validation | Fake source | ChatGPT |
| --- | --- | --- | --- |
| provider | fixed `google` for selected adapter | fixed `fake` in test settings only | fixed `chatgpt` only after consumer eligibility and the publisher contract both pass |
| subject | verified non-empty `sub` | deterministic fixture subject | stable non-empty subject from the supplied verified contract; never inferred from email |
| display snapshot | optional verified/name claim, length-normalized | sanitized fixture | only explicitly documented claims, normalized and optional |
| email snapshot | optional only; never identity/merge authority | sanitized fixture | optional only when the contract documents it; never identity/merge authority |

Google validates discovery/JWKS over HTTPS, exact issuer/audience, signature, expiry/not-before/issued-at skew, nonce, subject, code redirect URI, and PKCE. Tokens and raw claims exist only in memory for the exchange and are discarded. Timeouts and malformed provider responses become stable privacy-safe errors and structured outcomes.

## Cookie, CSRF, CORS, Proxy, And JWT Matrix

### Recommended same-site production

| Cookie | HttpOnly | Secure | SameSite | Path | Lifetime |
| --- | --- | --- | --- | --- | --- |
| `allies_access` | yes | yes | Lax | `/api/` | 10 minutes |
| `allies_refresh` | yes | yes | Strict | `/api/v1/auths/` | current token expiry, bounded by 14-day idle / 30-day absolute family |
| `allies_auth_flow` | yes | yes | Lax | `/api/v1/auths/callback/` | 10 minutes; cleared on completion |
| CSRF cookie | no | yes | Lax | `/api/` | Django policy |

- Host-only cookies by default; no broad `Domain` attribute. Exact HTTPS Interface origins populate `CSRF_TRUSTED_ORIGINS` and the credentialed CORS allowlist. Wildcards and reflected origins are forbidden.
- Mutating routes require Django's CSRF cookie/header pair (`X-CSRFToken`) and Origin/Referer enforcement. `GET /auths/csrf` is the documented bootstrap.
- Provider callback is a top-level `GET`; its defense is the one-time state plus constant-time flow-cookie binding, not CSRF middleware.
- Only explicitly configured proxy headers are trusted, from known ingress. Production startup fails if `DEBUG`, trusted-origin, forwarded-proto, signing-key, provider, cache, or R2 validation is unsafe/incomplete.
- Local HTTP development sets `Secure=false`, host-only localhost cookies, exact localhost origins, and never relaxes production settings implicitly.
- A cross-site deployment needs `SameSite=None; Secure`, exact credentialed CORS, and a separate approved/tested matrix before implementation. It is not the default.
- JWT uses one dedicated environment-provided 256-bit HS256 key, exact issuer/audience, 10-minute expiry, and only `iss/aud/sub/sid/jti/iat/exp`. It is not Django `SECRET_KEY`. Rotation replaces the key and may invalidate at most the ten-minute access window; refresh families remain authoritative and can issue new access tokens.

### Initial abuse controls

| Operation | Key | Limit | Cache outage |
| --- | --- | --- | --- |
| sign-in start / callback failures | privacy-safe IP prefix + provider | 10/minute and 50/hour | production readiness requires shared cache; runtime outage fails closed with `503` for new flows |
| refresh | token-digest prefix + IP prefix | 20/minute | existing access continues until expiry; refresh returns `503`, never falls back process-locally |
| identity link | user + provider | 5/hour | `503` |
| avatar prepare/complete | user | 10/hour / 20/hour | `503` |
Exact numbers are configuration constants with conservative defaults, not user-supplied settings. Logs never include raw IPs; use a rotating keyed prefix if IP correlation is retained.

## Avatar State And Race Rules

1. Preparation creates a pending row and a random `users/{user_public_id}/avatars/{asset_public_id}/{random}` key. The signed PUT fixes expected content type and length; optional signed `Content-MD5` may be added only after provider-compatibility verification. SHA-256 completion verification remains authoritative.
2. Completion obtains metadata and streams at most 5 MiB + 1 byte outside the database transaction with strict timeouts. It computes SHA-256, sniffs bytes, rejects animation/multiple frames unless later approved, runs Pillow verify plus a fresh decode, and enforces width/height ≤4096 and pixels ≤16,777,216 with decompression-bomb warnings treated as errors.
3. Completion then starts a short transaction, locks the asset and profile, rechecks user/status/expected metadata, records actual metadata, marks the asset ready/current, and marks the prior current asset replaced. Concurrent completion is idempotent for the same verified metadata; delete/replace winners cause `409` without republishing.
4. Delete locks profile/current asset, clears the pointer, and marks deleted before best-effort object deletion. A signed read issued earlier may remain usable until its maximum five-minute expiry; logout does not revoke an already-issued R2 URL.
5. Cleanup selects at most 100 expired pending/rejected/replaced/deleted rows by `(eligible_at,id)`, performs idempotent object deletion, records attempts/last error, and returns nonzero plus a metric when work remains failed. The deployment scheduler owns cadence (recommended every 15 minutes); the command owns no daemon.

## Operations And Audit Contract

### Commands

- `revoke_auth_sessions --user-id ACTOR | --family-id FAMILY --reason REASON`: privileged, mutually exclusive target; locks and revokes active families, is idempotent, prints counts only, and emits an audit outcome. No raw token input.
- `cleanup_auth_artifacts --batch-size 100`: bounded, idempotent, cursor-ordered cleanup for expired flows/token history and eligible avatar objects. Retries occur on the next scheduled invocation; permanent failures are visible through exit status, metric, and redacted event.

### Structured event envelope

`event_name`, `outcome`, `reason_code`, `provider`, hashed/opaque user or family reference when authorized, request correlation ID, timestamp, latency bucket, and environment. Never include authorization codes, tokens, cookies, raw claims, object URLs/keys, display names, email, full IP, or request bodies.

Initial events: `auth.flow.started`, `auth.flow.completed`, `auth.flow.rejected`, `auth.identity.linked`, `auth.identity.link_rejected`, `auth.refresh.rotated`, `auth.refresh.reuse_detected`, `auth.session.revoked`, `auth.avatar.rejected`, and `auth.cleanup.completed`. Deployment logging controls access and retention; recommended security retention is 90 days pending the project's production logging policy. Counters and alerts cover callback rejection spikes, refresh reuse, provider failure/latency, throttle/cache failure, cleanup backlog/failure, and R2 verification rejection. No new database audit-log product is introduced in AUTH-001.

## Repository Layout

```text
backend/
  auths/
    api/controllers.py
    api/register.py
    providers/{base,fake,google,chatgpt}.py  # chatgpt only after contract intake
    services/{accounts,flows,identities,sessions,profiles,avatars}.py
    storage/avatars.py
    management/commands/{cleanup_auth_artifacts,revoke_auth_sessions}.py
    models.py
    schemas.py
    authentication.py
    migrations/0001_initial.py
    tests/...
  workspaces/
    api/controllers.py
    api/register.py
    services/{bootstrap,access}.py
    capabilities.py
    models.py
    schemas.py
    migrations/0001_initial.py
    tests/...
  common/identifiers.py
  config/{settings,api}.py
```

The pure identifier helper is shared only because both new domains need the same prefix + 128-bit Crockford policy. Controllers validate/map HTTP; services own decisions and transactions; explicit registrars compose into `config/api.py`; there is no generic repository layer.

## Phases

### Phase 0 — Toolchain, Accounts, And Contract Gate

- Install/use the repository-declared `uv`; sync locked baseline; run untouched checks/tests.
- First verify ordinary-user eligibility for ChatGPT: normal consumer account,
  no API/developer/partner/business/workspace/invite entitlement, and adequate
  tier/age/region coverage. If it fails, remove ChatGPT from this plan and
  revise Nabu before provider code starts.
- Only if eligibility passes, start/confirm the company OpenAI Platform
  organization, open the official partner route, complete publisher identity
  readiness, and request the client contract. Record non-secret contract fields
  without credentials in Git.
- Configure the company Google Cloud OAuth project/consent screen and exact
  staging/production redirects. Approve origin topology, avatar defaults,
  JWT/provider/R2/cache secret names, and production cache.
- Review and lock deliberate dependencies; add PostgreSQL CI service and coverage tooling.
- Exit: reproducible baseline evidence and a complete configuration/readiness
  matrix. ChatGPT has an explicit include/exclude decision based on ordinary
  user eligibility; an included provider also has an owner, onboarding status,
  and explicit list of missing contract fields.

### Phase 1 — Principals, Workspaces, And Migrations

- Configure custom user first; create both domains, migrations, constraints, opaque IDs, and atomic personal bootstrap.
- Exit: empty SQLite and PostgreSQL migrations pass; repeat/concurrent bootstrap returns one user/profile/Workspace/owner membership.

### Phase 2 — Browser-Bound OIDC And Revocable Sessions

- Implement cookie-bound sign-in/link flows and fake/Google providers. Add the
  ChatGPT adapter only when Phase 0 marked it included and use only the supplied
  official contract; keep every incomplete provider fail-closed. Add session family/token rotation, cookie auth,
  CSRF/CORS/origins, targeted throttles, audit events, logout, and revocation.
- Exit: login-CSRF, mix-up, link collision, callback replay, refresh reuse/race, pre-revocation access JWT, and logout variants pass on required databases.

### Phase 3 — Self Profile, Workspace Context, And Avatar Lifecycle

- Add `/me`, display-name update, owner capabilities, isolation service/tests, private R2 lifecycle, byte/image verification, and cleanup command.
- Exit: query-count and two-user/two-Workspace negatives pass; avatar race and unsafe-image matrix passes.

### Phase 4 — Hardening And Release Evidence

- Run full checks, ≥90% new-domain coverage, migration/rollback drills, privacy-log inspection, cache/provider/R2 failure tests, runbook/readiness updates.
- Exit: evidence is recorded; Google passes; and ChatGPT either has a documented
  Phase 0 exclusion or passes an ordinary-consumer-account smoke test plus its
  sanitized contract and configured staging tests.

## Detailed Test Plan

### Unit And Service Tests

- Identity: new/repeat/concurrent subject, equal-email separation, authenticated link, same-user idempotence, other-user collision, disabled provider.
- Flow: state/flow-cookie constant-time match, missing/cross-browser cookie, provider mix-up, purpose mismatch, redirect allowlist, expiry, consumed replay, link session revoked mid-flow, nonce/issuer/audience/signature/time/subject/PKCE failures.
- Session: claim allowlist, issuer/audience/key/expiry, active family check, user mismatch, rotate, simultaneous double submit, reuse revocation, idle/absolute expiry, logout via access/refresh/both/neither, pre-revocation JWT rejected afterward.
- Workspace: one bootstrap, constraint collision retry, inactive membership, missing capability, foreign/missing resource indistinguishable, two users × two Workspaces.
- Profile/avatar: Unicode validation, provider snapshot does not overwrite, byte/type/hash/size/pixel/frame/decode failures, foreign asset, concurrent completion/delete/replace, old signed URL expiry disclosure, cleanup retries.

### Integration / CI Matrix

- SQLite: normal local suite, fresh migration, constraints, APIs, query counts.
- PostgreSQL: fresh migration, concurrent user bootstrap, callback completion collision, refresh rotation/reuse, row locks, conditional constraints, cleanup ordering.
- Provider: deterministic fake end-to-end; sanitized Google fixtures plus configured sandbox/manual callback checklist; no live provider secrets in CI.
- R2: fake object-store contract suite plus a separately configured private-bucket smoke test for signed headers/CORS/HEAD/GET/delete.
- Coverage: at least 90% lines across `auths` and `workspaces`; every enumerated security outcome branch asserted where coverage tooling reports it.

### Commands

```powershell
uv sync --locked
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest
uv run pytest --cov=auths --cov=workspaces --cov-fail-under=90
uv run ruff check .
uv run ruff format --check .
```

CI adds the repository's PostgreSQL service invocation and runs migration/concurrency markers against `DATABASE_URL`; no SQLite result is presented as proof of row locks.

## Query Optimization And N+1 Prevention

- `/auths/me`: one access-family lookup plus one deliberately joined profile/current-avatar query and one joined personal-Workspace/membership query. Establish the exact count after the auth middleware shape is implemented, then lock it with an upper-bound regression test.
- Workspace access: one indexed active-membership query with `select_related("workspace", "user")`, followed by an in-memory capability-map lookup.
- Refresh: indexed digest lookup plus `select_for_update()` family/token reads and one successor insert. Reuse family revocation is one set update.
- Bootstrap: direct constrained lookups; no collection iteration or generic repository abstraction.

## Risks, Rollback, And Residual Gates

- ChatGPT: ordinary-user eligibility is evaluated before code. A failed gate
  removes it from AUTH-001 and triggers a Nabu provider-decision update. If
  included, startup rejects enablement without the complete official contract.
- Cookie topology: same-site is the recommendation. Cross-site requires an owner-provided origin set and an explicit matrix revision before implementation.
- Provider/session outage: new sign-in/refresh fail closed; an already valid access token continues only until its short expiry unless its family is revoked.
- R2 URLs: bearer capabilities remain usable until five-minute expiry; replacement/logout cannot recall an issued URL.
- Rollback: disable provider starts/callbacks, revoke active families, clear cookies at the Interface, stop new signed URLs, and retain additive tables/events for investigation and forward repair. Do not destructively reverse identity data during incident rollback.

## Owner Decisions Required Before Phase 0 Exits

1. Approve same-site subdomains or provide exact cross-site Interface/Cloud origins.
2. Confirm whether an ordinary consumer ChatGPT account—without API access,
   billing, developer/partner status, paid business/workspace tier, or invite—
   is eligible in every target launch region. Exclude ChatGPT if not.
3. Only when included, create/use the company OpenAI Platform organization and
   supply the resulting publisher onboarding contract through deployment.
4. Approve the avatar defaults or provide replacements.
5. Provide production secret names/values through deployment—not the repository—for JWT keys, provider clients, R2, trusted origins, and cache.
6. Name the production shared cache and deployment scheduler/logging owner.

## Implementation Delegation

Implementation remains paused until this plan completes adversarial and simplicity review and the user approves it. When approved, kickoff delegates bounded implementation work to the personal named agent `luna_max` (`gpt-5.6-luna` with `max` reasoning) on `feature/auth-account-foundation`.
