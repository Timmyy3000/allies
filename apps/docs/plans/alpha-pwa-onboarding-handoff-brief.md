# Alpha PWA and onboarding handoff brief

## Objective

Deliver AT-032, AT-033, and AT-039 as one focused web PR against `dev`.

## Acceptance

- PWA logout returns to the verified `/app` surface and never flashes authenticated content after sign-out.
- `/app` follows the same selected light/dark theme contract as the rest of the application.
- A signed-in Ally creation flows from first message through the user's first reply into the final chat without exposing the roster/list in between.
- Draft, queued-send, Ally identity, and idempotency semantics remain intact.
- Focused regression tests and the requested web validation pass at the final head.

## Boundaries

- Branch: `web/fix/pwa-onboarding-handoff`
- Base: `origin/dev`
- Delivery: pull request; do not merge.
- Deferred/out of scope: AT-031, PR 1 styling, PR 3 approval/backend work, and inline file previews.
- Nabu is read-only unless implementation evidence requires reconciling an accepted decision.

## Route

Fast. The changes are bounded to the web client, but AT-039 crosses creation, queue, identity, and conversation presentation state and therefore needs a short durable plan plus independent adversarial review.

## Implementation mode

Ponytail full: trace the real flow, then take the first adequate rung—reuse existing helpers and platform/CSS behavior, add no dependency or speculative abstraction, keep the root-cause diff and meaningful regression checks as small as possible, and preserve accessibility, validation, error handling, security, and durable-state behavior.

Do not manufacture a change. If exact flow and tests prove the accepted behavior already exists, record evidence and close as a no-op without an empty PR. If a gap remains, implement only the smallest root-cause diff and one focused regression check.
