# INT-007 Web Google auth and personal account

## Status

- Type: feature
- Implementation delegation: always
- Delegation source: kickoff workflow fallback
- Planning worker: `sol_planning_worker`
- Planning worker source: `.agent/kickoff.yaml`
- Review worker: `sol_review_worker`
- Review worker source: `.agent/kickoff.yaml`
- Implementation worker: `luna_execution_worker`
- Implementation worker source: `.agent/kickoff.yaml`
- Planning mode: full
- Worktree manager: Forest
- Branch: `web/feat/int-007-google-auth-account`
- Worktree path: `E:\Users\Oluwatimilehin\Documents\Programming\helpers\allies-interface\.forest\worktrees\web\feat\int-007-google-auth-account`
- Task workspace: `E:\Users\Oluwatimilehin\Documents\Programming\helpers\allies-interface\.forest\worktrees\web\feat\int-007-google-auth-account\docs\plans`
- Created: 2026-08-21
- Target date: not specified
- Current phase: PR #12 open against `dev`; checks and reviews are being monitored

## Objective

Implement the accepted INT-007 web slice so a person can sign in with Google, restore and end a Cloud-owned session, edit their display name and avatar, and view their owner-only personal Workspace in the Next.js client.

## Context

INT-007 is accepted in Nabu and depends on the shipped INT-006 Interface foundation plus AUTH-001. The feature consumes Cloud's cookie-backed browser contract. The browser must include credentials without reading or persisting HttpOnly authentication values. The implementation is limited to `allies-interface`; missing or incompatible Cloud behavior is reported as a contract defect rather than patched in the client.

## Requirements

- Show Google as the only visible sign-in provider.
- Initiate sign-in through Cloud with a validated safe root-relative return path and restore the account through `/api/v1/auths/me` after the browser returns.
- Model signed-out, restoring, signed-in, unavailable, unauthorized, retry, and logout states truthfully.
- Satisfy the cross-origin Cloud CSRF contract through a validated in-memory header owner, and give each operation at most two total invocations across auth and CSRF recovery.
- Add the protected account experience for display-name editing, personal Workspace context, and the complete avatar prepare/upload/complete/read/delete lifecycle.
- Keep Cloud account data in TanStack Query, interaction state locally, and credentials out of Zustand, storage, logs, and rendered errors.
- Preserve input on recoverable failures and cover keyboard, focus, semantic labels, status announcements, responsive behavior, and reduced motion.
- Reuse the existing Interface foundation and installed dependencies; do not add speculative state or transport abstractions.

## Acceptance Criteria

1. Google is the only sign-in provider shown.
2. No password, provider token, JWT, refresh value, object credential, raw provider claim, or raw Cloud error body enters client storage, logs, or UI output.
3. Session restoration distinguishes restoring, signed out, signed in, and unavailable states.
4. Unsafe requests use the validated in-memory Cloud CSRF header without reading Interface cookies. Each operation has at most two invocations across auth and CSRF recovery.
5. Profile edits and avatar completion update or invalidate the current-account query without copying account DTOs into Zustand.
6. Workspace context uses Cloud-authoritative identifiers, role, and capabilities.
7. Avatar UI does not claim completion until Cloud verifies the upload; object-storage requests use only the returned URL and exact headers without Cloud cookies.
8. Keyboard operation, visible focus, announcements, labels, responsive layout, and reduced motion are verified.
9. Focused Vitest/component and contract checks pass with typecheck, lint, and the web production build.
10. Live Google sign-in proof is recorded when the trusted-origin callback correction and staging provider/origin configuration are available; otherwise the exact external blocker is documented without weakening fixture-backed acceptance.

## Evidence And Sources

- Nabu `projects/allies/index.md`, revision `ed0914c934877645ac8d28818638013cfca9c0a8bc4bf1907d1c52ad98dae3cf`.
- Nabu `projects/allies/engineering/specs/interface/INT-007-web-google-auth-and-account.md`, accepted revision `f4478a0ec56dc9ca97409f62d98a3df45f551e9d6eace6bee0c55f384f61b36f`.
- Nabu INT-006, AUTH-001, Interface roadmap, and first product requirements read through the authenticated by-path API on 2026-08-21.
- Repository `AGENTS.md`, `ENGINEERING_STYLE.md`, `docs/templates/PLAN_TEMPLATE.md`, `.agent/kickoff.yaml`, and `.agent/napkin.md`.
- GitHub Cloud PR #13 merged on 2026-08-21 at 20:30:04 UTC with all four checks passing.
- Repository code, package scripts, CI, test setup, installed Next.js 16.2.12 documentation, current UI tokens/screens, pinned/generated Cloud schema, and the matching Cloud implementation boundaries were inspected on 2026-08-21.
- The current Cloud implementation confirms dotted owner capabilities but the pinned OpenAPI examples still show `workspace:manage`. The same implementation returns `Content-Length` among the exact presigned PUT headers, which requires a real-browser staging verification because Fetch controls that header.

