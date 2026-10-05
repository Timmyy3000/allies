# AUTH-001 Cloud Auth And Account Foundation

## Status

- Type: feature
- Implementation delegation: always
- Delegation source: explicit task confirmation on 2026-08-09
- Review worker: `gpt-5.6-terra` with `xhigh` reasoning
- Review worker source: explicit task confirmation on 2026-08-09
- Implementation worker: personal named agent `luna_max` (`gpt-5.6-luna` with `max` reasoning)
- Implementation worker source: explicit task confirmation on 2026-08-09
- Planning mode: full
- Worktree manager: ordinary Git
- Branch: `feature/auth-account-foundation`
- Worktree path: `C:\Users\ASUS\Desktop\projects\allies-cloud-auth-account-foundation`
- Task workspace: `C:\Users\ASUS\Desktop\projects\allies-cloud-auth-account-foundation\docs\plans`
- Kickoff configuration: `C:\Users\ASUS\Desktop\projects\allies-cloud-auth-account-foundation\docs\plans\kickoff.yaml`
- Created: 2026-08-09
- Target date: not specified
- Current phase: implementation through `ship-it`; reviewed plan approved on 2026-08-11

## Objective

Implement the accepted AUTH-001 Cloud boundary so a person can sign in through
an approved external provider, return to the same Cloud user, maintain a basic
human profile, receive exactly one personal Workspace with an active owner
membership, and use a revocable Cloud session without exposing provider,
runtime, or cross-Workspace authority.

This slice establishes the account and authorization substrate required by
later Allies product domains. It must remain independent of Ally creation,
pre-auth onboarding, Foundry, Fly, Hermes, executions, and runtime bindings.

## Context

Allies is a managed product for durable, named digital helpers: “Give it a
name. Give it a job.” The product organizes memory, files, permissions,
routines, and visible work around a stable Ally identity while hiding runtime
infrastructure without hiding user control.

The repository is currently a minimal Python 3.13 / Django 6.0 / Django Ninja
Extra scaffold. It contains `config`, a `startdomain` generator, repository
engineering policy, and accepted architecture documents, but no product domain
apps or product migrations. Cloud owns users, Workspaces, authorization, human
profiles, conversations, and product truth; Foundry owns runtime truth.

AUTH-001 is owner-approved and self-contained. It freezes Google plus any
provider that passes the ordinary-user accessibility gate as the passwordless
provider set, a 5–10 minute JWT access cookie, a
rotating server-backed opaque refresh token, provider-subject identity linking,
one personal Workspace, one active owner membership, an explicit owner
capability map, editable display name, and private R2-backed avatars.

OpenAI has a real “Sign in with ChatGPT” partner capability, but two account
roles must not be conflated. The Allies publisher may need OpenAI partner
enablement to register the integration. An ordinary Allies user must never need
an API account, API billing, developer organization, partner status, or company
account to use the resulting button.

ChatGPT is currently excluded from provider implementation because the allowed
public OpenAI documentation does not establish ordinary-user eligibility. It
may re-enter AUTH-001 only after OpenAI confirms that a
normal consumer ChatGPT account in the launch regions can authenticate without
a paid, business, workspace, invite, or developer entitlement. If that
consumer-access test fails, ChatGPT is removed from AUTH-001 before
provider-specific implementation begins and the accepted Nabu provider decision
must be revised. Google remains the general passwordless route. If the test
passes, Phase 0 must also obtain the publisher-side client contract: partner
enablement, issuer/discovery metadata, client credentials, callback policy,
claims/scopes, test access, and launch requirements. No implementation may
guess endpoints or reuse ChatGPT browser-session behavior.

## External Account And Deployment Readiness

### OpenAI / ChatGPT publisher setup

These steps belong to the Allies team, not to people creating Allies accounts.

1. Create or use the company-owned OpenAI Platform organization at
   `https://platform.openai.com/`.
