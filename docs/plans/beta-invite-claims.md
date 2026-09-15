# Beta invite claims plan

## Using this template

Full route, one cross-repository plan. HTML required: no. Current worktree policy makes HTML conditional; existing auth presentation conventions and settled scope leave no unresolved visual-review need. Markdown is the complete review artifact. Planning only; delivery authorization is already recorded in the episode. Cloud branch `ft/beta-invites` and Interface branch `web/ft/beta-invites` target `dev`.

## Feature Overview

A person claims one invite code for an email before Google sign-in. Claiming grants eligibility only. Cloud creates the account when Google later verifies that email. Existing provider identities sign in unchanged. An unapproved new identity creates no user, profile, external identity, Workspace, membership, session, Ally, or runtime.

Evidence inspected: both repositories' `AGENTS.md`, `ENGINEERING_STYLE.md`, README, CI and toolchain configuration; Cloud `auths/services/accounts.py`, `flows.py`, `native_authorization.py`, `providers/base.py`, `admin.py`, `throttle.py`, `api/authentication.py`, `api/common.py`, concurrency tests, and Makefile; Interface `app/auth/return`, `lib/session`, onboarding resume storage, shared Cloud client, Vitest configuration, and installed Next 16.2.12 page documentation. Paths below are relative to the named repository; Cloud Python paths are under `backend/`, web paths under `apps/web/` unless qualified.

Nabu `projects/allies/index.md` and accepted `engineering/specs/auth-account-foundation.md` were read. Provider+subject remains the identity key; equal emails never merge accounts. The older specification mentions ChatGPT, but current code supports Google and the test fake provider. This change adds no provider.

## User Stories

1. An invited visitor can claim a code, then use the matching Google account to join.
2. A returning user can sign in without finding or reclaiming an invite.
3. An operator can issue a code, revoke unused eligibility, or recover a mistaken email claim.

## Scope

### In Scope

Cloud owns single-use invitations, public claims, operator actions, and first-signup enforcement for browser and native clients. Web adds `/claim-invite`, a shared-client method, and an actionable `invite_required` auth-return state. Preserve onboarding drafts and safe `returnTo` throughout.

### Out of Scope

No Foundry changes, waitlist enrollment, email delivery, email verification service, new operator dashboard/API, automatic email linking, membership invitations, or interception of "Make your first Ally". Native claim UI is outside this web slice; native server enforcement is required.

### Dependencies and Assumptions

Use PostgreSQL row locks in deployment and existing Redis-backed auth throttling. The current Google adapter owns verification of email and provider assertions. Claims accept an email without proving ownership; only subsequent verified Google sign-in proves ownership. Codes have 32 random bytes encoded URL-safe, stored only as SHA-256 digests. No expiry in this slice; operators can revoke them. Normalize both claim and verified email by stripping surrounding whitespace and lowercasing, with Django email validation and a 254-character bound. Do not rewrite dots, plus suffixes, or provider aliases.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Proposed symbol/signature | Boundary and result |
| --- | --- | --- |
| `auths/services/invites.py` | `issue_invite() -> tuple[BetaInvite, str]` | Persist digest, return raw code once to authorized admin; no email or account creation. |
| same | `claim_invite(*, code: str, email: str) -> None` | Validate and normalize, lock row, atomically claim; raise typed unavailable/validation errors. |
| same | `revoke_invite(invite_id: UUID) -> None` | Lock and mark revoked; repeat is a no-op; preserve claim and consumption evidence. |
| same | `reset_invite(invite_id: UUID) -> str` | Lock, reject consumed row, clear unconsumed claim/revocation and rotate code digest; return new raw code once. |
| `auths/services/accounts.py` | `resolve_or_create_user(identity: VerifiedIdentity) -> UserBootstrap` | Signature unchanged; returning identity first, otherwise require and consume locked email grant inside account transaction. |
| `packages/cloud-client/src/client.ts` | `claimInvite(input: {code: string; email: string}, options?: {signal?: AbortSignal}): Promise<void>` | Reuse typed transport, CSRF and bounded timeout conventions; validate success envelope, no token or client eligibility cache. |

