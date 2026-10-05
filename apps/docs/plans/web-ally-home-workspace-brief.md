# Web Ally Home Workspace

## Status

- Type: feature
- Implementation delegation: always
- Delegation source: repository `kickoff.yaml`
- Planning worker: `sol_planning_worker`
- Planning worker source: repository `kickoff.yaml`
- Review worker: `sol_review_worker`
- Review worker source: repository `kickoff.yaml`
- Implementation worker: `luna_execution_worker`
- Implementation worker source: repository `kickoff.yaml`
- Planning mode: full, planning stage only
- Worktree manager: Forest
- Branch: `web/feat/int-007-google-auth-account`
- Worktree path: `E:\Users\Oluwatimilehin\Documents\Programming\helpers\allies-interface\.forest\worktrees\web\feat\int-007-google-auth-account`
- Task workspace: `docs/plans/`
- Created: 2026-08-28
- Target date: not specified
- Current phase: planning

## Objective

Create the first authenticated Allies product workspace at `/home`: a calm, character-led Ally switcher and conversation surface that uses real account data, preserves the established onboarding design language, and gives an empty account a clear path to meet its first Ally.

## Context

The user has completed a local Google sign-in test against the local Cloud Docker stack. The current `/account` route is a debugging surface, not the intended product destination. The requested `/home` experience takes structural inspiration from a two-pane agent chat application without copying its dark visual identity or generic SaaS patterns.

Canonical product direction says Home is the default signed-in surface, each Ally has one continuous conversation, the Ally switcher shows identity and Job, and onboarding remains the entry point for creating an Ally. The accepted responsive onboarding pattern is a right-side drawer on desktop and the `/onboarding` route on mobile.

Repository evidence shows Cloud already supports authenticated Ally creation and retrieval, cursor-paginated conversation reads, idempotent message acceptance, and bounded activity snapshots containing `assistant_delta` records and execution state. Cloud does not expose a collection endpoint for the current workspace's Allies. The Interface generated client does not yet include the Ally, conversation, message, or activity endpoints.

## Requirements

1. `/home` is the default destination after successful sign-in and requires a valid session.
2. Desktop uses a full-height two-pane workspace: a compact Ally rail and a flexible conversation pane.
3. The visual system reuses the current onboarding typography, orange, Ally characters, rounded geometry, whitespace, and restrained motion. It must not resemble a generic generated dashboard, glass UI, metric-card grid, or a copy of the supplied dark reference.
4. The Ally rail displays real workspace-scoped Allies with avatar, name, Job, selected state, and a create action. Do not add search until product scale requires it.
5. An account with no Allies sees a generous empty state and the established `Meet your first ally` action.
6. On desktop, that action opens the existing right-side onboarding drawer without changing routes. On mobile, it navigates to `/onboarding`.
7. Successful Ally creation returns to `/home`, refreshes the Ally collection, and selects the newly created Ally without losing the onboarding handoff.
8. Selecting an Ally loads its one continuous conversation, supports older-history pagination, accepts a new text message idempotently, and shows execution progress and assistant output from Cloud's activity projection.
9. The first slice uses bounded polling only while a turn is active. Live streaming/reconnect is not invented in the Interface before the Cloud contract exists.
10. Loading, empty, error, retry, session-expired, provisioning, and reduced-motion states are explicit and truthful. No fake Allies, placeholder conversations presented as real, or optimistic delivery claims.
11. Interface talks only to Cloud's public versioned API through `@allies/cloud-client`.

## Acceptance Criteria

1. A signed-out visit to `/home` redirects to `/sign-in?returnTo=%2Fhome`; successful Google sign-in returns to `/home`.
2. A signed-in empty workspace renders no fabricated Ally rows and shows `Meet your first ally`.
3. The creation action opens the current onboarding drawer at desktop width and `/onboarding` at mobile width.
4. Completing signed-in onboarding creates the Ally through Cloud, refreshes the list, and opens its persisted onboarding conversation.
5. A workspace with Allies renders only authorized Allies in a deterministic order and selection survives reload through the route.
6. Conversation history renders the persisted onboarding exchange and later messages, loads older pages without duplicates, and preserves order.
7. Sending text uses a stable per-intent idempotency key, visibly distinguishes accepted/working/completed/failed states, and never claims a response before Cloud supplies it.
8. While an execution is active, bounded polling assembles `assistant_delta` activity in sequence and stops on a terminal state, route change, or unmount.
9. Desktop and mobile layouts are keyboard usable, focus-visible, responsive, reduced-motion safe, and visually consistent with onboarding.
10. Cloud tenant-isolation tests prove list results cannot cross Workspace boundaries; generated OpenAPI/client contract checks and focused Interface tests pass.

## Evidence And Sources

- User-provided split chat screenshot, used for layout inspiration only.
- `apps/web/app/(onboarding)/_components/index.tsx` and `onboarding-drawer.tsx` for the established responsive shell and `Meet your first ally` action.
- `apps/web/components/ally-avatar.tsx` and onboarding assets for Ally identity.
- `packages/cloud-client` for the sole Interface-to-Cloud boundary.
- Cloud `backend/allies/api/controllers.py` and `backend/allies/services/creation.py` for create/retrieve behavior.
- Cloud `backend/chat/api/controllers.py`, schemas, and services for cursor history and idempotent send.
- Cloud `backend/activities/api/register.py` and projection models/services for bounded assistant deltas and execution state.
- Nabu `projects/allies/product/allies-prd-response.md`.
- Nabu `projects/allies/engineering/specs/cld-004-conversation-and-message-lifecycle.md`.
- Nabu `projects/allies/engineering/specs/cld-005-foundry-gateway-and-activity-projection.md`.
- Nabu `projects/allies/engineering/specs/waitlist/INT-009-frontend-handoff.md`.

## Decisions

- This turn covers planning only. Implementation, review, PR creation, and monitoring are paused until the user explicitly advances the workflow.
- Use a URL-addressable selected Ally so reload, deep linking, browser back, and mobile navigation are predictable.
- Keep the first home slice focused on Ally switching and conversation. Do not add search, global attention dashboards, voice, approvals, Results, Routines, settings, stop/retry, or speculative abstractions.
- Add one Cloud collection endpoint rather than fabricating a list from known IDs or issuing per-Ally requests.
- Use current activity snapshots with bounded active-turn polling as the temporary transport; do not mislabel it as streaming.
- Reuse and, where necessary, extract existing onboarding primitives instead of duplicating their appearance.

## Risks

- The current Interface branch is an in-progress INT-007 worktree with local uncommitted design/test changes. Planning must preserve them and implementation must keep the eventual diff reviewable.
- Cloud and Interface changes require coordinated contract sequencing: Cloud endpoint and OpenAPI first, generated client second, UI third.
- Activity snapshots are bounded and are not a replay stream. Polling must stop deterministically and must not claim reconnect guarantees.
- Provisioning can be pending, retryable, failed, or repair-required; the UI must not assume every newly created Ally is immediately chat-ready.

## Open Questions

- None blocking for the plan. Exact visual measurements should be resolved through implementation screenshots against the established onboarding page rather than invented in prose.

## Plan

To be produced by the configured planning worker as `docs/plans/web-ally-home-workspace.md` and an Allies-styled Lavish artifact, then reviewed by the user before any shipping step.

## Execution Notes

- Backend capability audit completed on 2026-08-28.
- Kickoff version preflight: installed `0.3.0`; canonical `0.3.0`.