2. Use the official partner route at
   `https://platform.openai.com/partners/verify` while signed in. This is the
   only official partner entry point found during the 2026-08-11 documentation
   review; its public page does not establish that enrollment is self-service
   or that a generic Platform account is automatically eligible.
3. Verify the developer or business identity for the organization and make the
   Allies website, support contact, privacy policy, terms, and publisher name
   consistent. OpenAI documents these requirements for public Platform
   submissions; the Sign in with ChatGPT program may impose additional partner
   requirements that must be captured from the onboarding response.
4. Obtain the actual relying-party contract: issuer/discovery URL,
   authorization/token/JWKS or user-info endpoints, client ID and client
   authentication method, permitted scopes and stable subject claim, PKCE and
   nonce requirements, exact callback URLs, sandbox/test users, logo/brand
   rules, data-handling terms, rollout countries, and production approval.
5. Store credentials only in the deployment secret store. The repository gets
   setting names, validation, sanitized fixtures, and a disabled-until-complete
   readiness check—not credentials or guessed defaults.

### End-user accessibility gate

Before ChatGPT enters implementation scope, obtain written contract or sandbox
evidence that:

- a normal consumer ChatGPT account can authenticate;
- the user does not need OpenAI API access, API billing, a developer
  organization, partner enrollment, ChatGPT Business/Enterprise, or an invite;
- supported account tiers, minimum age, countries/regions, and account states
  cover the intended Allies launch audience;
- consent clearly identifies the data shared with Allies and permits a user to
  cancel without losing access to the Google sign-in path;
- the same ordinary-user behavior is available in production, not only partner
  test accounts.

While eligibility is unverified—or if any special entitlement makes regular
people ineligible—ChatGPT is absent from provider code, the provider picker,
configuration, acceptance criteria, and tests. Do not build a hidden or
partner-only login path for the public app.

### Google and shared production services

- A company-owned Google Cloud project, external OAuth consent configuration,
  web OAuth client, exact HTTPS redirect URIs, verified authorized domain,
  support email, homepage, privacy policy, terms, and production brand review
  where required.
- Final Interface and Cloud HTTPS origins, DNS, proxy/header trust, and exact
  CSRF/CORS/cookie policy.
- Cloud PostgreSQL and a shared production cache for distributed auth
  throttles; SQLite remains a local convenience, not concurrency proof.
- A private Cloudflare R2 bucket with exact CORS, lifecycle cleanup, scoped
  credentials, and signed upload/read support.
- A dedicated JWT signing secret, provider client secrets, R2 credentials,
  cache/database URLs, trusted origins, and operational secrets managed outside
  Git.
- Public homepage, support, privacy, and terms URLs; security/logging owner;
  scheduler for bounded cleanup; staging callback URLs and test accounts.

The host has Python 3.13.3 but currently lacks `uv`, `make`, Django, and Ruff on
the executable path. Existing validation commands could not run during intake.
Toolchain bootstrap is a prerequisite to implementation validation, not a
source-code failure.

## Requirements

1. Create focused `auths` and `workspaces` Django domains using the repository's
   explicit controller → registrar → root API composition.
2. Use one Cloud principal. Recommend `auths.User` as the project's custom
   Django user model, created in `auths/0001_initial` and configured through
   `AUTH_USER_MODEL` before product migrations. Provider identities, editable
   profile state, and Cloud sessions remain separate models.
3. Product authentication remains passwordless. No registration, password
   login, reset, magic-link, MFA, or recovery API is introduced. Operator-only
   Django admin authentication is not a product login contract.
4. Resolve identities only by verified `(provider, subject)`. Never auto-merge
   users by email. A second identity may be linked only from an authenticated
   user session and must preserve uniqueness.
5. Validate provider state, issuer, audience, subject, nonce, authorization
   code, redirect target, PKCE where supported, replay, timeouts, and malformed
   responses behind separate provider adapters.