### API and Transport Contracts

| Consumer | Method/path | Authorization and input | Result and recovery |
| --- | --- | --- | --- |
| Web | `POST /api/v1/auths/invites/claim` | Public; trusted Origin and valid CSRF required. JSON `{ "code": "example-only", "email": "person@example.com" }`; code trimmed, case-sensitive, maximum 128 characters; validated email; reject unknown fields. | `200 {"status":"success","message":"Invite claimed","data":{"claimed":true}}`. Same code+normalized email retry before consumption returns identical success. |
| Web claim failure | same | No eligibility/status lookup API. | `409 {"status":"error","message":"This invite is unavailable. Check the code or contact the person who invited you.","data":{"code":"invite_unavailable"}}` for missing/revoked/consumed code, claimed-other-email, or email already assigned to another invite. `422` malformed input, `403` Origin/CSRF rejection, `429` throttled, `503` throttle/database unavailable. |
| Browser Google callback | existing `GET /api/v1/auths/callback/google` | Existing state, provider verification, and browser binding unchanged. | Ineligible new identity: existing `303` redirect to validated stored target with `auth_error=invite_required`; no session cookies. Example Location `/auth/return?returnTo=%2Fhome&auth_error=invite_required` on the allowed Interface origin. Success remains existing session response. |
| Native callback | existing native Google callback and completion modes | Same shared account gate. | Persist terminal `invite_required` and return it through existing redirect/manual-code error shape; do not create exchange code or session. Preserve existing error handling for other failures. |
| Operator | Django admin `auths/betainvite` add/change/actions | Existing staff session, model add/change permissions and CSRF. Generated fields read-only; no direct arbitrary edits or delete action. | Issue form has no code input and displays raw code once on a non-cacheable response. Revoke/reset actions call service functions and use Django admin action logging, recording only invite ID/action. Reset of consumed invite is rejected. |

These are additive v1 contracts; no pagination or public list operation. Reuse the existing error envelope and CSRF bootstrap. Existing Railway cookie-bootstrap admission is the primary entry control. Apply its admission checks and trusted `_auth_rate_limit_identity`, never raw forwarded headers. Check the 10/minute browser/network identity bucket first where available; rejected attempts must not increment the shared global bucket. Then check a mandatory global emergency ceiling of 600/minute on the existing shared cache, including when no trustworthy identity exists. This ceiling assumes normal beta demand below 60 claims/minute and allows 10 attempts/second averaged over the minute, not a strict per-second limit; bursts remain possible. Cache failure returns 503 before mutation. Return `Retry-After: 60` on 429. Use distinct invite scope names and a low-cardinality saturation event with scope/outcome/reason only. Never log request bodies, code, digest, email, or claim response details; other operational events contain action/outcome/reason and internal invite ID only. Claim responses and admin issuance use `Cache-Control: no-store`.

### Data Shapes and Invariants

#### Database Models

| Model | Fields | Constraints and migration |
| --- | --- | --- |
| `BetaInvite` in `auths/models.py` | UUID id; unique `code_digest` varchar(64); nullable unique `claimed_email` varchar(254); nullable `claimed_at`, `revoked_at`, `consumed_at` datetimes; created/updated timestamps. | Additive migration. Unique non-null email prevents stacking multiple grants for one address. Check email and claimed_at are both null or both present; consumed_at requires a claim. Indexes supplied by unique fields. No raw code column. |

One row owns both code and grant. Available becomes claimed, then consumed. Revocation blocks claim and new signup but never logs out a user. Reset is allowed only before consumption, rotates the code and returns the row to available; old code stops working. Revocation preserves consumed evidence; consumed rows can never be reset or recycled.

