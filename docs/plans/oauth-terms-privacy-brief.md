# Public Terms and Privacy Pages for OAuth Publication

## Status

- Type: feature
- Implementation delegation: always
- Delegation source: kickoff fallback default; user did not opt out of subagents
- Planning worker: sol_planning_worker
- Planning worker source: repository `.agent/kickoff.yaml`
- Review worker: sol_review_worker
- Review worker source: repository `.agent/kickoff.yaml`
- Implementation worker: luna_execution_worker
- Implementation worker source: repository `.agent/kickoff.yaml`
- Planning mode: fast
- Worktree manager: Forest
- Branch: `web/prod/oauth-terms-privacy`
- Worktree path: `.forest/worktrees/web/prod/oauth-terms-privacy`
- Task workspace: `.agent/oauth-terms-privacy`
- Created: 2026-09-02
- Target date: 2026-09-02, subject to legal contact details and production checks
- Current phase: PR open, CI/review monitoring

## Objective

Publish public, product-specific Terms of Service and Privacy Policy pages on
the production web origin so the Allies Google OAuth client can satisfy its
production branding and consent-screen publication requirements.

## Context

The production branch is `prod` and currently serves the public waitlist and
Ally preview without `/terms` or `/privacy` routes or homepage legal links.
The repository also contains a separate `prod-fastlane` release branch and a
manual promotion workflow. The release path is a feature PR into
`prod-fastlane`, followed by **Promote Prod Fastlane → Prod**, which validates
the exact fastlane SHA, merges it into `prod`, tags the release, and opens a
back-merge PR into `dev`. The initial direct-to-`prod` interpretation was
corrected after the user clarified the intended fast-lane flow.

Google's current official guidance requires production app-domain links for
the homepage, privacy policy, and terms of service; the homepage must be
public, describe the app, and link to the same privacy policy configured in the
OAuth consent screen. The privacy policy must be a dedicated HTML page on a
verified domain and disclose how Google user data is accessed, used, stored,
and shared.

The current Allies auth contract describes Google sign-in as receiving the
minimum account identity data needed to establish an Allies account and
session. The production branch does not introduce the OAuth runtime or Cloud
contract in this change.

The kickoff package reported a version mismatch before this run (`0.3.0`
installed vs `0.4.0` available). The user explicitly instructed the workflow
to continue after the coordinated Skills CLI update returned success, so this
run records that exception and proceeds with the verified repository worker
configuration.

## Requirements

- Add a publicly accessible, server-rendered `/privacy` page with product-
  specific privacy disclosures for the current public preview/waitlist and
  Google sign-in data practices described by the accepted Allies auth contract.
- Add a publicly accessible, server-rendered `/terms` page describing the
  current Allies service, account and waitlist use, user responsibilities,
  third-party services, AI-output limitations, suspension, changes, and
  contact path without claiming features that are not shipped on `prod`.
- Link both pages from the public homepage in a visible, keyboard-accessible
  location that does not require sign-in or opening a private route.
- Use stable production paths `https://yourallies.io/privacy` and
  `https://yourallies.io/terms` as the OAuth consent-screen URLs.
- Keep legal copy readable, responsive, semantically structured, and free of
  secrets, private deployment details, fabricated provider scopes, or raw
  customer data.
- Add focused route/metadata/link coverage and run the repository's relevant
  typecheck, tests, lint, and web build checks.
- Do not change Cloud, OAuth credentials, redirect configuration, provider
  scopes, production secrets, or the fastlane promotion workflow.

## Acceptance Criteria

1. `GET /privacy` and `GET /terms` render successful dedicated HTML pages from
   the production web app without authentication.
2. Each page identifies Allies, has a clear title and effective/last-updated
   date, uses headings and navigable links, and exposes a verified contact
   method once the owner-approved address is known.
3. The privacy page specifically explains Google account data used for sign-in,
   waitlist data, cookies/session behavior, analytics where applicable,
   storage/retention, sharing boundaries, user choices, and change notices.
4. The homepage visibly links to `/privacy` and `/terms`; the privacy URL is
   the exact path intended for the Google OAuth consent screen.
5. The terms page covers the current service and does not promise account
   deletion, export, billing, team features, or other unshipped capabilities.