6. Issue a short-lived JWT access cookie containing only stable session and
   timing claims. Store a cryptographically random opaque refresh token only as
   a digest, rotate it on every use under a database lock, and revoke the token
   family on reuse.
7. Require CSRF plus Origin/Referer validation for cookie-authenticated writes.
   Apply an explicit CORS and cookie policy rather than inferring deployment
   topology.
8. Create one personal Workspace and one active owner membership during the
   first successful sign-in. Concurrent or replayed completion must not create
   duplicates.
9. Resolve current Workspace membership and capabilities from Cloud records for
   every Workspace request. Do not put Workspace IDs, roles, or capabilities in
   access JWTs. Cross-Workspace denial must not reveal resource existence.
10. Expose self-profile read/update for user-owned `display_name`; provider
    snapshots may seed but never overwrite user-owned profile fields.
11. Provide private R2 avatar upload preparation, completion verification,
    signed reads, replacement, deletion, and bounded abandoned-object cleanup.
    Cloud owns user-scoped keys and never exposes bucket credentials.
12. Record privacy-safe structured authentication/audit outcomes and enforce
    bounded provider/session abuse controls without tokens, codes, cookies, raw
    claims, or personal payloads in logs.
13. Support SQLite for the repository's local workflow and PostgreSQL in
    deployment, using additive migrations and database constraints for durable
    uniqueness.
14. Add no `PreAuthContext`, account claim, Ally, Foundry, Hermes, Fly,
    execution, gateway, team invitation, member role, billing, or account
    deletion behavior.

## Acceptance Criteria

1. First sign-in through every included v1 provider creates exactly one
   user, one user profile, one personal Workspace, one active owner membership,
   and one refresh-session family.
2. When ChatGPT is included, a normal consumer ChatGPT account with no API,
   developer, partner, paid-business, workspace, or invite entitlement can
   complete sign-in in every supported launch region. If this criterion cannot
   be proven before implementation, ChatGPT is excluded from AUTH-001.
3. Repeat and concurrent same-subject completion resolves the same user and
   personal Workspace without duplicate durable records.
4. Equal emails from different provider subjects never merge users; explicit
   linking requires the authenticated user and rejects collisions.
5. Access cookies are short-lived, Secure, HttpOnly, and scoped correctly;
   refresh tokens are opaque, hashed, rotating, one-time, revocable, and reuse
   revokes the family.
6. Expired, malformed, unknown, reused, and revoked sessions return privacy-safe
   `401` responses; logout is idempotent and cannot revoke another user's
   session.
7. `/api/v1/auths/me` returns user, editable profile, current session metadata,
   personal Workspace, owner role, and registered capabilities without
   provider tokens, raw claims, internal keys, or runtime identifiers.
8. Profile and avatar operations are self-only. R2 completion verifies the
   issued user-scoped key, object existence, type, size, and checksum before an
   asset becomes current.
9. Workspace context requires a current active membership and rechecks the
   registered capability in service code; two-user/two-Workspace negative
   tests prove isolation.
10. Provider callback state, nonce, issuer, audience, redirect, PKCE, replay,
   outage, timeout, and malformed-response behavior are covered with sanitized
   fixtures and fake-provider integration tests.
11. Query-count tests guard `/auths/me` and Workspace context against relation
    N+1 regressions.
12. Fresh SQLite and PostgreSQL-compatible migration paths pass checks, and the
    rollback path disables provider routes and revokes sessions without
    destructive table removal.
13. The implementation reaches at least 90% line coverage for the new domains
    and covers every security decision branch where the selected tooling can
    report it.
14. No pre-auth, collaboration, Ally, or runtime dependency appears in the new
    domains.

## Evidence And Sources