The signup transaction first queries `(provider, subject)` and follows the existing-user path unchanged when found, including inactive-user rejection. For a missing identity, validate Google verification provenance and canonical email, lock the matching invite, then re-query `(provider, subject)` before testing grant state. This second lookup lets a concurrent winner for the same subject return normally. Missing, revoked, unclaimed or consumed grants reject with `invite_required`. Account/profile/identity/Workspace/membership creation and setting consumed_at commit together. Preserve the existing unique-provider/subject conflict recovery with a savepoint; only the winning creation consumes its grant. A database failure rolls back all those writes. Avoid broad IntegrityError handling that mistakes an unrelated constraint failure for an identity race.

Claim locks by digest and checks revocation/consumption before its idempotent same-email result. Claiming a different email never changes the original claim. Distinct codes racing for one email rely on the unique constraint, caught outside the failed savepoint and mapped to the same unavailable response. Signup, reset and revoke all lock the same invite row, so whichever commits first determines eligibility. Provider I/O happens before these locks. Session issuance currently follows browser bootstrap; if it fails after account commit, the identity is already durable and a fresh sign-in resumes it without another grant. Native outer transactions retain their existing rollback behavior.

In `native_authorization.complete_native_callback`, catch `InviteRequired` in a dedicated branch before the broad finalization error handler. After finalization rolls back, call existing `_mark_failed` with the transaction ID, claim digest and `error_code="invite_required"`; its existing atomic transition persists the terminal result. Do not collapse this rejection to generic `flow_failed` or `provider_unavailable`. Return the stored error through both redirect and manual-code completion; subsequent callback/poll attempts return the same terminal error without creating an exchange code, account graph or session.

#### Enums

Not applicable: timestamps and nullable fields determine invite state without a second persisted status vocabulary. Add typed `InviteRequired`, `InviteUnavailable` and consumed-reset domain errors using existing exception conventions.

#### API Request Schemas

`ClaimInviteRequest` in `auths/api/schemas.py`: required bounded code and email strings, normalized by the service; unknown fields rejected. Shared client exposes the same fields. No client-supplied user, provider subject, status or return URL is accepted by Cloud claim.

#### API Response Schemas

`ClaimInviteResponse` contains only `claimed: Literal[True]` in the existing success envelope. Existing callback contracts gain the stable `invite_required` error code. Admin raw-code display is a private HTML response, never an API model.

#### Temporary / Internal Shapes

Raw invite code exists only during issue/reset response and in the visitor's form memory. Code and email must not enter URL query strings, analytics, local/session storage or error logging. Admin URLs identify rows by UUID. Auth flow records remain necessary pre-auth state; they are not accounts or grants.

#### Service Primitives

`claim_invite` owns the claim transaction; issue/revoke/reset own their short transactions. Account bootstrap owns grant consumption together with account state. Reuse Django admin audit records; do not introduce a separate event store, reservation table, task queue or eligibility service layer.

### Plain-language glossary

- Claim: attach a code to one email without creating an account.
- Grant: that row's permission to create one new verified identity.
- Consumption: commit that identity and mark the grant used in one transaction.
- Existing identity: an existing provider+subject record, regardless of current email.

### Frontend Interaction Shapes (if applicable)

| Entry | State and action | Recovery |
| --- | --- | --- |
| `/claim-invite?returnTo=<safe path>` | Server page awaits searchParams and validates returnTo; client has local code/email and idle/submitting/success/error state. Submit via shared Cloud client and existing CSRF owner. | Disable duplicate submission; abort on unmount and ignore stale responses. Errors keep entered fields; retry manually after timeout/429/503. Show success only after validated 200. |
| Claim success | "Invite claimed. Continue with the Google account for [entered email]." Link to `/sign-in?returnTo=...`; clear code from form memory. | Use existing Google sign-in UI. No auto-sign-in, account creation, new draft, or storage clear. |
| `auth_error=invite_required` | "You'll need a beta invite to create an account. Claim it using the email for your Google account." | Primary Claim invite link with preserved safe returnTo; secondary Sign in again for another Google account. Avoid a restore-session retry loop for this terminal error. |