## Decisions

- Use full planning because authentication, CSRF, redirects, direct uploads, session concurrency, accessibility, and live-environment proof create material security and failure-state risk.
- Use Forest with branch `web/feat/int-007-google-auth-account` from `dev`.
- Keep implementation delegation at the kickoff default `always` and use the repository's configured workers.
- Treat Ponytail's full mode as the simplicity constraint: reuse the existing foundation and add only code that directly satisfies INT-007 or its demonstrated risks.
- Treat live callback proof as externally blocked until Cloud PR #13's trusted-origin correction reaches staging and provider/origin configuration is verified; fixture-backed client work and validation may proceed.
- Treat the installed kickoff skill version 0.3.0 as current at the user's direction after the canonical remote frontmatter omitted a parseable version.

## Risks

- Cloud trusted-origin, cookie, CSRF, provider, CORS, or callback deployment configuration may block live proof even when the client implementation is correct.
- Session refresh and stale request handling can create loops or cross-request races if they bypass the existing transport boundary.
- Direct avatar upload can leak credentials or show false success if the returned object-storage contract is not followed exactly.
- The account UI may duplicate Cloud truth or hide permission failures unless mapping and query ownership remain narrow.
- Forest doctor reports three stale missing worktree records outside this task; they are left untouched.
- Forest could not reuse `.env` or `.env.local`; live validation may require secure environment setup later.

## Open Questions

- When will Cloud PR #13's trusted-origin correction reach staging, and are the final Interface origin and Google redirect URI configured there?
- Will Cloud publish a browser-compatible presigned avatar header set and matching R2 CORS behavior if staging confirms that the returned `Content-Length` header cannot be set by Fetch?
- When will the stale Workspace capability examples in the pinned OpenAPI be corrected to the implemented dotted capability set?

## Plan

- Durable plan: `docs/plans/int-007-web-google-auth-account.md`.
- Editable review artifact: `.lavish/int-007-web-google-auth-account.html`.
- Accepted read-only archive: `docs/plans/int-007-web-google-auth-account.html`.
- Better-docs review surface: `.lavish/int-007-web-google-auth-account-better-docs-comparison.html`, backed by the preserved first draft and clean copy.
- The plan uses `docs/templates/PLAN_TEMPLATE.md` as its exact spine, keeps kickoff/review history after the required sections, and preserves Markdown/HTML parity through a source-hash-stamped renderer.

## Execution Notes