- Nabu: `projects/allies/engineering/specs/auth-account-foundation.md`
- Nabu: `projects/allies/index.md`
- Nabu: `projects/allies/docs/01-northstar.md`
- Nabu: `projects/allies/docs/03-our-solution.md`
- Nabu: `projects/allies/docs/05-technical-architecture.md`
- Nabu: `projects/allies/planning/mvp-to-beta-roadmap.md`
- Nabu: `projects/allies/engineering/codebase-structure.md`
- Nabu: `projects/allies/engineering/decisions/decision-log.md`
- Nabu: `projects/allies/engineering/guides/backend-development.md`
- Local: `ENGINEERING_STYLE.md`
- Local: `docs/architecture/cloud-domain-map-and-contract.md`
- Local: `docs/engineering/backend-development.md`
- Local: `docs/templates/PLAN_TEMPLATE.md`
- Django 6.0 custom-user and migration documentation:
  `https://docs.djangoproject.com/en/6.0/topics/auth/customizing/`
- Google OpenID Connect documentation:
  `https://developers.google.com/identity/openid-connect/openid-connect`
- Cloudflare R2 presigned URL and CORS documentation:
  `https://developers.cloudflare.com/r2/api/s3/presigned-urls/`
  and `https://developers.cloudflare.com/r2/buckets/cors/`
- OpenAI documentation review repeated on 2026-08-11: the partner capability
  is accepted as real, but the public developer index still exposes no
  third-party relying-party integration contract. Official starting points:
  `https://platform.openai.com/` and
  `https://platform.openai.com/partners/verify`.

## Decisions

- Work type is `feature`; planning mode is `full` due to security, identity,
  migration, tenant isolation, and external-provider risk.
- Use `auths` and `workspaces`; older `accounts` and `tenants` target-layout
  names are superseded by AUTH-001 and CLD-001.
- Recommend `auths.User` as the custom Django user model while keeping
  `ExternalIdentity`, `UserProfile`, `RefreshSession`, and `AvatarAsset`
  separate.
- Use an explicit provider port. Implement the deterministic fake provider and
  Google. Add ChatGPT only after both the ordinary-user eligibility gate and
  the publisher client-contract gate pass. If consumer eligibility fails,
  Google-only becomes the correct AUTH-001 scope after the Nabu provider
  decision is revised.
- Keep the owner capability map in code. Do not introduce a generic database
  permission framework.
- Keep avatars in a private R2 bucket using short-lived presigned `PUT`, `GET`,
  and `HEAD` operations with exact CORS/header configuration.
- Use subagents for independent plan reviews and eventual bounded
  implementation work. Planning review and implementation use separate model
  selectors.

## Risks

- ChatGPT partner onboarding may not be self-service and its relying-party
  contract is not public. Mitigation: make partner enrollment and contract
  intake a Phase 0 external dependency, fail closed until every required field
  is present, and never scrape or reverse-engineer ChatGPT authentication.
- A custom user-model choice becomes expensive to change after migrations.
  Mitigation: settle it in the reviewed plan and create it in the first auths
  migration.
- Callback replay or refresh-token races could duplicate identity or sessions.
  Mitigation: one-time state, database uniqueness, row locks, token-family
  state, and concurrency tests.
- Cookie topology can create CSRF/CORS vulnerabilities. Mitigation: explicit
  same-site default plus a documented cross-site variant with a narrow origin
  allowlist.
- R2 presigned URLs are bearer capabilities and remain reusable until expiry.
  Mitigation: short expiry, unguessable user-scoped pending keys, completion
  verification, and cleanup.
- Broad auth libraries can smuggle in password, email-merge, or generic social
  account behavior that conflicts with the spec. Mitigation: narrow adapters
  and deliberate dependency review.
- The local toolchain is incomplete. Mitigation: bootstrap `uv` and locked
  dependencies before implementation, then record exact validation evidence.

## Open Questions

- Can a normal consumer ChatGPT account in every intended launch region use the
  partner login without API access, billing, developer/partner status, a paid
  business/workspace tier, or an invite? If not, remove ChatGPT from AUTH-001
  and revise the Nabu provider decision before implementation.