Use existing auth card styles, visible labels, `type=email`, keyboard submit, focus-visible controls and live status/error text. Success and error must not depend on color. The form has no email/code query prefills or analytics field capture. Inspect current PostHog autocapture/session-replay settings; explicitly exclude the claim form and success email from capture if existing masking does not establish this boundary, and verify emitted telemetry. Existing signed-in state can continue to the account via normal auth return. Do not touch onboarding draft clearing or Ally creation triggers.

## Phases

### Phase 1 - Cloud claim and signup boundary

Add the model/migration, focused invite service/controller, admin integration, typed error and explicit `ALLIES_BETA_INVITES_REQUIRED` setting (default true). Register the controller through existing registration. Enforce in accounts, preserve native terminal error, update env inventory/operations and focused tests. Use one test-only autouse fixture to disable enforcement for legacy fixtures; new invite tests explicitly enable it and use verified Google fixtures. Add a separate assertion of the production setting's true default, outside that fixture's override. Do not weaken provider verification or edit dozens of unrelated test fixtures. Exit: claim/admin and browser/native gate tests pass, PostgreSQL races prove one-use semantics, existing identities pass with enforcement enabled.

### Phase 2 - Interface recovery and contract pin

Add `app/claim-invite/page.tsx`, a focused client component/style, shared client schemas/method/tests and auth-return error handling. Reuse safe return parser and onboarding resume helpers. Export OpenAPI from a committed clean Cloud revision and update Interface snapshot/provenance/generated types through existing scripts. Exit: contract checks, form/recovery tests and build pass; draft survives denial, claim and later sign-in.

### Phase 3 - Ordered release and evidence

Ship two coherent PRs into `dev`; retain migrations and tests with Cloud implementation. Consider splitting only if the resulting changes remain deployable and testable. Before each environment rollout, explicitly set `ALLIES_BETA_INVITES_REQUIRED=false` for the transitional deployment, deploy additive Cloud first, then Interface with the pinned contract. Verify operator issue/reset/revoke access and public CSRF/claim round trip before enabling enforcement. Enable true, restart/redeploy all applicable Cloud instances consistently, then verify returning identity, invited new identity, denied new identity and native rejection. Do not announce beta gating complete while any serving Cloud instance remains ungated. Remove temporary false overrides after validation. Update canonical Nabu auth specification with the accepted boundary and rollout outcome using revision-aware writes by the delivery owner.

## Acceptance Criteria

1. Claim creates only invite state; matching repeated claim succeeds and another email loses atomically.
2. One grant admits at most one new provider identity, including concurrent browser/native callbacks. Email equality never merges users.
3. Existing identities, existing sessions, refresh and authenticated identity linking work without a grant; inactive users remain rejected.
4. Unverified/missing/mismatched email and unavailable grant create no account graph, session, exchange code, Ally or runtime.
5. Operator reset invalidates the old code and mistaken unconsumed claim; consumed grants cannot be recycled. Revoke races serialize with signup.
6. Web explains rejection and preserves safe return destination and onboarding draft; no invite gate is added to Make your first Ally.
7. Origin/CSRF and fail-closed shared throttling protect claim; sensitive data stays out of URLs, persistence outside the model, logs and telemetry.

## Backend Considerations (if applicable)

### Query Optimization Plan

Claim uses one indexed digest lookup with a row lock and at most one update. New signup adds one indexed email lookup with a row lock, one identity recheck and a grant update. Existing sign-in adds no grant query. Verify functionally that existing sign-in never reads the invite table; avoid exact query-count assertions. No provider network call runs while holding the invite lock.

### N+1 Prevention

There is no public collection. Use default Django admin pagination; no invite relation loading is needed. Keep generated raw codes out of changelist and search fields.

### Detailed Unit Test Cases

Cover normalized email parity, literal plus/dot handling, bounds/unknown input, issued code digest-only storage, repeated claims, conflicting claims, no side effects on failure, grant rollback on bootstrap failure, session-failure recovery, unauthorized/nonstaff admin, missing model permissions, CSRF, consumed reset rejection and old-code invalidation. Test logging with sentinel code/email values to detect disclosure.