6. Focused tests cover route rendering/metadata and the homepage legal links;
   repository validation passes for the changed web surface.
7. The PR is created from `web/prod/oauth-terms-privacy` with base
   `prod-fastlane`; promotion into `prod` occurs only through the manual
   fastlane workflow with an explicit release version.

## Evidence And Sources

- Nabu `projects/allies/index.md` — canonical Allies knowledge map and current
  focus.
- Nabu `projects/allies/delivery/now.md` — production and account-access
  delivery state.
- Nabu `projects/allies/engineering/specs/interface/INT-007-web-google-auth-and-account.md` —
  accepted Google account data and web boundary.
- Nabu `projects/allies/engineering/specs/auth-account-foundation.md` —
  Cloud-owned identity/session data and explicit out-of-scope controls.
- `ENGINEERING_STYLE.md`, `AGENTS.md`, `apps/web/AGENTS.md`,
  `docs/templates/PLAN_TEMPLATE.md` — repository policy and validation.
- `.github/workflows/ci.yml` — CI commands and production-target branch list.
- `.github/workflows/promote-prod-fastlane-prod.yml` — validates
  `prod-fastlane`, promotes its exact SHA into `prod`, tags the release, and
  opens the back-merge PR into `dev`.
- Google official verification guidance:
  `https://support.google.com/cloud/answer/13464321?hl=en`,
  `https://support.google.com/cloud/answer/15549049?hl=en`, and
  `https://developers.google.com/identity/protocols/oauth2/production-readiness/brand-verification`.

## Decisions

- Target repository: `allies-interface`.
- Target platform: production web only; mobile and Cloud are out of scope.
- Production baseline: `prod`.
- PR target: `prod-fastlane`.
- Stable legal routes: `/privacy` and `/terms`.
- Planning mode: fast, inferred from the user's “prod fast lane” instruction;
  independent adversarial and simplicity reviews remain required.
- Implementation delegation: `always`, using the repository's configured
  Luna worker.
- Keep the homepage product story intact and add the smallest visible legal
  navigation surface needed for discovery and OAuth verification.
- User update: use straightforward standard early-stage product Terms and
  Privacy copy based on the currently shipped Allies waitlist/preview and
  Google sign-in boundary; avoid custom legal infrastructure or elaborate
  approval machinery. Treat the copy as product-template content for owner
  review before final OAuth submission.

## Risks

- Legal copy could state inaccurate company identity, contact details,
  jurisdiction, retention periods, analytics behavior, or OAuth scopes.
- The production branch intentionally predates the web OAuth runtime, so the
  policy must describe only verified/current behavior and clearly bounded
  future sign-in handling.
- A homepage link hidden inside an onboarding interaction could fail Google's
  public discoverability requirement.
- Direct-to-prod review has a smaller environment-validation window than the
  normal dev → staging → prod path.

## Open Questions

- What owner-approved legal entity name, privacy/support email, and governing
  jurisdiction should appear in the final Terms and Privacy pages?
- Which exact Google OAuth scopes are in the production client, and do they
  require additional limited-use disclosure beyond basic sign-in?
- Is PostHog or any other analytics active on the production branch/origin, and
  should its data handling be named in the published policy?

## Plan

The planning worker will produce the concise fast-path Markdown plan in
`docs/plans/oauth-terms-privacy.md`, following the repository template where
applicable, and will identify the smallest route, homepage-link, copy, and
focused-test changes. The plan must preserve the open legal-authority
questions and make any production-readiness blocker explicit.

## Execution Notes

- The worktree is isolated and Forest-managed.
- The current worktree starts clean from `prod`.
- `.agent/kickoff.yaml` is ignored by repository policy and is present in the
  task worktree for worker dispatch; it must not be committed.
- Baseline on 2026-09-02: `bun install --frozen-lockfile` completed;
  `bun run typecheck` passed; `bun run test:run` passed with 94 tests in 19
  files; `bun run lint:web` passed with 8 pre-existing warnings and no errors;
  `bun run build:web` passed.
- The configured Sol planning worker produced the fast-path plan at
  `docs/plans/oauth-terms-privacy.md`; no implementation changes have been
  made.