- If ordinary-user eligibility passes, has the Allies publisher received the
  project-specific client contract and production enablement? This is an
  operator dependency and must never become an end-user prerequisite.
- What are the production Interface and Cloud origins? The answer selects the
  same-site cookie default or the explicit cross-site CORS/CSRF variant.
- Which secret names, issuer/audience values, callback URLs, and rotation policy
  will deployment provide for JWT signing, Google, ChatGPT, and R2?
- What maximum avatar byte size, content-type allowlist, signed-URL lifetime,
  and cleanup interval should be used? The plan will recommend conservative
  defaults for approval.
- Which shared production cache backs rate limits? The scaffold currently has
  no Redis/cache configuration.

## Plan

- Editable review artifact:
  `C:\Users\ASUS\Desktop\projects\allies-cloud-auth-account-foundation\.lavish\auth-account-foundation-plan.html`.
- Executable contract plan:
  `C:\Users\ASUS\Desktop\projects\allies-cloud-auth-account-foundation\docs\plans\auth-account-foundation-implementation-plan.md`.
- Adversarial review:
  `C:\Users\ASUS\Desktop\projects\allies-cloud-auth-account-foundation\docs\plans\auth-account-foundation-adversarial-review.md`.
- Adversarial verdict: `Needs revision`. All nine actionable findings were
  accepted and incorporated: browser-bound callback state, a typed identity-link
  flow, active-family access revocation, exact constraints/migration graph,
  concrete cookie/CSRF/CORS/throttle policy, operational commands/events,
  PostgreSQL race CI, repository registrar layout, and bounded avatar/race rules.
- Simplicity verdict: `Simplification recommended`. All four findings were
  accepted: do not create a placeholder ChatGPT module/settings before the
  official contract is supplied, remove refresh-token
  lineage fields, use one dedicated JWT key instead of a speculative key ring,
  and remove the special profile-update throttle.
- Simplicity review:
  `C:\Users\ASUS\Desktop\projects\allies-cloud-auth-account-foundation\docs\plans\auth-account-foundation-simplicity-review.md`.
- Both reviews are reconciled and the owner approved the reviewed plan on
  2026-08-11. Implementation proceeds with the recommended same-site topology,
  conservative avatar defaults, and ChatGPT excluded unless its consumer gate
  is later proven.

## Execution Notes

- Implementation began on 2026-08-11 through `ship-it`.
- Delegation mode is `always`; bounded product-domain implementation is assigned
  to the configured personal named worker `luna_max`. The orchestrator owns
  central configuration, dependency integration, review, and final validation.
- Nabu access was verified against the scoped `projects/allies` tree.
- Baseline repository validation could not run because `make` and `uv` are not
  installed on the current host; direct Python lacks Django and Ruff.
- Planning artifacts were present as untracked worktree files at execution
  start and are preserved as task-owned changes.
- Product-domain implementation completed through the configured `luna_max`
  worker; central settings, API registration, dependencies, CI, and operational
  documentation were integrated by the orchestrator.
- Iterative independent pre-PR review findings were all accepted and fixed,
  including production configuration enforcement, link/session races, avatar
  ownership/promotion/cleanup races, stable trusted-proxy throttles, Google
  issuer/audience binding, storage-outage normalization, and PostgreSQL evidence.
- Final local evidence: 69 tests passed and the five PostgreSQL-only race tests
  skipped on SQLite; production-domain coverage is 91.72%; Django checks,
  migration drift/state checks, Ruff lint/format, locked dependency resolution,
  production deployment checks, and dependency vulnerability audit pass.
- The PostgreSQL CI service lane is the release evidence for same-subject
  bootstrap, same-refresh-token rotation/reuse, and same-callback-state races.
  It also covers avatar completion versus cleanup and same-avatar completion
  idempotency. Docker was unavailable locally, so those five marked cases
  intentionally run only in CI.