- Kickoff dependencies and worker selectors validated on 2026-08-21.
- Forest worktree created and marked `working`.
- The locked dependency install succeeded, but the planning workstation resolves Bun 1.3.14 while the repository and CI pin Bun 1.2.20. Final implementation validation must use the pinned version.
- The full plan, better-docs comparison, humanized clean Markdown, and Allies-styled Lavish artifact were produced without product implementation changes.
- Lavish browser layout audit found one unreachable narrow-viewport skip link; the artifact now uses a reachable visible skip link and the follow-up audit reported no fresh layout warning during the one-minute observation window.
- Adversarial review verdict: `Blocked`. Durable review: `docs/plans/int-007-web-google-auth-account.adversarial.md`.
- Accepted Blocker: define an in-memory cross-origin CSRF token owner, capture the validated `X-CSRFToken` response header, inject it into every unsafe request, rotate it after bootstrap, and test replacement after `csrf_rejected` without relying on Interface-origin cookies.
- Accepted Major: define one operation-wide replay budget of two total operation invocations; the first eligible auth or CSRF failure consumes the sole replay, and any eligible replay failure is surfaced without a third invocation. Add ordered compound-failure and concurrency tests.
- Accepted Major: add an explicit bounded timeout for the direct object-store PUT, combine it with caller cancellation, clean up timer/listener resources, distinguish recoverable timeout from caller cancellation, and test stalled-fetch and abort/timeout races.
- Accepted Major: proactively renew signed avatar read metadata before expiry while `/account` remains mounted, cancel and reschedule renewal as metadata changes, and cover expiry and renewal failure with fake-clock tests.
- Accepted Major: restore the accepted Zod display-name schema using the installed dependency and retain focused normalization and boundary tests.
- Accepted Minor: refresh the Nabu revisions and Cloud PR #13 status while preserving staging deployment/configuration as the remaining external release gate.
- The revised plan integrates every accepted finding, preserves the template spine and existing implementation boundaries, and records exact unit, concurrency, fake-clock, timeout-race, staging, and release-gate validation.
- Better-docs and humanizer passes were rerun after the contract revision. The comparison keeps the pre-edit revision and better-docs clean copy; the main Markdown is the final humanized plan.
- Simplicity review verdict: `Simplification recommended`. Durable review: `docs/plans/int-007-web-google-auth-account.simplicity.md`.
- Accepted Simplify: remove provider-wide `restoreOnMount` and its initialization/effect branches; protected auth entry routes explicitly call `restore()` once while public routes remain request-free. Preserve cache ownership and logout race protection.
- Accepted Remove/Defer: remove the unrequired local avatar preview object URL and cleanup lifecycle. Preserve the selected `File` for retry, show safe filename/status feedback if useful, and keep the prior Cloud-confirmed avatar visible until completion succeeds.
- Protected complexity: retain the in-memory CSRF owner and bounded replay state machine, direct-upload timeout/cancellation cleanup, proactive signed-avatar renewal, and real-browser exact-header/CORS release probe.
- The final revision removes the provider mount-restore branches and preview lifecycle from contracts, phases, state notes, and tests. It adds exact protected-entry restoration/no-flash coverage while retaining targeted Query writes/removal and logout generation handling.
- Better-docs and humanizer were rerun after the simplicity revision, and the source-hash-stamped Lavish artifact was regenerated from the final Markdown.
- The user approved the fully reviewed plan on 2026-08-21. The editable Lavish and editing-comparison sessions were ended, and the accepted self-contained read-only archive was exported to `docs/plans/int-007-web-google-auth-account.html` with no unresolved local assets.
- Ship-it Task A was accepted at commit `713d95ca`: validated in-memory CSRF ownership, strict return paths, bounded auth/CSRF replay, Query-owned account state, explicit restoration, and logout race protection. The orchestrator reran all 129 tests and the full workspace typecheck successfully on 2026-08-22.
- Ship-it Task B was accepted at commit `08ae790`: Zod display-name validation plus bounded, credential-free avatar hashing/upload orchestration. The existing Task A query layer already owns proactive signed-avatar renewal. The orchestrator reran all 142 tests and the full workspace typecheck successfully.
- Ship-it Task C was accepted at commit `c2e17d0`: Google-only sign-in, return handling, protected account editing, avatar lifecycle controls, and responsive accessible route states. Integrated validation passed 156 tests, the full workspace typecheck, lint with only eight pre-existing onboarding warnings, and the Next.js production build.
- Browser validation on 2026-08-22 covered `/sign-in`, `/auth/return`, and `/account` at the default viewport and 320 px. The routes had semantic headings, regions, status/alert announcements, no horizontal overflow, a truthful unauthenticated fallback, and no browser console errors. Live provider/cookie/CORS proof remains an external staging gate.
- `bun run cloud:check` still reports the pre-existing pinned-schema metadata mismatch: the schema file is unchanged while its metadata records stale size and SHA values. This feature does not rewrite that generated contract metadata.
- Ponytail review found one simplification: `account-client.tsx` repeated Query invalidation and authoritative cache writes after successful profile/avatar mutations. Commit `d894962` keeps the Cloud response as the single cache update, removes the duplicate refetch/rewrite cycles, and reduces that path by 22 net lines.
- Revalidation after the browser run exposed two helpers exported from Next.js page modules, which violates App Router page-export constraints once `.next/dev` types exist. Commit `d894962` moves return-path and callback-error parsing to `lib/session/auth-route-query.ts`; focused tests, all 156 tests, full typecheck, lint, and production build pass afterward.
- Independent pre-PR code review found three issues and all were fixed in commit `d320907`: terminal replayed `401` responses now invalidate concurrent session work, clear private queries, and transition generation-safely to signed out; shared CSRF renewal no longer inherits the first caller's cancellation; and nullable avatar-completion responses now reconcile the authoritative account/avatar queries before success is shown.
- Regression coverage now includes concurrent CSRF cancellation, terminal-unauthorized invalidation, SessionProvider private-cache cleanup, and first/replacement avatar uploads whose completion response has no URL. The independent re-review reported no remaining actionable findings. After integrating the latest `dev`, the final local suite is 265 tests, with full typecheck, production build, and lint passing; lint retains only the eight pre-existing onboarding warnings.
- Latest `dev` integration retained both shared Cloud exports (`parseSafeReturnPath` and `createNativeAuthClient`) and passed the complete web/mobile/Cloud validation matrix. The canonical Git OpenAPI blob matches its metadata exactly; only the Windows CRLF working-tree byte check remains inapplicable locally.
- Pull request #12 was opened against `dev` on 2026-08-22: `https://github.com/Timmyy3000/allies-interface/pull/12`. A five-minute review monitor is active; merging still requires explicit user approval.
- Enkii's completed review found two P2 issues: pre-aborted direct avatar PUT entry could reject an unconsumed internal promise, and `apps/web` used Zod without declaring ownership. Both were fixed with an early abort guard plus regression test and a direct `zod` dependency/lockfile entry. The post-fix matrix passes 266 tests, full typecheck, lint, and the web production build.