- Planning result: ready with publication gated on owner-approved legal facts,
  exact production Google scopes, and verified production analytics behavior.

## Planning Review Notes

- The plan is intentionally Markdown-only for the fast path; the repository's
  existing HTML-plan convention is not expanded into this narrow legal-page
  change unless the review or implementation requires a synchronized
  presentation.
- The planner preserved the open authority gates and scoped the implementation
  to static public web routes, homepage discovery, route metadata/styles, and
  focused tests.
- Current phase: independent adversarial review.

## Adversarial Review Notes

- Verdict: Needs revision.
- Accepted Major — add an owner-operated post-deployment checklist for the
  exact HTTPS homepage, `/privacy`, and `/terms` URLs, including public 200
  HTML, metadata, links, TLS/redirect/auth behavior, deployment owner, and
  rollback path.
- Accepted Major — supplement component tests with executable anonymous route
  and generated-metadata checks using the repository's browser/HTTP test
  setup, including keyboard and responsive discoverability.
- Accepted Major — reconcile final policy wording with global analytics
  initialization and the actual production tracking/consent behavior, not
  only imports in the legal routes.
- Accepted Major — make legal entity, contact, jurisdiction, dates, retention,
  Google scopes, analytics behavior, and approver explicit traceable inputs;
  final copy/publication remains blocked while any is unknown.
- Accepted Major — narrow the outcome to OAuth-submission readiness and add
  the owner-operated Google Console/domain-verification checklist.
- Accepted Major — specify stable semantic homepage legal navigation and test
  initial/public visibility at relevant responsive boundaries.
- Accepted Minor — either provide the repository-required synchronized HTML
  plan presentation or record a scoped fast-path exception with owner,
  rationale, mitigation, and revisit condition.
- Accepted Question — the user explicitly resolved the PR ambiguity by asking
  for the direct-to-`prod` PR; the revised plan must include PR creation while
  retaining no-merge/no-direct-push safeguards.
- Accepted Minor — distinguish risk-targeted web checks from full CI-parity
  checks required before PR handoff; retain the latter where the PR workflow
  requires them, but do not misrepresent them as feature-specific evidence.
- Current phase: revised planning before simplicity review.

## Simplicity Review Notes

- Verdict: Simplification recommended and applied.
- Removed bespoke cryptographic copy hashing, mandatory shared verification
  manifest, duplicated exhaustive analytics-option assertions, malformed-origin
  test matrix, mandatory remote browser proof, and local duplication of
  Cloud/mobile CI commands.
- Preserved the legal-facts/analytics approval gate, focused public-route and
  responsive/keyboard checks, lightweight fixed-URL production HTTP proof,
  repository CI as a PR gate, and the `prod-fastlane` promotion boundary.

## Final Review And Handoff

- Final consistency review: no material contradiction found in the simplified
  implementation scope. The remaining owner checks are handoff requirements,
  not implementation blockers.
- The user explicitly simplified the scope to standard product-template pages.
  Implementation may proceed with Allies as the product identity, the current
  waitlist/preview behavior, and a website contact path; legal owner review
  remains required before treating the copy as final OAuth approval evidence.
- The Markdown-only exception is accepted for this fast path by the user's
  explicit request to keep the work simple; no HTML companion will be added.

## Implementation Notes

- Implemented and committed as `9c065d0` on
  `web/prod/oauth-terms-privacy`; PR #19 targets `prod-fastlane`.
- On 2026-09-03, `prod-fastlane` was safely fast-forwarded from its stale
  ancestor to the current `prod` SHA (`24076c8`) before PR #19 was retargeted.
- Follow-up commits aligned the simplified plan and presentation (`c7ae0ee`),
  kept legal links out of modal focus (`e060fa0`), updated the owner-supplied
  contact address (`dd18f15`), and corrected the fastlane path (`37a3912`).
- The implementation uses standard product-template copy and adds no custom
  verifier, approval hash, or analytics infrastructure.
- Contact copy uses the owner-supplied `inbox@yourallies.io` address; mailbox
  delivery should still be verified before OAuth submission.
- Focused and full local validation passed; PR #19 is open against
  `prod-fastlane` while CI and review rerun. No merge or direct push to `prod`
  was performed.