Native rejection tests cover redirect and manual-code modes plus repeated callback/poll reads of persisted `invite_required`, with no account, exchange or session writes. Throttle tests prove an abusive stable identity is rejected before charging the global counter while another identity can still claim; global saturation blocks mutation; cache failure fails closed; saturation logs contain no personal data.

## Frontend Considerations (if applicable)

### Data Path

Claim page -> local submit -> existing session/CSRF adapter -> typed Cloud client -> Cloud claim controller -> success/error view. No Next API proxy is required. Callback -> auth-return parser -> invite-required recovery -> claim -> existing sign-in -> existing post-auth resume path.

### State Management Considerations

Cloud is the only durable eligibility authority. Form state stays local; no new Zustand store or query cache. Preserve existing sessionStorage onboarding snapshot/pending marker untouched. Abort requests on navigation, disable duplicate submits and suppress stale completions. An uncertain claim result can be retried with the same pair before consumption; a consumed code returns unavailable, and the user can sign in normally if account creation already succeeded.

## Test Plan

- Cloud unit/API tests: `make check`, `make lint`, `make test APP=auths/tests`; extend config OpenAPI assertions. Run `uv run ruff format --check .`, `uv lock --check`, `uv run pytest`, and `uv run pytest --cov=auths --cov=workspaces --cov-fail-under=90` from backend as required by CI. Migration checks include `uv run python manage.py migrate --noinput` and `migrate --check`.
- PostgreSQL 17 CI: `uv run pytest -m postgresql`; add real concurrent claim-same-code/different-email, two-codes/same-email, same-subject signup, different-subject/same-grant, revoke/signup and reset/signup tests. Use the existing thread/barrier/separate-connection pattern; SQLite success is not concurrency evidence.
- Interface: `bun run cloud:check`, `bun run typecheck`, `bun run test:run`, `bun run lint`, `bun run build:web`; preserve CI-selected browser and mobile bundle checks because shared client changes can affect both clients. Focused Vitest covers CSRF/error mapping, duplicate submit, unknown network outcome, rejected return URLs, query error allowlist, draft preservation and Google continuation.
- Browser verification: keyboard-only form at desktop/narrow widths; invalid/unavailable/429/503 and retry; claim success then same-email Google; wrong Google email then correction; denied callback followed by claim preserves populated onboarding draft. Inspect network and telemetry for code/email leakage.
- Staging and production: use controlled test identities/codes, inspect durable row counts and session/exchange absence for denied attempts, confirm no Foundry calls, verify returning user both before and after enforcement. Record deployment versions and effective gate value, without codes/emails. Planning did not run product tests; commands above are implementation exit criteria.

## Risks and Mitigations

- A stolen code can be claimed to someone else's email. This flow deliberately proves ownership only at Google sign-in; operators reset unconsumed mistakes with code rotation. One grant cannot create unlimited subjects.
- Enforcement can lock out new testers if UI/operator access is not deployed. Use the explicit off -> Cloud -> Interface -> smoke -> on sequence and verify effective settings on all instances. Existing identities always bypass this new gate.
- Reverting Cloud to old code reopens signup. Prefer reverting Interface presentation while retaining the Cloud boundary, or repairing the gate in place. Emergency disabling is an explicit operator rollback with a recorded open-signup window; retain invite rows and do not reverse the migration or erase consumption evidence.
- Email normalization is a product matching rule, not identity ownership. Both boundaries use the same function; no alias conversion or account merging. Existing-email users whose provider identity is genuinely absent need an invite like any other new identity.
- Distributed callers or repeated new cookies can still exhaust the global allowance. The 600/minute ceiling is an accepted bounded-overload tradeoff, not DDoS prevention. Keep the existing limiter and Railway admission architecture; monitor low-cardinality saturation and revisit the ceiling if measured beta traffic approaches it.
- Open decisions: none for implementation. Operations must verify deployed Redis/proxy settings, operator permissions and environment rollout readiness before enabling, and record that evidence in the episode.
