# Public Terms and Privacy Pages

## Outcome

Add ordinary public Terms of Service and Privacy Policy pages for the young
Allies product so visitors and the Google OAuth consent screen have stable,
readable links:

- `https://yourallies.io/privacy`
- `https://yourallies.io/terms`

This is a small web-only change. It does not add or change OAuth runtime code,
Cloud APIs, credentials, secrets, mobile behavior, or the production fastlane.

## Scope

- Add static server-rendered `/privacy` and `/terms` App Router pages.
- Use straightforward product-template language for the current Allies preview,
  waitlist, account sign-in boundary, analytics, AI assistance, and third-party
  services.
- Add a visible semantic homepage nav with exact Privacy and Terms links.
- Reuse the existing Open Runde font and simple Allies visual language.
- Add focused route/metadata tests and preserve existing onboarding behavior.

Out of scope:

- New OAuth implementation, Google Console changes, Cloud/mobile changes,
  credentials, secrets, or fastlane workflow changes.
- Account deletion/export, billing, teams, integrations, or other unshipped
  features.
- Custom legal approval systems, copy hashing, verification manifests, or a
  production browser-verification framework.

## Copy Guardrails

- Identify the product as Allies; do not invent a separate corporate entity or
  jurisdiction.
- Describe only behavior visible in the current product and repository:
  waitlist participation, the public preview, Google sign-in/account identity,
  browser session operation, and product analytics at a high level.
- Do not claim exact Google scopes, retention periods, consent behavior, or
  provider guarantees that are not established.
- Use `inbox@yourallies.io` as the current public contact address; the owner
  must verify that mailbox before using the pages as final OAuth evidence.
- Mark the page date clearly and update it when the copy materially changes.

## Implementation

1. Create `apps/web/app/privacy/page.tsx` and
   `apps/web/app/terms/page.tsx` as public server components with route
   metadata and semantic headings.
2. Use one small shared `LegalPage` presentation only where it removes
   duplicated markup; keep the route copy readable in the route files.
3. Render one fixed homepage `<nav aria-label="Legal">` outside the desktop and
   mobile artwork shells so it is present before onboarding interaction. Keep
   the two exact links keyboard accessible and reserve enough mobile width so
   they do not cover the existing Skip control.
4. Add focused static-render tests for titles, canonicals, required sections,
   dates, contact text, and unshipped-feature exclusions.

## Validation

Focused checks:

```text
bun run test:run -- apps/web/app/legal-pages.test.tsx
bun --filter web typecheck
bun run lint:web
bun run build:web
```

Also run the repository test suite and root typecheck before handoff. Confirm
locally that anonymous requests to `/`, `/privacy`, and `/terms` return HTML,
and that the homepage contains both legal links. Existing lint warnings are
reported but do not block this change when no new warnings are introduced.

## Delivery

- Source branch: `web/prod/oauth-terms-privacy`, based on the current production
  baseline.
- Keep `prod-fastlane` synchronized with the current `prod` baseline, then open
  the feature PR with base `prod-fastlane`.
- Do not merge the feature PR or push directly to `prod` without separate user
  approval.
- After the feature PR is merged, manually run **Promote Prod Fastlane → Prod**
  with an explicit release version. That workflow validates the exact
  `prod-fastlane` SHA, merges it into `prod`, tags the release, and opens the
  back-merge PR into `dev`.
- Before OAuth submission, the owner verifies the contact address, domain
  ownership, app branding, exact consent-screen URLs, and final legal copy.

## Risks

- The contact mailbox or product-template wording may need owner/legal review
  before the OAuth client is submitted.
- Google OAuth publication still depends on Google Console configuration and
  review; this PR only supplies the public web pages.
- The homepage uses responsive absolute-positioned artwork, so the legal nav
  must remain outside those shells and be checked at mobile and desktop sizes.

## Review Record

- Planning mode: fast path.
- The initial plan was simplified after review to match the user's explicit
  request for standard pages and avoid unnecessary custom infrastructure.
- No implementation change should expand beyond the files and checks above
  without a new scope decision.
