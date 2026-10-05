# Web onboarding handoff and theme

Route: fast. Continue PR 29 at the user's request; no HTML needed.

## Scope and approach
- Replace the landing preview's waitlist attempt with the existing anonymous onboarding API. Keep waitlist consumers unchanged.
- Let the guest write a first reply, then save the exact attempt, configuration, reply, and idempotency key before Google sign-in.
- After session restoration, bind that command to the authenticated account/workspace, create once, and open `/home/<allyId>`. Keep failed commands for explicit retry; never silently regenerate an expired preview or invent a reply.
- Apply existing semantic theme tokens to landing/onboarding surfaces, typography, controls, and auth screens while preserving artwork and shell colours.

## Acceptance and validation
Same name, appearance, greeting attempt, and first reply survive the redirect. Retries use the same command/key; another account cannot claim a command already bound to an account. No generic Home redirect before successful creation. Legacy incomplete resumes show recovery.

Run focused Vitest onboarding/auth tests, `bun --filter web typecheck`, and `bun run lint:web`. Inspect landing and onboarding in light/dark at desktop/mobile widths; use mocked auth/API tests without signing the user out or sending test messages to their real account.

## Risks and review
Session storage must be available before leaving for OAuth. An expired attempt requires explicit recovery, not replacing the greeting. Backend owns authorization, attempt validation, and idempotency. Separate correctness and simplicity passes after implementation. Rollback: revert this focused diff. No backend contract change or unresolved product decision.

## Verification record
- Implemented the claimable anonymous attempt with browser CSRF, persistent creation command, account/workspace binding, same-Ally redirect, legacy configuration recovery, and semantic public-page theming.
- Fixed the landing hydration mismatch caused by reading session storage during the initial client render. The creation handoff owns navigation after it starts, including when it clears the stored resume.
- Replaced the old browser tests that simulated success by clicking the nonfunctional ChatGPT button with `guest-handoff.spec.ts`. Both light/mobile and dark/desktop journeys pass through a simulated Google redirect and display the original greeting and first reply in the specific Ally chat. Browser console checks found no hydration error in these runs. No real Google sign-in or authenticated test Ally creation was performed.
- Focused onboarding, auth, handoff, and page tests passed. The broad web run passed 319 tests and exposed one obsolete resume-screen assertion; that assertion was updated and its five-test file passed. Subsequent focused tests also cover legacy setup recovery and clearing resume without a competing generic Home redirect.
- `bun --filter web typecheck` passed. `bun run lint:web` passed with 34 existing warnings and no errors. `git diff --check` passed.
- Correctness review checked account isolation, retained reply/attempt, storage failure before OAuth, idempotent retries, and redirect ownership. Simplicity review reused the Cloud client, existing authenticated preview, and existing theme tokens; no backend changes or dependencies added.
- Nabu product design spec updated with the accepted handoff and public theme behavior. Changes remain local for user review.
